import httpx
import pytest
from sports_card_news.ollama_client import OllamaClient, OllamaError, OllamaFormatError, extract_json


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
    assert calls[0]['format'] == 'json'


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


def test_dynamic_selection_schema_is_sent_to_ollama(monkeypatch):
    from sports_card_news.staged_editorial import selection_schema
    calls = []
    def post(url, **kwargs):
        calls.append(kwargs['json'])
        return httpx.Response(200, json={'message': {'content': '{"facts":[]}'}})
    monkeypatch.setattr(httpx, 'post', post)
    schema = selection_schema({'C002-S005': '박타자가 홈런을 기록했다.'})
    assert OllamaClient().json_chat('JSON만 반환', {'stage': 'extract'}, response_schema=schema) == {'facts': []}
    assert calls[0]['format'] == schema
    assert calls[0]['options']['temperature'] == 0


@pytest.mark.parametrize('text', ['{"facts":broken}', '[1,2]', 'JSON이 아닌 응답'])
def test_malformed_json_has_retryable_type_and_original_text(text):
    with pytest.raises(OllamaFormatError) as error:
        extract_json(text)
    assert error.value.response_text == text


def test_schema_http_error_never_downgrades_or_retries(monkeypatch):
    from sports_card_news.staged_editorial import ask, SourceSelection
    calls = []
    def post(url, **kwargs):
        calls.append(kwargs['json'])
        return httpx.Response(400, json={'error': 'unsupported format'})
    monkeypatch.setattr(httpx, 'post', post)
    with pytest.raises(OllamaError, match='HTTP 400: unsupported format'):
        ask(OllamaClient(), SourceSelection, 'JSON만 반환', {'stage': 'extract'})
    assert len(calls) == 1
    assert isinstance(calls[0]['format'], dict)


def test_generic_schema_retry_keeps_constraints(monkeypatch):
    from sports_card_news.staged_editorial import ask, SourceSelection
    calls = []
    responses = iter(['{"facts":broken}', '{"facts":[]}'])
    def post(url, **kwargs):
        calls.append(kwargs['json'])
        return httpx.Response(200, json={'message': {'content': next(responses)}})
    monkeypatch.setattr(httpx, 'post', post)
    assert ask(OllamaClient(), SourceSelection, 'JSON만 반환', {'stage': 'extract'}).facts == []
    assert len(calls) == 2
    assert calls[0]['format'] == calls[1]['format'] == SourceSelection.model_json_schema()


def test_successive_markdown_jobs_use_fresh_schemas_and_sources(tmp_path, monkeypatch):
    """Exercise actual HTTP request construction; judgments remain scripted, not a live LLM."""
    import json
    from datetime import date
    from sports_card_news.local_studio import LocalStudioRequest, run_local_studio
    from sports_card_news.staged_editorial import normalize_quote
    from test_local_studio import FakeOllama

    responder = FakeOllama()
    calls = []
    def post(url, **kwargs):
        request = kwargs['json']
        payload = json.loads(request['messages'][1]['content'])
        schema = request['format']
        # Every stage must constrain generation, not merely validate afterwards.
        assert isinstance(schema, dict)
        assert schema['type'] == 'object'
        assert schema['additionalProperties'] is False
        calls.append((payload, schema))
        if payload['stage'] == 'extract':
            assert schema['$defs']['SourceChoice']['properties']['source_id']['enum'] == list(payload['source_units'])
        result = responder.json_chat(request['messages'][0]['content'], payload, response_schema=schema)
        return httpx.Response(200, json={'message': {'content': json.dumps(result, ensure_ascii=False)}})
    monkeypatch.setattr(httpx, 'post', post)
    sources = [
        '- 김투수가 **8탈삼진**을 기록했다.\r\n\r\n'
        '- 박타자가 결승 홈런을 기록했다.\r\n\r\n- 정투수가 세이브를 기록했다.',
        '> 이타자가 **4안타**를 기록했다.\n\n'
        '> 최투수가 무실점으로 경기를 마쳤다.\n\n> 한타자가 결승타를 기록했다.',
    ]
    client = OllamaClient()  # Reuse client to expose any stale schema/source leakage.
    for index, source in enumerate(sources):
        folder, package = run_local_studio(LocalStudioRequest(
            edition_date=date(2026, 10, 13), category='KBO', markdown_text=source,
            source_name=f'news-{index}.md', page_count=7),
            output_root=tmp_path/f'run-{index}', memory_path=tmp_path/'memory.sqlite3', client=client)
        facts = json.loads((folder/'extracted-facts.json').read_text())
        assert all(fact['quote'] in normalize_quote(source) for fact in facts)
        assert len(facts) == 3
        report = json.loads((folder/'extraction-diagnostic-001.json').read_text())
        assert report['response_format'] == 'json_schema'
        assert report['source_chunk'] == source
        assert report['status'] == 'passed'
        assert len(package.cards) == 7
        assert (folder/'card-07.png').exists()
        assert (folder/'work-bundle.zip').exists()
    assert {p['stage'] for p, _ in calls} >= {'extract', 'card', 'grounding_review', 'social', 'review'}
