from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path


def recent_performance_summary(
    output_root: str | Path,
    edition_date: date,
    days: int,
) -> str:
    root = Path(output_root)
    start = edition_date - timedelta(days=days)
    rows: list[dict[str, object]] = []
    for path in sorted(root.glob("*/performance.json")):
        try:
            day = date.fromisoformat(path.parent.name)
        except ValueError:
            continue
        if not (start <= day < edition_date):
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            payload["edition_date"] = day.isoformat()
            rows.append(payload)

    if not rows:
        return "성과 데이터 없음. 게시 후 performance.json을 저장하면 다음 편성에 참고합니다."

    rows = rows[-days:]
    lines = ["최근 카드뉴스 성과(팩트 판단이 아니라 편집 참고용):"]
    for row in rows:
        metrics = []
        for key in ("reach", "likes", "comments", "saves", "shares"):
            if key in row:
                metrics.append(f"{key}={row[key]}")
        topic = row.get("topic") or row.get("selected_candidate_title") or "제목 미기록"
        lines.append(f"- {row['edition_date']} · {topic} · " + ", ".join(metrics))
    return "\n".join(lines)
