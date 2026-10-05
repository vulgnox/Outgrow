#!/usr/bin/env bash
# OUTGROW installer for a Debian/Ubuntu VPS. Run once, as root, from a clone of the repo:
#   git clone <repo-url> /tmp/outgrow-src && sudo bash /tmp/outgrow-src/deploy/install.sh
# Safe to re-run (it only fills in what's missing and refreshes the root-owned helper scripts).
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Run with sudo."; exit 1; }
SRC="$(cd "$(dirname "$0")/.." && pwd)"
REPO="$(git -C "$SRC" remote get-url origin)"
BRANCH="$(git -C "$SRC" rev-parse --abbrev-ref HEAD)"
APP=/opt/outgrow/app

echo "==> packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq git python3 curl ca-certificates

echo "==> unprivileged 'outgrow' user + folders"
id outgrow >/dev/null 2>&1 || useradd --system --home-dir /opt/outgrow --create-home --shell /usr/sbin/nologin outgrow
mkdir -p /opt/outgrow/backups /usr/local/lib/outgrow
if [ ! -d "$APP/.git" ]; then
  (cd /opt/outgrow && runuser -u outgrow -- git clone --quiet --branch "$BRANCH" "$REPO" "$APP") \
    || { echo "git clone failed. Is the repo public? (private repos need a read-only deploy key, see DEPLOY.md)"; exit 1; }
fi
mkdir -p "$APP/data"
chown -R outgrow:outgrow /opt/outgrow

echo "==> helper scripts (root-owned, NOT auto-updated), config, systemd units"
install -m 755 -o root -g root "$APP/deploy/update.sh" "$APP/deploy/backup.sh" /usr/local/lib/outgrow/
[ -f /etc/outgrow.env ] || install -m 640 -o root -g outgrow "$APP/deploy/outgrow.env.example" /etc/outgrow.env
install -m 644 "$APP"/deploy/*.service "$APP"/deploy/*.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now outgrow.service outgrow-backup.timer outgrow-update.timer

echo "==> health check"
. /etc/outgrow.env
for i in 1 2 3 4 5 6 7 8 9 10; do
  if curl -fsS -m 3 "http://127.0.0.1:${PORT:-8765}/api/ping" >/dev/null 2>&1; then
    echo "OUTGROW is up on 127.0.0.1:${PORT:-8765}  (only reachable from this machine, on purpose)"
    echo "Invite code (first run only): $(cat "$APP/data/INVITE_CODE.txt" 2>/dev/null || echo 'already created')"
    echo; echo "Next: put it on the internet with HTTPS. See DEPLOY.md, step 2."; exit 0
  fi
  sleep 1
done
echo "Service did not answer. Look at:  journalctl -u outgrow -n 50 --no-pager"; exit 1
