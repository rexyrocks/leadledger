import copy
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from leadledger.adapters import message_hash
from leadledger.api import create_app
from leadledger.contracts import ROOT,Problem,validate
from leadledger.manager import Manager
from leadledger.repository import Change
from leadledger.seed import command,qualify,seed


def test_shared_examples_and_hash():
    for name,value in json.loads((ROOT/'examples.json').read_text()).items(): validate(name,value)
    vector=json.loads((ROOT/'message-hash-vector.json').read_text())
    assert message_hash(json.loads(vector['canonical_json']))==vector['sha256']


def test_happy_path_idempotency_and_why(approved):
    m=approved
    assert m.gate('lead-01')['allowed'] is True
    body=command(m,'lead-01')
    first=m.send('lead-01',body); assert first==m.send('lead-01',body)
    assert first['simulated'] and first['mode']=='log_only'
    d=m.detail('lead-01'); assert d['lead']['state']=='Sent' and len(d['outreach'])==1
    graph=m.explain(first['outreach_id']); assert graph['complete']
    assert {'gate_allowed','send_logged','outreach_approved','verification_completed'} <= {e['type'] for e in graph['events']}
    assert {'Company','Person','Verification','Campaign','Approval','Draft','Outreach','Evidence','Event'} <= {n['data']['type'] for n in graph['nodes']}
    assert len({n['data']['id'] for n in graph['nodes']})==len(graph['nodes'])


def test_completed_verification_replays_original_response(discovered):
    m=discovered; body=command(m,'lead-01'); original=m.verify('lead-01',body)
    m.draft('lead-01',command(m,'lead-01',subject=None,body_text=None))
    assert m.verify('lead-01',body)==original


def test_command_cannot_be_repurposed(discovered):
    m=discovered; body=command(m,'lead-01'); m.verify('lead-01',body)
    with pytest.raises(Problem) as exc:
        m.send('lead-01',body)
    assert exc.value.body['error']['code']=='COMMAND_REUSED'


def test_stale_scan_is_graph_driven_and_does_not_repeat(approved):
    m=approved; m.clock=lambda:1800000000+604801
    result=m.scan({'command_id':str(uuid4()),'campaign_id':'campaign-saas'})
    assert [x['id'] for x in result['updated']]==['lead-01']
    d=m.detail('lead-01'); assert d['lead']['state']=='Stale' and d['lead']['current_approval_id'] is None
    before=len(d['events'])
    assert m.scan({'command_id':str(uuid4()),'campaign_id':'campaign-saas'})['updated']==[]
    assert len(m.detail('lead-01')['events'])==before


def test_expiry_blocks_send_even_before_scan(approved):
    approved.clock=lambda:1800000000+604801
    assert 'VERIFICATION_INVALID' in approved.gate('lead-01')['reason_codes']


def test_optout_after_approval_and_block_receipt_replay(approved):
    m=approved; m.opt_out('lead-01',command(m,'lead-01',actor='kunal'))
    body=command(m,'lead-01'); errors=[]
    for _ in range(2):
        with pytest.raises(Problem) as exc: m.send('lead-01',body)
        errors.append(exc.value.body)
    assert errors[0]==errors[1]
    assert 'OPTED_OUT' in errors[0]['error']['details']['gate']['reason_codes']
    d=m.detail('lead-01'); assert d['outreach']==[]
    assert sum(e['type']=='send_blocked' for e in d['events'])==1


@pytest.mark.parametrize('state',['Discovered','Approved','Needs review','Rejected','Stale',
    'Awaiting outreach approval','Approved for sending','Sent','Delivery/Reply status','Opted out'])
def test_optout_is_terminal_at_each_stage(m,state):
    if state=='Rejected': m.candidates['seed-01']['person']['email']='invalid-address'
    if state=='Needs review':
        original=m.agents.check
        def review(ctx):
            assessment=original(ctx); assessment['recommendation']='needs_review'; return assessment
        m.agents.check=review
    m.ingest(m.candidates['seed-01'],str(uuid4()))
    if state not in {'Discovered','Opted out'}: m.verify('lead-01',command(m,'lead-01'))
    if state in {'Awaiting outreach approval','Approved for sending','Sent','Delivery/Reply status','Stale'}:
        m.draft('lead-01',command(m,'lead-01',subject=None,body_text=None))
    if state in {'Approved for sending','Sent','Delivery/Reply status','Stale'}:
        d=m.detail('lead-01')['draft']
        m.approve('lead-01',command(m,'lead-01',draft_id=d['id'],message_hash=d['message_hash'],actor='kunal'))
    if state in {'Sent','Delivery/Reply status'}:
        receipt=m.send('lead-01',command(m,'lead-01'))
        if state=='Delivery/Reply status':
            m.outcome(receipt['outreach_id'],command(m,'lead-01',actor='kunal',outcome='delivered'))
    if state=='Stale':
        m.clock=lambda:1800000000+604801
        m.scan({'command_id':str(uuid4()),'campaign_id':'campaign-saas'})
    if state=='Opted out': m.opt_out('lead-01',command(m,'lead-01',actor='kunal'))
    assert m.detail('lead-01')['lead']['state']==state
    m.opt_out('lead-01',command(m,'lead-01',actor='shubhangi'))
    assert m.detail('lead-01')['lead']['state']=='Opted out'
    assert 'OPTED_OUT' in m.gate('lead-01')['reason_codes']
    with pytest.raises(Problem): m.verify('lead-01',command(m,'lead-01'))


def test_duplicate_identity_and_global_optout(discovered):
    m=discovered; result=m.ingest(m.candidates['seed-07'],str(uuid4()))
    assert result['outcome']=='duplicate' and result['canonical_lead_id']=='lead-01'
    assert 'DUPLICATE' in m.gate('lead-07')['reason_codes']
    with pytest.raises(Problem): m.verify('lead-07',command(m,'lead-07'))
    m.opt_out('lead-07',command(m,'lead-07',actor='shubhangi'))
    assert m.detail('lead-01')['lead']['state']=='Opted out'
    assert len(m.repo.snapshot().all('Person'))==1


def test_message_edit_revokes_old_approval(approved):
    m=approved; old=m.detail('lead-01')['draft']
    result=m.draft('lead-01',command(m,'lead-01',subject='New subject',body_text='New body'))
    assert result['draft']['revision']==2 and result['draft']['message_hash']!=old['message_hash']
    assert result['lead']['current_approval_id'] is None
    assert result['approvals'][0]['revoked'] is True
    assert not m.gate('lead-01')['allowed']
    with pytest.raises(Problem):
        m.approve('lead-01',command(m,'lead-01',draft_id=old['id'],message_hash=old['message_hash'],actor='kunal'))


@pytest.mark.parametrize('tamper', ['policy','contact','hash','binding','verification'])
def test_gate_detects_graph_changes(approved,tamper):
    m=approved; d=m.detail('lead-01')
    if tamper=='policy':
        m.repo.graph.query('MATCH (c:Campaign {id:$id}) SET c.policy_version=$v',{'id':'campaign-saas','v':'policy-v2'})
    elif tamper=='contact':
        m.repo.graph.query('MATCH (p:Person {id:$id}) SET p.contact_version=2',{'id':d['person']['id']})
    elif tamper=='hash':
        m.repo.graph.query('MATCH (d:Draft {id:$id}) SET d.body_text=$text',{'id':d['draft']['id'],'text':'tampered'})
    elif tamper=='binding':
        m.repo.graph.query('MATCH (a:Approval {id:$id}) SET a.person_id=$p',{'id':d['approvals'][0]['id'],'p':'someone-else'})
    else:
        m.repo.graph.query('MATCH (v:Verification {id:$id}) SET v.status=$status',{'id':d['verifications'][0]['id'],'status':'rejected'})
    assert m.gate('lead-01')['allowed'] is False
    with pytest.raises(Problem): m.send('lead-01',command(m,'lead-01'))
    assert m.detail('lead-01')['outreach']==[]


def test_stale_client_version_cannot_approve(discovered):
    m=discovered; original=command(m,'lead-01'); m.verify('lead-01',original)
    with pytest.raises(Problem) as exc:
        m.draft('lead-01',{**original,'command_id':str(uuid4()),'subject':None,'body_text':None})
    assert exc.value.body['error']['code']=='VERSION_CONFLICT'


@pytest.mark.parametrize('index,status',[(10,'rejected'),(11,'rejected'),(12,'needs_review'),
                                        (13,'needs_review'),(14,'needs_review')])
def test_bad_or_uncertain_email_and_evidence(m,index,status):
    m.ingest(m.candidates[f'seed-{index:02}'],str(uuid4()))
    d=m.verify(f'lead-{index:02}',command(m,f'lead-{index:02}'))
    assert d['verifications'][-1]['status']==status
    assert d['verifications'][-1]['execution_mode']=='fixture_replay'


@pytest.mark.parametrize('corruption',['unknown_id','invented_quote','wrong_lead','malformed'])
def test_checker_cannot_invent_support(discovered,corruption):
    m=discovered; original=m.agents.check
    def corrupted(ctx):
        value=original(ctx)
        if corruption=='unknown_id': value['claims'][0]['evidence_ids']=['invented']
        elif corruption=='invented_quote': value['claims'][0]['quote']='Something never recorded'
        elif corruption=='wrong_lead': value['lead_id']='lead-elsewhere'
        else: value={'recommendation':'passed'}
        return value
    m.agents.check=corrupted
    result=m.verify('lead-01',command(m,'lead-01'))
    assert result['lead']['state']=='Needs review'
    assert not m.gate('lead-01')['allowed']


def test_simultaneous_repeated_send_is_one_outreach(approved):
    m=approved; body=command(m,'lead-01')
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:m.send('lead-01',body),range(2)))
    assert results[0]==results[1] and len(m.detail('lead-01')['outreach'])==1


def test_optout_while_checker_runs_cannot_commit(discovered):
    m=discovered; started=threading.Event(); proceed=threading.Event(); old=m.agents.check
    def slow(ctx):
        started.set(); assert proceed.wait(5); return old(ctx)
    m.agents.check=slow
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(m.verify,'lead-01',command(m,'lead-01'))
        assert started.wait(5)
        m.opt_out('lead-01',command(m,'lead-01',actor='kunal')); proceed.set()
        with pytest.raises(Problem): future.result()
    assert m.detail('lead-01')['lead']['state']=='Opted out'
    assert m.detail('lead-01')['verifications']==[]


def test_restart_recovery_and_persisted_idempotency(approved):
    m=approved; body=command(m,'lead-01'); result=m.send('lead-01',body)
    replacement=Manager(m.repo,clock=m.clock)
    assert replacement.send('lead-01',body)==result
    assert replacement.explain(result['outreach_id'])['complete']


def test_interrupted_check_goes_to_review(discovered):
    m=discovered; s=m.repo.snapshot(); u=Change(s); l=s.get('lead-01')
    m._guard(u,'lead-01',l['version'])
    m._event(u,'lead-01','verification_started',str(uuid4()),target='Verification pending')
    m.repo.commit(u); m.recover()
    assert m.detail('lead-01')['lead']['state']=='Needs review'
    m.recover()
    assert sum(e['type']=='verification_interrupted' for e in m.detail('lead-01')['events'])==1


def test_history_survives_later_optout_and_reply(approved):
    m=approved; receipt=m.send('lead-01',command(m,'lead-01'))
    v=m.detail('lead-01')['verifications'][0]
    m.opt_out('lead-01',command(m,'lead-01',actor='kunal'))
    m.outcome(receipt['outreach_id'],command(m,'lead-01',actor='shubhangi',outcome='replied'))
    assert m.detail('lead-01')['lead']['state']=='Opted out'
    assert m.detail('lead-01')['verifications'][0]==v
    assert m.explain(receipt['outreach_id'])['complete']


def test_incomplete_audit_not_fabricated(approved):
    m=approved; receipt=m.send('lead-01',command(m,'lead-01'))
    m.repo.graph.query('MATCH (a:Approval)-[r:BASED_ON]->(v:Verification) DELETE r')
    graph=m.explain(receipt['outreach_id'])
    assert not graph['complete'] and 'Incomplete audit chain' in graph['summary']


def test_missing_approval_returns_incomplete_graph(approved):
    m=approved; receipt=m.send('lead-01',command(m,'lead-01'))
    approval_id=m.detail('lead-01')['approvals'][0]['id']
    m.repo.graph.query('MATCH (a:Approval {id:$id}) DELETE a',{'id':approval_id})
    assert m.explain(receipt['outreach_id'])['complete'] is False


def test_bad_sender_result_cannot_create_outreach(approved):
    m=approved; m.sender=lambda _: {'status':'logged'}
    with pytest.raises(Problem) as exc: m.send('lead-01',command(m,'lead-01'))
    assert exc.value.status==503 and m.detail('lead-01')['outreach']==[]


def test_api_entire_approved_send(discovered):
    m=discovered
    with TestClient(create_app(m)) as client:
        for action,extra in [('verify',{}),('draft',{'subject':None,'body_text':None})]:
            response=client.post(f'/api/leads/lead-01/{action}',json=command(m,'lead-01',**extra))
            assert response.status_code==200; validate('LeadDetail',response.json())
        draft=response.json()['draft']
        response=client.post('/api/leads/lead-01/approve',json=command(m,'lead-01',
                             draft_id=draft['id'],message_hash=draft['message_hash'],actor='shubhangi'))
        assert response.status_code==200
        body=command(m,'lead-01')
        response=client.post('/api/leads/lead-01/send',json=body)
        assert response.status_code==200; validate('SendReceipt',response.json())
        assert client.post('/api/leads/lead-01/send',json=body).json()==response.json()
        graph=client.get('/api/outreach/'+response.json()['outreach_id']+'/why')
        assert graph.status_code==200 and graph.json()['complete']


def test_graph_failure_never_calls_sender(approved,monkeypatch):
    m=approved; called=[]; body=command(m,'lead-01')
    m.sender=lambda envelope:called.append(envelope)
    def unavailable(*args,**kwargs): raise Problem('DEPENDENCY_UNAVAILABLE','offline',503)
    monkeypatch.setattr(m.repo,'read',unavailable)
    with pytest.raises(Problem) as exc: m.send('lead-01',body)
    assert exc.value.status==503 and called==[]


def test_extraction_and_replay(m):
    body={'command_id':str(uuid4()),'campaign_id':'campaign-saas','source_ids':['source-01']}
    result=m.extract(body)
    assert result==m.extract(body) and result['items'][0]['lead_id']=='lead-01'
    assert m.leads()['total']==1


def test_api_matches_contract_and_rejects_invalid_requests(discovered):
    with TestClient(create_app(discovered)) as client:
        assert client.get('/api/health').json()['graph']=='connected'
        response=client.get('/api/leads'); assert response.status_code==200
        validate('LeadList',response.json())
        invalid=client.post('/api/leads/lead-01/verify',json={'command_id':str(uuid4()),'expected_version':True})
        assert invalid.status_code==422; validate('ErrorResponse',invalid.json())
        invalid=client.post('/api/leads/lead-01/send',json={**command(discovered,'lead-01'),'approved':True})
        assert invalid.status_code==422
        blocked=client.post('/api/leads/lead-01/send',json=command(discovered,'lead-01'))
        assert blocked.status_code==409 and blocked.json()['error']['code']=='SEND_BLOCKED'
        assert client.get('/openapi.json').json()==json.loads((ROOT/'openapi.json').read_text())


def test_full_seed_and_cross_campaign_contact(m):
    result=seed(m)
    assert result['active_leads']==20 and result['canonical_people']==18
    assert 'ALREADY_CONTACTED' in m.gate('lead-05')['reason_codes']
    assert m.detail('lead-05')['outreach']==[]
    assert m.explain(result['historical_outreach'])['complete']
    stale=m.scan({'command_id':str(uuid4()),'campaign_id':'campaign-saas'})
    assert {l['id'] for l in stale['updated']}=={'lead-02','lead-16'}
    with pytest.raises(Problem): seed(m)
