"""Controlled reviewer judgments test enforcement, not real LLM accuracy."""
import json

import pytest

from sports_card_news.fact_verification import (
    RELATIONS, RelationVerdict, numbers, numeric_issues, relation_issues,
    review_claims, review_relationships,
)
from sports_card_news.grounded_editorial import generate_grounded, GroundingReviewRequired
from sports_card_news.studio import CardCopy
from test_grounded_editorial import document
from test_local_studio import passing_relation_review


CITY = ('맨시티는 리그 개막 6경기를 모두 이겨 승점 18점을 기록했고, '
        '2위 아스널과의 승점 차를 3점으로 벌렸다.')
CITY_COPY = {'slide': 1, 'role': '표지', 'kicker': '',
    'headline': '맨시티, 리그 개막 6전 전승',
    'body': '맨시티는 리그 개막 6경기를 모두 이겨 승점 18점을 기록했다. 2위 아스널과의 승점 차는 3점으로 벌렸다.',
    'key_stat': '승점 18, 2위 아스널과 3점 차', 'visual_direction': ''}


class RelationClient:
    def __init__(self, copy, failed_relation=None):
        self.copy = copy
        self.failed_relation = failed_relation
        self.requests = []

    def json_chat(self, system, payload, *, response_schema=None):
        from sports_card_news.ollama_client import OllamaClient
        OllamaClient().check_budget(system, payload)
        self.requests.append(payload)
        if payload['stage'] == 'grounding_review':
            verdict = passing_relation_review(payload)
            if self.failed_relation:
                for claim, review in zip(payload['claims'], verdict['reviews']):
                    if claim['field'] == 'body':
                        review['checks'][self.failed_relation] = False
                        review['reason'] = '근거의 사실 관계와 다릅니다.'
            return verdict
        assert '그대로 복사한다' not in system
        return self.copy


def graph(client, path, documents):
    return generate_grounded(client=client, schema=CardCopy, system='카드 문구 작성',
        payload={'stage': 'card', 'slide': 1, 'role': '표지'}, documents=documents,
        evidence_ids=[d.metadata['evidence_id'] for d in documents],
        destination=path, label='card-01', notify=lambda *args: None, percent=35)


def test_reported_city_cover_passes_relationship_review_without_verbatim_repair(tmp_path):
    docs = [document(CITY),
            document('첼시 공식 리포트에 따르면 구단의 프리미어리그 경기 중 가장 이른 두 골 차 리드였다.', 'e2'),
            document('맨체스터 시티가 안필드 원정에서 리버풀을 3-0으로 꺾었다.', 'e3')]
    client = RelationClient(CITY_COPY)
    result = graph(client, tmp_path, docs)
    assert result.model_dump() == CITY_COPY
    assert not any(p['stage'].startswith('repair_') for p in client.requests)
    report = json.loads((tmp_path/'grounding-card-01.json').read_text())
    assert report['schema_version'] == 2
    assert report['status'] == 'passed'
    assert report['repairs'] == 0
    audit = report['attempts'][0]['model_verdict']
    assert audit['method'] == 'fact_relationships'
    assert {c['field'] for c in audit['claims']} == {'headline', 'body', 'key_stat'}
    assert audit['evidence_map']['E1'] == 'e1'


@pytest.mark.parametrize('body,relation', [
    ('박투수가 8탈삼진을 기록했다.', 'subject'),
    ('김투수가 9탈삼진을 기록했다.', 'quantity'),  # Nine exists, but belongs to Park.
    ('김투수가 8볼넷을 기록했다.', 'unit'),
    ('KIA가 LG에 4-6으로 승리했다.', 'outcome'),
    ('김투수가 이번 경기에서 8탈삼진을 기록했다.', 'context'),
    ('김투수가 8탈삼진을 기록하지 않았다.', 'polarity'),
    ('김투수가 아홉 탈삼진을 기록했다.', 'quantity'),
])
def test_same_numbers_cannot_override_rejected_fact_relationships(tmp_path, body, relation):
    docs = [document('김투수가 지난 경기에서 8탈삼진을 기록했다. 박투수가 9탈삼진을 기록했다. KIA가 LG에 6-4로 승리했다.')]
    copy = {**CITY_COPY, 'headline': '오늘 경기 주요 기록', 'body': body, 'key_stat': ''}
    assert numeric_issues(copy, docs) == []  # Presence alone must NOT approve it.
    client = RelationClient(copy, relation)
    with pytest.raises(GroundingReviewRequired):
        graph(client, tmp_path, docs)
    report = json.loads((tmp_path/'grounding-card-01.json').read_text())
    assert report['repairs'] == 2
    assert len(report['attempts']) == 3
    assert all(a['issues'][0]['code'] == 'fact_relationship_mismatch' for a in report['attempts'])
    checks = report['attempts'][-1]['model_verdict']['batches'][0]['verdict']['reviews']
    assert any(not r['checks'][relation] for r in checks)


def test_equivalent_score_with_team_order_reversed_is_allowed(tmp_path):
    docs = [document('KIA가 LG에 6-4로 승리했다.')]
    copy = {**CITY_COPY, 'headline': 'KIA, LG전 승리', 'body': 'LG는 KIA에 4-6으로 패했다.', 'key_stat': ''}
    assert graph(RelationClient(copy), tmp_path, docs).body == copy['body']


@pytest.mark.parametrize('text', ['김투수가 18탈삼진을 기록했다.', '평균자책점은 2.15다.', '승점은 19점이다.'])
def test_changed_value_or_decimal_is_rejected_without_llm_approval(text):
    assert numeric_issues({'body': text}, [document('김투수는 8탈삼진, 평균자책점 1.25, 팀은 승점 17점이다.')])


def test_number_format_changes_are_equivalent_but_partial_digits_are_not():
    assert numbers('평균 .300, 1,250명') == numbers('평균 0.300, 1250명')
    assert numbers('평균 1.25') != numbers('평균 2.15')
    assert numbers('8탈삼진') != numbers('18탈삼진')


def checked(claim_id='C1', evidence_ids=None):
    return {'claim_id': claim_id, 'evidence_ids': evidence_ids or ['E1'],
            'checks': {key: True for key in RELATIONS}, 'reason': ''}


@pytest.mark.parametrize('reviews', [[], [checked(), checked()], [checked('unknown')]])
def test_missing_duplicate_or_unknown_claim_review_cannot_pass(reviews):
    claims = review_claims({'body': '김투수는 8탈삼진을 기록했다.'})
    issues = relation_issues(claims, RelationVerdict(reviews=reviews), {'E1': '김투수는 8탈삼진을 기록했다.'})
    assert issues[0]['code'] == 'incomplete_relation_review'


def test_cited_evidence_must_support_numbers_even_when_model_says_all_true():
    claims = review_claims({'body': '김투수는 9탈삼진을 기록했다.'})
    verdict = RelationVerdict(reviews=[checked()])
    issues = relation_issues(claims, verdict, {'E1': '김투수는 8탈삼진.', 'E2': '박투수는 9탈삼진.'})
    assert issues[0]['code'] == 'numeric_value_not_in_cited_evidence'
    verdict = RelationVerdict(reviews=[checked(evidence_ids=['E999'])])
    assert relation_issues(claims, verdict, {'E1': '김투수는 9탈삼진.'})[0]['code'] == 'invalid_relation_evidence'


def test_long_caption_and_twelve_tags_are_all_reviewed_in_bounded_batches():
    caption = ('김투수는 8탈삼진을 기록했다. 경기의 주요 기록을 함께 살펴보세요. ' * 24)[:1200]
    copy = {'master_headline': '오늘의 경기', 'social': {'caption': caption,
            'hashtags': [f'#응원태그{number}' for number in range(12)]}, 'shortform_hook': '경기 흐름을 살펴보세요.'}
    docs = [document('김투수는 8탈삼진을 기록했다. 0 1 2 3 4 5 6 7 8 9 10 11')]
    client = RelationClient(copy)
    issues, audit = review_relationships(client, copy, docs, 'social')
    assert not issues
    assert len(audit['batches']) > 1
    assert {c['id'] for c in audit['claims']} == {cid for batch in audit['batches'] for cid in batch['claim_ids']}
    reviewed_caption = ' '.join(c['text'] for c in audit['claims'] if c['field'] == 'social.caption')
    assert reviewed_caption.split() == caption.split()
    assert len([c for c in audit['claims'] if c['field'].startswith('social.hashtags.')]) == 12
    assert all(len(p['claims']) <= 3 for p in client.requests)


def test_partial_review_is_preserved_when_later_model_call_fails(tmp_path):
    copy = {**CITY_COPY, 'kicker': '오늘의 주요 이슈'}  # Four fields force multiple batches.
    class Crash(RelationClient):
        def json_chat(self, system, payload, *, response_schema=None):
            if payload['stage'] == 'grounding_review' and any(p['stage'] == 'grounding_review' for p in self.requests):
                raise RuntimeError('review unavailable')
            return super().json_chat(system, payload, response_schema=response_schema)
    with pytest.raises(RuntimeError, match='review unavailable'):
        graph(Crash(copy), tmp_path, [document(CITY)])
    report = json.loads((tmp_path/'grounding-card-01.json').read_text())
    assert report['status'] == 'technical_error'
    assert len(report['pending_review']['batches']) == 1
    assert report['pending_copy'] == copy
