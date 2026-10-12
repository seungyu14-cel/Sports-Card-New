"""Synthetic data only: these are not real KBO results."""
import json
from collections import Counter
from datetime import date

import pytest
from langchain_core.documents import Document

from sports_card_news.grounded_editorial import (
    EvidenceRetriever, GroundingReviewRequired, build_index,
    generate_grounded, numeric_issues,
)
from sports_card_news.local_studio import LocalStudioRequest, run_local_studio
from sports_card_news.staged_editorial import normalize_quote
from sports_card_news.studio import CardCopy
from test_local_studio import FakeOllama, passing_relation_review


def document(text, evidence_id='e1', source='source-a', league='KBO'):
    return Document(page_content=text, metadata={
        'evidence_id': evidence_id, 'source_sha256': source, 'league': league})


@pytest.mark.parametrize('copy', [
    '김투수가 9탈삼진을 기록했다.',  # Invented number
    '김투수의 평균자책점은 2.15다.',  # Decimal alteration
])
def test_invented_values_are_blocked_before_relation_review(copy):
    docs = [document('김투수가 8탈삼진을 기록했다. KIA가 LG에 6-4로 승리했다. 김투수의 평균자책점은 1.25다.')]
    assert numeric_issues({'body': copy}, docs)


def test_literal_numbers_with_formatting_and_decimals_pass():
    docs = [document('김투수가 **8탈삼진**을 기록했다. 평균자책점은 1.25다.')]
    assert not numeric_issues({'body': '김투수가 8탈삼진을 기록했다.\n평균자책점은 1.25다.'}, docs)
    assert numeric_issues({'key_stat': '8탈삼진'}, [document('18탈삼진')])


def test_retrieval_never_borrows_unplanned_other_game_or_source():
    docs = [document('김투수가 8탈삼진을 기록했다.'),
            document('다른 경기 김투수가 9탈삼진을 기록했다.', 'e2'),
            document('김투수가 9탈삼진을 기록했다.', 'e1', source='old-source'),
            document('김투수가 9탈삼진을 기록했다.', 'e1', league='MLB')]
    retriever = EvidenceRetriever(documents=docs, allowed_ids=['e1'],
                                  source_sha256='source-a', league='KBO')
    assert [d.page_content for d in retriever.invoke('김투수 9탈삼진')] == [docs[0].page_content]
    with pytest.raises(ValueError, match='근거를 검색하지 못했습니다'):
        retriever.model_copy(update={'allowed_ids': ['missing']}).invoke('김투수')


def test_index_offsets_recover_quote_and_source_hash(tmp_path):
    chunks = ['# 테스트\n', '김투수가 **8탈삼진**을 기록했다.']
    quote = normalize_quote(chunks[1])
    facts = [{'quote': quote, 'chunk': 2, 'importance': 90}]
    docs = build_index(facts, chunks, ''.join(chunks), 'KBO', tmp_path)
    m = docs[0].metadata
    raw = ''.join(chunks)[m['raw_chunk_start']:m['raw_chunk_end']]
    assert normalize_quote(raw)[m['normalized_quote_start']:m['normalized_quote_end']] == quote
    assert m['verification_status'] == 'uploaded_source_only'
    assert facts[0]['evidence_id'] == m['evidence_id']
    assert len(m['source_sha256']) == 64


class RepairClient:
    def __init__(self, *, never_fix=False, semantic_failure=False, crash=False):
        self.calls = []
        self.never_fix = never_fix
        self.semantic_failure = semantic_failure
        self.crash = crash

    def json_chat(self, system, payload):
        from sports_card_news.ollama_client import OllamaClient
        OllamaClient().check_budget(system, payload)
        self.calls.append(payload['stage'])
        if payload['stage'] == 'grounding_review':
            verdict = passing_relation_review(payload)
            if self.semantic_failure:
                verdict['reviews'][0]['checks']['outcome'] = False
                verdict['reviews'][0]['reason'] = '원문에 역전승 근거가 없습니다.'
            return verdict
        if self.crash and payload['stage'] == 'repair_card':
            raise RuntimeError('model unavailable')
        wrong = payload['stage'] == 'card' or self.never_fix
        return {'slide': payload['slide'], 'role': payload['role'],
                'headline': '경기 주요 기록', 'body': f'김투수가 {9 if wrong else 8}탈삼진을 기록했다.',
                'key_stat': '', 'kicker': '', 'visual_direction': ''}


def generate(client, path):
    return generate_grounded(client=client, schema=CardCopy, system='근거 기반 카드 작성',
        payload={'stage': 'card', 'slide': 2, 'role': '메인 이슈', 'evidence': ['김투수가 8탈삼진을 기록했다.']},
        documents=[document('김투수가 8탈삼진을 기록했다.')], evidence_ids=['e1'],
        destination=path, label='card-02', notify=lambda *args: None, percent=40)


def test_graph_repairs_and_revalidates_only_bad_card(tmp_path):
    client = RepairClient()
    card = generate(client, tmp_path)
    assert card.body == '김투수가 8탈삼진을 기록했다.'
    assert client.calls == ['card', 'repair_card', 'grounding_review']
    report = json.loads((tmp_path/'grounding-card-02.json').read_text())
    assert report['status'] == 'passed'
    assert report['repairs'] == 1
    assert report['attempts'][0]['issues'][0]['code'] == 'numeric_value_not_in_evidence'
    assert report['attempts'][1]['issues'] == []


def test_failed_repairs_stop_after_two_and_keep_all_versions(tmp_path):
    client = RepairClient(never_fix=True)
    with pytest.raises(GroundingReviewRequired) as error:
        generate(client, tmp_path)
    assert client.calls == ['card', 'repair_card', 'repair_card']
    report = json.loads(error.value.report_path.read_text())
    assert report['status'] == 'needs_review'
    assert len(report['attempts']) == 3
    assert report['retrieved'][0]['page_content'] == '김투수가 8탈삼진을 기록했다.'


def test_semantic_rejection_cannot_be_overridden_by_numeric_pass(tmp_path):
    client = RepairClient(semantic_failure=True)
    with pytest.raises(GroundingReviewRequired):
        generate(client, tmp_path)
    assert client.calls.count('repair_card') == 2
    report = json.loads((tmp_path/'grounding-card-02.json').read_text())
    assert report['attempts'][-1]['issues'][0]['code'] == 'fact_relationship_mismatch'


def test_model_failure_keeps_previous_rejected_copy(tmp_path):
    with pytest.raises(RuntimeError, match='model unavailable'):
        generate(RepairClient(crash=True), tmp_path)
    report = json.loads((tmp_path/'grounding-card-02.json').read_text())
    assert report['status'] == 'technical_error'
    assert report['attempts'][0]['copy']['body'] == '김투수가 9탈삼진을 기록했다.'


SOURCE = ('김투수가 8탈삼진을 기록했다. KIA가 LG에 6-4로 승리했다. '
          '박타자가 결승 홈런을 기록했다. 정투수가 세이브를 기록했다.')


class FullRunClient(FakeOllama):
    def __init__(self, fail=False, corrupt_social=False):
        super().__init__()
        self.stages = []
        self.fail = fail
        self.corrupt_social = corrupt_social

    def json_chat(self, system, payload):
        from sports_card_news.ollama_client import OllamaClient
        OllamaClient().check_budget(system, payload)
        self.stages.append((payload['stage'], payload.get('slide')))
        if payload['stage'] == 'repair_card':
            return {**payload['previous_copy'], 'body': '김투수가 9탈삼진을 기록했다.' if self.fail else payload['evidence'][0]}
        if payload['stage'] == 'repair_social':
            return super().json_chat(system, {**payload, 'stage': 'social'})
        result = super().json_chat(system, payload)
        if payload['stage'] == 'card' and payload['slide'] == 2:
            result['body'] = '김투수가 9탈삼진을 기록했다.'
        if payload['stage'] == 'social' and self.corrupt_social:
            result['social']['post_title'] = '김투수가 9탈삼진을 기록했다.'
        return result


def run(client, tmp_path, league='KBO'):
    return run_local_studio(LocalStudioRequest(edition_date=date(2026,10,12),
        category=league, markdown_text=SOURCE), output_root=tmp_path/'output',
        memory_path=tmp_path/'memory.sqlite3', client=client)


def test_end_to_end_one_card_repair_has_provenance_in_download(tmp_path, monkeypatch):
    import zipfile
    client = FullRunClient(corrupt_social=True)
    folder, package = run(client, tmp_path)
    counts = Counter(client.stages)
    assert all(counts['card', i] == 1 for i in range(1,11))
    assert counts['repair_card', 2] == 1
    assert counts['repair_social', None] == 1
    assert package.cards[1].body == '김투수가 8탈삼진을 기록했다.'
    summary = json.loads((folder/'grounding-summary.json').read_text())
    assert len(summary['items']) == 11
    assert all(item['status'] == 'passed' for item in summary['items'])
    with zipfile.ZipFile(folder/'work-bundle.zip') as archive:
        assert {'evidence-index.json', 'grounding-summary.json', 'grounding-card-02.json'} <= set(archive.namelist())
    # Rendering must not inject an unrelated cover fact into another card.
    from sports_card_news import studio_renderer
    fit = studio_renderer._fit_text
    rendered_text = []
    def capture(draw, text, *args):
        rendered_text.append(text)
        return fit(draw, text, *args)
    monkeypatch.setattr(studio_renderer, '_fit_text', capture)
    studio_renderer._render_card(package.model_copy(update={'master_headline': '다른 경기 99득점'}),
                                package.cards[1], tmp_path/'isolated-card.png')
    assert '다른 경기 99득점' not in rendered_text
    assert rendered_text[-1] == package.cards[1].headline


def test_failed_session_has_no_publishable_package_or_learning(tmp_path):
    from sports_card_news.feedback_memory import FeedbackMemory
    with pytest.raises(GroundingReviewRequired):
        run(FullRunClient(fail=True), tmp_path)
    assert not list((tmp_path/'output').rglob('studio-package.json'))
    assert not list((tmp_path/'output').rglob('work-bundle.zip'))
    assert not list((tmp_path/'output').rglob('*.png'))
    assert FeedbackMemory(tmp_path/'memory.sqlite3').stats() == {'feedback_count': 0, 'run_count': 0}


def test_other_leagues_keep_existing_path(tmp_path):
    client = FullRunClient()
    folder, _ = run(client, tmp_path, 'NPB')
    assert not (folder/'grounding-summary.json').exists()
    assert not any(stage.startswith('repair_') or stage == 'grounding_review' for stage, _ in client.stages)
