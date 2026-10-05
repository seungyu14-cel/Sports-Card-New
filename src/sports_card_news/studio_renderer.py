from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .renderer import _find_font, _fit_text
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .studio import StudioPackage


CANVAS = (1080, 1350)
INK = "#101418"
WHITE = "#FFFFFF"


def render_studio_package(package: "StudioPackage", destination: str | Path) -> list[Path]:
    output = Path(destination)
    output.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for card in package.cards:
        path = output / f"card-{card.slide:02d}.png"
        _render_card(package, card, path)
        paths.append(path)
    return paths


def _render_card(package: "StudioPackage", card, path: Path) -> None:
    theme = package.theme
    image = Image.new("RGB", CANVAS, theme.paper)
    draw = ImageDraw.Draw(image)
    regular = _find_font("regular")
    bold = _find_font("bold")

    # Editorial frame
    draw.rectangle((0, 0, 1080, 185), fill=theme.primary)
    draw.rectangle((0, 185, 1080, 196), fill=theme.accent)
    draw.text((70, 60), "SPORTS DAILY CARD NEWS", font=ImageFont.truetype(bold, 26), fill=WHITE)
    draw.text(
        (1010, 62),
        f"{package.sport} · {package.league}",
        font=ImageFont.truetype(bold, 22),
        fill=theme.accent,
        anchor="ra",
    )
    draw.text(
        (70, 130),
        package.edition_date.replace("-", "."),
        font=ImageFont.truetype(regular, 20),
        fill="#D8E0DE",
    )

    # Kicker
    draw.rounded_rectangle((70, 248, 360, 302), radius=27, fill=theme.secondary)
    draw.text(
        (215, 275),
        card.kicker or card.role,
        font=ImageFont.truetype(bold, 19),
        fill=WHITE,
        anchor="mm",
    )

    headline_font, headline_lines = _fit_text(
        draw, card.headline, bold, 900, 3, 72 if card.slide == 1 else 62, 42
    )
    draw.multiline_text(
        (70, 350),
        "\n".join(headline_lines),
        font=headline_font,
        fill=INK,
        spacing=12,
    )
    headline_height = sum(
        headline_font.getbbox(line or "가")[3] - headline_font.getbbox(line or "가")[1] + 12
        for line in headline_lines
    )

    body_y = min(720, 390 + headline_height + 70)
    body_font, body_lines = _fit_text(draw, card.body, regular, 870, 5, 34, 26)
    draw.multiline_text(
        (70, body_y),
        "\n".join(body_lines),
        font=body_font,
        fill="#39434A",
        spacing=13,
    )

    # Key-stat block
    block_top = 910
    draw.rounded_rectangle(
        (70, block_top, 1010, 1138),
        radius=30,
        fill=theme.primary,
    )
    draw.text(
        (110, block_top + 55),
        "KEY",
        font=ImageFont.truetype(bold, 19),
        fill=theme.accent,
    )
    key_font, key_lines = _fit_text(
        draw, card.key_stat or package.master_headline, bold, 780, 2, 48, 32
    )
    draw.multiline_text(
        (110, block_top + 102),
        "\n".join(key_lines),
        font=key_font,
        fill=WHITE,
        spacing=8,
    )

    # Footer
    draw.line((70, 1212, 1010, 1212), fill=theme.secondary, width=2)
    draw.text(
        (70, 1250),
        f"PAGE {card.slide:02d} / 07",
        font=ImageFont.truetype(bold, 20),
        fill=theme.secondary,
    )
    draw.text(
        (1010, 1250),
        "스포츠 데일리 카드 뉴스 제작소",
        font=ImageFont.truetype(bold, 20),
        fill=INK,
        anchor="ra",
    )

    image.save(path, format="PNG", optimize=True)
