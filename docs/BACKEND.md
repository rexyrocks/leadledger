# Kunal's backend

Run commands from the repository root. Python 3.12+ is required; the verified local runtime is Python 3.13 on macOS ARM64. Run exactly one API worker and one application process per graph. The global lock is deliberately process-local; multiple API workers and external graph writers are outside this MVP's guarantees.

## Docker setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
docker compose up -d
python -m leadledger.seed
python -m uvicorn leadledger.api:app --host 127.0.0.1 --port 8000 --workers 1
```

Open `http://127.0.0.1:8000/docs`. FalkorDB Browser is at `http://127.0.0.1:3000`. The compose service exposes only localhost ports and explicitly stores AOF files in a named `/data` volume. The compose file is provided but could not be tested here because Docker is unavailable. Set `FALKORDB_IMAGE` to a tested immutable image digest before the final Docker demo; `latest` is only a development default.

## Windows (PowerShell): use Docker, not FalkorDBLite

Native Windows Python can use the normal FalkorDB TCP client. It does **not** need `redislite` or the `local` extra. Run Docker Desktop with Linux containers; its WSL 2 backend is a supported Windows setup. Install prerequisites using [Docker's Windows instructions](https://docs.docker.com/desktop/setup/install/windows-install/).

From the repository root, after pulling the backend branch's compatibility fix:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
docker compose up -d --wait
.\.venv\Scripts\python.exe -m pytest --graph-backend=server
.\.venv\Scripts\python.exe scripts/check_contracts.py
```

The commands invoke the virtual environment directly, so PowerShell activation policy does not need to change. Python 3.12+ is required. If this checkout already has an environment, reuse it. `falkordblite==0.10.0` is only an embedded macOS/Linux dependency; the `local` extra now excludes unsupported Windows installs.

To run the demo backend on Windows, in the same repository:

```powershell
$env:LEADLEDGER_DB = "server"
.\.venv\Scripts\python.exe -m leadledger.seed
.\.venv\Scripts\python.exe -m uvicorn leadledger.api:app --host 127.0.0.1 --port 8000 --workers 1
```

Seed once, then omit the seed command on later starts. In a second PowerShell terminal, run `.\.venv\Scripts\python.exe scripts/demo.py`. Alternatively run the Linux setup wholly inside WSL2 with a Linux Python environment; do not reuse the Windows `.venv` there.

## Embedded alternative — macOS/Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[local,test]'
export LEADLEDGER_DB=embedded
python -m leadledger.seed
python -m uvicorn leadledger.api:app --host 127.0.0.1 --port 8000 --workers 1
```

FalkorDBLite starts a real FalkorDB engine through a local Unix socket; it is not an in-memory substitute or mock database. On macOS its native module requires the Homebrew `libomp` runtime. Docker Browser is not included in embedded mode. Data is stored at `work/leadledger.rdb`; override with `LEADLEDGER_DATA`. Stop the API cleanly before another process opens the same embedded database.

Source execution is supported from an editable checkout: the wire-contract JSON files live in the repository root. Packaging an isolated wheel is not a supported deployment path yet.

## Demo

With the server running, in another terminal:

```bash
source .venv/bin/activate
python scripts/demo.py
```

This performs the happy path, retrieves its actual explanation graph, scans stale work and attempts blocked sends for opt-out and cross-campaign contact. Repeating the script reuses the historical happy-path send rather than contacting again. No LLM key or external email service is used. The backend returns `fixture_replay` and `simulated: true` explicitly.

The startup scan and 60-second scheduler automatically flag expired verifications. This means `lead-02` may already be Stale before clicking the manual scan; its timeline contains the recorded transition. Freshness is also checked inside every send gate.

The seed command creates twenty active Lead records for eighteen canonical people, plus one historical-campaign Lead. It refuses to seed a nonempty graph. To get a fresh demo while preserving history, set another `FALKORDB_GRAPH` name. There is no reset endpoint. Do not run tests or seed loaders against an active application graph.

## Verification

For an existing Docker/server database (all client platforms, including Windows):

```bash
python -m pip install -e '.[test]'
docker compose up -d --wait
python -m pytest --graph-backend=server
python scripts/check_contracts.py
```

For the embedded engine (macOS/Linux with the optional native runtime):

```bash
python scripts/check_contracts.py
python -m pip install -e '.[local,test]'
python -m pytest --graph-backend=embedded
```

Without a flag, `auto` uses embedded FalkorDB on macOS/Linux if installed. On unsupported platforms or when that optional dependency is missing, graph-dependent tests are explicitly **skipped** with setup instructions; schema-only tests still run. Skips do not mean the backend passed. Select `server` explicitly for a complete Windows run. Explicit server mode fails with a single setup message if the server is unavailable or is plain Redis; it never silently substitutes fixtures for the graph engine.

Server tests default to `127.0.0.1:6379`. Override with `FALKORDB_TEST_HOST`, `FALKORDB_TEST_PORT`, and optional `FALKORDB_TEST_PASSWORD`. Set `LEADLEDGER_TEST_DB=server` instead of the CLI flag if preferred. These test variables are deliberately separate from application database settings.

Tests create unique `test_<uuid>` graph names and delete only those disposable graphs. They never use `FALKORDB_GRAPH`, flush the database, or shut down an external server. The embedded path uses a separate temporary database process. They run actual Cypher for stale detection, cross-campaign contact checks, policy blocking, optimistic version guards and historical path retrieval. Live provider credentials, LLM calls and public email delivery are not tested. Synthetic syntax/DNS checks deliberately do not establish real deliverability.

## Integration boundaries

See [CONTRACTS.md](CONTRACTS.md). `Manager` owns all writes. `Repository.commit` writes each state change, artifact, event and completed-command receipt in one parameterized graph query with expected-version predicates. No HTTP client can submit arbitrary Cypher or mark a report passed. Agent calls run outside the global mutation lock; their results are committed only if the captured versions still match.

Fixture Extractor/Checker, email checks, message template and sender are small stand-ins so the backend can be demonstrated independently. Shubhangi replaces these adapters and owns the frontend; no application UI or live LLM integration is claimed on this branch.

Invalid or unavailable Checker output records a Needs review result. A model's unsupported rejection claim also goes to review; deterministic invalid address/domain checks can reject automatically. There is no user-facing evidence-refresh endpoint yet, so a stale bundled snapshot remains unqualified until updated evidence is ingested through a future trusted adapter. A rejected Lead cannot be reopened with the same evidence. These conservative limits prevent reviewer approval from bypassing failed evidence.

This local demo has no production authentication. Keep it on loopback. There is no SMTP transport, third agent, MCP server, or hosted deployment on this branch.
