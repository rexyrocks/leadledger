# Integrated agents and review workspace

Local UI: `http://127.0.0.1:8123/ui/`. API documentation remains at `/docs`. The frozen OpenAPI, schemas, examples and message-hash vector are unchanged.

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[local,test]'
python scripts/run_workspace.py --agents fixture --seed
```

The explicit seed option creates the 20 synthetic lead records, 18 canonical people and historical campaign only when the graph is empty. Existing history is preserved. Fixture seed reports and simulated DNS remain labelled even if later reviews use Qwen. Local default storage is `work/leadledger.rdb`, graph `leadledger_workspace`. The server binds only to loopback, uses one worker and has no production authentication.

Windows: use the existing server setup from BACKEND.md, install `.[test]`, set `LEADLEDGER_DB=server`, then run the same workspace script. No Docker or database is needed for frontend mock work against `examples.json`. Actual Windows and Docker execution remain unverified by this integration.

## Use our Qwen

The Mac calls the existing private Cloudflare Lounge relay. It does not expose the Colab model port. Its key stays in a server-side environment variable or private key file; it is never included in the frontend, API responses or git.

```bash
export QWEN_TRANSPORT=relay
export QWEN_BASE_URL=https://qwen-lounge.piyochoudhary.workers.dev
export QWEN_API_KEY_FILE=/absolute/path/to/private/key-file
export QWEN_MODEL_ID=Qwen3.8-27B-Q4_K_M
python scripts/run_workspace.py --agents qwen --seed
```

Alternatively, use a locally reachable llama.cpp server with `QWEN_TRANSPORT=openai` and `QWEN_BASE_URL=http://127.0.0.1:8766/v1`. The supplied model name is deployment configuration; verify it against the loaded runtime. HTTPS is required for non-loopback addresses. Redirects are rejected to avoid leaking keys. Context is bounded for the current 4K deployment. Thinking is disabled and each model task requests a JSON object. The relay supports a single active task; using Lounge chat at the same time may return a busy error. No paid API fallback is enabled.

Colab must be connected, the model startup cell complete, and the hidden-key Lounge relay cell running. Colab inactivity/session limits can disconnect it. AWS migration is separate and was blocked by g6.xlarge capacity across all three Sydney availability zones; this workspace uses Colab.

## What the adapters do

- **Extractor:** Qwen reads one permitted snapshot at a time and returns five grounded fields. The wrapper rejects unexpected fields and values absent from the source, derives record/campaign IDs from trusted input, and binds citations to the supplied snapshot. No browsing or scraping occurs. An incomplete record is skipped rather than inventing a mandatory contact field; source 14 intentionally has no email. Fixture-domain metadata is a synthetic namespace, not proof of a real company domain. All 20 seeded scenarios remain available independently.
- **Checker:** Qwen reviews exact contact fields and supplied snapshots for support, conflicts and missing information. The wrapper constructs evidence IDs and exact quotes from those snapshots, validates the report, and gives it to Manager. It receives no database connection or send capability. A quote supports what a source says, not its truth. Manager independently validates all citations, freshness, campaign fit and email results before determining state.
- **Email checks:** syntax plus bounded MX lookup for non-fixture evidence, with explicit absent, null-MX, NXDOMAIN and timeout outcomes. Synthetic evidence uses the existing simulated DNS scenarios and performs no DNS request. Mailbox existence is always unknown. No SMTP probing.
- **Drafting:** Qwen proposes subject/body only when a verified contact is eligible. Generation runs outside the mutation lock; Manager rechecks current version, contact and verification before saving. The original request ID still replays the same saved result. Every generated revision starts at Awaiting outreach approval. Draft events record generator and model ID within the existing extensible event payload.
- **Sender:** reuses the existing deterministic log-only function. It validates the final gate decision and exact message hash, performs no network/disk side effect, and returns its simulated receipt to Manager. Only Manager writes the outcome and audit chain.

Qwen mode never silently switches to fixture inference. Invalid/unsupported model reports fail closed into review; extraction/drafting errors are shown without accepting model output.

## Review interface

Search/filter leads; inspect synthetic evidence and captured hashes; run verification; edit/save message revisions; approve the exact server draft in an explicit human-review dialog; inspect the current gate; attempt simulated sends (including blocked demonstrations); log simulated delivery/reply/bounce outcomes; opt out; and scan for stale leads.

The UI uses server-supplied versions and message hashes. New commands receive UUIDs. After an uncertain network response, Retry the same action reuses the identical command body and ID. A version conflict refreshes current records for review. Unsaved edits disable approval and simulated send. Approval does not send; sending checks the gate again under the backend lock.

The Cytoscape view consumes the recorded graph for the selected exact Outreach ID. It includes clickable node facts and a textual record list. History events can be toggled into the graph; the default view focuses on the core evidence and approval chain. Incomplete audit chains display the backend's incomplete summary rather than inferred nodes. Cytoscape 3.34.4 is vendored from its official npm package with its MIT license, so this view needs no CDN. Visual layout was informed by the Watermelon Astrix audit dashboard; implementation uses the repository's vanilla HTML/JS stack.

## Validation

```bash
python -m pytest
python scripts/check_contracts.py
node --check leadledger/web/app.js
```

Tests include live-shaped adapter stubs (not actual model inference), evidence fabrication, invalid JSON, offline relay behaviour, synthetic-vs-live DNS, model-draft/opt-out races, idempotent draft replay, and local static/API integration. See VERIFICATION.md for live observations and known limits. No real emails are sent.
