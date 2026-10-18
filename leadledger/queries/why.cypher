MATCH chain=(co:Company)-[:HAS_CONTACT]->(p:Person)-[:VERIFIED_BY]->(v:Verification)
 -[:QUALIFIED_FOR]->(c:Campaign)-[:AUTHORIZED_BY]->(a:Approval)
 -[:SENT_AS]->(o:Outreach {id:$outreach_id})
MATCH (o)-[:FOR_LEAD]->(l:Lead)
MATCH (p)-[:HAS_LEAD]->(l)-[:IN_CAMPAIGN]->(c)
MATCH (l)-[:HAS_VERIFICATION]->(v)
MATCH (l)-[:HAS_APPROVAL]->(a)-[:BASED_ON]->(v)
MATCH message_path=(a)-[:APPROVES]->(d:Draft)
MATCH (o)-[:USES_DRAFT]->(d)
MATCH (o)-[:TO]->(p)
WHERE o.approval_id=a.id AND o.draft_id=d.id AND a.verification_id=v.id
OPTIONAL MATCH evidence_path=(v)-[:SUPPORTED_BY]->(e:Evidence)
OPTIONAL MATCH discovery_path=(l)-[:DISCOVERED_FROM]->(source:Evidence)
RETURN chain,message_path,evidence_path,discovery_path
