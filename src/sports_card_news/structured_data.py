from __future__ import annotations

import json
from datetime import date
from pathlib import Path


def load_structured_context(data_dir: str | Path, edition_date: date) -> str:
    root = Path(data_dir)
    candidates = [
        root / f"{edition_date.isoformat()}.json",
        root / "latest.json",
    ]
    for path in candidates:
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        provenance = payload.get("provenance")
        if provenance is None:
            return (
                f"{path.as_posix()} 파일은 존재하지만 provenance가 없어 자동 신뢰하지 않습니다. "
                "참고값으로만 사용하고 공식 원문을 다시 확인하세요.\n"
                + json.dumps(payload, ensure_ascii=False)[:6000]
            )
        return (
            f"구조화 데이터 파일: {path.as_posix()}\n"
            "provenance가 포함되어 있어도 공식 원문을 재확인해야 합니다.\n"
            + json.dumps(payload, ensure_ascii=False)[:8000]
        )
    return "사전 구조화 데이터 없음"
