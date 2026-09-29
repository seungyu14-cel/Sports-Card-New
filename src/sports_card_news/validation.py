from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse

from .config import Settings
from .models import DailyPackage, FactStatus, GameStatus, RightsStatus, SourceType


@dataclass
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_markdown(self) -> str:
        status = "[PASS] 자동 검증 통과" if self.ok else "[FAIL] 자동 검증 실패"
        blocks = [f"# 검토 보고서\n\n{status}"]
        if self.errors:
            blocks.append("## 차단 항목\n\n" + "\n".join(f"- {item}" for item in self.errors))
        if self.warnings:
            blocks.append("## 사람 확인 항목\n\n" + "\n".join(f"- {item}" for item in self.warnings))
        if not self.errors and not self.warnings:
            blocks.append("자동 검사에서 추가 경고가 발견되지 않았습니다.")
        blocks.append(
            "## 승인 절차\n\n"
            "이 보고서는 사람 검토를 대체하지 않습니다. 종목 담당 -> 팩트체크·권리 담당 -> 편집장 순서로 확인하세요."
        )
        return "\n\n".join(blocks) + "\n"


def validate_package(package: DailyPackage, settings: Settings) -> ValidationReport:
    report = ValidationReport()
    all_source_ids = [source.id for source in package.facts]
    source_ids = set(all_source_ids)
    facts_by_id = {source.id: source for source in package.facts}

    if len(source_ids) != len(all_source_ids):
        report.errors.append("출처 ID가 중복되었습니다.")

    candidate_titles = [candidate.title for candidate in package.candidates]
    if len(set(candidate_titles)) != len(candidate_titles):
        report.errors.append("후보 제목이 중복되었습니다.")

    if package.selected_candidate_title not in set(candidate_titles):
        report.errors.append("선정 제목이 후보 목록에 없습니다.")

    if package.generated_at.tzinfo is None:
        report.errors.append("생성 시각에 시간대가 없습니다.")

    sports = {candidate.sport for candidate in package.candidates}
    if len(sports) < settings.candidate_sports_min:
        report.errors.append(
            f"서로 다른 종목 후보가 {settings.candidate_sports_min}개보다 적습니다: {sorted(sports)}"
        )

    if not settings.cards_min <= len(package.cards) <= settings.cards_max:
        report.errors.append(f"카드 수는 {settings.cards_min}~{settings.cards_max}장이어야 합니다.")

    expected_slides = list(range(1, len(package.cards) + 1))
    actual_slides = [card.slide for card in package.cards]
    if actual_slides != expected_slides:
        report.errors.append(f"카드 번호가 연속적이지 않습니다: {actual_slides}")

    for candidate in package.candidates:
        missing = sorted(set(candidate.source_ids) - source_ids)
        if missing:
            report.errors.append(f"후보 '{candidate.title}'의 출처 ID가 없습니다: {missing}")
        unresolved = sorted(
            source_id
            for source_id in candidate.source_ids
            if source_id in facts_by_id and facts_by_id[source_id].status != FactStatus.VERIFIED
        )
        if unresolved:
            report.errors.append(
                f"후보 '{candidate.title}'가 검증 완료되지 않은 출처를 참조합니다: {unresolved}"
            )

    for card in package.cards:
        missing = sorted(set(card.source_ids) - source_ids)
        if missing:
            report.errors.append(f"카드 {card.slide}의 출처 ID가 없습니다: {missing}")
        unresolved = sorted(
            source_id
            for source_id in card.source_ids
            if source_id in facts_by_id and facts_by_id[source_id].status != FactStatus.VERIFIED
        )
        if unresolved:
            report.errors.append(
                f"카드 {card.slide}가 검증 완료되지 않은 출처를 참조합니다: {unresolved}"
            )
        if card.slide < len(package.cards) and not card.source_ids:
            report.warnings.append(f"카드 {card.slide}에 직접 연결된 출처가 없습니다.")

    if package.rights_status == RightsStatus.NEEDS_REVIEW:
        report.warnings.append(
            "시각 소재 권리가 '확인 필요' 상태입니다. 게시 전 팩트체크·권리 담당자가 확인하세요."
        )

    trusted_official = 0
    for source in package.facts:
        parsed_url = urlparse(str(source.url))
        domain = (parsed_url.hostname or "").lower()
        if parsed_url.scheme != "https":
            report.errors.append(f"HTTPS가 아닌 출처 URL입니다: {source.id}")
        if source.checked_at.tzinfo is None:
            report.errors.append(f"출처 조회 시각에 시간대가 없습니다: {source.id}")
        trusted = any(domain == item or domain.endswith(f".{item}") for item in settings.trusted_domains)
        if source.source_type == SourceType.OFFICIAL and trusted:
            trusted_official += 1
        if source.status == FactStatus.CONFLICT:
            report.errors.append(f"출처 충돌: {source.id} {source.claim}")
        elif source.status in {FactStatus.NEEDS_REVIEW, FactStatus.CHANGED}:
            report.warnings.append(f"{source.status.value}: {source.id} {source.claim}")
        if source.source_type == SourceType.OFFICIAL and not trusted:
            report.warnings.append(f"공식 출처로 표기됐지만 신뢰 도메인 목록에 없습니다: {domain}")

    if trusted_official == 0:
        report.warnings.append("등록된 리그 공식 도메인의 출처가 없습니다.")

    selected = next(
        (item for item in package.candidates if item.title == package.selected_candidate_title),
        None,
    )
    if selected and selected.game_status == GameStatus.LIVE:
        report.warnings.append("선정 주제가 진행 중 경기입니다. 최종 결과 표현이 없는지 다시 확인하세요.")

    if package.risk_flags:
        report.warnings.extend(f"AI 위험 표시: {flag}" for flag in package.risk_flags)
    return report
