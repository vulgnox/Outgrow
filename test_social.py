"""Social layer tests: schema/mapping, permissions matrix, chat API, SSE, reactions, receipts."""
import json, os, sys, time, urllib.request, http.cookiejar, subprocess, tempfile, signal, socket, sqlite3

PORT = 8801
tmp = tempfile.mkdtemp()
env = dict(os.environ, PORT=str(PORT), RAGDAMAXING_DB=os.path.join(tmp, "t.db"), RAGDAMAXING_ADMINS="zenx")
srv = subprocess.Popen([sys.executable, "server.py"], env=env, cwd=os.path.dirname(os.path.abspath(__file__)),
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
time.sleep(1.5)


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
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def cookie(self):
        return next((c.value for c in self.cj if c.name == "og"), "")


ok = True


def check(name, cond, extra=""):
    global ok
    print(("PASS " if cond else "FAIL ") + name, extra if not cond else "")
    ok = ok and cond


def sse_open(client, timeout=8):
    """Raw socket so we can assert on the actual event stream."""
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


def sse_event(s, buf, want, timeout=8):
    """Read until one event block named `want`. Returns (data or None, buffer)."""
    s.settimeout(timeout)
    end = time.time() + timeout
    while time.time() < end:
        text = buf.decode(errors="replace")
        for block in text.split("\n\n"):
            if ("event: %s" % want) in block.splitlines():
                data = next((ln[6:] for ln in block.splitlines() if ln.startswith("data: ")), "")
                try:
                    return json.loads(data), buf
                except ValueError:
                    pass
        try:
            chunk = s.recv(4096)
        except socket.timeout:
            break
        if not chunk:
            break
        buf += chunk
    return None, buf


try:
    a, b, o, anon = Client(), Client(), Client(), Client()
    s, r = a.call("POST", "/api/register", {"username": "Zenx", "pin": "1234", "crew_name": "SocCrew"})
    check("register owner", s == 200, r)
    code = a.call("GET", "/api/crew")[1]["crew"]["code"]
    s, r = b.call("POST", "/api/register", {"username": "krit", "pin": "abcd", "crew_code": code})
    check("register member", s == 200, r)
    s, r = o.call("POST", "/api/register", {"username": "outsider", "pin": "abcd", "crew_name": "OtherCrew"})
    check("register outsider (own crew)", s == 200, r)
    uid_b = b.call("GET", "/api/me")[1]["user"]["id"]

    # ---- schema + default server mapping
    s, r = a.call("GET", "/api/servers")
    check("servers auto-created for crew", s == 200 and len(r["servers"]) == 1, r)
    srvj = r["servers"][0]
    names = [c["name"] for c in srvj["channels"]]
    check("default channels", names == ["general", "study-wins"], names)
    check("members auto-joined", srvj["members"] == 2, srvj["members"])
    gid = next(c["id"] for c in srvj["channels"] if c["name"] == "general")
    wid = next(c["id"] for c in srvj["channels"] if c["name"] == "study-wins")
    check("owner perms are all", srvj["perms"] > 0)
    s, r2 = b.call("GET", "/api/servers")
    check("member sees same server", s == 200 and r2["servers"][0]["id"] == srvj["id"])
    s, r3 = o.call("GET", "/api/servers")
    check("outsider sees only own server", s == 200 and r3["servers"][0]["id"] != srvj["id"])

    # ---- send + legacy mapping
    s, r = a.call("POST", "/api/ch/send", {"ch": gid, "text": "hello crew"})
    check("owner sends to #general", s == 200 and r["message"]["id"], r)
    mid1 = r["message"]["id"]
    s, r = a.call("GET", "/api/chat/messages?thread=crew")
    check("legacy crew room sees the same message", s == 200 and any(m["id"] == mid1 for m in r["messages"]), r)
    s, r = b.call("GET", f"/api/ch/messages?ch={gid}")
    check("member reads channel", s == 200 and any(m["id"] == mid1 for m in r["messages"]), r)
    check("anon is refused", anon.call("GET", f"/api/ch/messages?ch={gid}")[0] == 401)
    check("outsider cannot read (404)", o.call("GET", f"/api/ch/messages?ch={gid}")[0] == 404)

    # ---- IDOR matrix: every route x outsider/anon
    matrix = [
        ("GET", f"/api/ch/messages?ch={gid}", None),
        ("POST", "/api/ch/send", {"ch": gid, "text": "nope"}),
        ("POST", "/api/ch/edit", {"ch": gid, "id": mid1, "text": "nope"}),
        ("POST", "/api/ch/delete", {"ch": gid, "id": mid1}),
        ("POST", "/api/ch/react", {"ch": gid, "id": mid1, "emoji": "🔥"}),
        ("POST", "/api/ch/typing", {"ch": gid}),
        ("POST", "/api/ch/read", {"ch": gid, "id": mid1}),
        ("GET", f"/api/ch/search?ch={gid}&q=hello", None),
    ]
    for method, path, body in matrix:
        st = o.call(method, path, body)[0]
        check("outsider blocked %s %s" % (method, path.split("?")[0]), st in (403, 404), st)
        st = anon.call(method, path, body)[0]
        check("anon blocked %s %s" % (method, path.split("?")[0]), st == 401, st)

    # ---- permission bits: strip send from @everyone
    db = sqlite3.connect(env["RAGDAMAXING_DB"])
    db.execute("UPDATE roles SET perms=1 WHERE server_id=? AND is_default=1", (srvj["id"],))  # view only
    db.commit()
    check("member without send bit is refused", b.call("POST", "/api/ch/send", {"ch": gid, "text": "x"})[0] == 403)
    check("member can still read", b.call("GET", f"/api/ch/messages?ch={gid}")[0] == 200)
    check("owner bypasses bits", a.call("POST", "/api/ch/send", {"ch": gid, "text": "owner still talks"})[0] == 200)
    db.execute("UPDATE roles SET perms=31 WHERE server_id=? AND is_default=1", (srvj["id"],))
    db.commit()

    # ---- timeout
    db.execute("INSERT OR REPLACE INTO timeouts(server_id,user_id,until,by_id,reason) VALUES(?,?,?,?,?)",
               (srvj["id"], uid_b, time.time() + 600, 1, "test"))
    db.commit()
    check("timed out member cannot send", b.call("POST", "/api/ch/send", {"ch": gid, "text": "x"})[0] == 403)
    check("timed out member can read", b.call("GET", f"/api/ch/messages?ch={gid}")[0] == 200)
    db.execute("DELETE FROM timeouts WHERE server_id=? AND user_id=?", (srvj["id"], uid_b))
    db.commit()
    s, r = b.call("POST", "/api/ch/send", {"ch": gid, "text": "from b"})
    check("member sends after timeout", s == 200, r)
    mid_b = r["message"]["id"]

    # ---- multi-emoji reactions
    s, r = b.call("POST", "/api/ch/react", {"ch": gid, "id": mid1, "emoji": "🔥"})
    check("react adds", s == 200 and r["re"].get("🔥") == 1, r)
    s, r = b.call("POST", "/api/ch/react", {"ch": gid, "id": mid1, "emoji": "👍"})
    check("second emoji from same user", s == 200 and r["re"].get("👍") == 1 and len(r["re"]) == 2, r)
    s, r = b.call("POST", "/api/ch/react", {"ch": gid, "id": mid1, "emoji": "🔥"})
    check("toggle removes one emoji", s == 200 and "🔥" not in r["re"], r)
    check("bad emoji rejected", b.call("POST", "/api/ch/react", {"ch": gid, "id": mid1, "emoji": "<b>"})[0] == 400)
    s, r = b.call("GET", f"/api/ch/messages?ch={gid}")
    m1 = next(m for m in r["messages"] if m["id"] == mid1)
    check("reactions come back on read", m1["re"].get("👍") == 1 and m1["mine"] == ["👍"], m1)

    # ---- edit / delete / moderator delete
    check("cannot edit someone else's message", b.call("POST", "/api/ch/edit", {"ch": gid, "id": mid1, "text": "hax"})[0] == 403)
    s, r = a.call("POST", "/api/ch/edit", {"ch": gid, "id": mid1, "text": "hello crew (edited)"})
    check("edit own message", s == 200 and r["text"].endswith("(edited)"), r)
    check("cannot delete someone else's message (member)", b.call("POST", "/api/ch/delete", {"ch": gid, "id": mid1})[0] == 403)
    check("owner can delete a member's message", a.call("POST", "/api/ch/delete", {"ch": gid, "id": mid_b})[0] == 200)
    s, r = b.call("GET", f"/api/ch/messages?ch={gid}")
    check("deleted message is gone", all(m["id"] != mid_b for m in r["messages"]))

    # ---- replies + paging + search
    s, r = a.call("POST", "/api/ch/send", {"ch": gid, "text": "reply text", "reply_to": mid1})
    check("reply accepted", s == 200 and r["message"]["reply"]["id"] == mid1, r)
    mids = []
    for i in range(3):
        s, r = a.call("POST", "/api/ch/send", {"ch": gid, "text": "page %d" % i})
        mids.append(r["message"]["id"])
    s, r = a.call("GET", f"/api/ch/messages?ch={gid}&before={mids[0]}")
    check("history paging", s == 200 and r["messages"] and all(m["id"] < mids[0] for m in r["messages"]), r)
    s, r = a.call("GET", f"/api/ch/search?ch={gid}&q=page")
    check("search finds messages", s == 200 and len(r["results"]) == 3, r)
    check("search needs 2 chars", a.call("GET", f"/api/ch/search?ch={gid}&q=p")[1]["results"] == [])

    # ---- read receipts + typing
    b.call("GET", f"/api/ch/messages?ch={gid}&mark=1")
    s, r = a.call("GET", f"/api/ch/messages?ch={gid}")
    check("read receipts returned", str(uid_b) in r["reads"] and r["reads"][str(uid_b)] > 0, r["reads"])
    check("typing accepted", b.call("POST", "/api/ch/typing", {"ch": wid})[0] == 200)
    s, r = a.call("GET", f"/api/ch/messages?ch={wid}")
    check("typing visible to others", uid_b in r["typing"], r["typing"])
    s, r = a.call("GET", "/api/ch/unread")
    check("unread counts by channel", s == 200 and "total" in r and "ch" in r, r)

    # ---- SSE
    sa, head, buf = sse_open(a)
    check("stream is text/event-stream", "text/event-stream" in head, head)
    hello, buf = sse_event(sa, buf, "hello")
    check("stream hello identifies user", hello and hello.get("uid") == a.call("GET", "/api/me")[1]["user"]["id"], hello)
    s, r = b.call("POST", "/api/ch/send", {"ch": gid, "text": "sse ping"})
    ev, buf = sse_event(sa, buf, "msg")
    check("live message arrives over SSE", ev and ev.get("ch") == gid and ev["message"]["text"] == "sse ping", ev)
    mid_live = ev["message"]["id"] if ev else 0
    b.call("POST", "/api/ch/react", {"ch": gid, "id": mid_live, "emoji": "🎉"})
    rev, buf = sse_event(sa, buf, "react")
    check("live reaction arrives over SSE", rev and rev.get("id") == mid_live and rev["re"].get("🎉") == 1, rev)
    a.call("POST", "/api/ch/typing", {"ch": gid})
    b.call("POST", "/api/ch/typing", {"ch": gid})
    tyv, buf = sse_event(sa, buf, "typing")
    check("live typing arrives over SSE", tyv and tyv.get("ch") == gid, tyv)
    sa.close()

    # stream cap: three connections per user, the fourth is refused
    socks = []
    for i in range(3):
        s2, h2, b2 = sse_open(b)
        socks.append(s2)
        ev, b2 = sse_event(s2, b2, "hello")
        check("stream connection %d opened" % (i + 1), ev is not None, h2[-80:])
    s4, h4, b4 = sse_open(b)
    check("fourth live connection refused", "429" in h4.splitlines()[0], h4[:60])
    s4.close()
    for s2 in socks:
        s2.close()

    # ---- rate limit (fresh member so earlier sends do not matter)
    rl = Client()
    rl.call("POST", "/api/register", {"username": "ratelim", "pin": "abcd", "crew_code": code})
    codes = [rl.call("POST", "/api/ch/send", {"ch": gid, "text": "spam %d" % i})[0] for i in range(11)]
    check("message rate limit (10 / 10s)", codes[:10] == [200] * 10 and codes[10] == 429, codes)

    # ---- regression: legacy chat endpoints still work
    s, r = a.call("GET", "/api/chat/threads")
    check("legacy threads still work", s == 200 and any(t["kind"] == "crew" for t in r["threads"]), r)
    s, r = a.call("POST", "/api/chat/send", {"thread": "crew", "text": "old client still here"})
    check("legacy send still works", s == 200, r)
    s, r = b.call("GET", f"/api/ch/messages?ch={gid}")
    check("legacy message appears in channel", any(m["text"] == "old client still here" for m in r["messages"]), r)

    # ---- external crew cannot join by channel id guess
    s, r = o.call("GET", "/api/servers")
    other_gid = r["servers"][0]["channels"][0]["id"]
    check("other crew's channel works for its owner", o.call("GET", f"/api/ch/messages?ch={other_gid}")[0] == 200)
    check("crew 1 member cannot read crew 2", b.call("GET", f"/api/ch/messages?ch={other_gid}")[0] == 404)
    check("global admin may moderate any server", a.call("GET", f"/api/ch/messages?ch={other_gid}")[0] == 200)
finally:
    srv.send_signal(signal.SIGTERM)
    out = srv.stdout.read()
    if "Traceback" in out:
        print("SERVER TRACEBACK:\n", out)
        ok = False
print("ALL OK" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
