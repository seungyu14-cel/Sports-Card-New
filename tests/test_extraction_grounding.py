"""Source fidelity tests. Sports copy is input text, not verified sports data."""
import json
from datetime import date

import pytest

from sports_card_news.staged_editorial import (
    ExtractionReviewRequired, extract_chunk, normalize_quote, source_units,
)


class Responses:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def json_chat(self, system, payload):
        from sports_card_news.ollama_client import OllamaClient
        OllamaClient().check_budget(system, payload)
        self.requests.append(payload)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response(payload) if callable(response) else response


def choose_first(payload):
    return {'facts': [{'source_id': next(iter(payload['source_units'])), 'importance': 90}]}


def test_formatting_and_wrapped_lines_are_copied_without_model_retyping(tmp_path):
    source = '## 경기 결과\n\n- 두산은 **7-5**로\n  승리했다.\n'
    client = Responses([lambda p: {'facts': [{'source_id': list(p['source_units'])[1], 'importance': 90}]}])
    result = extract_chunk(client, 'KBO', source, 1, tmp_path, lambda: pytest.fail('불필요한 재시도'))
    assert result.facts[0].quote == '두산은 7-5로 승리했다.'
    assert len(client.requests) == 1
    assert normalize_quote('`김도영`의 __홈런__ 기록') == '김도영의 홈런 기록'


NAME_SOURCE = ('맨체스터 시티가 안필드 원정에서 리버풀을 3-0으로 꺾었다. '
    '리버풀의 라이언 흐라벤베르흐가 경고 누적으로 퇴장한 뒤 엘링 홀란, 제레미 도쿠, 라얀 체르키가 차례로 득점했다. '
    '맨시티는 리그 개막 6경기를 모두 이겨 승점 18점을 기록했고, 2위 아스널과의 승점 차를 3점으로 벌렸다.')


def test_reported_korean_latin_name_corruption_cannot_enter_evidence(tmp_path):
    original = source_units(NAME_SOURCE, 1)[1]['quote']
    corrupted = original.replace('라얀', '라yan')
    assert corrupted not in normalize_quote(NAME_SOURCE)
    client = Responses([
        {'facts': [{'quote': corrupted, 'importance': 90}]},
        {'facts': [{'source_id': 'C001-S002', 'importance': 90}]},
    ])
    retries = []
    result = extract_chunk(client, 'EPL', NAME_SOURCE, 1, tmp_path, lambda: retries.append(1))
    assert retries == [1]
    assert result.facts[0].quote == original
    assert '라yan' not in result.facts[0].quote
    report = json.loads((tmp_path/'extraction-diagnostic-001.json').read_text())
    assert report['status'] == 'recovered'
    assert report['attempts'][0]['model_response']['facts'][0]['quote'] == corrupted
    assert report['selected_quotes'][0]['quote'] == original


@pytest.mark.parametrize('response', [
    {'facts': [{'source_id': 'C999-S001', 'importance': 90}]},
    {'facts': [{'source_id': 'C002-S999', 'importance': 90}]},
    {'facts': [{'source_id': 'C002-S001', 'importance': 90, 'quote': '두산은 8-5로 승리했다.'}]},
    {'facts': [{'source_id': 'C002-S001', 'importance': 90}]*2},
    {'facts': [{'source_id': 'C002-S001', 'importance': True}]},
])
def test_invalid_selection_stops_after_one_retry_with_diagnostics(tmp_path, response):
    source = '두산은 **7-5**로 승리했다.'
    client = Responses([response, response])
    retries = []
    with pytest.raises(ExtractionReviewRequired, match='원문 번호 선택') as error:
        extract_chunk(client, 'KBO', source, 2, tmp_path, lambda: retries.append(2))
    assert retries == [2]
    report = json.loads(error.value.report_path.read_text())
    assert report['source_chunk'] == source
    assert report['status'] == 'needs_review'
    assert len(report['attempts']) == 2
    assert all(attempt['issues'] for attempt in report['attempts'])
    assert 'selected_quotes' not in report


def test_only_failed_chunk_retried_and_recovery_logged(tmp_path):
    client = Responses([choose_first, {'facts': [{'source_id': 'C001-S001', 'importance': 90}]}, choose_first])
    retries = []
    extract_chunk(client, 'KBO', '김도영이 홈런을 기록했다.', 1, tmp_path, lambda: retries.append(1))
    result = extract_chunk(client, 'KBO', '두산은 **7-5**로 승리했다.', 2, tmp_path, lambda: retries.append(2))
    assert [list(p['source_units']) for p in client.requests] == [['C001-S001'], ['C002-S001'], ['C002-S001']]
    assert retries == [2]
    assert result.facts[0].quote == '두산은 7-5로 승리했다.'
    assert json.loads((tmp_path/'extraction-diagnostic-002.json').read_text())['status'] == 'recovered'


def test_normalization_preserves_meaningful_symbols_and_word_boundaries():
    for text in ['7-5', '1.25', '-3', '~~승리~~', '42호', '김 도영']:
        assert normalize_quote(text) == text
    assert normalize_quote('두산은\t  승리했다.') == '두산은 승리했다.'


def test_span_offsets_preserve_decimals_and_long_text():
    source = '평균자책점은 **1.25**다.\n\n' + '선수의 긴 설명 ' * 40 + '기록은 -3이다.'
    units = source_units(source, 4)
    normalized = normalize_quote(source)
    assert ' '.join(unit['quote'] for unit in units) == normalized
    assert units[0]['quote'] == '평균자책점은 1.25다.'
    for unit in units:
        assert 5 <= len(unit['quote']) <= 160
        assert normalized[unit['start']:unit['end']] == unit['quote']


def test_dense_short_sentences_are_batched_without_dropping_units(tmp_path):
    source = ' '.join(f'팀{i} 승리.' for i in range(180))
    client = Responses([choose_first]*20)
    result = extract_chunk(client, 'EPL', source, 1, tmp_path, lambda: pytest.fail('retry'))
    sent = [text for request in client.requests for text in request['source_units'].values()]
    assert ' '.join(sent) == source
    assert len(client.requests) > 1
    assert len(result.facts) <= 4


def test_http_failure_after_rejected_selection_preserves_diagnostic(tmp_path):
    client = Responses([{'facts': [{'source_id': 'missing', 'importance': 90}]}, RuntimeError('offline')])
    with pytest.raises(RuntimeError, match='offline'):
        extract_chunk(client, 'EPL', NAME_SOURCE, 1, tmp_path, lambda: None)
    report = json.loads((tmp_path/'extraction-diagnostic-001.json').read_text())
    assert report['status'] == 'technical_error'
    assert report['attempts'][0]['issues']
    assert report['source_chunk'] == NAME_SOURCE


def test_epl_pipeline_generates_ten_cards_with_exact_selected_names(tmp_path):
    import zipfile
    from sports_card_news.local_studio import LocalStudioRequest, run_local_studio
    from test_local_studio import FakeOllama
    folder, package = run_local_studio(
        LocalStudioRequest(edition_date=date(2026, 10, 12), category='EPL', markdown_text=NAME_SOURCE),
        output_root=tmp_path/'output', memory_path=tmp_path/'memory.sqlite3', client=FakeOllama())
    assert len(package.cards) == 10
    assert (folder/'card-10.png').exists()
    assert (folder/'work-bundle.zip').exists()
    with zipfile.ZipFile(folder/'work-bundle.zip') as bundle:
        assert 'extraction-diagnostic-001.json' in bundle.namelist()
    facts = json.loads((folder/'extracted-facts.json').read_text())
    assert any('라얀 체르키' in fact['quote'] for fact in facts)
    assert all(fact['quote'] in NAME_SOURCE for fact in facts)
