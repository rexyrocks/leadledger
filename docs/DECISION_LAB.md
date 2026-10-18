# Decision Lab and demo guide

Open a lead at [leadledger.live/ui/](https://leadledger.live/ui/) and select **Decision Lab**.

The panel reads the same `gate.cypher` query used by sending, shows the actual parameters, returned policy facts, row count and query duration, and displays ten policy checks. Cypher retrieves the relationships; deterministic Python evaluates the policy. A preview is advisory: the backend still reads current graph facts and evaluates policy under the mutation lock when sending.

## Read-only counterfactuals

Four fixed scenarios run the **same policy evaluator**, each against a deep copy of the facts returned by FalkorDB:

- Person opts out.
- Person is suppressed.
- Current verification expires.
- Saved message content changes while retaining the approved hash.

No arbitrary Cypher or user-defined overrides are accepted. No graph record, command receipt, approval, version or event is written. The result identifies newly introduced blocking reasons; a lead already blocked can remain blocked for other reasons. If there is no current verification or draft, the corresponding scenario is unavailable. These cases explain policy behavior, not predicted business outcomes.

## Runtime status

The Qwen badge now probes the configured model connection, rather than equating configuration with availability. Relay mode checks `/health`; direct OpenAI mode checks `/models`. The probe uses a three-second request timeout, never enqueues inference and never returns credentials. Results are cached for five seconds. Click **Refresh** to check again after reconnecting Colab (a fresh cached result may remain for up to five seconds).

A ready probe demonstrates connection readiness, not model quality or a completed generation. Fixture mode remains explicit. A missing model does not silently enable fixture replay.

## Demo guide

**Demo guide** describes a six-step workflow and selects existing examples for an unreviewed lead, a previous-campaign block, or conflicting evidence. It does not reset the shared campaign or execute actions. If no unreviewed lead remains, it says so.

The public demo still runs on the host Mac through a named Cloudflare tunnel, with Qwen on a separate Colab runtime. Keep the host and tunnel running. This upgrade does not move hosting or guarantee Colab uptime. Current records and audit history are preserved.

## UI helper endpoints

These read-only helpers supplement the frozen shared contracts; the four contract files remain unchanged:

| GET endpoint | Purpose |
| --- | --- |
| `/ui-api/leads/{lead_id}/decision` | Current gate, policy checklist, query metadata, selected graph facts and bounded counterfactuals |
| `/ui-api/runtime` | Configured mode and cached connection readiness |
| `/ui-api/openapi.json` | Browser-only copy of OpenAPI with a relative server URL, so Swagger uses the current deployment |

`/openapi.json` still returns the frozen contract. `/docs` uses the browser copy. A graph error does not produce a simulated decision; it fails with the normal dependency error.

## Validation

86 tests passed against real embedded FalkorDB after the upgrade. New coverage includes no-write counterfactuals, allowed baseline becoming blocked under each scenario, missing artifact handling, cross-campaign outreach, real opt-out after a preview, runtime probe caching and separation of browser docs from the frozen contract. All 24 contract examples and the message-hash vector passed.

Browser checks exercised all four scenarios, the executed query and graph facts, an allowed baseline after explicit demo approval, and guided navigation. Approval in these tests was an automated synthetic UI action, not independent human review.
