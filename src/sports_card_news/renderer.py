from __future__ import annotations

import os
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .config import Settings
from .models import Card, DailyPackage, VisualItem, VisualTemplate


CANVAS = (1080, 1350)
PAPER = "#F4F0E8"
INK = "#111111"
YELLOW = "#FFD63D"
RED = "#E44236"
MUTED = "#6B685F"
HAIRLINE = "#C9C3B8"
WHITE = "#FFFDF7"

MARKDOWN_CITATION = re.compile(r"\s*\(\s*\[[^\]]+\]\(https?://[^)]*\)\s*\)", re.IGNORECASE)
MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\(https?://[^)]*\)", re.IGNORECASE)
RAW_URL = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
BARE_DOMAIN = re.compile(r"\b(?:[a-z0-9-]+\.)+(?:com|net|org|kr|co\.kr)(?:/\S*)?", re.IGNORECASE)


def render_package(package: DailyPackage, destination: str | Path, settings: Settings) -> list[Path]:
    output = Path(destination)
    output.mkdir(parents=True, exist_ok=True)
    selected = next(item for item in package.candidates if item.title == package.selected_candidate_title)
    candidates_by_league = {item.league.upper(): item for item in package.candidates}
    issue_candidates = [
        item for league, item in candidates_by_league.items() if league in {"KBO", "KBL", "NPB", "EPL", "NBA"}
    ]
    cover_sport = f"{len({item.sport for item in issue_candidates})} SPORTS"
    total_slides = len(package.cards)
    paths: list[Path] = []

    for card in package.cards:
        candidate = candidates_by_league.get(card.league.value, selected)
        path = output / f"card-{card.slide:02d}.png"
        _render_card(
            card=card,
            sport=cover_sport if card.slide == 1 else candidate.sport,
            league=f"{len(issue_candidates)} LEAGUES" if card.slide == 1 else candidate.league,
            game_status=str(candidate.game_status),
            edition_date=package.edition_date,
            total_slides=total_slides,
            path=path,
            settings=settings,
        )
        paths.append(path)
    return paths


def _render_card(
    card: Card,
    sport: str,
    league: str,
    game_status: str,
    edition_date: str,
    total_slides: int,
    path: Path,
    settings: Settings,
) -> None:
    image = Image.new("RGB", CANVAS, PAPER)
    draw = ImageDraw.Draw(image)
    fonts = _load_fonts()

    _draw_paper_texture(draw)
    _draw_header(draw, fonts, edition_date)

    if card.slide == 1:
        _draw_cover(draw, fonts, card, sport, league, edition_date)
    else:
        _draw_story_card(draw, fonts, card, game_status)

    _draw_footer(draw, fonts, card, total_slides)

    if (settings.output_width, settings.output_height) != CANVAS:
        image = image.resize((settings.output_width, settings.output_height), Image.Resampling.LANCZOS)
    image.save(path, format="PNG", optimize=True)


def _load_fonts() -> dict[str, str]:
    return {
        "regular": _find_font("regular"),
        "bold": _find_font("bold"),
    }


def _font(fonts: dict[str, str], size: int, weight: str = "regular") -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(fonts[weight], size)


def _draw_paper_texture(draw: ImageDraw.ImageDraw) -> None:
    # Deterministic, very light paper grain keeps every automated render stable.
    grain = (232, 227, 217)
    light_grain = (248, 245, 238)
    for index in range(1850):
        x = (index * 73 + index * index * 17) % CANVAS[0]
        y = (index * 151 + index * index * 11) % CANVAS[1]
        draw.point((x, y), fill=grain if index % 3 else light_grain)


def _draw_header(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, str],
    edition_date: str,
) -> None:
    draw.line((70, 72, 1010, 72), fill=INK, width=3)
    draw.text((70, 90), "Daily Issue", font=_font(fonts, 25, "bold"), fill=INK)
    draw.text(
        (1010, 88),
        edition_date.replace("-", "."),
        font=_font(fonts, 23),
        fill=INK,
        anchor="ra",
    )
    draw.line((70, 134, 1010, 134), fill=INK, width=2)


def _draw_cover(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, str],
    card: Card,
    sport: str,
    league: str,
    edition_date: str,
) -> None:
    draw.text((70, 190), "DAILY SPORTS BRIEF", font=_font(fonts, 24, "bold"), fill=RED)
    draw.rectangle((70, 229, 130, 237), fill=RED)
    headline_text = _clean_card_text(card.headline)
    body_text = _clean_card_text(card.body)

    headline_font, headline_lines = _fit_text(
        draw,
        headline_text,
        fonts["bold"],
        max_width=655,
        max_lines=3,
        start_size=106,
        minimum_size=72,
    )
    line_height = _line_height(headline_font, 18)
    headline_y = 270
    highlight_index = min(1, len(headline_lines) - 1)
    highlight_top = headline_y + highlight_index * line_height + int(line_height * 0.56)
    highlight_width = int(draw.textlength(headline_lines[highlight_index], font=headline_font)) + 24
    draw.rectangle((58, highlight_top, 58 + highlight_width, highlight_top + 38), fill=YELLOW)
    draw.multiline_text(
        (70, headline_y),
        "\n".join(headline_lines),
        font=headline_font,
        fill=INK,
        spacing=18,
    )

    headline_bottom = headline_y + len(headline_lines) * line_height
    body_font, body_lines = _fit_text(
        draw,
        body_text,
        fonts["regular"],
        max_width=650,
        max_lines=5,
        start_size=43,
        minimum_size=31,
    )
    body_y = max(655, headline_bottom + 42)
    draw.line((70, body_y - 24, 650, body_y - 24), fill=INK, width=3)
    draw.multiline_text((70, body_y), "\n".join(body_lines), font=body_font, fill=INK, spacing=16)

    _draw_field_notation(draw, fonts)
    _draw_cover_facts(draw, fonts, sport, league, edition_date)


def _draw_field_notation(draw: ImageDraw.ImageDraw, fonts: dict[str, str]) -> None:
    left, top, right, bottom = 742, 275, 1010, 590
    draw.rectangle((left, top, right, bottom), outline=INK, width=3)
    middle_x = (left + right) // 2
    middle_y = (top + bottom) // 2
    draw.line((middle_x, top, middle_x, bottom), fill=INK, width=2)
    draw.ellipse((middle_x - 43, middle_y - 43, middle_x + 43, middle_y + 43), outline=INK, width=2)
    draw.arc((left - 48, middle_y - 82, left + 95, middle_y + 82), -90, 90, fill=INK, width=2)
    draw.arc((right - 95, middle_y - 82, right + 48, middle_y + 82), 90, 270, fill=INK, width=2)

    points = [(765, 550), (812, 500), (862, 429), (918, 375), (982, 335)]
    for start, end in zip(points, points[1:], strict=False):
        _draw_dashed_line(draw, start, end, INK, 3)
    draw.ellipse((969, 322, 995, 348), fill=INK)
    draw.text((1010, 610), "PLAY / DATA", font=_font(fonts, 18, "bold"), fill=MUTED, anchor="ra")
    draw.rectangle((992, 643, 1010, 649), fill=RED)


def _draw_cover_facts(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, str],
    sport: str,
    league: str,
    edition_date: str,
) -> None:
    top, bottom = 1000, 1185
    labels = (("SPORT", sport), ("LEAGUE", league), ("EDITION", edition_date[5:]), ("REVIEW", "REQUIRED"))
    cell_width = 940 / len(labels)
    draw.rectangle((70, top, 1010, bottom), outline=INK, width=3)
    draw.rectangle((70, top, 1010, top + 52), fill=YELLOW)
    for index, (label, value) in enumerate(labels):
        left = round(70 + index * cell_width)
        right = round(70 + (index + 1) * cell_width)
        if index:
            draw.line((left, top, left, bottom), fill=INK, width=2)
        draw.text(((left + right) // 2, top + 13), label, font=_font(fonts, 20, "bold"), fill=INK, anchor="ma")
        value_font, value_lines = _fit_text(
            draw,
            value,
            fonts["bold"],
            max_width=int(cell_width - 28),
            max_lines=2,
            start_size=35,
            minimum_size=24,
        )
        draw.multiline_text(
            ((left + right) // 2, top + 91),
            "\n".join(value_lines),
            font=value_font,
            fill=INK,
            spacing=4,
            anchor="ma",
            align="center",
        )


def _draw_story_card(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, str],
    card: Card,
    game_status: str,
) -> None:
    draw.text((70, 185), f"{card.slide - 1:02d}", font=_font(fonts, 108, "bold"), fill=INK)
    draw.ellipse((202, 267, 220, 285), fill=RED)
    draw.text(
        (1010, 205),
        f"{card.league.value} / DAILY BRIEF",
        font=_font(fonts, 19, "bold"),
        fill=MUTED,
        anchor="ra",
    )
    if card.kicker:
        draw.rectangle((760, 242, 1010, 285), fill=INK)
        draw.text(
            (985, 263),
            card.kicker.upper(),
            font=_font(fonts, 17, "bold"),
            fill=WHITE,
            anchor="rm",
        )
    headline_text = _clean_card_text(card.headline)
    body_text = _clean_card_text(card.body)

    headline_font, headline_lines = _fit_text(
        draw,
        headline_text,
        fonts["bold"],
        max_width=940,
        max_lines=2,
        start_size=82,
        minimum_size=58,
    )
    headline_y = 340
    line_height = _line_height(headline_font, 14)
    band_y = headline_y + min(1, len(headline_lines) - 1) * line_height + int(line_height * 0.58)
    band_width = min(620, int(draw.textlength(headline_lines[-1], font=headline_font)) + 22)
    draw.rectangle((58, band_y, 58 + band_width, band_y + 30), fill=YELLOW)
    draw.multiline_text((70, headline_y), "\n".join(headline_lines), font=headline_font, fill=INK, spacing=14)

    body_y = headline_y + len(headline_lines) * line_height + 55
    body_font, body_lines = _fit_text(
        draw,
        body_text,
        fonts["regular"],
        max_width=900,
        max_lines=5,
        start_size=39,
        minimum_size=28,
    )
    draw.multiline_text((70, body_y), "\n".join(body_lines), font=body_font, fill=INK, spacing=15)

    panel_top = max(745, body_y + len(body_lines) * _line_height(body_font, 15) + 40)
    panel_top = min(panel_top, 835)
    template = _resolve_visual_template(card)
    if template == VisualTemplate.MATCH_RESULT:
        _draw_match_result_module(draw, fonts, panel_top, card)
    elif template == VisualTemplate.MATCH_PREVIEW:
        _draw_match_preview_module(draw, fonts, panel_top, card)
    elif template == VisualTemplate.PLAYER:
        _draw_player_module(draw, fonts, panel_top, card)
    elif template in {VisualTemplate.STAT, VisualTemplate.RANKING}:
        _draw_stat_module(draw, fonts, panel_top, card)
    elif template == VisualTemplate.BREAKING:
        _draw_breaking_module(draw, fonts, panel_top, card)
    elif template == VisualTemplate.SCHEDULE:
        _draw_schedule_module(draw, fonts, panel_top, card.visual_title, card.visual_items)
    elif template == VisualTemplate.THREE_SCREEN:
        _draw_three_screen_module(draw, fonts, panel_top, card)
    elif template in {VisualTemplate.SEAT_SPLIT, VisualTemplate.LOCATION, VisualTemplate.STEPS}:
        _draw_visual_rows(draw, fonts, panel_top, card.visual_title, card.visual_items)
    elif template == VisualTemplate.TIMELINE:
        _draw_schedule_module(draw, fonts, panel_top, card.visual_title, card.visual_items)
    elif template == VisualTemplate.COMPARISON:
        _draw_official_module(draw, fonts, panel_top, card.visual_title, card.visual_items)
    elif template == VisualTemplate.STATUS:
        _draw_status_module(draw, fonts, panel_top, game_status, card.visual_title, card.visual_items)
    elif template == VisualTemplate.SOURCES:
        _draw_sources_module(draw, fonts, panel_top, card.source_ids)
    elif template == VisualTemplate.APPROVAL:
        _draw_approval_module(draw, fonts, panel_top)
    else:
        _draw_key_fact_module(draw, fonts, panel_top, card.visual_title, card.visual_items)


def _clean_card_text(text: str) -> str:
    """Keep only reader-facing copy; source locations belong in package metadata."""
    cleaned = MARKDOWN_CITATION.sub("", text)
    cleaned = MARKDOWN_LINK.sub(r"\1", cleaned)
    cleaned = RAW_URL.sub("", cleaned)
    cleaned = BARE_DOMAIN.sub("", cleaned)
    cleaned = re.sub(r"\(\s*\)", "", cleaned)
    cleaned = re.sub(r"\s+([,.!?。！？])", r"\1", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip(" -·,.") or "상세 내용은 출처 검토 후 확정합니다"


def _resolve_visual_template(card: Card) -> VisualTemplate:
    if card.visual_template != VisualTemplate.AUTO:
        return card.visual_template

    context = f"{card.headline} {card.body} {card.visual_direction}".lower()
    keyword_templates = (
        (("3면", "세 화면", "스크린", "screen"), VisualTemplate.THREE_SCREEN),
        (("좌석", "응원석", "홈·원정", "홈 원정"), VisualTemplate.SEAT_SPLIT),
        (("장소", "위치", "지점", "경기장", "상영관"), VisualTemplate.LOCATION),
        (("방법", "단계", "순서", "예매", "신청"), VisualTemplate.STEPS),
        (("일정", "시간", "시각", "날짜", "달력"), VisualTemplate.TIMELINE),
        (("비교", "구분", "확정", "발표"), VisualTemplate.COMPARISON),
        (("상태", "진행", "종료", "연기", "취소"), VisualTemplate.STATUS),
        (("출처", "근거", "자료"), VisualTemplate.SOURCES),
        (("승인", "검토", "체크"), VisualTemplate.APPROVAL),
    )
    for keywords, template in keyword_templates:
        if any(keyword in context for keyword in keywords):
            return template
    return VisualTemplate.KEY_FACT


def _draw_three_screen_module(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, str],
    top: int,
    card: Card,
) -> None:
    _panel(draw, top)
    draw.text((100, top + 32), card.visual_title, font=_font(fonts, 25, "bold"), fill=MUTED)
    defaults = (
        VisualItem(label="범위", value="공식 발표 확인"),
        VisualItem(label="핵심", value="3면 영상"),
        VisualItem(label="상태", value="세부 일정 확인"),
    )
    items = tuple(card.visual_items[:3])
    items = items + defaults[len(items):]
    panels = ((115, items[0]), (385, items[1]), (730, items[2]))
    widths = (285, 310, 285)
    for index, ((left, item), width) in enumerate(zip(panels, widths, strict=True)):
        y = top + (125 if index == 1 else 155)
        height = 235 if index == 1 else 205
        fill = YELLOW if index == 1 else WHITE
        draw.rounded_rectangle((left, y, left + width, y + height), radius=14, fill=fill, outline=INK, width=3)
        draw.line((left + 28, y + height - 42, left + width - 28, y + height - 42), fill=INK, width=2)
        value_font, value_lines = _fit_text(
            draw, item.value, fonts["bold"], width - 34, 2, 29, 21
        )
        draw.multiline_text(
            (left + width // 2, y + height // 2 - 12),
            "\n".join(value_lines),
            font=value_font,
            fill=INK,
            spacing=5,
            anchor="mm",
            align="center",
        )
        draw.text(
            (left + width // 2, y + height - 28),
            item.label,
            font=_font(fonts, 18, "bold"),
            fill=MUTED,
            anchor="mm",
        )
    note = next((item.note for item in items if item.note), "실제 정보는 공식 원문 기준")
    draw.text((540, top + 382), note, font=_font(fonts, 22), fill=MUTED, anchor="ma")


def _draw_seat_split_module(draw: ImageDraw.ImageDraw, fonts: dict[str, str], top: int) -> None:
    _panel(draw, top)
    middle = 540
    draw.line((middle, top + 76, middle, 1165), fill=INK, width=3)
    draw.rectangle((70, top, middle, top + 76), fill=YELLOW)
    draw.rectangle((middle, top, 1010, top + 76), fill=INK)
    draw.text((305, top + 38), "홈 응원 구역", font=_font(fonts, 29, "bold"), fill=INK, anchor="mm")
    draw.text((775, top + 38), "원정 응원 구역", font=_font(fonts, 29, "bold"), fill=WHITE, anchor="mm")
    for column, base_x in enumerate((145, 615)):
        for row in range(3):
            y = top + 130 + row * 76
            for seat in range(4):
                x = base_x + seat * 76
                fill = RED if column == 0 and row == 0 else (YELLOW if column == 1 and row == 0 else WHITE)
                draw.rounded_rectangle((x, y, x + 50, y + 42), radius=7, fill=fill, outline=INK, width=2)
    draw.rectangle((245, top + 330, 835, top + 377), fill=WHITE)
    draw.text((540, top + 350), "예매 전 상영관별 실제 좌석 배치를 확인하세요", font=_font(fonts, 24), fill=MUTED, anchor="ma")


def _draw_location_module(draw: ImageDraw.ImageDraw, fonts: dict[str, str], top: int) -> None:
    _panel(draw, top)
    pin_x, pin_y = 260, top + 205
    draw.ellipse((pin_x - 75, pin_y - 105, pin_x + 75, pin_y + 45), fill=YELLOW, outline=INK, width=4)
    draw.polygon(((pin_x - 48, pin_y + 5), (pin_x + 48, pin_y + 5), (pin_x, pin_y + 105)), fill=YELLOW, outline=INK)
    draw.ellipse((pin_x - 22, pin_y - 52, pin_x + 22, pin_y - 8), fill=INK)
    draw.text((430, top + 112), "상영 지점 확인", font=_font(fonts, 39, "bold"), fill=INK)
    details = (("01", "지점"), ("02", "회차"), ("03", "시작 시각"))
    for index, (number, label) in enumerate(details):
        y = top + 180 + index * 65
        draw.text((435, y), number, font=_font(fonts, 22, "bold"), fill=RED)
        draw.text((515, y), label, font=_font(fonts, 29, "bold"), fill=INK)
        draw.line((690, y + 22, 930, y + 22), fill=HAIRLINE, width=2)
    draw.text((540, top + 380), "공식 안내에서 최종 장소를 확인하세요", font=_font(fonts, 23), fill=MUTED, anchor="ma")


def _draw_steps_module(draw: ImageDraw.ImageDraw, fonts: dict[str, str], top: int) -> None:
    _panel(draw, top)
    steps = (("01", "공식 안내 확인"), ("02", "지점·회차 선택"), ("03", "최종 조건 확인"))
    row_height = (1165 - top) // len(steps)
    for index, (number, label) in enumerate(steps):
        row_top = top + index * row_height
        if index:
            draw.line((200, row_top, 1010, row_top), fill=HAIRLINE, width=2)
        draw.rectangle((70, row_top, 200, row_top + row_height), fill=YELLOW if index == 0 else INK)
        draw.text((135, row_top + row_height // 2), number, font=_font(fonts, 34, "bold"), fill=INK if index == 0 else WHITE, anchor="mm")
        draw.text((245, row_top + row_height // 2), label, font=_font(fonts, 33, "bold"), fill=INK, anchor="lm")
        draw.text((955, row_top + row_height // 2), "→", font=_font(fonts, 34, "bold"), fill=RED, anchor="rm")


def _draw_match_result_module(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, str],
    top: int,
    card: Card,
) -> None:
    _panel(draw, top)
    draw.rectangle((70, top, 1010, top + 68), fill=INK)
    draw.text((100, top + 34), card.visual_title, font=_font(fonts, 25, "bold"), fill=WHITE, anchor="lm")
    items = list(card.visual_items[:4])
    if len(items) >= 2:
        left, right = items[0], items[1]
        draw.text((260, top + 150), left.label, font=_font(fonts, 24, "bold"), fill=MUTED, anchor="mm")
        draw.text((820, top + 150), right.label, font=_font(fonts, 24, "bold"), fill=MUTED, anchor="mm")
        lf, ll = _fit_text(draw, left.value, fonts["bold"], 310, 2, 62, 36)
        rf, rl = _fit_text(draw, right.value, fonts["bold"], 310, 2, 62, 36)
        draw.multiline_text((260, top + 245), "\n".join(ll), font=lf, fill=INK, spacing=6, anchor="mm", align="center")
        draw.multiline_text((820, top + 245), "\n".join(rl), font=rf, fill=INK, spacing=6, anchor="mm", align="center")
        draw.text((540, top + 240), "—", font=_font(fonts, 70, "bold"), fill=RED, anchor="mm")
    if len(items) > 2:
        note = " · ".join(f"{item.label} {item.value}" for item in items[2:])
        nf, nl = _fit_text(draw, note, fonts["bold"], 840, 2, 28, 21)
        draw.multiline_text((540, top + 390), "\n".join(nl), font=nf, fill=INK, spacing=4, anchor="mm", align="center")


def _draw_match_preview_module(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, str],
    top: int,
    card: Card,
) -> None:
    _panel(draw, top)
    draw.rectangle((70, top, 1010, top + 68), fill=YELLOW)
    draw.text((100, top + 34), card.visual_title, font=_font(fonts, 25, "bold"), fill=INK, anchor="lm")
    items = list(card.visual_items[:4])
    if items:
        lead = items[0]
        vf, vl = _fit_text(draw, lead.value, fonts["bold"], 760, 2, 52, 34)
        draw.multiline_text((540, top + 175), "\n".join(vl), font=vf, fill=INK, spacing=5, anchor="mm", align="center")
        draw.text((540, top + 255), lead.label, font=_font(fonts, 22, "bold"), fill=RED, anchor="mm")
    for index, item in enumerate(items[1:4]):
        left = 115 + index * 300
        draw.rounded_rectangle((left, top + 310, left + 250, top + 415), radius=14, outline=INK, width=3)
        draw.text((left + 125, top + 340), item.label, font=_font(fonts, 19, "bold"), fill=MUTED, anchor="mm")
        value_font, value_lines = _fit_text(draw, item.value, fonts["bold"], 215, 2, 27, 20)
        draw.multiline_text((left + 125, top + 382), "\n".join(value_lines), font=value_font, fill=INK, spacing=3, anchor="mm", align="center")


def _draw_player_module(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, str],
    top: int,
    card: Card,
) -> None:
    _panel(draw, top)
    draw.ellipse((105, top + 105, 345, top + 345), fill=YELLOW, outline=INK, width=4)
    draw.text((225, top + 225), "PLAYER", font=_font(fonts, 27, "bold"), fill=INK, anchor="mm")
    draw.text((400, top + 88), card.visual_title, font=_font(fonts, 28, "bold"), fill=INK)
    for index, item in enumerate(card.visual_items[:4]):
        y = top + 145 + index * 72
        draw.text((405, y), item.label, font=_font(fonts, 20, "bold"), fill=RED)
        vf, vl = _fit_text(draw, item.value, fonts["bold"], 430, 1, 34, 24)
        draw.text((575, y), vl[0], font=vf, fill=INK)


def _draw_stat_module(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, str],
    top: int,
    card: Card,
) -> None:
    _panel(draw, top)
    draw.text((100, top + 42), card.visual_title, font=_font(fonts, 27, "bold"), fill=INK)
    items = list(card.visual_items[:4])
    cell_w = 430
    for index, item in enumerate(items):
        row, col = divmod(index, 2)
        left = 95 + col * 465
        upper = top + 90 + row * 165
        draw.rounded_rectangle((left, upper, left + cell_w, upper + 140), radius=16, fill=WHITE, outline=INK, width=3)
        draw.text((left + 24, upper + 28), item.label, font=_font(fonts, 19, "bold"), fill=RED)
        vf, vl = _fit_text(draw, item.value, fonts["bold"], 360, 2, 42, 27)
        draw.multiline_text((left + 24, upper + 72), "\n".join(vl), font=vf, fill=INK, spacing=3)


def _draw_breaking_module(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, str],
    top: int,
    card: Card,
) -> None:
    _panel(draw, top)
    draw.rectangle((70, top, 1010, top + 92), fill=RED)
    draw.text((100, top + 46), "BREAKING", font=_font(fonts, 31, "bold"), fill=WHITE, anchor="lm")
    tf, tl = _fit_text(draw, card.visual_title, fonts["bold"], 840, 2, 46, 31)
    draw.multiline_text((100, top + 145), "\n".join(tl), font=tf, fill=INK, spacing=6)
    if card.visual_items:
        item = card.visual_items[0]
        vf, vl = _fit_text(draw, item.value, fonts["bold"], 820, 2, 42, 27)
        draw.multiline_text((100, top + 300), "\n".join(vl), font=vf, fill=INK, spacing=4)
        if item.note:
            draw.text((100, top + 395), item.note, font=_font(fonts, 20), fill=MUTED)


def _draw_key_fact_module(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, str],
    top: int,
    title: str,
    items: list[VisualItem],
) -> None:
    _draw_visual_rows(draw, fonts, top, title, items)


def _draw_schedule_module(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, str],
    top: int,
    title: str,
    items: list[VisualItem],
) -> None:
    _draw_visual_rows(draw, fonts, top, title, items)


def _draw_official_module(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, str],
    top: int,
    title: str,
    items: list[VisualItem],
) -> None:
    _panel(draw, top)
    draw.rectangle((70, top, 1010, top + 70), fill=YELLOW)
    draw.text((100, top + 35), title, font=_font(fonts, 27, "bold"), fill=INK, anchor="lm")
    shown = items[:4]
    cell_width = 940 / len(shown)
    for index, item in enumerate(shown):
        left = round(70 + index * cell_width)
        right = round(70 + (index + 1) * cell_width)
        if index:
            draw.line((left, top + 70, left, 1165), fill=INK, width=2)
        draw.text(
            ((left + right) // 2, top + 112),
            item.label,
            font=_font(fonts, 21, "bold"),
            fill=RED,
            anchor="ma",
        )
        value_font, value_lines = _fit_text(
            draw, item.value, fonts["bold"], int(cell_width - 28), 3, 38, 25
        )
        draw.multiline_text(
            ((left + right) // 2, top + 205),
            "\n".join(value_lines),
            font=value_font,
            fill=INK,
            spacing=5,
            anchor="ma",
            align="center",
        )
        if item.note:
            note_font, note_lines = _fit_text(
                draw, item.note, fonts["regular"], int(cell_width - 28), 2, 21, 17
            )
            draw.multiline_text(
                ((left + right) // 2, top + 350),
                "\n".join(note_lines),
                font=note_font,
                fill=MUTED,
                spacing=3,
                anchor="ma",
                align="center",
            )


def _draw_status_module(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, str],
    top: int,
    game_status: str,
    title: str,
    items: list[VisualItem],
) -> None:
    status_items = list(items)
    if not any(item.label == "상태" for item in status_items):
        status_items.insert(
            0,
            VisualItem(label="상태", value=game_status, note="생성 시점 기준"),
        )
    _draw_visual_rows(draw, fonts, top, title, status_items[:4])


def _draw_visual_rows(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, str],
    top: int,
    title: str,
    items: list[VisualItem],
) -> None:
    _panel(draw, top)
    draw.rectangle((70, top, 1010, top + 70), fill=YELLOW)
    draw.text((100, top + 35), title, font=_font(fonts, 27, "bold"), fill=INK, anchor="lm")
    shown = items[:4]
    content_top = top + 70
    row_height = (1165 - content_top) // len(shown)
    for index, item in enumerate(shown):
        row_top = content_top + index * row_height
        if index:
            draw.line((200, row_top, 1010, row_top), fill=HAIRLINE, width=2)
        draw.rectangle(
            (70, row_top, 200, row_top + row_height),
            fill=INK if index else WHITE,
        )
        draw.text(
            (135, row_top + row_height // 2),
            item.label,
            font=_font(fonts, 23, "bold"),
            fill=WHITE if index else RED,
            anchor="mm",
        )
        value_font, value_lines = _fit_text(
            draw, item.value, fonts["bold"], 500, 2, 31, 23
        )
        draw.multiline_text(
            (235, row_top + row_height // 2),
            "\n".join(value_lines),
            font=value_font,
            fill=INK,
            spacing=4,
            anchor="lm",
        )
        if item.note:
            note_font, note_lines = _fit_text(
                draw, item.note, fonts["regular"], 245, 2, 21, 17
            )
            draw.multiline_text(
                (970, row_top + row_height // 2),
                "\n".join(note_lines),
                font=note_font,
                fill=MUTED,
                spacing=3,
                anchor="rm",
                align="right",
            )


def _draw_sources_module(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, str],
    top: int,
    source_ids: list[str],
) -> None:
    _panel(draw, top)
    source_count = max(1, len(source_ids))
    center = (540, top + 188)
    draw.rounded_rectangle((395, top + 128, 685, top + 248), radius=18, fill=INK)
    draw.text(center, "핵심 주장", font=_font(fonts, 31, "bold"), fill=WHITE, anchor="mm")
    for index in range(source_count):
        source_label = f"공식 {index + 1}"
        x = round(175 + index * (730 / max(source_count - 1, 1))) if source_count > 1 else 540
        y = top + 330
        draw.line((center[0], center[1] + 60, x, y - 42), fill=RED, width=3)
        draw.ellipse((x - 48, y - 48, x + 48, y + 48), fill=YELLOW, outline=INK, width=3)
        draw.text((x, y), source_label, font=_font(fonts, 22, "bold"), fill=INK, anchor="mm")


def _draw_approval_module(draw: ImageDraw.ImageDraw, fonts: dict[str, str], top: int) -> None:
    _panel(draw, top)
    roles = (("01", "종목 담당"), ("02", "팩트·권리"), ("03", "편집장"))
    row_height = (1165 - top) // len(roles)
    for index, (number, role) in enumerate(roles):
        y = top + index * row_height
        if index:
            draw.line((70, y, 1010, y), fill=HAIRLINE, width=2)
        draw.text((105, y + row_height // 2), number, font=_font(fonts, 27, "bold"), fill=RED, anchor="lm")
        draw.text((210, y + row_height // 2), role, font=_font(fonts, 33, "bold"), fill=INK, anchor="lm")
        box = (890, y + row_height // 2 - 26, 942, y + row_height // 2 + 26)
        draw.rounded_rectangle(box, radius=7, outline=INK, width=3)
        draw.text((865, y + row_height // 2), "승인", font=_font(fonts, 21, "bold"), fill=MUTED, anchor="rm")


def _panel(draw: ImageDraw.ImageDraw, top: int) -> None:
    draw.rounded_rectangle((70, top, 1010, 1165), radius=18, fill=WHITE, outline=INK, width=3)


def _draw_footer(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, str],
    card: Card,
    total_slides: int,
) -> None:
    page_text = f"PAGE  {card.slide:02d} / {total_slides:02d}"
    draw.line((70, 1232, 1010, 1232), fill=INK, width=2)
    draw.text((70, 1267), page_text, font=_font(fonts, 21, "bold"), fill=MUTED)
    draw.rectangle((851, 1259, 869, 1282), fill=RED)
    draw.text((1010, 1267), "Daily._.hor", font=_font(fonts, 20, "bold"), fill=INK, anchor="ra")


def _fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font_path: str,
    max_width: int,
    max_lines: int,
    start_size: int,
    minimum_size: int,
) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    for size in range(start_size, minimum_size - 1, -2):
        font = ImageFont.truetype(font_path, size)
        lines = _wrap_by_pixels(draw, text, font, max_width)
        if len(lines) <= max_lines:
            return font, lines
    font = ImageFont.truetype(font_path, minimum_size)
    lines = _wrap_by_pixels(draw, text, font, max_width)
    visible_lines = lines[:max_lines]
    if len(lines) > max_lines and visible_lines:
        visible_lines[-1] = _ellipsize(draw, visible_lines[-1], font, max_width)
    return font, visible_lines


def _ellipsize(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> str:
    candidate = text.rstrip() + "…"
    while text and draw.textlength(candidate, font=font) > max_width:
        text = text[:-1].rstrip()
        candidate = text + "…"
    return candidate


def _wrap_by_pixels(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> list[str]:
    lines: list[str] = []
    for paragraph in text.splitlines() or [text]:
        current = ""
        for character in paragraph:
            candidate = current + character
            if not current or draw.textlength(candidate, font=font) <= max_width:
                current = candidate
                continue
            lines.append(current.rstrip())
            current = character.lstrip()
        if current:
            lines.append(current.rstrip())
    return lines or [""]


def _line_height(font: ImageFont.FreeTypeFont, spacing: int) -> int:
    box = font.getbbox("가Ag")
    return box[3] - box[1] + spacing


def _draw_dashed_line(
    draw: ImageDraw.ImageDraw,
    start: tuple[int, int],
    end: tuple[int, int],
    fill: str,
    width: int,
) -> None:
    x1, y1 = start
    x2, y2 = end
    segments = 10
    for index in range(segments):
        if index % 2:
            continue
        begin = index / segments
        finish = (index + 1) / segments
        draw.line(
            (
                round(x1 + (x2 - x1) * begin),
                round(y1 + (y2 - y1) * begin),
                round(x1 + (x2 - x1) * finish),
                round(y1 + (y2 - y1) * finish),
            ),
            fill=fill,
            width=width,
        )


def _find_font(weight: str = "regular") -> str:
    custom = os.getenv("CARD_NEWS_FONT", "")
    regular = [
        custom,
        "C:/Windows/Fonts/malgun.ttf",
        "C:/Windows/Fonts/NotoSansKR-Regular.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansKR-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    bold = [
        os.getenv("CARD_NEWS_BOLD_FONT", ""),
        "C:/Windows/Fonts/malgunbd.ttf",
        "C:/Windows/Fonts/NotoSansKR-Bold.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansKR-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        *regular,
    ]
    for candidate in bold if weight == "bold" else regular:
        if candidate and Path(candidate).exists():
            return candidate
    raise FileNotFoundError(
        "한글 폰트를 찾지 못했습니다. CARD_NEWS_FONT 환경 변수에 TTF/TTC 경로를 지정하세요."
    )
