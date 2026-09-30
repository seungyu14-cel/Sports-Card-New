from __future__ import annotations

import json
import re
import sys
import zipfile
from datetime import date, timedelta
from pathlib import Path

from PIL import Image

from .config import Settings
from .generator import generate_daily_package, repair_daily_package
from .history import recent_publication_summary
from .models import DailyPackage
from .renderer import render_package
from .validation import ValidationReport, validate_package


def load_package(path: str | Path) -> DailyPackage:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    # Keep packages from earlier releases readable. The fixed league sequence is
    # also used as a safe migration default for publication history.
    legacy_leagues = ("COVER", "KBO", "KBL", "NPB", "EPL", "NBA")
    for card in payload.get("cards", []):
        default_template = "cover" if card.get("slide") == 1 else "auto"
        card.setdefault("visual_template", default_template)
        slide_index = int(card.get("slide", 1)) - 1
        if 0 <= slide_index < len(legacy_leagues):
            card.setdefault("league", legacy_leagues[slide_index])
        headline = str(card.get("headline", "핵심 정보")).splitlines()[0]
        body = str(card.get("body", "")).replace("\n", " ")
        card.setdefault("visual_title", headline[:60])
        card.setdefault(
            "visual_items",
            [{"label": "핵심", "value": headline[:60], "note": body[:80]}],
        )
    for fact in payload.get("facts", []):
        fact.setdefault("expires_at", None)
        # Legacy packages remain readable, but missing provenance must never be
        # upgraded to a false direct-verification claim.
        fact.setdefault("verification_method", "보조 자료만 확인")
        fact.setdefault("evidence", str(fact.get("claim", "공식 원문 확인"))[:500])
    return DailyPackage.model_validate(payload)


def run_daily(
    edition_date: date,
    output_root: str | Path,
    settings: Settings,
    fixture: str | Path | None = None,
) -> tuple[Path, ValidationReport]:
    output_root = Path(output_root)
    history = ""
    recovery_attempts: list[tuple[int, list[str]]] = []
    if fixture:
        package = load_package(fixture)
        fixture_day = package.generated_at.date()
        date_shift = timedelta(days=(edition_date - fixture_day).days)
        shifted_facts = [
            fact.model_copy(
                update={
                    "checked_at": fact.checked_at + date_shift,
                    "expires_at": (
                        fact.expires_at + date_shift if fact.expires_at is not None else None
                    ),
                }
            )
            for fact in package.facts
        ]
        package = package.model_copy(
            update={
                "edition_date": edition_date.isoformat(),
                "generated_at": package.generated_at + date_shift,
                "facts": shifted_facts,
            }
        )
    else:
        history = recent_publication_summary(output_root, edition_date, settings.recent_days)
        package = generate_daily_package(edition_date, settings, history)

    report = _validate_for_edition(package, settings, edition_date)
    if not fixture:
        for attempt in range(1, settings.auto_repair_attempts + 1):
            if report.ok:
                break
            errors = list(report.errors)
            recovery_attempts.append((attempt, errors))
            print(
                f"[자동 복구 {attempt}/{settings.auto_repair_attempts}] "
                f"차단 항목 {len(errors)}건을 발견했습니다.",
                file=sys.stderr,
                flush=True,
            )
            for error in errors:
                print(f"  - {error}", file=sys.stderr, flush=True)
            package = repair_daily_package(
                edition_date=edition_date,
                settings=settings,
                history_summary=history,
                invalid_package=package,
                errors=errors,
                warnings=list(report.warnings),
                attempt=attempt,
            )
            report = _validate_for_edition(package, settings, edition_date)

    if not report.ok:
        recovery_detail = _recovery_markdown(recovery_attempts, resolved=False)
        raise ValueError(report.as_markdown() + recovery_detail)

    if recovery_attempts:
        report.warnings.insert(
            0,
            f"자동 복구 {len(recovery_attempts)}회 후 차단 항목을 해결하고 전체 검증을 다시 통과했습니다.",
        )
        print(
            f"[자동 복구 완료] {len(recovery_attempts)}회 재조사 후 자동 검증을 통과했습니다.",
            file=sys.stderr,
            flush=True,
        )

    destination = output_root / edition_date.isoformat()
    destination.mkdir(parents=True, exist_ok=True)
    _write_text(destination / "package.json", package.model_dump_json(indent=2) + "\n")
    _write_text(destination / "caption.md", _caption_markdown(package))
    _write_text(destination / "editorial-review.md", _editorial_markdown(package, settings))
    _write_text(destination / "validation.md", report.as_markdown())
    recovery_path = destination / "recovery-log.md"
    if recovery_attempts:
        _write_text(
            recovery_path,
            _recovery_markdown(recovery_attempts, resolved=True),
        )
    elif recovery_path.exists():
        recovery_path.unlink()
    rendered_paths = render_package(package, destination, settings)
    _validate_rendered_output(rendered_paths, settings)
    _write_publication_package(destination, package, rendered_paths)
    return destination, report


def _validate_for_edition(
    package: DailyPackage,
    settings: Settings,
    edition_date: date,
) -> ValidationReport:
    report = validate_package(package, settings)
    expected = edition_date.isoformat()
    if package.edition_date != expected:
        report.errors.insert(
            0,
            f"생성물 편집일({package.edition_date})이 요청한 편집일({expected})과 다릅니다.",
        )
    return report


def _recovery_markdown(
    attempts: list[tuple[int, list[str]]],
    *,
    resolved: bool,
) -> str:
    if not attempts:
        return ""
    blocks = ["# 자동 복구 기록"]
    for attempt, errors in attempts:
        items = "\n".join(f"- {item}" for item in errors)
        blocks.append(f"## {attempt}차 재조사 사유\n\n{items}")
    outcome = (
        "공식 출처 재조사와 원고 재작성 후 모든 차단 항목이 해결되었습니다."
        if resolved
        else "설정된 자동 복구 횟수 안에 모든 차단 항목을 해결하지 못했습니다."
    )
    blocks.append(f"## 최종 결과\n\n{outcome}")
    return "\n\n".join(blocks) + "\n"


def validate_file(path: str | Path, settings: Settings) -> ValidationReport:
    return validate_package(load_package(path), settings)


def render_file(path: str | Path, destination: str | Path, settings: Settings) -> list[Path]:
    package = load_package(path)
    report = validate_package(package, settings)
    if not report.ok:
        raise ValueError(report.as_markdown())
    return render_package(package, destination, settings)


def _caption_markdown(package: DailyPackage) -> str:
    tags = " ".join(package.hashtags)
    return (
        f"# {package.selected_candidate_title}\n\n"
        f"> {package.approval_notice}\n\n"
        f"{package.caption}\n\n{tags}\n\n"
        "## 대체 텍스트\n\n"
        + "\n\n".join(f"{card.slide}. {card.alt_text}" for card in package.cards)
        + "\n"
    )


def _instagram_caption(package: DailyPackage) -> str:
    text = re.sub(
        r"\s*\(\s*\[[^\]]+\]\(https?://[^)]*\)\s*\)",
        "",
        package.caption,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\[([^\]]+)\]\(https?://[^)]*\)", r"\1", text, flags=re.IGNORECASE)
    text = re.sub(r"https?://\S+|www\.\S+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip() + "\n\n" + " ".join(package.hashtags) + "\n"


def _sources_markdown(package: DailyPackage) -> str:
    blocks = [f"# 출처 목록: {package.edition_date}"]
    for fact in package.facts:
        expiry = fact.expires_at.isoformat() if fact.expires_at else "별도 만료 없음"
        blocks.append(
            f"## {fact.id} · {fact.title}\n\n"
            f"- URL: {fact.url}\n"
            f"- 확인 방식: {fact.verification_method.value}\n"
            f"- 조회 시각: {fact.checked_at.isoformat()}\n"
            f"- 유효 기한: {expiry}\n"
            f"- 근거: {fact.evidence}"
        )
    return "\n\n".join(blocks) + "\n"


def _validate_rendered_output(paths: list[Path], settings: Settings) -> None:
    if len(paths) != 6:
        raise ValueError(f"렌더링 결과는 정확히 6장이어야 합니다: {len(paths)}장")
    expected_size = (settings.output_width, settings.output_height)
    for path in paths:
        if not path.exists() or path.stat().st_size == 0:
            raise ValueError(f"렌더링 파일이 비어 있습니다: {path.name}")
        with Image.open(path) as image:
            if image.format != "PNG":
                raise ValueError(f"인스타그램 카드가 PNG가 아닙니다: {path.name}")
            if image.size != expected_size:
                raise ValueError(
                    f"카드 크기가 {expected_size}와 다릅니다: {path.name}={image.size}"
                )
            if image.mode != "RGB":
                raise ValueError(f"카드 색상 모드는 RGB여야 합니다: {path.name}={image.mode}")


def _write_publication_package(
    destination: Path,
    package: DailyPackage,
    rendered_paths: list[Path],
) -> None:
    _write_text(destination / "caption-instagram.md", _instagram_caption(package))
    _write_text(destination / "sources.md", _sources_markdown(package))
    alt_text_payload = [
        {"slide": card.slide, "league": card.league.value, "alt_text": card.alt_text}
        for card in package.cards
    ]
    _write_text(
        destination / "alt-text.json",
        json.dumps(alt_text_payload, ensure_ascii=False, indent=2) + "\n",
    )
    manifest = {
        "edition_date": package.edition_date,
        "generated_at": package.generated_at.isoformat(),
        "approval_status": "pending_human_review",
        "requires_human_approval": package.needs_human_approval,
        "cards": [path.name for path in rendered_paths],
        "caption": "caption-instagram.md",
        "alt_text": "alt-text.json",
        "sources": "sources.md",
    }
    _write_text(
        destination / "publish-manifest.json",
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
    )
    archive_path = destination / "instagram-carousel.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in rendered_paths:
            archive.write(path, arcname=path.name)
        for name in (
            "caption-instagram.md",
            "alt-text.json",
            "sources.md",
            "publish-manifest.json",
        ):
            archive.write(destination / name, arcname=name)


def _editorial_markdown(package: DailyPackage, settings: Settings) -> str:
    candidate_rows = []
    for candidate in package.candidates:
        candidate_rows.append(
            "| {sport} | {league} | {title} | {status} | {score:.1f} | {sources} |".format(
                sport=candidate.sport,
                league=candidate.league,
                title=candidate.title.replace("|", "\\|"),
                status=candidate.game_status.value,
                score=candidate.editorial_score(settings.weights),
                sources=", ".join(candidate.source_ids),
            )
        )
    fact_rows = [
        f"| {fact.id} | {fact.claim.replace('|', '\\|')} | [{fact.title}]({fact.url}) | {fact.status.value} |"
        for fact in package.facts
    ]
    checklist = package.approval_checklist
    return f"""# 편집 검토: {package.edition_date}

> **{package.approval_notice}**

## 후보 비교

| 종목 | 리그 | 후보 | 경기 상태 | 가중 점수 | 출처 |
|---|---|---|---|---:|---|
{chr(10).join(candidate_rows)}

## 오늘의 추천

**{package.selected_candidate_title}**

{package.selection_reason}

## 팩트 카드

| ID | 주장 | 원문 | 상태 |
|---|---|---|---|
{chr(10).join(fact_rows)}

## 디자인 브리프

{package.design_brief}

## 사람 승인 체크리스트

### 종목 담당
{_checklist(checklist.sport_editor)}

### 팩트체크·권리 담당
{_checklist(checklist.fact_rights)}

### 편집장
{_checklist(checklist.editor_in_chief)}
"""


def _checklist(items: list[str]) -> str:
    return "\n".join(f"- [ ] {item}" for item in items)


def _write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8", newline="\n")
