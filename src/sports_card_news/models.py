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


class RightsStatus(StrEnum):
    ORIGINAL = "자체 제작"
    LICENSED = "사용 허가"
    NEEDS_REVIEW = "확인 필요"


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
    source_ids: list[str] = Field(min_length=1)
    caution: str = Field(default="", max_length=300)

    def editorial_score(self, weights: dict[str, float]) -> float:
        return round(
            self.importance * weights["importance"]
            + self.korean_relevance * weights["korean_relevance"]
            + self.source_reliability * weights["source_reliability"]
            + self.explainability * weights["explainability"],
            1,
        )


class FactSource(StrictModel):
    id: str = Field(pattern=r"^S\d+$")
    claim: str = Field(min_length=5, max_length=500)
    title: str = Field(min_length=2, max_length=200)
    # Keep the Structured Outputs schema simple: Pydantic HttpUrl emits
    # JSON Schema format="uri", which the OpenAI response_format validator
    # rejects. Validate http(s) URLs at the model layer instead.
    url: str = Field(min_length=8, max_length=2048)
    source_type: SourceType
    checked_at: datetime
    published_at: str = Field(default="", max_length=100)
    local_time: str = Field(default="", max_length=100)
    korea_time: str = Field(default="", max_length=100)
    status: FactStatus
    rights_note: str = Field(default="텍스트 사실 확인용. 이미지 재사용 안 함", max_length=300)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError("URL은 http:// 또는 https://로 시작해야 합니다")
        return value


class Card(StrictModel):
    slide: int = Field(ge=1, le=6)
    headline: str = Field(min_length=2, max_length=40)
    body: str = Field(min_length=10, max_length=240)
    source_ids: list[str] = Field(default_factory=list)
    visual_direction: str = Field(min_length=4, max_length=240)
    alt_text: str = Field(min_length=10, max_length=400)


class ApprovalChecklist(StrictModel):
    sport_editor: list[str] = Field(min_length=1)
    fact_rights: list[str] = Field(min_length=1)
    editor_in_chief: list[str] = Field(min_length=1)


class DailyPackage(StrictModel):
    approval_notice: str = Field(pattern="^게시 전 사람 승인 필요$")
    needs_human_approval: bool
    edition_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    generated_at: datetime
    candidates: list[Candidate] = Field(min_length=3)
    selected_candidate_title: str
    selection_reason: str = Field(min_length=10, max_length=500)
    facts: list[FactSource] = Field(min_length=1)
    cards: list[Card] = Field(min_length=5, max_length=6)
    caption: str = Field(min_length=150, max_length=300)
    hashtags: list[str] = Field(min_length=5, max_length=8)
    design_brief: str = Field(min_length=10, max_length=500)
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
