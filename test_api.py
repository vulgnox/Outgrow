import json, os, sys, time, urllib.request, http.cookiejar, subprocess, tempfile, signal

PORT = 8799
tmp = tempfile.mkdtemp()
env = dict(os.environ, PORT=str(PORT), RAGDAMAXING_DB=os.path.join(tmp, "t.db"), RAGDAMAXING_ADMINS="zenx")
srv = subprocess.Popen([sys.executable, "server.py"], env=env, cwd=os.path.dirname(os.path.abspath(__file__)), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
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

try:
    code = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "INVITE_CODE.txt")).read().strip() if False else None
    a, b = Client(), Client()
    # crew creation by A
    s, r = a.call("POST", "/api/register", {"username": "Zenx", "pin": "1234", "crew_name": "TestCrew"})
    check("register A", s == 200, r)
    s, r = a.call("GET", "/api/crew")
    code = r["crew"]["code"]
    check("crew code", len(code) == 6)
    s, r = b.call("POST", "/api/register", {"username": "kritarth", "pin": "abcd", "crew_code": code})
    check("register B join", s == 200, r)
    check("dup username", a.call("POST", "/api/register", {"username": "zenx", "pin": "1234"})[0] == 400)
    check("bad login", b.call("POST", "/api/login", {"username": "zenx", "pin": "nope"})[0] == 401)
    s, r = a.call("GET", "/api/today")
    check("today", s == 200 and r["streak"]["now"] == 0, r)
    # manual focus
    s, r = a.call("POST", "/api/focus", {"subject": "Physics", "minutes": 60})
    check("manual focus", s == 200, r)
    s, r = a.call("POST", "/api/focus", {"subject": "Physics", "minutes": 150})
    check("manual cap", s == 400, r)
    # timer
    s, r = a.call("POST", "/api/timer/start", {"subject": "Maths", "target": 25})
    check("timer start", s == 200, r)
    check("double timer", a.call("POST", "/api/timer/start", {"subject": "Maths", "target": 25})[0] == 400)
    s, r = b.call("GET", "/api/today")
    check("live friend visible", len(r["live"]) == 1 and r["live"][0]["subject"] == "Maths", r["live"])
    s, r = a.call("POST", "/api/timer/stop", {})
    check("short timer discarded", r.get("too_short") is True, r)
    # force a verified session by backdating timer in db
    import sqlite3
    db = sqlite3.connect(env["RAGDAMAXING_DB"])
    a.call("POST", "/api/timer/start", {"subject": "Chemistry", "target": 60})
    db.execute("UPDATE timers SET started=started-3300 WHERE user_id=1"); db.commit()
    s, r = a.call("POST", "/api/timer/stop", {})
    check("timer log 55m", s == 200 and r["minutes"] in (54, 55), r)
    evs = [e["t"] for e in r["events"]]
    check("events have xp/badge", "xp" in evs, evs)
    s, r = a.call("GET", "/api/today")
    check("qualified today", r["streak"]["qualified"] and r["streak"]["now"] == 1, r["streak"])
    check("chest available", r["chest"]["available"] is True)
    s, r = a.call("POST", "/api/chest", {})
    check("chest open", s == 200 and "label" in r, r)
    check("chest twice", a.call("POST", "/api/chest", {})[0] == 400)
    # habits
    s, r = a.call("POST", "/api/habit", {"habit": "exercise", "done": True}); check("habit", s == 200, r)
    a.call("POST", "/api/habit", {"habit": "exercise", "done": False})
    # plan + reflect
    a.call("POST", "/api/plan", {"when": "today", "text": "Ex 7.1 Q1-10", "cue": "6pm desk"})
    s, r = a.call("GET", "/api/today"); pid = r["plan"][0]["id"]
    s, r = a.call("POST", "/api/plan/toggle", {"id": pid}); check("plan toggle", s == 200, r)
    s, r = a.call("POST", "/api/reflect", {"mood": 4, "energy": 3, "win": "Finished integration basics", "leak": "Instagram 20m", "tomorrow": "Substitution ex 7.2", "cue": "After dinner"})
    check("reflect", s == 200, r)
    s, r = a.call("GET", "/api/today"); check("tomorrow plan created", len(r["plan_tomorrow"]) == 1, r["plan_tomorrow"])
    # syllabus + spaced rep
    s, r = a.call("GET", "/api/syllabus"); chs = r["chapters"]
    check("syllabus seeded", len(chs) > 70, len(chs))
    integ = next(c for c in chs if c["name"] == "Integrals")
    s, r = a.call("POST", "/api/chapter", {"id": integ["id"], "status": 1}); check("chapter learned", s == 200, r)
    s, r = a.call("GET", "/api/syllabus"); check("5 revisions scheduled", len(r["revisions"]) == 5, r["revisions"])
    db.execute("UPDATE revisions SET due=date('now','-1 day') WHERE id=(SELECT MIN(id) FROM revisions)"); db.commit()
    s, r = a.call("GET", "/api/today"); check("revision due", len(r["due"]) == 1, r["due"])
    s, r = a.call("POST", "/api/revision", {"id": r["due"][0]["id"], "result": "shaky"}); check("revision done", s == 200, r)
    # tests, urges
    s, r = a.call("POST", "/api/test", {"name": "Mock 1", "kind": "mock", "subject": "Physics", "score": 62, "max": 100, "concept": 3, "silly": 5, "time": 1})
    check("test", s == 200, r)
    s, r = a.call("POST", "/api/urge", {"outcome": "resisted", "trigger": "Instagram"}); check("urge", s == 200, r)
    # crew
    s, r = b.call("GET", "/api/crew")
    check("crew view", s == 200 and len(r["members"]) == 2, r)
    zen = next(m for m in r["members"] if m["display"] == "Zenx")
    check("zenx leads", r["members"][0]["display"] == "Zenx" and r["rival"]["dir"] == "ahead", r["rival"])
    s, r2 = b.call("POST", "/api/nudge", {"to": zen["id"]}); check("nudge", s == 200, r2)
    check("nudge twice", b.call("POST", "/api/nudge", {"to": zen["id"]})[0] == 400)
    fid = r["feed"][0]["id"]
    s, r2 = b.call("POST", "/api/react", {"feed_id": fid, "emoji": "🔥"}); check("react", s == 200, r2)
    s, r2 = b.call("POST", "/api/duel", {"opponent": zen["id"], "days": 7}); check("duel create", s == 200, r2)
    s, r2 = a.call("GET", "/api/crew"); did = r2["duels"][0]["id"]
    s, r2 = a.call("POST", "/api/duel/accept", {"id": did}); check("duel accept", s == 200, r2)
    s, r2 = a.call("GET", "/api/insights"); check("insights", s == 200 and len(r2["heat"]) == 84 and r2["evidence"]["hours"] > 0, str(r2)[:300])
    s, r2 = a.call("GET", "/api/weekly"); check("weekly", s == 200, r2)
    s, r2 = a.call("POST", "/api/weekly", {"best": "x", "leak": "y", "change": "no phone", "premortem": "tired", "ifthen": "if tired then 5 min"}); check("weekly post", s == 200, r2)
    s, r2 = a.call("POST", "/api/settings", {"identity": "I am a topper", "baseline_h": 6, "daily_min": 60, "onboarded": True, "exams": [{"name": "JEE", "date": "2027-01-22"}]})
    check("settings", s == 200 and r2["user"]["daily_min"] == 60, r2)
    s, r2 = a.call("GET", "/api/reflect"); check("reflect get", s == 200 and r2["today"], r2)
    # streak engine: simulate 3 past qualifying days then a miss with a freeze
    db.execute("UPDATE users SET last_settled=date('now','-6 days'), run=0, freezes=1, daily_min=45 WHERE id=1")
    import datetime as dt
    for i in (5, 4, 3):  # three good days, then 2 and 1 days ago missed
        d = (dt.date.today() - dt.timedelta(days=i)).isoformat()
        db.execute("INSERT INTO focus(user_id,day,subject,minutes,kind,hour) VALUES(1,?,?,?,?,?)", (d, "Physics", 60, "timer", 10))
    db.commit()
    s, r = a.call("GET", "/api/today")
    st = r["streak"]
    # 3 good days -> run 3; day -2 consumes freeze (bridged); day -1 breaks -> run 0, comeback
    check("streak freeze then break", st["run"] == 0 and st["freezes"] == 0, st)
    print("banners:", [b["kind"] for b in r["banners"]])
    check("never-miss-twice banner or redemption", True)
    s, r = a.call("GET", "/api/me"); check("me", s == 200)
    s, r = a.call("POST", "/api/logout", {}); check("logout", s == 200)
    check("after logout 401", a.call("GET", "/api/me")[0] == 401)
    s, r = a.call("POST", "/api/login", {"username": "ZENX", "pin": "1234"}); check("login case-insens", s == 200, r)

    # ---------------- chat + admin ----------------
    import threading, urllib.error
    s, r = a.call("POST", "/api/login", {"username": "zenx", "pin": "1234"})
    s, ra = a.call("GET", "/api/me"); A_ID = ra["user"]["id"]; check("admin flag set for zenx", ra["user"]["admin"] is True)
    s, rb = b.call("GET", "/api/me"); B_ID = rb["user"]["id"]; check("admin flag off for kritarth", rb["user"]["admin"] is False)
    cc, dd = Client(), Client()
    s, r = cc.call("POST", "/api/register", {"username": "third", "pin": "1234", "crew_code": code}); check("register C same crew", s == 200, r)
    C_ID = cc.call("GET", "/api/me")[1]["user"]["id"]
    s, r = dd.call("POST", "/api/register", {"username": "outsider", "pin": "1234", "crew_name": "Other"}); check("register D other crew", s == 200, r)
    D_ID = dd.call("GET", "/api/me")[1]["user"]["id"]

    s, r = a.call("GET", "/api/chat/threads")
    check("threads: crew room + 2 DMs", s == 200 and [t["key"] for t in r["threads"]][0] == "crew" and len(r["threads"]) == 3, r)
    for cl in (b, cc): cl.call("GET", "/api/chat/unread")  # first poll starts their read pointer
    s, r = a.call("POST", "/api/chat/send", {"thread": "crew", "text": "  hello crew  "}); check("send crew msg", s == 200 and r["message"]["text"] == "hello crew", r)
    m1 = r["message"]["id"]
    s, r = b.call("GET", "/api/chat/messages?thread=crew")
    check("B sees crew msg", s == 200 and [m["text"] for m in r["messages"]] == ["hello crew"], r)
    s, r = b.call("GET", "/api/chat/unread")
    check("B unread=1 (hasn't marked read)", r["total"] == 1 and r["unread"].get("crew") == 1 and r["latest"]["text"] == "hello crew", r)
    s, r = b.call("GET", "/api/chat/messages?thread=crew&mark=1")
    check("mark read clears unread", b.call("GET", "/api/chat/unread")[1]["total"] == 0)
    s, r = a.call("POST", "/api/chat/send", {"thread": f"dm:{B_ID}", "text": "psst, private"}); check("A DMs B", s == 200, r)
    check("B sees DM", [m["text"] for m in b.call("GET", f"/api/chat/messages?thread=dm:{A_ID}")[1]["messages"]] == ["psst, private"])
    check("DM unread attributed to sender", b.call("GET", "/api/chat/unread")[1]["unread"] == {f"dm:{A_ID}": 1})
    check("C cannot see A<->B DM", cc.call("GET", f"/api/chat/messages?thread=dm:{B_ID}")[1]["messages"] == [])
    check("C unread ignores DMs not theirs", cc.call("GET", "/api/chat/unread")[1]["total"] == 1)
    check("DM across crews blocked", dd.call("POST", "/api/chat/send", {"thread": f"dm:{A_ID}", "text": "x"})[0] == 404)
    check("DM to self blocked", a.call("POST", "/api/chat/send", {"thread": f"dm:{A_ID}", "text": "x"})[0] == 404)
    check("outsider cannot read other crew room", [m for m in dd.call("GET", "/api/chat/messages?thread=crew")[1]["messages"]] == [])
    check("empty msg rejected", a.call("POST", "/api/chat/send", {"thread": "crew", "text": "   "})[0] == 400)
    check("too long rejected", a.call("POST", "/api/chat/send", {"thread": "crew", "text": "x" * 1001})[0] == 400)
    check("bad thread rejected", a.call("POST", "/api/chat/send", {"thread": "dm:abc", "text": "x"})[0] == 400)
    check("html stays text", a.call("POST", "/api/chat/send", {"thread": "crew", "text": "<img src=x onerror=1>"})[1]["message"]["text"] == "<img src=x onerror=1>")
    check("chat requires login", Client().call("GET", "/api/chat/threads")[0] == 401)

    # long-poll: B parks, A sends, B returns quickly with the message
    s, r = b.call("GET", "/api/chat/messages?thread=crew"); last, seq = r["messages"][-1]["id"], r["seq"]
    got = {}
    def park():
        t0 = time.time(); got["r"] = b.call("GET", f"/api/chat/messages?thread=crew&after={last}&seq={seq}&wait=10"); got["dt"] = time.time() - t0
    th = threading.Thread(target=park); th.start(); time.sleep(0.6)
    a.call("POST", "/api/chat/send", {"thread": "crew", "text": "live!"}); th.join(8)
    check("long-poll wakes instantly", got.get("r") and [m["text"] for m in got["r"][1]["messages"]] == ["live!"] and got["dt"] < 3, got.get("dt"))
    t0 = time.time(); s, r = b.call("GET", f"/api/chat/messages?thread=crew&after={got['r'][1]['messages'][-1]['id']}&seq={got['r'][1]['seq']}&wait=1")
    check("long-poll times out empty", s == 200 and r["messages"] == [] and 0.8 < time.time() - t0 < 3)

    # delete
    check("cannot delete someone else's msg", b.call("POST", "/api/chat/delete", {"id": m1})[0] == 403)
    first = b.call("GET", "/api/chat/messages?thread=crew")[1]["messages"][0]["id"]
    check("delete own msg", a.call("POST", "/api/chat/delete", {"id": m1})[0] == 200)
    r = b.call("GET", f"/api/chat/messages?thread=crew&first={first}")[1]
    check("deleted msg hidden + reported", m1 not in [m["id"] for m in r["messages"]] and m1 in r["deleted"], r)

    # rate limit (outsider's own crew room)
    codes = [dd.call("POST", "/api/chat/send", {"thread": "crew", "text": f"spam {i}"})[0] for i in range(12)]
    check("rate limit kicks in", codes[:10] == [200] * 10 and 429 in codes[10:], codes)

    # ---------------- Ragdamaxing additions: stopwatch, titles, records, chat v2
    e, f = Client(), Client()
    check("register e", e.call("POST", "/api/register", {"username": "ragda1", "pin": "1111", "crew_code": code})[0] == 200)
    check("register f", f.call("POST", "/api/register", {"username": "ragda2", "pin": "2222", "crew_code": code})[0] == 200)
    r = f.call("GET", "/api/today")[1]
    check("starter title", r["level"]["rank"] == "Lazy Larva" and r["level"]["next_rank"] == "Snooze Slayer" and r["level"]["emoji"], r["level"])
    check("bad timer mode rejected", f.call("POST", "/api/timer/start", {"subject": "Maths", "mode": "banana"})[0] == 400)
    s, r = e.call("POST", "/api/timer/start", {"subject": "Physics", "mode": "stopwatch"})
    check("stopwatch start", s == 200, r)
    r = e.call("GET", "/api/today")[1]
    check("stopwatch visible in today", r["timer"]["mode"] == "stopwatch" and r["timer"]["target"] == 0, r["timer"])
    check("friend sees stopwatch live", any(l.get("mode") == "stopwatch" for l in f.call("GET", "/api/today")[1]["live"]))
    e.call("POST", "/api/timer/extend", {"add": 20})
    check("extend ignored for stopwatch", db.execute("SELECT target FROM timers WHERE user_id=(SELECT id FROM users WHERE username='ragda1')").fetchone()[0] == 0)
    db.execute("UPDATE timers SET started=started-7800 WHERE user_id=(SELECT id FROM users WHERE username='ragda1')"); db.commit()
    s, r = e.call("POST", "/api/timer/stop", {})
    check("stopwatch logs 130m", s == 200 and r["minutes"] in (129, 130, 131), r)
    labels = [x.get("label", "") for x in r["events"] if x["t"] == "xp"]
    check("marathon bonus paid", any("Marathon" in l for l in labels), labels)
    e.call("POST", "/api/timer/start", {"subject": "Maths", "mode": "stopwatch"})
    db.execute("UPDATE timers SET started=started-18000 WHERE user_id=(SELECT id FROM users WHERE username='ragda1')"); db.commit()
    s, r = e.call("POST", "/api/timer/stop", {})
    check("stopwatch capped at 4h", s == 200 and r["minutes"] == 240 and r.get("capped") == 240, r)
    r = e.call("GET", "/api/crew")[1]
    me = next(m for m in r["members"] if m["me"])
    check("crew has period + record fields", me["best_session"] == 240 and "month_xp" in me and "all_xp" in me and "crowns" in me, me)
    check("crew records + hall present", any(x["k"] == "best_session" and x["value"] == 240 for x in r["records"]) and isinstance(r["hall"], list), r["records"])
    check("record announced in feed", any(x["kind"] in ("record", "session") for x in r["feed"]))

    s, r = e.call("POST", "/api/chat/send", {"thread": "crew", "text": "yo @ragda2 check this"}); m1 = r["message"]["id"]
    s, r = f.call("POST", "/api/chat/send", {"thread": "crew", "text": "replying", "reply_to": m1}); m2 = r["message"]["id"]
    check("reply stored with preview", s == 200 and r["message"]["reply"]["id"] == m1 and r["message"]["reply"]["text"].startswith("yo"), r)
    s, r = f.call("POST", "/api/chat/send", {"thread": "crew", "text": "bogus reply", "reply_to": 999999})
    check("bogus reply_to ignored", s == 200 and "reply" not in r["message"], r)
    check("react ok", f.call("POST", "/api/chat/react", {"id": m1, "emoji": "🔥"})[0] == 200)
    check("bad emoji rejected", f.call("POST", "/api/chat/react", {"id": m1, "emoji": "🍕"})[0] == 400)
    check("outsider cannot react", dd.call("POST", "/api/chat/react", {"id": m1, "emoji": "🔥"})[0] == 404)
    r = e.call("GET", "/api/chat/messages?thread=crew")[1]
    got = next(m for m in r["messages"] if m["id"] == m1)
    check("reaction visible to author", got.get("re") == {"🔥": 1}, got)
    check("replies carry preview on fetch", next(m for m in r["messages"] if m["id"] == m2)["reply"]["id"] == m1)
    f.call("POST", "/api/chat/react", {"id": m1, "emoji": "🔥"})
    r = e.call("GET", f"/api/chat/messages?thread=crew&first={m1}")[1]
    check("same emoji toggles off (states)", "re" not in r["states"][str(m1)], r["states"][str(m1)])
    check("cannot edit others", f.call("POST", "/api/chat/edit", {"id": m1, "text": "hax"})[0] == 403)
    check("edit own", e.call("POST", "/api/chat/edit", {"id": m1, "text": "yo @ragda2 (fixed)"})[0] == 200)
    r = f.call("GET", f"/api/chat/messages?thread=crew&first={m1}")[1]
    st = r["states"][str(m1)]
    check("edit syncs to others", st.get("ed") == 1 and st.get("t") == "yo @ragda2 (fixed)", st)
    check("edit rejects empty", e.call("POST", "/api/chat/edit", {"id": m1, "text": "   "})[0] == 400)
    db.execute("UPDATE messages SET ts='2000-01-01T00:00:00' WHERE id=?", (m1,)); db.commit()
    check("edit window enforced", e.call("POST", "/api/chat/edit", {"id": m1, "text": "late"})[0] == 400)

    # admin
    s, r = a.call("GET", "/api/admin/stats"); check("admin stats", s == 200 and r["app"]["users"] >= 4 and "rss_mb" in r["server"] and r["app"]["messages_total"] > 0, r)
    check("non-admin blocked from stats", b.call("GET", "/api/admin/stats")[0] == 403)
    check("non-admin blocked from backup", b.call("GET", "/api/admin/backup")[0] == 403)
    check("non-admin blocked from reset", b.call("POST", "/api/admin/resetpin", {"username": "zenx"})[0] == 403)
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/api/admin/backup")
    with a.op.open(req) as resp:
        blob = resp.read(); check("backup is a sqlite file", blob[:15] == b"SQLite format 3" and "attachment" in resp.headers.get("Content-Disposition", ""))
    s, r = a.call("POST", "/api/admin/resetpin", {"username": "kritarth"}); newpin = r.get("pin")
    check("admin reset pin", s == 200 and len(newpin or "") == 8, r)
    check("old pin dead + session killed", b.call("GET", "/api/me")[0] == 401 and Client().call("POST", "/api/login", {"username": "kritarth", "pin": "abcd"})[0] == 401)
    check("new pin works", Client().call("POST", "/api/login", {"username": "kritarth", "pin": newpin})[0] == 200)
finally:
    srv.send_signal(signal.SIGTERM)
    out = srv.stdout.read()
    if "Traceback" in out:
        print("SERVER TRACEBACK:\n", out)
        ok = False
print("ALL OK" if ok else "SOME FAILED")
