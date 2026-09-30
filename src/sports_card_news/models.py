from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GameStatus(StrEnum):
    SCHEDULED = "예정"
    LIVE = "진행 중"
    FINAL = "종료"
    POSTPONED = "연기"
    CANCELLED = "취소"
    CHECKING = "확인 중"


class FactStatus(StrEnum):
    VERIFIED = "검증 완료"
    NEEDS_REVIEW = "검증 필요"
    CHANGED = "변경됨"
    CONFLICT = "출처 충돌"


class SourceType(StrEnum):
    OFFICIAL = "공식"
    PRIMARY = "1차 자료"
    SECONDARY = "보조 자료"


class VerificationMethod(StrEnum):
    DIRECT = "원문 직접 확인"
    SEARCH_SNIPPET = "검색 결과 요약"
    SECONDARY_ONLY = "보조 자료만 확인"


class RightsStatus(StrEnum):
    ORIGINAL = "자체 제작"
    LICENSED = "사용 허가"
    NEWS_APPROVED = "뉴스 이미지 사용 승인"
    NEEDS_REVIEW = "확인 필요"


class AssetType(StrEnum):
    PLAYER_PHOTO = "player_photo"
    TEAM_LOGO = "team_logo"
    LEAGUE_LOGO = "league_logo"
    STADIUM = "stadium"
    ILLUSTRATION = "illustration"
    DATA_GRAPHIC = "data_graphic"
    NEWS_IMAGE = "news_image"


class ContentType(StrEnum):
    AUTO = "auto"
    MATCH_RESULT = "match_result"
    MATCH_PREVIEW = "match_preview"
    BREAKING = "breaking"
    PLAYER = "player"
    STAT = "stat"
    RANKING = "ranking"
    TRANSFER = "transfer"
    INJURY = "injury"
    SCHEDULE = "schedule"
    EXPLAINER = "explainer"
    SUMMARY = "summary"


class VisualTemplate(StrEnum):
    COVER = "cover"
    MATCH_RESULT = "match_result"
    MATCH_PREVIEW = "match_preview"
    PLAYER = "player"
    STAT = "stat"
    RANKING = "ranking"
    BREAKING = "breaking"
    SCHEDULE = "schedule"
    SUMMARY = "summary"
    KEY_FACT = "key_fact"
    THREE_SCREEN = "three_screen"
    SEAT_SPLIT = "seat_split"
    LOCATION = "location"
    STEPS = "steps"
    TIMELINE = "timeline"
    COMPARISON = "comparison"
    STATUS = "status"
    SOURCES = "sources"
    APPROVAL = "approval"
    AUTO = "auto"


class CardLeague(StrEnum):
    COVER = "COVER"
    KBO = "KBO"
    KBL = "KBL"
    NPB = "NPB"
    EPL = "EPL"
    NBA = "NBA"
    SUMMARY = "SUMMARY"


Score = Annotated[int, Field(ge=1, le=5)]


class Candidate(StrictModel):
    sport: str = Field(min_length=1)
    league: str = Field(min_length=1)
    title: str = Field(min_length=4, max_length=100)
    summary: str = Field(min_length=10, max_length=500)
    game_status: GameStatus
    importance: Score
    korean_relevance: Score
    source_reliability: Score
    explainability: Score
    freshness: Score = 3
    fan_interest: Score = 3
    visual_potential: Score = 3
    uniqueness: Score = 3
    source_ids: list[str] = Field(min_length=1)
    caution: str = Field(default="", max_length=300)

    def editorial_score(self, weights: dict[str, float]) -> float:
        dimensions = {
            "importance": self.importance,
            "korean_relevance": self.korean_relevance,
            "source_reliability": self.source_reliability,
            "explainability": self.explainability,
            "freshness": self.freshness,
            "fan_interest": self.fan_interest,
            "visual_potential": self.visual_potential,
            "uniqueness": self.uniqueness,
        }
        return round(
            sum(value * float(weights.get(name, 0.0)) for name, value in dimensions.items()),
            2,
        )


class FactSource(StrictModel):
    id: str = Field(pattern=r"^S\d+$")
    claim: str = Field(min_length=5, max_length=500)
    title: str = Field(min_length=2, max_length=200)
    url: str = Field(min_length=8, max_length=2048)
    source_type: SourceType
    checked_at: datetime
    expires_at: datetime | None
    verification_method: VerificationMethod
    evidence: str = Field(min_length=5, max_length=500)
    published_at: str = Field(default="", max_length=100)
    local_time: str = Field(default="", max_length=100)
    korea_time: str = Field(default="", max_length=100)
    status: FactStatus
    rights_note: str = Field(default="텍스트 사실 확인용", max_length=300)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError("URL은 http:// 또는 https://로 시작해야 합니다")
        return value


class VisualAsset(StrictModel):
    id: str = Field(pattern=r"^A\d+$")
    asset_type: AssetType
    title: str = Field(min_length=2, max_length=120)
    source_url: str = Field(default="", max_length=2048)
    source_fact_id: str = Field(default="", max_length=24)
    rights_status: RightsStatus
    rights_note: str = Field(min_length=2, max_length=300)
    credit: str = Field(default="", max_length=160)
    usage_scope: list[str] = Field(default_factory=list, max_length=8)
    license_evidence: str = Field(default="", max_length=500)
    approved_for_publish: bool = False


class VisualItem(StrictModel):
    label: str = Field(min_length=1, max_length=24)
    value: str = Field(min_length=1, max_length=60)
    note: str = Field(default="", max_length=80)


class Card(StrictModel):
    slide: int = Field(ge=1, le=10)
    league: CardLeague
    candidate_title: str = Field(default="", max_length=100)
    headline: str = Field(min_length=2, max_length=40)
    body: str = Field(min_length=10, max_length=240)
    source_ids: list[str] = Field(default_factory=list)
    content_type: ContentType = ContentType.AUTO
    kicker: str = Field(default="", max_length=32)
    visual_template: VisualTemplate
    visual_title: str = Field(min_length=2, max_length=60)
    visual_items: list[VisualItem] = Field(min_length=1, max_length=8)
    visual_direction: str = Field(min_length=4, max_length=240)
    asset_ids: list[str] = Field(default_factory=list, max_length=3)
    alt_text: str = Field(min_length=10, max_length=400)


class ApprovalChecklist(StrictModel):
    sport_editor: list[str] = Field(min_length=1)
    fact_rights: list[str] = Field(min_length=1)
    editor_in_chief: list[str] = Field(min_length=1)


class ResearchBrief(StrictModel):
    edition_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    generated_at: datetime
    candidates: list[Candidate] = Field(min_length=8, max_length=20)
    facts: list[FactSource] = Field(min_length=1)
    risk_flags: list[str] = Field(default_factory=list)


class EditorialCard(StrictModel):
    slide: int = Field(ge=1, le=10)
    league: CardLeague
    candidate_title: str = Field(default="", max_length=100)
    headline: str = Field(min_length=2, max_length=40)
    body: str = Field(min_length=10, max_length=180)
    source_ids: list[str] = Field(default_factory=list)
    content_type: ContentType
    kicker: str = Field(default="", max_length=32)
    alt_text: str = Field(min_length=10, max_length=400)


class EditorialPlan(StrictModel):
    edition_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    selected_candidate_title: str
    selection_reason: str = Field(min_length=10, max_length=500)
    cards: list[EditorialCard] = Field(min_length=10, max_length=10)
    caption: str = Field(min_length=500, max_length=2000)
    hashtags: list[str] = Field(min_length=5, max_length=8)
    approval_checklist: ApprovalChecklist

    @field_validator("hashtags")
    @classmethod
    def validate_hashtags(cls, values: list[str]) -> list[str]:
        if any(not value.startswith("#") or " " in value for value in values):
            raise ValueError("해시태그는 공백 없이 #으로 시작해야 합니다")
        return values


class DesignCard(StrictModel):
    slide: int = Field(ge=1, le=10)
    visual_template: VisualTemplate
    visual_title: str = Field(min_length=2, max_length=60)
    visual_items: list[VisualItem] = Field(min_length=1, max_length=8)
    visual_direction: str = Field(min_length=4, max_length=240)
    asset_ids: list[str] = Field(default_factory=list, max_length=3)


class DesignPlan(StrictModel):
    design_brief: str = Field(min_length=10, max_length=500)
    rights_status: RightsStatus
    assets: list[VisualAsset] = Field(default_factory=list, max_length=30)
    cards: list[DesignCard] = Field(min_length=10, max_length=10)


class DailyPackage(StrictModel):
    approval_notice: str = Field(pattern="^게시 전 사람 승인 필요$")
    needs_human_approval: bool
    edition_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    generated_at: datetime
    candidates: list[Candidate] = Field(min_length=8, max_length=20)
    selected_candidate_title: str
    selection_reason: str = Field(min_length=10, max_length=500)
    facts: list[FactSource] = Field(min_length=1)
    cards: list[Card] = Field(min_length=10, max_length=10)
    caption: str = Field(min_length=500, max_length=2000)
    hashtags: list[str] = Field(min_length=5, max_length=8)
    design_brief: str = Field(min_length=10, max_length=500)
    assets: list[VisualAsset] = Field(default_factory=list, max_length=30)
    rights_status: RightsStatus
    risk_flags: list[str] = Field(default_factory=list)
    approval_checklist: ApprovalChecklist

    @field_validator("needs_human_approval")
    @classmethod
    def require_human_approval(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("사람 승인 단계는 비활성화할 수 없습니다")
        return value

    @field_validator("hashtags")
    @classmethod
    def validate_hashtags(cls, values: list[str]) -> list[str]:
        if any(not value.startswith("#") or " " in value for value in values):
            raise ValueError("해시태그는 공백 없이 #으로 시작해야 합니다")
        return values
