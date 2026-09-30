from __future__ import annotations

import os
import time
from datetime import date

from openai import OpenAI

from .config import Settings
from .models import DailyPackage
from .prompts import REPAIR_SYSTEM_PROMPT, SYSTEM_PROMPT, build_daily_prompt, build_repair_prompt


class GenerationError(RuntimeError):
    """AI 생성 결과가 없거나 사용할 수 없을 때 발생한다."""


def generate_daily_package(
    edition_date: date,
    settings: Settings,
    history_summary: str,
    client: OpenAI | None = None,
) -> DailyPackage:
    return _request_package(
        settings=settings,
        instructions=SYSTEM_PROMPT,
        prompt=build_daily_prompt(edition_date, settings, history_summary),
        phase="생성",
        client=client,
    )


def repair_daily_package(
    edition_date: date,
    settings: Settings,
    history_summary: str,
    invalid_package: DailyPackage,
    errors: list[str],
    warnings: list[str],
    attempt: int,
    client: OpenAI | None = None,
) -> DailyPackage:
    """Re-research and rebuild an invalid package without weakening validation."""
    prompt = build_repair_prompt(
        edition_date=edition_date,
        settings=settings,
        history_summary=history_summary,
        package_json=invalid_package.model_dump_json(indent=2),
        errors=errors,
        warnings=warnings,
        attempt=attempt,
    )
    return _request_package(
        settings=settings,
        instructions=REPAIR_SYSTEM_PROMPT,
        prompt=prompt,
        phase=f"자동 복구 {attempt}차",
        client=client,
    )


def _request_package(
    settings: Settings,
    instructions: str,
    prompt: str,
    phase: str,
    client: OpenAI | None,
) -> DailyPackage:
    if not os.getenv("OPENAI_API_KEY") and client is None:
        raise GenerationError(
            "OPENAI_API_KEY가 없습니다. GitHub Actions secret 또는 로컬 환경 변수에 등록하세요."
        )

    api = client or OpenAI(timeout=settings.api_timeout_seconds, max_retries=0)
    response = None
    last_error: Exception | None = None
    for request_attempt in range(1, settings.api_retry_attempts + 1):
        try:
            response = api.responses.parse(
                model=settings.model,
                reasoning={"effort": settings.reasoning_effort},
                tools=[{"type": "web_search", "external_web_access": True}],
                tool_choice="required",
                include=["web_search_call.action.sources"],
                instructions=instructions,
                input=prompt,
                text_format=DailyPackage,
                max_output_tokens=16000,
                store=False,
            )
            break
        except Exception as error:
            last_error = error
            if not _is_retryable(error) or request_attempt >= settings.api_retry_attempts:
                raise GenerationError(f"OpenAI {phase} 요청에 실패했습니다: {error}") from error
            time.sleep(min(8, 2 ** (request_attempt - 1)))

    if response is None:
        raise GenerationError(f"OpenAI {phase} 요청에 실패했습니다: {last_error}")

    package = response.output_parsed
    if package is None:
        refusal = _extract_refusal(response)
        detail = f" 모델 응답: {refusal}" if refusal else ""
        raise GenerationError(f"{phase} 단계에서 구조화된 카드뉴스 초안을 받지 못했습니다.{detail}")
    return package


def _is_retryable(error: Exception) -> bool:
    status_code = getattr(error, "status_code", None)
    if status_code == 429 or isinstance(status_code, int) and status_code >= 500:
        return True
    return error.__class__.__name__ in {
        "APIConnectionError",
        "APITimeoutError",
        "InternalServerError",
        "RateLimitError",
    }


def _extract_refusal(response: object) -> str:
    for item in getattr(response, "output", []):
        for content in getattr(item, "content", []):
            if getattr(content, "type", "") == "refusal":
                return str(getattr(content, "refusal", ""))
    return ""
