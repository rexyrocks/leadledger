# Persistent judge deployment (AWS)

Prepared for Ubuntu 24.04 x86_64, a small CPU instance, and a retained encrypted gp3 disk. This is a deployment recipe, not evidence that an EC2 instance has been launched.

## Isolation and continuity

- FastAPI and embedded FalkorDB run as a non-root system service, listening only on `127.0.0.1:8123`.
- Database path: `/var/lib/leadledger/leadledger.rdb`. The existing graph must be restored before the app starts; this recipe does not silently seed over the audit history.
- Keep one API worker/process: the mutation lock is process-local.
- Cloudflare Tunnel is the only public ingress. Do not expose port 8123 or the database. Restrict SSH to the regional EC2 Instance Connect source range.
- A system service restarts after failure/reboot. Persistent storage is not a backup: retain the original Mac database and a verified migration backup.
- Judge actions explicitly use `fixture_replay`; existing historical Qwen reports retain their original provenance. No GPU or API key is needed for the hosted fixture demo.
- There is no silent fallback from failed Qwen inference to fixture output. A future live mode needs its own explicit deployment and availability checks.
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
