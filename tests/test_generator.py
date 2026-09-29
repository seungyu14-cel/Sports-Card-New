from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

from sports_card_news.config import load_settings
from sports_card_news.generator import generate_daily_package, repair_daily_package
from sports_card_news.models import DailyPackage, FactStatus
from sports_card_news.pipeline import load_package


ROOT = Path(__file__).parents[1]


class FakeResponses:
    def __init__(self, package: object) -> None:
        self.package = package
        self.kwargs: dict[str, object] = {}

    def parse(self, **kwargs: object) -> SimpleNamespace:
        self.kwargs = kwargs
        return SimpleNamespace(output_parsed=self.package, output=[])


def test_generation_uses_openai_responses_web_search_and_schema() -> None:
    package = load_package(ROOT / "fixtures/demo_package.json")
    responses = FakeResponses(package)
    client = SimpleNamespace(responses=responses)
    settings = load_settings(ROOT / "config/settings.toml")

    generated = generate_daily_package(
        date(2026, 9, 29),
        settings,
        "최근 게시 이력 없음",
        client=client,  # type: ignore[arg-type]
    )

    assert generated.edition_date == "2026-09-29"
    assert responses.kwargs["model"] == "gpt-6-astra"
    assert responses.kwargs["tools"] == [
        {"type": "web_search", "external_web_access": True}
    ]
    assert responses.kwargs["tool_choice"] == "required"
    assert responses.kwargs["text_format"] is generated.__class__
    assert responses.kwargs["store"] is False


def test_daily_package_schema_does_not_emit_uri_format() -> None:
    schema_text = str(DailyPackage.model_json_schema())
    assert "'format': 'uri'" not in schema_text
    assert '"format": "uri"' not in schema_text


def test_repair_generation_includes_validation_errors_and_invalid_package() -> None:
    package = load_package(ROOT / "fixtures/demo_package.json")
    conflicted_fact = package.facts[0].model_copy(update={"status": FactStatus.CONFLICT})
    invalid = package.model_copy(update={"facts": [conflicted_fact, *package.facts[1:]]})
    responses = FakeResponses(package)
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
    assert "출처 충돌: S1" in str(responses.kwargs["input"])
    assert "검증에 실패한 이전 초안" in str(responses.kwargs["input"])
    assert '"status": "출처 충돌"' in str(responses.kwargs["input"])
    assert "자동 복구 단계" in str(responses.kwargs["instructions"])
