#!/usr/bin/env bash
# Start OUTGROW. Friends on the same Wi-Fi can open the LAN address printed below.
cd "$(dirname "$0")"
IP=$(hostname -I 2>/dev/null | awk '{print $1}')
echo "Local:  http://localhost:${PORT:-8765}"
[ -n "$IP" ] && echo "LAN:    http://$IP:${PORT:-8765}   (friends on your Wi-Fi)"
echo "Remote friends? run ./share.sh in a second terminal."
exec python3 server.py
