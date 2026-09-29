from __future__ import annotations

import os
from datetime import date
from typing import Any, cast

from openai import OpenAI
from pydantic import ValidationError

from .config import Settings
from .models import DailyPackage
from .openrouter import create_openrouter_client
from .prompts import SYSTEM_PROMPT, build_daily_prompt


class GenerationError(RuntimeError):
    """AI 생성 결과가 없거나 사용할 수 없을 때 발생한다."""


def generate_daily_package(
    edition_date: date,
    settings: Settings,
    history_summary: str,
    client: OpenAI | None = None,
) -> DailyPackage:
    if not os.getenv("OPENROUTER_API_KEY") and client is None:
        raise GenerationError(
            "OPENROUTER_API_KEY가 없습니다. GitHub Actions secret 또는 로컬 환경 변수에 등록하세요."
        )

    api = client or create_openrouter_client()
    response_format = {
        "type": "json_schema",
        "json_schema": {
            "name": "daily_sports_card_news",
            "strict": True,
            "schema": DailyPackage.model_json_schema(),
        },
    }
    try:
        response = api.chat.completions.create(
            model=settings.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": build_daily_prompt(edition_date, settings, history_summary),
                },
            ],
            response_format=cast(Any, response_format),
            reasoning_effort=cast(Any, settings.reasoning_effort),
            max_completion_tokens=16000,
            extra_body={
                "tool_choice": "required",
                "tools": [
                    {
                        "type": "openrouter:web_search",
                        "parameters": {"max_results": 12},
                    }
                ]
            },
        )
    except Exception as error:
        raise GenerationError(f"OpenRouter 생성 요청에 실패했습니다: {error}") from error

    if not response.choices:
        raise GenerationError("OpenRouter에서 생성 결과를 받지 못했습니다.")
    content = response.choices[0].message.content
    if not isinstance(content, str) or not content.strip():
        raise GenerationError("OpenRouter에서 구조화된 카드뉴스 초안을 받지 못했습니다.")
    try:
        return DailyPackage.model_validate_json(content)
    except ValidationError as error:
        raise GenerationError("OpenRouter 응답이 카드뉴스 스키마를 충족하지 못했습니다.") from error
