import json,os,sys
from datetime import datetime,timezone
from pathlib import Path
from urllib.request import Request
import pytest
from sponsor_hub.core import IntegrationError, clean_model, public_status, safe_post_json, snowflake_host
from sponsor_hub.llm import gemini_complete, snowflake_complete,evidence_reply
from sponsor_hub.prizes import vultr_instances,report_sha256,verify_report,verify_domain_dns,solana_devnet_transaction
from sponsor_hub.storage import AtlasEvidence,TigerData,TIGER_SCHEMA
from sponsor_hub.gateway import _throttle, _authenticated, handle_get_sponsor, handle_post_sponsor, _REQUESTS
from bridge_install import patch

@pytest.fixture(autouse=True)
def clear_secrets(monkeypatch):
    for name in ('GEMINI_API_KEY','GOOGLE_API_KEY','SNOWFLAKE_ACCOUNT','SNOWFLAKE_PAT','TIGER_DATABASE_URL','MONGODB_ATLAS_URI','VULTR_API_KEY','SPONSOR_API_TOKEN'):
        monkeypatch.delenv(name,raising=False)

def test_unconfigured_status_does_not_claim_connected():
    data=public_status()
    assert all(not x.checked_live for x in data.values())
    assert not data['gemini'].configured

def test_status_has_no_tokens(monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY','super-secret')
    assert 'super-secret' not in repr(public_status())
    assert public_status()['gemini'].configured

def test_snowflake_account_validation(monkeypatch):
    monkeypatch.setenv('SNOWFLAKE_ACCOUNT','hello.example')
    assert snowflake_host()=='https://hello.example.snowflakecomputing.com'
    for v in ('https://bad.com','user@host','evil/../../','..bad.com','good.com?token=foo'):
        monkeypatch.setenv('SNOWFLAKE_ACCOUNT',v)
        with pytest.raises(IntegrationError):snowflake_host()

def test_model_validation():
    assert clean_model('gemini-2.5-flash')=='gemini-2.5-flash'
    with pytest.raises(IntegrationError):clean_model('../../etc/passwd?')

def test_no_http_provider_calls():
    with pytest.raises(IntegrationError):safe_post_json('http://example.com',{}, {},transport=lambda req,t:{} )

def test_gemini_response(monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY','mock-only-key')
    def fake(req,timeout):
        assert req.get_header('X-goog-api-key')=='mock-only-key'
        assert 'mock-only-key' not in req.full_url
        assert req.full_url.endswith('generateContent')
        return {'candidates':[{'content':{'parts':[{'text':'PONG'}]}}]}
    assert gemini_complete('ping',transport=fake)=='PONG'

def test_gemini_absent_key():
    with pytest.raises(IntegrationError,match='not configured'):gemini_complete('ping')

def test_snowflake_response(monkeypatch):
    monkeypatch.setenv('SNOWFLAKE_ACCOUNT','abc123.us-east-1')
    monkeypatch.setenv('SNOWFLAKE_PAT','mock-only-pat')
    def fake(req,timeout):
        assert req.full_url.endswith('/api/v2/cortex/v1/chat/completions')
        assert req.get_header('Authorization')=='Bearer mock-only-pat'
        return {'choices':[{'message':{'content':'CORTEX_OK'}}]}
    assert snowflake_complete('ping',transport=fake)=='CORTEX_OK'

def test_evidence_reply_authoritative_and_cited(monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY','mock')
    facts={'ok':True,'answer':'The confirmed cost is $1,200', 'metrics':{'cost':1200},
       'sources':['ace-recommendation-1'], 'period':'Jan–Jun', 'limitations':['estimate']}
    def fake(req,timeout):
        prompt=json.loads(req.data)['contents'][0]['parts'][0]['text']
        assert 'ace-recommendation-1' in prompt
        return {'candidates':[{'content':{'parts':[{'text':json.dumps({'narrative':'The inspection is priced at $1,200.', 'citations':['ace-recommendation-1']})}]}}]}
    response=evidence_reply('What is the cost?',facts,'gemini',transport=fake)
    assert response['answer']==facts['answer'] and response['metrics']==facts['metrics']

def test_evidence_rejects_fake_citations(monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY','mock')
    facts={'ok':True,'answer':'Correct answer','sources':['valid-id']}
    def fake(req,timeout):
        return {'candidates':[{'content':{'parts':[{'text':json.dumps({'narrative':'Fabricated claim','citations':['forged-id']})}]}}]}
    with pytest.raises(IntegrationError,match='evidence validation'):
        evidence_reply('question?',facts,transport=fake)

def test_evidence_rejects_invented_amount(monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY','mock')
    facts={'ok':True,'answer':'Inspection $1,200','metrics':{'cost':1200},'sources':['ace-1']}
    def fake(req,timeout):
        reply={'narrative':'Inspection will definitely return $999,999.','citations':['ace-1']}
        return {'candidates':[{'content':{'parts':[{'text':json.dumps(reply)}]}}]}
    with pytest.raises(IntegrationError,match='numeric claim'):
        evidence_reply('question?',facts,transport=fake)

def test_evidence_rejects_missing_verified_answer():
    with pytest.raises(IntegrationError):evidence_reply('hey',{'ok':False,'sources':['x']})

def test_provider_unknown():
    with pytest.raises(IntegrationError,match='Unsupported'):
        evidence_reply('hey',{'ok':True,'answer':'Yes','sources':['x']},'unknown')

def test_tiger_requires_explicit_write():
    tiger=TigerData(conn_factory=lambda:None)
    with pytest.raises(IntegrationError):tiger.initialize()
    with pytest.raises(IntegrationError):tiger.upsert([])
    assert 'create_hypertable' in TIGER_SCHEMA

def test_tiger_rejects_bad_rows_before_connection():
    tiger=TigerData(conn_factory=lambda:pytest.fail('unexpected DB connection'))
    with pytest.raises(IntegrationError):tiger.upsert([{'observed_at':datetime.now(),'machine_id':'M1','coin_in_cents':5,'house_win_cents':1,'downtime_minutes':0}],confirm_write=True)

def test_tiger_queries_parameterized():
    class Cursor:
        def __init__(self):self.params=None
        def execute(self,query,params):
            assert '%s' in query and 'GROUP BY 1' in query
            self.params=params
        def fetchall(self):return [(datetime(2026,11,7,tzinfo=timezone.utc),4500,120,15)]
        def __enter__(self):return self
        def __exit__(self,*args):pass
    cur=Cursor()
    class Conn:
        def cursor(self):return cur
        def __enter__(self):return self
        def __exit__(self,*args):pass
    obj=TigerData(conn_factory=Conn)
    result=obj.daily(datetime(2026,11,1,tzinfo=timezone.utc),datetime(2026,12,1,tzinfo=timezone.utc))
    assert result[0]['coin_in_cents']==4500 and len(cur.params)==2

def test_atlas_evidence_requires_provenance():
    class Coll:
        def insert_one(self,doc):return type('R',(),{'inserted_id':'fake-id'})()
    class DB:
        def __getitem__(self,x):return Coll()
    class Client:
        def __getitem__(self,x):return DB()
    atlas=AtlasEvidence(client=Client())
    with pytest.raises(IntegrationError):atlas.save({'answer':'x','sources':['id']})
    with pytest.raises(IntegrationError):atlas.save({'answer':'x','sources':[]},confirm_write=True)
    assert atlas.save({'answer':'verified','sources':['source']},confirm_write=True)=='fake-id'

def test_vultr_read_only_and_sanitized(monkeypatch):
    monkeypatch.setenv('VULTR_API_KEY','fake-key')
    def fetch(req):
        assert req.get_method()=='GET'
        assert req.get_header('Authorization')=='Bearer fake-key'
        return {'instances':[{'id':'id1','region':'ewr','status':'active','main_ip':'hidden'}]}
    assert vultr_instances(fetch=fetch)==[{'id':'id1','region':'ewr','status':'active'}]

def test_vultr_requires_key():
    with pytest.raises(IntegrationError):vultr_instances(fetch=lambda req:{'instances':[]})

def test_report_digest():
    digest=report_sha256(b'hello')
    assert len(digest)==64 and verify_report(b'hello',digest) and not verify_report(b'world',digest)

def test_solana_does_not_falsely_verify_digest():
    signature='2'*88
    fake=lambda req,timeout:{'result':{'meta':{'err':None},'slot':42}}
    result=solana_devnet_transaction(signature,transport=fake)
    assert result['found'] and not result['digest_verified']

def test_solana_bad_signature():
    with pytest.raises(IntegrationError):solana_devnet_transaction('not a signature')

def test_domain_dns_does_not_claim_registration():
    fake=lambda hostname,port,type:[(0,0,0,'',('203.0.113.4',443))]
    result=verify_domain_dns('demo.example.com',resolver=fake)
    assert result['resolves'] and result['registered_by_user'] is None and not result['https_verified']

def test_rate_limit():
    _REQUESTS.clear()
    assert _throttle('unit',now=0,limit=2)
    assert _throttle('unit',now=1,limit=2)
    assert not _throttle('unit',now=2,limit=2)
    assert _throttle('unit',now=61,limit=2)

def test_api_requires_secret(monkeypatch):
    class Handler:
        headers={'X-Sponsor-Token':'short'}
    assert not _authenticated(Handler())
    monkeypatch.setenv('SPONSOR_API_TOKEN','a'*30)
    assert not _authenticated(Handler())
    Handler.headers={'X-Sponsor-Token':'a'*30}
    assert _authenticated(Handler())

def test_bridge_idempotent():
    source='''from domains.routes.router import route\nclass Handler:\n    def do_GET(self):\n        parsed = urlparse(self.path)\n    def do_POST(self) -> None:\n        pass\n'''
    result=patch(source)
    assert 'handle_get_sponsor(self, parsed.path)' in result
    assert patch(result)==result

def test_bridge_fails_unknown_layout():
    with pytest.raises(RuntimeError):patch('print("different server")')

def test_bridge_gates_existing_paid_gemini():
    source='''from pathlib import Path
from domains.routes.router import route
class Handler:
    def do_GET(self):
        parsed = urlparse(self.path)
    def _investigate(self):
        if result["ok"] and isinstance(question, str):
            do_paid_call()
    def do_POST(self) -> None:
        pass
def main():
    ThreadingHTTPServer(("127.0.0.1", 8765), Handler).serve_forever()
'''
    patched=patch(source)
    assert 'and _authenticated(self)' in patched
    assert 'os.getenv("PITBOSS_HOST", "127.0.0.1")' in patched
    import ast
    ast.parse(patched)

def test_get_sponsor_status_never_claims_live():
    class Fake:
        def _send(self,code,raw,mime):self.code=code;self.payload=json.loads(raw)
    handler=Fake()
    assert handle_get_sponsor(handler,'/api/sponsors/status')
    assert handler.code==200
    assert not handler.payload['providers']['snowflake']['checked_live']

def test_get_timeseries_denies_unauthorized():
    class Fake:
        headers={}
        def _send(self,code,raw,mime):self.code=code
    h=Fake()
    assert handle_get_sponsor(h,'/api/sponsors/timeseries')
    assert h.code==401

def test_post_sponsor_denies_unauthorized():
    class Fake:
        path='/api/sponsors/ask'
        headers={}
        def _send(self,code,raw,mime):self.code=code;self.payload=json.loads(raw)
    h=Fake()
    assert handle_post_sponsor(h)
    assert h.code==401 and not h.payload['ok']

def test_bridge_does_not_touch_databricks():
    original='''from domains.routes.router import route
# No touching Databricks endpoints!
class H:
    def do_GET(self):
        parsed = urlparse(self.path)
    def do_POST(self) -> None:
        pass
'''
    patched=patch(original)
    assert '# No touching Databricks endpoints!' in patched
