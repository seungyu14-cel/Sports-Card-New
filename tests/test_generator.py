from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

from sports_card_news.config import load_settings
from sports_card_news.generator import generate_daily_package
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
