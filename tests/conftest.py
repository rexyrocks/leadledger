import os
import sys
from importlib import import_module
from uuid import uuid4
import pytest
from leadledger.manager import Manager
from leadledger.repository import Repository


def pytest_addoption(parser):
    parser.addoption('--graph-backend',choices=['auto','embedded','server'],
        default=os.getenv('LEADLEDGER_TEST_DB','auto'),
        help='auto: embedded on macOS/Linux; server: existing FalkorDB over TCP (Windows supported)')


def backend_choice(requested,platform):
    if requested not in {'auto','embedded','server'}:
        raise ValueError('Choose auto, embedded or server for LEADLEDGER_TEST_DB.')
    if requested=='server': return 'server'
    if platform not in {'darwin','linux'}: return 'unavailable'
    return 'embedded'


def pytest_report_header(config):
    return 'FalkorDB test backend: '+config.getoption('--graph-backend')


@pytest.fixture(scope='session')
def engine(tmp_path_factory,pytestconfig):
    """Real graph engine; never shut down a user-owned TCP server."""
    requested=pytestconfig.getoption('--graph-backend')
    try: mode=backend_choice(requested,sys.platform)
    except ValueError as exc: pytest.exit(str(exc),returncode=4)
    hint=('Graph tests did not run. On Windows use Docker Desktop (Linux containers), '
          'docker compose up -d --wait, then python -m pytest --graph-backend=server. '
          'On macOS/Linux install .[local,test] or select server mode.')
    if mode=='unavailable':
        if requested=='embedded': pytest.exit('Embedded FalkorDB does not support this platform. '+hint,returncode=4)
        pytest.skip(hint)
    if mode=='server':
        from falkordb import FalkorDB
        try:
            db=FalkorDB(host=os.getenv('FALKORDB_TEST_HOST','127.0.0.1'),
                port=int(os.getenv('FALKORDB_TEST_PORT','6379')),
                password=os.getenv('FALKORDB_TEST_PASSWORD') or None,
                socket_connect_timeout=3,socket_timeout=10)
            db.connection.ping()
            db.execute_command('GRAPH.LIST')  # Plain Redis is not a graph-test substitute.
        except Exception:
            pytest.exit('Cannot reach the FalkorDB test server. Check Docker and FALKORDB_TEST_HOST/PORT/PASSWORD. '
                        'No graph tests were validated.',returncode=4)
        try: yield db
        finally: db.connection.close()  # Never SHUTDOWN or FLUSHDB an external server.
    else:
        try:
            FalkorDB=import_module('redislite.falkordb_client').FalkorDB
        except ImportError:
            if requested=='embedded': pytest.exit('Embedded test dependency is missing. '+hint,returncode=4)
            pytest.skip(hint)
        path=tmp_path_factory.mktemp('falkordb')/'test.rdb'
        try: db=FalkorDB(str(path))
        except Exception:
            pytest.exit('Embedded FalkorDB could not start. Check the native runtime or use --graph-backend=server.',returncode=4)
        try: yield db
        finally: db.client.shutdown()


@pytest.fixture
def m(engine):
    repo=Repository(engine.select_graph('test_'+uuid4().hex))
    manager=Manager(repo,clock=lambda:1800000000)
    try:
        manager.bootstrap()
        yield manager
    finally:
        repo.graph.delete()  # Deletes only this fixture's random test_<uuid> graph.


@pytest.fixture
def discovered(m):
    m.ingest(m.candidates['seed-01'],str(uuid4()))
    return m


@pytest.fixture
def approved(discovered):
    from leadledger.seed import qualify
    qualify(discovered,'lead-01')
    return discovered
