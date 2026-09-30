from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Settings:
    timezone: str
    model: str
    reasoning_effort: str
    cards_min: int
    cards_max: int
    caption_min_chars: int
    caption_max_chars: int
    output_width: int
    output_height: int
    auto_repair_attempts: int
    api_retry_attempts: int
    api_timeout_seconds: float
    leagues: tuple[str, ...]
    candidate_sports_min: int
    candidate_pool_target: int
    min_distinct_story_leagues: int
    max_cards_per_league: int
    visual_repeat_limit: int
    recent_days: int
    analytics_days: int
    structured_data_dir: str
    weights: dict[str, float]
    trusted_domains: tuple[str, ...]


def load_settings(path: str | Path = "config/settings.toml") -> Settings:
    raw: dict[str, Any]
    with Path(path).open("rb") as file:
        raw = tomllib.load(file)

    editorial = raw["editorial"]
    sources = raw["sources"]
    return Settings(
        timezone=raw["timezone"],
        model=os.getenv("OPENAI_MODEL", raw["model"]),
        reasoning_effort=raw["reasoning_effort"],
        cards_min=raw["cards_min"],
        cards_max=raw["cards_max"],
        caption_min_chars=raw["caption_min_chars"],
        caption_max_chars=raw["caption_max_chars"],
        output_width=raw["output_width"],
        output_height=raw["output_height"],
        auto_repair_attempts=min(3, max(0, int(raw.get("auto_repair_attempts", 2)))),
        api_retry_attempts=min(5, max(1, int(raw.get("api_retry_attempts", 3)))),
        api_timeout_seconds=max(10.0, float(raw.get("api_timeout_seconds", 120))),
        leagues=tuple(editorial["leagues"]),
        candidate_sports_min=int(editorial["candidate_sports_min"]),
        candidate_pool_target=min(20, max(5, int(editorial.get("candidate_pool_target", 10)))),
        min_distinct_story_leagues=min(
            5, max(1, int(editorial.get("min_distinct_story_leagues", 3)))
        ),
        max_cards_per_league=min(
            5, max(1, int(editorial.get("max_cards_per_league", 2)))
        ),
        visual_repeat_limit=min(5, max(1, int(editorial.get("visual_repeat_limit", 2)))),
        recent_days=max(1, int(editorial["recent_days"])),
        analytics_days=max(1, int(editorial.get("analytics_days", 30))),
        structured_data_dir=str(editorial.get("structured_data_dir", "data/structured")),
        weights=dict(editorial["weights"]),
        trusted_domains=tuple(sources["trusted_domains"]),
    )
