from __future__ import annotations

from pathlib import Path

from PIL import Image

from sports_card_news.config import load_settings
from sports_card_news.pipeline import load_package
from sports_card_news.renderer import render_package


ROOT = Path(__file__).parents[1]


def test_sports_desk_renderer_uses_editorial_palette(tmp_path: Path) -> None:
    settings = load_settings(ROOT / "config/settings.toml")
    package = load_package(ROOT / "fixtures/demo_package.json")

    paths = render_package(package, tmp_path, settings)

    assert len(paths) == 6
    with Image.open(paths[0]) as image:
        assert image.size == (1080, 1350)
        colors = {color for _, color in image.getcolors(maxcolors=2_000_000) or []}
        assert (244, 240, 232) in colors  # warm paper
        assert (255, 214, 61) in colors  # score yellow
        assert (17, 17, 17) in colors  # editorial ink
        assert (228, 66, 54) in colors  # review red


def test_story_cards_render_distinct_data_modules(tmp_path: Path) -> None:
    settings = load_settings(ROOT / "config/settings.toml")
    package = load_package(ROOT / "fixtures/demo_package.json")

    paths = render_package(package, tmp_path, settings)

    with Image.open(paths[1]) as schedule, Image.open(paths[3]) as status:
        assert schedule.tobytes() != status.tobytes()
