# Backend verification

Checked locally on October 17, 2026, on macOS ARM64 / Python 3.13, using the actual FalkorDB engine bundled in FalkorDBLite 0.10.0 and the official FalkorDB Python client 1.8.0.

- **47 tests passed** against isolated real graphs, including every opt-out stage, stale versions, expiry, duplicate identity, cross-campaign contact, wrong approval binding, changed messages, malformed Checker output, invented citations, concurrent retries, interrupted work and incomplete audit paths.
- All **24 shared contract examples** and the message-hash test vector passed validation.
- Editable package installation succeeded.
- Running HTTP demo completed discovery/check/draft/human approval/log-only send, returned a complete **13-node / 25-edge** explanation subgraph, and blocked opted-out and previously contacted leads.
- The API and embedded database were stopped cleanly and restarted. The same Outreach ID and complete explanation remained available; repeating the demo reused that send.
- Seed loading produced twenty active Leads for eighteen canonical people and one additional historical-campaign Lead.
- No real outreach was sent. Agent execution and DNS results were labelled fixture replay/simulated.

One upstream Starlette warning notes that its httpx TestClient integration is deprecated. It did not cause a failure.

Not verified: live LLM/provider calls, live DNS deliverability, frontend visualization, Docker image execution/container recreation, hosted deployment, multiple application processes, or production authentication. Docker's development image remains configurable; pin a tested immutable digest before using that path for the final demo.

Reproduce with `python -m pytest`, `python scripts/check_contracts.py`, and the running-API `python scripts/demo.py`. See [BACKEND.md](BACKEND.md) for setup and [CONTRACTS.md](CONTRACTS.md) for the teammate handoff.

## Windows test compatibility — October 18, 2026

The original graph-test fixture unconditionally imported `redislite`, which is unavailable on native Windows. Tests now support an existing FalkorDB TCP server with `--graph-backend=server`. Installing the `local` extra on Windows no longer attempts the unsupported native dependency. Default auto mode reports explicit skips when an embedded runtime is unavailable; skipped graph tests are not reported as validated backend behavior.

- **54 tests passed in server mode**, with every attempted `redislite` import deliberately blocked in the test process. The real TCP engine was FalkorDB 4.18.3 running locally on macOS, reached through the same official Python TCP client used with Docker.
- **54 tests passed in embedded mode**; all 24 shared examples and the hash vector still passed.
- A missing-embedded-dependency check produced 8 passes and 1 explicit skip for the selected representative tests, rather than import errors.
- Explicit server mode with an unavailable server produced one setup message and exit code 4; no graph tests were treated as passed.
- After the TCP suite, the external server remained running and its disposable test graphs had been removed.

Windows PowerShell setup is documented in [BACKEND.md](BACKEND.md#windows-powershell-use-docker-not-falkordblite). Actual Windows execution and Docker Desktop/container startup remain unverified on this macOS host. This change fixes the cross-platform test-database selection; it is not a claim that frontend or live-agent testing has been completed.
