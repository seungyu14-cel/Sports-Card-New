from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path


def recent_publication_summary(output_root: str | Path, edition_date: date, days: int = 7) -> str:
    root = Path(output_root)
    rows: list[str] = []
    earliest = edition_date - timedelta(days=days)

    if not root.exists():
        return "최근 승인·병합된 게시 이력 없음"

    for package_file in sorted(root.glob("*/package.json"), reverse=True):
        try:
            data = json.loads(package_file.read_text(encoding="utf-8"))
            package_date = date.fromisoformat(data["edition_date"])
        except (OSError, KeyError, ValueError, json.JSONDecodeError):
            continue
        if not (earliest <= package_date < edition_date):
            continue
        selected = next(
            (item for item in data.get("candidates", []) if item.get("title") == data.get("selected_candidate_title")),
            {},
        )
        rows.append(
            f"- {package_date.isoformat()} | {selected.get('sport', '미상')} | "
            f"{selected.get('league', '미상')} | {data.get('selected_candidate_title', '제목 없음')}"
        )
    return "\n".join(rows) if rows else "최근 승인·병합된 게시 이력 없음"

