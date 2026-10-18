"""Explicit mode selection; offline Qwen never silently becomes fixture replay."""
import os
from .manager import Manager
from .repository import Repository
from .email_checks import EmailChecker


def configured_manager():
    mode=os.getenv('LEADLEDGER_AGENTS','fixture')
    if mode not in {'fixture','qwen'}: raise ValueError('LEADLEDGER_AGENTS must be fixture or qwen.')
    agents=None
    if mode=='qwen':
        from .qwen import QwenAgents,QwenClient
        agents=QwenAgents(QwenClient.from_env())
    repo=Repository.connect()
    try:
        manager=Manager(repo,agents=agents,drafter=agents.draft if agents else None)
        manager.email_checker=EmailChecker(manager.dns_scenarios)
        return manager
    except Exception:
        repo.close()
        raise
