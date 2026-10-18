"""Synthetic permitted sources. Nothing here represents a real prospect."""
import hashlib

CAMPAIGN={'id':'campaign-saas','name':'SaaS partnerships','industry':'B2B SaaS',
          'target_role':'Head of Partnerships','policy_version':'policy-v1',
          'verification_ttl_seconds':604800,'mode':'log_only'}


def registry(now):
    names=['Asha Rao','Dev Mehta','Mira Shah','Riya Sen','Kabir Jain','Neha Das',
           'Asha Rao','Isha Roy','Isha Roy','Aryan Patel','Tara Bose','Veer Sethi',
           'Anaya Kapoor','Rehan Khan','Diya Nair','Arjun Iyer','Sana Ali',
           'Nikhil Joshi','Zoya Malik','Ishaan Gupta']
    companies=['Acme','Orbit','Vista','Cedar','Northstar','Relay','Acme','Lattice',
               'Lattice','Flint','Nimbus','Atlas','Bloom','Canvas','Forma','Helix',
               'Prism','Quill','Signal','Tandem']
    sources={}; candidates={}; scenarios={}
    for i,(name,co) in enumerate(zip(names,companies),1):
        domain=co.lower()+'.test'; email=name.split()[0].lower()+'@'+domain
        if i==10: email='not-an-email'
        text=f'{co} Demo is a B2B SaaS company. {name} is Head of Partnerships.'
        if i!=14: text+=f' Email: {email}.'
        if i==13: text+=' Conflicting role: Finance Intern.'
        source_id=f'source-{i:02}'; record_id=f'seed-{i:02}'
        sources[source_id]={'id':source_id,'source_record_id':record_id,
            'source_uri':f'fixture://{co.lower()}/team/{i}', 'source_kind':'contact_page',
            'snapshot_text':text,'content_hash':hashlib.sha256(text.encode()).hexdigest(),
            'captured_at':now-8*86400 if i==2 else now,'is_fixture':True}
        candidates[record_id]={'source_record_id':record_id,'campaign_id':CAMPAIGN['id'],
            'company':{'name':co+' Demo','domain':domain,'industry':'B2B SaaS'},
            'person':{'name':name,'role':'Head of Partnerships','email':email},
            'evidence':[{'source_id':source_id,'field':f,'quote':text}
                        for f in ['company','industry','name','role']+(['email'] if i!=14 else [])]}
        scenarios[f'lead-{i:02}']='nxdomain' if i==11 else 'timeout' if i==12 else 'present'
    return sources,candidates,scenarios
