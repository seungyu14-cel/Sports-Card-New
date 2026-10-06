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
        self.num_ctx = int(os.getenv('OLLAMA_NUM_CTX', '8192'))
        self.num_predict = int(os.getenv('OLLAMA_NUM_PREDICT', '1536'))
        self.timeout = float(os.getenv('OLLAMA_TIMEOUT_SECONDS', '600'))
        if self.num_ctx < 4096 or not 256 <= self.num_predict <= self.num_ctx // 2 or self.timeout <= 0:
            raise OllamaError('Ollama 설정 오류: NUM_CTX >= 4096, 출력 256~컨텍스트 절반, 시간 제한 > 0 필요.')

    def check_budget(self, system: str, payload: dict[str, Any]) -> None:
        # Conservative UTF-8 byte ceiling, not an exact tokenizer count.
        size = len(system.encode('utf-8')) + len(json.dumps(payload, ensure_ascii=False).encode('utf-8'))
        budget = self.num_ctx - self.num_predict - 512
        if size > budget:
            raise OllamaError(f"{payload.get('stage', '요청')}: 입력 예산 초과 ({size}바이트 / {budget}). "
                              '입력을 자르지 않고 중단했습니다. 추가 편집지시를 줄이거나 OLLAMA_NUM_CTX를 조정하세요.')

    def health(self) -> dict[str, Any]:
        response = httpx.get(f'{self.base_url}/api/tags', timeout=5.0)
        response.raise_for_status()
        models = [str(item.get('name', '')) for item in response.json().get('models', []) if isinstance(item, dict)]
        return {'reachable': True, 'model': self.model, 'model_installed': self.model in models, 'models': models}

    def json_chat(self, system: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.check_budget(system, payload)
        try:
            response = httpx.post(
                f'{self.base_url}/api/chat',
                json={
                    'model': self.model, 'stream': False, 'format': 'json', 'think': False,
                    'options': {'temperature': 0.15, 'top_p': 0.9,
                                'num_ctx': self.num_ctx, 'num_predict': self.num_predict},
                    'messages': [{'role': 'system', 'content': system},
                                 {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}],
                }, timeout=httpx.Timeout(self.timeout, connect=10.0),
            )
        except httpx.TimeoutException as exc:
            raise OllamaError(f"{payload.get('stage', '요청')}: Ollama 응답 대기 시간 초과. "
                              '모델 실행 상태와 PC 자원을 확인하세요.') from exc
        except httpx.RequestError as exc:
            raise OllamaError('Ollama 연결 실패. 실행 상태와 OLLAMA_BASE_URL을 확인하세요.') from exc
        if response.is_error:
            try:
                detail = str(response.json().get('error', '상세 오류 없음'))[:320]
            except (ValueError, AttributeError):
                detail = 'JSON 오류 본문 없음. Ollama server.log를 확인하세요.'
            raise OllamaError(f"{payload.get('stage', '요청')}: Ollama HTTP {response.status_code}: {detail}")
        if response.json().get('done_reason') == 'length':
            raise OllamaError('Ollama 출력 길이 한도에 도달했습니다. 불완전한 JSON을 사용하지 않습니다. OLLAMA_NUM_PREDICT를 조정하세요.')
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