# Live Qwen workflow verification — 18 October 2026

The deployed workspace at https://leadledger.live/ui/ was exercised with the real Qwen relay and the existing synthetic `lead-19` (Zoya Malik at Signal Demo). This was an automated UI verification session, not independent human approval or a real outreach campaign.

## Observed workflow

1. Extraction against `seed-19` completed. The existing contact was reused; this was not a newly discovered real person.
2. Qwen Checker returned a passed report with verbatim source support for all five fields. The report recorded `live_llm`, the model ID and checker version. DNS/MX stayed explicitly simulated; mailbox existence remained unknown.
3. Qwen generated revision 1. Before approval, a simulated send was blocked with `WRONG_STATE`, `APPROVAL_INVALID` and `MESSAGE_CHANGED`.
4. After demo approval, Decision Lab showed all ten checks passing. Its opt-out hypothetical returned `OPTED_OUT` without changing the lead's saved version or approval.
5. A manual UI edit saved revision 2, revoked the earlier approval and returned the lead to `Awaiting outreach approval`. The revision was manually entered during automated testing; it is not another model generation.
6. After explicit reapproval of revision 2, a fresh gate allowed the log-only sender. The lead reached `Sent`, version 10.
7. The explanation endpoint returned `complete: true` for `outreach-8cee66d3b8474bf7953dde0b08aa37eb`; ten recorded events cover discovery, verification, drafting, blocked send, approvals, revision, allowed gate and logged send.

Reviewer IDs in the frozen shared contract are limited to `kunal` and `shubhangi`. These UI tests used `kunal` as demo attribution. That value is not authenticated identity or proof of independent human review. An attempted unsupported test attribution was rejected by contract validation and did not create an approval; no contract was changed.

## Scope and limits

- Real model inference was verified for extraction, checking and initial drafting; the source text, contacts and DNS results remain synthetic fixtures.
- No email was sent. Health readback reported `graph: connected`, `execution_mode: live_llm` and `sender_mode: log_only`.
- Readiness readback reported `ready: true`. This is a point-in-time check, not an uptime guarantee.
- Hosting still depends on the Mac, its Cloudflare tunnel and the separate Colab GPU session.
- The submitted YouTube walkthrough remains the earlier labelled fixture demo; it was not replaced with a live inference recording.
- The final suite passed all 86 tests against embedded FalkorDB. All 24 shared examples and the message-hash vector passed. JavaScript syntax checks passed and frozen shared contract files were unchanged.

The local verification bundle contains API readbacks and screenshots under `outputs/leadledger-live-demo/` in the parent workspace. It is not a public monitoring service.
