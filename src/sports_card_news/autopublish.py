"""Canva REST -> durable Metricool media -> Instagram scheduling.

Uses independent API credentials; ChatGPT plugin credentials are never reused.
Mutations are not retried automatically after an ambiguous network failure.
"""
from __future__ import annotations
import hashlib
import json
import os
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse, quote
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
import httpx
from pydantic import Field, model_validator
from .models import StrictModel
from .studio import StudioPackage
from .work_hub import WorkStore, quality_report, stamp

REQUIRED_ENV = ('CANVA_ACCESS_TOKEN', 'METRICOOL_API_TOKEN', 'METRICOOL_USER_ID', 'METRICOOL_BLOG_ID')

class AutoRequest(StrictModel):
    template_id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,160}$')
    scheduled_at: datetime
    content_checked: bool
    template_and_rights_checked: bool
    authorize_schedule: bool
    reviewer: str = Field(min_length=1, max_length=80)
    warning_resolution: str = Field(default='', max_length=2000)

    @model_validator(mode='after')
    def validate(self):
        if self.scheduled_at.tzinfo is None or self.scheduled_at.utcoffset() is None:
            raise ValueError('예약 시각에 +09:00 등 시간대를 포함하세요.')
        if not all((self.content_checked, self.template_and_rights_checked, self.authorize_schedule)):
            raise ValueError('원고·템플릿·사진 권한 확인과 자동 예약 설정이 필요합니다.')
        return self


def configuration_status():
    missing = [key for key in REQUIRED_ENV if not os.getenv(key)]
    return {'configured': not missing, 'missing': missing,
            'brand_id': os.getenv('METRICOOL_BLOG_ID', ''),
            'message': '값 설정 여부만 확인했습니다. 실제 계정 권한은 준비 상태 검사에서 확인합니다.'}


class ProviderError(RuntimeError):
    pass


class Providers:
    def __init__(self, client=None, sleep=time.sleep):
        self.client = client or httpx.Client(timeout=45, follow_redirects=False)
        self.owns_client = client is None
        self.sleep = sleep

    def close(self):
        if self.owns_client:
            self.client.close()

    def call(self, provider, method, path, **kwargs):
        if provider == 'canva':
            base = 'https://api.canva.com/rest/v1'
            headers = {'Authorization': 'Bearer ' + os.environ['CANVA_ACCESS_TOKEN']}
        else:
            base = 'https://app.metricool.com/api'
            headers = {'X-Mc-Auth': os.environ['METRICOOL_API_TOKEN']}
            kwargs['params'] = {'userId': os.environ['METRICOOL_USER_ID'], 'blogId': os.environ['METRICOOL_BLOG_ID'], **kwargs.pop('params', {})}
        try:
            response = self.client.request(method, base+path, headers=headers, **kwargs)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as error:
            # Provider bodies can echo auth headers or signed media URLs.
            raise ProviderError(f'{provider} HTTP {error.response.status_code}: 연결·권한·요금제·요청을 확인하세요. 자동 재시도하지 않습니다.') from None
        except (httpx.RequestError, ValueError):
            raise ProviderError(f'{provider} 응답 확인 실패. 외부 처리 여부를 확인한 후 재개하세요. 자동 재전송하지 않습니다.') from None

    def preflight(self, template_id, fields):
        dataset = self.call('canva', 'GET', f'/brand-templates/{quote(template_id, safe="")}/dataset').get('dataset', {})
        if not dataset or set(dataset) != set(fields) or any(v.get('type') != 'text' for v in dataset.values()):
            raise ProviderError('템플릿 자동 채우기 필드가 원고와 다릅니다. p01_headline/body/kicker/key_stat 등 모든 페이지의 텍스트 필드를 정확히 맞추세요.')
        status = self.call('metricool', 'GET', '/v2/scheduler/posts/instagram-properties')
        if status.get('data', {}).get('autopublishAllowed') is not True:
            raise ProviderError('선택한 Metricool 브랜드에서 Instagram 자동 게시를 사용할 수 없습니다.')
        return {'ready': True, 'field_count': len(dataset), 'instagram_autopublish': True}

    def poll(self, kind, job_id):
        for _ in range(60):
            job = self.call('canva', 'GET', f'/{kind}/{quote(str(job_id), safe="")}')['job']
            if job['status'] == 'success':
                return job
            if job['status'] == 'failed':
                raise ProviderError(f'Canva {kind} 작업 실패. 기록된 job ID를 확인하세요.')
            self.sleep(2)
        raise ProviderError('Canva 작업 대기 시간 초과. 작업 ID로 결과를 확인하세요.')

    def normalize_media(self, url):
        data = self.call('metricool', 'GET', '/actions/normalize/image/url', params={'url': url})
        value = data.get('data', data) if isinstance(data, dict) else data
        value = value.get('url') if isinstance(value, dict) else value
        parsed = urlparse(value) if isinstance(value, str) else None
        if not parsed or parsed.scheme != 'https' or not (parsed.hostname == 'metricool.com' or (parsed.hostname or '').endswith('.metricool.com')) or parsed.query:
            raise ProviderError('Metricool의 영구 미디어 URL을 확인하지 못했습니다. 임시 Canva URL로 예약하지 않습니다.')
        return value


def fields_for(package):
    if len(package.cards) not in (7, 10) or [c.slide for c in package.cards] != list(range(1, len(package.cards)+1)):
        raise ValueError('7장 또는 10장의 순서가 맞는 원고가 필요합니다.')
    return {f'p{c.slide:02d}_{key}': {'type': 'text', 'text': getattr(c, key)}
            for c in package.cards for key in ('headline', 'body', 'kicker', 'key_stat')}


class AutoPublisher:
    def __init__(self, output_root: Path, db_path: Path):
        self.output_root, self.db_path = output_root, db_path
        self.store = WorkStore(db_path)
        with self.store.connect() as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS auto_publish_runs (session_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, payload TEXT NOT NULL)')

    def load(self, session_id):
        if not re.fullmatch(r'[A-Za-z0-9_-]{6,40}', session_id):
            raise ValueError('세션 ID가 올바르지 않습니다.')
        folder = self.output_root/'studio'/session_id
        raw = (folder/'studio-package.json').read_text(encoding='utf-8')
        source = (folder/'source.md').read_text(encoding='utf-8')
        return StudioPackage.model_validate_json(raw), source, hashlib.sha256((raw+source).encode()).hexdigest()

    def get(self, session_id):
        with self.store.connect() as conn:
            row = conn.execute('SELECT payload FROM auto_publish_runs WHERE session_id=?', (session_id,)).fetchone()
        return json.loads(row[0]) if row else {'status': 'not_started'}

    def save(self, session_id, value):
        with self.store.connect() as conn:
            conn.execute('UPDATE auto_publish_runs SET payload=? WHERE session_id=?', (json.dumps(value, ensure_ascii=False), session_id))

    def prepare(self, session_id, request):
        package, source, fingerprint = self.load(session_id)
        existing = self.get(session_id)
        if existing['status'] != 'not_started':
            return existing, False
        if self.store.get(session_id)['receipt']:
            raise ValueError('이미 예약 결과가 있는 세션입니다.')
        missing = configuration_status()['missing']
        if missing:
            raise ValueError('로컬 .env 설정 필요: ' + ', '.join(missing))
        if request.scheduled_at <= datetime.now(timezone.utc)+timedelta(minutes=10):
            raise ValueError('제작 시간을 고려해 최소 10분 이후로 예약하세요.')
        fields_for(package)
        caption = package.social.caption+'\n\n'+' '.join(package.social.hashtags)
        if len(caption) > 2200:
            raise ValueError('Instagram 캡션은 2200자 이내로 줄이세요.')
        if quality_report(package, source)['flags'] and not request.warning_resolution.strip():
            raise ValueError('원고 검사 경고의 확인·해결 내용을 기록하세요.')
        state = {'status': 'queued', 'stage': 'preflight', 'session_id': session_id, 'fingerprint': fingerprint,
                 'request': request.model_dump(mode='json'), 'brand_id': os.environ['METRICOOL_BLOG_ID'],
                 'created_at': stamp(), 'external_actions_executed': False, 'jobs': []}
        with self.store.connect() as conn:
            try:
                conn.execute('INSERT INTO auto_publish_runs VALUES (?, ?, ?)', (session_id, fingerprint, json.dumps(state, ensure_ascii=False)))
            except sqlite3.IntegrityError:
                return self.get(session_id), False
        return state, True

    def execute(self, session_id, provider=None):
        state = self.get(session_id)
        # Atomic claim prevents double scheduling from concurrent workers or clicks.
        with self.store.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT payload FROM auto_publish_runs WHERE session_id=?', (session_id,)).fetchone()
            if not row or json.loads(row[0])['status'] != 'queued':
                return self.get(session_id)
            state = json.loads(row[0]); state['status'] = 'running'
            conn.execute('UPDATE auto_publish_runs SET payload=? WHERE session_id=?', (json.dumps(state), session_id))
        p = provider
        def checkpoint(stage):
            state['stage'] = stage
            self.save(session_id, state)
        try:
            p = p or Providers()
            request = AutoRequest.model_validate(state['request'])
            package, source, fingerprint = self.load(session_id)
            if fingerprint != state['fingerprint'] or os.environ['METRICOOL_BLOG_ID'] != state['brand_id']:
                raise ValueError('원고 또는 대상 브랜드가 변경되어 실행을 중단했습니다.')
            fields = fields_for(package)
            p.preflight(request.template_id, fields)
            state['external_actions_executed'] = True
            checkpoint('canva_create')
            job = p.call('canva', 'POST', '/autofills', json={'type':'create_from_brand_template', 'brand_template_id':request.template_id,
                          'title':package.master_headline, 'data':fields})['job']
            state['jobs'].append({'kind':'autofills', 'id':job['id']}); checkpoint('canva_wait')
            result = p.poll('autofills', job['id'])
            design = result['result']['design']; state['design_id'] = design['id']
            state['design_url'] = design.get('urls', {}).get('edit_url') or design.get('url') or ''
            checkpoint('canva_export')
            design_meta = p.call('canva', 'GET', '/designs/'+quote(design['id'], safe=''))['design']
            if design_meta.get('page_count') != len(package.cards):
                raise ProviderError('완성 Canva 디자인 페이지 수가 원고와 다릅니다.')
            media = []
            # One page per export guarantees carousel ordering and avoids ZIP exports.
            for card in package.cards:
                job = p.call('canva', 'POST', '/exports', json={'design_id':design['id'],
                         'format':{'type':'png', 'pages':[card.slide], 'width':1080, 'height':1350}})['job']
                state['jobs'].append({'kind':'exports', 'id':job['id'], 'page':card.slide}); checkpoint('canva_export')
                urls = p.poll('exports', job['id'])['urls']
                if len(urls) != 1:
                    raise ProviderError('Canva 페이지별 이미지 URL 수가 올바르지 않습니다.')
                media.append(p.normalize_media(urls[0]))
            checkpoint('metricool_schedule')
            if request.scheduled_at <= datetime.now(timezone.utc)+timedelta(minutes=1):
                raise ValueError('제작 중 예약 시각이 임박했습니다. 외부 예약은 실행하지 않았습니다.')
            if self.load(session_id)[2] != fingerprint:
                raise ValueError('제작 중 원고가 변경되어 예약을 중단했습니다.')
            caption = package.social.caption+'\n\n'+' '.join(package.social.hashtags)
            local_time = request.scheduled_at.astimezone(ZoneInfo('Asia/Seoul')).strftime('%Y-%m-%dT%H:%M:%S')
            body = {'publicationDate':{'dateTime':local_time,'timezone':'Asia/Seoul'}, 'text':caption,
                    'providers':[{'network':'instagram'}], 'media':media, 'mediaAltText':[c.headline for c in package.cards],
                    'autoPublish':True, 'draft':False, 'saveExternalMediaFiles':True, 'instagramData':{'autoPublish':True,'type':'POST'}}
            # Mark the uncertainty window BEFORE sending a non-idempotent request.
            state['schedule_attempted'] = True; self.save(session_id, state)
            post = p.call('metricool', 'POST', '/v2/scheduler/posts', json=body)['data']
            state['post_id'] = str(post['id']); checkpoint('verify_reservation')
            confirmed = p.call('metricool', 'GET', '/v2/scheduler/posts/'+quote(state['post_id'], safe=''))['data']
            if (str(confirmed.get('id')) != state['post_id'] or confirmed.get('draft') is not False
                or confirmed.get('text') != caption or confirmed.get('media') != media
                or confirmed.get('publicationDate') != body['publicationDate']
                or not any(x.get('network') == 'instagram' and x.get('status') == 'PENDING' for x in confirmed.get('providers', []))):
                raise ProviderError('예약 응답의 내용·이미지·시간·상태를 확인하지 못했습니다. Metricool에서 확인하세요.')
            self.store.set(session_id, 'review', {'fingerprint':fingerprint, 'reviewer':request.reviewer,
                'template_id':request.template_id, 'design_url':state['design_url'], 'reviewed_at':stamp(),
                'content_checked':True, 'template_and_rights_checked':True, 'visual_checked':False,
                'review_type':'preauthorized_template_automation', 'notes':request.warning_resolution})
            self.store.save_receipt(session_id, {'brand_id':state['brand_id'], 'post_id':state['post_id'],
                'scheduled_at':request.scheduled_at.isoformat(), 'timezone':'Asia/Seoul'})
            state['status'] = 'scheduled'; checkpoint('complete')
        except Exception as error:
            state['status'] = 'needs_reconciliation' if state.get('external_actions_executed') else 'blocked'
            state['error'] = str(error) if isinstance(error, (ProviderError, ValueError)) else '외부 응답 형식 또는 처리 오류. 작업 ID와 Metricool 예약을 확인하세요.'
            self.save(session_id, state)
        finally:
            if provider is None and p is not None:
                p.close()
        return state


def auto_router(output_root, db_path):
    router = APIRouter()
    engine = AutoPublisher(output_root, db_path)

    def local_action(request):
        if request.headers.get('X-Requested-With') != 'sports-card-news':
            raise HTTPException(403, '로컬 운영 화면에서 실행하세요.')
        origin = request.headers.get('origin')
        if origin and urlparse(origin).netloc != request.headers.get('host'):
            raise HTTPException(403, '다른 사이트에서 시작한 실행 요청은 허용하지 않습니다.')

    @router.get('/api/auto/config')
    def config():
        return configuration_status()

    @router.get('/api/auto/sessions/{session_id}')
    def state(session_id: str):
        return engine.get(session_id)

    @router.post('/api/auto/sessions/{session_id}/check')
    def check(session_id: str, payload: AutoRequest, request: Request):
        local_action(request)
        missing = configuration_status()['missing']
        if missing:
            raise HTTPException(422, '로컬 .env 설정 필요: '+', '.join(missing))
        p = Providers()
        try:
            package, _, _ = engine.load(session_id)
            return p.preflight(payload.template_id, fields_for(package))
        except (ValueError, ProviderError, OSError) as error:
            raise HTTPException(422, str(error) if not isinstance(error, OSError) else '제작 세션 파일을 찾을 수 없습니다.') from None
        finally:
            p.close()

    @router.post('/api/auto/sessions/{session_id}/run', status_code=202)
    def run(session_id: str, payload: AutoRequest, request: Request, tasks: BackgroundTasks):
        local_action(request)
        try:
            state, created = engine.prepare(session_id, payload)
        except (ValueError, OSError) as error:
            raise HTTPException(422, str(error) if not isinstance(error, OSError) else '제작 세션 파일을 찾을 수 없습니다.') from None
        if created:
            tasks.add_task(engine.execute, session_id)
        return state

    return router
