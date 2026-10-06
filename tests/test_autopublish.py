from datetime import datetime, timedelta, timezone
import json
import pytest
import httpx
from fastapi.testclient import TestClient
from sports_card_news.autopublish import AutoPublisher, AutoRequest, Providers, ProviderError, REQUIRED_ENV
from sports_card_news.webapp import create_app
from test_webapp import make_project
from test_work_hub import payload

class FakeProviders:
    def __init__(self, fail=False): self.calls=[]; self.fail=fail; self.body=None
    def preflight(self, template, fields): return {'ready':True}
    def call(self, service, method, path, **kwargs):
        self.calls.append((service,method,path,kwargs))
        if path=='/autofills': return {'job':{'id':'job1'}}
        if path=='/designs/D1': return {'design':{'page_count':7}}
        if path=='/exports': return {'job':{'id':str(kwargs['json']['format']['pages'][0])}}
        if path=='/v2/scheduler/posts':
            self.body=kwargs['json']
            if self.fail: raise ProviderError('응답 불명확')
            return {'data':{'id':123}}
        if path.endswith('/123'): return {'data':{**self.body,'id':123,'providers':[{'network':'instagram','status':'PENDING'}]}}
        raise AssertionError(path)
    def poll(self, kind, job):
        if kind=='autofills': return {'result':{'design':{'id':'D1','urls':{'edit_url':'https://www.canva.com/design/D1/edit'}}}}
        return {'urls':['https://export.canva.com/'+job+'.png']}
    def normalize_media(self,url): return url.replace('export.canva.com','static.metricool.com')

@pytest.fixture
def setup(tmp_path,monkeypatch):
    for key in REQUIRED_ENV: monkeypatch.setenv(key,'test-secret' if 'TOKEN' in key else '12345')
    monkeypatch.setattr('sports_card_news.work_hub.render_studio_package', lambda *a:None)
    app=create_app(make_project(tmp_path))
    with TestClient(app) as client:
        session=client.post('/api/work/import',json=payload(7)).json()['session_id']
    req=AutoRequest(template_id='BTM_TEST',scheduled_at=datetime.now(timezone.utc)+timedelta(hours=2),
        content_checked=True,template_and_rights_checked=True,authorize_schedule=True,reviewer='편집자',warning_resolution='원문 확인 완료')
    return app,AutoPublisher(tmp_path/'output',tmp_path/'data/work_operations.sqlite3'),session,req

def test_order_and_idempotence(setup):
    _,engine,session,req=setup
    assert engine.prepare(session,req)[1]
    provider=FakeProviders()
    result=engine.execute(session,provider)
    assert result['status']=='scheduled',result
    assert len(provider.body['media'])==7
    assert provider.body['publicationDate']['timezone']=='Asia/Seoul'
    assert provider.body['draft'] is False
    assert engine.store.get(session)['receipt']['post_id']=='123'
    assert engine.prepare(session,req)[1] is False
    engine.execute(session,provider)
    assert sum(p=='/v2/scheduler/posts' for _,_,p,_ in provider.calls)==1

def test_ambiguous_schedule_never_reposts(setup):
    _,engine,session,req=setup
    engine.prepare(session,req)
    provider=FakeProviders(fail=True)
    assert engine.execute(session,provider)['status']=='needs_reconciliation'
    engine.execute(session,provider)
    assert sum(p=='/v2/scheduler/posts' for _,_,p,_ in provider.calls)==1
    assert engine.store.get(session)['receipt'] is None

def test_source_change_blocks_mutation(setup):
    _,engine,session,req=setup
    engine.prepare(session,req)
    path=engine.output_root/'studio'/session/'source.md'
    path.write_text(path.read_text()+'changed')
    p=FakeProviders()
    assert engine.execute(session,p)['status']=='blocked'
    assert not p.calls

def test_route_security_and_missing_config(setup,monkeypatch):
    app,_,session,req=setup
    monkeypatch.delenv('CANVA_ACCESS_TOKEN')
    with TestClient(app) as client:
        url=f'/api/auto/sessions/{session}/run'
        data=req.model_dump(mode='json')
        assert client.post(url,json=data).status_code==403
        assert client.post(url,json=data,headers={'X-Requested-With':'sports-card-news','Origin':'https://elsewhere.example'}).status_code==403
        assert client.post(url,json=data,headers={'X-Requested-With':'sports-card-news'}).status_code==422
        assert 'test-secret' not in client.get('/api/auto/config').text

def test_provider_errors_do_not_echo_secrets(monkeypatch):
    for key in REQUIRED_ENV: monkeypatch.setenv(key,'sensitive-token')
    client=httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(401,json={'error':'sensitive-token'})))
    p=Providers(client)
    with pytest.raises(ProviderError) as e:p.call('canva','POST','/autofills')
    assert 'sensitive-token' not in str(e.value)

def test_rejects_expiring_media(monkeypatch):
    p=Providers(httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={}))))
    monkeypatch.setattr(p,'call',lambda *a,**k:'https://export.canva.com/image.png?token=temporary')
    with pytest.raises(ProviderError):p.normalize_media('https://export.canva.com/image.png')
