import os
from uuid import uuid4
import pytest
from leadledger.manager import Manager
from leadledger.repository import Repository
from leadledger.seed import command


@pytest.fixture(scope='session')
def engine(tmp_path_factory):
    """Actual embedded FalkorDB, shared process but isolated graphs per test."""
    from redislite.falkordb_client import FalkorDB
    path=tmp_path_factory.mktemp('falkordb')/'test.rdb'
    db=FalkorDB(str(path))
    yield db
    db.client.shutdown()


@pytest.fixture
def m(engine):
    repo=Repository(engine.select_graph('test_'+uuid4().hex))
    manager=Manager(repo,clock=lambda:1800000000)
    manager.bootstrap()
    yield manager
    repo.graph.delete()


@pytest.fixture
def discovered(m):
    m.ingest(m.candidates['seed-01'],str(uuid4()))
    return m


@pytest.fixture
def approved(discovered):
    from leadledger.seed import qualify
    qualify(discovered,'lead-01')
    return discovered
