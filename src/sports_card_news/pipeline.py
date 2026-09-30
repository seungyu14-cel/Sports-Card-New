from __future__ import annotations

import json
import re
import sys
import zipfile
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

from .analytics import recent_performance_summary
from .assets import attach_verified_news_images
from .config import Settings
from .generator import generate_daily_package, repair_daily_package
from .history import recent_publication_summary
from .models import DailyPackage
from .renderer import render_package
from .structured_data import load_structured_context
from .validation import ValidationReport, validate_package
from .visual_qa import run_visual_qa


def load_package(path: str | Path) -> DailyPackage:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    legacy_leagues = (
        "COVER",
        "KBO",
        "KBL",
        "NPB",
        "EPL",
        "NBA",
        "SUMMARY",
    )
    candidates = payload.get("candidates", [])
    candidate_by_league = {}
    for candidate in candidates:
        league = str(candidate.get("league", "")).upper()
        candidate_by_league.setdefault(league, candidate)
        candidate.setdefault("freshness", 3)
        candidate.setdefault("fan_interest", 3)
        candidate.setdefault("visual_potential", 3)
        candidate.setdefault("uniqueness", 3)

    for card in payload.get("cards", []):
        slide_index = int(card.get("slide", 1)) - 1
        if 0 <= slide_index < len(legacy_leagues):
            card.setdefault("league", legacy_leagues[slide_index])
        default_template = "cover" if card.get("slide") == 1 else "auto"
        card.setdefault("visual_template", default_template)
        card.setdefault("content_type", "auto")
        card.setdefault("kicker", "")
        card.setdefault("asset_ids", [])
        if int(card.get("slide", 1)) == 1:
            card.setdefault("candidate_title", "")
        else:
            league = str(card.get("league", "")).upper()
            candidate = candidate_by_league.get(league)
            card.setdefault("candidate_title", str(candidate.get("title", "")) if candidate else "")
        headline = str(card.get("headline", "핵심 정보")).splitlines()[0]
        body = str(card.get("body", "")).replace("\n", " ")
        card.setdefault("visual_title", headline[:60])
        card.setdefault(
            "visual_items",
            [{"label": "핵심", "value": headline[:60], "note": body[:80]}],
        )

    for fact in payload.get("facts", []):
        fact.setdefault("expires_at", None)
        fact.setdefault("verification_method", "보조 자료만 확인")
        fact.setdefault("evidence", str(fact.get("claim", "공식 원문 확인"))[:500])

    payload.setdefault("assets", [])
    for asset in payload["assets"]:
        asset.setdefault("source_fact_id", "")
        asset.setdefault("usage_scope", [])
        asset.setdefault("license_evidence", "")
    return DailyPackage.model_validate(payload)


def run_daily(
    edition_date: date,
    output_root: str | Path,
    settings: Settings,
    fixture: str | Path | None = None,
) -> tuple[Path, ValidationReport]:
    output_root = Path(output_root)
    history = ""
    performance = "성과 데이터 없음"
    structured_context = "사전 구조화 데이터 없음"
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
        performance = recent_performance_summary(
            output_root,
            edition_date,
            settings.analytics_days,
        )
        structured_context = load_structured_context(
            settings.structured_data_dir,
            edition_date,
        )
        package = generate_daily_package(
            edition_date,
            settings,
            history,
            performance_summary=performance,
            structured_context=structured_context,
        )
        package = attach_verified_news_images(package, settings)

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
                performance_summary=performance,
                structured_context=structured_context,
                invalid_package=package,
                errors=errors,
                warnings=list(report.warnings),
                attempt=attempt,
            )
            package = attach_verified_news_images(package, settings)
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
        _write_text(recovery_path, _recovery_markdown(recovery_attempts, resolved=True))
    elif recovery_path.exists():
        recovery_path.unlink()

    rendered_paths = render_package(package, destination, settings)
    visual_report = run_visual_qa(package, rendered_paths, settings)
    _write_text(destination / "visual-qa.md", visual_report.as_markdown())
    if not visual_report.ok:
        raise ValueError(visual_report.as_markdown())

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
    paths = render_package(package, destination, settings)
    visual_report = run_visual_qa(package, paths, settings)
    if not visual_report.ok:
        raise ValueError(visual_report.as_markdown())
    return paths


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
    if package.assets:
        blocks.append("# 시각 자산 권리")
        for asset in package.assets:
            blocks.append(
                f"## {asset.id} · {asset.title}\n\n"
                f"- 종류: {asset.asset_type.value}\n"
                f"- 권리 상태: {asset.rights_status.value}\n"
                f"- 게시 승인: {'예' if asset.approved_for_publish else '아니오'}\n"
                f"- 출처: {asset.source_url or '외부 URL 없음'}\n"
                f"- 원문 Fact: {asset.source_fact_id or '없음'}\n"
                f"- 크레딧: {asset.credit or '없음'}\n"
                f"- 사용 범위: {', '.join(asset.usage_scope) or '없음'}\n"
                f"- 승인 근거: {asset.license_evidence or '없음'}\n"
                f"- 권리 메모: {asset.rights_note}"
            )
    return "\n\n".join(blocks) + "\n"


def _write_publication_package(
    destination: Path,
    package: DailyPackage,
    rendered_paths: list[Path],
) -> None:
    _write_text(destination / "caption-instagram.md", _instagram_caption(package))
    _write_text(destination / "sources.md", _sources_markdown(package))
    alt_text_payload = [
        {
            "slide": card.slide,
            "league": card.league.value,
            "content_type": card.content_type.value,
            "alt_text": card.alt_text,
        }
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
        "visual_qa": "visual-qa.md",
        "assets": [asset.model_dump(mode="json") for asset in package.assets],
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
            "visual-qa.md",
            "publish-manifest.json",
        ):
            archive.write(destination / name, arcname=name)


def _editorial_markdown(package: DailyPackage, settings: Settings) -> str:
    candidate_rows = []
    for candidate in sorted(
        package.candidates,
        key=lambda item: item.editorial_score(settings.weights),
        reverse=True,
    ):
        candidate_rows.append(
            "| {sport} | {league} | {title} | {status} | {score:.2f} | {freshness} | {interest} | {visual} | {sources} |".format(
                sport=candidate.sport,
                league=candidate.league,
                title=candidate.title.replace("|", "\\|"),
                status=candidate.game_status.value,
                score=candidate.editorial_score(settings.weights),
                freshness=candidate.freshness,
                interest=candidate.fan_interest,
                visual=candidate.visual_potential,
                sources=", ".join(candidate.source_ids),
            )
        )
    fact_rows = [
        f"| {fact.id} | {fact.claim.replace('|', '\\|')} | [{fact.title}]({fact.url}) | {fact.status.value} |"
        for fact in package.facts
    ]
    story_mix = Counter(card.league.value for card in package.cards[1:6])
    template_mix = Counter(card.visual_template.value for card in package.cards[1:6])
    checklist = package.approval_checklist
    return f"""# 편집 검토: {package.edition_date}

> **{package.approval_notice}**

## 후보 비교

| 종목 | 리그 | 후보 | 경기 상태 | 편집 점수 | 최신성 | 팬 관심 | 시각화 | 출처 |
|---|---|---|---|---:|---:|---:|---:|---|
{chr(10).join(candidate_rows)}

## 오늘의 대표 이슈

**{package.selected_candidate_title}**

{package.selection_reason}

## 오늘의 편성
- 리그 구성: {dict(story_mix)}
- 템플릿 구성: {dict(template_mix)}
- 2~6번: 다섯 카테고리에서 서로 다른 5개 이슈
- 카테고리 분포: KBO/KBL/NPB/EPL/NBA 각 1개
- 7번: 마무리/한눈 요약

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
