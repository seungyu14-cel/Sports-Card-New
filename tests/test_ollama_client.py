import httpx
import pytest
from sports_card_news.ollama_client import OllamaClient, OllamaError


def test_request_options_and_server_details(monkeypatch):
    calls=[]
    def post(url,**kwargs):
        calls.append(kwargs['json'])
        return httpx.Response(500,json={'error':'runner failed: example detail'})
    monkeypatch.setattr(httpx,'post',post)
    with pytest.raises(OllamaError,match='runner failed: example detail'):
        OllamaClient().json_chat('JSON만',{'stage':'card'})
    assert calls[0]['think'] is False
    assert calls[0]['options']['num_ctx']==8192
    assert calls[0]['options']['num_predict']==1536


def test_oversized_input_is_rejected_before_network(monkeypatch):
    def forbidden(*args,**kwargs): pytest.fail('request must not be sent')
    monkeypatch.setattr(httpx,'post',forbidden)
    with pytest.raises(OllamaError,match='입력 예산 초과'):
        OllamaClient().json_chat('JSON',{'source':'가'*9800})


def test_incomplete_output_and_timeout(monkeypatch):
    monkeypatch.setattr(httpx,'post',lambda *a,**kw:httpx.Response(200,json={'done_reason':'length','message':{'content':'{"a":1}'}}))
    with pytest.raises(OllamaError,match='출력 길이'):
        OllamaClient().json_chat('JSON',{})
    def timeout(*a,**kw): raise httpx.ReadTimeout('timeout')
    monkeypatch.setattr(httpx,'post',timeout)
    with pytest.raises(OllamaError,match='대기 시간 초과'):
        OllamaClient().json_chat('JSON',{})
