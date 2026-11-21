#!/usr/bin/env python3
"""Canned yt-dlp used by test_music.py. Never shipped or enabled in production."""
import json
import os
import sys
import time


def log_args(args):
    path = os.environ.get("FAKE_YTDLP_LOG")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(args) + "\n")


def main():
    args = sys.argv[1:]
    log_args(args)
    delay = os.environ.get("FAKE_SLEEP")
    if delay:
        time.sleep(float(delay))
    if os.environ.get("FAKE_FAIL") == "1":
        print("ERROR: Sign in to confirm you are not a bot", file=sys.stderr)
        return 1
    if "--version" in args:
        print("2026.08.19")
        return 0
    search = next((a for a in args if a.startswith("ytsearch")), "")
    if search:
        try:
            n = int(search[len("ytsearch"):].split(":", 1)[0])
        except ValueError:
            n = 1
        q = search.split(":", 1)[1] if ":" in search else "test"
        for i in range(max(1, min(n, 5))):
            dur = 9999 if "long" in q.lower() else 60
            print(json.dumps({"id": "tst%08d" % (i + 1), "title": "Fake song %d for %s" % (i + 1, q),
                              "duration": dur, "uploader": "Fake Artist", "is_live": False}))
        return 0
    url = next((a for a in reversed(args) if a.startswith("https://www.youtube.com/watch?v=")), "")
    vid = url.rsplit("v=", 1)[-1] if url else "tst00000001"
    direct = os.environ.get("FAKE_AUDIO_URL", "")
    if not direct:
        print("no FAKE_AUDIO_URL", file=sys.stderr)
        return 2
    print(json.dumps({"id": vid, "title": "Fake Song " + vid, "uploader": "Fake Artist", "duration": 60,
                      "is_live": os.environ.get("FAKE_LIVE") == "1", "ext": "wav", "url": direct,
                      "http_headers": {"User-Agent": "fake-agent"}, "expires": int(time.time()) + 3600}))
    return 0


if __name__ == "__main__":
    sys.exit(main())