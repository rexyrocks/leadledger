# Persistent deployment verification — 19 October 2026

## What changed

LeadLedger's app and embedded FalkorDB moved from the Mac to a Sydney AWS CPU host. The existing named Cloudflare Tunnel now connects to that host. Qwen uses a private Cloudflare Workers AI relay, rather than a Colab GPU session. The original Mac database and independent migration backups remain available for rollback; the Mac app and connector are stopped.

Only inference has a free allowance. AWS hosting consumes credits or incurs charges separately. The approved server has an absolute automatic stop on 17 November 2026 at 16:52:22 UTC. Retained storage continues to incur charges after stop.

## Evidence collected

- 86 backend tests passed on the actual Ubuntu AWS host using the tested dependency versions. All 24 shared contract examples and the message-hash check passed locally; shared contracts were not modified.
- The final graph backup's SHA-256 matched after transfer: `d258976c308c3dd50e2b61d21a5f5c6763bfddbd4c7c2f56a50489d734ff75b7`.
- AWS restore validation matched 786 nodes, 363 relationships, all 21 lead versions (20 current campaign records plus one historical lead), all outreach IDs and 105 events before serving traffic. No fresh seed replaced the history.
- Public health reported `graph: connected`, `execution_mode: live_llm`, model `@cf/qwen/qwen3.8-27b` and `sender_mode: log_only` after cutover.
- The public API returned 20 current-campaign leads. Zoya's existing outreach explanation remained complete. Decision Lab remained read-only and blocked the previously contacted Kabir record with `ALREADY_CONTACTED`.
- A real Qwen Extractor call from the AWS host returned one schema-valid, source-grounded synthetic candidate in 3.92 seconds. This test did not write to the campaign graph.
- After a full EC2 reboot, the public app, connected graph and Qwen readiness returned automatically. All 20 public lead versions matched their pre-reboot values, and the existing outreach explanation remained complete.

## Model and relay tests

Six direct hosted-model calls passed: one complete extraction, missing-email extraction returning no candidate, a supported verification, conflicting-role review, missing-email review and drafting that still required approval. These ran on a separate disposable graph. Combined reported usage was about 200.1 neurons; latency ranged from 3.65 to 88.61 seconds. A single fast response is not a latency guarantee.

The deployed private relay also passed a real extraction, with anonymous access rejected and persistent budget accounting observed. Its 19 automated tests passed, covering request bounds, fixed inference settings, budget persistence and UTC reset, failed-request reservation, cancellation, concurrent jobs and authentication boundaries.

The relay reserves usage before inference and retains the reservation if actual usage is unknown. Its 9,000-neuron daily guard is below the account's 10,000-neuron free allowance; other account workloads can consume that allowance too. Exhaustion or provider failure returns an explicit error. There is no paid inference upgrade or silent fixture fallback.

## Scope and limitations

The model is advisory. Approval binding, idempotency, version checks and the final deterministic send gate remain in FalkorDB-backed application logic. Contacts, source snapshots and DNS scenarios are synthetic; all sends are log-only. Historical fixture and Qwen reports retain their original labels and provenance.

The demo's reviewer labels are not production authentication. This is a public synthetic hackathon workspace, not a production outreach service. Persistent hosting removes session/sleep dependence; it does not guarantee an outage-free provider, unlimited inference or perpetual free hosting.
