import json

import pytest

from sports_card_news.staged_editorial import extract_chunk, normalize_quote


class Responses:
    def __init__(self, quotes):
        self.quotes = iter(quotes)
        self.sources = []

    def json_chat(self, system, payload):
        from sports_card_news.ollama_client import OllamaClient
        OllamaClient().check_budget(system, payload)
        self.sources.append(payload['source_chunk'])
        return {'facts': [{'quote': next(self.quotes), 'importance': 90}]}


def test_formatting_differences_need_no_retry(tmp_path):
    source = '## 경기 결과\n- 두산은 **7-5**로\n  승리했다.\n'
    client = Responses(['두산은 7-5로 승리했다.'])
    extract_chunk(client, 'KBO', source, 1, tmp_path, lambda: pytest.fail('불필요한 재시도'))
    assert len(client.sources) == 1
    assert normalize_quote('`김도영`의 __홈런__ 기록') == '김도영의 홈런 기록'


@pytest.mark.parametrize('quote', ['두산은 8-5로 승리했다.', 'LG는 7-5로 승리했다.',
                                  '두산은 75로 승리했다.'])
def test_real_changes_still_fail_and_preserve_both_attempts(tmp_path, quote):
    source = '두산은 **7-5**로 승리했다.'
    client = Responses([quote, quote])
    retries = []
    with pytest.raises(ValueError, match='원문에 없는 근거') as error:
        extract_chunk(client, 'KBO', source, 2, tmp_path, lambda: retries.append(2))
    assert retries == [2]
    report = json.loads((tmp_path / 'extraction-diagnostic-002.json').read_text())
    assert report['source_chunk'] == source
    assert report['status'] == 'failed'
    assert [a['rejected_quotes'] for a in report['attempts']] == [[quote], [quote]]
    assert 'extraction-diagnostic-002.json' in str(error.value)
    assert quote in str(error.value)


def test_only_failed_chunk_retried_and_recovery_logged(tmp_path):
    source1 = '김도영이 홈런을 기록했다.'
    source2 = '두산은 **7-5**로 승리했다.'
    client = Responses([source1, '두산은 8-5로 승리했다.', '두산은 7-5로 승리했다.'])
    retries = []
    extract_chunk(client, 'KBO', source1, 1, tmp_path, lambda: retries.append(1))
    result = extract_chunk(client, 'KBO', source2, 2, tmp_path, lambda: retries.append(2))
    assert client.sources == [source1, source2, source2]
    assert retries == [2]
    assert result.facts[0].quote == '두산은 7-5로 승리했다.'
    report = json.loads((tmp_path / 'extraction-diagnostic-002.json').read_text())
    assert report['status'] == 'recovered'
    assert report['attempts'][1]['rejected_quotes'] == []


def test_normalization_preserves_meaningful_symbols_and_word_boundaries():
    for text in ['7-5', '1.25', '-3', '~~승리~~', '42호', '김 도영']:
        assert normalize_quote(text) == text
    assert normalize_quote('두산은\t  승리했다.') == '두산은 승리했다.'
