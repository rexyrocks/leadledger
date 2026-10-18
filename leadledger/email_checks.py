"""Syntax and MX only; never SMTP or a claim that a mailbox exists."""
from email_validator import validate_email, EmailNotValidError
from .adapters import fixture_email_checks


class EmailChecker:
    def __init__(self, scenarios=None, resolver=None):
        self.scenarios=scenarios or {}
        self.resolver=resolver

    def __call__(self, person, evidence, now, lead_id):
        if evidence and all(e['is_fixture'] for e in evidence):
            return fixture_email_checks(person,evidence,now,self.scenarios.get(lead_id.removeprefix('historical-'),'timeout'))
        result={'syntax':'pass','mx':'timeout','mailbox_exists':'unknown',
                'checked_at':now,'is_fixture':False,'fixture_result':None}
        try: address=validate_email(person['email_normalized'],check_deliverability=False,allow_smtputf8=False)
        except EmailNotValidError:
            return {**result,'syntax':'fail','mx':'absent'}
        if not evidence: return result
        import dns.exception
        import dns.resolver
        try:
            resolver=self.resolver or dns.resolver.Resolver()
            answers=list(resolver.resolve(address.domain,'MX',lifetime=3))
            result['mx']='null_mx' if any(str(r.exchange)=='.' for r in answers) else 'present' if answers else 'absent'
        except dns.resolver.NXDOMAIN: result['mx']='nxdomain'
        except dns.resolver.NoAnswer: result['mx']='absent'
        except (dns.exception.DNSException,OSError): result['mx']='timeout'
        return result
