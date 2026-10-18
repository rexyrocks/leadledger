import copy
import json
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from types import SimpleNamespace
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from leadledger.api import create_app
from leadledger.contracts import Problem,validate
from leadledger.fixtures import CAMPAIGN,registry
from leadledger.qwen import QwenAgents,QwenClient,parse_object,FIELDS
from leadledger.email_checks import EmailChecker
from leadledger.seed import command


class Replies:
    model_id='test-qwen-stub'
    def __init__(self,*replies): self.replies=list(replies); self.calls=0
    def complete(self,*args):
        self.calls+=1
        return copy.deepcopy(self.replies.pop(0))


def extraction_context(index=1):
    sources,_,_=registry(1800000000)
    return {'campaign_id':CAMPAIGN['id'],'campaign':CAMPAIGN,'sources':[sources[f'source-{index:02}']]}


def test_extractor_creates_only_grounded_candidates():
    values={'company':'Acme Demo','industry':'B2B SaaS','name':'Asha Rao','role':'Head of Partnerships','email':'asha@acme.test'}
    agent=QwenAgents(Replies(values))
    batch=agent.extract(extraction_context())
    validate('ExtractionBatch',batch)
    assert batch['execution_mode']=='live_llm'
    candidate=batch['candidates'][0]
    assert candidate['person']['email']=='asha@acme.test'
    assert candidate['company']['domain']=='acme.test'
    assert len(candidate['evidence'])==5
    assert all(e['quote'] in extraction_context()['sources'][0]['snapshot_text'] for e in candidate['evidence'])
    values['email']='invented@acme.test'
    with pytest.raises(Problem): QwenAgents(Replies(values)).extract(extraction_context())


def test_extractor_skips_missing_email_and_ignores_authority_fields():
    values={'company':'Canvas Demo','industry':'B2B SaaS','name':'Rehan Khan','role':'Head of Partnerships','email':None}
    assert QwenAgents(Replies(values)).extract(extraction_context(14))['candidates']==[]
    values['approve']=True
    with pytest.raises(Problem): QwenAgents(Replies(values)).extract(extraction_context(14))


def test_checker_grounds_citations_and_cannot_grant_approval(discovered):
    m=discovered
    agent=QwenAgents(Replies({'supported':list(FIELDS),'missing_fields':[],'conflicts':[],'summary':'All fields appear in the source.'}))
    m.agents=agent
    result=m.verify('lead-01',command(m,'lead-01'))
    report=next(v for v in result['verifications'] if v['id']==result['lead']['current_verification_id'])
    assert report['execution_mode']=='live_llm' and report['status']=='passed'
    assert result['lead']['state']=='Approved' and result['approvals']==[]
    assert m.gate('lead-01')['allowed'] is False
    assert report['email_checks']['mx']=='fixture'


def test_checker_false_email_claim_fails_closed(m):
    m.ingest(m.candidates['seed-14'],str(uuid4()))
    m.agents=QwenAgents(Replies({'supported':list(FIELDS),'missing_fields':[],'conflicts':[],'summary':'Trust me.'}))
    result=m.verify('lead-14',command(m,'lead-14'))
    assert result['lead']['state']=='Needs review'
    assert result['verifications'][-1]['reason_codes']==['CHECKER_UNAVAILABLE_OR_INVALID']
    assert not m.gate('lead-14')['allowed']


def test_conflicting_role_requires_review(m):
    m.ingest(m.candidates['seed-13'],str(uuid4()))
    m.agents=QwenAgents(Replies({'supported':list(FIELDS),'missing_fields':[],'conflicts':['Finance Intern conflicts with Head of Partnerships.'],'summary':'Conflicting roles.'}))
    result=m.verify('lead-13',command(m,'lead-13'))
    assert result['lead']['state']=='Needs review'
    assert not m.gate('lead-13')['allowed']


def test_qwen_draft_requires_human_and_replays_same_revision(discovered):
    m=discovered; m.verify('lead-01',command(m,'lead-01'))
    client=Replies({'subject':'A partnership conversation','body_text':'Hi Asha, would you be open to a SaaS partnership conversation?\nKunal'})
    m.drafter=QwenAgents(client).draft
    body=command(m,'lead-01',subject=None,body_text=None)
    result=m.draft('lead-01',body)
    assert result==m.draft('lead-01',body) and client.calls==1
    assert result['lead']['state']=='Awaiting outreach approval'
    assert result['approvals']==[] and not m.gate('lead-01')['allowed']
    assert result['events'][-1]['payload']['generator']=='qwen'


def test_model_drafting_does_not_lock_out_optout(discovered):
    m=discovered; m.verify('lead-01',command(m,'lead-01'))
    started=threading.Event(); proceed=threading.Event(); failures=[]
    def drafter(detail):
        started.set(); assert proceed.wait(5)
        return {'subject':'Hello','body_text':'A draft.'}
    m.drafter=drafter; body=command(m,'lead-01',subject=None,body_text=None)
    def run():
        try: m.draft('lead-01',body)
        except Problem as e: failures.append(e.body['error']['code'])
    thread=threading.Thread(target=run); thread.start(); assert started.wait(5)
    try:
        m.opt_out('lead-01',command(m,'lead-01',actor='kunal'))
    finally:
        proceed.set(); thread.join(5)
    assert failures==['VERSION_CONFLICT']
    assert m.detail('lead-01')['draft'] is None


def test_synthetic_email_never_runs_dns(discovered):
    class ForbiddenResolver:
        def resolve(self,*a,**k): raise AssertionError('Fixture performed a real lookup')
    context=discovered.check_context('lead-01')
    result=EmailChecker({'lead-01':'present'},ForbiddenResolver())(context['person'],context['evidence'],1800000000,'lead-01')
    assert result['is_fixture'] and result['mx']=='fixture' and result['mailbox_exists']=='unknown'


@pytest.mark.parametrize('mode,expected',[('present','present'),('null','null_mx'),('absent','absent'),('nxdomain','nxdomain'),('timeout','timeout')])
def test_real_mx_is_conservative(mode,expected):
    import dns.resolver,dns.exception
    class Resolver:
        def resolve(self,domain,kind,lifetime):
            assert domain=='example.com' and kind=='MX' and lifetime==3
            if mode=='absent': raise dns.resolver.NoAnswer
            if mode=='nxdomain': raise dns.resolver.NXDOMAIN
            if mode=='timeout': raise dns.exception.Timeout
            return [SimpleNamespace(exchange='.' if mode=='null' else 'mail.example.com.')]
    result=EmailChecker(resolver=Resolver())({'email_normalized':'person@example.com'},[{'is_fixture':False}],1800000000,'lead-live')
    assert result['mx']==expected and result['mailbox_exists']=='unknown' and result['fixture_result'] is None


def test_invalid_email_does_not_query_dns():
    class Resolver:
        def resolve(self,*a,**k): raise AssertionError('Invalid address queried DNS')
    result=EmailChecker(resolver=Resolver())({'email_normalized':'not-email'},[{'is_fixture':False}],1,'lead-live')
    assert result['syntax']=='fail'


@pytest.mark.parametrize('text',['prose {"a":1}','[1]','{"a":1} trailing','<think>x</think>{"a":1}'])
def test_no_executing_or_salvaging_model_prose(text):
    with pytest.raises((ValueError,TypeError)): parse_object(text)


def test_ui_and_contracts_served_without_network_dependencies(m):
    with TestClient(create_app(m)) as client:
        response=client.get('/')
        assert response.status_code==200 and 'Good leads. Clear reasons.' in response.text
        assert client.get('/ui/app.js').status_code==200
        assert client.get('/ui/vendor/cytoscape.min.js').status_code==200
        assert client.get('/openapi.json').json()==json.load(open('openapi.json'))
        assert client.get('/api/health').json()['execution_mode']=='fixture_replay'


def test_direct_client_uses_json_only_and_thinking_off():
    captured=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_POST(self):
            captured.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            self.send_response(200); self.send_header('Content-Type','application/json'); self.end_headers()
            self.wfile.write(json.dumps({'choices':[{'message':{'content':'{"ok":true}'}}]}).encode())
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    try:
        client=QwenClient(f'http://127.0.0.1:{server.server_port}/v1',transport='openai')
        assert client.complete('Return JSON',{'text':'untrusted'})=={'ok':True}
        assert captured[0]['chat_template_kwargs']=={'enable_thinking':False}
        assert captured[0]['stream'] is False
        with pytest.raises(Problem): client.complete('a'*12000,{})
    finally: server.shutdown(); server.server_close(); thread.join()


def test_relay_offline_does_not_fallback_or_enqueue():
    client=QwenClient('https://relay.example',transport='relay'); calls=[]
    def request(path,*args,**kwargs):
        calls.append(path); return {'ready':False}
    client._request=request
    with pytest.raises(Problem): client.complete('Extract',{})
    assert calls==['/health']


def test_draft_rejects_unfinished_placeholders(discovered):
    agent=QwenAgents(Replies({'subject':'Hello from [Your Company]','body_text':'Hi Asha.'}))
    with pytest.raises(Problem): agent.draft(discovered.detail('lead-01'))
