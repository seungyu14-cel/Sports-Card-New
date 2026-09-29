from __future__ import annotations

import os
from datetime import date

from openai import OpenAI

from .config import Settings
from .models import DailyPackage
from .prompts import SYSTEM_PROMPT, build_daily_prompt


class GenerationError(RuntimeError):
    """AI 생성 결과가 없거나 사용할 수 없을 때 발생한다."""


def generate_daily_package(
    edition_date: date,
    settings: Settings,
    history_summary: str,
    client: OpenAI | None = None,
) -> DailyPackage:
    if not os.getenv("OPENAI_API_KEY") and client is None:
        raise GenerationError(
            "OPENAI_API_KEY가 없습니다. GitHub Actions secret 또는 로컬 환경 변수에 등록하세요."
        )

    api = client or OpenAI()
    try:
        response = api.responses.parse(
            model=settings.model,
            reasoning={"effort": settings.reasoning_effort},
            tools=[{"type": "web_search", "external_web_access": True}],
            tool_choice="required",
            include=["web_search_call.action.sources"],
            instructions=SYSTEM_PROMPT,
            input=build_daily_prompt(edition_date, settings, history_summary),
            text_format=DailyPackage,
            max_output_tokens=16000,
            store=False,
        )
    except Exception as error:
        raise GenerationError(f"OpenAI 생성 요청에 실패했습니다: {error}") from error

    package = response.output_parsed
    if package is None:
        refusal = _extract_refusal(response)
        detail = f" 모델 응답: {refusal}" if refusal else ""
        raise GenerationError(f"구조화된 카드뉴스 초안을 받지 못했습니다.{detail}")
    return package


def _extract_refusal(response: object) -> str:
    for item in getattr(response, "output", []):
        for content in getattr(item, "content", []):
            if getattr(content, "type", "") == "refusal":
                return str(getattr(content, "refusal", ""))
    return ""
