#!/usr/bin/env bash
# Ubuntu 24.04 x86_64. No credentials belong in EC2 user data.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3 python3-venv git curl ca-certificates ec2-instance-connect
id leadledger >/dev/null 2>&1 || useradd --system --create-home --home-dir /opt/leadledger --shell /usr/sbin/nologin leadledger
install -d -o leadledger -g leadledger -m 0750 /opt/leadledger /var/lib/leadledger /var/backups/leadledger
if [ ! -d /opt/leadledger/app/.git ]; then
  runuser -u leadledger -- git clone https://github.com/rexyrocks/leadledger.git /opt/leadledger/app
fi
# Deploy the reviewed revision, never an unattended git pull on restart.
runuser -u leadledger -- git -C /opt/leadledger/app checkout dbbca2a
runuser -u leadledger -- python3 -m venv /opt/leadledger/venv
runuser -u leadledger -- /opt/leadledger/venv/bin/pip install '/opt/leadledger/app[local]'
cat >/etc/leadledger.env <<'ENV'
LEADLEDGER_DB=embedded
LEADLEDGER_DATA=/var/lib/leadledger/leadledger.rdb
FALKORDB_GRAPH=leadledger_workspace
LEADLEDGER_AGENTS=fixture
ENV
chmod 0640 /etc/leadledger.env
chown root:leadledger /etc/leadledger.env
cat >/etc/systemd/system/leadledger.service <<'SERVICE'
[Unit]
Description=LeadLedger synthetic judge workspace
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
User=leadledger
Group=leadledger
WorkingDirectory=/opt/leadledger/app
EnvironmentFile=/etc/leadledger.env
ExecStartPre=/usr/bin/test -s /var/lib/leadledger/leadledger.rdb
ExecStart=/opt/leadledger/venv/bin/python scripts/run_workspace.py --agents fixture --port 8123
Restart=on-failure
RestartSec=5
TimeoutStopSec=120
KillMode=mixed
UMask=0027
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/leadledger /var/backups/leadledger
[Install]
WantedBy=multi-user.target
SERVICE
# Deliberately do not start or seed: restore and verify the existing graph first.
systemctl daemon-reload
systemctl enable leadledger.service
curl --fail --location --proto '=https' --tlsv1.2 \
  https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb \
  -o /tmp/cloudflared.deb
dpkg -i /tmp/cloudflared.deb
printf '\nPrepared. Restore the graph before starting leadledger.service. No tunnel credential was installed.\n'

# Absolute expiry survives reboot; retained disk charges continue after stop.
stop_at=$(date -u -d '+30 days' '+%Y-%m-%d %H:%M:%S UTC')
printf '%s\n' "$stop_at" >/etc/leadledger-stop-at
cat >/etc/systemd/system/leadledger-expiry.service <<'STOP'
[Unit]
Description=Stop EC2 after the approved 30-day judge window
[Service]
Type=oneshot
ExecStart=/usr/sbin/shutdown -h now
STOP
cat >/etc/systemd/system/leadledger-expiry.timer <<TIMER
[Unit]
Description=Absolute end of the LeadLedger hosting trial
[Timer]
OnCalendar=$stop_at
Persistent=true
Unit=leadledger-expiry.service
[Install]
WantedBy=timers.target
TIMER
systemctl daemon-reload
systemctl enable --now leadledger-expiry.timer
