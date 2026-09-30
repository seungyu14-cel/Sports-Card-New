from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from sports_card_news.config import load_settings
from sports_card_news.generator import generate_daily_package, repair_daily_package
from sports_card_news.models import (
    DesignCard,
    DesignPlan,
    EditorialCard,
    EditorialPlan,
    FactStatus,
    ResearchBrief,
)
from sports_card_news.pipeline import load_package


ROOT = Path(__file__).parents[1]


def _stages():
    package = load_package(ROOT / "fixtures/demo_package.json")
    research = ResearchBrief(
        edition_date=package.edition_date,
        generated_at=package.generated_at,
        candidates=package.candidates,
        facts=package.facts,
        risk_flags=package.risk_flags,
    )
    editorial = EditorialPlan(
        edition_date=package.edition_date,
        selected_candidate_title=package.selected_candidate_title,
        selection_reason=package.selection_reason,
        cards=[
            EditorialCard(
                slide=card.slide,
                league=card.league,
                candidate_title=card.candidate_title,
                headline=card.headline,
                body=card.body,
                source_ids=card.source_ids,
                content_type=card.content_type,
                kicker=card.kicker,
                alt_text=card.alt_text,
            )
            for card in package.cards
        ],
        caption=package.caption,
        hashtags=package.hashtags,
        approval_checklist=package.approval_checklist,
    )
    design = DesignPlan(
        design_brief=package.design_brief,
        rights_status=package.rights_status,
        assets=package.assets,
        cards=[
            DesignCard(
                slide=card.slide,
                visual_template=card.visual_template,
                visual_title=card.visual_title,
                visual_items=card.visual_items,
                visual_direction=card.visual_direction,
                asset_ids=card.asset_ids,
            )
            for card in package.cards
        ],
    )
    return package, research, editorial, design


class StageResponses:
    def __init__(self, outputs: list[object]) -> None:
        self.outputs = list(outputs)
        self.kwargs_history: list[dict[str, object]] = []

    def parse(self, **kwargs: object) -> SimpleNamespace:
        self.kwargs_history.append(kwargs)
        return SimpleNamespace(output_parsed=self.outputs.pop(0), output=[])


class TransientApiError(RuntimeError):
    status_code = 429


class FlakyStageResponses(StageResponses):
    def __init__(self, outputs: list[object]) -> None:
        super().__init__(outputs)
        self.calls = 0

    def parse(self, **kwargs: object) -> SimpleNamespace:
        self.calls += 1
        if self.calls == 1:
            raise TransientApiError("잠시 후 다시 시도")
        return super().parse(**kwargs)


def test_generation_uses_three_stage_research_editorial_design_pipeline() -> None:
    package, research, editorial, design = _stages()
    responses = StageResponses([research, editorial, design])
    client = SimpleNamespace(responses=responses)
    settings = load_settings(ROOT / "config/settings.toml")

    generated = generate_daily_package(
        date(2026, 9, 29),
        settings,
        "최근 게시 이력 없음",
        client=client,  # type: ignore[arg-type]
    )

    assert generated.edition_date == package.edition_date
    assert generated.cards[1].candidate_title == package.cards[1].candidate_title
    assert len(responses.kwargs_history) == 3
    research_call, editorial_call, design_call = responses.kwargs_history
    assert research_call["model"] == "gpt-6-astra"
    assert research_call["tools"] == [{"type": "web_search", "external_web_access": True}]
    assert research_call["tool_choice"] == "required"
    assert "tools" not in editorial_call
    assert "tools" not in design_call
    assert research_call["store"] is False
    assert editorial_call["store"] is False
    assert design_call["store"] is False


def test_schema_includes_quality_and_rights_fields() -> None:
    package, research, _, design = _stages()
    assert research.candidates[0].freshness >= 1
    assert research.candidates[0].visual_potential >= 1
    assert hasattr(package.cards[0], "content_type")
    assert hasattr(package.cards[0], "candidate_title")
    assert hasattr(package.cards[0], "asset_ids")
    assert isinstance(design.assets, list)


def test_generation_retries_a_transient_api_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, research, editorial, design = _stages()
    responses = FlakyStageResponses([research, editorial, design])
    client = SimpleNamespace(responses=responses)
    settings = replace(load_settings(ROOT / "config/settings.toml"), api_retry_attempts=2)
    sleeps: list[int] = []
    monkeypatch.setattr("sports_card_news.generator.time.sleep", sleeps.append)

    generated = generate_daily_package(
        date(2026, 9, 29),
        settings,
        "최근 게시 이력 없음",
        client=client,  # type: ignore[arg-type]
    )

    assert generated.edition_date == "2026-09-29"
    assert responses.calls == 4
    assert sleeps == [1]


def test_repair_generation_includes_validation_errors_and_invalid_package() -> None:
    package, _, _, _ = _stages()
    conflicted_fact = package.facts[0].model_copy(update={"status": FactStatus.CONFLICT})
    invalid = package.model_copy(update={"facts": [conflicted_fact, *package.facts[1:]]})
    responses = StageResponses([package])
    client = SimpleNamespace(responses=responses)
    settings = load_settings(ROOT / "config/settings.toml")

    repaired = repair_daily_package(
        edition_date=date(2026, 9, 29),
        settings=settings,
        history_summary="최근 게시 이력 없음",
        invalid_package=invalid,
        errors=["출처 충돌: S1 점수가 일치하지 않습니다."],
        warnings=["게시 전 재확인 필요"],
        attempt=1,
        client=client,  # type: ignore[arg-type]
    )

    assert repaired is package
    request = responses.kwargs_history[0]
    assert "출처 충돌: S1" in str(request["input"])
    assert "검증에 실패한 이전 초안" in str(request["input"])
    assert '"status": "출처 충돌"' in str(request["input"])
    assert "자동 복구" in str(request["instructions"])
