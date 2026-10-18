MATCH (p:Person)-[:HAS_LEAD]->(l:Lead {id:$lead_id})-[:IN_CAMPAIGN]->(c:Campaign)
OPTIONAL MATCH (l)-[:HAS_VERIFICATION]->(v:Verification)
WHERE v.id=l.current_verification_id
OPTIONAL MATCH (l)-[:HAS_DRAFT]->(d:Draft)
WHERE d.id=l.current_draft_id
OPTIONAL MATCH (l)-[:HAS_APPROVAL]->(a:Approval)
WHERE a.id=l.current_approval_id
RETURN p,l,c,v,d,a,
 [(a)-[:APPROVES]->(ad:Draft) WHERE ad.id=d.id | ad.id],
 [(a)-[:BASED_ON]->(av:Verification) WHERE av.id=v.id | av.id],
 [(v)-[:SUPPORTED_BY]->(e:Evidence) | e.id],
 [(p)<-[:TO]-(prior:Outreach)
   WHERE prior.status IN ['dispatching','sent','unknown'] | prior.id]
