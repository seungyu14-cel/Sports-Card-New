from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from datetime import date

from openai import OpenAI

from .config import Settings
from .models import (
    Card,
    DailyPackage,
    DesignPlan,
    EditorialPlan,
    ResearchBrief,
)
from .prompts import (
    DESIGN_SYSTEM_PROMPT,
    EDITOR_SYSTEM_PROMPT,
    REPAIR_SYSTEM_PROMPT,
    RESEARCH_SYSTEM_PROMPT,
    build_design_prompt,
    build_editorial_prompt,
    build_repair_prompt,
    build_research_prompt,
)


class GenerationError(RuntimeError):
    """AI 생성 결과가 없거나 사용할 수 없을 때 발생한다."""


@dataclass
class OutputTokenBudget:
    """하루 실행에서 API에 예약할 수 있는 최대 출력 토큰을 제한한다."""

    limit: int
    reserved: int = 0

    def reserve(self, amount: int, phase: str) -> None:
        if self.reserved + amount > self.limit:
            raise GenerationError(
                f"{phase} 요청을 보내지 않았습니다. 일일 출력 토큰 예산 "
                f"{self.limit:,}을 초과합니다 "
                f"(예약 {self.reserved:,} + 요청 {amount:,})."
            )
        self.reserved += amount
        print(
            f"[토큰 예산] {phase}: 최대 {amount:,}, "
            f"누적 예약 {self.reserved:,}/{self.limit:,}",
            file=sys.stderr,
            flush=True,
        )


def generate_daily_package(
    edition_date: date,
    settings: Settings,
    history_summary: str,
    performance_summary: str = "성과 데이터 없음",
    structured_context: str = "사전 구조화 데이터 없음",
    client: OpenAI | None = None,
    budget: OutputTokenBudget | None = None,
) -> DailyPackage:
    budget = budget or OutputTokenBudget(settings.daily_output_token_budget)
    research = _request_model(
        settings=settings,
        instructions=RESEARCH_SYSTEM_PROMPT,
        prompt=build_research_prompt(
            edition_date,
            settings,
            history_summary,
            performance_summary,
            structured_context,
        ),
        output_type=ResearchBrief,
        phase="리서치",
        client=client,
        require_web=True,
        max_output_tokens=settings.research_max_output_tokens,
        budget=budget,
    )
    editorial = _request_model(
        settings=settings,
        instructions=EDITOR_SYSTEM_PROMPT,
        prompt=build_editorial_prompt(
            edition_date,
            settings,
            history_summary,
            performance_summary,
            research.model_dump_json(),
        ),
        output_type=EditorialPlan,
        phase="편집",
        client=client,
        require_web=False,
        max_output_tokens=settings.editorial_max_output_tokens,
        budget=budget,
    )
    design = _request_model(
        settings=settings,
        instructions=DESIGN_SYSTEM_PROMPT,
        prompt=build_design_prompt(
            edition_date,
            settings,
            research.model_dump_json(),
            editorial.model_dump_json(),
        ),
        output_type=DesignPlan,
        phase="디자인",
        client=client,
        require_web=False,
        max_output_tokens=settings.design_max_output_tokens,
        budget=budget,
    )
    return _compose_package(research, editorial, design)


def repair_daily_package(
    edition_date: date,
    settings: Settings,
    history_summary: str,
    invalid_package: DailyPackage,
    errors: list[str],
    warnings: list[str],
    attempt: int,
    performance_summary: str = "성과 데이터 없음",
    structured_context: str = "사전 구조화 데이터 없음",
    client: OpenAI | None = None,
    budget: OutputTokenBudget | None = None,
) -> DailyPackage:
    prompt = build_repair_prompt(
        edition_date=edition_date,
        settings=settings,
        history_summary=history_summary,
        performance_summary=performance_summary,
        structured_context=structured_context,
        package_json=invalid_package.model_dump_json(indent=2),
        errors=errors,
        warnings=warnings,
        attempt=attempt,
    )
    return _request_model(
        settings=settings,
        instructions=REPAIR_SYSTEM_PROMPT,
        prompt=prompt,
        output_type=DailyPackage,
        phase=f"자동 복구 {attempt}차",
        client=client,
        require_web=True,
        max_output_tokens=settings.repair_max_output_tokens,
        budget=budget or OutputTokenBudget(settings.daily_output_token_budget),
    )


def _compose_package(
    research: ResearchBrief,
    editorial: EditorialPlan,
    design: DesignPlan,
) -> DailyPackage:
    design_by_slide = {item.slide: item for item in design.cards}
    cards: list[Card] = []
    for editorial_card in editorial.cards:
        design_card = design_by_slide.get(editorial_card.slide)
        if design_card is None:
            raise GenerationError(
                f"디자인 단계에서 {editorial_card.slide}번 카드가 누락되었습니다."
            )
        cards.append(
            Card(
                slide=editorial_card.slide,
                league=editorial_card.league,
                candidate_title=editorial_card.candidate_title,
                headline=editorial_card.headline,
                body=editorial_card.body,
                source_ids=editorial_card.source_ids,
                content_type=editorial_card.content_type,
                kicker=editorial_card.kicker,
                visual_template=design_card.visual_template,
                visual_title=design_card.visual_title,
                visual_items=design_card.visual_items,
                visual_direction=design_card.visual_direction,
                asset_ids=design_card.asset_ids,
                alt_text=editorial_card.alt_text,
            )
        )

    return DailyPackage(
        approval_notice="게시 전 사람 승인 필요",
        needs_human_approval=True,
        edition_date=research.edition_date,
        generated_at=research.generated_at,
        candidates=research.candidates,
        selected_candidate_title=editorial.selected_candidate_title,
        selection_reason=editorial.selection_reason,
        facts=research.facts,
        cards=cards,
        caption=editorial.caption,
        hashtags=editorial.hashtags,
        design_brief=design.design_brief,
        assets=design.assets,
        rights_status=design.rights_status,
        risk_flags=research.risk_flags,
        approval_checklist=editorial.approval_checklist,
    )


def _request_model(
    *,
    settings: Settings,
    instructions: str,
    prompt: str,
    output_type: type,
    phase: str,
    client: OpenAI | None,
    require_web: bool,
    max_output_tokens: int,
    budget: OutputTokenBudget,
):
    if not os.getenv("OPENAI_API_KEY") and client is None:
        raise GenerationError(
            "OPENAI_API_KEY가 없습니다. GitHub Actions secret 또는 로컬 환경 변수에 등록하세요."
        )

    prompt_chars = len(instructions) + len(prompt)
    if prompt_chars > settings.max_prompt_chars:
        raise GenerationError(
            f"{phase} 요청을 보내지 않았습니다. 프롬프트가 안전 상한 "
            f"{settings.max_prompt_chars:,}자를 넘었습니다: {prompt_chars:,}자"
        )

    budget.reserve(max_output_tokens, phase)
    api = client or OpenAI(timeout=settings.api_timeout_seconds, max_retries=0)
    response = None
    last_error: Exception | None = None
    kwargs: dict[str, object] = {
        "model": settings.model,
        "reasoning": {"effort": settings.reasoning_effort},
        "instructions": instructions,
        "input": prompt,
        "text_format": output_type,
        "max_output_tokens": max_output_tokens,
        "store": False,
    }
    if require_web:
        kwargs.update(
            {
                "tools": [
                    {
                        "type": "web_search",
                        "filters": {"allowed_domains": list(settings.trusted_domains)},
                        "external_web_access": True,
                    }
                ],
                "tool_choice": "required",
                "include": ["web_search_call.action.sources"],
            }
        )

    for request_attempt in range(1, settings.api_retry_attempts + 1):
        try:
            response = api.responses.parse(**kwargs)
            break
        except Exception as error:
            last_error = error
            if not _is_retryable(error) or request_attempt >= settings.api_retry_attempts:
                timeout_note = (
                    " 비용 중복을 막기 위해 시간 초과 요청은 자동 재시도하지 않았습니다."
                    if _is_timeout(error)
                    else ""
                )
                raise GenerationError(
                    f"OpenAI {phase} 요청에 실패했습니다: {error}.{timeout_note}"
                ) from error
            time.sleep(min(8, 2 ** (request_attempt - 1)))

    if response is None:
        raise GenerationError(f"OpenAI {phase} 요청에 실패했습니다: {last_error}")

    parsed = response.output_parsed
    if parsed is None:
        refusal = _extract_refusal(response)
        detail = f" 모델 응답: {refusal}" if refusal else ""
        raise GenerationError(f"{phase} 단계에서 구조화된 결과를 받지 못했습니다.{detail}")
    _log_usage(response, phase)
    return parsed


def _is_retryable(error: Exception) -> bool:
    status_code = getattr(error, "status_code", None)
    if status_code == 429:
        return True
    return error.__class__.__name__ in {
        "APIConnectionError",
        "RateLimitError",
    }


def _is_timeout(error: Exception) -> bool:
    return error.__class__.__name__ in {"APITimeoutError", "TimeoutError"}


def _log_usage(response: object, phase: str) -> None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return
    input_tokens = getattr(usage, "input_tokens", 0) or 0
    output_tokens = getattr(usage, "output_tokens", 0) or 0
    total_tokens = getattr(usage, "total_tokens", input_tokens + output_tokens) or 0
    print(
        f"[실제 토큰] {phase}: 입력 {input_tokens:,}, 출력 {output_tokens:,}, 합계 {total_tokens:,}",
        file=sys.stderr,
        flush=True,
    )


def _extract_refusal(response: object) -> str:
    for item in getattr(response, "output", []):
        for content in getattr(item, "content", []):
            if getattr(content, "type", "") == "refusal":
                return str(getattr(content, "refusal", ""))
    return ""

