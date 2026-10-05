from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx


class OllamaError(RuntimeError):
    pass


class OllamaClient:
    def __init__(self, base_url: str | None = None, model: str | None = None) -> None:
        self.base_url = (base_url or os.getenv('OLLAMA_BASE_URL') or 'http://127.0.0.1:11434').rstrip('/')
        self.model = model or os.getenv('OLLAMA_MODEL') or 'qwen3:8b'

    def health(self) -> dict[str, Any]:
        response = httpx.get(f'{self.base_url}/api/tags', timeout=5.0)
        response.raise_for_status()
        models = [str(item.get('name', '')) for item in response.json().get('models', []) if isinstance(item, dict)]
        return {'reachable': True, 'model': self.model, 'model_installed': self.model in models, 'models': models}

    def json_chat(self, system: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = httpx.post(
            f'{self.base_url}/api/chat',
            json={
                'model': self.model,
                'stream': False,
                'format': 'json',
                'options': {'temperature': 0.15, 'top_p': 0.9},
                'messages': [
                    {'role': 'system', 'content': system},
                    {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)},
                ],
            },
            timeout=180.0,
        )
        response.raise_for_status()
        text = str((response.json().get('message') or {}).get('content') or '').strip()
        if not text:
            raise OllamaError('Ollama가 빈 응답을 반환했습니다.')
        return extract_json(text)


def extract_json(text: str) -> dict[str, Any]:
    cleaned = re.sub(r'^```(?:json)?\s*|\s*```$', '', text.strip(), flags=re.I)
    try:
        value = json.loads(cleaned)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass
    start, end = cleaned.find('{'), cleaned.rfind('}')
    if start >= 0 and end > start:
        value = json.loads(cleaned[start:end + 1])
        if isinstance(value, dict):
            return value
    raise OllamaError('Ollama 응답에서 JSON 객체를 찾지 못했습니다.')