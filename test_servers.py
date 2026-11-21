"""Phase 2: server/channel/role CRUD, invites, moderation, audit, friends, blocks, DM rules."""
import json, os, sys, time, urllib.request, http.cookiejar, subprocess, tempfile, signal, sqlite3

PORT = 8803
tmp = tempfile.mkdtemp()
env = dict(os.environ, PORT=str(PORT), RAGDAMAXING_DB=os.path.join(tmp, "t.db"), RAGDAMAXING_ADMINS="boss")
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


ok = True


def check(name, cond, extra=""):
    global ok
    print(("PASS " if cond else "FAIL ") + name, extra if not cond else "")
    ok = ok and cond


def uid(cl):
    return cl.call("GET", "/api/me")[1]["user"]["id"]


try:
    a, b, c, boss = Client(), Client(), Client(), Client()
    a.call("POST", "/api/register", {"username": "owner", "pin": "1234", "crew_name": "Alpha"})
    code_a = a.call("GET", "/api/crew")[1]["crew"]["code"]
    b.call("POST", "/api/register", {"username": "moduser", "pin": "1234", "crew_code": code_a})
    c.call("POST", "/api/register", {"username": "outsider", "pin": "1234", "crew_name": "Beta"})
    boss.call("POST", "/api/register", {"username": "boss", "pin": "1234", "crew_name": "BossCrew"})
    ua, ub, uc = uid(a), uid(b), uid(c)
    crew_sid = a.call("GET", "/api/servers")[1]["servers"][0]["id"]

    # ---- create server + caps
    s, r = a.call("POST", "/api/server/create", {"name": "Study Hall", "icon": "📚"})
    check("create server", s == 200 and r["server_id"], r)
    sid = r["server_id"]
    s, r = a.call("GET", f"/api/server?sid={sid}")
    check("new server has general + roles", s == 200 and [x["name"] for x in r["channels"]] == ["general"]
          and {x["name"] for x in r["roles"]} == {"@everyone", "Admin"}, r)
    check("owner perms in new server", r["me"]["perm"] > 0 if "perm" in r["me"] else r["me"]["perms"] > 0)
    for i in range(2):
        check("create server %d" % (i + 2), a.call("POST", "/api/server/create", {"name": "Extra %d" % i})[0] == 200)
    check("owned server cap (3)", a.call("POST", "/api/server/create", {"name": "One Too Many"})[0] == 403)
    check("bad server name rejected", a.call("POST", "/api/server/create", {"name": "x"})[0] == 400)

    # ---- invites
    s, r = a.call("POST", "/api/invite/create", {"sid": sid, "days": 7, "max_uses": 5})
    check("create invite", s == 200 and len(r["code"]) == 8, r)
    inv = r["code"]
    plain = Client()
    plain.call("POST", "/api/register", {"username": "plainuser", "pin": "1234", "crew_code": code_a})
    plain.call("POST", "/api/server/join", {"code": inv})
    s, r = plain.call("POST", "/api/invite/create", {"sid": sid})
    check("member cannot create invite", s == 403, (s, r))
    s, r = b.call("POST", "/api/server/join", {"code": inv})
    check("join by invite", s == 200 and r["server_id"] == sid, r)
    check("join is idempotent", b.call("POST", "/api/server/join", {"code": inv})[0] == 200)
    check("outsider is not a member yet", c.call("GET", f"/api/server?sid={sid}")[0] == 404)
    s, r = c.call("POST", "/api/server/join", {"code": "NOPENOPE"})
    check("bad code rejected", s == 404, r)

    # expiry + uses, written directly so the clock is unambiguous
    db = sqlite3.connect(env["RAGDAMAXING_DB"])
    db.execute("INSERT INTO invites(code,server_id,created_by,created_at,expires,max_uses,uses) VALUES(?,?,?,?,?,0,0)",
               ("EXPIRED1", sid, ua, "2020-01-01T00:00:00", "2020-01-02T00:00:00"))
    db.execute("INSERT INTO invites(code,server_id,created_by,created_at,expires,max_uses,uses) VALUES(?,?,?,?,?,1,0)",
               ("ONESHOT1", sid, ua, "2020-01-01T00:00:00", ""))
    db.commit()
    check("expired invite refused", c.call("POST", "/api/server/join", {"code": "EXPIRED1"})[0] == 410)
    check("single-use invite joins", c.call("POST", "/api/server/join", {"code": "ONESHOT1"})[0] == 200)
    c.call("POST", "/api/server/leave", {"sid": sid})
    check("used-up invite refused", c.call("POST", "/api/server/join", {"code": "ONESHOT1"})[0] == 410)
    a.call("POST", "/api/invite/revoke", {"sid": sid, "code": "EXPIRED1"})
    check("revoked invite refused", c.call("POST", "/api/server/join", {"code": "EXPIRED1"})[0] == 404)

    # ---- channels
    s, r = a.call("POST", "/api/channel/create", {"sid": sid, "name": "Maths", "kind": "text"})
    check("owner creates channel", s == 200 and r["name"] == "maths", r)
    ch_maths = r["channel_id"]
    check("member cannot create channel (no bit)", b.call("POST", "/api/channel/create", {"sid": sid, "name": "x1"})[0] == 403)
    s, r = a.call("POST", "/api/channel/update", {"ch": ch_maths, "name": "maths-12", "topic": "Integration"})
    check("rename channel", s == 200, r)
    s, r = a.call("GET", f"/api/server?sid={sid}")
    check("channel rename visible", any(x["name"] == "maths-12" and x["topic"] == "Integration" for x in r["channels"]))
    check("duplicate channel name handled", a.call("POST", "/api/channel/create", {"sid": sid, "name": "maths-12"})[1]["name"] == "maths-12-2")
    check("delete a channel", a.call("POST", "/api/channel/delete", {"ch": ch_maths})[0] == 200)
    s, r = a.call("GET", f"/api/server?sid={sid}")
    general_ch = next(x["id"] for x in r["channels"] if x["name"] == "general")
    for x in r["channels"]:
        if x["id"] != general_ch:
            a.call("POST", "/api/channel/delete", {"ch": x["id"]})
    check("last text channel is protected", a.call("POST", "/api/channel/delete", {"ch": general_ch})[0] == 400)
    crew_ch = a.call("GET", f"/api/server?sid={crew_sid}")[1]["channels"][0]["id"]
    check("legacy crew channel is protected", a.call("POST", "/api/channel/delete", {"ch": crew_ch})[0] == 400)

    # ---- roles + privilege escalation
    s, r = a.call("POST", "/api/role/create", {"sid": sid, "name": "Helper", "color": "#34d3a0", "perms": 258})  # send|manage_channels
    check("owner creates role", s == 200, r)
    helper = r["role_id"]
    s, r = a.call("POST", "/api/role/assign", {"sid": sid, "role": helper, "uid": ub, "on": True})
    check("assign role", s == 200, r)
    s, r = b.call("GET", f"/api/roles?sid={sid}")
    check("member sees roles", s == 200 and any(x["id"] == helper and ub in x["members"] for x in r["roles"]), r)
    s, r = b.call("POST", "/api/channel/create", {"sid": sid, "name": "by-mod"})
    check("delegated manage_channels works", s == 200, r)
    s, r = b.call("POST", "/api/role/create", {"sid": sid, "name": "Sneaky", "perms": 32767})
    check("role creation refused without manage_roles", s == 403, r)
    s, r = a.call("POST", "/api/role/create", {"sid": sid, "name": "Mod", "perms": 16383})  # almost everything
    modrole = r["role_id"]
    a.call("POST", "/api/role/assign", {"sid": sid, "role": modrole, "uid": ub})
    s, r = b.call("POST", "/api/role/create", {"sid": sid, "name": "Escalate", "perms": 32767})
    check("moderator can create a role", s == 200, r)
    esc = r["role_id"]
    s, r = b.call("GET", f"/api/roles?sid={sid}")
    er = next(x for x in r["roles"] if x["id"] == esc)
    allowed = 31 | 16383
    check("role perms are masked to the creator's bits", er["perms"] == (32767 & allowed), er["perms"])
    check("cannot assign @everyone", a.call("POST", "/api/role/assign", {"sid": sid, "role": next(x["id"] for x in r["roles"] if x["default"]), "uid": ub, "on": True})[0] == 400)
    check("cannot delete @everyone", a.call("POST", "/api/role/delete", {"sid": sid, "role": next(x["id"] for x in r["roles"] if x["default"])})[0] == 400)

    # ---- moderation
    db.execute("INSERT OR REPLACE INTO timeouts(server_id,user_id,until,by_id,reason) VALUES(?,?,?,?,?)",
               (sid, ub, time.time() + 600, ua, "test"))
    db.commit()
    s, r = b.call("POST", "/api/ch/send", {"ch": general_ch, "text": "during timeout"})
    check("timeout blocks send", s == 403, r)
    check("timeout still allows read", b.call("GET", f"/api/ch/messages?ch={general_ch}")[0] == 200)
    s, r = a.call("POST", "/api/mod/untimeout", {"sid": sid, "uid": ub})
    check("untimeout", s == 200, r)
    check("send works after timeout", b.call("POST", "/api/ch/send", {"ch": general_ch, "text": "free again"})[0] == 200)
    check("member cannot kick", b.call("POST", "/api/mod/kick", {"sid": sid, "uid": ua})[0] == 403)
    check("cannot kick owner", b.call("POST", "/api/mod/kick", {"sid": sid, "uid": ua})[0] in (403, 400))
    s, r = a.call("POST", "/api/mod/kick", {"sid": sid, "uid": ub})
    check("owner kicks member", s == 200, r)
    check("kicked member loses access", b.call("GET", f"/api/server?sid={sid}")[0] == 404)
    s, r = b.call("POST", "/api/server/join", {"code": inv})
    check("kicked member can rejoin with invite", s == 200, r)
    s, r = a.call("POST", "/api/mod/ban", {"sid": sid, "uid": ub, "reason": "spam"})
    check("ban member", s == 200, r)
    check("banned member loses access", b.call("GET", f"/api/server?sid={sid}")[0] == 404)
    check("banned member cannot rejoin", b.call("POST", "/api/server/join", {"code": inv})[0] == 403)
    s, r = a.call("GET", f"/api/bans?sid={sid}")
    check("ban list", s == 200 and any(x["id"] == ub for x in r["bans"]), r)
    check("unban", a.call("POST", "/api/mod/unban", {"sid": sid, "uid": ub})[0] == 200)
    check("rejoin after unban", b.call("POST", "/api/server/join", {"code": inv})[0] == 200)

    # ---- audit
    s, r = a.call("GET", f"/api/audit?sid={sid}")
    check("audit log has entries", s == 200 and len(r["audit"]) >= 6, r)
    acts = {x["action"] for x in r["audit"]}
    check("audit covers create/kick/ban", {"server.create", "member.kick", "member.ban"} <= acts, acts)
    check("plain member cannot read audit", plain.call("GET", f"/api/audit?sid={sid}")[0] == 403)
    check("plain member cannot kick", plain.call("POST", "/api/mod/kick", {"sid": sid, "uid": ub})[0] == 403)

    # ---- reports
    s, r = a.call("POST", "/api/ch/send", {"ch": general_ch, "text": "something reportable"})
    mid = r["message"]["id"]
    s, r = b.call("POST", "/api/report", {"id": mid, "reason": "rude"})
    check("member can report a message", s == 200, r)
    check("reports are admin-only", a.call("GET", "/api/reports")[0] == 403)
    s, r = boss.call("GET", "/api/reports")
    check("global admin sees reports", s == 200 and any(x["message"] == mid for x in r["reports"]), r)
    check("report count in admin stats", boss.call("GET", "/api/admin/stats")[1]["app"]["reports"] >= 1)

    # ---- friends + DM rules
    s, r = a.call("GET", "/api/friends")
    check("friends starts empty", s == 200 and r["friends"] == [] and r["incoming"] == [], r)
    check("cannot friend yourself", a.call("POST", "/api/friend/request", {"username": "owner"})[0] == 400)
    check("unknown user 404", a.call("POST", "/api/friend/request", {"username": "ghost"})[0] == 404)
    s, r = a.call("POST", "/api/friend/request", {"username": "outsider"})
    check("friend request by username", s == 200, r)
    s, r = c.call("GET", "/api/friends")
    check("incoming request visible", s == 200 and any(x["id"] == ua for x in r["incoming"]), r)
    check("dm to non-friend refused", a.call("POST", "/api/chat/send", {"thread": "dm:%d" % uc, "text": "hi"})[0] == 404)
    s, r = c.call("POST", "/api/friend/accept", {"uid": ua})
    check("accept friend", s == 200, r)
    s, r = a.call("GET", "/api/friends")
    check("friend appears in list", s == 200 and any(x["id"] == uc for x in r["friends"]), r)
    s, r = a.call("POST", "/api/chat/send", {"thread": "dm:%d" % uc, "text": "friends now"})
    check("dm to friend allowed", s == 200, r)
    s, r = c.call("GET", "/api/chat/messages?thread=dm:%d" % ua)
    check("friend dm readable by both", s == 200 and any(m["text"] == "friends now" for m in r["messages"]), r)
    s, r = c.call("POST", "/api/block", {"uid": ua, "on": True})
    check("block", s == 200, r)
    check("blocked dm refused", a.call("POST", "/api/chat/send", {"thread": "dm:%d" % uc, "text": "hello?"})[0] == 404)
    check("block removes friendship", not any(x["id"] == uc for x in a.call("GET", "/api/friends")[1]["friends"]))
    check("blocked friend request refused", a.call("POST", "/api/friend/request", {"username": "outsider"})[0] == 403)
    c.call("POST", "/api/block", {"uid": ua, "on": False})
    check("unblock", a.call("POST", "/api/friend/request", {"username": "outsider"})[0] == 200)

    # when you block someone, their messages are hidden from you (not from everyone)
    a.call("POST", "/api/block", {"uid": ub, "on": True})
    b.call("POST", "/api/ch/send", {"ch": general_ch, "text": "hidden from owner"})
    s, r = a.call("GET", f"/api/ch/messages?ch={general_ch}")
    check("blocked user's messages hidden from the blocker", s == 200 and all(m["text"] != "hidden from owner" for m in r["messages"]), r)
    s, r = b.call("GET", f"/api/ch/messages?ch={general_ch}")
    check("blocked user still sees the room", s == 200 and any(m["text"] == "hidden from owner" for m in r["messages"]), r)
    a.call("POST", "/api/block", {"uid": ub, "on": False})

    # ---- leave + delete
    check("member leaves", b.call("POST", "/api/server/leave", {"sid": sid})[0] == 200)
    check("left server is gone", b.call("GET", f"/api/server?sid={sid}")[0] == 404)
    check("owner cannot leave own server", a.call("POST", "/api/server/leave", {"sid": sid})[0] in (400, 403))
    s, r = a.call("GET", "/api/servers")
    extra = next(x["id"] for x in r["servers"] if x["name"] == "Extra 0")
    check("delete extra server", a.call("POST", "/api/server/delete", {"sid": extra})[0] == 200)
    check("deleted server is gone", a.call("GET", f"/api/server?sid={extra}")[0] == 404)
    check("crew server cannot be deleted", a.call("POST", "/api/server/delete", {"sid": crew_sid})[0] in (400, 403))

    # ---- IDOR matrix on the new routes
    outsider_calls = [
        ("GET", f"/api/server?sid={sid}", None),
        ("POST", "/api/server/update", {"sid": sid, "name": "hax"}),
        ("POST", "/api/server/delete", {"sid": sid}),
        ("POST", "/api/invite/create", {"sid": sid}),
        ("POST", "/api/channel/create", {"sid": sid, "name": "hax"}),
        ("POST", "/api/channel/update", {"ch": general_ch, "name": "hax"}),
        ("POST", "/api/channel/delete", {"ch": general_ch}),
        ("GET", f"/api/roles?sid={sid}", None),
        ("POST", "/api/role/create", {"sid": sid, "name": "hax"}),
        ("POST", "/api/mod/kick", {"sid": sid, "uid": ub}),
        ("POST", "/api/mod/ban", {"sid": sid, "uid": ub}),
        ("GET", f"/api/audit?sid={sid}", None),
        ("GET", f"/api/bans?sid={sid}", None),
    ]
    for method, path, body in outsider_calls:
        st = c.call(method, path, body)[0]
        check("outsider blocked %s %s" % (method, path.split("?")[0]), st in (403, 404), st)
    check("anon blocked server detail", Client().call("GET", f"/api/server?sid={sid}")[0] == 401)
    check("anon blocked server create", Client().call("POST", "/api/server/create", {"name": "x"})[0] == 401)
finally:
    srv.send_signal(signal.SIGTERM)
    out = srv.stdout.read()
    if "Traceback" in out:
        print("SERVER TRACEBACK:\n", out)
        ok = False
print("ALL OK" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
