#!/usr/bin/env bash
# Pulls the latest code from GitHub, restarts OUTGROW, and rolls back if the new version won't start.
# Runs as root from a systemd timer, but only ever runs git/python as the unprivileged "outgrow" user.
# This file lives in /usr/local/lib/outgrow (a root-owned copy), so pushing to GitHub can never change what root runs.
set -uo pipefail
APP=/opt/outgrow/app
BAD=/opt/outgrow/.bad_commit
[ -f /etc/outgrow.env ] && { set -a; . /etc/outgrow.env; set +a; }
as() { runuser -u outgrow -- "$@"; }
cd "$APP" || exit 1

old=$(as git rev-parse HEAD)
as git fetch --quiet origin || { echo "fetch failed (offline?), will retry"; exit 0; }
branch=$(as git rev-parse --abbrev-ref HEAD)
new=$(as git rev-parse "origin/$branch")
[ "$old" = "$new" ] && exit 0
[ "$(cat "$BAD" 2>/dev/null)" = "$new" ] && exit 0   # already tried this one and it failed; wait for a new push

echo "updating ${old:0:7} -> ${new:0:7}"
as git reset --hard --quiet "origin/$branch"
if ! as python3 -m py_compile server.py; then
  echo "new version has a syntax error, rolling back"
  as git reset --hard --quiet "$old"; echo "$new" > "$BAD"; exit 1
fi
systemctl restart outgrow.service
for i in 1 2 3 4 5 6 7 8; do
  sleep 2
  if curl -fsS -m 3 "http://127.0.0.1:${PORT:-8765}/api/ping" >/dev/null 2>&1; then echo "update ok"; rm -f "$BAD"; exit 0; fi
done
echo "new version did not come up, rolling back to ${old:0:7}"
as git reset --hard --quiet "$old"; echo "$new" > "$BAD"
systemctl restart outgrow.service
exit 1
