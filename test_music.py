"""Music rooms: provider validation, queue/permissions, proxy ranges and cache."""
import http.cookiejar
import http.server
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
FAKE = os.path.join(ROOT, "tests", "fake_ytdlp.py")
try:
    os.chmod(FAKE, 0o755)
except OSError:
    pass

AUDIO = (b"RIFF" + (4096).to_bytes(4, "little") + b"WAVEfmt " + (16).to_bytes(4, "little")
         + (1).to_bytes(2, "little") + (1).to_bytes(2, "little") + (8000).to_bytes(4, "little")
         + (8000).to_bytes(4, "little") + (1).to_bytes(2, "little") + (8).to_bytes(2, "little")
         + b"data" + (4096 - 44).to_bytes(4, "little") + b"\x80" * (4096 - 44))


class AudioHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(AUDIO)))
        self.end_headers()
        self.wfile.write(AUDIO)


def wait_ready(port, proc, seconds=10):
    end = time.time() + seconds
    while time.time() < end:
        if proc.poll() is not None:
            out = proc.stdout.read() if proc.stdout else ""
            raise RuntimeError("server exited: " + out[-3000:])
        try:
            with urllib.request.urlopen("http://127.0.0.1:%d/api/ping" % port, timeout=1) as r:
                if r.status == 200:
                    return
        except Exception:
            time.sleep(0.12)
    raise RuntimeError("server did not start on %d" % port)


class Client:
    def __init__(self):
        self.cj = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))

    def call(self, method, path, body=None):
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (PORT, path), method=method,
                                     data=json.dumps(body or {}).encode() if method == "POST" else None,
                                     headers={"Content-Type": "application/json"})
        try:
            with self.op.open(req) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def raw(self, path, headers=None):
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (PORT, path), headers=headers or {})
        try:
            with self.op.open(req) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    def cookie(self):
        return next((c.value for c in self.cj if c.name == "og"), "")


def sse_open(client, timeout=8):
    s = socket.create_connection(("127.0.0.1", PORT), timeout=timeout)
    s.sendall(("GET /api/stream HTTP/1.0\r\nHost: 127.0.0.1\r\nCookie: og=%s\r\n\r\n" % client.cookie()).encode())
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = s.recv(4096)
        if not chunk:
            break
        buf += chunk
    _head, _, rest = buf.partition(b"\r\n\r\n")
    return s, rest


def sse_event(s, buf, want, timeout=8, pred=None):
    s.settimeout(timeout)
    end = time.time() + timeout
    while time.time() < end:
        blocks = buf.decode(errors="replace").split("\n\n")
        for i, block in enumerate(blocks[:-1]):
            lines = block.splitlines()
            if ("event: %s" % want) not in lines:
                continue
            data = next((ln[6:] for ln in lines if ln.startswith("data: ")), "")
            try:
                obj = json.loads(data)
            except ValueError:
                continue
            if pred and not pred(obj):
                continue
            return obj, "\n\n".join(blocks[i + 1:]).encode()
        try:
            chunk = s.recv(4096)
        except socket.timeout:
            break
        if not chunk:
            break
        buf += chunk
    return None, buf


ok = True


def check(name, cond, extra=""):
    global ok
    print(("PASS " if cond else "FAIL ") + name, extra if not cond else "")
    ok = ok and cond


def stop(proc):
    try:
        proc.terminate()
        proc.wait(timeout=4)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


audio = http.server.ThreadingHTTPServer(("127.0.0.1", 0), AudioHandler)
threading.Thread(target=audio.serve_forever, daemon=True).start()
AUDIO_URL = "http://127.0.0.1:%d/audio.wav" % audio.server_address[1]
tmp = tempfile.mkdtemp()
PORT = 8811
LOG = os.path.join(tmp, "ytdlp.log")
env = dict(os.environ, PORT=str(PORT), RAGDAMAXING_DB=os.path.join(tmp, "t.db"),
           RAGDAMAXING_MUSIC="1", RAGDAMAXING_YTDLP=FAKE,
           RAGDAMAXING_MUSIC_QUEUE_MAX="4", RAGDAMAXING_MUSIC_CACHE_MB="1",
           RAGDAMAXING_MUSIC_CACHE_DIR=os.path.join(tmp, "music_cache"),
           RAGDAMAXING_MUSIC_TIMEOUT="5", FAKE_AUDIO_URL=AUDIO_URL, FAKE_YTDLP_LOG=LOG)
proc = subprocess.Popen([sys.executable, "server.py"], cwd=ROOT, env=env,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

try:
    wait_ready(PORT, proc)
    a, b, c, d, out = Client(), Client(), Client(), Client(), Client()
    a.call("POST", "/api/register", {"username": "owner", "pin": "1234", "crew_name": "MusicCrew"})
    code = a.call("GET", "/api/crew")[1]["crew"]["code"]
    for cl, name in ((b, "member"), (c, "carol"), (d, "dave")):
        cl.call("POST", "/api/register", {"username": name, "pin": "1234", "crew_code": code})
    out.call("POST", "/api/register", {"username": "outsider", "pin": "1234", "crew_name": "Other"})
    for cl in (a, b, c, d, out):
        cl.call("GET", "/api/servers")
    sid = a.call("GET", "/api/servers")[1]["servers"][0]["id"]
    s, r = a.call("POST", "/api/channel/create", {"sid": sid, "name": "music-room", "kind": "voice"})
    ch = r.get("channel_id", 0)
    check("voice channel created", s == 200 and ch > 0, r)

    s, r = b.call("GET", "/api/time")
    check("public server clock", s == 200 and abs(r.get("t", 0) / 1000 - time.time()) < 5, r)

    for cl in (a, b, c):
        cl.call("POST", "/api/voice/join", {"ch": ch})
    s, r = b.call("GET", "/api/music/state?channel=%d" % ch)
    check("state enabled for voice member", s == 200 and r.get("enabled") is True, r)
    check("join snapshot carries music", isinstance(b.call("POST", "/api/voice/join", {"ch": ch})[1].get("music"), dict))

    s, r = out.call("GET", "/api/music/search?channel=%d&q=lofi" % ch)
    check("outsider search hidden", s == 404, r)
    s, r = b.call("GET", "/api/music/search?channel=%d&q=lofi" % ch)
    check("search returns fake result", s == 200 and r["results"] and r["results"][0]["id"] == "tst00000001", r)
    s, r2 = b.call("GET", "/api/music/search?channel=%d&q=lofi" % ch)
    check("search cached ten minutes", s == 200 and r2.get("cached") is True, r2)

    sse, sbuf = sse_open(b)
    s, r = b.call("POST", "/api/music/add", {"channel": ch, "query": "lofi song"})
    check("add by query starts playback", s == 200 and r.get("now") and r["now"]["track"]["requester"] == 2, r)
    ev, sbuf = sse_event(sse, sbuf, "music", pred=lambda x: x.get("channel") == ch and x.get("now"))
    check("music SSE reaches room", ev is not None and ev["now"]["track"]["id"] == "tst00000001", ev)

    for i in range(2, 6):
        s, r = b.call("POST", "/api/music/add", {"channel": ch, "id": "tst%08d" % i})
        check("queue add %d" % i, s == 200, r)
    s, r = b.call("POST", "/api/music/add", {"channel": ch, "id": "tst00000006"})
    check("queue cap enforced", s == 429, r)
    s, r = b.call("POST", "/api/music/add", {"channel": ch, "id": "tst00000007"})
    check("add rate limit", s == 429, r)

    before = sum(1 for _ in open(LOG, encoding="utf-8")) if os.path.exists(LOG) else 0
    bad = ["https://evil.example/watch?v=tst00000001", "file:///etc/passwd",
           "https://youtube.com/watch?v=tst00000001&list=RD1", "tst000000012", "--exec=touch /tmp/x"]
    for raw in bad:
        s, r = c.call("POST", "/api/music/add", {"channel": ch, "query": raw})
        check("reject unsafe input %s" % raw[:24], s == 400, r)
    after = sum(1 for _ in open(LOG, encoding="utf-8")) if os.path.exists(LOG) else 0
    check("unsafe inputs never reach yt-dlp", before == after, (before, after))
    s, r = d.call("POST", "/api/music/add", {"channel": ch, "id": "tst00000001"})
    check("member not in voice cannot add", s == 403, r)
    s, r = out.call("POST", "/api/music/add", {"channel": ch, "id": "tst00000001"})
    check("non-member cannot add", s == 404, r)

    s, r = b.call("GET", "/api/music/state?channel=%d" % ch)
    now_id = r["now"]["track"]["id"]
    cache_dir = env["RAGDAMAXING_MUSIC_CACHE_DIR"]
    os.makedirs(cache_dir, exist_ok=True)
    old = os.path.join(cache_dir, "old.audio")
    with open(old, "wb") as f:
        f.write(b"x" * (2 * 1024 * 1024))
    os.utime(old, (time.time() - 3600, time.time() - 3600))
    s, h, body = b.raw("/api/music/stream/%s?channel=%d" % (now_id, ch), {"Range": "bytes=0-31"})
    check("stream range 206", s == 206 and len(body) == 32 and h.get("Content-Range", "").startswith("bytes 0-31/"), (s, h))
    check("stream length exact", h.get("Content-Length") == "32" and h.get("Accept-Ranges") == "bytes", h)
    check("cache pruned to cap", not os.path.exists(old), old)
    check("no temp cache files", not [x for x in os.listdir(cache_dir) if x.endswith(".part")], os.listdir(cache_dir))
    s, h, body = b.raw("/api/music/stream/%s?channel=%d" % (now_id, ch))
    check("stream full 200", s == 200 and len(body) == len(AUDIO) and h.get("Content-Length") == str(len(AUDIO)), (s, h))
    s, h, body = b.raw("/api/music/stream/%s?channel=%d" % (now_id, ch), {"Range": "bytes=999999-"})
    check("bad range 416", s == 416, (s, h))
    anon = Client()
    s, h, body = anon.raw("/api/music/stream/%s?channel=%d" % (now_id, ch), {"Range": "bytes=0-1"})
    check("anonymous stream refused", s == 401, s)
    s, h, body = d.raw("/api/music/stream/%s?channel=%d" % (now_id, ch), {"Range": "bytes=0-1"})
    check("not-in-room stream refused", s == 403, s)
    s, h, body = out.raw("/api/music/stream/%s?channel=%d" % (now_id, ch), {"Range": "bytes=0-1"})
    check("non-member stream hidden", s == 404, s)
    s, h, body = b.raw("/api/music/stream/tst00000009?channel=%d" % ch, {"Range": "bytes=0-1"})
    check("track not in queue refused", s == 404, s)

    s, r = c.call("POST", "/api/music/skip", {"channel": ch})
    check("first skip is a vote", s == 200 and r["now"]["track"]["id"] == now_id and r["votes"].get("skip") == 1, r)
    s, r = c.call("POST", "/api/music/skip", {"channel": ch})
    check("same vote is idempotent", s == 200 and r["votes"].get("skip") == 1, r)
    s, r = a.call("POST", "/api/music/skip", {"channel": ch})
    check("moderator skip works", s == 200 and r["now"]["track"]["id"] == "tst00000002", r)
    ev, sbuf = sse_event(sse, sbuf, "music", pred=lambda x: x.get("now") and x["now"]["track"]["id"] == "tst00000002")
    check("skip seen by other listener", ev is not None, ev)
    s, r = b.call("POST", "/api/music/skip", {"channel": ch})
    check("requester skip works", s == 200 and r["now"]["track"]["id"] == "tst00000003", r)
    s, r = b.call("POST", "/api/music/pause", {"channel": ch})
    check("requester pause", s == 200 and r["now"]["paused_at_ms"] is not None, r)
    time.sleep(0.2)
    s, r = b.call("POST", "/api/music/resume", {"channel": ch})
    check("requester resume", s == 200 and r["now"]["paused_at_ms"] is None, r)
    s, r = b.call("POST", "/api/music/remove", {"channel": ch, "index": 0})
    check("requester removes queue item", s == 200 and len(r["queue"]) == 1, r)
    s, r = b.call("POST", "/api/music/loop", {"channel": ch, "mode": "track"})
    check("loop mode", s == 200 and r["loop"] == "track", r)
    s, r = a.call("POST", "/api/music/stop", {"channel": ch})
    check("moderator stop", s == 200 and r["now"] is None, r)
    sse.close()

    for i in range(10):
        s, r = d.call("GET", "/api/music/search?channel=%d&q=rate%d" % (ch, i))
        if s != 200:
            break
    check("ten searches allowed", s == 200, (s, r))
    s, r = d.call("GET", "/api/music/search?channel=%d&q=rate-last" % ch)
    check("search rate limit", s == 429, r)

    # Provider timeout directly: the child must be killed, not left running for the full sleep.
    sys.path.insert(0, ROOT)
    import social_music
    os.environ["FAKE_SLEEP"] = "3"
    p = social_music.YtdlpProvider(FAKE, timeout=1)
    t0 = time.time()
    try:
        p.resolve("tst00000001")
        timed = False
    except social_music.MusicError as e:
        timed = e.code == 504
    finally:
        os.environ.pop("FAKE_SLEEP", None)
    check("yt-dlp timeout kills child", timed and time.time() - t0 < 2.6, time.time() - t0)

finally:
    stop(proc)
    audio.shutdown()

# Feature off when the binary is missing, but the rest of the app still boots.
tmp2 = tempfile.mkdtemp()
PORT = 8812
env2 = dict(os.environ, PORT=str(PORT), RAGDAMAXING_DB=os.path.join(tmp2, "t.db"),
            RAGDAMAXING_MUSIC="1", RAGDAMAXING_YTDLP="/definitely/not/yt-dlp",
            RAGDAMAXING_MUSIC_CACHE_DIR=os.path.join(tmp2, "music_cache"))
proc2 = subprocess.Popen([sys.executable, "server.py"], cwd=ROOT, env=env2,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
try:
    wait_ready(PORT, proc2)
    z = Client()
    z.call("POST", "/api/register", {"username": "solo", "pin": "1234", "crew_name": "Solo"})
    z.call("GET", "/api/servers")
    sid = z.call("GET", "/api/servers")[1]["servers"][0]["id"]
    ch = z.call("POST", "/api/channel/create", {"sid": sid, "name": "quiet", "kind": "voice"})[1].get("channel_id", 0)
    joined = z.call("POST", "/api/voice/join", {"ch": ch})[1]
    s, r = z.call("GET", "/api/music/state?channel=%d" % ch)
    check("missing binary keeps music off", s == 200 and r.get("enabled") is False and "yt-dlp" in r.get("reason", ""), r)
    check("join snapshot explains music off", joined.get("music", {}).get("enabled") is False, joined.get("music"))
    s, r = z.call("GET", "/api/music/search?channel=%d&q=test" % ch)
    check("missing binary search 503", s == 503 and "yt-dlp" in r.get("error", ""), r)
finally:
    stop(proc2)

print("ALL OK" if ok else "FAILURES")
sys.exit(0 if ok else 1)
