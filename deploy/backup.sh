#!/usr/bin/env bash
# Daily consistent snapshot of the database (safe while the app is running). Keeps 14 days.
set -euo pipefail
DB=/opt/ragdamaxing/app/data/ragdamaxing.db
OUT=/opt/ragdamaxing/backups
[ -f "$DB" ] || exit 0
runuser -u ragdamaxing -- python3 - "$DB" "$OUT/ragdamaxing-$(date +%Y%m%d-%H%M).db" <<'PY'
import sqlite3, sys
src, dst = sqlite3.connect(sys.argv[1]), sqlite3.connect(sys.argv[2])
src.backup(dst); dst.close(); src.close()
PY
find "$OUT" -name 'ragdamaxing-*.db' -mtime +14 -delete
