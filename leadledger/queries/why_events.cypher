MATCH event_path=(artifact)-[:HAS_EVENT]->(event:Event)
WHERE artifact.id IN $artifact_ids
RETURN event_path
ORDER BY event.at,event.sequence
