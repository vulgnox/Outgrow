import sys
P = "/home/nox/growth_tracker_v3/server.py"
s = open(P, encoding="utf-8").read()


def rep(old, new, n=1):
    global s
    c = s.count(old)
    assert c == n, f"expected {n} got {c}: {old[:80]!r}"
    s = s.replace(old, new)


def slice_rep(start, end, new):
    global s
    i = s.index(start)
    j = s.index(end, i)
    s = s[:i] + new + s[j:]


# ---------------------------------------------------------------- 1. XP economy constants
rep('''STOPWATCH_CAP = 240  # minutes. Forgot to stop the stopwatch? You still only get 4h.
''', '''STOPWATCH_CAP = 240  # minutes. Forgot to stop the stopwatch? You still only get 4h.

# ---- XP economy: grind (verified focus) decides the leaderboard; side XP (study tab, plans, habits...) is capped per day ----
XP_PER_MIN = 2   # verified timer minute (manual log = half)
SESSION_MILESTONES = [(25, 40, "Milestone: 25 min block"), (50, 100, "Milestone: 50 min deep block"),
                      (90, 220, "Milestone: 90 min elite block"), (120, 400, "Marathon bonus: 2h+ in one sitting"),
                      (180, 800, "Milestone: 3h beast mode"), (240, 1600, "Milestone: 4h legend")]
DAY_MILESTONES = [(60, 50), (120, 120), (240, 300), (360, 600), (480, 1200)]  # verified minutes in one day
SIDE_CAP = 200   # max XP/day from study section / plans / habits / quests etc.
GRIND_PREFIXES = ("focus:", "deep:", "marathon:", "clean:", "ms:", "dm:", "admin:")
SIDE_PREFIXES = ("chap:", "rev:", "test:", "plan:", "urge:", "nudge:", "habit:", "reflect:", "quest:", "sweep:", "chest:", "weekly:")
GRIND_SQL = "(" + " OR ".join(f"key LIKE '{p}%'" for p in GRIND_PREFIXES) + ")"
BOSS_PER_MEMBER = 150  # verified minutes per active crew member for the daily boss
POMO_GRACE = 15 * 60   # seconds. If you vanish for longer than this after a phase ends, the pomodoro stops


def grind(conn, uid, d1=None, d2=None):
    """Ragda points = XP earned by actually focusing. This is what the leaderboard ranks."""
    sql, a = f"SELECT COALESCE(SUM(amount),0) FROM xp WHERE user_id=? AND {GRIND_SQL}", [uid]
    if d1:
        sql += " AND day>=?"
        a.append(d1)
    if d2:
        sql += " AND day<?"
        a.append(d2)
    return conn.execute(sql, a).fetchone()[0]
''')

# ---------------------------------------------------------------- 2. award(): daily cap on side XP
rep('''def award(c, key, amount, label, uid=None, day=None, quiet=False):
    uid = uid or c.user["id"]
    day = day or iso(today())
    try:''', '''def award(c, key, amount, label, uid=None, day=None, quiet=False):
    uid = uid or c.user["id"]
    day = day or iso(today())
    if amount > 0 and key.startswith(SIDE_PREFIXES):  # daily cap on non-focus XP
        used = c.conn.execute("SELECT COALESCE(SUM(amount),0) FROM xp WHERE user_id=? AND day=? AND ("
                              + " OR ".join("key LIKE ?" for _ in SIDE_PREFIXES) + ")",
                              (uid, day, *[p + "%" for p in SIDE_PREFIXES])).fetchone()[0]
        amount = min(amount, max(SIDE_CAP - used, 0))
        if amount <= 0:
            return 0
    try:''')

rep('''"pct": round((xp - lo) / (hi - lo) * 100, 1),''', '''"pct": max(0, round((xp - lo) / (hi - lo) * 100, 1)),''')

# ---------------------------------------------------------------- 3. evaluate(): daily milestones
rep('''            award(c, f"quest:{ts}:{qu['id']}", qu["xp"], f"Quest: {qu['text']}")
''', '''            award(c, f"quest:{ts}:{qu['id']}", qu["xp"], f"Quest: {qu['text']}")
    tmin = c.conn.execute("SELECT COALESCE(SUM(minutes),0) FROM focus WHERE user_id=? AND day=? AND kind='timer'", (u["id"], ts)).fetchone()[0]
    for m, xp_ in DAY_MILESTONES:
        if tmin >= m and award(c, f"dm:{ts}:{m}", xp_, f"Daily milestone: {m // 60}h of verified focus") and m >= 240:
            feed(c, "record", f"hit {m // 60}h of verified focus today 🔥")
''')

# ---------------------------------------------------------------- 4. team goal respects failed bosses
rep('''    mins = {}
''', '''    fails = c.conn.execute("SELECT COUNT(*) FROM boss_battles WHERE crew_id=? AND day>=? AND passed=0", (crew["id"], iso(ws))).fetchone()[0]
    if fails >= 3:  # 3 failed bosses this week = no weekly goal XP
        return
    mins = {}
''')

# ---------------------------------------------------------------- 5. boss battle (fixed: used to "fail" the moment the day began)
slice_rep("def check_boss_battle(c):", "def resolve_duels(c):", '''def boss_target(conn, crew_id, d):
    """Crew target in verified minutes: 2.5h per ACTIVE member (someone who focused in the last 7 days), min 2 members."""
    n = conn.execute("SELECT COUNT(DISTINCT f.user_id) FROM focus f JOIN users x ON x.id=f.user_id WHERE x.crew_id=? AND f.day BETWEEN ? AND ?",
                     (crew_id, iso(d - D(6)), iso(d))).fetchone()[0]
    total = conn.execute("SELECT COUNT(*) FROM users WHERE crew_id=?", (crew_id,)).fetchone()[0]
    return max(2, min(n, total)) * BOSS_PER_MEMBER


def boss_actual(conn, crew_id, day):
    return conn.execute("SELECT COALESCE(SUM(f.minutes),0) FROM focus f JOIN users x ON x.id=f.user_id WHERE x.crew_id=? AND f.day=? AND f.kind='timer'",
                        (crew_id, day)).fetchone()[0]


def check_boss_battle(c):
    """Daily Boss: the crew's verified minutes vs a shared target. Defeated the moment the target is hit;
    a day only counts as FAILED once it is over (yesterday), never while it is still in progress."""
    u = c.user
    if not u["crew_id"]:
        return
    crew = q1(c.conn, "SELECT * FROM crews WHERE id=?", (u["crew_id"],))
    mem = q(c.conn, "SELECT id FROM users WHERE crew_id=?", (u["crew_id"],))
    if not crew or len(mem) < 2:
        return
    t = today()

    def settle_day(d, final):
        ds = iso(d)
        if c.conn.execute("SELECT 1 FROM boss_battles WHERE crew_id=? AND day=?", (crew["id"], ds)).fetchone():
            return
        target, actual = boss_target(c.conn, crew["id"], d), boss_actual(c.conn, crew["id"], ds)
        passed = actual >= target
        if not passed and (not final or actual == 0):  # still in progress, or nobody played at all
            return
        try:
            c.conn.execute("INSERT INTO boss_battles(crew_id, day, target_min, actual_min, passed) VALUES(?,?,?,?,?)",
                           (crew["id"], ds, target, actual, 1 if passed else 0))
        except sqlite3.IntegrityError:
            return
        label = f"{actual // 60}h{actual % 60:02d} / {target // 60}h{target % 60:02d}"
        if passed:
            for m in mem:
                award(c, f"boss:{ds}", 50, "Daily Boss Battle defeated!", uid=m["id"], day=ds, quiet=(m["id"] != u["id"]))
                if random.random() < 0.2:
                    c.conn.execute("UPDATE users SET freezes=MIN(2, freezes+1) WHERE id=?", (m["id"],))
            feed(c, "boss", f"👹 **DAILY BOSS DEFEATED!** Crew hit {label}. Everyone gets +50 XP!")
        else:
            fails = c.conn.execute("SELECT COUNT(*) FROM boss_battles WHERE crew_id=? AND day>=? AND passed=0", (crew["id"], iso(wstart(d)))).fetchone()[0]
            extra = " Weekly goal XP disabled until next week!" if fails >= 3 else ""
            feed(c, "boss", f"👹 **Boss Battle Failed** ({fails}/3 this week). Crew hit {label}.{extra}")

    settle_day(t, False)
    settle_day(t - D(1), True)


''')

# ---------------------------------------------------------------- 6. log_focus: 2 XP/min + exponential milestones
rep('''    base = round(minutes * (1.0 if kind == "timer" else 0.5))
    award(c, f"focus:{fid}", base, f"{minutes} min {subject}" + ("" if kind == "timer" else " (manual, half XP)"))
    if kind == "timer" and minutes >= 50:
        award(c, f"deep:{fid}", 20, "Deep block bonus")
    if kind == "timer" and minutes >= 25 and distractions == 0:
        award(c, f"clean:{fid}", 10, "Clean run: zero distractions")
    if kind == "timer" and minutes >= 120:
        award(c, f"marathon:{fid}", 40, "Marathon bonus: 2h+ in one sitting")
''', '''    base = round(minutes * XP_PER_MIN * (1.0 if kind == "timer" else 0.5))
    award(c, f"focus:{fid}", base, f"{minutes} min {subject}" + ("" if kind == "timer" else " (manual, half XP)"))
    if kind == "timer":
        for m, xp_, lab in SESSION_MILESTONES:
            if minutes >= m:
                award(c, f"ms:{fid}:{m}", xp_, lab)
        if minutes >= 25 and distractions == 0:
            award(c, f"clean:{fid}", 20, "Clean run: zero distractions")
''')

# ---------------------------------------------------------------- 7. api_today
rep('''def api_today(c):
    evaluate(c)''', '''def api_today(c):
    pomo_advance(c)
    evaluate(c)''')
rep('''week_xp[m["id"]] = c.conn.execute("SELECT COALESCE(SUM(amount),0) FROM xp WHERE user_id=? AND day>=? AND day<>'0000-00-00'", (m["id"], iso(ws))).fetchone()[0]''',
    '''week_xp[m["id"]] = grind(c.conn, m["id"], iso(ws))''')
rep('''"target": len(mem) * 150, "actual": today_timer}''', '''"target": boss_target(c.conn, crew["id"], t), "actual": today_timer}''')
rep('''"rival": rival_info, "boss": boss_info,''', '''"rival": rival_info, "boss": boss_info, "pomo": pomo_view(c),''')

# ---------------------------------------------------------------- 8. timers x pomodoro
rep('''    if q1(c.conn, "SELECT 1 x FROM timers WHERE user_id=?", (c.user["id"],)):
        raise ApiError("A timer is already running")''', '''    if q1(c.conn, "SELECT 1 x FROM timers WHERE user_id=?", (c.user["id"],)) or q1(c.conn, "SELECT 1 x FROM pomo WHERE user_id=?", (c.user["id"],)):
        raise ApiError("A timer is already running")''')
rep('''    c.conn.execute("DELETE FROM timers WHERE user_id=?", (c.user["id"],))
    if c.body.get("discard"):''', '''    c.conn.execute("DELETE FROM timers WHERE user_id=?", (c.user["id"],))
    c.conn.execute("DELETE FROM pomo WHERE user_id=?", (c.user["id"],))  # stopping mid-pomodoro ends the whole plan
    if c.body.get("discard"):''')

POMO = '''# ----------------------------------------------------------------------------- pomodoro (auto work/break cycles toward a daily focus goal)
def pomo_plan(total, work):
    """Work-block lengths (min) that add up to `total`. A leftover under 5 min is merged into the last block."""
    out, rem = [], total
    while rem >= 5:
        n = rem if rem - work < 5 else work
        out.append(n)
        rem -= n
    return out


def _pomo_to_work(c, p, plan, start):
    n = p["block"] + 1
    ln = plan[n - 1]
    c.conn.execute("UPDATE pomo SET block=?, phase='work', phase_start=?, phase_len=? WHERE user_id=?", (n, start, ln * 60, p["user_id"]))
    c.conn.execute("DELETE FROM timers WHERE user_id=?", (p["user_id"],))
    c.conn.execute("INSERT INTO timers(user_id,subject,started,target,mode) VALUES(?,?,?,?,'timer')", (p["user_id"], p["subject"], start, ln))


def pomo_advance(c):
    """Lazily moves the pomodoro forward: finished work blocks are logged as verified sessions, then break, then next block.
    If you were away for longer than POMO_GRACE after a phase ended, the plan stops there (no free hours while the phone sleeps)."""
    uid = c.user["id"]
    for _ in range(40):
        p = q1(c.conn, "SELECT * FROM pomo WHERE user_id=?", (uid,))
        if not p:
            return
        t = time.time()
        end = p["phase_start"] + p["phase_len"]
        if t < end:
            return
        late = t - end > POMO_GRACE
        plan = pomo_plan(p["total_min"], p["work_min"])
        if p["phase"] == "work":
            tm = q1(c.conn, "SELECT distractions FROM timers WHERE user_id=?", (uid,))
            c.conn.execute("DELETE FROM timers WHERE user_id=?", (uid,))
            mins = p["phase_len"] // 60
            log_focus(c, p["subject"], mins, "timer", tm["distractions"] if tm else 0, "pomodoro", dt.datetime.fromtimestamp(p["phase_start"]))
            done = p["done_min"] + mins
            if p["block"] >= len(plan) or done >= p["total_min"]:
                c.conn.execute("DELETE FROM pomo WHERE user_id=?", (uid,))
                award(c, f"ms:pomo:{int(p['started'])}", p["total_min"] // 2, f"Pomodoro goal done: {p['total_min'] // 60}h{p['total_min'] % 60:02d} of focus")
                feed(c, "record", f"finished a {p['total_min'] // 60}h{p['total_min'] % 60:02d} pomodoro plan 🍅")
                c.ev.append({"t": "info", "text": "🍅 Pomodoro goal complete. Go rest."})
                return
            if late:
                c.conn.execute("DELETE FROM pomo WHERE user_id=?", (uid,))
                c.ev.append({"t": "info", "text": "🍅 You were away, so the pomodoro stopped after that block."})
                return
            brk = p["long_min"] if p["block"] % p["every"] == 0 else p["break_min"]
            c.conn.execute("UPDATE pomo SET done_min=?, phase='break', phase_start=?, phase_len=? WHERE user_id=?", (done, end, brk * 60, uid))
        else:
            if late:
                c.conn.execute("DELETE FROM pomo WHERE user_id=?", (uid,))
                c.ev.append({"t": "info", "text": "🍅 Break ran long, so the pomodoro stopped. Start a new one when you're back."})
                return
            _pomo_to_work(c, p, plan, end)


def pomo_view(c):
    p = q1(c.conn, "SELECT * FROM pomo WHERE user_id=?", (c.user["id"],))
    if not p:
        return None
    plan = pomo_plan(p["total_min"], p["work_min"])
    return {"subject": p["subject"], "total": p["total_min"], "done": p["done_min"], "work": p["work_min"], "brk": p["break_min"],
            "long": p["long_min"], "every": p["every"], "block": p["block"], "blocks": len(plan), "phase": p["phase"],
            "phase_len": p["phase_len"], "elapsed": int(time.time() - p["phase_start"]),
            "is_long": p["phase"] == "break" and p["block"] % p["every"] == 0,
            "next_len": plan[p["block"]] if p["block"] < len(plan) else 0}


@route("POST", "/api/pomo/start")
def pomo_start(c):
    uid = c.user["id"]
    sub = need(c, "subject")
    if sub not in SUBJECTS:
        raise ApiError("bad subject")
    total = max(30, min(720, need(c, "total", int)))
    work = max(15, min(120, need(c, "work", int, 50)))
    brk = max(3, min(30, need(c, "brk", int, 10)))
    if q1(c.conn, "SELECT 1 x FROM timers WHERE user_id=?", (uid,)) or q1(c.conn, "SELECT 1 x FROM pomo WHERE user_id=?", (uid,)):
        raise ApiError("A timer is already running")
    plan = pomo_plan(total, work)
    t = time.time()
    c.conn.execute("INSERT INTO pomo(user_id,subject,total_min,work_min,break_min,long_min,every,done_min,block,phase,phase_start,phase_len,started) "
                   "VALUES(?,?,?,?,?,?,?,0,1,'work',?,?,?)",
                   (uid, sub, total, work, brk, max(brk * 2, 15), 4 if work <= 30 else 3, t, plan[0] * 60, t))
    c.conn.execute("INSERT INTO timers(user_id,subject,started,target,mode) VALUES(?,?,?,?,'timer')", (uid, sub, t, plan[0]))
    return {"ok": True}


@route("POST", "/api/pomo/skip")
def pomo_skip(c):
    p = q1(c.conn, "SELECT * FROM pomo WHERE user_id=?", (c.user["id"],))
    if not p or p["phase"] != "break":
        raise ApiError("No break to skip")
    _pomo_to_work(c, p, pomo_plan(p["total_min"], p["work_min"]), time.time())
    return {"ok": True}


@route("POST", "/api/pomo/stop")
def pomo_stop(c):
    """End the plan. Mid-block this logs the part you already did (5+ min), exactly like stopping a timer."""
    if q1(c.conn, "SELECT 1 x FROM timers WHERE user_id=?", (c.user["id"],)):
        return timer_stop(c)
    c.conn.execute("DELETE FROM pomo WHERE user_id=?", (c.user["id"],))
    return {"ok": True}


'''
rep('''# ----------------------------------------------------------------------------- habits, plan, urges, chest''',
    POMO + '''# ----------------------------------------------------------------------------- habits, plan, urges, chest''')

# ---------------------------------------------------------------- 9. crew: leaderboard = grind
rep('''    c.conn.execute("UPDATE users SET crew_id=? WHERE id=?", (cr["id"], c.user["id"]))
    c.user["crew_id"] = cr["id"]''', '''    if c.user.get("prev_crew") == cr["id"]:
        raise ApiError("The admin removed you from this crew.", 403)
    c.conn.execute("UPDATE users SET crew_id=? WHERE id=?", (cr["id"], c.user["id"]))
    c.user["crew_id"] = cr["id"]''')
rep('''wk = c.conn.execute("SELECT COALESCE(SUM(amount),0) FROM xp WHERE user_id=? AND day>=? AND day<>'0000-00-00'", (mu["id"], iso(ws))).fetchone()[0]''',
    '''wk = grind(c.conn, mu["id"], iso(ws))''')
rep('''lw = c.conn.execute("SELECT COALESCE(SUM(amount),0) FROM xp WHERE user_id=? AND day>=? AND day<?", (mu["id"], iso(ws - D(7)), iso(ws))).fetchone()[0]''',
    '''lw = grind(c.conn, mu["id"], iso(ws - D(7)), iso(ws))''')
rep('''extra = {"month_xp": one("SELECT COALESCE(SUM(amount),0) FROM xp WHERE user_id=? AND day>=? AND day<>'0000-00-00'", mstart),''',
    '''extra = {"month_xp": grind(c.conn, mu["id"], mstart),''')
rep('''"all_xp": tx,''', '''"all_xp": grind(c.conn, mu["id"]),''')
rep('''WHERE day>=? AND day<? AND user_id IN ({ph}) GROUP BY user_id''', '''WHERE day>=? AND day<? AND {GRIND_SQL} AND user_id IN ({ph}) GROUP BY user_id''', 2)
rep('''"target": len(out) * 150, "actual": sum(m["today_min"] for m in out if m.get("today_min", 0) > 0)}''',
    '''"target": boss_target(c.conn, crew["id"], t), "actual": boss_actual(c.conn, crew["id"], ts)}''')

# ---------------------------------------------------------------- 10. blocked users
rep('''    FAILS.pop(key, None)
    c.user = u
''', '''    FAILS.pop(key, None)
    if u.get("banned"):
        raise ApiError("This account is blocked. Ask the admin.", 403)
    c.user = u
''')
rep('''            if auth and not user:
                return self.send_json(401, {"error": "login"})''', '''            if user and user.get("banned"):
                user = None
            if auth and not user:
                return self.send_json(401, {"error": "login"})''')

# ---------------------------------------------------------------- 11. schema + migration
rep('''CREATE TABLE IF NOT EXISTS msg_reacts(msg_id INTEGER, user_id INTEGER, emoji TEXT, PRIMARY KEY(msg_id, user_id));
"""''', '''CREATE TABLE IF NOT EXISTS msg_reacts(msg_id INTEGER, user_id INTEGER, emoji TEXT, PRIMARY KEY(msg_id, user_id));
CREATE TABLE IF NOT EXISTS pomo(user_id INTEGER PRIMARY KEY, subject TEXT, total_min INTEGER, work_min INTEGER, break_min INTEGER,
 long_min INTEGER, every INTEGER, done_min INTEGER DEFAULT 0, block INTEGER DEFAULT 1, phase TEXT, phase_start REAL, phase_len INTEGER, started REAL);
"""''')
rep('''    for table, col, ddl in (("timers", "mode", "TEXT DEFAULT 'timer'"),
                            ("messages", "reply_to", "INTEGER"),
                            ("messages", "edited", "INTEGER DEFAULT 0")):
        if col not in cols(table):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
    conn.commit()''', '''    for table, col, ddl in (("timers", "mode", "TEXT DEFAULT 'timer'"),
                            ("messages", "reply_to", "INTEGER"),
                            ("messages", "edited", "INTEGER DEFAULT 0"),
                            ("users", "banned", "INTEGER DEFAULT 0"),
                            ("users", "prev_crew", "INTEGER")):
        if col not in cols(table):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
    if conn.execute("PRAGMA user_version").fetchone()[0] < 1:
        # v1: the boss used to be resolved (and failed) the moment a day began, so every stored failure is bogus
        conn.execute("DELETE FROM boss_battles WHERE passed=0")
        conn.execute("PRAGMA user_version=1")
    conn.commit()''')

# ---------------------------------------------------------------- 12. admin
slice_rep('''    users = q(conn, """SELECT u.id, u.username, u.display, u.crew_id,''', '''    for u in users:
        u["admin"]''', '''    users = q(conn, f"""SELECT u.id, u.username, u.display, u.crew_id, u.banned, u.prev_crew,
        COALESCE((SELECT SUM(amount) FROM xp WHERE user_id=u.id),0) xp,
        COALESCE((SELECT SUM(amount) FROM xp WHERE user_id=u.id AND {GRIND_SQL}),0) grind,
        (SELECT MAX(day) FROM focus WHERE user_id=u.id) last_focus,
        (SELECT COUNT(*) FROM messages WHERE sender=u.id) msgs
        FROM users u ORDER BY grind DESC""")
''')

ADMIN = '''XP_SOURCES = {"focus": "Focus session", "deep": "Focus bonus", "clean": "Clean run", "marathon": "Marathon", "ms": "Session milestone",
              "dm": "Daily milestone", "quest": "Quest", "sweep": "Quest sweep", "chap": "Chapter", "rev": "Revision", "test": "Test logged",
              "plan": "Plan", "urge": "Urge surfed", "nudge": "Nudge", "habit": "Habit", "reflect": "Reflection", "weekly": "Weekly review",
              "chest": "Daily chest", "badge": "Badge", "streak": "Streak bonus", "redeem": "Redemption", "crewgoal": "Crew goal", "boss": "Boss battle",
              "duel": "Duel", "legacy": "Season 0", "admin": "Admin", "adm0": "Admin (side XP)"}


def need_target(c):
    t = q1(c.conn, "SELECT * FROM users WHERE id=?", (need(c, "id", int),))
    if not t:
        raise ApiError("No such user", 404)
    return t


@route("GET", "/api/admin/activity")
def admin_activity(c):
    """Every XP event with its source + timestamp. ?user=<id> for one member (omit = everyone), ?before=<event id> to page."""
    need_admin(c)
    uid, before, limit = qpi(c, "user"), qpi(c, "before"), max(1, min(qpi(c, "limit", 60), 200))
    where, a = ["x.id<?"], [before or 2 ** 62]
    if uid:
        where.append("x.user_id=?")
        a.append(uid)
    rows = q(c.conn, f"""SELECT x.id, x.user_id uid, u.username, u.display, x.day, x.ts, x.key, x.amount, x.label
        FROM xp x JOIN users u ON u.id=x.user_id WHERE {' AND '.join(where)} ORDER BY x.id DESC LIMIT ?""", (*a, limit + 1))
    more, rows = len(rows) > limit, rows[:limit]
    for r in rows:
        r["src"] = XP_SOURCES.get(r["key"].split(":")[0], "Other")
        r["grind"] = r["key"].startswith(GRIND_PREFIXES)
        r["revoked"] = False
    if rows:
        ids = [f"admin:rev:{r['id']}" for r in rows] + [f"adm0:rev:{r['id']}" for r in rows]
        gone = {r["key"] for r in q(c.conn, f"SELECT key FROM xp WHERE key IN ({','.join('?' * len(ids))})", ids)}
        for r in rows:
            r["revoked"] = f"admin:rev:{r['id']}" in gone or f"adm0:rev:{r['id']}" in gone
    return {"events": rows, "more": more}


@route("POST", "/api/admin/xp")
def admin_xp(c):
    """Add (+) or remove (-) XP. Counts for the leaderboard unless side=true."""
    need_admin(c)
    t = need_target(c)
    amt = need(c, "amount", int)
    if amt == 0 or abs(amt) > 100000:
        raise ApiError("Amount must be non-zero and under 100000")
    reason = need(c, "reason", maxlen=60, default="") or "adjustment"
    key = f"{'adm0' if c.body.get('side') else 'admin'}:{secrets.token_hex(4)}"
    award(c, key, amt, f"Admin: {reason}", uid=t["id"], quiet=True)
    return {"ok": True, "total": total_xp(c.conn, t["id"]), "grind": grind(c.conn, t["id"])}


@route("POST", "/api/admin/revoke")
def admin_revoke(c):
    """Undo one XP event (adds an equal negative entry in the same day, so history stays auditable)."""
    need_admin(c)
    r = q1(c.conn, "SELECT * FROM xp WHERE id=?", (need(c, "id", int),))
    if not r:
        raise ApiError("No such event", 404)
    if r["key"].startswith(("admin:", "adm0:")):
        raise ApiError("That is an admin adjustment. Make a new one instead.")
    key = f"{'admin' if r['key'].startswith(GRIND_PREFIXES) else 'adm0'}:rev:{r['id']}"
    if not award(c, key, -r["amount"], f"Admin revoked: {r['label']}"[:90], uid=r["user_id"], day=r["day"], quiet=True):
        raise ApiError("Already revoked")
    return {"ok": True}


@route("POST", "/api/admin/block")
def admin_block(c):
    """Blocked users are logged out and cannot log in. Reversible: blocked=false."""
    need_admin(c)
    t = need_target(c)
    if t["id"] == c.user["id"] or is_admin(t):
        raise ApiError("You can't block an admin")
    on = 1 if c.body.get("blocked", True) else 0
    c.conn.execute("UPDATE users SET banned=? WHERE id=?", (on, t["id"]))
    if on:
        for tb in ("sessions", "timers", "pomo"):
            c.conn.execute(f"DELETE FROM {tb} WHERE user_id=?", (t["id"],))
    return {"ok": True, "banned": on}


@route("POST", "/api/admin/kick")
def admin_kick(c):
    """Remove from the crew (they can't rejoin with the code until undo=true). Their account and XP stay."""
    need_admin(c)
    t = need_target(c)
    if c.body.get("undo"):
        c.conn.execute("UPDATE users SET prev_crew=NULL WHERE id=?", (t["id"],))
        return {"ok": True}
    if t["id"] == c.user["id"] or is_admin(t):
        raise ApiError("You can't kick an admin")
    if not t["crew_id"]:
        raise ApiError("They are not in a crew")
    c.conn.execute("UPDATE users SET prev_crew=crew_id, crew_id=NULL WHERE id=?", (t["id"],))
    c.conn.execute("UPDATE duels SET status='cancelled' WHERE status IN ('pending','active') AND (a=? OR b=?)", (t["id"], t["id"]))
    for tb in ("timers", "pomo"):
        c.conn.execute(f"DELETE FROM {tb} WHERE user_id=?", (t["id"],))
    return {"ok": True}


'''
rep('''# ----------------------------------------------------------------------------- http
''', ADMIN + '''# ----------------------------------------------------------------------------- http
''')

open(P, "w", encoding="utf-8").write(s)
print("server.py patched")
