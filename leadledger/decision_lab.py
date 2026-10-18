"""Read-only, bounded counterfactuals using the authoritative send evaluator."""
import copy
from pathlib import Path

CHECKS=(
 ('WRONG_STATE','Lead is approved for sending'),
 ('OPTED_OUT','Person has not opted out'),
 ('SUPPRESSED','Person is not suppressed'),
 ('DUPLICATE','Lead is not a duplicate'),
 ('VERIFICATION_INVALID','Verification is current, passed and backed by evidence'),
 ('DRAFT_MISSING','A saved draft exists'),
 ('APPROVAL_INVALID','Approval binds this contact, policy, verification and draft'),
 ('MESSAGE_CHANGED','Message hash, recipient and log-only mode match'),
 ('ALREADY_CONTACTED','No earlier or uncertain outreach exists across campaigns'),
 ('AUDIT_INCONSISTENT','Graph artifact identities and relationships are consistent'))


def build_lab(manager,lead_id,facts,now,query_ms):
    baseline=manager._evaluate_gate(lead_id,facts,now)
    scenarios=[]
    for ident,title,change in [
        ('opt_out','Person opts out',{'person.opted_out':True}),
        ('suppressed','Person is suppressed',{'person.suppressed':True}),
        ('expired','Verification expires',{'verification.valid_until':now}),
        ('message','Message changes after approval',{'draft.body_text':'append hypothetical edit'})]:
        altered=copy.deepcopy(facts)
        if ident=='expired' and altered['verification'] is None:
            scenarios.append({'id':ident,'title':title,'available':False,'reason':'No current verification to expire.'})
            continue
        if ident=='message' and altered['draft'] is None:
            scenarios.append({'id':ident,'title':title,'available':False,'reason':'No saved draft to change.'})
            continue
        if ident=='opt_out': altered['person']['opted_out']=True
        elif ident=='suppressed': altered['person']['suppressed']=True
        elif ident=='expired': altered['verification']['valid_until']=now
        else: altered['draft']['body_text']+='\nHypothetical edit, never saved.'
        result=manager._evaluate_gate(lead_id,altered,now)
        scenarios.append({'id':ident,'title':title,'available':True,'hypothetical':True,
            'changed_fields':change,'decision':result,
            'added_reason_codes':[r for r in result['reason_codes'] if r not in baseline['reason_codes']]})
    # Only small, relevant graph facts are exposed; no provider keys or full report blobs.
    fields={'person':('id','opted_out','suppressed','contact_version'),
        'lead':('id','state','version','duplicate','person_id','campaign_id'),
        'campaign':('id','mode','policy_version'),
        'verification':('id','status','valid_until','contact_version'),
        'draft':('id','revision','message_hash','mode'),
        'approval':('id','revoked','message_hash','contact_version','policy_version','verification_id','draft_id')}
    visible={kind:{k:row.get(k) for k in keys} if (row:=facts[kind]) else None
             for kind,keys in fields.items()}
    visible.update({k:facts[k] for k in ('approved','basis','evidence','prior')})
    return {'read_only':True,'checked_at':now,'baseline':baseline,'checks':[
        {'code':code,'label':label,'passed':code not in baseline['reason_codes']} for code,label in CHECKS],
        'query':{'name':'gate.cypher','text':(Path(__file__).parent/'queries/gate.cypher').read_text(),
                 'parameters':{'lead_id':lead_id},'row_count':1,'duration_ms':query_ms,'access':'GRAPH.RO_QUERY'},
        'facts':visible,'scenarios':scenarios,
        'note':'Cypher retrieves graph facts; deterministic Python evaluates policy. Hypotheticals change only a copy in memory. Nothing is approved, sent or saved.'}
