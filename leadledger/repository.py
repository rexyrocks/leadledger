"""FalkorDB only: no SQLite or in-memory fallback for graph decisions."""
import copy
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from .contracts import Problem, conflict

LABELS = {'Company','Person','Lead','Campaign','Evidence','Verification','Draft',
          'Approval','Outreach','Event','Command'}
RELS = {'HAS_CONTACT','HAS_LEAD','IN_CAMPAIGN','DISCOVERED_FROM','HAS_VERIFICATION',
        'HAS_DRAFT','HAS_APPROVAL','DUPLICATE_OF','SUPPORTED_BY','BASED_ON','APPROVES',
        'FOR_LEAD','TO','USES_DRAFT','HAS_EVENT','VERIFIED_BY','QUALIFIED_FOR',
        'AUTHORIZED_BY','SENT_AS'}


@dataclass
class Snapshot:
    nodes: dict = field(default_factory=dict)
    labels: dict = field(default_factory=dict)
    edges: dict = field(default_factory=dict)

    def get(self, ident, label=None):
        if ident not in self.nodes or (label and self.labels[ident] != label):
            raise Problem('NOT_FOUND', f'{label or "Record"} not found.', 404)
        return self.nodes[ident]

    def all(self, label):
        return [n for i,n in self.nodes.items() if self.labels[i] == label]

    def linked(self, source, relation):
        return [self.nodes[b] for a,r,b in self.edges.values()
                if a == source and r == relation]

    def has(self, source, relation, target):
        return (source,relation,target) in self.edges.values()


class Change:
    def __init__(self, snapshot):
        self.s = copy.deepcopy(snapshot)
        self.nodes = {}
        self.edges = {}
        self.guards = {}

    def put(self, label, props):
        assert label in LABELS
        ident = props['id']
        previous = self.s.nodes.get(ident, {})
        self.s.nodes[ident] = {**previous, **props}
        self.s.labels[ident] = label
        self.nodes[ident] = (label, self.s.nodes[ident])
        return self.s.nodes[ident]

    def link(self, source, relation, target):
        assert relation in RELS
        import hashlib
        ident = 'edge-' + hashlib.sha256(f'{source}|{relation}|{target}'.encode()).hexdigest()[:32]
        self.edges[ident] = (source,relation,target)
        self.s.edges[ident] = (source,relation,target)


class Repository:
    def __init__(self, graph, owner=None):
        self.graph = graph
        self.owner = owner

    @classmethod
    def connect(cls):
        name = os.getenv('FALKORDB_GRAPH','leadgraph_demo')
        if os.getenv('LEADLEDGER_DB','server') == 'embedded':
            from redislite.falkordb_client import FalkorDB
            path = Path(os.getenv('LEADLEDGER_DATA','work/leadledger.rdb')).resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            db = FalkorDB(str(path))
        else:
            from falkordb import FalkorDB
            db = FalkorDB(host=os.getenv('FALKORDB_HOST','127.0.0.1'),
                          port=int(os.getenv('FALKORDB_PORT','6379')),
                          password=os.getenv('FALKORDB_PASSWORD') or None,
                          socket_connect_timeout=5, socket_timeout=10)
        return cls(db.select_graph(name), db)

    def read(self, query, params=None):
        try:
            return self.graph.ro_query(query, params or {}, timeout=5000).result_set
        except Exception as exc:
            raise Problem('DEPENDENCY_UNAVAILABLE', 'FalkorDB could not answer the query.', 503) from exc

    def snapshot(self):
        s = Snapshot()
        for [node] in self.read('MATCH (n) RETURN n'):
            props = dict(node.properties)
            if 'id' not in props:
                raise Problem('DEPENDENCY_UNAVAILABLE','Graph contains an unrecognized record.',503)
            ident = props['id']
            if ident in s.nodes:
                raise Problem('DEPENDENCY_UNAVAILABLE','Graph contains duplicate application IDs.',503)
            s.nodes[ident] = props
            s.labels[ident] = node.labels[0]
        for a,r,i,b in self.read('MATCH (a)-[r]->(b) RETURN a.id, type(r), r.id, b.id'):
            if not i or i in s.edges:
                raise Problem('DEPENDENCY_UNAVAILABLE','Graph contains invalid relationship IDs.',503)
            s.edges[i] = (a,r,b)
        return s

    def commit(self, change):
        """Guard current versions and write state, artifacts, events and receipt in one query."""
        parts, params, aliases = [], {}, {}
        for i,(ident,ver) in enumerate(change.guards.items()):
            params.update({f'g{i}id':ident, f'g{i}v':ver})
            parts.append(f'MATCH (g{i}:Lead {{id:$g{i}id}}) WHERE g{i}.version=$g{i}v')
        aliases={ident:f'n{i}' for i,ident in enumerate(change.nodes)}
        for ident in {x for a,_,b in change.edges.values() for x in [a,b]} - aliases.keys():
            alias=f'n{len(aliases)}'; aliases[ident]=alias
            key=f'existing{len(aliases)}'; params[key]=ident
            # Labels come from the trusted snapshot, never from request strings.
            label=change.s.labels[ident]
            if label not in LABELS:
                raise Problem('INTERNAL_ERROR','Unrecognized graph label.',500)
            parts.append(f'MATCH ({alias}:{label} {{id:${key}}})')
        for i,(ident,(label,props)) in enumerate(change.nodes.items()):
            alias=aliases[ident]
            params.update({f'i{i}':ident, f'p{i}':props})
            parts.append(f'MERGE ({alias}:{label} {{id:$i{i}}}) SET {alias} += $p{i}')
        for i,(ident,(a,r,b)) in enumerate(change.edges.items()):
            params[f'e{i}']=ident
            parts.append(f'MERGE ({aliases[a]})-[:{r} {{id:$e{i}}}]->({aliases[b]})')
        parts.append('RETURN 1')
        try:
            rows=self.graph.query('\n'.join(parts), params, timeout=5000).result_set
        except Exception as exc:
            raise Problem('DEPENDENCY_UNAVAILABLE','Graph write failed; refresh before retrying.',503) from exc
        if len(rows) != 1:
            raise conflict()

    def query_file(self, name, params):
        query=(Path(__file__).parent/'queries'/f'{name}.cypher').read_text()
        return self.read(query, params)

    def ensure_graph(self):
        try:
            self.graph.query('RETURN 1', timeout=5000)
        except Exception as exc:
            raise Problem('DEPENDENCY_UNAVAILABLE','FalkorDB is not ready.',503) from exc

    def close(self):
        if self.owner and os.getenv('LEADLEDGER_DB') == 'embedded':
            self.owner.client.shutdown()
