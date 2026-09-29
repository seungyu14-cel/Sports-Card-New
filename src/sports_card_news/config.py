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
    leagues: tuple[str, ...]
    candidate_sports_min: int
    recent_days: int
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
        model=os.getenv("OPENROUTER_MODEL", raw["model"]),
        reasoning_effort=raw["reasoning_effort"],
        cards_min=raw["cards_min"],
        cards_max=raw["cards_max"],
        caption_min_chars=raw["caption_min_chars"],
        caption_max_chars=raw["caption_max_chars"],
        output_width=raw["output_width"],
        output_height=raw["output_height"],
        leagues=tuple(editorial["leagues"]),
        candidate_sports_min=editorial["candidate_sports_min"],
        recent_days=editorial["recent_days"],
        weights=dict(editorial["weights"]),
        trusted_domains=tuple(sources["trusted_domains"]),
    )
