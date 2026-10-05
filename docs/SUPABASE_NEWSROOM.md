# Supabase 스포츠 뉴스룸

이 계층은 OpenAI가 매번 모든 사실을 웹에서 다시 조사하지 않도록 설계되어 있습니다.

## 흐름

1. 스포츠 API/공식 사이트 자료를 Supabase에 저장
2. 경기·선수 숫자는 구조화 테이블에서 조회
3. 검증된 원문은 `knowledge_documents`에 저장하고 임베딩
4. 경기 생성 시 SQL 사실 + hybrid RAG 문맥을 먼저 사용
5. `official_final_result`, `verified_game_result`, `key_player_stats`, `official_postgame_context` 중 빠진 핵심 정보가 있을 때만 OpenAI Web Search 사용
6. 경기마다 TOP3를 `game_reports`, `news_events`에 저장
7. `data/structured/YYYY-MM-DD.json`을 기존 카드뉴스 Research 단계에 공급
8. 사람 승인 전에는 게시하지 않음

## 1. Supabase 준비

Supabase SQL Editor에서 `supabase/schema.sql`을 실행합니다.

서버 환경 변수:

```env
SUPABASE_URL=https://YOUR_PROJECT.supabase.co
SUPABASE_SERVICE_ROLE_KEY=...
OPENAI_API_KEY=...
OPENAI_NEWS_MODEL=gpt-6.1-sol
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
```

service role key는 RLS를 우회하므로 브라우저/프론트엔드에 노출하지 않습니다.

## 2. 데이터 적재 JSON

예시:

```json
{
  "teams": [
    {"team_id":"KBO-LG","league":"KBO","name":"LG 트윈스"}
  ],
  "games": [
    {
      "game_id":"KBO-20261005-LG-KT",
      "league":"KBO",
      "season":2026,
      "game_date":"2026-10-05",
      "home_team_id":"KBO-LG",
      "away_team_id":"KBO-KT",
      "home_team_name":"LG 트윈스",
      "away_team_name":"KT 위즈",
      "home_score":6,
      "away_score":3,
      "status":"종료",
      "verified":true
    }
  ],
  "player_game_stats": [
    {
      "game_id":"KBO-20261005-LG-KT",
      "player_id":"player-1",
      "team_id":"KBO-LG",
      "stat_type":"batting",
      "stats":{"AB":4,"H":2,"HR":1,"RBI":3},
      "verified":true
    }
  ],
  "sources": [
    {
      "source_key":"kbo-game-20261005-lg-kt",
      "source_type":"official",
      "league":"KBO",
      "game_id":"KBO-20261005-LG-KT",
      "publisher":"KBO",
      "url":"https://www.koreabaseball.com/...",
      "title":"공식 경기 결과",
      "content":"공식 원문에서 추출한 텍스트",
      "verified":true,
      "source_priority":5
    }
  ]
}
```

적재:

```powershell
sports-card-news ingest-json data/import/2026-10-05.json
```

공식 원문을 직접 스크랩해 저장:

```powershell
sports-card-news scrape-source ^
  --url "https://www.koreabaseball.com/..." ^
  --league KBO ^
  --game-id KBO-20261005-LG-KT ^
  --verified
```

`--verified`는 `config/settings.toml`의 `trusted_domains`에 속한 URL에만 허용됩니다.

## 3. 모든 종료 경기 TOP3 생성

```powershell
sports-card-news game-news --date 2026-10-05
```

특정 리그:

```powershell
sports-card-news game-news --date 2026-10-05 --league KBO --league MLB
```

특정 경기:

```powershell
sports-card-news game-news --date 2026-10-05 --game-id KBO-20261005-LG-KT
```

결과는 Supabase와 `data/structured/2026-10-05.json`에 동시에 저장됩니다.

그 후 기존 카드뉴스 생성:

```powershell
sports-card-news daily --date 2026-10-05
```

## 데이터 원칙

- 스코어/선수 기록/순위: SQL 구조화 데이터가 기준
- 기사·인터뷰·맥락: 검증된 원문 + RAG
- 최신 결핍 정보: OpenAI Web Search
- 숫자는 vector similarity를 사실 근거로 사용하지 않음
- 만료된 문서는 RAG에서 제외
- 모델이 만든 URL은 허용하지 않고 DB 또는 실제 Web Search source URL만 유지
- 모든 최종 게시물은 사람 승인 필요

## 권장 수집기 확장

실서비스에서는 KBO/MLB/NPB/NBA/EPL별 collector가 위 JSON 스키마로 정규화하도록 구현합니다. 외부 사이트 이용약관과 robots 정책을 준수하고, 공식 API가 존재하면 HTML 스크래핑보다 공식 API를 우선합니다.
