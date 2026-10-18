MATCH (p:Person)-[:HAS_LEAD]->(l:Lead)-[:IN_CAMPAIGN]->(c:Campaign {id:$campaign_id})
OPTIONAL MATCH (l)-[:HAS_VERIFICATION]->(v:Verification)
WHERE v.id=l.current_verification_id
WITH p,l,v
WHERE l.state IN ['Approved','Awaiting outreach approval','Approved for sending']
AND (v IS NULL OR coalesce(v.valid_until,0)<=$now
     OR coalesce(v.contact_version,-1)<>p.contact_version)
RETURN l.id,l.version
ORDER BY l.id
