#!/usr/bin/env bash
# Daily consistent snapshot of the database (safe while the app is running). Keeps 14 days.
set -euo pipefail
DB=/opt/outgrow/app/data/outgrow.db
OUT=/opt/outgrow/backups
[ -f "$DB" ] || exit 0
runuser -u outgrow -- python3 - "$DB" "$OUT/outgrow-$(date +%Y%m%d-%H%M).db" <<'PY'
import sqlite3, sys
src, dst = sqlite3.connect(sys.argv[1]), sqlite3.connect(sys.argv[2])
src.backup(dst); dst.close(); src.close()
PY
find "$OUT" -name 'outgrow-*.db' -mtime +14 -delete
