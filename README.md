# OUTGROW (growth_tracker_v3)

Multiplayer discipline engine for exam season. Python stdlib only, SQLite, mobile-first web UI.

    ./run.sh          # start (http://localhost:8765, LAN address printed)
    ./share.sh        # second terminal: public https link for friends not on your Wi-Fi
    python3 test_api.py   # ~80 API checks (temp DB, own port)

First start creates the crew `NervHQ` and prints its invite code (also in `data/INVITE_CODE.txt`).
Friends: open the link, "New here?", enter the code. Add to Home Screen to install it as an app.

Chat: the Chat tab has a crew room and private DMs between crew members. Text only, no media or files (1000 chars max).
Admin: set `OUTGROW_ADMINS=yourusername` to get Me -> Server dashboard (stats, DB backup download, PIN reset).
Env: `OUTGROW_BIND` (default 0.0.0.0; use 127.0.0.1 behind a tunnel), `TZ` (the day rolls over at 3 AM in this zone).
Hosting 24/7 on a VPS: see DEPLOY.md.

Optional: `OUTGROW_DISCORD_WEBHOOK=<url> ./run.sh` posts badges, level-ups, streaks and comebacks to a Discord channel.

Old data: the original growth_tracker CSV is imported as "Season 0". Anyone who registers with their old
username (exe, kritarth, zenx, dharmxveer) gets XP + a veteran badge.

The day rolls over at 3 AM. Data lives in `data/outgrow.db` (back it up by copying the file).
