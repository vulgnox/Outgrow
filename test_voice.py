"""Phase 5: voice rooms, permissions, signaling relay, state, capacity and cleanup."""
import base64
import hashlib
import hmac
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import http.cookiejar

PORT = 8806
tmp = tempfile.mkdtemp()
env = dict(os.environ, PORT=str(PORT), RAGDAMAXING_DB=os.path.join(tmp, "t.db"), RAGDAMAXING_ADMINS="boss",
           TURN_URLS="turn:turn.example.test:80?transport=tcp", TURN_SECRET="voice-test-secret")
srv = subprocess.Popen([sys.executable, "server.py"], env=env, cwd=os.path.dirname(os.path.abspath(__file__)),
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
time.sleep(1.6)


class Client:
    def __init__(self):
        self.cj = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))

    def call(self, method, path, body=None):
        req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", method=method,
                                     data=json.dumps(body or {}).encode() if method == "POST" else None,
                                     headers={"Content-Type": "application/json"})
        try:
            with self.op.open(req) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def cookie(self):
        return next((c.value for c in self.cj if c.name == "og"), "")


ok = True


def check(name, cond, extra=""):
    global ok
    print(("PASS " if cond else "FAIL ") + name, extra if not cond else "")
    ok = ok and cond


def uid(cl):
    return cl.call("GET", "/api/me")[1]["user"]["id"]


def sse_open(client, timeout=8):
    s = socket.create_connection(("127.0.0.1", PORT), timeout=timeout)
    s.sendall(("GET /api/stream HTTP/1.0\r\nHost: 127.0.0.1\r\nCookie: og=%s\r\n\r\n" % client.cookie()).encode())
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = s.recv(4096)
        if not chunk:
            break
        buf += chunk
    head, _, rest = buf.partition(b"\r\n\r\n")
    return s, head.decode(errors="replace"), rest


def sse_event(s, buf, want, timeout=8, pred=None):
    """Read until one complete event block named want (and matching pred), consuming it."""
    s.settimeout(timeout)
    end = time.time() + timeout
    while time.time() < end:
        text = buf.decode(errors="replace")
        blocks = text.split("\n\n")
        complete = blocks[:-1]
        for i, block in enumerate(complete):
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
            rest = "\n\n".join(blocks[i + 1:])
            return obj, rest.encode()
        try:
            chunk = s.recv(4096)
        except socket.timeout:
            break
        if not chunk:
            break
        buf += chunk
    return None, buf


def type_is(name):
    return lambda d: d.get("type") == name


try:
    a, b, out = Client(), Client(), Client()
    a.call("POST", "/api/register", {"username": "owner", "pin": "1234", "crew_name": "VoiceCrew"})
    code = a.call("GET", "/api/crew")[1]["crew"]["code"]
    b.call("POST", "/api/register", {"username": "member", "pin": "1234", "crew_code": code})
    out.call("POST", "/api/register", {"username": "outsider", "pin": "1234", "crew_name": "OtherCrew"})
    extras = []
    for i in range(7):
        c = Client()
        c.call("POST", "/api/register", {"username": "extra%d" % i, "pin": "1234", "crew_code": code})
        extras.append(c)
    for c in [a, b, out] + extras:
        c.call("GET", "/api/servers")
    ua, ub = uid(a), uid(b)
    sid = a.call("GET", "/api/servers")[1]["servers"][0]["id"]
    textch = a.call("GET", f"/api/server?sid={sid}")[1]["channels"][0]["id"]

    def mkv(name):
        s, r = a.call("POST", "/api/channel/create", {"sid": sid, "name": name, "kind": "voice"})
        return r.get("channel_id", 0)

    voice_a, voice_b, voice_cap = mkv("voice-a"), mkv("voice-b"), mkv("voice-cap")
    voice_d, voice_e = mkv("voice-drop"), mkv("voice-kick")
    check("voice channels created", all([voice_a, voice_b, voice_cap, voice_d, voice_e]))
    check("voice channel appears in server", a.call("GET", f"/api/server?sid={sid}")[1]["channels"][-1]["kind"] == "voice")

    # ---------------------------------------------------------------- access checks
    check("voice join needs login", Client().call("POST", "/api/voice/join", {"ch": voice_a})[0] == 401)
    check("room state needs login", Client().call("GET", f"/api/voice?ch={voice_a}")[0] == 401)
    check("outsider cannot join", out.call("POST", "/api/voice/join", {"ch": voice_a})[0] == 404)
    check("outsider cannot read room", out.call("GET", f"/api/voice?ch={voice_a}")[0] == 404)
    check("text channel is not a voice room", a.call("POST", "/api/voice/join", {"ch": textch})[0] == 400)
    check("bad channel id rejected", a.call("POST", "/api/voice/join", {"ch": 999999})[0] == 404)
    check("missing channel rejected", a.call("GET", "/api/voice?ch=")[0] in (400, 404))

    # ---------------------------------------------------------------- join, room state, signaling
    sa, ahead, abuf = sse_open(a)
    sb, _, bbuf = sse_open(b)
    hello, abuf = sse_event(sa, abuf, "hello")
    check("voice SSE opens", "text/event-stream" in ahead and hello and hello["uid"] == ua, (ahead, hello))
    s, r = a.call("POST", "/api/voice/join", {"ch": voice_a})
    check("owner joins voice", s == 200 and r["self"] is True and len(r["participants"]) == 1, r)
    check("join response carries the room cap", r.get("max") == 8, r)
    check("join response carries the screen viewer cap", r.get("screen_max") == 3, r)
    turn = next((x for x in r.get("ice", []) if any(str(u).startswith("turn:") for u in ([x.get("urls")] if isinstance(x.get("urls"), str) else x.get("urls", [])))), None)
    check("join response carries TURN relay config", bool(turn), r.get("ice"))
    if turn:
        expect = base64.b64encode(hmac.new(b"voice-test-secret", turn["username"].encode(), hashlib.sha1).digest()).decode()
        check("TURN credential is signed and short-lived", turn["credential"] == expect and int(turn["username"].split(":")[0]) > time.time(), turn)
    s, r = b.call("POST", "/api/voice/join", {"ch": voice_a})
    check("member joins voice", s == 200 and len(r["participants"]) == 2, r)
    check("second participant sees the first",
          any(p["uid"] == ua for p in r["participants"]) and any(p["uid"] == ub for p in r["participants"]), r["participants"])
    check("voice cards carry the screen state", all(p.get("screen") is False for p in r["participants"]), r["participants"])
    ev, abuf = sse_event(sa, abuf, "voice", pred=type_is("join"))
    check("existing peer gets a join event", ev and ev["user"]["uid"] == ub, ev)

    s, r = a.call("GET", f"/api/voice?ch={voice_a}")
    check("room state lists both", s == 200 and len(r["participants"]) == 2 and r["self"] is True, r)
    s, r = b.call("GET", f"/api/voice?ch={voice_a}")
    check("room state is per viewer", s == 200 and r["self"] is True, r)

    offer = {"type": "offer", "sdp": "v=0\r\no=- 1 1 IN IP4 127.0.0.1\r\n"}
    s, r = a.call("POST", "/api/voice/signal", {"ch": voice_a, "to": ub, "kind": "offer", "payload": offer})
    check("offer relayed", s == 200, r)
    ev, bbuf = sse_event(sb, bbuf, "voice", pred=type_is("signal"))
    check("target receives the offer", ev and ev["from"] == ua and ev["kind"] == "offer"
          and ev["payload"]["sdp"] == offer["sdp"], ev)
    s, r = b.call("POST", "/api/voice/signal", {"ch": voice_a, "to": ua, "kind": "answer",
                                                "payload": {"type": "answer", "sdp": "v=0\r\nanswer\r\n"}})
    check("answer relayed", s == 200, r)
    ev, abuf = sse_event(sa, abuf, "voice", pred=type_is("signal"))
    check("offerer receives the answer", ev and ev["from"] == ub and ev["kind"] == "answer", ev)
    ice = {"candidate": "candidate:1 1 udp 1 127.0.0.1 5000 typ host", "sdpMid": "0", "sdpMLineIndex": 0}
    s, r = a.call("POST", "/api/voice/signal", {"ch": voice_a, "to": ub, "kind": "ice", "payload": ice})
    check("ICE relayed", s == 200, r)
    ev, bbuf = sse_event(sb, bbuf, "voice", pred=type_is("signal"))
    check("target receives ICE", ev and ev["kind"] == "ice" and ev["payload"]["candidate"] == ice["candidate"], ev)

    check("cannot signal yourself",
          a.call("POST", "/api/voice/signal", {"ch": voice_a, "to": ua, "kind": "offer", "payload": offer})[0] == 400)
    check("cannot signal a non-participant",
          a.call("POST", "/api/voice/signal", {"ch": voice_a, "to": uid(out), "kind": "offer", "payload": offer})[0] == 400)
    check("unknown signal kind rejected",
          a.call("POST", "/api/voice/signal", {"ch": voice_a, "to": ub, "kind": "hack", "payload": offer})[0] == 400)
    check("signal payload must be an object",
          a.call("POST", "/api/voice/signal", {"ch": voice_a, "to": ub, "kind": "offer", "payload": "x"})[0] == 400)
    check("oversized signal rejected",
          a.call("POST", "/api/voice/signal", {"ch": voice_a, "to": ub, "kind": "offer",
                                              "payload": {"type": "offer", "sdp": "x" * 40000}})[0] in (400, 413))
    check("signaling before joining rejected",
          extras[0].call("POST", "/api/voice/signal", {"ch": voice_a, "to": ua, "kind": "offer", "payload": offer})[0] == 400)

    # ---------------------------------------------------------------- mute / deafen / speaking
    s, r = b.call("POST", "/api/voice/state", {"ch": voice_a, "muted": True, "deafened": False})
    check("mute state accepted", s == 200 and r["muted"] is True, r)
    ev, abuf = sse_event(sa, abuf, "voice", pred=type_is("state"))
    check("peer receives mute state", ev and ev["uid"] == ub and ev["muted"] is True, ev)
    s, r = a.call("GET", f"/api/voice?ch={voice_a}")
    bcard = next(p for p in r["participants"] if p["uid"] == ub)
    check("room state carries mute", bcard["muted"] is True, bcard)
    s, r = b.call("POST", "/api/voice/state", {"ch": voice_a, "muted": True, "deafened": False, "screen": True})
    check("screen state accepted", s == 200 and r.get("screen") is True, r)
    ev, abuf = sse_event(sa, abuf, "voice", pred=type_is("state"))
    check("peer receives screen state", ev and ev["uid"] == ub and ev.get("screen") is True, ev)
    s, r = a.call("GET", f"/api/voice?ch={voice_a}")
    bcard = next(p for p in r["participants"] if p["uid"] == ub)
    check("room state carries screen", bcard.get("screen") is True, bcard)
    s, r = a.call("POST", "/api/voice/state", {"ch": voice_a, "muted": False, "deafened": False, "screen": True})
    check("only one screen sharer at a time", s == 409, (s, r))
    s, r = b.call("POST", "/api/voice/state", {"ch": voice_a, "muted": True, "deafened": False, "screen": False})
    check("screen state can be cleared", s == 200 and r.get("screen") is False, r)
    ev, abuf = sse_event(sa, abuf, "voice", pred=type_is("state"))
    check("peer receives screen stop", ev and ev.get("screen") is False, ev)
    s, r = b.call("POST", "/api/voice/signal", {"ch": voice_a, "to": ua, "kind": "lower", "payload": {"screen": True}})
    check("lower-preset request relayed", s == 200, r)
    ev, abuf = sse_event(sa, abuf, "voice", pred=type_is("signal"))
    check("peer receives lower request", ev and ev["kind"] == "lower", ev)
    check("lower signal needs an object payload",
          b.call("POST", "/api/voice/signal", {"ch": voice_a, "to": ua, "kind": "lower", "payload": "x"})[0] == 400)
    s, r = b.call("POST", "/api/voice/signal", {"ch": voice_a, "to": ua, "kind": "preset", "payload": {"screen": True, "preset": "sharp30"}})
    check("preset change relayed", s == 200, r)
    ev, abuf = sse_event(sa, abuf, "voice", pred=type_is("signal"))
    check("peer receives preset change", ev and ev["kind"] == "preset" and ev["payload"]["preset"] == "sharp30", ev)
    check("preset must be a short string",
          b.call("POST", "/api/voice/signal", {"ch": voice_a, "to": ua, "kind": "preset", "payload": {"preset": 3}})[0] == 400)
    s, r = b.call("POST", "/api/voice/state", {"ch": voice_a, "muted": False, "deafened": True})
    check("deafen implies mute", s == 200 and r["deafened"] is True and r["muted"] is True, r)
    ev, abuf = sse_event(sa, abuf, "voice", pred=type_is("state"))
    check("peer receives deafen", ev and ev["deafened"] is True and ev["muted"] is True, ev)
    b.call("POST", "/api/voice/state", {"ch": voice_a, "muted": False, "deafened": False})
    s, r = b.call("POST", "/api/voice/speaking", {"ch": voice_a, "on": True})
    check("speaking flag accepted", s == 200 and r.get("speaking") is True, r)
    ev, abuf = sse_event(sa, abuf, "voice", pred=type_is("speaking"))
    check("peer receives speaking", ev and ev["uid"] == ub and ev["on"] is True, ev)
    s, r = b.call("POST", "/api/voice/ping", {"ch": voice_a})
    check("voice ping works", s == 200 and r.get("ch") == voice_a, r)
    check("state before joining rejected",
          extras[0].call("POST", "/api/voice/state", {"ch": voice_a, "muted": True})[0] == 400)
    check("speaking before joining rejected",
          extras[0].call("POST", "/api/voice/speaking", {"ch": voice_a, "on": True})[0] == 400)

    # ---------------------------------------------------------------- voice permission and timeout
    e1 = extras[0]
    check("default member can join voice", e1.call("POST", "/api/voice/join", {"ch": voice_b})[0] == 200)
    e1.call("POST", "/api/voice/leave", {"ch": voice_b})
    roles = a.call("GET", f"/api/roles?sid={sid}")[1]["roles"]
    everyone = next(x for x in roles if x["default"])
    base = everyone["perms"]
    a.call("POST", "/api/role/update", {"sid": sid, "role": everyone["id"], "name": everyone["name"],
                                        "color": everyone["color"], "perms": base & ~16})
    check("voice bit blocks joining", e1.call("POST", "/api/voice/join", {"ch": voice_b})[0] == 403)
    check("voice bit blocks state", e1.call("POST", "/api/voice/state", {"ch": voice_b, "muted": True})[0] == 403)
    check("voice bit blocks signaling", e1.call("POST", "/api/voice/signal", {"ch": voice_b, "to": ua, "kind": "ice",
                                                                          "payload": {"candidate": "c"}})[0] == 403)
    check("viewing an empty room still needs only view", e1.call("GET", f"/api/voice?ch={voice_b}")[0] == 200)
    a.call("POST", "/api/role/update", {"sid": sid, "role": everyone["id"], "name": everyone["name"],
                                        "color": everyone["color"], "perms": base})
    db = sqlite3.connect(env["RAGDAMAXING_DB"])
    db.execute("INSERT OR REPLACE INTO timeouts(server_id,user_id,until,by_id,reason) VALUES(?,?,?,?,?)",
               (sid, uid(e1), time.time() + 600, ua, "voice test"))
    db.commit()
    db.close()
    check("timed out member cannot join voice", e1.call("POST", "/api/voice/join", {"ch": voice_b})[0] == 403)
    db = sqlite3.connect(env["RAGDAMAXING_DB"])
    db.execute("DELETE FROM timeouts WHERE server_id=? AND user_id=?", (sid, uid(e1)))
    db.commit()
    db.close()
    check("member joins after timeout", e1.call("POST", "/api/voice/join", {"ch": voice_b})[0] == 200)
    e1.call("POST", "/api/voice/leave", {"ch": voice_b})

    # ---------------------------------------------------------------- capacity (8)
    b.call("POST", "/api/voice/leave", {"ch": voice_a})
    a.call("POST", "/api/voice/leave", {"ch": voice_a})
    room8 = [a, b] + extras[:6]
    for i, c in enumerate(room8):
        st, rr = c.call("POST", "/api/voice/join", {"ch": voice_cap})
        check("voice capacity join %d" % (i + 1), st == 200, rr)
    st, rr = extras[6].call("POST", "/api/voice/join", {"ch": voice_cap})
    check("ninth participant refused", st == 429, (st, rr))
    for c in room8:
        c.call("POST", "/api/voice/leave", {"ch": voice_cap})

    # ---------------------------------------------------------------- one room per user + leave
    a.call("POST", "/api/voice/join", {"ch": voice_a})
    a.call("POST", "/api/voice/join", {"ch": voice_b})
    s, r = a.call("GET", f"/api/voice?ch={voice_a}")
    check("joining another room leaves the first", s == 200 and len(r["participants"]) == 0, r)
    s, r = a.call("GET", f"/api/voice?ch={voice_b}")
    check("user is in the second room", s == 200 and len(r["participants"]) == 1, r)
    s, r = a.call("POST", "/api/voice/leave", {"ch": voice_b})
    check("leave succeeds", s == 200, r)
    s, r = a.call("GET", f"/api/voice?ch={voice_b}")
    check("leave removes the participant", s == 200 and len(r["participants"]) == 0, r)
    check("state after leave is rejected", a.call("POST", "/api/voice/state", {"ch": voice_b, "muted": True})[0] == 400)

    # ---------------------------------------------------------------- kick prunes a live seat (non-legacy server)
    s, r = a.call("POST", "/api/server/create", {"name": "Voice Kick Hall", "icon": "🥾"})
    check("create a non-legacy server for kick test", s == 200 and r.get("server_id"), r)
    ksid = r.get("server_id", 0)
    inv = a.call("POST", "/api/invite/create", {"sid": ksid, "days": 1, "max_uses": 5})[1].get("code", "")
    check("invite member to kick server", b.call("POST", "/api/server/join", {"code": inv})[0] == 200)
    s, r = a.call("POST", "/api/channel/create", {"sid": ksid, "name": "kick-voice", "kind": "voice"})
    kch = r.get("channel_id", 0)
    check("non-legacy voice channel created", s == 200 and kch, r)
    b.call("POST", "/api/voice/join", {"ch": kch})
    a.call("POST", "/api/voice/join", {"ch": kch})
    s, r = a.call("POST", "/api/mod/kick", {"sid": ksid, "uid": ub})
    check("kick member for voice prune", s == 200, r)
    s, r = a.call("GET", f"/api/voice?ch={kch}")
    check("kicked member is pruned from the room", s == 200 and all(p["uid"] != ub for p in r["participants"]), r)
    check("kicked member cannot rejoin voice", b.call("POST", "/api/voice/join", {"ch": kch})[0] == 404)
    a.call("POST", "/api/voice/leave", {"ch": kch})
    a.call("POST", "/api/server/delete", {"sid": ksid})

    # ---------------------------------------------------------------- channel delete drops the room
    a.call("POST", "/api/voice/join", {"ch": voice_d})
    s, r = a.call("POST", "/api/channel/delete", {"ch": voice_d})
    check("delete a voice channel", s == 200, r)
    check("deleted voice room is gone", a.call("GET", f"/api/voice?ch={voice_d}")[0] == 404)

    # ---------------------------------------------------------------- SSE disconnect frees the seat
    e1.call("POST", "/api/voice/leave", {"ch": voice_b})
    se1, _, ebuf = sse_open(e1)
    e1.call("POST", "/api/voice/join", {"ch": voice_b})
    se1.close()
    e2 = extras[1]
    e2.call("POST", "/api/voice/join", {"ch": voice_b})
    time.sleep(0.8)
    s, r = a.call("GET", f"/api/voice?ch={voice_b}")
    check("closing the last SSE connection frees the voice seat",
          s == 200 and all(p["uid"] != uid(e1) for p in r["participants"]), r)
    e2.call("POST", "/api/voice/leave", {"ch": voice_b})

    # ---------------------------------------------------------------- regression: text chat still live
    check("text chat still sends", b.call("POST", "/api/ch/send", {"ch": textch, "text": "voice phase done"})[0] in (200, 403))
    check("voice routes are independent of chat", a.call("GET", "/api/servers")[0] == 200)
finally:
    srv.terminate()
    try:
        outp, _ = srv.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        srv.kill()
        outp = b""
    tail = str(outp or "")[-1800:]
    if "Traceback" in tail:
        print(tail)

print("\nALL OK" if ok else "\nFAILURES")
sys.exit(0 if ok else 1)
