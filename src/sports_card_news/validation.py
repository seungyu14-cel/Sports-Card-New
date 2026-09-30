from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from .config import Settings
from .models import (
    AssetType,
    CardLeague,
    ContentType,
    DailyPackage,
    FactStatus,
    GameStatus,
    RightsStatus,
    SourceType,
    VerificationMethod,
    VisualTemplate,
)


CARD_LINK_PATTERN = re.compile(
    r"https?://|www\.|\[[^\]]+\]\([^)]*\)|\b[a-z0-9-]+(?:\.[a-z0-9-]+)+\b",
    re.IGNORECASE,
)


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
    edition_date = date.fromisoformat(package.edition_date)
    editorial_timezone = ZoneInfo(settings.timezone)
    all_source_ids = [source.id for source in package.facts]
    source_ids = set(all_source_ids)
    facts_by_id = {source.id: source for source in package.facts}
    candidates_by_title = {candidate.title: candidate for candidate in package.candidates}
    asset_ids = [asset.id for asset in package.assets]
    assets_by_id = {asset.id: asset for asset in package.assets}

    def is_trusted_official(source_id: str) -> bool:
        source = facts_by_id.get(source_id)
        if source is None or source.source_type != SourceType.OFFICIAL:
            return False
        domain = (urlparse(str(source.url)).hostname or "").lower()
        return any(domain == item or domain.endswith(f".{item}") for item in settings.trusted_domains)

    if len(source_ids) != len(all_source_ids):
        report.errors.append("출처 ID가 중복되었습니다.")
    if len(set(asset_ids)) != len(asset_ids):
        report.errors.append("시각 자산 ID가 중복되었습니다.")

    candidate_titles = [candidate.title for candidate in package.candidates]
    if len(set(candidate_titles)) != len(candidate_titles):
        report.errors.append("후보 제목이 중복되었습니다.")
    if package.selected_candidate_title not in candidates_by_title:
        report.errors.append("선정 제목이 후보 목록에 없습니다.")

    if package.generated_at.tzinfo is None:
        report.errors.append("생성 시각에 시간대가 없습니다.")
    elif package.generated_at.astimezone(editorial_timezone).date() != edition_date:
        report.errors.append("생성 시각의 현지 날짜가 편집일과 다릅니다.")

    sports = {candidate.sport for candidate in package.candidates}
    if len(sports) < settings.candidate_sports_min:
        report.errors.append(
            f"서로 다른 종목 후보가 {settings.candidate_sports_min}개보다 적습니다: {sorted(sports)}"
        )

    configured_leagues = {league.upper() for league in settings.leagues}
    candidate_leagues = {candidate.league.upper() for candidate in package.candidates}
    missing_candidate_leagues = sorted(configured_leagues - candidate_leagues)
    if missing_candidate_leagues:
        report.errors.append(
            f"리서치 후보 풀에 필수 조사 카테고리가 없습니다: {missing_candidate_leagues}"
        )

    if len(package.cards) != 10:
        report.errors.append("카드는 표지 포함 정확히 10장이어야 합니다.")

    actual_slides = [card.slide for card in package.cards]
    if actual_slides != list(range(1, len(package.cards) + 1)):
        report.errors.append(f"카드 번호가 연속적이지 않습니다: {actual_slides}")

    if package.cards:
        first = package.cards[0]
        last = package.cards[-1]
        if first.league != CardLeague.COVER:
            report.errors.append("1번 카드는 COVER여야 합니다.")
        if first.visual_template != VisualTemplate.COVER:
            report.errors.append("1번 카드의 visual_template은 cover여야 합니다.")
        if last.league != CardLeague.SUMMARY:
            report.errors.append("10번 카드는 SUMMARY여야 합니다.")
        if last.content_type != ContentType.SUMMARY:
            report.errors.append("10번 카드의 content_type은 summary여야 합니다.")
        if last.visual_template != VisualTemplate.SUMMARY:
            report.errors.append("10번 카드의 visual_template은 summary여야 합니다.")
        if last.candidate_title:
            report.errors.append("10번 SUMMARY 카드의 candidate_title은 비워야 합니다.")

    issue_cards = package.cards[1:9]
    if len(issue_cards) != 8:
        report.errors.append("2~9번에는 정확히 8개의 메인 이슈가 있어야 합니다.")

    issue_titles = [card.candidate_title for card in issue_cards]
    if any(not title for title in issue_titles):
        report.errors.append("2~9번 모든 이슈 카드에 candidate_title이 필요합니다.")
    if len(set(issue_titles)) != 8:
        report.errors.append("2~9번은 서로 다른 8개의 이슈를 사용해야 합니다.")

    issue_leagues = [card.league.value for card in issue_cards]
    unknown_story_leagues = sorted(set(issue_leagues) - configured_leagues)
    if unknown_story_leagues:
        report.errors.append(f"지원하지 않는 이슈 카테고리가 있습니다: {unknown_story_leagues}")

    distinct_story_leagues = len(set(issue_leagues))
    if distinct_story_leagues < settings.min_distinct_story_leagues:
        report.errors.append(
            f"8개 이슈에 다섯 카테고리가 모두 포함되어야 합니다: {distinct_story_leagues}개 "
            f"(필요 {settings.min_distinct_story_leagues}개)"
        )

    league_counts = Counter(issue_leagues)
    crowded = {
        league: count
        for league, count in league_counts.items()
        if count > settings.max_cards_per_league
    }
    if crowded:
        report.errors.append(
            f"한 카테고리의 이슈 수가 최대 {settings.max_cards_per_league}개를 넘었습니다: {crowded}"
        )

    if len(issue_cards) == 8 and distinct_story_leagues == 5 and not crowded:
        distribution = sorted(league_counts.values(), reverse=True)
        if distribution != [2, 2, 2, 1, 1]:
            report.errors.append(
                f"8개 이슈의 카테고리 분포는 2·2·2·1·1이어야 합니다: {distribution}"
            )

    previous_template: VisualTemplate | None = None
    repeat_count = 0

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

        if CARD_LINK_PATTERN.search(card.headline) or CARD_LINK_PATTERN.search(card.body):
            report.errors.append(
                f"카드 {card.slide} 문구에 URL·도메인·Markdown 링크가 포함되어 있습니다. "
                "출처는 source_ids와 facts.url로만 연결하세요."
            )

        if len(card.body) > 180:
            report.errors.append(
                f"카드 {card.slide} 본문이 180자를 초과했습니다: {len(card.body)}자"
            )

        if card.slide > 1 and card.visual_template == VisualTemplate.COVER:
            report.errors.append(f"카드 {card.slide}에는 cover 템플릿을 사용할 수 없습니다.")

        if 2 <= card.slide <= 9:
            if card.visual_template == previous_template:
                repeat_count += 1
            else:
                repeat_count = 1
                previous_template = card.visual_template
            if repeat_count > settings.visual_repeat_limit:
                report.errors.append(
                    f"같은 시각 템플릿이 연속 {repeat_count}회 반복되었습니다: {card.visual_template.value}"
                )

            candidate = candidates_by_title.get(card.candidate_title)
            if candidate is None:
                report.errors.append(
                    f"카드 {card.slide}의 후보 제목이 리서치 후보에 없습니다: {card.candidate_title}"
                )
            else:
                if candidate.league.upper() != card.league.value:
                    report.errors.append(
                        f"카드 {card.slide}의 카테고리와 후보 카테고리가 다릅니다: "
                        f"{card.league.value} != {candidate.league}"
                    )
                if not set(card.source_ids).intersection(candidate.source_ids):
                    report.errors.append(
                        f"카드 {card.slide}가 선택 후보의 직접 출처를 참조하지 않습니다."
                    )
            if not card.source_ids:
                report.errors.append(f"{card.league.value} 카드에 직접 연결된 출처가 없습니다.")

        for asset_id in card.asset_ids:
            asset = assets_by_id.get(asset_id)
            if asset is None:
                report.errors.append(f"카드 {card.slide}의 시각 자산 ID가 없습니다: {asset_id}")
                continue
            if not asset.approved_for_publish:
                report.errors.append(f"게시 승인되지 않은 시각 자산을 참조합니다: {asset_id}")
                continue

            if asset.asset_type == AssetType.NEWS_IMAGE:
                if not settings.allow_news_images:
                    report.errors.append(f"뉴스 이미지 사용이 비활성화되어 있습니다: {asset_id}")
                if asset.rights_status != RightsStatus.NEWS_APPROVED:
                    report.errors.append(f"뉴스 이미지 승인 상태가 아닙니다: {asset_id}")
                if not asset.source_fact_id or asset.source_fact_id not in facts_by_id:
                    report.errors.append(f"뉴스 이미지의 원문 fact 연결이 없습니다: {asset_id}")
                elif asset.source_fact_id not in card.source_ids:
                    report.errors.append(
                        f"뉴스 이미지가 해당 카드의 원문 출처와 연결되지 않습니다: {asset_id}"
                    )
                else:
                    source_fact = facts_by_id[asset.source_fact_id]
                    if (
                        source_fact.status != FactStatus.VERIFIED
                        or source_fact.verification_method != VerificationMethod.DIRECT
                    ):
                        report.errors.append(
                            f"검증 완료 원문에서 발견된 이미지가 아닙니다: {asset_id}"
                        )
                if "instagram_post" not in asset.usage_scope:
                    report.errors.append(
                        f"인스타그램 게시 사용 범위가 없는 뉴스 이미지입니다: {asset_id}"
                    )
                if not asset.license_evidence.strip():
                    report.errors.append(f"뉴스 이미지 사용 승인 근거가 없습니다: {asset_id}")
            elif asset.rights_status == RightsStatus.NEEDS_REVIEW:
                report.errors.append(f"권리 확인이 끝나지 않은 시각 자산을 참조합니다: {asset_id}")

        recommended = {
            ContentType.MATCH_RESULT: {VisualTemplate.MATCH_RESULT, VisualTemplate.STAT},
            ContentType.MATCH_PREVIEW: {VisualTemplate.MATCH_PREVIEW, VisualTemplate.SCHEDULE},
            ContentType.PLAYER: {VisualTemplate.PLAYER, VisualTemplate.STAT},
            ContentType.STAT: {VisualTemplate.STAT, VisualTemplate.RANKING},
            ContentType.RANKING: {VisualTemplate.RANKING, VisualTemplate.STAT},
            ContentType.BREAKING: {VisualTemplate.BREAKING, VisualTemplate.KEY_FACT},
            ContentType.SCHEDULE: {VisualTemplate.SCHEDULE, VisualTemplate.TIMELINE},
            ContentType.SUMMARY: {VisualTemplate.SUMMARY},
        }
        if card.content_type in recommended and card.visual_template not in recommended[card.content_type]:
            report.warnings.append(
                f"카드 {card.slide}의 콘텐츠 유형({card.content_type.value})과 "
                f"시각 템플릿({card.visual_template.value}) 조합을 사람이 확인하세요."
            )

    summary = package.cards[-1] if package.cards else None
    if summary is not None:
        issue_source_ids = {source_id for card in issue_cards for source_id in card.source_ids}
        if summary.source_ids and not set(summary.source_ids).issubset(issue_source_ids):
            report.errors.append("10번 요약 카드가 2~9번에서 사용하지 않은 출처를 참조합니다.")

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

        direct_official = [
            source_id
            for source_id in candidate.source_ids
            if is_trusted_official(source_id)
            and facts_by_id[source_id].verification_method == VerificationMethod.DIRECT
            and facts_by_id[source_id].status == FactStatus.VERIFIED
        ]
        if not direct_official:
            report.errors.append(
                f"{candidate.league} 후보에 직접 확인한 리그 공식 출처가 없습니다."
            )

        if candidate.game_status in {GameStatus.SCHEDULED, GameStatus.LIVE}:
            expiring_sources = [
                facts_by_id[source_id]
                for source_id in candidate.source_ids
                if source_id in facts_by_id and facts_by_id[source_id].expires_at is not None
            ]
            if not expiring_sources:
                report.errors.append(
                    f"시간 민감형 후보 '{candidate.title}'에 출처 유효 기한(expires_at)이 없습니다."
                )

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
        elif source.checked_at.astimezone(editorial_timezone).date() != edition_date:
            report.errors.append(f"출처를 편집일 당일에 다시 확인하지 않았습니다: {source.id}")
        elif package.generated_at.tzinfo is not None and source.checked_at > package.generated_at:
            report.errors.append(f"출처 조회 시각이 생성 시각보다 늦습니다: {source.id}")

        if source.expires_at is not None:
            if source.expires_at.tzinfo is None:
                report.errors.append(f"출처 유효 기한에 시간대가 없습니다: {source.id}")
            elif source.expires_at <= source.checked_at:
                report.errors.append(f"출처 유효 기한이 조회 시각보다 빠릅니다: {source.id}")
            elif source.expires_at <= package.generated_at:
                report.errors.append(f"생성 시점에 이미 만료된 출처입니다: {source.id}")

        if source.status == FactStatus.VERIFIED and source.verification_method != VerificationMethod.DIRECT:
            report.errors.append(
                f"원문을 직접 확인하지 않은 출처는 검증 완료로 표시할 수 없습니다: {source.id}"
            )

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

    selected = candidates_by_title.get(package.selected_candidate_title)
    if selected and selected.game_status == GameStatus.LIVE:
        report.warnings.append("선정 주제가 진행 중 경기입니다. 최종 결과 표현이 없는지 다시 확인하세요.")

    if package.risk_flags:
        report.warnings.extend(f"AI 위험 표시: {flag}" for flag in package.risk_flags)

    return report
