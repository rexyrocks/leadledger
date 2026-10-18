# Shared contracts 1.0.0

The root `schemas.json`, `openapi.json`, `examples.json` and `message-hash-vector.json` remain unchanged from main. The backend validates their exact shapes; JSON Schema is the source of truth. FastAPI's `/docs` renders the committed OpenAPI file.

## Ownership and module boundary

Kunal owns graph persistence, state, approvals, gate evaluation, send orchestration and HTTP endpoints. Shubhangi owns the real Extractor/Checker, DNS adapter, frontend and sender implementation. `leadledger/adapters.py` contains labelled fixture implementations so backend work is independently demoable. These are replacement adapters, not live LLM agents.

```python
class Agents:
    execution_mode = "live_llm"  # fixture adapter uses "fixture_replay"
    model_id = "your-configured-model"
    prompt_version = "checker-v1"

    def extract(self, context: dict) -> dict:
        # ExtractorInput -> ExtractionBatch
        ...

    def check(self, context: dict) -> dict:
        # CheckContext -> CheckerAssessment
        ...

def sender(envelope: dict) -> dict:
    # SendEnvelope -> SenderResult
    # No network calls or database writes in this log-only MVP.
    ...

def email_checker(person, evidence, now, lead_id) -> dict:
    # EmailChecks; live mode performs syntax + MX checks, never SMTP probing.
    ...
```

Inject them with `Manager(repo, agents=..., sender=..., email_checker=...)` and `create_app(manager)`. Agents receive no Repository or database connection. The Checker returns only its assessment; the Manager sets IDs, final status, expiry and state. Every supported claim must cite supplied evidence IDs, include a quote present in each cited snapshot, and match the current field value. All five fields must be supported. A quote is evidence of what the source says, not proof of its truth.

The sender runs inside the Manager's mutation lock after the final graph gate. It returns `status: "logged"`; only the backend commits `Outreach.status: "sent"`, the `Sent` lead state, and audit events. Do not make it call the send endpoint recursively. `SendReceipt` is the HTTP response; `SenderResult` is the internal return value.

## Wire rules

- Local base: `http://127.0.0.1:8000`; routes begin `/api`.
- JSON UTF-8, snake_case keys, timestamps in UTC **seconds**, stable string IDs.
- Required-but-unknown properties use `null`; lists use `[]`. Do not omit required properties.
- Additional fields are rejected except explicitly extensible graph properties, event payloads and error details.
- No top-level success wrapper. List response: `{ "items": [...], "total": 20 }`.
- Dates, model IDs and statuses come from the server, not frontend controls.
- `Approved` is qualification; `Approved for sending` requires human approval of a Draft.
- List/details return `current_verification_id`; select that report rather than assuming array order means latest.
- Fixtures have `execution_mode: "fixture_replay"`, `model_id: null`, `is_fixture: true`. For DNS fixtures, `mx: "fixture"` and `fixture_result` is the simulated DNS result. `mailbox_exists` remains `unknown`.

## Commands, retries and conflicts

Lead-changing POST bodies contain `command_id` (UUID v4 string) and `expected_version` (current `lead.version`). Generate a new UUID for each new action. Retry the **identical** body with the same UUID after a lost response. Completed commands replay the original stored response, even if the lead subsequently changes. Reusing a UUID for a changed action/body returns 409 `COMMAND_REUSED`.

Versions are opaque concurrency tokens: one request may record multiple events and advance the version more than once. Always use the returned/latest version; do not increment it in the frontend. Each event has a separate monotonically increasing per-lead sequence.

On 409 `VERSION_CONFLICT`, refresh the detail and have the user review it. A changed request needs a new command ID. On 409 `SEND_BLOCKED`, display `error.details.gate.reason_codes`; the backend records the block, so refresh the version. A green GET `/gate` response is advisory: POST `/send` always rechecks.

Two creation/batch exceptions have no client `expected_version`: `/extract` creates records (or returns existing records), and `/rechecks/scan` gets versions internally. Both still require command IDs. Extraction uses deterministic child-command IDs per candidate, so retries resume without repeating persisted discovery. It is not an all-or-nothing multi-lead transaction.

## Endpoint responses

| Method and route | Request schema | Success schema |
|---|---|---|
| GET `/api/health` | — | `Health` |
| GET `/api/sources` | — | `SourceList` |
| GET `/api/leads` | — | `LeadList` |
| GET `/api/leads/{lead_id}` | — | `LeadDetail` |
| POST `/api/extract` | `ExtractRequest` | `ExtractResponse` |
| POST `/api/leads/{lead_id}/verify` | `MutationRequest` | `LeadDetail` |
| POST `/api/leads/{lead_id}/draft` | `DraftRequest` | `LeadDetail` |
| POST `/api/leads/{lead_id}/approve` | `ApproveRequest` | `LeadDetail` |
| GET `/api/leads/{lead_id}/gate` | — | `GateDecision` |
| POST `/api/leads/{lead_id}/send` | `MutationRequest` | `SendReceipt` |
| POST `/api/leads/{lead_id}/opt-out` | `OptOutRequest` | `LeadDetail` |
| POST `/api/rechecks/scan` | `ScanRequest` | `ScanResponse` |
| GET `/api/outreach/{outreach_id}/why` | — | `ExplanationGraph` |
| POST `/api/outreach/{outreach_id}/outcome` | `OutcomeRequest` | `LeadDetail` |

Set both `subject` and `body_text` to null to request the default template; supply both strings to create a custom revision. Approval supplies current `draft_id`, `message_hash`, `expected_version`, `command_id`, and `actor` (`kunal` or `shubhangi`). Actor selection is demo attribution, not authentication. The backend obtains the verification/contact/policy versions itself.

Outcomes are `delivered`, `replied`, or `bounced`, always simulated. A late outcome can be logged after opt-out without reopening the lead.

## Message hash

Hash exactly these keys: `campaign_id`, `person_id`, `to_address`, `from_address`, `subject`, `body_text`, `mode`. Serialize with lexicographically sorted keys, no whitespace between keys/values, unescaped Unicode, no NaN, and UTF-8 encoding. Then SHA-256 to lowercase hex. Preserve message text exactly, including newlines. Use the committed hash vector as the interoperability test. Clients should submit the server-provided hash, not recompute approved content differently.

Any revision produces a new Draft, revokes previous approval and returns to `Awaiting outreach approval`. A send is bound to exact artifact IDs, not whichever approval is connected to the shared Campaign.

## Errors

```json
{"error":{"code":"SEND_BLOCKED","message":"The graph blocked this send.","details":{"gate":{"allowed":false,"reason_codes":["OPTED_OUT"]}}}}
```

The shortened gate above illustrates nesting; use the complete `GateDecision` shape in `examples.json` for mocks. 404: missing record. 409: state/version conflict, reused command, in-progress command, or blocked send. 422: invalid request. 503: unavailable graph/sender. 500: unexpected failure. No dependency failure permits sending.

## Explanation UI

Pass `nodes` and `edges` to Cytoscape as elements; IDs are stable application IDs. Click details come from `data.properties`. Use the selected Outreach ID, not the current Lead's latest report, to explain a historical send. Verification reports and the Draft preserve historical values; Person/Lead properties show current values. If `complete` is false, show the supplied incomplete-audit summary. The backend returns the scoped graph; do not traverse the shared Campaign to load unrelated approvals.

The frontend dev origin `http://localhost:5173` (or `127.0.0.1:5173`) is allowed. There is no public endpoint for raw reports, arbitrary state changes, or graph mutations.
