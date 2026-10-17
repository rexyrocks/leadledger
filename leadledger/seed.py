"""Explicit seed command; never resets existing graph history."""
import json
from uuid import uuid4
from .contracts import Problem
from .manager import Manager
from .repository import Repository, Change


def command(m,lead_id,**extra):
    return {'command_id':str(uuid4()),'expected_version':m.detail(lead_id)['lead']['version'],**extra}


def qualify(m,lead_id):
    m.verify(lead_id,command(m,lead_id))
    m.draft(lead_id,command(m,lead_id,subject=None,body_text=None))
    d=m.detail(lead_id)['draft']
    m.approve(lead_id,command(m,lead_id,draft_id=d['id'],message_hash=d['message_hash'],actor='kunal'))


def seed(m):
    m.bootstrap()
    if m.leads()['total']:
        raise Problem('INVALID_STATE','Graph already has leads. Seed a fresh graph name; history is never reset.')
    normal_clock=m.clock; now=m.clock()
    # Canonical records are inserted before their duplicate source records.
    for i in [1,2,3,4,5,6,9,7,8,*range(10,21)]:
        m.clock=(lambda:now-8*86400) if i==2 else normal_clock
        try: m.ingest(m.candidates[f'seed-{i:02}'],str(uuid4()))
        finally: m.clock=normal_clock
    m.opt_out('lead-03',command(m,'lead-03',actor='shubhangi'))
    m.clock=lambda:now-8*86400
    try:
        m.verify('lead-02',command(m,'lead-02'))
    finally: m.clock=normal_clock
    qualify(m,'lead-04'); m.opt_out('lead-04',command(m,'lead-04',actor='shubhangi'))
    qualify(m,'lead-05'); qualify(m,'lead-06'); qualify(m,'lead-18')
    m.send('lead-06',command(m,'lead-06')); m.send('lead-18',command(m,'lead-18'))
    # A fully bound historical-campaign outreach, separate from active approval.
    with m.lock:
        s=m.repo.snapshot(); u=Change(s); l=s.get('lead-05'); p=s.get(l['person_id'])
        historical={**s.get('campaign-saas'),'id':'campaign-history','name':'Historical fixture campaign'}
        u.put('Campaign',historical)
        old_lead={**l,'id':'historical-lead-05','source_record_id':'historical-seed-05',
            'campaign_id':historical['id'],'state':'Discovered','version':0,'event_sequence':0,
            'current_verification_id':None,'current_draft_id':None,'current_approval_id':None,
            'latest_outreach_id':None,'execution_mode':None}
        u.put('Lead',old_lead); u.link(p['id'],'HAS_LEAD',old_lead['id'])
        u.link(old_lead['id'],'IN_CAMPAIGN',historical['id'])
        for e in s.linked(l['id'],'DISCOVERED_FROM'): u.link(old_lead['id'],'DISCOVERED_FROM',e['id'])
        m._event(u,old_lead['id'],'historical_fixture_discovered',str(uuid4()),payload={'is_fixture':True})
        m.repo.commit(u)
    qualify(m,'historical-lead-05'); m.send('historical-lead-05',command(m,'historical-lead-05'))
    qualify(m,'lead-15')
    m.draft('lead-15',command(m,'lead-15',subject='Revised message',body_text='This revision requires new human approval.'))
    qualify(m,'lead-16')
    with m.lock:
        s=m.repo.snapshot(); u=Change(s); l=s.get('lead-16'); p=s.get(l['person_id'])
        m._guard(u,l['id'],l['version']); u.put('Person',{**p,'contact_version':p['contact_version']+1})
        m._event(u,l['id'],'contact_changed',str(uuid4()),payload={'is_fixture':True})
        m.repo.commit(u)
        s=m.repo.snapshot(); u=Change(s); l=s.get('lead-17'); p=s.get(l['person_id'])
        m._guard(u,l['id'],l['version']); u.put('Person',{**p,'suppressed':True})
        m._event(u,l['id'],'contact_suppressed',str(uuid4()),payload={'is_fixture':True}); m.repo.commit(u)
    return {'active_leads':m.leads()['total'],'canonical_people':len(m.repo.snapshot().all('Person')),
            'historical_outreach':m.detail('lead-18')['lead']['latest_outreach_id']}


if __name__=='__main__':
    repo=Repository.connect()
    try: print(json.dumps(seed(Manager(repo)),indent=2))
    finally: repo.close()
