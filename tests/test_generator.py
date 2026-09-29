from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

from sports_card_news.config import load_settings
from sports_card_news.generator import generate_daily_package
from sports_card_news.openrouter import OPENROUTER_BASE_URL, create_openrouter_client


ROOT = Path(__file__).parents[1]


class FakeCompletions:
    def __init__(self, content: str) -> None:
        self.content = content
        self.kwargs: dict[str, object] = {}

    def create(self, **kwargs: object) -> SimpleNamespace:
        self.kwargs = kwargs
        message = SimpleNamespace(content=self.content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def test_generation_uses_openrouter_chat_web_search_and_schema() -> None:
    fixture = (ROOT / "fixtures/demo_package.json").read_text(encoding="utf-8")
    completions = FakeCompletions(fixture)
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    settings = load_settings(ROOT / "config/settings.toml")

    package = generate_daily_package(
        date(2026, 9, 29),
        settings,
        "최근 게시 이력 없음",
        client=client,  # type: ignore[arg-type]
    )

    assert package.edition_date == "2026-09-29"
    assert completions.kwargs["model"] == "openai/gpt-5.2"
    response_format = completions.kwargs["response_format"]
    assert isinstance(response_format, dict)
    assert response_format["type"] == "json_schema"
    extra_body = completions.kwargs["extra_body"]
    assert isinstance(extra_body, dict)
    assert extra_body["tool_choice"] == "required"
    assert extra_body["tools"] == [
        {"type": "openrouter:web_search", "parameters": {"max_results": 12}}
    ]


def test_openrouter_client_uses_openrouter_endpoint() -> None:
    client = create_openrouter_client("sk-or-v1-test-value-1234567890")
    assert str(client.base_url) == f"{OPENROUTER_BASE_URL}/"
