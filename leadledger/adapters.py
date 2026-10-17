"""Replacement boundary for Shubhangi's agents and sender. Defaults are labelled fixtures."""
import copy
import hashlib
import json
from typing import Protocol
from email_validator import validate_email, EmailNotValidError
from .contracts import Problem, validate


class Agents(Protocol):
    def extract(self, context: dict) -> dict: ...  # ExtractorInput -> ExtractionBatch
    def check(self, context: dict) -> dict: ...  # CheckContext -> CheckerAssessment


class Sender(Protocol):
    def __call__(self, envelope: dict) -> dict: ...  # SendEnvelope -> SenderResult


def message_hash(draft):
    fields=['campaign_id','person_id','to_address','from_address','subject','body_text','mode']
    content={k:draft[k] for k in fields}
    return hashlib.sha256(json.dumps(content,sort_keys=True,ensure_ascii=False,
                         separators=(',',':'),allow_nan=False).encode('utf-8')).hexdigest()


def log_only_sender(envelope):
    """No network or disk side effects. Kunal's manager commits the returned result."""
    validate('SendEnvelope',envelope)
    if envelope['gate_decision']['allowed'] is not True:
        raise Problem('SEND_BLOCKED','Sender requires an allowed gate decision.')
    draft=envelope['draft']
    if draft['mode']!='log_only' or message_hash(draft)!=draft['message_hash']:
        raise Problem('SEND_BLOCKED','Sender rejected the message revision.')
    return validate('SenderResult',{'outreach_id':envelope['outreach_id'],'status':'logged',
        'mode':'log_only','message_hash':draft['message_hash'],'simulated':True})


def fixture_email_checks(person,evidence,now,scenario='present'):
    """No DNS claims: fixtures explicitly carry a simulated DNS result."""
    is_fixture=bool(evidence) and all(e['is_fixture'] for e in evidence)
    try:
        validate_email(person['email_normalized'],check_deliverability=False,
                       test_environment=is_fixture,allow_smtputf8=False)
        syntax='pass'
    except EmailNotValidError:
        syntax='fail'
    return {'syntax':syntax,'mx':'fixture' if is_fixture else 'timeout',
            'mailbox_exists':'unknown','checked_at':now,'is_fixture':is_fixture,
            'fixture_result':scenario if is_fixture else None}


class FixtureAgents:
    execution_mode='fixture_replay'
    model_id=None
    prompt_version='fixture-checker-v1'

    def __init__(self,candidates):
        self.candidates=candidates

    def extract(self,context):
        validate('ExtractorInput',context)
        records={s['source_record_id'] for s in context['sources'] if s['source_kind']!='campaign_brief'}
        return {'execution_mode':'fixture_replay','model_id':None,'prompt_version':'fixture-extractor-v1',
                'candidates':[copy.deepcopy(self.candidates[i]) for i in sorted(records)]}

    def check(self,context):
        validate('CheckContext',context)
        p,c=context['person'],context['company']
        values={'company':c['name'],'industry':c['industry'],'name':p['name'],
                'role':p['role'],'email':p['email_normalized']}
        claims=[]; missing=[]; conflicts=[]
        for field,value in values.items():
            supporting=[e for e in context['evidence'] if value in e['snapshot_text']]
            if supporting:
                e=supporting[0]
                claims.append({'field':field,'value':value,'result':'supported',
                               'evidence_ids':[e['id']],'quote':e['snapshot_text']})
            else:
                missing.append(field)
        if any('Conflicting role:' in e['snapshot_text'] for e in context['evidence']):
            conflicts.append('The source records two conflicting roles.')
        return {'lead_id':context['lead']['id'],
                'recommendation':'needs_review' if missing or conflicts else 'passed',
                'claims':claims,'conflicts':conflicts,'missing_fields':missing,
                'summary':'Fixture replay: claims checked against bundled synthetic snapshots.'}
