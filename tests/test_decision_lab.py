import copy
from types import SimpleNamespace
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from leadledger.api import create_app
from leadledger.contracts import Problem
from leadledger.qwen import QwenClient
from leadledger.seed import command,seed


def test_counterfactuals_share_gate_and_never_write(approved):
    m=approved; before=copy.deepcopy(m.repo.snapshot())
    lab=m.decision_lab('lead-01')
    assert lab['read_only'] is True
    assert lab['baseline']==m.gate('lead-01') and lab['baseline']['allowed']
    expected={'opt_out':'OPTED_OUT','suppressed':'SUPPRESSED','expired':'VERIFICATION_INVALID','message':'MESSAGE_CHANGED'}
    for case in lab['scenarios']:
        assert case['available'] and case['hypothetical']
        assert not case['decision']['allowed']
        assert expected[case['id']] in case['added_reason_codes']
    assert m.repo.snapshot()==before
    assert m.gate('lead-01')['allowed']
    assert lab['query']['access']=='GRAPH.RO_QUERY' and lab['query']['row_count']==1
    assert lab['query']['parameters']=={'lead_id':'lead-01'}
    assert {c['code'] for c in lab['checks'] if not c['passed']}==set()


def test_missing_artifacts_cannot_be_manufactured_by_preview(discovered):
    lab=discovered.decision_lab('lead-01')
    assert not lab['baseline']['allowed']
    unavailable={c['id'] for c in lab['scenarios'] if not c['available']}
    assert unavailable=={'expired','message'}
    assert discovered.detail('lead-01')['draft'] is None
    with pytest.raises(Problem): discovered.decision_lab('missing')


def test_cross_campaign_prior_contact_visible_in_lab(m):
    seed(m)
    lab=m.decision_lab('lead-05')
    assert 'ALREADY_CONTACTED' in lab['baseline']['reason_codes']
    assert lab['facts']['prior'] and lab['facts']['prior']==lab['baseline']['prior_outreach_ids']
    assert not next(c for c in lab['checks'] if c['code']=='ALREADY_CONTACTED')['passed']


def test_preview_does_not_authorize_send_after_real_optout(approved):
    m=approved; assert m.decision_lab('lead-01')['baseline']['allowed']
    m.opt_out('lead-01',command(m,'lead-01',actor='kunal'))
    with pytest.raises(Problem) as exc: m.send('lead-01',command(m,'lead-01'))
    assert 'OPTED_OUT' in exc.value.body['error']['details']['gate']['reason_codes']
    assert m.detail('lead-01')['outreach']==[]


def test_ui_extensions_do_not_change_shared_contracts(m):
    with TestClient(create_app(m)) as client:
        frozen=client.get('/openapi.json').json()
        assert client.get('/ui-api/openapi.json').json()['servers']==[{'url':'/'}]
        assert client.get('/openapi.json').json()==frozen
        assert '/ui-api/openapi.json' in client.get('/docs').text
        assert client.get('/ui-api/runtime').json()['status']=='fixture'
        assert client.get('/ui-api/leads/missing/decision').status_code==404


def test_runtime_probe_cached_and_no_inference(m):
    calls=[]
    client_stub=SimpleNamespace(probe=lambda:(calls.append(1) or {'ready':False,'status':'offline'}))
    m.agents=SimpleNamespace(client=client_stub,execution_mode='live_llm',model_id='test')
    with TestClient(create_app(m)) as client:
        for _ in range(2):
            result=client.get('/ui-api/runtime').json()
            assert result['status']=='offline' and result['ready'] is False
    assert calls==[1]


@pytest.mark.parametrize('response,ready', [({'ready':True},True),({'ready':False},False),({'ready':'yes'},False)])
def test_probe_does_not_enqueue_or_treat_truthy_value_as_online(response,ready):
    client=QwenClient('https://relay.example',key='test-secret',transport='relay');calls=[]
    def request(path,**kwargs):calls.append((path,kwargs));return response
    client._request=request
    assert client.probe()['ready'] is ready
    assert calls==[('/health',{'timeout':3})]


def test_probe_dependency_error_is_not_exposed():
    client=QwenClient('https://relay.example',transport='relay')
    def request(*a,**kw):raise Problem('DEPENDENCY_UNAVAILABLE','private upstream error')
    client._request=request
    assert client.probe()=={'ready':False,'status':'unreachable'}
