from __future__ import annotations

from pathlib import Path

from PIL import Image

from sports_card_news.config import load_settings
from sports_card_news.models import VisualTemplate
from sports_card_news.pipeline import load_package
from sports_card_news.renderer import _clean_card_text, _resolve_visual_template, render_package


ROOT = Path(__file__).parents[1]


def test_sports_desk_renderer_uses_editorial_palette(tmp_path: Path) -> None:
    settings = load_settings(ROOT / "config/settings.toml")
    package = load_package(ROOT / "fixtures/demo_package.json")

    paths = render_package(package, tmp_path, settings)

    assert len(paths) == 5
    with Image.open(paths[0]) as image:
        assert image.size == (1080, 1350)
        colors = {color for _, color in image.getcolors(maxcolors=2_000_000) or []}
        assert (244, 240, 232) in colors
        assert (255, 214, 61) in colors
        assert (17, 17, 17) in colors
        assert (228, 66, 54) in colors


def test_story_cards_render_distinct_data_modules(tmp_path: Path) -> None:
    settings = load_settings(ROOT / "config/settings.toml")
    package = load_package(ROOT / "fixtures/demo_package.json")
    paths = render_package(package, tmp_path, settings)

    with Image.open(paths[1]) as preview, Image.open(paths[3]) as timeline:
        assert preview.tobytes() != timeline.tobytes()


def test_summary_card_has_distinct_render(tmp_path: Path) -> None:
    settings = load_settings(ROOT / "config/settings.toml")
    package = load_package(ROOT / "fixtures/demo_package.json")
    paths = render_package(package, tmp_path, settings)

    with Image.open(paths[3]) as issue, Image.open(paths[4]) as summary:
        assert issue.tobytes() != summary.tobytes()


def test_structured_visual_items_change_the_rendered_card(tmp_path: Path) -> None:
    settings = load_settings(ROOT / "config/settings.toml")
    package = load_package(ROOT / "fixtures/demo_package.json")
    original_paths = render_package(package, tmp_path / "original", settings)
    first_item = package.cards[2].visual_items[0].model_copy(
        update={"value": "직접 바꾼 경기 정보"}
    )
    changed_card = package.cards[2].model_copy(
        update={"visual_items": [first_item, *package.cards[2].visual_items[1:]]}
    )
    changed_package = package.model_copy(
        update={"cards": [*package.cards[:2], changed_card, *package.cards[3:]]}
    )
    changed_paths = render_package(changed_package, tmp_path / "changed", settings)

    with Image.open(original_paths[2]) as original, Image.open(changed_paths[2]) as changed:
        assert original.tobytes() != changed.tobytes()


def test_renderer_removes_source_links_from_visible_copy() -> None:
    source = "공식 일정이 발표됐습니다. ([example.com](https://example.com/news))"
    cleaned = _clean_card_text(source)

    assert cleaned == "공식 일정이 발표됐습니다"
    assert "http" not in cleaned


def test_auto_template_uses_card_content_instead_of_slide_number() -> None:
    package = load_package(ROOT / "fixtures/demo_package.json")
    card = package.cards[1].model_copy(
        update={
            "visual_template": VisualTemplate.AUTO,
            "headline": "홈·원정 응원석 구분",
            "visual_direction": "좌석 구역을 두 부분으로 나눈다",
        }
    )

    assert _resolve_visual_template(card) == VisualTemplate.SEAT_SPLIT

