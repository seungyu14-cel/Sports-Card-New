from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from openai import OpenAI

from .supabase_store import SupabaseStore


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"}:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"} and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            text = re.sub(r"\s+", " ", data).strip()
            if text:
                self.parts.append(text)


class SportsIngestor:
    def __init__(
        self,
        store: SupabaseStore,
        *,
        trusted_domains: tuple[str, ...] = (),
        openai_client: OpenAI | None = None,
    ) -> None:
        self.store = store
        self.trusted_domains = tuple(domain.lower() for domain in trusted_domains)
        self.openai = openai_client
        self.embedding_model = os.getenv(
            "OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"
        )

    def ingest_bundle(self, payload: dict[str, Any]) -> dict[str, int]:
        counts: dict[str, int] = {}
        mappings = (
            ("teams", "team_id"),
            ("players", "player_id"),
            ("games", "game_id"),
            ("player_game_stats", "game_id,player_id,stat_type"),
        )
        for table, conflict in mappings:
            rows = payload.get(table, [])
            if isinstance(rows, list) and rows:
                counts[table] = len(self.store.upsert(table, rows, on_conflict=conflict))
            else:
                counts[table] = 0

        sources = payload.get("sources", [])
        counts["sources"] = 0
        if isinstance(sources, list):
            for source in sources:
                if isinstance(source, dict):
                    self.ingest_source_record(source)
                    counts["sources"] += 1
        self._log("bundle", sum(counts.values()), "ok", {"counts": counts})
        return counts

    def ingest_json_file(self, path: str | Path) -> dict[str, int]:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("수집 JSON 최상위 값은 객체여야 합니다.")
        return self.ingest_bundle(payload)

    def scrape_url(
        self,
        *,
        url: str,
        league: str,
        game_id: str | None = None,
        source_type: str = "official",
        verified: bool = False,
    ) -> dict[str, Any]:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("http/https URL만 스크랩할 수 있습니다.")
        host = parsed.hostname.lower()
        trusted = any(host == d or host.endswith("." + d) for d in self.trusted_domains)
        if verified and not trusted:
            raise ValueError("검증 완료 표시는 trusted_domains의 원문에만 사용할 수 있습니다.")

        response = httpx.get(
            url,
            follow_redirects=True,
            timeout=15.0,
            headers={"User-Agent": "SportsCardNewsBot/1.0 (+editorial research)"},
        )
        response.raise_for_status()
        if len(response.content) > 2_000_000:
            raise ValueError("원문이 2MB를 넘어 자동 수집을 중단했습니다.")
        content_type = response.headers.get("content-type", "")
        if "html" not in content_type.lower() and "text" not in content_type.lower():
            raise ValueError("HTML/텍스트 원문만 자동 수집합니다.")

        parser = _TextExtractor()
        parser.feed(response.text)
        text = "\n".join(parser.parts)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()[:80_000]
        if len(text) < 80:
            raise ValueError("본문 텍스트가 너무 짧아 저장하지 않았습니다.")

        title = self._html_title(response.text) or host
        record = {
            "source_type": source_type,
            "league": league.upper(),
            "game_id": game_id,
            "publisher": host,
            "url": str(response.url),
            "title": title[:300],
            "content": text,
            "published_at": None,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "verified": bool(verified and trusted),
            "source_priority": 5 if verified and trusted else 2,
            "metadata": {"trusted_domain": trusted, "content_type": content_type},
        }
        return self.ingest_source_record(record)

    def ingest_source_record(self, source: dict[str, Any]) -> dict[str, Any]:
        content = str(source.get("content", "")).strip()
        url = str(source.get("url", "")).strip()
        if not content or not url:
            raise ValueError("source에는 url과 content가 필요합니다.")
        checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
        source_key = str(source.get("source_key") or f"{url}#{checksum[:16]}")
        verified = bool(source.get("verified", False))
        raw_fields = {
            "source_key",
            "source_type",
            "league",
            "game_id",
            "publisher",
            "url",
            "title",
            "content",
            "published_at",
            "scraped_at",
            "expires_at",
            "checksum",
            "verified",
            "source_priority",
            "metadata",
        }
        row = {
            key: value
            for key, value in {
                **source,
                "source_key": source_key,
                "checksum": checksum,
                "verified": verified,
            }.items()
            if key in raw_fields
        }
        stored = self.store.upsert("raw_sources", row, on_conflict="source_key")

        document = {
            "source_key": source_key,
            "document_type": str(source.get("document_type") or source.get("source_type") or "source"),
            "league": source.get("league"),
            "game_id": source.get("game_id"),
            "team_id": source.get("team_id"),
            "player_id": source.get("player_id"),
            "title": source.get("title"),
            "content": content[:40_000],
            "source_url": url,
            "published_at": source.get("published_at"),
            "expires_at": source.get("expires_at"),
            "verified": verified,
            "source_priority": int(source.get("source_priority", 1)),
            "metadata": source.get("metadata", {}),
            "embedding": self._embedding(content) if verified else None,
        }
        self.store.upsert("knowledge_documents", document, on_conflict="source_key")
        return stored[0] if stored else row

    def _embedding(self, text: str) -> list[float] | None:
        if self.openai is None:
            return None
        response = self.openai.embeddings.create(
            model=self.embedding_model,
            input=text[:24_000],
        )
        return list(response.data[0].embedding)

    def _log(
        self,
        source_name: str,
        rows_written: int,
        status: str,
        detail: dict[str, Any],
    ) -> None:
        self.store.upsert(
            "ingest_logs",
            {
                "source_name": source_name,
                "rows_written": rows_written,
                "status": status,
                "detail": detail,
            },
        )

    @staticmethod
    def _html_title(html: str) -> str:
        match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.I | re.S)
        if not match:
            return ""
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", match.group(1))).strip()
