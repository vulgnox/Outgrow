#!/bin/sh
# Container entrypoint for Render (free web service, ephemeral disk).
# 1. restore the latest DB from the bucket (skipped if there is nothing there yet = first ever boot)
# 2. run the server under Litestream so every write is streamed back to the bucket within ~5 s
set -e
mkdir -p "$(dirname "$OUTGROW_DB")"
export PORT="${PORT:-10000}"

if [ -n "$LITESTREAM_BUCKET" ]; then
  echo "[start] restoring database from bucket (if one exists)..."
  litestream restore -if-db-not-exists -if-replica-exists -config /app/deploy/litestream.yml "$OUTGROW_DB"
  echo "[start] starting OUTGROW under litestream"
  exec litestream replicate -config /app/deploy/litestream.yml -exec "python3 /app/server.py"
else
  echo "[start] WARNING: LITESTREAM_BUCKET not set. Data will be LOST on every restart."
  exec python3 /app/server.py
fi
