from __future__ import annotations

import os

from openai import OpenAI


OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_SITE_URL = "https://github.com/seungyu14-cel/Sports-Card-New"
OPENROUTER_APP_TITLE = "Sports Card News Studio"


def create_openrouter_client(
    api_key: str | None = None,
    *,
    timeout: float = 180.0,
    max_retries: int = 2,
) -> OpenAI:
    """OpenRouter의 OpenAI 호환 엔드포인트를 사용하는 클라이언트를 만든다."""
    key = (api_key or os.getenv("OPENROUTER_API_KEY", "")).strip()
    if not key:
        raise ValueError("OPENROUTER_API_KEY가 없습니다.")
    return OpenAI(
        api_key=key,
        base_url=OPENROUTER_BASE_URL,
        timeout=timeout,
        max_retries=max_retries,
        default_headers={
            "HTTP-Referer": OPENROUTER_SITE_URL,
            "X-OpenRouter-Title": OPENROUTER_APP_TITLE,
        },
    )
