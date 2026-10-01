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
    research_max_output_tokens: int
    editorial_max_output_tokens: int
    design_max_output_tokens: int
    repair_max_output_tokens: int
    daily_output_token_budget: int
    max_prompt_chars: int
    context_max_chars: int
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
    allow_news_images: bool
    auto_approve_verified_news_images: bool
    render_news_images: bool
    news_image_timeout_seconds: float


def load_settings(path: str | Path = "config/settings.toml") -> Settings:
    raw: dict[str, Any]
    with Path(path).open("rb") as file:
        raw = tomllib.load(file)

    editorial = raw["editorial"]
    sources = raw["sources"]
    assets = raw.get("assets", {})
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
        auto_repair_attempts=min(1, max(0, int(raw.get("auto_repair_attempts", 1)))),
        api_retry_attempts=min(2, max(1, int(raw.get("api_retry_attempts", 2)))),
        api_timeout_seconds=max(30.0, float(raw.get("api_timeout_seconds", 300))),
        research_max_output_tokens=min(
            10_000, max(2_000, int(raw.get("research_max_output_tokens", 8_000)))
        ),
        editorial_max_output_tokens=min(
            8_000, max(2_000, int(raw.get("editorial_max_output_tokens", 6_000)))
        ),
        design_max_output_tokens=min(
            6_000, max(2_000, int(raw.get("design_max_output_tokens", 4_000)))
        ),
        repair_max_output_tokens=min(
            12_000, max(3_000, int(raw.get("repair_max_output_tokens", 9_000)))
        ),
        daily_output_token_budget=min(
            30_000, max(18_000, int(raw.get("daily_output_token_budget", 27_000)))
        ),
        max_prompt_chars=min(80_000, max(10_000, int(raw.get("max_prompt_chars", 40_000)))),
        context_max_chars=min(10_000, max(1_000, int(raw.get("context_max_chars", 4_000)))),
        leagues=tuple(editorial["leagues"]),
        candidate_sports_min=int(editorial["candidate_sports_min"]),
        candidate_pool_target=min(9, max(3, int(editorial.get("candidate_pool_target", 6)))),
        min_distinct_story_leagues=min(
            3, max(1, int(editorial.get("min_distinct_story_leagues", 3)))
        ),
        max_cards_per_league=min(
            1, max(1, int(editorial.get("max_cards_per_league", 1)))
        ),
        visual_repeat_limit=min(5, max(1, int(editorial.get("visual_repeat_limit", 2)))),
        recent_days=max(1, int(editorial["recent_days"])),
        analytics_days=max(1, int(editorial.get("analytics_days", 30))),
        structured_data_dir=str(editorial.get("structured_data_dir", "data/structured")),
        weights=dict(editorial["weights"]),
        trusted_domains=tuple(sources["trusted_domains"]),
        allow_news_images=bool(assets.get("allow_news_images", True)),
        auto_approve_verified_news_images=bool(
            assets.get("auto_approve_verified_news_images", True)
        ),
        render_news_images=bool(assets.get("render_news_images", True)),
        news_image_timeout_seconds=max(
            2.0, float(assets.get("news_image_timeout_seconds", 8))
        ),
    )

