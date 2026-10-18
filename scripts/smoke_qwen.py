"""Opt-in real Qwen probe against the local synthetic workspace; no approval/send calls."""
import argparse,json,time,urllib.request
from pathlib import Path
from uuid import uuid4


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:8123')
    args=parser.parse_args()
    if args.url not in {'http://127.0.0.1:8123','http://localhost:8123'}:
        parser.error('This smoke probe is restricted to the local demo workspace on port 8123.')
    def call(path,body=None):
        req=urllib.request.Request(args.url+path,data=json.dumps(body).encode() if body else None,
                                   headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=180) as r: return json.load(r)
    results={'at':int(time.time()),'health':call('/api/health'),'synthetic_only':True,'steps':[]}
    assert results['health']['execution_mode']=='live_llm','Start the server with --agents qwen.'
    for source,expected in [('source-01',1),('source-14',0)]:
        start=time.monotonic()
        batch=call('/api/extract',{'command_id':str(uuid4()),'campaign_id':'campaign-saas','source_ids':[source]})
        assert batch['execution_mode']=='live_llm' and len(batch['items'])==expected
        results['steps'].append({'kind':'extract','source':source,'seconds':round(time.monotonic()-start,2),'response':batch})
        print('Live extract',source,'accepted records:',len(batch['items']),flush=True)
    for lead_id in ['lead-13','lead-14']:
        detail=call('/api/leads/'+lead_id)
        assert detail['evidence'] and all(e['is_fixture'] for e in detail['evidence'])
        assert detail['lead']['state'] in {'Discovered','Needs review'}
        start=time.monotonic()
        result=call('/api/leads/'+lead_id+'/verify',{'command_id':str(uuid4()),'expected_version':detail['lead']['version']})
        report=next(v for v in result['verifications'] if v['id']==result['lead']['current_verification_id'])
        assert report['execution_mode']=='live_llm' and report['status']=='needs_review'
        if lead_id=='lead-13': assert report['assessment']['conflicts']
        if lead_id=='lead-14': assert 'email' in report['assessment']['missing_fields']
        assert report['email_checks']['mx']=='fixture'
        assert not call('/api/leads/'+lead_id+'/gate')['allowed']
        results['steps'].append({'kind':'check','lead':lead_id,'seconds':round(time.monotonic()-start,2),'report':report})
        print('Live check',lead_id,report['status'],report['reason_codes'],flush=True)
    happy=call('/api/leads/lead-01')
    assert happy['lead']['state'] in {'Sent','Delivery/Reply status'} and happy['draft']
    report=next(v for v in happy['verifications'] if v['id']==happy['lead']['current_verification_id'])
    assert report['execution_mode']=='live_llm'
    why=call('/api/outreach/'+happy['lead']['latest_outreach_id']+'/why')
    assert why['complete'] and next(o for o in happy['outreach'] if o['id']==happy['lead']['latest_outreach_id'])['simulated']
    results['browser_happy_path']={'detail':happy,'explanation':why}
    target=Path('work/qwen-live-validation.json');target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(results,indent=2))
    print('Validated live extraction, missing email skip, conflicting/missing evidence review, and recorded browser happy path.',flush=True)


if __name__=='__main__': main()
