"""Single-writer deterministic workflow. Every authoritative fact lives in FalkorDB."""
import copy
import hashlib
import json
import threading
import time
from uuid import uuid4
from jsonschema import ValidationError
from email_validator import validate_email, EmailNotValidError
from .adapters import FixtureAgents, fixture_email_checks, log_only_sender, message_hash
from .contracts import Problem, conflict, project, uid, validate
from .fixtures import CAMPAIGN, registry
from .repository import Change

TRANSITIONS={
 'Discovered':{'Verification pending','Rejected'},
 'Verification pending':{'Approved','Needs review','Rejected'},
 'Approved':{'Awaiting outreach approval','Stale'},
 'Awaiting outreach approval':{'Approved for sending','Stale'},
 'Approved for sending':{'Awaiting outreach approval','Sent','Stale'},
 'Stale':{'Verification pending'},'Needs review':{'Verification pending'},
 'Rejected':{'Verification pending'},'Sent':{'Delivery/Reply status'},
 'Delivery/Reply status':{'Delivery/Reply status'},'Opted out':set()}


class Manager:
    def __init__(self,repo,agents=None,sender=log_only_sender,clock=None,email_checker=None,drafter=None):
        self.repo=repo; self.clock=clock or (lambda:int(time.time()))
        self.sources,self.candidates,self.dns_scenarios=registry(self.clock())
        self.agents=agents or FixtureAgents(self.candidates)
        self.sender=sender
        self.email_checker=email_checker or self._fixture_checks
        self.drafter=drafter
        self.lock=threading.RLock()
        self.inflight=set()

    def _fixture_checks(self,person,evidence,now,lead_id):
        return fixture_email_checks(person,evidence,now,self.dns_scenarios.get(lead_id.removeprefix('historical-'),'timeout'))

    def _summary(self,s,l):
        p=s.get(l['person_id'],'Person'); c=s.get(l['company_id'],'Company')
        d=project('LeadSummary',{**l,'person_name':p['name'],'role':p['role'],
            'email_normalized':p['email_normalized'],'company_name':c['name']})
        return validate('LeadSummary',d)

    def _detail(self,s,lead_id):
        l=s.get(lead_id,'Lead')
        reports=[json.loads(v['report_json']) for v in s.linked(lead_id,'HAS_VERIFICATION')]
        events=[{**project('Event',e),'payload':json.loads(e['payload_json'])}
                for e in s.linked(lead_id,'HAS_EVENT')]
        details={'lead':self._summary(s,l),'company':project('Company',s.get(l['company_id'])),
            'person':project('Person',s.get(l['person_id'])),'campaign':project('Campaign',s.get(l['campaign_id'])),
            'evidence':[project('Evidence',e) for e in s.linked(lead_id,'DISCOVERED_FROM')],
            'verifications':sorted(reports,key=lambda x:(x['checked_at'],x['id'])),
            'draft':project('Draft',s.get(l['current_draft_id'])) if l.get('current_draft_id') else None,
            'approvals':[project('Approval',a) for a in s.linked(lead_id,'HAS_APPROVAL')],
            'outreach':[project('Outreach',o) for o in s.all('Outreach') if s.has(o['id'],'FOR_LEAD',lead_id)],
            'events':sorted(events,key=lambda e:e['sequence'])}
        return validate('LeadDetail',details)

    def detail(self,lead_id):
        with self.lock: return self._detail(self.repo.snapshot(),lead_id)

    def leads(self):
        with self.lock:
            s=self.repo.snapshot()
            items=[self._summary(s,l) for l in sorted(s.all('Lead'),key=lambda x:x['id'])
                   if l['campaign_id']==CAMPAIGN['id']]
            return {'items':items,'total':len(items)}

    def _fingerprint(self,action,body):
        return hashlib.sha256(json.dumps([action,body],sort_keys=True,separators=(',',':')).encode()).hexdigest()

    def _replay(self,s,action,body):
        ident=body['command_id']
        if ident in self.inflight:
            raise Problem('COMMAND_IN_PROGRESS','This command is still running.')
        if ident not in s.nodes: return None
        c=s.get(ident,'Command')
        if c['fingerprint']!=self._fingerprint(action,body):
            raise Problem('COMMAND_REUSED','Use a new command_id for a different request.')
        result=json.loads(c['result_json'])
        if c['http_status']!=200:
            e=result['error']; raise Problem(e['code'],e['message'],c['http_status'],e['details'])
        return result

    def _save(self,u,action,body,result,status=200):
        u.put('Command',{'id':body['command_id'],'created_at':self.clock(),
            'fingerprint':self._fingerprint(action,body),'result_json':json.dumps(result),
            'http_status':status})
        self.repo.commit(u)
        return result

    def _guard(self,u,lead_id,expected):
        l=u.s.get(lead_id,'Lead')
        if l['version']!=expected: raise conflict()
        u.guards.setdefault(lead_id,expected)
        return l

    def _event(self,u,lead_id,kind,command_id,actor='system',target=None,payload=None,artifacts=()):
        l=u.s.get(lead_id,'Lead'); before=l['state']; target=target or before
        if target!=before and target!='Opted out' and target not in TRANSITIONS[before]:
            raise Problem('INVALID_STATE',f'Cannot move from {before} to {target}.')
        if before=='Opted out' and target!=before:
            raise Problem('INVALID_STATE','An opted-out lead cannot be reopened.')
        l=u.put('Lead',{**l,'state':target,'updated_at':self.clock(),
                       'version':l['version']+1,'event_sequence':l.get('event_sequence',0)+1})
        event=u.put('Event',{'id':uid('event'),'created_at':self.clock(),'lead_id':lead_id,
            'sequence':l['event_sequence'],'type':kind,'actor':actor,'at':self.clock(),
            'from_state':before,'to_state':target,'command_id':command_id,
            'payload_json':json.dumps(payload or {})})
        u.link(lead_id,'HAS_EVENT',event['id'])
        for artifact in artifacts: u.link(artifact,'HAS_EVENT',event['id'])
        return l

    def _invalidate(self,u,l):
        if l.get('current_approval_id'):
            a=u.s.get(l['current_approval_id'],'Approval')
            u.put('Approval',{**a,'revoked':True})
        return u.put('Lead',{**l,'current_approval_id':None})

    def bootstrap(self):
        with self.lock:
            self.repo.ensure_graph()
            s=self.repo.snapshot()
            if CAMPAIGN['id'] not in s.nodes:
                u=Change(s); u.put('Campaign',{**CAMPAIGN,'created_at':self.clock()}); self.repo.commit(u)

    def ingest(self,candidate,command_id):
        validate('LeadCandidate',candidate)
        with self.lock:
            body={'command_id':command_id,'candidate':candidate}; action='ingest'
            s=self.repo.snapshot(); cached=self._replay(s,action,body)
            if cached is not None: return cached
            s.get(candidate['campaign_id'],'Campaign')
            if candidate['campaign_id']!=CAMPAIGN['id']:
                raise Problem('INVALID_INPUT','Only the active campaign accepts discovery.',422)
            record=candidate['source_record_id']
            for l in s.all('Lead'):
                if l['source_record_id']==record:
                    result={'source_record_id':record,'lead_id':l['id'],'person_id':l['person_id'],
                            'outcome':'existing','canonical_lead_id':l.get('duplicate_of_id'),
                            'state':l['state'],'version':l['version']}
                    return self._save(Change(s),action,body,result)
            evidence_sources={}
            for cite in candidate['evidence']:
                source=self.sources.get(cite['source_id'])
                if not source or source['source_record_id']!=record or cite['quote'] not in source['snapshot_text']:
                    raise Problem('INVALID_INPUT','Candidate contains an unknown source or unsupported quote.',422)
                evidence_sources[source['id']]=source
            p=candidate['person']; co=candidate['company']
            try: email=validate_email(p['email'],check_deliverability=False,test_environment=True).normalized
            except EmailNotValidError: email=p['email'].strip()
            identity=hashlib.sha256(email.casefold().encode()).hexdigest()
            person=next((x for x in s.all('Person') if x['identity_key']==identity),None)
            canonical=next((l for l in s.all('Lead') if person and l['person_id']==person['id']
                            and l['campaign_id']==candidate['campaign_id'] and not l['duplicate']),None)
            u=Change(s)
            company_id='company-'+hashlib.sha256(co['domain'].casefold().encode()).hexdigest()[:24]
            if company_id not in s.nodes: u.put('Company',{'id':company_id,**co,'created_at':self.clock()})
            if person is None:
                person=u.put('Person',{'id':uid('person'),'name':p['name'],'role':p['role'],
                    'email_normalized':email,'identity_key':identity,'contact_version':1,
                    'opted_out':False,'suppressed':False,'created_at':self.clock()})
            lead_id='lead-'+record[5:] if record.startswith('seed-') else uid('lead')
            if lead_id in s.nodes: raise Problem('INVALID_INPUT','Source record ID collision.',422)
            l=u.put('Lead',{'id':lead_id,'created_at':self.clock(),'updated_at':self.clock(),
                'source_record_id':record,'campaign_id':candidate['campaign_id'],'company_id':company_id,
                'person_id':person['id'],'state':'Discovered','version':0,'event_sequence':0,
                'duplicate':canonical is not None,'duplicate_of_id':canonical['id'] if canonical else None,
                'execution_mode':None,'current_verification_id':None,'current_draft_id':None,
                'current_approval_id':None,'latest_outreach_id':None})
            u.link(company_id,'HAS_CONTACT',person['id']); u.link(person['id'],'HAS_LEAD',lead_id)
            u.link(lead_id,'IN_CAMPAIGN',l['campaign_id'])
            for source in evidence_sources.values():
                e=u.put('Evidence',{**{k:v for k,v in source.items() if k!='source_record_id'},
                    'id':uid('evidence'),'source_id':source['id'],'created_at':self.clock()})
                u.link(lead_id,'DISCOVERED_FROM',e['id'])
            self._event(u,lead_id,'lead_discovered',command_id,'extractor')
            if canonical:
                u.link(lead_id,'DUPLICATE_OF',canonical['id'])
                self._event(u,lead_id,'duplicate_detected',command_id,target='Rejected',
                            payload={'canonical_lead_id':canonical['id']})
            if person['opted_out']:
                self._event(u,lead_id,'opted_out',command_id,target='Opted out')
            l=u.s.get(lead_id)
            result={'source_record_id':record,'lead_id':lead_id,'person_id':person['id'],
                    'outcome':'duplicate' if canonical else 'inserted',
                    'canonical_lead_id':canonical['id'] if canonical else None,'state':l['state'],'version':l['version']}
            return self._save(u,action,body,validate('IngestResult',result))

    def check_context(self,lead_id,s=None):
        s=s or self.repo.snapshot(); d=self._detail(s,lead_id)
        return validate('CheckContext',{'lead':d['lead'],'company':d['company'],'person':d['person'],
            'campaign':d['campaign'],'evidence':d['evidence'],'previous_reports':d['verifications'],
            'history':d['events'],'email_checks':self.email_checker(d['person'],d['evidence'],self.clock(),lead_id)})

    def _classification(self,context,assessment):
        expected={'company':context['company']['name'],'industry':context['company']['industry'],
                  'name':context['person']['name'],'role':context['person']['role'],
                  'email':context['person']['email_normalized']}
        evidence={e['id']:e for e in context['evidence']}; supported=set(); reasons=[]
        for claim in assessment['claims']:
            if any(i not in evidence for i in claim['evidence_ids']):
                reasons.append('UNKNOWN_EVIDENCE'); continue
            if claim['result']=='supported':
                if (not claim['quote'] or not claim['evidence_ids']
                    or any(claim['quote'] not in evidence[i]['snapshot_text'] for i in claim['evidence_ids'])
                    or claim['value']!=expected[claim['field']] or claim['value'] not in claim['quote']):
                    reasons.append('UNSUPPORTED_CLAIM')
                else: supported.add(claim['field'])
        checks=context['email_checks']; mx=checks['fixture_result'] if checks['is_fixture'] else checks['mx']
        if checks['syntax']=='fail' or mx in {'nxdomain','null_mx'}:
            return 'rejected',['EMAIL_INVALID']
        if reasons: return 'needs_review',sorted(set(reasons))
        if checks['is_fixture'] and (checks['mx']!='fixture' or checks['fixture_result'] is None):
            return 'needs_review',['DNS_UNCERTAIN']
        if mx!='present': reasons.append('DNS_UNCERTAIN')
        if supported!=set(expected) or assessment['missing_fields']: reasons.append('MISSING_EVIDENCE')
        if assessment['conflicts'] or any(c['result']!='supported' for c in assessment['claims']):
            reasons.append('CONFLICTING_EVIDENCE')
        if context['company']['industry']!=context['campaign']['industry'] or context['person']['role']!=context['campaign']['target_role']:
            reasons.append('CAMPAIGN_MISMATCH')
        if any(e['captured_at']+604800<=self.clock() for e in evidence.values()): reasons.append('STALE_EVIDENCE')
        # A model's rejected recommendation cannot establish a confirmed contradiction by itself.
        if assessment['recommendation']!='passed': reasons.append('CHECKER_REVIEW')
        return ('needs_review',sorted(set(reasons))) if reasons else ('passed',[])

    def verify(self,lead_id,body):
        action=f'verify:{lead_id}'
        with self.lock:
            s=self.repo.snapshot(); cached=self._replay(s,action,body)
            if cached is not None: return cached
            u=Change(s); l=self._guard(u,lead_id,body['expected_version'])
            if l['duplicate'] or l['state'] not in {'Discovered','Stale','Needs review','Rejected'}:
                raise Problem('INVALID_STATE','This lead cannot enter verification.')
            if l['state']=='Rejected':
                current=s.nodes.get(l.get('current_verification_id'))
                latest=json.loads(current['report_json']) if current else None
                if latest and set(e['id'] for e in s.linked(lead_id,'DISCOVERED_FROM')) <= set(
                    i for c in latest['assessment']['claims'] for i in c['evidence_ids']):
                    raise Problem('INVALID_STATE','Reopening a rejected lead requires new evidence.')
            l=self._invalidate(u,l)
            self._event(u,lead_id,'verification_started',body['command_id'],'checker',target='Verification pending')
            self.repo.commit(u); context=self.check_context(lead_id,u.s)
            pending_version=u.s.get(lead_id)['version']; self.inflight.add(body['command_id'])
        try:
            try:
                assessment=self.agents.check(copy.deepcopy(context)); validate('CheckerAssessment',assessment)
                if assessment['lead_id']!=lead_id: raise ValueError('wrong lead')
                status,reasons=self._classification(context,assessment)
            except Exception:
                assessment={'lead_id':lead_id,'recommendation':'needs_review','claims':[],
                    'conflicts':[],'missing_fields':['company','industry','name','role','email'],
                    'summary':'Checker unavailable or returned an invalid report; review required.'}
                status,reasons='needs_review',['CHECKER_UNAVAILABLE_OR_INVALID']
            with self.lock:
                s=self.repo.snapshot(); u=Change(s); l=self._guard(u,lead_id,pending_version)
                if s.get(l['person_id'])['contact_version']!=context['person']['contact_version']:
                    raise conflict('Contact changed while checking. Run verification again.')
                checked=self.clock(); valid_until=checked if status!='passed' else min(
                    checked+context['campaign']['verification_ttl_seconds'],
                    min(e['captured_at']+604800 for e in context['evidence']))
                report={'id':uid('verification'),'lead_id':lead_id,'person_id':l['person_id'],
                    'campaign_id':l['campaign_id'],'contact_version':context['person']['contact_version'],
                    'status':status,'checked_at':checked,'valid_until':valid_until,'assessment':assessment,
                    'email_checks':context['email_checks'],'model_id':self.agents.model_id,
                    'prompt_version':self.agents.prompt_version,'execution_mode':self.agents.execution_mode,
                    'reason_codes':reasons}
                validate('VerificationReport',report)
                v=u.put('Verification',{**{k:v for k,v in report.items() if k not in {'assessment','email_checks','reason_codes'}},
                    'created_at':checked,'report_json':json.dumps(report)})
                u.link(lead_id,'HAS_VERIFICATION',v['id']); u.link(l['person_id'],'VERIFIED_BY',v['id'])
                if status=='passed': u.link(v['id'],'QUALIFIED_FOR',l['campaign_id'])
                for claim in assessment['claims']:
                    for ident in claim['evidence_ids']:
                        if ident in {e['id'] for e in context['evidence']}: u.link(v['id'],'SUPPORTED_BY',ident)
                u.put('Lead',{**l,'current_verification_id':v['id'],'execution_mode':report['execution_mode']})
                target={'passed':'Approved','needs_review':'Needs review','rejected':'Rejected'}[status]
                self._event(u,lead_id,'verification_completed',body['command_id'],'checker',target=target,
                            payload={'verification_id':v['id'],'reason_codes':reasons},artifacts=[v['id']])
                return self._save(u,action,body,self._detail(u.s,lead_id))
        finally:
            with self.lock: self.inflight.discard(body['command_id'])

    def draft(self,lead_id,body):
        action=f'draft:{lead_id}'
        generated=None
        if self.drafter and body['subject'] is None and body['body_text'] is None:
            # Network/model work must not hold the mutation lock. Recheck all current
            # bindings below after generation, before persisting a revision.
            with self.lock:
                s=self.repo.snapshot(); cached=self._replay(s,action,body)
                if cached is not None: return cached
                l=self._guard(Change(s),lead_id,body['expected_version'])
                if l['state'] not in {'Approved','Awaiting outreach approval','Approved for sending'}:
                    raise Problem('INVALID_STATE','Verify this lead before drafting.')
                v=s.get(l['current_verification_id']); p=s.get(l['person_id'])
                if v['status']!='passed' or v['valid_until']<=self.clock() or v['contact_version']!=p['contact_version']:
                    raise Problem('INVALID_STATE','Verification is stale. Run the recheck scan.')
                context=copy.deepcopy(self._detail(s,lead_id))
            generated=self.drafter(context)
            if (not isinstance(generated,dict) or set(generated)!={'subject','body_text'}
                or any(not isinstance(v,str) or not v.strip() for v in generated.values())):
                raise Problem('ASSESSMENT_INVALID','Draft generator returned invalid content.',422)
        with self.lock:
            s=self.repo.snapshot(); cached=self._replay(s,action,body)
            if cached is not None: return cached
            u=Change(s); l=self._guard(u,lead_id,body['expected_version']); p=s.get(l['person_id'])
            if l['state'] not in {'Approved','Awaiting outreach approval','Approved for sending'}:
                raise Problem('INVALID_STATE','Verify this lead before drafting.')
            v=s.get(l['current_verification_id'])
            if v['status']!='passed' or v['valid_until']<=self.clock() or v['contact_version']!=p['contact_version']:
                raise Problem('INVALID_STATE','Verification is stale. Run the recheck scan.')
            if (body['subject'] is None)!=(body['body_text'] is None):
                raise Problem('INVALID_INPUT','Provide both subject and body, or set both to null.',422)
            previous=s.get(l['current_draft_id']) if l.get('current_draft_id') else None
            d={'id':uid('draft'),'lead_id':lead_id,'person_id':p['id'],'campaign_id':l['campaign_id'],
                'revision':previous['revision']+1 if previous else 1,'to_address':p['email_normalized'],
                'from_address':'kunal@leadledger.test','subject':body['subject'] or (generated or {}).get('subject') or f'A partnership conversation with {s.get(l["company_id"])["name"]}',
                'body_text':body['body_text'] or (generated or {}).get('body_text') or f'Hi {p["name"].split()[0]},\nWould you be open to a conversation about a SaaS partnership?\nKunal',
                'mode':'log_only','created_at':self.clock()}
            d['message_hash']=message_hash(d); validate('Draft',d); u.put('Draft',d)
            u.link(lead_id,'HAS_DRAFT',d['id']); l=self._invalidate(u,l)
            u.put('Lead',{**l,'current_draft_id':d['id']})
            self._event(u,lead_id,'draft_created',body['command_id'],target='Awaiting outreach approval',
                        payload={'draft_id':d['id'],'message_hash':d['message_hash'],
                                 'generator':'qwen' if generated else 'human' if body['subject'] is not None else 'template',
                                 'model_id':self.agents.model_id if generated else None})
            return self._save(u,action,body,self._detail(u.s,lead_id))

    def gate(self,lead_id):
        with self.lock:
            rows=self.repo.query_file('gate',{'lead_id':lead_id})
            if not rows: raise Problem('NOT_FOUND','Lead not found.',404)
            if len(rows)!=1: raise Problem('DEPENDENCY_UNAVAILABLE','Ambiguous graph facts; sending blocked.',503)
            p,l,c,v,d,a,approved,basis,evidence,prior=rows[0]
            p,l,c=[dict(x.properties) for x in [p,l,c]]
            v,d,a=[dict(x.properties) if x else None for x in [v,d,a]]
            reasons=[]
            if l.get('state')!='Approved for sending': reasons.append('WRONG_STATE')
            if p.get('opted_out') is not False: reasons.append('OPTED_OUT')
            if p.get('suppressed') is not False: reasons.append('SUPPRESSED')
            if l.get('duplicate') is not False: reasons.append('DUPLICATE')
            if (not v or v.get('status')!='passed' or v.get('valid_until',0)<=self.clock()
                or v.get('contact_version')!=p.get('contact_version') or not evidence):
                reasons.append('VERIFICATION_INVALID')
            if not d: reasons.append('DRAFT_MISSING')
            if (not a or a.get('revoked') is not False or not approved or not basis
                or a.get('contact_version')!=p.get('contact_version')
                or a.get('policy_version')!=c.get('policy_version')
                or a.get('verification_id')!=(v or {}).get('id')
                or a.get('draft_id')!=(d or {}).get('id')):
                reasons.append('APPROVAL_INVALID')
            if (not d or not a or a.get('message_hash')!=d.get('message_hash')
                or message_hash(d)!=d.get('message_hash')
                or d.get('to_address')!=p.get('email_normalized') or d.get('mode')!='log_only'):
                reasons.append('MESSAGE_CHANGED')
            if prior: reasons.append('ALREADY_CONTACTED')
            for artifact in [v,d,a]:
                if artifact and (artifact.get('lead_id')!=l['id'] or artifact.get('person_id')!=p['id']
                                 or artifact.get('campaign_id')!=c['id']):
                    reasons.append('AUDIT_INCONSISTENT')
            if (l.get('person_id')!=p['id'] or l.get('campaign_id')!=c['id'] or c.get('mode')!='log_only'
                or any(len(x)>1 for x in [approved,basis])): reasons.append('AUDIT_INCONSISTENT')
            return validate('GateDecision',{'allowed':not reasons,'reason_codes':list(dict.fromkeys(reasons)),
                'lead_id':lead_id,'lead_version':l['version'],'verification_id':(v or {}).get('id'),
                'approval_id':(a or {}).get('id'),'draft_id':(d or {}).get('id'),
                'message_hash':(d or {}).get('message_hash'),'checked_at':self.clock(),
                'prior_outreach_ids':sorted(set(prior))})

    def send(self,lead_id,body):
        action=f'send:{lead_id}'
        with self.lock:
            s=self.repo.snapshot(); cached=self._replay(s,action,body)
            if cached is not None: return cached
            u=Change(s); l=self._guard(u,lead_id,body['expected_version'])
            gate=self.gate(lead_id)
            if not gate['allowed']:
                self._event(u,lead_id,'send_blocked',body['command_id'],payload={'gate':gate})
                error=Problem('SEND_BLOCKED','The graph blocked this send.',409,{'gate':gate})
                self._save(u,action,body,error.body,409)
                raise error
            outreach_id=uid('outreach'); draft=project('Draft',s.get(gate['draft_id']))
            envelope={'outreach_id':outreach_id,'lead_id':lead_id,'approval_id':gate['approval_id'],
                'verification_id':gate['verification_id'],'draft':draft,
                'idempotency_key':body['command_id'],'gate_decision':gate}
            try:
                result=self.sender(copy.deepcopy(validate('SendEnvelope',envelope)))
                validate('SenderResult',result)
            except Exception as exc:
                raise Problem('DEPENDENCY_UNAVAILABLE','Log-only sender failed; no send was recorded.',503) from exc
            if result['outreach_id']!=outreach_id or result['message_hash']!=draft['message_hash']:
                raise Problem('DEPENDENCY_UNAVAILABLE','Sender returned an inconsistent receipt.',503)
            now=self.clock()
            o=u.put('Outreach',{'id':outreach_id,'created_at':now,'lead_id':lead_id,
                'person_id':l['person_id'],'campaign_id':l['campaign_id'],'approval_id':gate['approval_id'],
                'draft_id':draft['id'],'message_hash':draft['message_hash'],'mode':'log_only','status':'sent',
                'idempotency_key':body['command_id'],'sent_at':now,'outcome':None,'simulated':True})
            for source,rel,target in [(gate['approval_id'],'SENT_AS',outreach_id),
                (outreach_id,'FOR_LEAD',lead_id),(outreach_id,'TO',l['person_id']),
                (outreach_id,'USES_DRAFT',draft['id'])]: u.link(source,rel,target)
            self._event(u,lead_id,'gate_allowed',body['command_id'],payload={'gate':gate},artifacts=[o['id']])
            self._event(u,lead_id,'send_logged',body['command_id'],target='Sent',
                        payload={'outreach_id':outreach_id,'simulated':True},artifacts=[o['id']])
            u.put('Lead',{**u.s.get(lead_id),'latest_outreach_id':outreach_id})
            receipt=validate('SendReceipt',{'outreach_id':outreach_id,'lead_id':lead_id,
                'lead_version':u.s.get(lead_id)['version'],'status':'sent','mode':'log_only',
                'reason_codes':[],'message_hash':draft['message_hash'],'recorded_at':now,'simulated':True})
            return self._save(u,action,body,receipt)

    def opt_out(self,lead_id,body):
        action=f'opt-out:{lead_id}'
        with self.lock:
            s=self.repo.snapshot(); cached=self._replay(s,action,body)
            if cached is not None: return cached
            u=Change(s); l=self._guard(u,lead_id,body['expected_version']); p=s.get(l['person_id'])
            u.put('Person',{**p,'opted_out':True})
            for related in s.all('Lead'):
                if related['person_id']!=p['id']: continue
                self._guard(u,related['id'],related['version']); self._invalidate(u,related)
                self._event(u,related['id'],'opted_out',body['command_id'],body['actor'],target='Opted out')
            return self._save(u,action,body,self._detail(u.s,lead_id))

    def scan(self,body):
        action='scan'
        with self.lock:
            s=self.repo.snapshot(); cached=self._replay(s,action,body)
            if cached is not None: return cached
            s.get(body['campaign_id'],'Campaign'); u=Change(s); updated=[]
            rows=self.repo.query_file('stale',{'campaign_id':body['campaign_id'],'now':self.clock()})
            for lead_id,ver in rows:
                l=self._guard(u,lead_id,ver); self._invalidate(u,l)
                self._event(u,lead_id,'verification_expired',body['command_id'],target='Stale')
                updated.append(self._summary(u.s,u.s.get(lead_id)))
            return self._save(u,action,body,{'checked_at':self.clock(),'updated':updated})

    def recover(self):
        """Run before serving requests. Never race this with active checking work."""
        with self.lock:
            s=self.repo.snapshot(); u=Change(s)
            for l in s.all('Lead'):
                if l['state']=='Verification pending':
                    self._guard(u,l['id'],l['version'])
                    self._event(u,l['id'],'verification_interrupted',str(uuid4()),target='Needs review')
            if u.nodes: self.repo.commit(u)

    def extract(self,body):
        action='extract'
        with self.lock:
            s=self.repo.snapshot(); cached=self._replay(s,action,body)
            if cached is not None: return cached
            if body['campaign_id']!=CAMPAIGN['id']:
                raise Problem('INVALID_INPUT','Only the active campaign supports extraction.',422)
            if any(i not in self.sources for i in body['source_ids']):
                raise Problem('INVALID_INPUT','Select permitted source IDs.',422)
            context={'campaign_id':body['campaign_id'],'campaign':project('Campaign',s.get(body['campaign_id'])),
                     'sources':[self.sources[i] for i in body['source_ids']]}
            self.inflight.add(body['command_id'])
        try:
            batch=self.agents.extract(copy.deepcopy(context)); validate('ExtractionBatch',batch)
            permitted=set(body['source_ids'])
            for c in batch['candidates']:
                if c['campaign_id']!=body['campaign_id'] or any(e['source_id'] not in permitted for e in c['evidence']):
                    raise Problem('ASSESSMENT_INVALID','Extractor cited an unselected source.',422)
            # Child commands make a retried batch resume without duplicating candidates.
            from uuid import UUID,uuid5
            results=[self.ingest(c,str(uuid5(UUID(body['command_id']),c['source_record_id'])))
                     for c in batch['candidates']]
            result={**{k:batch[k] for k in ['execution_mode','model_id','prompt_version']},'items':results}
            with self.lock: return self._save(Change(self.repo.snapshot()),action,body,validate('ExtractResponse',result))
        finally:
            with self.lock: self.inflight.discard(body['command_id'])

    def outcome(self,outreach_id,body):
        action=f'outcome:{outreach_id}'
        with self.lock:
            s=self.repo.snapshot(); cached=self._replay(s,action,body)
            if cached is not None: return cached
            o=s.get(outreach_id,'Outreach'); lead_id=o['lead_id']; u=Change(s)
            l=self._guard(u,lead_id,body['expected_version'])
            # Outcomes may arrive after an opt-out; preserve the terminal lead state.
            if l['state'] not in {'Sent','Delivery/Reply status','Opted out'}:
                raise Problem('INVALID_STATE','This lead has no sent outreach.')
            u.put('Outreach',{**o,'outcome':body['outcome']})
            self._event(u,lead_id,'simulated_'+body['outcome'],body['command_id'],body['actor'],
                        target='Opted out' if l['state']=='Opted out' else 'Delivery/Reply status',
                        payload={'outreach_id':outreach_id,'simulated':True},artifacts=[outreach_id])
            return self._save(u,action,body,self._detail(u.s,lead_id))

    def explain(self,outreach_id):
        with self.lock:
            s=self.repo.snapshot(); o=s.get(outreach_id,'Outreach')
            rows=self.repo.query_file('why',{'outreach_id':outreach_id})
            paths=[p for row in rows for p in row if p is not None]
            artifact_ids={o['id'],o['approval_id']}
            a=s.nodes.get(o['approval_id'],{})
            if a.get('verification_id'): artifact_ids.add(a['verification_id'])
            paths.extend(row[0] for row in self.repo.query_file('why_events',{'artifact_ids':sorted(artifact_ids)}))
            node_ids=set(); edge_ids=set()
            for path in paths:
                node_ids.update(n.properties['id'] for n in path.nodes())
                edge_ids.update(e.properties['id'] for e in path.edges())
            # Include all causal binding edges between the scoped nodes, not campaign neighbors.
            for ident,(source,_,target) in s.edges.items():
                if source in node_ids and target in node_ids: edge_ids.add(ident)
            nodes=[]; events=[]
            for ident in sorted(node_ids):
                n=s.get(ident); label=s.labels[ident]
                props=copy.deepcopy(n)
                if 'report_json' in props: props['report']=json.loads(props.pop('report_json'))
                if 'payload_json' in props: props['payload']=json.loads(props.pop('payload_json'))
                name=n.get('name') or n.get('subject') or n.get('type') or label
                nodes.append({'data':{'id':ident,'label':name,'type':label,'properties':props}})
                if label=='Event': events.append({**project('Event',n),'payload':props['payload']})
            types={e['type'] for e in events}
            complete=bool(rows) and any(s.labels[i]=='Evidence' for i in node_ids) and {
                'verification_completed','outreach_approved','gate_allowed','send_logged'}<=types
            if any(x not in node_ids for x in [o['id'],a.get('id'),a.get('verification_id'),o['draft_id']]): complete=False
            summary=('Recorded evidence, human approval and the gate authorized this simulated send.'
                     if complete else 'Incomplete audit chain. Some recorded evidence or decision links are missing.')
            return validate('ExplanationGraph',{'outreach_id':outreach_id,'complete':complete,'nodes':nodes,
                'edges':[{'data':{'id':i,'source':s.edges[i][0],'target':s.edges[i][2],'label':s.edges[i][1]}}
                         for i in sorted(edge_ids)],'events':sorted(events,key=lambda e:e['sequence']),'summary':summary})

    def approve(self,lead_id,body):
        action=f'approve:{lead_id}'
        with self.lock:
            s=self.repo.snapshot(); cached=self._replay(s,action,body)
            if cached is not None: return cached
            u=Change(s); l=self._guard(u,lead_id,body['expected_version'])
            if l['state']!='Awaiting outreach approval': raise Problem('INVALID_STATE','This lead is not awaiting approval.')
            p=s.get(l['person_id']); v=s.get(l['current_verification_id']); d=s.get(l['current_draft_id']); c=s.get(l['campaign_id'])
            if (p['opted_out'] or p['suppressed'] or v['status']!='passed'
                or v['valid_until']<=self.clock() or v['contact_version']!=p['contact_version']):
                raise Problem('INVALID_STATE','This contact is not eligible for approval.')
            if body['draft_id']!=d['id'] or body['message_hash']!=d['message_hash'] or message_hash(d)!=d['message_hash']:
                raise conflict('The message changed. Review the latest revision.')
            a=u.put('Approval',{'id':uid('approval'),'created_at':self.clock(),'lead_id':lead_id,
                'person_id':p['id'],'campaign_id':c['id'],'verification_id':v['id'],'draft_id':d['id'],
                'contact_version':p['contact_version'],'message_hash':d['message_hash'],'policy_version':c['policy_version'],
                'approved_by':body['actor'],'approved_at':self.clock(),'revoked':False})
            u.link(lead_id,'HAS_APPROVAL',a['id']); u.link(c['id'],'AUTHORIZED_BY',a['id'])
            u.link(a['id'],'BASED_ON',v['id']); u.link(a['id'],'APPROVES',d['id'])
            u.put('Lead',{**l,'current_approval_id':a['id']})
            self._event(u,lead_id,'outreach_approved',body['command_id'],body['actor'],target='Approved for sending',
                        payload={'approval_id':a['id'],'message_hash':d['message_hash']},artifacts=[a['id']])
            return self._save(u,action,body,self._detail(u.s,lead_id))
