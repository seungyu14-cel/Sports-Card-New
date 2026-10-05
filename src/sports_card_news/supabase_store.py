from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx


class SupabaseConfigurationError(RuntimeError):
    """Supabase server-side credentials are missing."""


class SupabaseRequestError(RuntimeError):
    """Supabase Data API request failed."""


@dataclass
class SupabaseStore:
    url: str
    service_role_key: str
    timeout_seconds: float = 20.0

    @classmethod
    def from_env(cls) -> "SupabaseStore":
        url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        if not url or not key:
            raise SupabaseConfigurationError(
                "SUPABASE_URL과 SUPABASE_SERVICE_ROLE_KEY를 서버 환경변수에 설정하세요."
            )
        return cls(url=url, service_role_key=key)

    @classmethod
    def is_configured(cls) -> bool:
        return bool(
            os.getenv("SUPABASE_URL", "").strip()
            and os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        )

    @property
    def rest_url(self) -> str:
        return f"{self.url}/rest/v1"

    def _headers(self, prefer: str | None = None) -> dict[str, str]:
        headers = {
            "apikey": self.service_role_key,
            "Authorization": f"Bearer {self.service_role_key}",
            "Content-Type": "application/json",
        }
        if prefer:
            headers["Prefer"] = prefer
        return headers

    def select(
        self,
        table: str,
        *,
        params: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        query = {"select": "*", **(params or {})}
        response = httpx.get(
            f"{self.rest_url}/{table}",
            headers=self._headers(),
            params=query,
            timeout=self.timeout_seconds,
        )
        self._raise(response)
        payload = response.json()
        return payload if isinstance(payload, list) else []

    def upsert(
        self,
        table: str,
        rows: dict[str, Any] | list[dict[str, Any]],
        *,
        on_conflict: str | None = None,
    ) -> list[dict[str, Any]]:
        payload = rows if isinstance(rows, list) else [rows]
        if not payload:
            return []
        params = {"on_conflict": on_conflict} if on_conflict else None
        response = httpx.post(
            f"{self.rest_url}/{table}",
            headers=self._headers("resolution=merge-duplicates,return=representation"),
            params=params,
            json=payload,
            timeout=self.timeout_seconds,
        )
        self._raise(response)
        result = response.json()
        return result if isinstance(result, list) else []

    def rpc(self, name: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
        response = httpx.post(
            f"{self.rest_url}/rpc/{name}",
            headers=self._headers(),
            json=payload,
            timeout=self.timeout_seconds,
        )
        self._raise(response)
        result = response.json()
        return result if isinstance(result, list) else []

    def games_for_date(
        self,
        edition_date: date,
        leagues: tuple[str, ...] | list[str] | None = None,
        *,
        final_only: bool = True,
    ) -> list[dict[str, Any]]:
        params = {
            "game_date": f"eq.{edition_date.isoformat()}",
            "order": "league.asc,start_at.asc",
        }
        if final_only:
            params["status"] = "eq.종료"
        if leagues:
            params["league"] = "in.(" + ",".join(leagues) + ")"
        return self.select("games", params=params)

    def game(self, game_id: str) -> dict[str, Any] | None:
        rows = self.select("games", params={"game_id": f"eq.{game_id}", "limit": "1"})
        return rows[0] if rows else None

    def stats_for_game(self, game_id: str) -> list[dict[str, Any]]:
        return self.select(
            "player_game_stats",
            params={"game_id": f"eq.{game_id}", "order": "verified.desc,id.asc"},
        )

    def sources_for_game(self, game_id: str) -> list[dict[str, Any]]:
        return self.select(
            "raw_sources",
            params={
                "game_id": f"eq.{game_id}",
                "verified": "eq.true",
                "order": "source_priority.desc,scraped_at.desc",
                "limit": "30",
            },
        )

    def reports_for_date(self, edition_date: date) -> list[dict[str, Any]]:
        return self.select(
            "game_reports",
            params={
                "edition_date": f"eq.{edition_date.isoformat()}",
                "order": "created_at.desc",
            },
        )

    def hybrid_search(
        self,
        *,
        query_embedding: list[float],
        query_text: str,
        league: str | None,
        game_id: str | None,
        count: int = 8,
    ) -> list[dict[str, Any]]:
        return self.rpc(
            "match_knowledge",
            {
                "query_embedding": query_embedding,
                "query_text": query_text,
                "match_count": count,
                "filter_league": league,
                "filter_game_id": game_id,
            },
        )

    def healthcheck(self) -> bool:
        self.select("games", params={"limit": "1"})
        return True

    @staticmethod
    def _raise(response: httpx.Response) -> None:
        if response.is_success:
            return
        detail = response.text[:500]
        raise SupabaseRequestError(
            f"Supabase 요청 실패 ({response.status_code}): {detail}"
        )
