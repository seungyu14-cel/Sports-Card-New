-- Sports Card News · Supabase newsroom schema
-- Supabase SQL Editor에서 한 번 실행하세요.
create extension if not exists pgcrypto;
create extension if not exists vector;

create table if not exists teams (
  team_id text primary key,
  league text not null,
  name text not null,
  short_name text,
  logo_url text,
  metadata jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

create table if not exists players (
  player_id text primary key,
  league text not null,
  team_id text references teams(team_id) on delete set null,
  name text not null,
  position text,
  jersey_number text,
  metadata jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

create table if not exists games (
  game_id text primary key,
  league text not null,
  season integer not null,
  game_date date not null,
  start_at timestamptz,
  home_team_id text references teams(team_id) on delete set null,
  away_team_id text references teams(team_id) on delete set null,
  home_team_name text not null,
  away_team_name text not null,
  home_score integer,
  away_score integer,
  status text not null default '예정',
  venue text,
  winner_team_id text references teams(team_id) on delete set null,
  source_url text,
  verified boolean not null default false,
  metadata jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

create index if not exists games_date_league_idx on games(game_date, league);
create index if not exists games_status_idx on games(status);

create table if not exists player_game_stats (
  id bigint generated always as identity primary key,
  game_id text not null references games(game_id) on delete cascade,
  player_id text not null,
  team_id text,
  stat_type text not null default 'game',
  stats jsonb not null default '{}'::jsonb,
  source_url text,
  verified boolean not null default false,
  updated_at timestamptz not null default now(),
  unique(game_id, player_id, stat_type)
);

create index if not exists player_game_stats_game_idx on player_game_stats(game_id);

create table if not exists raw_sources (
  source_id uuid primary key default gen_random_uuid(),
  source_key text not null unique,
  source_type text not null,
  league text,
  game_id text references games(game_id) on delete set null,
  publisher text,
  url text not null,
  title text,
  content text not null,
  published_at timestamptz,
  scraped_at timestamptz not null default now(),
  expires_at timestamptz,
  checksum text not null,
  verified boolean not null default false,
  source_priority integer not null default 1 check (source_priority between 1 and 5),
  metadata jsonb not null default '{}'::jsonb
);

create index if not exists raw_sources_game_idx on raw_sources(game_id, scraped_at desc);
create index if not exists raw_sources_league_idx on raw_sources(league, scraped_at desc);

create table if not exists knowledge_documents (
  document_id uuid primary key default gen_random_uuid(),
  source_key text not null unique,
  document_type text not null,
  league text,
  game_id text references games(game_id) on delete set null,
  team_id text,
  player_id text,
  title text,
  content text not null,
  source_url text,
  published_at timestamptz,
  expires_at timestamptz,
  verified boolean not null default false,
  source_priority integer not null default 1 check (source_priority between 1 and 5),
  metadata jsonb not null default '{}'::jsonb,
  embedding vector(1536),
  search_tsv tsvector generated always as (
    to_tsvector('simple', coalesce(title, '') || ' ' || coalesce(content, ''))
  ) stored,
  updated_at timestamptz not null default now()
);

create index if not exists knowledge_documents_vector_idx
  on knowledge_documents using hnsw (embedding vector_cosine_ops);
create index if not exists knowledge_documents_search_idx
  on knowledge_documents using gin(search_tsv);
create index if not exists knowledge_documents_game_idx
  on knowledge_documents(game_id, verified, source_priority desc);

create table if not exists news_events (
  event_id uuid primary key default gen_random_uuid(),
  event_key text not null unique,
  game_id text references games(game_id) on delete cascade,
  league text not null,
  event_type text not null,
  rank integer check (rank between 1 and 3),
  headline text not null,
  summary text not null,
  why_it_matters text,
  player_id text,
  team_id text,
  importance_score numeric(5,2) not null default 0,
  confidence_score numeric(4,3) not null default 0,
  source_urls jsonb not null default '[]'::jsonb,
  fact_keys jsonb not null default '[]'::jsonb,
  verified boolean not null default false,
  needs_human_review boolean not null default true,
  occurred_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists news_events_game_rank_idx on news_events(game_id, rank);
create index if not exists news_events_league_created_idx on news_events(league, created_at desc);

create table if not exists game_reports (
  report_id uuid primary key default gen_random_uuid(),
  report_key text not null unique,
  game_id text not null references games(game_id) on delete cascade,
  edition_date date not null,
  payload jsonb not null,
  model text not null,
  input_tokens integer not null default 0,
  output_tokens integer not null default 0,
  web_search_used boolean not null default false,
  missing_fields jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists game_reports_date_idx on game_reports(edition_date, game_id);

create table if not exists card_templates (
  template_id text primary key,
  name text not null,
  sport text not null default 'baseball',
  event_type text not null,
  version integer not null default 1,
  structure jsonb not null,
  writing_rules jsonb not null default '{}'::jsonb,
  active boolean not null default true,
  updated_at timestamptz not null default now()
);

create table if not exists card_news (
  card_id uuid primary key default gen_random_uuid(),
  card_key text not null unique,
  game_id text references games(game_id) on delete set null,
  edition_date date not null,
  league text not null,
  template_id text references card_templates(template_id) on delete set null,
  payload jsonb not null,
  source_event_keys jsonb not null default '[]'::jsonb,
  approval_status text not null default 'pending_human_review',
  performance jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists ingest_logs (
  ingest_id uuid primary key default gen_random_uuid(),
  source_name text not null,
  rows_written integer not null default 0,
  status text not null,
  detail jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

-- verified + not-expired 문서만 반환하는 hybrid RAG 함수.
create or replace function match_knowledge(
  query_embedding vector(1536),
  query_text text,
  match_count integer default 8,
  filter_league text default null,
  filter_game_id text default null
)
returns table (
  document_id uuid,
  source_key text,
  document_type text,
  league text,
  game_id text,
  title text,
  content text,
  source_url text,
  source_priority integer,
  semantic_score double precision,
  keyword_score real,
  combined_score double precision
)
language sql
stable
as $$
  select
    kd.document_id,
    kd.source_key,
    kd.document_type,
    kd.league,
    kd.game_id,
    kd.title,
    kd.content,
    kd.source_url,
    kd.source_priority,
    case
      when kd.embedding is null then 0
      else 1 - (kd.embedding <=> query_embedding)
    end as semantic_score,
    ts_rank(kd.search_tsv, plainto_tsquery('simple', query_text)) as keyword_score,
    (
      0.70 * case when kd.embedding is null then 0 else 1 - (kd.embedding <=> query_embedding) end
      + 0.20 * ts_rank(kd.search_tsv, plainto_tsquery('simple', query_text))
      + 0.10 * (kd.source_priority::double precision / 5.0)
    ) as combined_score
  from knowledge_documents kd
  where kd.verified = true
    and (kd.expires_at is null or kd.expires_at > now())
    and (filter_league is null or kd.league = filter_league)
    and (filter_game_id is null or kd.game_id = filter_game_id)
  order by combined_score desc
  limit greatest(1, least(match_count, 30));
$$;

alter table teams enable row level security;
alter table players enable row level security;
alter table games enable row level security;
alter table player_game_stats enable row level security;
alter table raw_sources enable row level security;
alter table knowledge_documents enable row level security;
alter table news_events enable row level security;
alter table game_reports enable row level security;
alter table card_templates enable row level security;
alter table card_news enable row level security;
alter table ingest_logs enable row level security;

-- service_role은 RLS를 우회한다. 브라우저에 service role key를 절대 노출하지 않는다.

insert into card_templates(template_id, name, event_type, structure, writing_rules)
values
('game-result-v1','경기 결과형','GAME_RESULT',
 '{"slides":["cover","score","top1","top2","top3","key_stats","summary"]}'::jsonb,
 '{"headline_max":40,"body_max":180}'::jsonb),
('player-performance-v1','선수 맹활약형','PLAYER_PERFORMANCE',
 '{"slides":["cover","player_hero","top1","top2","top3","stat_board","summary"]}'::jsonb,
 '{"headline_max":40,"body_max":180}'::jsonb),
('record-v1','대기록형','RECORD',
 '{"slides":["cover","record","context","top1","top2","comparison","summary"]}'::jsonb,
 '{"headline_max":40,"body_max":180}'::jsonb),
('comeback-v1','역전승형','COMEBACK',
 '{"slides":["cover","score_flow","turning_point","top1","top2","top3","summary"]}'::jsonb,
 '{"headline_max":40,"body_max":180}'::jsonb),
('pitching-duel-v1','투수전형','PITCHING_DUEL',
 '{"slides":["cover","score","starter_a","starter_b","turning_point","key_stats","summary"]}'::jsonb,
 '{"headline_max":40,"body_max":180}'::jsonb),
('slugfest-v1','난타전형','SLUGFEST',
 '{"slides":["cover","score","run_flow","top1","top2","key_stats","summary"]}'::jsonb,
 '{"headline_max":40,"body_max":180}'::jsonb),
('ranking-impact-v1','순위 경쟁형','RANKING',
 '{"slides":["cover","result","standings_before","top1","top2","standings_after","summary"]}'::jsonb,
 '{"headline_max":40,"body_max":180}'::jsonb)
on conflict (template_id) do update set
  name = excluded.name,
  event_type = excluded.event_type,
  structure = excluded.structure,
  writing_rules = excluded.writing_rules,
  updated_at = now();


-- Sports Daily Card News Studio production memory
create table if not exists production_sessions (
  session_id text primary key,
  edition_date date not null,
  sport text not null,
  league text not null,
  topic text not null,
  theme_id text not null,
  input_payload jsonb not null default '{}'::jsonb,
  final_payload jsonb not null default '{}'::jsonb,
  status text not null default 'pending_human_review',
  notion_page_url text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists production_sessions_date_idx
  on production_sessions(edition_date desc, sport, league);

create table if not exists agent_feedback (
  feedback_id uuid primary key default gen_random_uuid(),
  feedback_key text not null unique,
  session_id text not null references production_sessions(session_id) on delete cascade,
  agent_id text not null,
  agent_name text not null,
  sport text not null,
  score integer not null check (score between 1 and 100),
  what_worked text not null,
  improve_next text not null,
  learning_rule text not null,
  applied_count integer not null default 0,
  created_at timestamptz not null default now()
);

create index if not exists agent_feedback_learning_idx
  on agent_feedback(sport, agent_id, created_at desc);

alter table production_sessions enable row level security;
alter table agent_feedback enable row level security;
