from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .config import Settings
from .models import Card, DailyPackage


PALETTES = {
    "야구": ("#071E3D", "#21E6C1", "#278EA5"),
    "축구": ("#102A13", "#A8FF3E", "#2F6B37"),
    "농구": ("#2B1207", "#FF7A00", "#8A3210"),
    "기타": ("#1C1538", "#C5A3FF", "#5A3D96"),
}


def render_package(package: DailyPackage, destination: str | Path, settings: Settings) -> list[Path]:
    output = Path(destination)
    output.mkdir(parents=True, exist_ok=True)
    selected = next(item for item in package.candidates if item.title == package.selected_candidate_title)
    palette = PALETTES.get(selected.sport, PALETTES["기타"])
    paths: list[Path] = []
    for card in package.cards:
        path = output / f"card-{card.slide:02d}.png"
        _render_card(card, selected.sport, selected.league, palette, path, settings)
        paths.append(path)
    return paths


def _render_card(
    card: Card,
    sport: str,
    league: str,
    palette: tuple[str, str, str],
    path: Path,
    settings: Settings,
) -> None:
    width, height = settings.output_width, settings.output_height
    background, accent, secondary = palette
    image = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(image)
    _draw_gradient(draw, width, height, background, secondary)

    font_path = _find_font()
    small = ImageFont.truetype(font_path, 34)
    label = ImageFont.truetype(font_path, 38)
    headline_size, body_size = _fit_sizes(card)
    headline = ImageFont.truetype(font_path, headline_size)
    body = ImageFont.truetype(font_path, body_size)
    marker = ImageFont.truetype(font_path, 150)

    draw.rounded_rectangle((70, 70, 390, 138), radius=34, fill=accent)
    draw.text((100, 84), f"{sport}  ·  {league}", font=label, fill=background)
    draw.text((850, 65), f"{card.slide:02d}", font=marker, fill=_with_alpha_color(accent, 0.35), anchor="ma")

    headline_lines = _wrap_by_pixels(draw, card.headline, headline, width - 140)
    headline_text = "\n".join(headline_lines)
    draw.multiline_text((70, 300), headline_text, font=headline, fill="#FFFFFF", spacing=18)
    headline_box = draw.multiline_textbbox((70, 300), headline_text, font=headline, spacing=18)

    rule_y = min(headline_box[3] + 55, 680)
    draw.rounded_rectangle((70, rule_y, 330, rule_y + 12), radius=6, fill=accent)

    body_lines = _wrap_by_pixels(draw, card.body, body, width - 140)
    body_text = "\n".join(body_lines[:7])
    draw.multiline_text((70, rule_y + 65), body_text, font=body, fill="#F2F5F8", spacing=20)

    source_text = "출처  " + (" · ".join(card.source_ids) if card.source_ids else "검토 체크리스트 참조")
    draw.text((70, height - 120), source_text, font=small, fill="#C7D1DB")
    draw.text((width - 70, height - 120), "HUMAN REVIEW REQUIRED", font=small, fill=accent, anchor="ra")

    image.save(path, format="PNG", optimize=True)


def _draw_gradient(draw: ImageDraw.ImageDraw, width: int, height: int, top: str, bottom: str) -> None:
    top_rgb = _hex_rgb(top)
    bottom_rgb = _hex_rgb(bottom)
    for y in range(height):
        ratio = y / max(height - 1, 1)
        rgb = tuple(round(a + (b - a) * ratio) for a, b in zip(top_rgb, bottom_rgb, strict=True))
        draw.line((0, y, width, y), fill=rgb)
    draw.ellipse((700, -220, 1240, 320), fill=_mix(_hex_rgb(top), _hex_rgb(bottom), 0.55))
    draw.ellipse((-220, 1040, 300, 1560), fill=_mix(_hex_rgb(top), _hex_rgb(bottom), 0.7))


def _fit_sizes(card: Card) -> tuple[int, int]:
    headline_size = 86 if len(card.headline) <= 22 else 72
    body_size = 48 if len(card.body) <= 110 else 42
    return headline_size, body_size


def _wrap_by_pixels(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> list[str]:
    lines: list[str] = []
    for paragraph in text.splitlines() or [text]:
        current = ""
        tokens = paragraph.split(" ") if " " in paragraph else list(paragraph)
        separator = " " if " " in paragraph else ""
        for token in tokens:
            candidate = token if not current else current + separator + token
            if draw.textlength(candidate, font=font) <= max_width:
                current = candidate
            else:
                if current:
                    lines.append(current)
                current = token
        if current:
            lines.append(current)
    return lines or [""]


def _find_font() -> str:
    candidates = [
        os.getenv("CARD_NEWS_FONT", ""),
        "C:/Windows/Fonts/malgun.ttf",
        "C:/Windows/Fonts/NotoSansKR-Regular.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansKR-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    raise FileNotFoundError(
        "한글 폰트를 찾지 못했습니다. CARD_NEWS_FONT 환경 변수에 TTF/TTC 경로를 지정하세요."
    )


def _hex_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[index : index + 2], 16) for index in (0, 2, 4))  # type: ignore[return-value]


def _mix(left: tuple[int, int, int], right: tuple[int, int, int], ratio: float) -> tuple[int, int, int]:
    return tuple(round(a * (1 - ratio) + b * ratio) for a, b in zip(left, right, strict=True))


def _with_alpha_color(value: str, ratio: float) -> tuple[int, int, int]:
    # RGB 캔버스에서는 투명도 대신 배경과 혼합한 색을 사용한다.
    return _mix(_hex_rgb(value), (255, 255, 255), 1 - ratio)
