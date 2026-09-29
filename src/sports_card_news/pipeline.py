from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

from .config import Settings
from .generator import generate_daily_package, repair_daily_package
from .history import recent_publication_summary
from .models import DailyPackage
from .renderer import render_package
from .validation import ValidationReport, validate_package


def load_package(path: str | Path) -> DailyPackage:
    return DailyPackage.model_validate_json(Path(path).read_text(encoding="utf-8"))


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
        package = package.model_copy(
            update={"edition_date": edition_date.isoformat()}
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
    render_package(package, destination, settings)
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
