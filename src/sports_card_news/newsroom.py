from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from openai import OpenAI
from pydantic import Field, field_validator

from .models import StrictModel
from .supabase_store import SupabaseStore


class TopNewsItem(StrictModel):
    rank: int = Field(ge=1, le=3)
    event_type: str = Field(min_length=2, max_length=40)
    headline: str = Field(min_length=4, max_length=80)
    summary: str = Field(min_length=10, max_length=500)
    why_it_matters: str = Field(min_length=5, max_length=300)
    importance_score: float = Field(ge=0, le=100)
    confidence_score: float = Field(ge=0, le=1)
    source_urls: list[str] = Field(default_factory=list, max_length=10)
    fact_keys: list[str] = Field(default_factory=list, max_length=20)


class GameNewsDraft(StrictModel):
    game_id: str
    league: str
    game_headline: str = Field(min_length=4, max_length=100)
    top3: list[TopNewsItem] = Field(min_length=3, max_length=3)
    summary: str = Field(min_length=10, max_length=700)

    @field_validator("top3")
    @classmethod
    def validate_ranks(cls, items: list[TopNewsItem]) -> list[TopNewsItem]:
        if sorted(item.rank for item in items) != [1, 2, 3]:
            raise ValueError("TOP3 rank는 1,2,3이 각각 한 번씩 필요합니다.")
        return sorted(items, key=lambda item: item.rank)


class GameNewsroom:
    def __init__(
        self,
        store: SupabaseStore,
        *,
        openai_client: OpenAI | None = None,
        model: str | None = None,
        embedding_model: str | None = None,
        trusted_domains: tuple[str, ...] = (),
        reasoning_effort: str = "low",
    ) -> None:
        self.store = store
        self.openai = openai_client or OpenAI()
        self.model = model or os.getenv("OPENAI_NEWS_MODEL", "gpt-6.1-sol")
        self.embedding_model = embedding_model or os.getenv(
            "OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"
        )
        self.trusted_domains = trusted_domains
        self.reasoning_effort = reasoning_effort

    def generate_for_date(
        self,
        edition_date: date,
        *,
        leagues: tuple[str, ...] | list[str] | None = None,
        game_id: str | None = None,
        output_dir: str | Path | None = None,
    ) -> list[dict[str, Any]]:
        games = (
            [self.store.game(game_id)] if game_id else self.store.games_for_date(edition_date, leagues)
        )
        reports: list[dict[str, Any]] = []
        for game in games:
            if not game:
                continue
            reports.append(self.generate_game_report(game, edition_date))

        if output_dir is not None:
            self.write_structured_export(edition_date, reports, output_dir)
        return reports

    def generate_game_report(
        self,
        game: dict[str, Any],
        edition_date: date,
    ) -> dict[str, Any]:
        game_id = str(game["game_id"])
        stats = self.store.stats_for_game(game_id)
        sources = self.store.sources_for_game(game_id)
        missing = _missing_critical_fields(game, stats, sources)
        query = self._query_text(game)
        knowledge = self._rag(query, game)

        known_urls = {
            str(item.get("url") or item.get("source_url"))
            for item in [*sources, *knowledge]
            if item.get("url") or item.get("source_url")
        }
        require_web = bool(missing)
        draft, web_urls, usage = self._request_draft(
            game=game,
            stats=stats,
            sources=sources,
            knowledge=knowledge,
            missing=missing,
            require_web=require_web,
        )
        all_allowed_urls = known_urls | web_urls
        sanitized = []
        for item in draft.top3:
            urls = [url for url in item.source_urls if url in all_allowed_urls]
            sanitized.append(item.model_copy(update={"source_urls": urls}))
        draft = draft.model_copy(update={"top3": sanitized})

        template_id = _select_template(draft.top3[0].event_type)
        report_key = f"{game_id}:{edition_date.isoformat()}"
        payload = {
            **draft.model_dump(mode="json"),
            "template_id": template_id,
            "missing_fields": missing,
            "web_search_used": require_web,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        report_row = {
            "report_key": report_key,
            "game_id": game_id,
            "edition_date": edition_date.isoformat(),
            "payload": payload,
            "model": self.model,
            "input_tokens": usage["input_tokens"],
            "output_tokens": usage["output_tokens"],
            "web_search_used": require_web,
            "missing_fields": missing,
        }
        self.store.upsert("game_reports", report_row, on_conflict="report_key")

        event_rows = []
        game_verified = bool(game.get("verified"))
        for item in draft.top3:
            program_verified = (
                game_verified
                and not missing
                and item.confidence_score >= 0.90
                and bool(item.source_urls or item.fact_keys)
            )
            event_rows.append(
                {
                    "event_key": f"{report_key}:{item.rank}",
                    "game_id": game_id,
                    "league": draft.league,
                    "event_type": item.event_type,
                    "rank": item.rank,
                    "headline": item.headline,
                    "summary": item.summary,
                    "why_it_matters": item.why_it_matters,
                    "importance_score": item.importance_score,
                    "confidence_score": item.confidence_score,
                    "source_urls": item.source_urls,
                    "fact_keys": item.fact_keys,
                    "verified": program_verified,
                    "needs_human_review": True,
                    "occurred_at": game.get("start_at"),
                }
            )
        self.store.upsert("news_events", event_rows, on_conflict="event_key")
        return payload

    def write_structured_export(
        self,
        edition_date: date,
        reports: list[dict[str, Any]],
        output_dir: str | Path,
    ) -> Path:
        root = Path(output_dir)
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"{edition_date.isoformat()}.json"
        payload = {
            "edition_date": edition_date.isoformat(),
            "provenance": {
                "type": "supabase-newsroom",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "human_approval_required": True,
            },
            "game_reports": reports,
        }
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return path

    def _rag(self, query: str, game: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            embedding = self.openai.embeddings.create(
                model=self.embedding_model,
                input=query,
            ).data[0].embedding
            return self.store.hybrid_search(
                query_embedding=list(embedding),
                query_text=query,
                league=str(game.get("league") or ""),
                game_id=str(game.get("game_id") or ""),
                count=8,
            )
        except Exception:
            # RAG 장애가 전체 경기 생산을 막지 않도록 한다.
            return []

    def _request_draft(
        self,
        *,
        game: dict[str, Any],
        stats: list[dict[str, Any]],
        sources: list[dict[str, Any]],
        knowledge: list[dict[str, Any]],
        missing: list[str],
        require_web: bool,
    ) -> tuple[GameNewsDraft, set[str], dict[str, int]]:
        instructions = """당신은 스포츠 미디어 경기 담당 데스크다.
제공된 구조화 사실을 최우선으로 사용하고 한 경기의 TOP3 뉴스만 작성한다.
규칙:
- 점수, 선수 기록, 날짜, 팀명은 입력 데이터와 불일치하면 안 된다.
- TOP3는 서로 다른 사건이어야 한다.
- 단순 승패 반복보다 승부 영향, 개인 기록, 시즌 영향 순으로 가치가 높은 사건을 고른다.
- 입력에 없는 숫자·인터뷰·부상·역대기록은 만들지 않는다.
- 웹검색이 허용된 경우 missing_fields에 필요한 정보만 조사한다.
- source_urls에는 입력 또는 실제 검색으로 확인한 URL만 넣는다.
- 확신이 낮으면 confidence_score를 낮춘다.
- 결과는 GameNewsDraft 스키마만 반환한다."""
        prompt_payload = {
            "game": game,
            "player_game_stats": stats[:40],
            "verified_sources": [
                {
                    "source_key": row.get("source_key"),
                    "title": row.get("title"),
                    "url": row.get("url"),
                    "content": str(row.get("content", ""))[:2500],
                    "source_priority": row.get("source_priority"),
                }
                for row in sources[:12]
            ],
            "rag_context": [
                {
                    "source_key": row.get("source_key"),
                    "title": row.get("title"),
                    "source_url": row.get("source_url"),
                    "content": str(row.get("content", ""))[:1800],
                    "combined_score": row.get("combined_score"),
                }
                for row in knowledge[:8]
            ],
            "missing_fields": missing,
        }
        kwargs: dict[str, Any] = {
            "model": self.model,
            "reasoning": {"effort": self.reasoning_effort},
            "instructions": instructions,
            "input": json.dumps(prompt_payload, ensure_ascii=False),
            "text_format": GameNewsDraft,
            "max_output_tokens": 3500,
            "store": False,
        }
        if require_web:
            tool: dict[str, Any] = {
                "type": "web_search",
                "external_web_access": True,
            }
            if self.trusted_domains:
                tool["filters"] = {"allowed_domains": list(self.trusted_domains)}
            kwargs["tools"] = [tool]
            kwargs["tool_choice"] = "required"
            kwargs["include"] = ["web_search_call.action.sources"]

        response = self.openai.responses.parse(**kwargs)
        if response.output_parsed is None:
            raise RuntimeError("경기별 TOP3 구조화 응답을 받지 못했습니다.")
        usage = getattr(response, "usage", None)
        usage_dict = {
            "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
            "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
        }
        return response.output_parsed, _extract_web_urls(response), usage_dict

    @staticmethod
    def _query_text(game: dict[str, Any]) -> str:
        return (
            f"{game.get('game_date', '')} {game.get('league', '')} "
            f"{game.get('away_team_name', '')} {game.get('away_score', '')} "
            f"{game.get('home_team_name', '')} {game.get('home_score', '')}"
        ).strip()


def _missing_critical_fields(
    game: dict[str, Any],
    stats: list[dict[str, Any]],
    sources: list[dict[str, Any]],
) -> list[str]:
    missing: list[str] = []
    if game.get("status") != "종료" or game.get("home_score") is None or game.get("away_score") is None:
        missing.append("official_final_result")
    if not bool(game.get("verified")):
        missing.append("verified_game_result")
    verified_stats = [row for row in stats if row.get("verified")]
    if len(verified_stats) < 2:
        missing.append("key_player_stats")
    high_quality_sources = [
        row
        for row in sources
        if row.get("verified") and int(row.get("source_priority") or 0) >= 4
    ]
    if not high_quality_sources:
        missing.append("official_postgame_context")
    return missing


def _select_template(event_type: str) -> str:
    key = event_type.upper()
    mapping = {
        "PLAYER_PERFORMANCE": "player-performance-v1",
        "RECORD": "record-v1",
        "COMEBACK": "comeback-v1",
        "PITCHING_DUEL": "pitching-duel-v1",
        "SLUGFEST": "slugfest-v1",
        "RANKING": "ranking-impact-v1",
    }
    return mapping.get(key, "game-result-v1")


def _extract_web_urls(response: object) -> set[str]:
    urls: set[str] = set()
    for item in getattr(response, "output", []) or []:
        action = getattr(item, "action", None)
        sources = getattr(action, "sources", None) if action is not None else None
        for source in sources or []:
            url = getattr(source, "url", None)
            if not url and isinstance(source, dict):
                url = source.get("url")
            if isinstance(url, str) and url.startswith(("http://", "https://")):
                urls.add(url)
    return urls
