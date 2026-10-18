"""Exercise the running backend through HTTP, without real outreach or an LLM key."""
import json
import sys
import urllib.request
import urllib.error
from uuid import uuid4

BASE='http://127.0.0.1:8000'


def api(path,body=None,expected=200):
    req=urllib.request.Request(BASE+path, data=json.dumps(body).encode() if body is not None else None,
                               headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req,timeout=60) as response: status,value=response.status,json.load(response)
    except urllib.error.HTTPError as exc: status,value=exc.code,json.load(exc)
    if status!=expected: raise RuntimeError(f'{path}: expected {expected}, got {status}: {value}')
    return value


def change(lead_id,action,**extra):
    version=api(f'/api/leads/{lead_id}')['lead']['version']
    return api(f'/api/leads/{lead_id}/{action}',{
        'command_id':str(uuid4()),'expected_version':version,**extra})


def main():
    lead_id=sys.argv[1] if len(sys.argv)>1 else 'lead-01'
    print('Health:',api('/api/health'))
    detail=api(f'/api/leads/{lead_id}')
    if detail['lead']['state'] in {'Discovered','Stale','Needs review'}:
        detail=change(lead_id,'verify')
    if detail['lead']['state']=='Approved': detail=change(lead_id,'draft',subject=None,body_text=None)
    if detail['lead']['state']=='Awaiting outreach approval':
        d=detail['draft']; detail=change(lead_id,'approve',draft_id=d['id'],message_hash=d['message_hash'],actor='kunal')
    if detail['lead']['state']=='Approved for sending':
        receipt=change(lead_id,'send'); outreach_id=receipt['outreach_id']
        print('Sent — simulated, log only:',receipt)
    else:
        outreach_id=detail['lead']['latest_outreach_id']
        if not outreach_id: raise RuntimeError(f'Cannot demo happy path from {detail["lead"]["state"]}.')
        print('Reusing previously recorded simulated outreach:',outreach_id)
    graph=api(f'/api/outreach/{outreach_id}/why')
    assert graph['complete']; print('Why graph:',len(graph['nodes']),'nodes,',len(graph['edges']),'edges')
    print('Stale scan:',api('/api/rechecks/scan',{'command_id':str(uuid4()),'campaign_id':'campaign-saas'}))
    for blocked in ['lead-04','lead-05']:
        d=api(f'/api/leads/{blocked}')
        error=api(f'/api/leads/{blocked}/send',{'command_id':str(uuid4()),'expected_version':d['lead']['version']},409)
        print(blocked,'BLOCKED:',error['error']['details']['gate']['reason_codes'])


if __name__=='__main__': main()
