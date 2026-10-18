# Persistent judge deployment (AWS)

Deployed on 19 October 2026 (IST): Ubuntu 24.04 x86_64, one Sydney t3.small CPU instance, and a retained encrypted 20 GiB gp3 disk. The bootstrap script remains the conservative fixture-mode starting recipe; the live host uses the explicit managed-Qwen configuration below.

## Live deployment

- Public dashboard: https://leadledger.live/ui/
- FastAPI, embedded FalkorDB and the named tunnel run as restartable system services on AWS. The Mac application and connector are stopped.
- Managed inference: `@cf/qwen/qwen3.8-27b` through the private Qwen Lounge relay using its Workers AI binding. The CPU instance does not load the model weights.
- The existing relay access key is stored outside the checkout, in `/etc/leadledger-qwen.key`, readable only by root and the application group. No key is published in source or browser responses.
- Free AI guard: 9,000 neurons per UTC day, stored in a SQLite Durable Object. This is below the account's 10,000-neuron free allowance, which other account workloads may also consume. Exhaustion fails closed; no paid-plan upgrade or provider fallback was enabled.
- Approved hosting estimate: about $25/month including the instance, disk and public IPv4, before taxes or unusual traffic. Eligible AWS credits apply; this is not free hosting indefinitely.
- Absolute automatic stop: **2026-11-17 16:52:22 UTC**. A stopped server cannot serve the demo. Retained disk still costs about $2/month; the stop timer is not an account-wide billing cap.
- Synthetic data and log-only sending remain unchanged. Reviewer names are demo attribution, not production authentication.

The deployment checks and bounded live model tests are recorded in [migration verification](../../docs/PERSISTENT_DEPLOYMENT_2026-10-19.md).

## Isolation and continuity

- FastAPI and embedded FalkorDB run as a non-root system service, listening only on `127.0.0.1:8123`.
- Database path: `/var/lib/leadledger/leadledger.rdb`. The existing graph must be restored before the app starts; this recipe does not silently seed over the audit history.
- Keep one API worker/process: the mutation lock is process-local.
- Cloudflare Tunnel is the only public ingress. Do not expose port 8123 or the database. Restrict SSH to the regional EC2 Instance Connect source range.
- A system service restarts after failure/reboot. Persistent storage is not a backup: retain the original Mac database and a verified migration backup.
- The bootstrap defaults to `fixture_replay`; the live deployment explicitly uses `live_llm`. Existing historical reports retain their original provenance.
- There is no silent fallback from failed Qwen inference to fixture output. The live mode checks provider readiness and reports unavailable inference explicitly.
- Public demo reviewer names remain attribution, not production authentication. Use synthetic data only; sender remains log-only.

## Migration checklist

1. Verify AWS credits, selected service eligibility and running/storage charges. Obtain approval for the selected ongoing cost and any tunnel credential transfer before launching.
2. Launch one Ubuntu 24.04 x86_64 CPU instance with encrypted storage and IMDSv2 required. Use standard CPU credits to avoid surplus CPU credit charges. Keep database disk on instance termination.
3. Run `bootstrap.sh` as root (or supply as EC2 user data). It pins the reviewed application revision and leaves the service stopped.
4. Save a consistent snapshot on the source database; copy it to an independent backup and compute SHA-256. Transfer only that snapshot, not the Mac-specific `.settings` file. Verify checksum on AWS; install as `leadledger:leadledger`, mode 0640.
5. Start `leadledger.service`; verify graph health, all 20 lead IDs/versions, outreach IDs, event counts and complete explanation chains. If the embedded RDB format cannot be loaded, do not overwrite the source or cut over.
6. Test fixture extraction/checking/drafting and approval/edit/block/log-only workflow against a separate disposable graph before changing the public route. Test restart persistence.
7. Transfer only this application's existing tunnel connector credential (not the Cloudflare account certificate/API token). Confirm this new destination first. Keep credentials outside the repository/user data and readable only by the connector service.
8. Stop the old connector before starting the AWS connector for the same tunnel. Two different writable application copies must not receive load-balanced production traffic. Retain the old app and database for rollback.
9. Verify `https://leadledger.live/ui/`, `/api/health`, Decision Lab and browser docs from the public route, then stop the old Mac app. Never claim the cutover succeeded based only on EC2 status.
10. Configure an agreed absolute stop date and billing alerts. AWS budgets alert; they are not a hard spending cap. Stopping the VM still leaves retained storage charges.

## Service operations

```sh
sudo systemctl status leadledger
sudo journalctl -u leadledger -n 80 --no-pager
sudo systemctl restart leadledger
curl --fail http://127.0.0.1:8123/api/health
```

Stop gracefully before copying a destination database for backup. Do not delete either source database until migration, readback and restart persistence have been verified.

## Explicit managed inference configuration

The live environment file adds these values to the database settings above:

```dotenv
LEADLEDGER_AGENTS=qwen
QWEN_TRANSPORT=relay
QWEN_BASE_URL=https://qwen-lounge.piyochoudhary.workers.dev
QWEN_MODEL_ID=@cf/qwen/qwen3.8-27b
QWEN_API_KEY_FILE=/etc/leadledger-qwen.key
QWEN_TIMEOUT=120
```

The systemd override clears the fixture-mode `ExecStart` and replaces it with `scripts/run_workspace.py --agents qwen --port 8123` using the existing application virtual environment. It does not use `--seed` during migration. Protect the environment and key files with owner root, group leadledger and mode 0640. Never put the actual key in this document, EC2 user data, shell history or the repository.
