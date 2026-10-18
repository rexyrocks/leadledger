"""Local review UI. Never enables network email or binds a public interface."""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--agents',choices=['fixture','qwen'],default='fixture')
    parser.add_argument('--seed',action='store_true',help='Seed labelled synthetic scenarios only if this graph is empty')
    parser.add_argument('--port',type=int,default=8123)
    args=parser.parse_args()
    os.environ.setdefault('LEADLEDGER_DB','embedded')
    os.environ.setdefault('FALKORDB_GRAPH','leadledger_workspace')
    os.environ['LEADLEDGER_AGENTS']=args.agents
    if args.seed:
        from leadledger.repository import Repository
        from leadledger.manager import Manager
        from leadledger.seed import seed
        repo=Repository.connect()
        try:
            manager=Manager(repo); manager.bootstrap()
            if not manager.leads()['total']:
                print('Loading synthetic scenarios with labelled fixture reports:',seed(manager),flush=True)
            else: print('Existing graph preserved; no reseeding.',flush=True)
        finally: repo.close()
    import uvicorn
    print(f'LeadLedger: http://127.0.0.1:{args.port}/ui/ | agents={args.agents} | log-only sender',flush=True)
    uvicorn.run('leadledger.api:app',host='127.0.0.1',port=args.port,workers=1)


if __name__=='__main__': main()
