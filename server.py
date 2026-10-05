#!/usr/bin/env python3
"""
OUTGROW — multiplayer discipline engine for exam season.
Zero dependencies (Python 3.9+ stdlib only). SQLite storage. Mobile-first web UI in ./static.

Run:  python3 server.py        (then open http://localhost:8765)
"""
import csv
import datetime as dt
import hashlib
import json
import math
import mimetypes
import os
import random
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(ROOT, "static")
DATA_DIR = os.path.join(ROOT, "data")
DB_PATH = os.environ.get("OUTGROW_DB", os.path.join(DATA_DIR, "outgrow.db"))
PORT = int(os.environ.get("PORT", "8765"))
WEBHOOK = os.environ.get("OUTGROW_DISCORD_WEBHOOK", "")
BIND = os.environ.get("OUTGROW_BIND", "0.0.0.0")  # set 127.0.0.1 behind a tunnel/reverse proxy
ADMINS = {n.strip().lower() for n in os.environ.get("OUTGROW_ADMINS", "").split(",") if n.strip()}  # usernames that get the Server dashboard
LEGACY_CSV = os.environ.get("OUTGROW_LEGACY_CSV", os.path.join(ROOT, "..", "growth_tracker", "form_data", "growth_data.csv"))
ROLLOVER_HOUR = 3  # a "day" ends at 3 AM, so late-night study still counts for the day you started
SUBJECTS = ["Physics", "Chemistry", "Maths", "English", "Other"]
CORE = ["Physics", "Chemistry", "Maths"]
EMOJIS = ["🔥", "💪", "👏", "😤", "🫡"]

HABITS = [
    ("exercise", "Exercise", "💪", 40),
    ("wake", "Woke up on time", "🌅", 30),
    ("sleep", "Lights out on time", "🌙", 30),
    ("screen", "Screen control (<1h waste)", "📵", 30),
]

RANKS = [(1, "Drifter"), (2, "Awake"), (3, "Initiate"), (4, "Grinder"), (6, "Locked-In"), (8, "Relentless"),
         (10, "Dominant"), (13, "A+ Reborn"), (16, "Beyond A+"), (20, "OUTGROWN")]

SYLLABUS = {
    "Physics": {
        "11": ["Units & Measurements", "Motion in a Straight Line", "Motion in a Plane", "Laws of Motion",
               "Work, Energy & Power", "System of Particles & Rotational Motion", "Gravitation",
               "Mechanical Properties of Solids", "Mechanical Properties of Fluids", "Thermal Properties of Matter",
               "Thermodynamics", "Kinetic Theory", "Oscillations", "Waves"],
        "12": ["Electric Charges & Fields", "Electrostatic Potential & Capacitance", "Current Electricity",
               "Moving Charges & Magnetism", "Magnetism & Matter", "Electromagnetic Induction", "Alternating Current",
               "Electromagnetic Waves", "Ray Optics", "Wave Optics", "Dual Nature of Radiation & Matter", "Atoms",
               "Nuclei", "Semiconductor Electronics"],
    },
    "Chemistry": {
        "11": ["Some Basic Concepts", "Structure of Atom", "Periodic Classification & Periodicity",
               "Chemical Bonding & Molecular Structure", "Thermodynamics", "Equilibrium", "Redox Reactions",
               "GOC (Organic Basics)", "Hydrocarbons"],
        "12": ["Solutions", "Electrochemistry", "Chemical Kinetics", "d- & f-Block Elements", "Coordination Compounds",
               "p-Block Elements", "Haloalkanes & Haloarenes", "Alcohols, Phenols & Ethers",
               "Aldehydes, Ketones & Carboxylic Acids", "Amines", "Biomolecules"],
    },
    "Maths": {
        "11": ["Sets, Relations & Functions", "Trigonometric Functions", "Complex Numbers & Quadratics",
               "Permutations & Combinations", "Binomial Theorem", "Sequences & Series", "Straight Lines",
               "Conic Sections", "Limits & Derivatives", "Statistics", "Probability", "Intro to 3D Geometry"],
        "12": ["Relations & Functions", "Inverse Trigonometric Functions", "Matrices", "Determinants",
               "Continuity & Differentiability", "Application of Derivatives", "Integrals", "Application of Integrals",
               "Differential Equations", "Vector Algebra", "3D Geometry", "Linear Programming", "Probability (12)"],
    },
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
 id INTEGER PRIMARY KEY, username TEXT UNIQUE COLLATE NOCASE, display TEXT, pw_hash TEXT, salt TEXT,
 crew_id INTEGER, color TEXT DEFAULT '#7c5cff', emoji TEXT DEFAULT '🦊',
 identity TEXT DEFAULT '', baseline_h REAL DEFAULT 5, daily_min INTEGER DEFAULT 45,
 exams TEXT DEFAULT '[]', created_at TEXT, onboarded INTEGER DEFAULT 0,
 run INTEGER DEFAULT 0, longest INTEGER DEFAULT 0, freezes INTEGER DEFAULT 1,
 last_settled TEXT, comeback INTEGER DEFAULT 0, frozen_days TEXT DEFAULT '[]');
CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id INTEGER, created REAL);
CREATE TABLE IF NOT EXISTS crews(id INTEGER PRIMARY KEY, name TEXT, code TEXT UNIQUE, goal_h REAL DEFAULT 15, created_at TEXT);
CREATE TABLE IF NOT EXISTS focus(id INTEGER PRIMARY KEY, user_id INTEGER, day TEXT, subject TEXT, minutes INTEGER,
 kind TEXT, distractions INTEGER DEFAULT 0, note TEXT DEFAULT '', started_at TEXT, hour INTEGER);
CREATE INDEX IF NOT EXISTS ix_focus ON focus(user_id, day);
CREATE TABLE IF NOT EXISTS timers(user_id INTEGER PRIMARY KEY, subject TEXT, started REAL, target INTEGER, distractions INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS xp(id INTEGER PRIMARY KEY, user_id INTEGER, day TEXT, ts TEXT, key TEXT, amount INTEGER, label TEXT, UNIQUE(user_id, key));
CREATE TABLE IF NOT EXISTS habits(user_id INTEGER, day TEXT, habit TEXT, PRIMARY KEY(user_id, day, habit));
CREATE TABLE IF NOT EXISTS plans(id INTEGER PRIMARY KEY, user_id INTEGER, day TEXT, text TEXT, cue TEXT DEFAULT '', done INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS reflections(id INTEGER PRIMARY KEY, user_id INTEGER, day TEXT, mood INTEGER, energy INTEGER,
 win TEXT, leak TEXT, kind_note TEXT, tomorrow TEXT, UNIQUE(user_id, day));
CREATE TABLE IF NOT EXISTS weekly(id INTEGER PRIMARY KEY, user_id INTEGER, week TEXT, best TEXT, leak TEXT, change TEXT,
 premortem TEXT, ifthen TEXT, UNIQUE(user_id, week));
CREATE TABLE IF NOT EXISTS chapters(id INTEGER PRIMARY KEY, user_id INTEGER, subject TEXT, grade TEXT, name TEXT,
 status INTEGER DEFAULT 0, learned_on TEXT, custom INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS revisions(id INTEGER PRIMARY KEY, user_id INTEGER, chapter_id INTEGER, due TEXT, stage INTEGER, done_at TEXT, result TEXT);
CREATE TABLE IF NOT EXISTS tests(id INTEGER PRIMARY KEY, user_id INTEGER, day TEXT, name TEXT, kind TEXT, subject TEXT,
 score REAL, maxscore REAL, concept INTEGER DEFAULT 0, silly INTEGER DEFAULT 0, timeerr INTEGER DEFAULT 0, note TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS urges(id INTEGER PRIMARY KEY, user_id INTEGER, ts TEXT, hour INTEGER, trigger TEXT, outcome TEXT);
CREATE TABLE IF NOT EXISTS feed(id INTEGER PRIMARY KEY, crew_id INTEGER, user_id INTEGER, ts TEXT, kind TEXT, text TEXT);
CREATE TABLE IF NOT EXISTS reactions(feed_id INTEGER, user_id INTEGER, emoji TEXT, PRIMARY KEY(feed_id, user_id));
CREATE TABLE IF NOT EXISTS nudges(id INTEGER PRIMARY KEY, from_id INTEGER, to_id INTEGER, day TEXT, UNIQUE(from_id, to_id, day));
CREATE TABLE IF NOT EXISTS duels(id INTEGER PRIMARY KEY, crew_id INTEGER, a INTEGER, b INTEGER, days INTEGER, start TEXT, end TEXT, status TEXT, winner INTEGER);
CREATE TABLE IF NOT EXISTS chests(user_id INTEGER, day TEXT, reward TEXT, PRIMARY KEY(user_id, day));
CREATE TABLE IF NOT EXISTS badges(user_id INTEGER, id TEXT, day TEXT, PRIMARY KEY(user_id, id));
CREATE TABLE IF NOT EXISTS legacy(username TEXT, day TEXT, done INTEGER, total INTEGER);
CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY, thread TEXT NOT NULL, sender INTEGER NOT NULL, recip INTEGER, ts TEXT, body TEXT, deleted INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS idx_msg_thread ON messages(thread, id);
CREATE INDEX IF NOT EXISTS idx_msg_recip ON messages(recip, id);
CREATE TABLE IF NOT EXISTS chat_reads(user_id INTEGER, thread TEXT, last_id INTEGER DEFAULT 0, PRIMARY KEY(user_id, thread));
"""


# ----------------------------------------------------------------------------- utils
def connect():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def q(conn, sql, a=()):
    return [dict(r) for r in conn.execute(sql, a).fetchall()]


def q1(conn, sql, a=()):
    r = conn.execute(sql, a).fetchone()
    return dict(r) if r else None


def now():
    return dt.datetime.now()


def today():
    return (now() - dt.timedelta(hours=ROLLOVER_HOUR)).date()


def iso(d):
    return d.isoformat()


def pd(s):
    return dt.date.fromisoformat(s)


def wstart(d):
    return d - dt.timedelta(days=d.weekday())


def D(n):
    return dt.timedelta(days=n)


class ApiError(Exception):
    def __init__(self, msg, code=400):
        super().__init__(msg)
        self.msg, self.code = msg, code


class Ctx:
    def __init__(self, conn, user, body, query, handler):
        self.conn, self.user, self.body, self.q, self.h = conn, user, body, query, handler
        self.ev = []
        self.cookie = None


def need(c, key, typ=str, default=None, maxlen=500):
    v = c.body.get(key, default)
    if v is None:
        raise ApiError(f"missing {key}")
    if typ is str:
        v = str(v).strip()[:maxlen]
    elif typ is int:
        try:
            v = int(v)
        except Exception:
            raise ApiError(f"bad {key}")
    elif typ is float:
        try:
            v = float(v)
        except Exception:
            raise ApiError(f"bad {key}")
    return v


# ----------------------------------------------------------------------------- xp / levels / feed
def total_xp(conn, uid):
    return conn.execute("SELECT COALESCE(SUM(amount),0) FROM xp WHERE user_id=?", (uid,)).fetchone()[0]


def level_of(xp):
    return int(math.sqrt(max(xp, 0) / 60)) + 1


def level_info(xp):
    L = level_of(xp)
    lo, hi = 60 * (L - 1) ** 2, 60 * L ** 2
    rank = [n for l, n in RANKS if L >= l][-1]
    return {"level": L, "rank": rank, "xp": xp, "lo": lo, "hi": hi, "pct": round((xp - lo) / (hi - lo) * 100, 1)}


def award(c, key, amount, label, uid=None, day=None, quiet=False):
    uid = uid or c.user["id"]
    day = day or iso(today())
    try:
        c.conn.execute("INSERT INTO xp(user_id,day,ts,key,amount,label) VALUES(?,?,?,?,?,?)",
                       (uid, day, now().isoformat(timespec="seconds"), key, int(amount), label))
    except sqlite3.IntegrityError:
        return 0
    if not quiet and uid == c.user["id"]:
        c.ev.append({"t": "xp", "amount": int(amount), "label": label})
    return int(amount)


def post_hook(msg):
    try:
        req = urllib.request.Request(WEBHOOK, data=json.dumps({"content": msg[:1900]}).encode(),
                                     headers={"Content-Type": "application/json", "User-Agent": "outgrow"})
        urllib.request.urlopen(req, timeout=8)
    except Exception:
        pass


def feed(c, kind, text, uid=None):
    uid = uid or c.user["id"]
    u = c.user if uid == c.user["id"] else q1(c.conn, "SELECT * FROM users WHERE id=?", (uid,))
    if not u or not u.get("crew_id"):
        return
    c.conn.execute("INSERT INTO feed(crew_id,user_id,ts,kind,text) VALUES(?,?,?,?,?)",
                   (u["crew_id"], uid, now().isoformat(timespec="seconds"), kind, text))
    if WEBHOOK and kind in ("badge", "levelup", "streak", "comeback", "test", "duel", "crew"):
        threading.Thread(target=post_hook, args=(f"**{u['display']}** {text}",), daemon=True).start()


# ----------------------------------------------------------------------------- streak engine
def day_stats(conn, uid, d1, d2):
    rows = q(conn, "SELECT day, kind, subject, SUM(minutes) m FROM focus WHERE user_id=? AND day BETWEEN ? AND ? GROUP BY day, kind, subject",
             (uid, iso(d1), iso(d2)))
    out = {}
    for r in rows:
        o = out.setdefault(r["day"], {"total": 0, "timer": 0, "sub": {}})
        o["total"] += r["m"]
        if r["kind"] == "timer":
            o["timer"] += r["m"]
        o["sub"][r["subject"]] = o["sub"].get(r["subject"], 0) + r["m"]
    return out


def qualifies(st, daily_min):
    # A "streak day" = hit your daily floor, and at least half of it came from the verified timer.
    return bool(st) and st["total"] >= daily_min and st["timer"] >= daily_min / 2


def settle(conn, uid):
    u = q1(conn, "SELECT * FROM users WHERE id=?", (uid,))
    t = today()
    last = pd(u["last_settled"]) if u["last_settled"] else t - D(1)
    if last >= t - D(1):
        return u
    d = last + D(1)
    stats = day_stats(conn, uid, d, t - D(1))
    run, longest, fr, cb = u["run"], u["longest"], u["freezes"], u["comeback"]
    frozen = json.loads(u["frozen_days"] or "[]")
    while d <= t - D(1):
        if qualifies(stats.get(iso(d)), u["daily_min"]):
            run += 1
            longest = max(longest, run)
            if run % 7 == 0:
                fr = min(2, fr + 1)
        elif run > 0 and fr > 0:
            fr -= 1
            frozen.append(iso(d))
        else:
            run, cb = 0, 1
        d += D(1)
    conn.execute("UPDATE users SET run=?,longest=?,freezes=?,comeback=?,frozen_days=?,last_settled=? WHERE id=?",
                 (run, longest, fr, cb, json.dumps(frozen[-120:]), iso(t - D(1)), uid))
    return q1(conn, "SELECT * FROM users WHERE id=?", (uid,))


def streak_view(conn, u):
    t = today()
    st = day_stats(conn, u["id"], t, t).get(iso(t)) or {"total": 0, "timer": 0, "sub": {}}
    ok = qualifies(st, u["daily_min"])
    now_ = u["run"] + (1 if ok else 0)
    return {"now": now_, "run": u["run"], "longest": max(u["longest"], now_), "freezes": u["freezes"],
            "qualified": ok, "at_risk": u["run"] > 0 and not ok}, st


# ----------------------------------------------------------------------------- quests, badges, stats
def quests(conn, u):
    t = today()
    ts = iso(t)
    uid = u["id"]
    stt = day_stats(conn, uid, t - D(7), t)
    cur = stt.get(ts, {"total": 0, "timer": 0, "sub": {}})
    week = {s: 0 for s in CORE}
    for d, v in stt.items():
        if d != ts:
            for s in CORE:
                week[s] += v["sub"].get(s, 0)
    weak = min(CORE, key=lambda s: week[s])
    out = [{"id": "weak", "text": f"Weakest link: {weak}, 30+ min", "xp": 60,
            "done": cur["sub"].get(weak, 0) >= 30, "prog": min(cur["sub"].get(weak, 0), 30), "goal": 30}]
    deep = conn.execute("SELECT COALESCE(MAX(minutes),0) FROM focus WHERE user_id=? AND day=? AND kind='timer'", (uid, ts)).fetchone()[0]
    out.append({"id": "deep", "text": "One deep block: 50+ min on the timer", "xp": 60, "done": deep >= 50,
                "prog": min(deep, 50), "goal": 50})
    due = conn.execute("SELECT COUNT(*) FROM revisions WHERE user_id=? AND due<=? AND done_at IS NULL", (uid, ts)).fetchone()[0]
    dn = conn.execute("SELECT COUNT(*) FROM revisions WHERE user_id=? AND done_at=?", (uid, ts)).fetchone()[0]
    if due > 0 or dn > 0:
        out.append({"id": "rev", "text": "Clear your revision queue", "xp": 50, "done": due == 0 and dn > 0,
                    "prog": dn, "goal": dn + due})
    else:
        y = stt.get(iso(t - D(1)), {"total": 0})["total"]
        goal = max(y + 1, u["daily_min"])
        out.append({"id": "beat", "text": f"Beat yesterday: {goal} min", "xp": 50, "done": cur["total"] >= goal,
                    "prog": min(cur["total"], goal), "goal": goal})
    pl = conn.execute("SELECT COUNT(*), COALESCE(SUM(done),0) FROM plans WHERE user_id=? AND day=?", (uid, ts)).fetchone()
    if pl[0]:
        out.append({"id": "plan", "text": "Finish today's Top-3 plan", "xp": 50, "done": pl[1] == pl[0], "prog": pl[1], "goal": pl[0]})
    return out


def get_stats(conn, u):
    uid = u["id"]
    f = q1(conn, """SELECT COALESCE(SUM(minutes),0) m, COUNT(*) n,
        COALESCE(SUM(CASE WHEN kind='timer' AND minutes>=50 THEN 1 ELSE 0 END),0) deep,
        COALESCE(SUM(CASE WHEN kind='timer' AND hour<7 THEN 1 ELSE 0 END),0) early
        FROM focus WHERE user_id=?""", (uid,))
    one = lambda sql: conn.execute(sql, (uid,)).fetchone()[0]
    t = today()
    st7 = day_stats(conn, uid, t - D(6), t)
    last7 = sum(v["total"] for v in st7.values())
    ratio = (last7 / 7.0) / max(u["baseline_h"] * 60, 1)
    return {"minutes": f["m"], "sessions": f["n"], "deep": f["deep"], "early": f["early"],
            "urges_won": one("SELECT COUNT(*) FROM urges WHERE user_id=? AND outcome IN ('resisted','redirected')"),
            "revs": one("SELECT COUNT(*) FROM revisions WHERE user_id=? AND done_at IS NOT NULL"),
            "tests": one("SELECT COUNT(*) FROM tests WHERE user_id=?"),
            "mastered": one("SELECT COUNT(*) FROM chapters WHERE user_id=? AND status>=3"),
            "learned": one("SELECT COUNT(*) FROM chapters WHERE user_id=? AND status>=1"),
            "reflections": one("SELECT COUNT(*) FROM reflections WHERE user_id=?"),
            "weeklies": one("SELECT COUNT(*) FROM weekly WHERE user_id=?"),
            "redeems": one("SELECT COUNT(*) FROM xp WHERE user_id=? AND key LIKE 'redeem:%'"),
            "longest": u["longest"], "run": u["run"], "veteran": one("SELECT COUNT(*) FROM xp WHERE user_id=? AND key='legacy:season0'"),
            "ratio": ratio, "last7": last7}


BADGES = [
    ("first", "🚀", "First Blood", "Log your first focus session", lambda s: s["sessions"] >= 1),
    ("h10", "⏱️", "10 Hours", "10 hours of focus", lambda s: s["minutes"] >= 600),
    ("h50", "🔥", "50 Hours", "50 hours of focus", lambda s: s["minutes"] >= 3000),
    ("h100", "💎", "100 Hours", "100 hours of focus", lambda s: s["minutes"] >= 6000),
    ("h250", "👑", "250 Hours", "250 hours of focus", lambda s: s["minutes"] >= 15000),
    ("deep5", "🧠", "Deep Diver", "5 deep blocks (50+ min)", lambda s: s["deep"] >= 5),
    ("deep25", "🌊", "Ocean Mind", "25 deep blocks", lambda s: s["deep"] >= 25),
    ("st3", "🕯️", "3-Day Chain", "3-day streak", lambda s: s["longest"] >= 3),
    ("st7", "⚔️", "Week Warrior", "7-day streak", lambda s: s["longest"] >= 7),
    ("st14", "⚡", "Fortnight", "14-day streak", lambda s: s["longest"] >= 14),
    ("st30", "🏆", "Unbreakable", "30-day streak", lambda s: s["longest"] >= 30),
    ("early5", "🌅", "Early Bird", "5 sessions started before 7 AM", lambda s: s["early"] >= 5),
    ("urge10", "🛡️", "Urge Slayer", "Beat 10 urges", lambda s: s["urges_won"] >= 10),
    ("rev25", "🔁", "Memory Forge", "25 spaced revisions done", lambda s: s["revs"] >= 25),
    ("test5", "📝", "Test Pilot", "Log 5 tests", lambda s: s["tests"] >= 5),
    ("master5", "🎓", "Chapter Crusher", "Master 5 chapters", lambda s: s["mastered"] >= 5),
    ("redeem", "🌱", "Never Twice", "Come back right after a miss", lambda s: s["redeems"] >= 1),
    ("refl7", "🪞", "Self-Aware", "7 nightly reflections", lambda s: s["reflections"] >= 7),
    ("weekly1", "🧭", "Navigator", "First weekly review", lambda s: s["weeklies"] >= 1),
    ("veteran", "🎖️", "Season 0 Veteran", "Used the original Growth Tracker", lambda s: s["veteran"] >= 1),
    ("outgrown", "🦋", "Outgrown", "7-day average beats your old A+ baseline", lambda s: s["ratio"] >= 1.0 and s["last7"] > 0),
]


def check_badges(c):
    u = c.user
    s = get_stats(c.conn, u)
    have = {r["id"] for r in q(c.conn, "SELECT id FROM badges WHERE user_id=?", (u["id"],))}
    for bid, emoji, name, desc, fn in BADGES:
        if bid not in have and fn(s):
            c.conn.execute("INSERT OR IGNORE INTO badges(user_id,id,day) VALUES(?,?,?)", (u["id"], bid, iso(today())))
            award(c, f"badge:{bid}", 50, f"Badge: {name}")
            c.ev.append({"t": "badge", "emoji": emoji, "name": name, "desc": desc})
            feed(c, "badge", f"earned {emoji} {name}")


STREAK_BONUS = {3: 30, 7: 100, 14: 200, 21: 300, 30: 500, 50: 800, 75: 1200, 100: 2000}


def evaluate(c):
    """Idempotent: settle streaks, award anything newly earned (quests, redemption, milestones, badges, crew goal, duels)."""
    u = settle(c.conn, c.user["id"])
    c.user = u
    ts = iso(today())
    sv, st = streak_view(c.conn, u)
    if sv["now"] > u["longest"]:
        c.conn.execute("UPDATE users SET longest=? WHERE id=?", (sv["now"], u["id"]))
        u["longest"] = sv["now"]
    if sv["qualified"]:
        if u["comeback"]:
            if award(c, f"redeem:{ts}", 100, "Redemption: you came back. Never miss twice."):
                feed(c, "comeback", "bounced back right after a miss. 🌱 Redemption +100 XP")
            c.conn.execute("UPDATE users SET comeback=0 WHERE id=?", (u["id"],))
            u["comeback"] = 0
        if sv["now"] in STREAK_BONUS:
            if award(c, f"streak:{sv['now']}", STREAK_BONUS[sv["now"]], f"{sv['now']}-day streak!"):
                feed(c, "streak", f"hit a {sv['now']}-day streak 🔥")
    qs = quests(c.conn, u)
    for qu in qs:
        if qu["done"]:
            award(c, f"quest:{ts}:{qu['id']}", qu["xp"], f"Quest: {qu['text']}")
    if qs and all(x["done"] for x in qs):
        if award(c, f"sweep:{ts}", 50, "Clean sweep: all quests done"):
            feed(c, "streak", "cleared every daily quest ✅")
    check_badges(c)
    if u["crew_id"]:
        team_goal(c)
        resolve_duels(c)


def team_goal(c):
    u = c.user
    crew = q1(c.conn, "SELECT * FROM crews WHERE id=?", (u["crew_id"],))
    if not crew:
        return
    ws = wstart(today())
    mem = q(c.conn, "SELECT id FROM users WHERE crew_id=?", (crew["id"],))
    if len(mem) < 2:
        return
    mins = {}
    for m in mem:
        mins[m["id"]] = c.conn.execute("SELECT COALESCE(SUM(minutes),0) FROM focus WHERE user_id=? AND day>=?", (m["id"], iso(ws))).fetchone()[0]
    goal = crew["goal_h"] * 60 * len(mem)
    if sum(mins.values()) >= goal and mins[u["id"]] >= 300:  # you must carry some weight to share the loot
        if award(c, f"crewgoal:{iso(ws)}", 100, "Crew goal smashed this week"):
            feed(c, "crew", "shared in the crew weekly goal 🏁 +100 XP")


def resolve_duels(c):
    t = today()
    for d in q(c.conn, "SELECT * FROM duels WHERE status='active' AND end<? AND (a=? OR b=?)", (iso(t), c.user["id"], c.user["id"])):
        ma = c.conn.execute("SELECT COALESCE(SUM(minutes),0) FROM focus WHERE user_id=? AND day BETWEEN ? AND ?", (d["a"], d["start"], d["end"])).fetchone()[0]
        mb = c.conn.execute("SELECT COALESCE(SUM(minutes),0) FROM focus WHERE user_id=? AND day BETWEEN ? AND ?", (d["b"], d["start"], d["end"])).fetchone()[0]
        win = d["a"] if ma >= mb else d["b"]
        lose = d["b"] if win == d["a"] else d["a"]
        c.conn.execute("UPDATE duels SET status='done', winner=? WHERE id=?", (win, d["id"]))
        for uid, amt, lab in ((win, 150, "Duel won"), (lose, 30, "Duel fought")):
            award(c, f"duel:{d['id']}", amt, lab, uid=uid, day=d["end"], quiet=(uid != c.user["id"]))
        wn = q1(c.conn, "SELECT display FROM users WHERE id=?", (win,))["display"]
        ln = q1(c.conn, "SELECT display FROM users WHERE id=?", (lose,))["display"]
        feed(c, "duel", f"duel finished: {wn} beat {ln} ({max(ma, mb)//60}h{max(ma, mb)%60:02d} vs {min(ma, mb)//60}h{min(ma, mb)%60:02d})", uid=win)


# ----------------------------------------------------------------------------- auth
def hash_pw(pw, salt):
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 150_000).hex()


FAILS = {}


def is_admin(u):
    return bool(u) and u["username"].lower() in ADMINS


def public_user(u):
    return {"admin": is_admin(u), "id": u["id"], "username": u["username"], "display": u["display"], "color": u["color"], "emoji": u["emoji"],
            "identity": u["identity"], "baseline_h": u["baseline_h"], "daily_min": u["daily_min"],
            "onboarded": u["onboarded"], "exams": json.loads(u["exams"] or "[]"), "crew_id": u["crew_id"]}


def new_session(c, uid):
    tok = secrets.token_urlsafe(32)
    c.conn.execute("INSERT INTO sessions(token,user_id,created) VALUES(?,?,?)", (tok, uid, time.time()))
    c.cookie = tok


def make_code():
    return "".join(random.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(6))


ROUTES = {}


def route(method, path, auth=True):
    def deco(fn):
        ROUTES[(method, path)] = (fn, auth)
        return fn
    return deco


@route("POST", "/api/register", auth=False)
def api_register(c):
    name = need(c, "username", maxlen=20)
    pin = need(c, "pin", maxlen=100)
    if not re.fullmatch(r"[A-Za-z0-9_]{2,20}", name):
        raise ApiError("Username: 2-20 letters/numbers/underscore")
    if len(pin) < 4:
        raise ApiError("PIN/password needs at least 4 characters")
    if q1(c.conn, "SELECT id FROM users WHERE username=?", (name,)):
        raise ApiError("That username is taken")
    crew_id = None
    code = str(c.body.get("crew_code", "")).strip().upper()
    cname = str(c.body.get("crew_name", "")).strip()[:30]
    if code:
        cr = q1(c.conn, "SELECT * FROM crews WHERE code=?", (code,))
        if not cr:
            raise ApiError("Invite code not found")
        crew_id = cr["id"]
    elif cname:
        cur = c.conn.execute("INSERT INTO crews(name,code,created_at) VALUES(?,?,?)", (cname, make_code(), now().isoformat(timespec="seconds")))
        crew_id = cur.lastrowid
    salt = secrets.token_hex(16)
    colors = ["#7c5cff", "#ff5c8a", "#22d3a6", "#ffb020", "#3ea6ff", "#ff7a45", "#b6f442", "#e879f9"]
    n = c.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    exams = json.dumps([{"name": "Exams (set your real dates in Me)", "date": "2027-02-15"}])
    cur = c.conn.execute("""INSERT INTO users(username,display,pw_hash,salt,crew_id,color,emoji,exams,created_at,last_settled)
        VALUES(?,?,?,?,?,?,?,?,?,?)""", (name, name, hash_pw(pin, salt), salt, crew_id, colors[n % len(colors)],
                                          random.choice(["🦊", "🐺", "🦅", "🐉", "🦁", "🐯", "🦈", "🔥"]), exams,
                                          now().isoformat(timespec="seconds"), iso(today() - D(1))))
    uid = cur.lastrowid
    c.user = q1(c.conn, "SELECT * FROM users WHERE id=?", (uid,))
    new_session(c, uid)
    # Season 0: carry over the original growth tracker history
    lg = q1(c.conn, "SELECT COALESCE(SUM(done),0) d, COALESCE(SUM(total),0) t FROM legacy WHERE username=? COLLATE NOCASE", (name,))
    if lg and lg["t"]:
        award(c, "legacy:season0", min(500, lg["d"] * 5), f"Season 0 veteran ({lg['d']}/{lg['t']} habits done)", day="0000-00-00")
    if crew_id:
        feed(c, "join", "joined the crew 👋")
    return {"user": public_user(c.user)}


@route("POST", "/api/login", auth=False)
def api_login(c):
    name = need(c, "username", maxlen=20)
    pin = need(c, "pin", maxlen=100)
    key = (c.h.client_address[0], name.lower())
    f = FAILS.get(key, [])
    f = [t for t in f if time.time() - t < 600]
    if len(f) >= 6:
        raise ApiError("Too many attempts. Wait 10 minutes.", 429)
    u = q1(c.conn, "SELECT * FROM users WHERE username=?", (name,))
    if not u or hash_pw(pin, u["salt"]) != u["pw_hash"]:
        f.append(time.time())
        FAILS[key] = f
        raise ApiError("Wrong username or PIN", 401)
    FAILS.pop(key, None)
    c.user = u
    new_session(c, u["id"])
    return {"user": public_user(u)}


@route("POST", "/api/logout")
def api_logout(c):
    tok = c.h.token()
    c.conn.execute("DELETE FROM sessions WHERE token=?", (tok,))
    c.cookie = ""
    return {"ok": True}


@route("GET", "/api/ping", auth=False)
def api_ping(c):
    return {"ok": True}


@route("GET", "/api/me")
def api_me(c):
    return {"user": public_user(c.user), "level": level_info(total_xp(c.conn, c.user["id"])),
            "habit_defs": [{"id": h[0], "name": h[1], "emoji": h[2], "xp": h[3]} for h in HABITS], "subjects": SUBJECTS}


@route("POST", "/api/settings")
def api_settings(c):
    u = c.user
    b = c.body
    fields = {}
    if "display" in b:
        fields["display"] = need(c, "display", maxlen=20) or u["display"]
    if "identity" in b:
        fields["identity"] = need(c, "identity", maxlen=140)
    if "baseline_h" in b:
        fields["baseline_h"] = max(1.0, min(14.0, need(c, "baseline_h", float)))
    if "daily_min" in b:
        fields["daily_min"] = max(15, min(240, need(c, "daily_min", int)))
    if "color" in b and re.fullmatch(r"#[0-9a-fA-F]{6}", str(b["color"])):
        fields["color"] = b["color"]
    if "emoji" in b:
        fields["emoji"] = str(b["emoji"])[:4] or u["emoji"]
    if "exams" in b and isinstance(b["exams"], list):
        ex = []
        for e in b["exams"][:8]:
            try:
                pd(str(e.get("date")))
                ex.append({"name": str(e.get("name", "Exam"))[:40], "date": str(e["date"])})
            except Exception:
                pass
        fields["exams"] = json.dumps(ex)
    if b.get("onboarded"):
        fields["onboarded"] = 1
    if fields:
        c.conn.execute("UPDATE users SET " + ",".join(f"{k}=?" for k in fields) + " WHERE id=?", (*fields.values(), u["id"]))
    c.user = q1(c.conn, "SELECT * FROM users WHERE id=?", (u["id"],))
    return {"user": public_user(c.user)}


# ----------------------------------------------------------------------------- today
@route("GET", "/api/today")
def api_today(c):
    evaluate(c)
    u = c.user
    uid = u["id"]
    t = today()
    ts = iso(t)
    sv, st = streak_view(c.conn, u)
    tm = q1(c.conn, "SELECT * FROM timers WHERE user_id=?", (uid,))
    if tm:
        tm["elapsed"] = int(time.time() - tm["started"])
    done_h = {r["habit"] for r in q(c.conn, "SELECT habit FROM habits WHERE user_id=? AND day=?", (uid, ts))}
    plan = q(c.conn, "SELECT * FROM plans WHERE user_id=? AND day=? ORDER BY id", (uid, ts))
    plan_t = q(c.conn, "SELECT * FROM plans WHERE user_id=? AND day=? ORDER BY id", (uid, iso(t + D(1))))
    due = q(c.conn, """SELECT r.id, r.due, r.stage, ch.name, ch.subject FROM revisions r JOIN chapters ch ON ch.id=r.chapter_id
        WHERE r.user_id=? AND r.due<=? AND r.done_at IS NULL ORDER BY r.due LIMIT 12""", (uid, ts))
    chest = q1(c.conn, "SELECT * FROM chests WHERE user_id=? AND day=?", (uid, ts))
    banners = []
    for n in q(c.conn, "SELECT u.display FROM nudges n JOIN users u ON u.id=n.from_id WHERE n.to_id=? AND n.day=?", (uid, ts)):
        banners.append({"kind": "nudge", "text": f"{n['display']} nudged you 👊 — go earn your day."})
    ys = day_stats(c.conn, uid, t - D(1), t - D(1)).get(iso(t - D(1)))
    if not sv["qualified"] and u["comeback"]:
        banners.append({"kind": "twice", "text": "You missed a day. That's human. Missing TWO is a pattern. Hit your floor today and collect a +100 XP Redemption bonus."})
    if t.weekday() == 0:
        banners.append({"kind": "fresh", "text": "🆕 New week. League reset. Everyone starts from zero — including the person ahead of you."})
    live = []
    if u["crew_id"]:
        live = q(c.conn, """SELECT us.display, us.emoji, tm.subject, tm.started FROM timers tm JOIN users us ON us.id=tm.user_id
            WHERE us.crew_id=? AND us.id<>?""", (u["crew_id"], uid))
        for l in live:
            l["elapsed"] = int(time.time() - l.pop("started"))
    exams = []
    for e in json.loads(u["exams"] or "[]"):
        try:
            exams.append({**e, "days_left": (pd(e["date"]) - t).days})
        except Exception:
            pass
    return {
        "day": ts, "user": public_user(u), "level": level_info(total_xp(c.conn, uid)),
        "xp_today": c.conn.execute("SELECT COALESCE(SUM(amount),0) FROM xp WHERE user_id=? AND day=?", (uid, ts)).fetchone()[0],
        "today": st, "daily_min": u["daily_min"], "stretch_min": int(u["baseline_h"] * 60),
        "streak": sv, "timer": tm, "habits": sorted(done_h),
        "habit_defs": [{"id": h[0], "name": h[1], "emoji": h[2], "xp": h[3]} for h in HABITS],
        "plan": plan, "plan_tomorrow": plan_t, "quests": quests(c.conn, u), "due": due,
        "chest": {"available": sv["qualified"] and not chest, "opened": bool(chest), "reward": chest["reward"] if chest else None},
        "banners": banners, "live": live, "exams": exams,
        "sessions": q(c.conn, "SELECT id, subject, minutes, kind, hour FROM focus WHERE user_id=? AND day=? ORDER BY id DESC", (uid, ts)),
        "reflected": bool(q1(c.conn, "SELECT id FROM reflections WHERE user_id=? AND day=?", (uid, ts))),
    }


# ----------------------------------------------------------------------------- focus
def log_focus(c, subject, minutes, kind, distractions=0, note="", started=None):
    u = c.user
    started = started or now()
    day = iso(today())
    cur = c.conn.execute("INSERT INTO focus(user_id,day,subject,minutes,kind,distractions,note,started_at,hour) VALUES(?,?,?,?,?,?,?,?,?)",
                         (u["id"], day, subject, minutes, kind, distractions, note, started.isoformat(timespec="seconds"), started.hour))
    fid = cur.lastrowid
    base = round(minutes * (1.0 if kind == "timer" else 0.5))
    award(c, f"focus:{fid}", base, f"{minutes} min {subject}" + ("" if kind == "timer" else " (manual, half XP)"))
    if kind == "timer" and minutes >= 50:
        award(c, f"deep:{fid}", 20, "Deep block bonus")
    if kind == "timer" and minutes >= 25 and distractions == 0:
        award(c, f"clean:{fid}", 10, "Clean run: zero distractions")
    if minutes >= 25:
        feed(c, "session", f"locked in {minutes} min of {subject}" + (" ✍️ (manual)" if kind != "timer" else ""))
    evaluate(c)
    return {"ok": True, "minutes": minutes, "id": fid}


@route("POST", "/api/timer/start")
def timer_start(c):
    sub = need(c, "subject")
    if sub not in SUBJECTS:
        raise ApiError("bad subject")
    target = max(5, min(180, need(c, "target", int, 25)))
    if q1(c.conn, "SELECT 1 x FROM timers WHERE user_id=?", (c.user["id"],)):
        raise ApiError("A timer is already running")
    c.conn.execute("INSERT INTO timers(user_id,subject,started,target) VALUES(?,?,?,?)", (c.user["id"], sub, time.time(), target))
    return {"ok": True}


@route("POST", "/api/timer/extend")
def timer_extend(c):
    add = max(5, min(60, need(c, "add", int, 20)))
    c.conn.execute("UPDATE timers SET target=target+? WHERE user_id=?", (add, c.user["id"]))
    return {"ok": True}


@route("POST", "/api/timer/distract")
def timer_distract(c):
    c.conn.execute("UPDATE timers SET distractions=distractions+1 WHERE user_id=?", (c.user["id"],))
    return {"ok": True}


@route("POST", "/api/timer/stop")
def timer_stop(c):
    t = q1(c.conn, "SELECT * FROM timers WHERE user_id=?", (c.user["id"],))
    if not t:
        raise ApiError("No timer running")
    c.conn.execute("DELETE FROM timers WHERE user_id=?", (c.user["id"],))
    if c.body.get("discard"):
        return {"ok": True, "discarded": True}
    elapsed = (time.time() - t["started"]) / 60.0
    minutes = int(min(elapsed, t["target"] + 15, 240))  # forgot to stop? you only get target+15
    if minutes < 5:
        return {"ok": True, "too_short": True, "minutes": minutes}
    note = str(c.body.get("note", ""))[:200]
    return log_focus(c, t["subject"], minutes, "timer", t["distractions"], note, dt.datetime.fromtimestamp(t["started"]))


@route("POST", "/api/focus")
def focus_manual(c):
    sub = need(c, "subject")
    if sub not in SUBJECTS:
        raise ApiError("bad subject")
    mins = max(5, min(180, need(c, "minutes", int)))
    used = c.conn.execute("SELECT COALESCE(SUM(minutes),0) FROM focus WHERE user_id=? AND day=? AND kind='manual'", (c.user["id"], iso(today()))).fetchone()[0]
    if used + mins > 180:
        raise ApiError("Manual logging caps at 3h/day. Use the timer: it's worth double XP and it's what keeps your streak.")
    return log_focus(c, sub, mins, "manual", 0, str(c.body.get("note", ""))[:200])


@route("POST", "/api/focus/delete")
def focus_delete(c):
    fid = need(c, "id", int)
    r = q1(c.conn, "SELECT * FROM focus WHERE id=? AND user_id=? AND day=?", (fid, c.user["id"], iso(today())))
    if not r or r["kind"] != "manual":
        raise ApiError("Only today's manual entries can be removed")
    c.conn.execute("DELETE FROM focus WHERE id=?", (fid,))
    c.conn.execute("DELETE FROM xp WHERE user_id=? AND key=?", (c.user["id"], f"focus:{fid}"))
    return {"ok": True}


# ----------------------------------------------------------------------------- habits, plan, urges, chest
@route("POST", "/api/habit")
def api_habit(c):
    hid = need(c, "habit")
    hd = next((h for h in HABITS if h[0] == hid), None)
    if not hd:
        raise ApiError("bad habit")
    ts = iso(today())
    uid = c.user["id"]
    if c.body.get("done", True):
        c.conn.execute("INSERT OR IGNORE INTO habits(user_id,day,habit) VALUES(?,?,?)", (uid, ts, hid))
        award(c, f"habit:{ts}:{hid}", hd[3], hd[1])
    else:
        c.conn.execute("DELETE FROM habits WHERE user_id=? AND day=? AND habit=?", (uid, ts, hid))
        c.conn.execute("DELETE FROM xp WHERE user_id=? AND key=?", (uid, f"habit:{ts}:{hid}"))
    evaluate(c)
    return {"ok": True}


@route("POST", "/api/plan")
def plan_add(c):
    which = c.body.get("when", "today")
    d = today() + (D(1) if which == "tomorrow" else D(0))
    text = need(c, "text", maxlen=120)
    if not text:
        raise ApiError("Write the task")
    n = c.conn.execute("SELECT COUNT(*) FROM plans WHERE user_id=? AND day=?", (c.user["id"], iso(d))).fetchone()[0]
    if n >= 5:
        raise ApiError("Max 5 tasks per day. A plan with 12 items is a wish list.")
    c.conn.execute("INSERT INTO plans(user_id,day,text,cue) VALUES(?,?,?,?)", (c.user["id"], iso(d), text, str(c.body.get("cue", ""))[:120]))
    evaluate(c)
    return {"ok": True}


@route("POST", "/api/plan/toggle")
def plan_toggle(c):
    pid = need(c, "id", int)
    p = q1(c.conn, "SELECT * FROM plans WHERE id=? AND user_id=?", (pid, c.user["id"]))
    if not p:
        raise ApiError("not found", 404)
    nd = 0 if p["done"] else 1
    c.conn.execute("UPDATE plans SET done=? WHERE id=?", (nd, pid))
    if nd:
        award(c, f"plan:{pid}", 25, "Kept a promise to yourself")
    else:
        c.conn.execute("DELETE FROM xp WHERE user_id=? AND key=?", (c.user["id"], f"plan:{pid}"))
    evaluate(c)
    return {"ok": True}


@route("POST", "/api/plan/delete")
def plan_delete(c):
    pid = need(c, "id", int)
    c.conn.execute("DELETE FROM plans WHERE id=? AND user_id=?", (pid, c.user["id"]))
    c.conn.execute("DELETE FROM xp WHERE user_id=? AND key=?", (c.user["id"], f"plan:{pid}"))
    return {"ok": True}


@route("POST", "/api/urge")
def api_urge(c):
    outcome = need(c, "outcome")
    if outcome not in ("resisted", "redirected", "gave_in"):
        raise ApiError("bad outcome")
    n = now()
    cur = c.conn.execute("INSERT INTO urges(user_id,ts,hour,trigger,outcome) VALUES(?,?,?,?,?)",
                         (c.user["id"], n.isoformat(timespec="seconds"), n.hour, str(c.body.get("trigger", ""))[:60], outcome))
    cnt = c.conn.execute("SELECT COUNT(*) FROM urges WHERE user_id=? AND substr(ts,1,10)=? AND outcome<>'gave_in'", (c.user["id"], n.date().isoformat())).fetchone()[0]
    if outcome != "gave_in" and cnt <= 5:
        award(c, f"urge:{cur.lastrowid}", 25, "Urge surfed. The wave passed.")
    evaluate(c)
    return {"ok": True}


@route("POST", "/api/chest")
def api_chest(c):
    sv, _ = streak_view(c.conn, c.user)
    ts = iso(today())
    if not sv["qualified"]:
        raise ApiError("Hit your daily floor to unlock today's chest")
    if q1(c.conn, "SELECT 1 x FROM chests WHERE user_id=? AND day=?", (c.user["id"], ts)):
        raise ApiError("Already opened today")
    r = random.random()
    if r < 0.05:
        reward, label = "freeze", "❄️ Streak Freeze (RARE)"
        c.conn.execute("UPDATE users SET freezes=MIN(2, freezes+1) WHERE id=?", (c.user["id"],))
        c.user["freezes"] = min(2, c.user["freezes"] + 1)
        amt = 25
        tier = "rare"
    elif r < 0.15:
        amt, tier = random.randint(100, 160), "epic"
    elif r < 0.40:
        amt, tier = random.randint(60, 95), "rare"
    else:
        amt, tier = random.randint(25, 55), "common"
    if r >= 0.05:
        reward, label = f"{amt} XP", f"{amt} XP"
    c.conn.execute("INSERT INTO chests(user_id,day,reward) VALUES(?,?,?)", (c.user["id"], ts, label))
    award(c, f"chest:{ts}", amt, f"Daily chest: {label}")
    if tier in ("epic", "rare") and r < 0.15:
        feed(c, "chest", f"opened an {tier.upper()} chest: {label} 🎁")
    evaluate(c)
    return {"ok": True, "tier": tier, "label": label}


# ----------------------------------------------------------------------------- reflection
@route("GET", "/api/reflect")
def reflect_get(c):
    ts = iso(today())
    today_r = q1(c.conn, "SELECT * FROM reflections WHERE user_id=? AND day=?", (c.user["id"], ts))
    hist = q(c.conn, "SELECT day, mood, energy, win, leak, kind_note, tomorrow FROM reflections WHERE user_id=? ORDER BY day DESC LIMIT 14", (c.user["id"],))
    st = day_stats(c.conn, c.user["id"], today(), today()).get(ts) or {"total": 0}
    return {"today": today_r, "history": hist, "minutes": st["total"], "daily_min": c.user["daily_min"], "day": ts}


@route("POST", "/api/reflect")
def reflect_post(c):
    ts = iso(today())
    mood = max(1, min(5, need(c, "mood", int, 3)))
    energy = max(1, min(5, need(c, "energy", int, 3)))
    win = need(c, "win", maxlen=300)
    leak = need(c, "leak", maxlen=300, default="")
    kind = need(c, "kind_note", maxlen=300, default="")
    tomorrow = need(c, "tomorrow", maxlen=120, default="")
    cue = need(c, "cue", maxlen=120, default="")
    if len(win) < 3:
        raise ApiError("Name one real win, even a small one. Specific beats big.")
    c.conn.execute("""INSERT INTO reflections(user_id,day,mood,energy,win,leak,kind_note,tomorrow) VALUES(?,?,?,?,?,?,?,?)
        ON CONFLICT(user_id,day) DO UPDATE SET mood=excluded.mood, energy=excluded.energy, win=excluded.win, leak=excluded.leak,
        kind_note=excluded.kind_note, tomorrow=excluded.tomorrow""", (c.user["id"], ts, mood, energy, win, leak, kind, tomorrow))
    award(c, f"reflect:{ts}", 40, "Nightly reflection")
    if tomorrow:
        tmr = iso(today() + D(1))
        n = c.conn.execute("SELECT COUNT(*) FROM plans WHERE user_id=? AND day=? AND text=?", (c.user["id"], tmr, tomorrow)).fetchone()[0]
        if not n:
            c.conn.execute("INSERT INTO plans(user_id,day,text,cue) VALUES(?,?,?,?)", (c.user["id"], tmr, tomorrow, cue))
    evaluate(c)
    return {"ok": True}


def week_summary(conn, u, ws):
    we = ws + D(6)
    st = day_stats(conn, u["id"], ws, we)
    pst = day_stats(conn, u["id"], ws - D(7), ws - D(1))
    tot = sum(v["total"] for v in st.values())
    ptot = sum(v["total"] for v in pst.values())
    bysub = {}
    for v in st.values():
        for s, m in v["sub"].items():
            bysub[s] = bysub.get(s, 0) + m
    days = sum(1 for v in st.values() if qualifies(v, u["daily_min"]))
    best = max(st.items(), key=lambda kv: kv[1]["total"], default=(None, None))
    xp = conn.execute("SELECT COALESCE(SUM(amount),0) FROM xp WHERE user_id=? AND day BETWEEN ? AND ?", (u["id"], iso(ws), iso(we))).fetchone()[0]
    return {"week": iso(ws), "minutes": tot, "prev_minutes": ptot, "by_subject": bysub, "qualified_days": days,
            "best_day": best[0], "best_day_minutes": best[1]["total"] if best[1] else 0, "xp": xp,
            "avg_mood": conn.execute("SELECT AVG(mood) FROM reflections WHERE user_id=? AND day BETWEEN ? AND ?", (u["id"], iso(ws), iso(we))).fetchone()[0]}


@route("GET", "/api/weekly")
def weekly_get(c):
    t = today()
    ws = wstart(t)
    # Review the week that just finished on Mon, otherwise the week in progress
    rs = ws - D(7) if t.weekday() == 0 else ws
    ex = q1(c.conn, "SELECT * FROM weekly WHERE user_id=? AND week=?", (c.user["id"], iso(rs)))
    return {"summary": week_summary(c.conn, c.user, rs), "existing": ex}


@route("POST", "/api/weekly")
def weekly_post(c):
    t = today()
    ws = wstart(t)
    rs = ws - D(7) if t.weekday() == 0 else ws
    vals = [need(c, k, maxlen=300, default="") for k in ("best", "leak", "change", "premortem", "ifthen")]
    if not vals[2]:
        raise ApiError("Pick ONE thing to change next week")
    c.conn.execute("""INSERT INTO weekly(user_id,week,best,leak,change,premortem,ifthen) VALUES(?,?,?,?,?,?,?)
        ON CONFLICT(user_id,week) DO UPDATE SET best=excluded.best, leak=excluded.leak, change=excluded.change,
        premortem=excluded.premortem, ifthen=excluded.ifthen""", (c.user["id"], iso(rs), *vals))
    award(c, f"weekly:{iso(rs)}", 100, "Weekly review")
    evaluate(c)
    return {"ok": True}


# ----------------------------------------------------------------------------- crew
@route("POST", "/api/crew/join")
def crew_join(c):
    code = need(c, "code").upper()
    cr = q1(c.conn, "SELECT * FROM crews WHERE code=?", (code,))
    if not cr:
        raise ApiError("Invite code not found")
    c.conn.execute("UPDATE users SET crew_id=? WHERE id=?", (cr["id"], c.user["id"]))
    c.user["crew_id"] = cr["id"]
    feed(c, "join", "joined the crew 👋")
    return {"ok": True}


@route("POST", "/api/crew/create")
def crew_create(c):
    name = need(c, "name", maxlen=30)
    cur = c.conn.execute("INSERT INTO crews(name,code,created_at) VALUES(?,?,?)", (name, make_code(), now().isoformat(timespec="seconds")))
    c.conn.execute("UPDATE users SET crew_id=? WHERE id=?", (cur.lastrowid, c.user["id"]))
    return {"ok": True}


@route("GET", "/api/crew")
def api_crew(c):
    u = c.user
    if not u["crew_id"]:
        return {"crew": None}
    crew = q1(c.conn, "SELECT * FROM crews WHERE id=?", (u["crew_id"],))
    t = today()
    ts = iso(t)
    ws = wstart(t)
    out = []
    for m in q(c.conn, "SELECT id FROM users WHERE crew_id=?", (crew["id"],)):
        mu = settle(c.conn, m["id"])
        sv, st = streak_view(c.conn, mu)
        wk = c.conn.execute("SELECT COALESCE(SUM(amount),0) FROM xp WHERE user_id=? AND day>=? AND day<>'0000-00-00'", (mu["id"], iso(ws))).fetchone()[0]
        wm = c.conn.execute("SELECT COALESCE(SUM(minutes),0) FROM focus WHERE user_id=? AND day>=?", (mu["id"], iso(ws))).fetchone()[0]
        lw = c.conn.execute("SELECT COALESCE(SUM(amount),0) FROM xp WHERE user_id=? AND day>=? AND day<?", (mu["id"], iso(ws - D(7)), iso(ws))).fetchone()[0]
        tx = total_xp(c.conn, mu["id"])
        live = q1(c.conn, "SELECT subject, started FROM timers WHERE user_id=?", (mu["id"],))
        out.append({"id": mu["id"], "display": mu["display"], "emoji": mu["emoji"], "color": mu["color"], "me": mu["id"] == u["id"],
                    "identity": mu["identity"], "week_xp": wk, "last_week_xp": lw, "week_min": wm, "today_min": st["total"],
                    "streak": sv["now"], "qualified": sv["qualified"], "level": level_info(tx),
                    "live": {"subject": live["subject"], "elapsed": int(time.time() - live["started"])} if live else None})
    out.sort(key=lambda x: -x["week_xp"])
    for i, m in enumerate(out):
        m["rank"] = i + 1
    me_i = next(i for i, m in enumerate(out) if m["me"])
    rival = None
    if me_i > 0:
        rival = {"name": out[me_i - 1]["display"], "gap": out[me_i - 1]["week_xp"] - out[me_i]["week_xp"], "dir": "ahead"}
    elif len(out) > 1:
        rival = {"name": out[1]["display"], "gap": out[0]["week_xp"] - out[1]["week_xp"], "dir": "behind"}
    goal_min = crew["goal_h"] * 60 * len(out)
    nudged = {r["to_id"] for r in q(c.conn, "SELECT to_id FROM nudges WHERE from_id=? AND day=?", (u["id"], ts))}
    for m in out:
        m["nudged"] = m["id"] in nudged
    fd = q(c.conn, """SELECT f.id, f.ts, f.kind, f.text, us.display, us.emoji, us.color, f.user_id FROM feed f JOIN users us ON us.id=f.user_id
        WHERE f.crew_id=? ORDER BY f.id DESC LIMIT 40""", (crew["id"],))
    for f in fd:
        rs = q(c.conn, "SELECT emoji, COUNT(*) n FROM reactions WHERE feed_id=? GROUP BY emoji", (f["id"],))
        f["reactions"] = {r["emoji"]: r["n"] for r in rs}
        mine = q1(c.conn, "SELECT emoji FROM reactions WHERE feed_id=? AND user_id=?", (f["id"], u["id"]))
        f["mine"] = mine["emoji"] if mine else None
    duels = q(c.conn, """SELECT d.*, ua.display an, ub.display bn FROM duels d JOIN users ua ON ua.id=d.a JOIN users ub ON ub.id=d.b
        WHERE d.crew_id=? AND d.status IN ('pending','active') ORDER BY d.id DESC""", (crew["id"],))
    for d in duels:
        if d["status"] == "active":
            for k in ("a", "b"):
                d[k + "_min"] = c.conn.execute("SELECT COALESCE(SUM(minutes),0) FROM focus WHERE user_id=? AND day BETWEEN ? AND ?", (d[k], d["start"], d["end"])).fetchone()[0]
    return {"crew": {"name": crew["name"], "code": crew["code"], "goal_h": crew["goal_h"]}, "members": out, "rival": rival,
            "team": {"minutes": sum(m["week_min"] for m in out), "goal": int(goal_min)}, "feed": fd, "duels": duels, "me": u["id"]}


@route("POST", "/api/react")
def api_react(c):
    fid = need(c, "feed_id", int)
    em = need(c, "emoji")
    if em not in EMOJIS:
        raise ApiError("bad emoji")
    f = q1(c.conn, "SELECT * FROM feed WHERE id=? AND crew_id=?", (fid, c.user["crew_id"]))
    if not f:
        raise ApiError("not found", 404)
    cur = q1(c.conn, "SELECT emoji FROM reactions WHERE feed_id=? AND user_id=?", (fid, c.user["id"]))
    if cur and cur["emoji"] == em:
        c.conn.execute("DELETE FROM reactions WHERE feed_id=? AND user_id=?", (fid, c.user["id"]))
    else:
        c.conn.execute("INSERT OR REPLACE INTO reactions(feed_id,user_id,emoji) VALUES(?,?,?)", (fid, c.user["id"], em))
    return {"ok": True}


@route("POST", "/api/nudge")
def api_nudge(c):
    to = need(c, "to", int)
    tu = q1(c.conn, "SELECT * FROM users WHERE id=? AND crew_id=?", (to, c.user["crew_id"]))
    if not tu or to == c.user["id"]:
        raise ApiError("bad target")
    ts = iso(today())
    try:
        c.conn.execute("INSERT INTO nudges(from_id,to_id,day) VALUES(?,?,?)", (c.user["id"], to, ts))
    except sqlite3.IntegrityError:
        raise ApiError("You already nudged them today")
    award(c, f"nudge:{ts}:{to}", 5, f"Nudged {tu['display']}")
    return {"ok": True}


@route("POST", "/api/duel")
def api_duel(c):
    opp = q1(c.conn, "SELECT * FROM users WHERE id=? AND crew_id=?", (need(c, "opponent", int), c.user["crew_id"]))
    if not opp or opp["id"] == c.user["id"]:
        raise ApiError("bad opponent")
    days = max(3, min(14, need(c, "days", int, 7)))
    ex = q1(c.conn, "SELECT id FROM duels WHERE status IN ('pending','active') AND ((a=? AND b=?) OR (a=? AND b=?))", (c.user["id"], opp["id"], opp["id"], c.user["id"]))
    if ex:
        raise ApiError("You two already have a duel going")
    c.conn.execute("INSERT INTO duels(crew_id,a,b,days,status) VALUES(?,?,?,?,'pending')", (c.user["crew_id"], c.user["id"], opp["id"], days))
    return {"ok": True}


@route("POST", "/api/duel/accept")
def api_duel_accept(c):
    d = q1(c.conn, "SELECT * FROM duels WHERE id=? AND b=? AND status='pending'", (need(c, "id", int), c.user["id"]))
    if not d:
        raise ApiError("not found", 404)
    t = today()
    c.conn.execute("UPDATE duels SET status='active', start=?, end=? WHERE id=?", (iso(t), iso(t + D(d["days"] - 1)), d["id"]))
    a = q1(c.conn, "SELECT display FROM users WHERE id=?", (d["a"],))["display"]
    feed(c, "duel", f"accepted {a}'s {d['days']}-day focus duel ⚔️")
    return {"ok": True}


# ----------------------------------------------------------------------------- syllabus & spaced repetition
STATUS = ["Untouched", "Learned", "Practiced", "Mastered"]
STAGES = [1, 3, 7, 14, 30]


def seed_chapters(conn, uid):
    if conn.execute("SELECT COUNT(*) FROM chapters WHERE user_id=?", (uid,)).fetchone()[0]:
        return
    for sub, grades in SYLLABUS.items():
        for g, names in grades.items():
            for n in names:
                conn.execute("INSERT INTO chapters(user_id,subject,grade,name) VALUES(?,?,?,?)", (uid, sub, g, n))


@route("GET", "/api/syllabus")
def syllabus_get(c):
    seed_chapters(c.conn, c.user["id"])
    chs = q(c.conn, "SELECT id, subject, grade, name, status, custom FROM chapters WHERE user_id=? ORDER BY subject, grade, id", (c.user["id"],))
    upcoming = q(c.conn, """SELECT r.id, r.due, r.stage, ch.name, ch.subject FROM revisions r JOIN chapters ch ON ch.id=r.chapter_id
        WHERE r.user_id=? AND r.done_at IS NULL ORDER BY r.due LIMIT 30""", (c.user["id"],))
    return {"chapters": chs, "statuses": STATUS, "revisions": upcoming, "today": iso(today())}


@route("POST", "/api/chapter")
def chapter_set(c):
    cid = need(c, "id", int)
    s = max(0, min(3, need(c, "status", int)))
    ch = q1(c.conn, "SELECT * FROM chapters WHERE id=? AND user_id=?", (cid, c.user["id"]))
    if not ch:
        raise ApiError("not found", 404)
    t = today()
    c.conn.execute("UPDATE chapters SET status=? WHERE id=?", (s, cid))
    if s >= 1 and not ch["learned_on"]:
        c.conn.execute("UPDATE chapters SET learned_on=? WHERE id=?", (iso(t), cid))
        for i, off in enumerate(STAGES):
            c.conn.execute("INSERT INTO revisions(user_id,chapter_id,due,stage) VALUES(?,?,?,?)", (c.user["id"], cid, iso(t + D(off)), i))
    for lvl, amt in ((1, 50), (2, 50), (3, 100)):
        if s >= lvl:
            if award(c, f"chap:{cid}:{lvl}", amt, f"{ch['name']}: {STATUS[lvl]}") and lvl >= 2:
                feed(c, "chapter", f"moved {ch['subject']} · {ch['name']} to {STATUS[lvl]} 📚")
    evaluate(c)
    return {"ok": True}


@route("POST", "/api/chapter/add")
def chapter_add(c):
    sub = need(c, "subject")
    if sub not in SUBJECTS:
        raise ApiError("bad subject")
    name = need(c, "name", maxlen=60)
    if not name:
        raise ApiError("name it")
    seed_chapters(c.conn, c.user["id"])
    c.conn.execute("INSERT INTO chapters(user_id,subject,grade,name,custom) VALUES(?,?,?,?,1)", (c.user["id"], sub, "+", name))
    return {"ok": True}


@route("POST", "/api/revision")
def revision_done(c):
    rid = need(c, "id", int)
    res = need(c, "result", default="solid")
    r = q1(c.conn, "SELECT * FROM revisions WHERE id=? AND user_id=? AND done_at IS NULL", (rid, c.user["id"]))
    if not r:
        raise ApiError("not found", 404)
    t = today()
    c.conn.execute("UPDATE revisions SET done_at=?, result=? WHERE id=?", (iso(t), res, rid))
    award(c, f"rev:{rid}", 30, "Active recall done")
    if res == "shaky":
        c.conn.execute("INSERT INTO revisions(user_id,chapter_id,due,stage) VALUES(?,?,?,?)", (c.user["id"], r["chapter_id"], iso(t + D(2)), r["stage"]))
    elif res == "blank":
        c.conn.execute("INSERT INTO revisions(user_id,chapter_id,due,stage) VALUES(?,?,?,?)", (c.user["id"], r["chapter_id"], iso(t + D(1)), 0))
    evaluate(c)
    return {"ok": True}


# ----------------------------------------------------------------------------- tests
@route("GET", "/api/tests")
def tests_get(c):
    rows = q(c.conn, "SELECT * FROM tests WHERE user_id=? ORDER BY day, id", (c.user["id"],))
    tot = {"concept": 0, "silly": 0, "time": 0}
    for r in rows[-8:]:
        tot["concept"] += r["concept"]
        tot["silly"] += r["silly"]
        tot["time"] += r["timeerr"]
    return {"tests": rows, "errors": tot}


@route("POST", "/api/test")
def test_post(c):
    name = need(c, "name", maxlen=60) or "Test"
    kind = need(c, "kind", default="mock")
    sub = need(c, "subject", default="All")
    score, mx = need(c, "score", float), need(c, "max", float)
    if mx <= 0 or score > mx:
        raise ApiError("Check the marks")
    cur = c.conn.execute("INSERT INTO tests(user_id,day,name,kind,subject,score,maxscore,concept,silly,timeerr,note) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                         (c.user["id"], iso(today()), name, kind, sub, score, mx, max(0, need(c, "concept", int, 0)),
                          max(0, need(c, "silly", int, 0)), max(0, need(c, "time", int, 0)), str(c.body.get("note", ""))[:200]))
    award(c, f"test:{cur.lastrowid}", 80, "Logged a test (data > feelings)")
    feed(c, "test", f"logged {sub} {kind}: {round(score / mx * 100)}%")
    evaluate(c)
    return {"ok": True}


# ----------------------------------------------------------------------------- insights
@route("GET", "/api/insights")
def api_insights(c):
    u = c.user
    uid = u["id"]
    t = today()
    stt = day_stats(c.conn, uid, t - D(83), t)
    frozen = set(json.loads(u["frozen_days"] or "[]"))
    heat = []
    for i in range(83, -1, -1):
        d = iso(t - D(i))
        heat.append({"d": d, "m": stt.get(d, {"total": 0})["total"], "f": d in frozen, "q": qualifies(stt.get(d), u["daily_min"])})
    hours = [0] * 24
    for r in q(c.conn, "SELECT hour, SUM(minutes) m FROM focus WHERE user_id=? AND kind='timer' GROUP BY hour", (uid,)):
        hours[r["hour"]] = r["m"]
    weeks = []
    ws0 = wstart(t)
    for i in range(7, -1, -1):
        ws = ws0 - D(7 * i)
        m = c.conn.execute("SELECT COALESCE(SUM(minutes),0) FROM focus WHERE user_id=? AND day BETWEEN ? AND ?", (uid, iso(ws), iso(ws + D(6)))).fetchone()[0]
        weeks.append({"w": iso(ws), "m": m})
    # Ghost race: this week vs your own best week
    wk_days = lambda ws: [stt_all.get(iso(ws + D(i)), 0) for i in range(7)]
    stt_all = {r["day"]: r["m"] for r in q(c.conn, "SELECT day, SUM(minutes) m FROM focus WHERE user_id=? GROUP BY day", (uid,))}
    allweeks = {}
    for d, m in stt_all.items():
        w = iso(wstart(pd(d)))
        allweeks[w] = allweeks.get(w, 0) + m
    cur_w = iso(ws0)
    prev = {w: m for w, m in allweeks.items() if w != cur_w}
    ghost = None
    if prev:
        bw = max(prev, key=prev.get)
        g = wk_days(pd(bw))
        ghost = {"week": bw, "total": prev[bw], "cum": [sum(g[:i + 1]) for i in range(7)]}
    cw = wk_days(ws0)
    cum = [sum(cw[:i + 1]) if i <= t.weekday() else None for i in range(7)]
    last7 = sum(stt.get(iso(t - D(i)), {"total": 0})["total"] for i in range(7))
    ratio = (last7 / 7.0) / max(u["baseline_h"] * 60, 1)
    sub7 = {}
    for i in range(7):
        for s, m in stt.get(iso(t - D(i)), {"sub": {}})["sub"].items():
            sub7[s] = sub7.get(s, 0) + m
    seed_chapters(c.conn, uid)
    ch = q1(c.conn, "SELECT COUNT(*) n, SUM(status>=1) l, SUM(status>=3) mst FROM chapters WHERE user_id=?", (uid,))
    recent = c.conn.execute("SELECT COUNT(*) FROM chapters WHERE user_id=? AND learned_on>=?", (uid, iso(t - D(14)))).fetchone()[0]
    rate = recent / 2.0
    left = ch["n"] - (ch["l"] or 0)
    exams = []
    for e in json.loads(u["exams"] or "[]"):
        try:
            dl = (pd(e["date"]) - t).days
            wks = max(dl / 7.0, 0.1)
            exams.append({"name": e["name"], "days_left": dl, "need_per_week": round(left / wks, 1)})
        except Exception:
            pass
    s = get_stats(c.conn, u)
    wins = q(c.conn, "SELECT day, win FROM reflections WHERE user_id=? AND length(win)>2 ORDER BY day DESC LIMIT 6", (uid,))
    mood = q(c.conn, "SELECT day, mood, energy FROM reflections WHERE user_id=? ORDER BY day DESC LIMIT 14", (uid,))
    urg = q(c.conn, "SELECT trigger, COUNT(*) n FROM urges WHERE user_id=? AND trigger<>'' GROUP BY trigger ORDER BY n DESC LIMIT 4", (uid,))
    badges = {r["id"]: r["day"] for r in q(c.conn, "SELECT id, day FROM badges WHERE user_id=?", (uid,))}
    qdays = sum(1 for h in heat if h["q"])
    return {"heat": heat, "hours": hours, "weeks": weeks, "ghost": ghost, "cum": cum, "outgrow": {"ratio": round(ratio, 2), "last7": last7, "baseline_h": u["baseline_h"]},
            "sub7": sub7, "chapters": {"total": ch["n"], "learned": ch["l"] or 0, "mastered": ch["mst"] or 0, "rate": rate, "left": left},
            "exams": exams, "mood": list(reversed(mood)), "urge_triggers": urg,
            "evidence": {"hours": round(s["minutes"] / 60, 1), "sessions": s["sessions"], "deep": s["deep"], "longest": max(u["longest"], u["run"]),
                         "days_hit": qdays, "revs": s["revs"], "urges_won": s["urges_won"], "tests": s["tests"], "mastered": s["mastered"],
                         "learned": s["learned"], "wins": wins},
            "badges": [{"id": b[0], "emoji": b[1], "name": b[2], "desc": b[3], "got": b[0] in badges, "day": badges.get(b[0])} for b in BADGES],
            "level": level_info(total_xp(c.conn, uid)), "xp_log": q(c.conn, "SELECT day, label, amount FROM xp WHERE user_id=? ORDER BY id DESC LIMIT 15", (uid,))}


# ----------------------------------------------------------------------------- chat (text only: crew room + private DMs)
CHAT_MAX = 1000
CHAT_COND = threading.Condition()
CHAT_SEQ = 0          # bumps on every send/delete; long-polling clients wait on it
CHAT_RATE = {}        # user_id -> recent send timestamps


def chat_bump():
    global CHAT_SEQ
    with CHAT_COND:
        CHAT_SEQ += 1
        CHAT_COND.notify_all()


def qp(c, key, default=""):
    v = c.q.get(key)
    return v[0] if v else default


def qpi(c, key, default=0):
    try:
        return int(qp(c, key, default))
    except (TypeError, ValueError):
        return default


def chat_thread(c, key):
    """Client key ('crew' or 'dm:<user id>') -> (db thread id, other user or None). Enforces same-crew access."""
    u = c.user
    if not u["crew_id"]:
        raise ApiError("Join a crew to use chat", 403)
    if key == "crew":
        return f"crew:{u['crew_id']}", None
    m = re.fullmatch(r"dm:(\d+)", key or "")
    if not m:
        raise ApiError("bad thread")
    oid = int(m.group(1))
    other = q1(c.conn, "SELECT id, display, emoji, color, crew_id FROM users WHERE id=?", (oid,))
    if not other or other["crew_id"] != u["crew_id"] or oid == u["id"]:
        raise ApiError("No such member", 404)
    lo, hi = sorted((u["id"], oid))
    return f"dm:{lo}:{hi}", other


def chat_mark(conn, uid, thread, last_id):
    conn.execute("""INSERT INTO chat_reads(user_id,thread,last_id) VALUES(?,?,?)
        ON CONFLICT(user_id,thread) DO UPDATE SET last_id=MAX(last_id, excluded.last_id)""", (uid, thread, last_id))


def chat_unread(conn, u):
    """{'crew': n, 'dm:<other id>': n}. A newcomer's crew history starts out as read."""
    if not u["crew_id"]:
        return {}
    ct = f"crew:{u['crew_id']}"
    conn.execute("""INSERT OR IGNORE INTO chat_reads(user_id,thread,last_id)
        SELECT ?, ?, COALESCE(MAX(id),0) FROM messages WHERE thread=?""", (u["id"], ct, ct))
    out = {}
    for r in q(conn, """SELECT m.thread, m.sender, COUNT(*) n FROM messages m
            LEFT JOIN chat_reads r ON r.user_id=? AND r.thread=m.thread
            WHERE m.deleted=0 AND m.sender<>? AND m.id>COALESCE(r.last_id,0) AND (m.thread=? OR m.recip=?)
            GROUP BY m.thread, m.sender""", (u["id"], u["id"], ct, u["id"])):
        key = "crew" if r["thread"] == ct else f"dm:{r['sender']}"
        out[key] = out.get(key, 0) + r["n"]
    return out


def chat_people(conn, crew_id):
    return {r["id"]: {"display": r["display"], "emoji": r["emoji"], "color": r["color"]}
            for r in q(conn, "SELECT id, display, emoji, color FROM users WHERE crew_id=?", (crew_id,))}


def chat_msg(m):
    return {"id": m["id"], "uid": m["sender"], "ts": m["ts"], "text": m["body"]}


def chat_fetch(conn, thread, after=0, before=0, limit=60):
    if after:
        rows = q(conn, "SELECT id,sender,ts,body FROM messages WHERE thread=? AND id>? AND deleted=0 ORDER BY id LIMIT 200", (thread, after))
        return rows, False
    rows = q(conn, "SELECT id,sender,ts,body FROM messages WHERE thread=? AND id<? AND deleted=0 ORDER BY id DESC LIMIT ?",
             (thread, before or 2 ** 62, limit + 1))
    return rows[:limit][::-1], len(rows) > limit


@route("GET", "/api/chat/threads")
def chat_threads(c):
    u = c.user
    if not u["crew_id"]:
        return {"threads": [], "unread": {}, "total": 0, "people": {}, "seq": CHAT_SEQ}
    unread = chat_unread(c.conn, u)
    crew = q1(c.conn, "SELECT name FROM crews WHERE id=?", (u["crew_id"],))

    def last_of(th):
        m = q1(c.conn, "SELECT id,sender,ts,body FROM messages WHERE thread=? AND deleted=0 ORDER BY id DESC LIMIT 1", (th,))
        return {"id": m["id"], "uid": m["sender"], "ts": m["ts"], "text": m["body"][:80]} if m else None
    threads = [{"key": "crew", "kind": "crew", "title": crew["name"], "last": last_of(f"crew:{u['crew_id']}"), "unread": unread.get("crew", 0)}]
    dms = []
    for m in q(c.conn, "SELECT id, display, emoji, color FROM users WHERE crew_id=? AND id<>? ORDER BY display COLLATE NOCASE", (u["crew_id"], u["id"])):
        lo, hi = sorted((u["id"], m["id"]))
        dms.append({"key": f"dm:{m['id']}", "kind": "dm", "title": m["display"], "emoji": m["emoji"], "color": m["color"], "uid": m["id"],
                    "last": last_of(f"dm:{lo}:{hi}"), "unread": unread.get(f"dm:{m['id']}", 0)})
    dms.sort(key=lambda t: -(t["last"]["id"] if t["last"] else 0))
    return {"threads": threads + dms, "unread": unread, "total": sum(unread.values()),
            "people": chat_people(c.conn, u["crew_id"]), "seq": CHAT_SEQ}


@route("GET", "/api/chat/messages")
def chat_messages(c):
    u = c.user
    thread, _ = chat_thread(c, qp(c, "thread"))
    after, before, first = qpi(c, "after"), qpi(c, "before"), qpi(c, "first")
    wait, seq0 = min(qpi(c, "wait"), 25), qpi(c, "seq", -1)
    rows, more = chat_fetch(c.conn, thread, after, before)
    if wait and after is not None and not rows:
        c.conn.commit()  # never hold a write lock while parked
        end = time.time() + wait
        with CHAT_COND:
            while CHAT_SEQ == seq0 and time.time() < end:
                CHAT_COND.wait(end - time.time())
        rows, more = chat_fetch(c.conn, thread, after, before)
    if qp(c, "mark") == "1" and rows and not before:
        chat_mark(c.conn, u["id"], thread, rows[-1]["id"])
    deleted = []
    if first:
        deleted = [r["id"] for r in q(c.conn, "SELECT id FROM messages WHERE thread=? AND deleted=1 AND id>=? ORDER BY id DESC LIMIT 100", (thread, first))]
    unread = chat_unread(c.conn, u)
    return {"messages": [chat_msg(m) for m in rows], "more": more, "deleted": deleted, "seq": CHAT_SEQ,
            "people": chat_people(c.conn, u["crew_id"]), "unread": unread, "total": sum(unread.values())}


@route("POST", "/api/chat/send")
def chat_send(c):
    u = c.user
    thread, other = chat_thread(c, str(c.body.get("thread", "")))
    text = str(c.body.get("text", ""))[:CHAT_MAX * 3].replace("\r\n", "\n")
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", text).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    if not text:
        raise ApiError("Say something first")
    if len(text) > CHAT_MAX:
        raise ApiError(f"Max {CHAT_MAX} characters")
    recent = [t for t in CHAT_RATE.get(u["id"], []) if time.time() - t < 20]
    if len(recent) >= 10:
        raise ApiError("Slow down 😅", 429)
    CHAT_RATE[u["id"]] = recent + [time.time()]
    ts = now().isoformat(timespec="seconds")
    cur = c.conn.execute("INSERT INTO messages(thread,sender,recip,ts,body) VALUES(?,?,?,?,?)",
                         (thread, u["id"], other["id"] if other else None, ts, text))
    chat_mark(c.conn, u["id"], thread, cur.lastrowid)
    c.conn.commit()  # visible to waiting pollers before we wake them
    chat_bump()
    return {"message": {"id": cur.lastrowid, "uid": u["id"], "ts": ts, "text": text}}


@route("POST", "/api/chat/delete")
def chat_delete(c):
    m = q1(c.conn, "SELECT id, sender FROM messages WHERE id=?", (need(c, "id", int),))
    if not m or m["sender"] != c.user["id"]:
        raise ApiError("You can only delete your own messages", 403)
    c.conn.execute("UPDATE messages SET deleted=1, body='' WHERE id=?", (m["id"],))
    c.conn.commit()
    chat_bump()
    return {"ok": True}


@route("POST", "/api/chat/read")
def chat_read(c):
    thread, _ = chat_thread(c, str(c.body.get("thread", "")))
    chat_mark(c.conn, c.user["id"], thread, need(c, "id", int))
    return {"ok": True}


@route("GET", "/api/chat/unread")
def chat_unread_route(c):
    un = chat_unread(c.conn, c.user)
    latest = None
    if un:
        r = q1(c.conn, """SELECT m.id, m.body, us.display FROM messages m JOIN users us ON us.id=m.sender
            LEFT JOIN chat_reads r ON r.user_id=? AND r.thread=m.thread
            WHERE m.deleted=0 AND m.sender<>? AND m.id>COALESCE(r.last_id,0) AND (m.thread=? OR m.recip=?)
            ORDER BY m.id DESC LIMIT 1""", (c.user["id"], c.user["id"], f"crew:{c.user['crew_id']}", c.user["id"]))
        if r:
            latest = {"id": r["id"], "from": r["display"], "text": r["body"][:80]}
    return {"unread": un, "total": sum(un.values()), "latest": latest}


# ----------------------------------------------------------------------------- admin (owner dashboard)
STARTED = time.time()


def need_admin(c):
    if not is_admin(c.user):
        raise ApiError("Admins only", 403)


def git_rev():
    try:
        r = subprocess.run(["git", "-C", ROOT, "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=2)
        return r.stdout.strip() or "n/a"
    except Exception:
        return "n/a"


def rss_mb():
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return round(int(line.split()[1]) / 1024, 1)
    except Exception:
        pass
    return None


@route("GET", "/api/admin/stats")
def admin_stats(c):
    need_admin(c)
    conn, d0 = c.conn, iso(today())
    one = lambda sql, a=(): conn.execute(sql, a).fetchone()[0]
    users = q(conn, """SELECT u.id, u.username, u.display, u.crew_id,
        COALESCE((SELECT SUM(amount) FROM xp WHERE user_id=u.id),0) xp,
        (SELECT MAX(day) FROM focus WHERE user_id=u.id) last_focus,
        (SELECT COUNT(*) FROM messages WHERE sender=u.id) msgs
        FROM users u ORDER BY xp DESC""")
    for u in users:
        u["admin"] = u["username"].lower() in ADMINS
    du = shutil.disk_usage(DATA_DIR)
    db_bytes = sum(os.path.getsize(p) for p in (DB_PATH, DB_PATH + "-wal") if os.path.exists(p))
    return {
        "app": {"users": len(users), "crews": one("SELECT COUNT(*) FROM crews"),
                "active_today": one("SELECT COUNT(DISTINCT user_id) FROM (SELECT user_id FROM focus WHERE day=? UNION SELECT user_id FROM xp WHERE day=?)", (d0, d0)),
                "active_7d": one("SELECT COUNT(DISTINCT user_id) FROM focus WHERE day>=?", (iso(today() - D(6)),)),
                "focus_min_today": one("SELECT COALESCE(SUM(minutes),0) FROM focus WHERE day=?", (d0,)),
                "focus_min_week": one("SELECT COALESCE(SUM(minutes),0) FROM focus WHERE day>=?", (iso(wstart(today())),)),
                "messages_total": one("SELECT COUNT(*) FROM messages WHERE deleted=0"),
                "messages_today": one("SELECT COUNT(*) FROM messages WHERE deleted=0 AND substr(ts,1,10)=?", (now().date().isoformat(),)),
                "live_timers": one("SELECT COUNT(*) FROM timers"), "sessions": one("SELECT COUNT(*) FROM sessions")},
        "server": {"uptime_s": int(time.time() - STARTED), "rss_mb": rss_mb(), "threads": threading.active_count(),
                   "load": [round(x, 2) for x in os.getloadavg()], "db_kb": round(db_bytes / 1024, 1),
                   "disk_free_gb": round(du.free / 1e9, 1), "disk_total_gb": round(du.total / 1e9, 1),
                   "python": sys.version.split()[0], "version": git_rev(), "time": now().isoformat(timespec="seconds"),
                   "tz": time.strftime("%Z %z")},
        "users": users,
    }


@route("POST", "/api/admin/resetpin")
def admin_resetpin(c):
    need_admin(c)
    u = q1(c.conn, "SELECT id, username FROM users WHERE username=? COLLATE NOCASE", (need(c, "username", maxlen=20),))
    if not u:
        raise ApiError("No such user", 404)
    pin = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(8))
    salt = secrets.token_hex(16)
    c.conn.execute("UPDATE users SET pw_hash=?, salt=? WHERE id=?", (hash_pw(pin, salt), salt, u["id"]))
    c.conn.execute("DELETE FROM sessions WHERE user_id=?", (u["id"],))
    FAILS.clear()
    return {"username": u["username"], "pin": pin}


@route("GET", "/api/admin/backup")
def admin_backup(c):
    need_admin(c)
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        dst = sqlite3.connect(tmp)
        c.conn.backup(dst)
        dst.close()
        with open(tmp, "rb") as f:
            data = f.read()
    finally:
        os.unlink(tmp)
    return (data, f"outgrow-{now().strftime('%Y%m%d-%H%M')}.db", "application/octet-stream")


# ----------------------------------------------------------------------------- http
class Handler(BaseHTTPRequestHandler):
    server_version = "Outgrow/3"
    timeout = 30

    def log_message(self, *a):
        pass

    def token(self):
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "og":
                return v
        return None

    def send_json(self, code, obj, cookie=None):
        data = json.dumps(obj, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        if cookie is not None:
            if cookie == "":
                self.send_header("Set-Cookie", "og=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax")
            else:
                secure = "; Secure" if self.headers.get("X-Forwarded-Proto", "").lower() == "https" else ""
                self.send_header("Set-Cookie", f"og={cookie}; Path=/; Max-Age=7776000; HttpOnly; SameSite=Lax{secure}")
        self.end_headers()
        self.wfile.write(data)

    def send_file(self, data, name, ctype):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Disposition", f'attachment; filename="{name}"')
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def static(self, path):
        if path in ("/", ""):
            path = "/index.html"
        fp = os.path.normpath(os.path.join(STATIC, path.lstrip("/")))
        if not fp.startswith(STATIC) or not os.path.isfile(fp):
            fp = os.path.join(STATIC, "index.html")
        ctype = mimetypes.guess_type(fp)[0] or "application/octet-stream"
        with open(fp, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith("text") or "javascript" in ctype else ""))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def dispatch(self, method):
        p = urlparse(self.path)
        if method == "GET" and not p.path.startswith("/api/"):
            return self.static(p.path)
        r = ROUTES.get((method, p.path))
        if not r:
            return self.send_json(404, {"error": "not found"})
        fn, auth = r
        body = {}
        if method == "POST":
            n = int(self.headers.get("Content-Length") or 0)
            if n > 100_000:
                return self.send_json(413, {"error": "too big"})
            raw = self.rfile.read(n) if n else b""
            try:
                body = json.loads(raw) if raw else {}
            except Exception:
                return self.send_json(400, {"error": "bad json"})
        conn = connect()
        try:
            user = None
            tok = self.token()
            if tok:
                user = q1(conn, "SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=?", (tok,))
            if auth and not user:
                return self.send_json(401, {"error": "login"})
            c = Ctx(conn, user, body, parse_qs(p.query), self)
            before = level_of(total_xp(conn, user["id"])) if user and method == "POST" else None
            res = fn(c)
            if before is not None and c.user:
                after = level_of(total_xp(conn, c.user["id"]))
                if after > before:
                    li = level_info(total_xp(conn, c.user["id"]))
                    c.ev.append({"t": "levelup", "level": li["level"], "rank": li["rank"]})
                    feed(c, "levelup", f"reached level {li['level']} · {li['rank']} ⬆️")
            conn.commit()
            if isinstance(res, tuple):
                return self.send_file(*res)
            if isinstance(res, dict):
                res["events"] = res.get("events", []) + c.ev
            self.send_json(200, res, cookie=c.cookie)
        except ApiError as e:
            conn.rollback()
            self.send_json(e.code, {"error": e.msg})
        except (BrokenPipeError, ConnectionResetError):
            conn.rollback()  # client went away mid-response (normal for long-polls)
        except Exception:
            conn.rollback()
            traceback.print_exc()
            self.send_json(500, {"error": "server error"})
        finally:
            conn.close()


# ----------------------------------------------------------------------------- bootstrap
def import_legacy(conn):
    """Season 0: the original Growth Tracker's Google-Form CSV."""
    if conn.execute("SELECT COUNT(*) FROM legacy").fetchone()[0] or not os.path.isfile(LEGACY_CSV):
        return
    n = 0
    with open(LEGACY_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                name = (row.get("Username") or "").strip()
                vals = [v for k, v in row.items() if k not in ("Timestamp", "Username")]
                done = sum(1 for v in vals if str(v).strip().lower() == "done")
                conn.execute("INSERT INTO legacy(username,day,done,total) VALUES(?,?,?,?)", (name, row.get("Timestamp", ""), done, len(vals)))
                n += 1
            except Exception:
                pass
    conn.commit()
    print(f"  imported {n} rows of Season 0 history")


def bootstrap():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = connect()
    conn.executescript(SCHEMA)
    import_legacy(conn)
    if not conn.execute("SELECT COUNT(*) FROM crews").fetchone()[0]:
        code = make_code()
        conn.execute("INSERT INTO crews(name,code,created_at) VALUES(?,?,?)", ("NervHQ", code, now().isoformat(timespec="seconds")))
        conn.commit()
        with open(os.path.join(DATA_DIR, "INVITE_CODE.txt"), "w") as f:
            f.write(code + "\n")
    code = conn.execute("SELECT name, code FROM crews ORDER BY id LIMIT 1").fetchone()
    conn.close()
    return code


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64

    def handle_error(self, request, client_address):
        if isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError, TimeoutError)):
            return
        super().handle_error(request, client_address)


if __name__ == "__main__":
    crew = bootstrap()
    print(f"\n  OUTGROW  ·  http://{BIND}:{PORT}")
    print(f"  Crew: {crew['name']}   Invite code: {crew['code']}")
    print(f"  Server time: {now().isoformat(timespec='seconds')} ({time.strftime('%Z %z')})   admins: {', '.join(sorted(ADMINS)) or 'none'}\n", flush=True)
    Server((BIND, PORT), Handler).serve_forever()
