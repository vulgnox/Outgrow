#!/usr/bin/env bash
# Expose OUTGROW to friends anywhere, with a public https link. Ctrl+C to stop sharing.
# Picks the first thing available: cloudflared -> tailscale funnel -> ssh tunnel (no install needed).
PORT=${PORT:-8765}
if command -v cloudflared >/dev/null; then
  exec cloudflared tunnel --url http://localhost:$PORT
elif command -v tailscale >/dev/null && tailscale status >/dev/null 2>&1; then
  exec tailscale funnel $PORT
else
  echo "Using localhost.run (ssh tunnel). Your public URL appears below:"
  exec ssh -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 -R 80:localhost:$PORT nokey@localhost.run
fi
