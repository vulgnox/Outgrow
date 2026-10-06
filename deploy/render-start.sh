#!/bin/sh
# Container entrypoint for Render (free web service, ephemeral disk).
# Persistence options (pick one, both are free):
#   GH_BACKUP_REPO + GH_BACKUP_TOKEN  -> private GitHub repo, no card needed (deploy/ghsync.py)
#   LITESTREAM_BUCKET (+ keys)        -> S3-compatible bucket via Litestream
set -e
mkdir -p "$(dirname "$OUTGROW_DB")"
export PORT="${PORT:-10000}"

if [ -n "$GH_BACKUP_REPO" ] || [ -n "$GH_BACKUP_URL" ]; then
  echo "[start] starting OUTGROW with GitHub-repo persistence"
  exec python3 /app/deploy/ghsync.py supervise
elif [ -n "$LITESTREAM_BUCKET" ]; then
  echo "[start] restoring database from bucket (if one exists)..."
  litestream restore -if-db-not-exists -if-replica-exists -config /app/deploy/litestream.yml "$OUTGROW_DB"
  echo "[start] starting OUTGROW under litestream"
  exec litestream replicate -config /app/deploy/litestream.yml -exec "python3 /app/server.py"
else
  echo "[start] WARNING: no GH_BACKUP_REPO or LITESTREAM_BUCKET set. Data will be LOST on every restart."
  exec python3 /app/server.py
fi
