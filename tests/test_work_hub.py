from datetime import datetime, timedelta, timezone
import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from sports_card_news.webapp import create_app
from sports_card_news.work_hub import performance_context
from test_webapp import make_project
from test_local_studio import FakeOllama


def payload(pages=10):
    editorial = FakeOllama().json_chat('', {})
    editorial['cards'] = editorial['cards'][:pages]
    source = '# KIA 6-4 LG\nKIA가 6-4로 승리했다. 김도영이 9회 시즌 42호 역전 3점 홈런을 기록했다. 정해영이 세이브를 기록했다.\nhttps://example.com/source'
    return {'edition_date': '2026-10-06', 'category': 'KBO', 'topic': '경기 브리핑 테스트', 'page_count': pages,
            'markdown_text': source, 'editorial': editorial,
            'evidence': {str(i): 'KIA가 6-4로 승리했다.' for i in range(1, pages+1)}}


def review_data():
    return {'template_id': 'MASTER_TEST', 'design_url': 'https://www.canva.com/design/TEST/edit', 'reviewer': '편집자',
            'facts_checked': True, 'duplicates_checked': True, 'visual_checked': True, 'rights_checked': True,
            'notes': '테스트 원문과 비교 및 디자인 확인 완료'}


@pytest.mark.parametrize('pages', [7, 10])
def test_work_import_bundle_and_reload_without_llm(tmp_path, monkeypatch, pages):
    root = make_project(tmp_path)
    monkeypatch.setattr('sports_card_news.work_hub.render_studio_package', lambda *args: None)
    with TestClient(create_app(root)) as client:
        response = client.post('/api/work/import', json=payload(pages))
        assert response.status_code == 201, response.text
        session = response.json()['session_id']
        detail = client.get(f'/api/work/sessions/{session}').json()
        assert len(detail['package']['cards']) == pages
        assert detail['package']['agent_outputs'] == []
        assert detail['package']['needs_human_approval']
        download = client.get(f'/api/work/sessions/{session}/bundle')
        with zipfile.ZipFile(io.BytesIO(download.content)) as bundle:
            handoff = json.loads(bundle.read('work-handoff.json'))
            assert handoff['external_actions_executed'] is False
            assert handoff['collection_cutoff']['local_time'] == '23:50'
            assert handoff['metricool']['scheduled_at'] is None
            assert f'p{pages:02d}_headline' in bundle.read('canva-bulk.csv').decode('utf-8-sig')
            assert bundle.read('source.md').decode() == payload(pages)['markdown_text']
            assert 'evidence.json' in bundle.namelist()
        assert client.get('/work').status_code == 200
    with TestClient(create_app(root)) as client:
        assert client.get('/api/work/sessions').json()['items'][0]['session_id'] == session


@pytest.mark.parametrize('mutation', ['evidence', 'count', 'sequence'])
def test_bad_work_input_is_rejected_before_render(tmp_path, mutation):
    data = payload()
    if mutation == 'evidence':
        data['evidence']['2'] = '존재하지 않는 경기 결과'
    elif mutation == 'count':
        data['page_count'] = 7
    else:
        data['editorial']['cards'][1]['slide'] = 1
    with TestClient(create_app(make_project(tmp_path))) as client:
        assert client.post('/api/work/import', json=data).status_code == 422
        assert not list((tmp_path/'output'/'studio').glob('*'))


def test_review_receipt_metrics_guards_and_persistence(tmp_path, monkeypatch):
    root = make_project(tmp_path)
    monkeypatch.setattr('sports_card_news.work_hub.render_studio_package', lambda *args: None)
    with TestClient(create_app(root)) as client:
        session = client.post('/api/work/import', json=payload()).json()['session_id']
        base = f'/api/work/sessions/{session}'
        now = datetime.now(timezone.utc)
        receipt = {'brand_id': 'brand-1', 'post_id': 'post-1', 'scheduled_at': (now-timedelta(days=3)).isoformat()}
        assert client.post(base+'/schedule-receipt', json=receipt).status_code == 409
        invalid = review_data(); invalid['facts_checked'] = False
        assert client.post(base+'/review', json=invalid).status_code == 422
        invalid = review_data(); invalid['design_url'] = 'https://canva.com.evil.example/design/x'
        assert client.post(base+'/review', json=invalid).status_code == 422
        assert client.post(base+'/review', json=review_data()).status_code == 200
        assert client.post(base+'/schedule-receipt', json=receipt).status_code == 200
        assert client.post(base+'/schedule-receipt', json=receipt).status_code == 200
        assert client.post(base+'/schedule-receipt', json={**receipt, 'post_id':'post-2'}).status_code == 409
        other = client.post('/api/work/import', json=payload(7)).json()['session_id']
        other_base = f'/api/work/sessions/{other}'
        assert client.post(other_base+'/review', json=review_data()).status_code == 200
        assert client.post(other_base+'/schedule-receipt', json=receipt).status_code == 409
        metrics = {'post_id':'other', 'collected_at':now.isoformat(), 'window_hours':48,
                   'reach':0, 'impressions':0, 'likes':0, 'comments':0, 'saves':0, 'shares':0}
        assert client.post(base+'/metrics', json=metrics).status_code == 409
        metrics['post_id'] = 'post-1'
        assert client.post(base+'/metrics', json={**metrics, 'reach':-1}).status_code == 422
        assert client.post(base+'/metrics', json={**metrics, 'collected_at':(now-timedelta(days=2)).isoformat()}).status_code == 422
        response = client.post(base+'/metrics', json=metrics)
        assert response.status_code == 200, response.text
        assert response.json()['metrics']['save_rate'] is None
        states = {item['session_id']:item['status'] for item in client.get('/api/work/sessions').json()['items']}
        assert states[session] == 'metrics_recorded'
        group = client.get('/api/work/performance').json()['groups'][0]
        assert group['sample_count'] == 1
        assert '표본 부족' in group['interpretation']
    with TestClient(create_app(root)) as client:
        assert client.get(base).json()['metrics']['post_id'] == 'post-1'
        path = root/'output'/'studio'/session/'source.md'
        path.write_text(path.read_text()+'\n원문 수정됨')
        assert client.get(base).json()['review_valid'] is False
        assert client.post(base+'/schedule-receipt', json=receipt).status_code == 409
        assert client.post(base+'/metrics', json=metrics).status_code == 409
    assert performance_context(root/'data'/'work_operations.sqlite3', 'MLB')['groups'] == []


def test_work_schema_has_roles_and_7_or_10_pages(tmp_path):
    with TestClient(create_app(make_project(tmp_path))) as client:
        data = client.get('/api/work/import-schema').json()
        assert len(data['team']) == 6
        assert data['schema']['properties']['page_count']['enum'] == [7,10]
        assert data['cutoffs']['EPL'] == '08:00'
