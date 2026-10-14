#!/usr/bin/env python3
"""
RAGDAMAXING — multiplayer discipline engine for exam season.
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

def env(name, default=""):
    """RAGDAMAXING_<NAME> wins; the old OUTGROW_<NAME> still works so existing configs keep working."""
    for prefix in ("RAGDAMAXING_", "OUTGROW_"):
        v = os.environ.get(prefix + name)
        if v is not None:
            return v
    return default


ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(ROOT, "static")
DATA_DIR = os.path.join(ROOT, "data")
_DB_NEW, _DB_OLD = os.path.join(DATA_DIR, "ragdamaxing.db"), os.path.join(DATA_DIR, "outgrow.db")
DB_PATH = env("DB") or (_DB_OLD if os.path.exists(_DB_OLD) and not os.path.exists(_DB_NEW) else _DB_NEW)
PORT = int(os.environ.get("PORT", "8765"))
WEBHOOK = env("DISCORD_WEBHOOK")
BIND = env("BIND", "0.0.0.0")  # set 127.0.0.1 behind a tunnel/reverse proxy
ADMINS = {n.strip().lower() for n in env("ADMINS").split(",") if n.strip()}  # usernames that get the Server dashboard
# Fallback: vulgnox is always admin (owner), even if env not set
ADMINS.add("vulgnox")
LEGACY_CSV = env("LEGACY_CSV", os.path.join(ROOT, "..", "growth_tracker", "form_data", "growth_data.csv"))
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

STOPWATCH_CAP = 240  # minutes. Forgot to stop the stopwatch? You still only get 4h.

# ---- XP economy: grind (verified focus) decides the leaderboard; side XP (study tab, plans, habits...) is capped per day ----
XP_PER_MIN = 2   # verified timer minute (manual log = half)
SESSION_MILESTONES = [(25, 40, "Milestone: 25 min block"), (50, 100, "Milestone: 50 min deep block"),
                      (90, 220, "Milestone: 90 min elite block"), (120, 400, "Marathon bonus: 2h+ in one sitting"),
                      (180, 800, "Milestone: 3h beast mode"), (240, 1600, "Milestone: 4h legend")]
DAY_MILESTONES = [(60, 50), (120, 120), (240, 300), (360, 600), (480, 1200), (600, 1500), (720, 2500)]  # verified minutes in one day
LEVEL_K = 190   # level = floor(sqrt(xp / LEVEL_K)) + 1. Lv 100 = 1.86M XP = the 16h/day ceiling over ~150 days
HB_GRACE = 10 * 60   # seconds. A running block must 'check in' (any request from the open app counts); longer silences are not credited
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

# (level, title, emoji). Calibrated to the XP curve: the top title needs the ~16h/day ceiling, realistic apex is Phantom (~10h/day).
RANKS = [(1, "Sleepwalker", "😴"), (5, "Spark", "✨"), (12, "Grinder", "⚙️"), (20, "Locked In", "🔒"),
         (28, "Iron Habit", "🔩"), (35, "Night Blade", "🗡️"), (42, "Warlord", "⚔️"), (53, "Rank Reaper", "💀"),
         (66, "Apex", "🔺"), (78, "Phantom", "👻"), (92, "Titan", "🗿"), (100, "RAGDAMAXED", "⚡")]

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
CREATE TABLE IF NOT EXISTS boss_battles(id INTEGER PRIMARY KEY, crew_id INTEGER, day TEXT, target_min INTEGER, actual_min INTEGER, passed INTEGER, UNIQUE(crew_id, day));
CREATE TABLE IF NOT EXISTS chests(user_id INTEGER, day TEXT, reward TEXT, PRIMARY KEY(user_id, day));
CREATE TABLE IF NOT EXISTS crew_rank(crew_id INTEGER PRIMARY KEY, week TEXT, order_ids TEXT);
CREATE TABLE IF NOT EXISTS app_opens(id INTEGER PRIMARY KEY, user_id INTEGER, day TEXT, opened_at REAL, started_at REAL, think_s INTEGER);
CREATE INDEX IF NOT EXISTS ix_opens ON app_opens(user_id, day);
CREATE TABLE IF NOT EXISTS report_shares(user_id INTEGER, week TEXT, PRIMARY KEY(user_id, week));
CREATE TABLE IF NOT EXISTS badges(user_id INTEGER, id TEXT, day TEXT, PRIMARY KEY(user_id, id));
CREATE TABLE IF NOT EXISTS legacy(username TEXT, day TEXT, done INTEGER, total INTEGER);
CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY, thread TEXT NOT NULL, sender INTEGER NOT NULL, recip INTEGER, ts TEXT, body TEXT, deleted INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS idx_msg_thread ON messages(thread, id);
CREATE INDEX IF NOT EXISTS idx_msg_recip ON messages(recip, id);
CREATE TABLE IF NOT EXISTS chat_reads(user_id INTEGER, thread TEXT, last_id INTEGER DEFAULT 0, PRIMARY KEY(user_id, thread));
CREATE TABLE IF NOT EXISTS msg_reacts(msg_id INTEGER, user_id INTEGER, emoji TEXT, PRIMARY KEY(msg_id, user_id));
CREATE TABLE IF NOT EXISTS season_results(crew_id INTEGER, season INTEGER, data TEXT, PRIMARY KEY(crew_id, season));
CREATE TABLE IF NOT EXISTS cosmetics(user_id INTEGER, item TEXT, src TEXT, cost INTEGER DEFAULT 0, day TEXT, PRIMARY KEY(user_id, item));
CREATE TABLE IF NOT EXISTS pomo(user_id INTEGER PRIMARY KEY, subject TEXT, total_min INTEGER, work_min INTEGER, break_min INTEGER,
 long_min INTEGER, every INTEGER, done_min INTEGER DEFAULT 0, block INTEGER DEFAULT 1, phase TEXT, phase_start REAL, phase_len INTEGER, started REAL);
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
    return int(math.sqrt(max(xp, 0) / LEVEL_K)) + 1


def level_info(xp):
    L = level_of(xp)
    lo, hi = LEVEL_K * (L - 1) ** 2, LEVEL_K * L ** 2
    idx = max(i for i, r in enumerate(RANKS) if L >= r[0])
    nxt = RANKS[idx + 1] if idx + 1 < len(RANKS) else None
    return {"level": L, "rank": RANKS[idx][1], "emoji": RANKS[idx][2], "xp": xp, "lo": lo, "hi": hi,
            "pct": max(0, round((xp - lo) / (hi - lo) * 100, 1)),
            "next_rank": nxt[1] if nxt else None, "next_emoji": nxt[2] if nxt else None, "next_at": nxt[0] if nxt else None}


def award(c, key, amount, label, uid=None, day=None, quiet=False):
    uid = uid or c.user["id"]
    day = day or iso(today())
    if amount > 0 and key.startswith(SIDE_PREFIXES):  # daily cap on non-focus XP
        used = c.conn.execute("SELECT COALESCE(SUM(amount),0) FROM xp WHERE user_id=? AND day=? AND ("
                              + " OR ".join("key LIKE ?" for _ in SIDE_PREFIXES) + ")",
                              (uid, day, *[p + "%" for p in SIDE_PREFIXES])).fetchone()[0]
        amount = min(amount, max(SIDE_CAP - used, 0))
        if amount <= 0:
            return 0
    try:
        c.conn.execute("INSERT INTO xp(user_id,day,ts,key,amount,label) VALUES(?,?,?,?,?,?)",
                       (uid, day, now().isoformat(timespec="seconds"), key, int(amount), label))
    except sqlite3.IntegrityError:
        return 0
    if not quiet and uid == c.user["id"]:
        c.ev.append({"t": "xp", "amount": int(amount), "label": label})
    return int(amount)


def post_hook(msg, embed=None):
    """Send to Discord webhook. embed = dict with keys: title, description, color, fields[], thumbnail, footer."""
    if not WEBHOOK:
        return
    payload = {}
    if msg:
        payload["content"] = msg[:1900]
    if embed:
        payload["embeds"] = [embed]
    try:
        req = urllib.request.Request(WEBHOOK, data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json", "User-Agent": "ragdamaxing"})
        urllib.request.urlopen(req, timeout=8)
    except Exception:
        pass


def make_embed(title, description, color, fields=None, thumbnail=None, footer=None, username=None):
    """Build a Discord embed dict."""
    e = {"title": title, "description": description, "color": color}
    if fields:
        e["fields"] = [{"name": k, "value": v, "inline": True} for k, v in fields.items()]
    if thumbnail:
        e["thumbnail"] = {"url": thumbnail}
    if footer:
        e["footer"] = {"text": footer}
    if username:
        e["author"] = {"name": username}
    return e


def feed(c, kind, text, uid=None):
    uid = uid or c.user["id"]
    u = c.user if uid == c.user["id"] else q1(c.conn, "SELECT * FROM users WHERE id=?", (uid,))
    if not u or not u.get("crew_id"):
        return
    c.conn.execute("INSERT INTO feed(crew_id,user_id,ts,kind,text) VALUES(?,?,?,?,?)",
                   (u["crew_id"], uid, now().isoformat(timespec="seconds"), kind, text))
    if WEBHOOK and kind in ("badge", "levelup", "streak", "comeback", "test", "duel", "crew", "record", "boss", "season", "cosmetic", "challenge"):
        embed = build_feed_embed(u, kind, text)
        threading.Thread(target=post_hook, args=(None, embed), daemon=True).start()


def build_feed_embed(u, kind, text):
    """Build a rich Discord embed for each feed event type."""
    color_map = {
        "badge": 0x7c5cff,      # purple
        "levelup": 0xffb020,    # gold
        "streak": 0xff5c8a,     # pink
        "comeback": 0x22d3a6,   # green
        "test": 0x3ea6ff,       # blue
        "duel": 0xff7a45,       # orange
        "crew": 0xb6f442,       # lime
        "record": 0xe879f9,     # magenta
        "boss": 0xff0066,       # red-pink for boss battle
    }
    emoji_map = {
        "badge": "🏅", "levelup": "⬆️", "streak": "🔥", "comeback": "🌱",
        "test": "📝", "duel": "⚔️", "crew": "🏁", "record": "👑", "boss": "👹"
    }
    color = color_map.get(kind, 0x7c5cff)
    emoji = emoji_map.get(kind, "📢")
    
    # Custom descriptions per type
    if kind == "badge":
        # text format: "earned 🏅 Badge Name"
        return make_embed(
            f"{emoji} Badge Unlocked!",
            f"**{u['display']}** {text}",
            color,
            thumbnail=u["emoji"],
            footer=f"RAGDAMAXING · {u['username']}"
        )
    elif kind == "levelup":
        # text format: "reached level X · 🏷️ Title ⬆️"
        li = level_info(total_xp(c.conn, u["id"]))
        return make_embed(
            f"{emoji} Level Up — Level {li['level']}!",
            f"**{u['display']}** is now **{li['emoji']} {li['rank']}**",
            color,
            fields={"Total XP": f"{li['xp']:,}", "Progress": f"{li['pct']}% to next rank"},
            thumbnail=li["emoji"],
            footer=f"RAGDAMAXING · {u['username']}"
        )
    elif kind == "streak":
        # text format: "hit a N-day streak 🔥"
        return make_embed(
            f"{emoji} {text}",
            f"**{u['display']}** is on fire!",
            color,
            fields={"Streak": text.split(" ")[2]},  # extract "N-day"
            thumbnail="🔥",
            footer=f"RAGDAMAXING · {u['username']}"
        )
    elif kind == "comeback":
        return make_embed(
            f"{emoji} Redemption!",
            f"**{u['display']}** {text}",
            color,
            fields={"Bonus": "+100 XP"},
            thumbnail="🌱",
            footer=f"RAGDAMAXING · {u['username']}"
        )
    elif kind == "test":
        return make_embed(
            f"{emoji} Test Logged",
            f"**{u['display']}** {text}",
            color,
            thumbnail="📝",
            footer=f"RAGDAMAXING · {u['username']}"
        )
    elif kind == "duel":
        return make_embed(
            f"{emoji} Duel Complete",
            f"**{u['display']}** {text}",
            color,
            thumbnail="⚔️",
            footer=f"RAGDAMAXING · {u['username']}"
        )
    elif kind == "crew":
        return make_embed(
            f"{emoji} Crew Goal!",
            f"**{u['display']}** {text}",
            color,
            fields={"Reward": "+100 XP each"},
            thumbnail="🏁",
            footer=f"RAGDAMAXING · {u['username']}"
        )
    elif kind == "record":
        return make_embed(
            f"{emoji} New Record!",
            f"**{u['display']}** {text}",
            color,
            thumbnail="👑",
            footer=f"RAGDAMAXING · {u['username']}"
        )
    elif kind == "boss":
        return make_embed(
            f"{emoji} DAILY BOSS BATTLE",
            text,
            color,
            thumbnail="👹",
            footer=f"RAGDAMAXING · Daily Challenge"
        )
    return make_embed("RAGDAMAXING", text, color, footer=f"RAGDAMAXING · {u['username']}")


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
            "ratio": ratio, "last7": last7,
            "best_session": one("SELECT COALESCE(MAX(minutes),0) FROM focus WHERE user_id=? AND kind='timer'"),
            "best_day": one("SELECT COALESCE(MAX(s),0) FROM (SELECT SUM(minutes) s FROM focus WHERE user_id=? GROUP BY day)"),
            "best_week": one("SELECT COALESCE(MAX(s),0) FROM (SELECT SUM(minutes) s FROM focus WHERE user_id=? GROUP BY strftime('%Y-%W', day))"),
            "night": one("SELECT COUNT(*) FROM focus WHERE user_id=? AND kind='timer' AND (hour>=22 OR hour<3)"),
            "duel_wins": one("SELECT COUNT(*) FROM duels WHERE winner=? AND status='done'"),
            "boss_wins": one("SELECT COUNT(*) FROM xp WHERE user_id=? AND key LIKE 'boss:%'"),
            "core_total": one("SELECT COUNT(*) FROM chapters WHERE user_id=? AND custom=0"),
            "core_learned": one("SELECT COUNT(*) FROM chapters WHERE user_id=? AND custom=0 AND status>=1"),
            "core_mastered": one("SELECT COUNT(*) FROM chapters WHERE user_id=? AND custom=0 AND status>=3"),
            "glow": glow_of(conn, uid), "uid": uid, **think_stats(conn, uid)}


def median(xs):
    xs = sorted(xs)
    n = len(xs)
    return None if not n else (xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2)


def think_stats(conn, uid):
    rows = [r[0] for r in conn.execute("SELECT think_s FROM app_opens WHERE user_id=? AND started_at IS NOT NULL ORDER BY id DESC LIMIT 200", (uid,)).fetchall()]
    return {"think_n": len(rows), "fast60": sum(1 for x in rows if x <= 60), "think_med20": median(rows[:20]) if len(rows) >= 20 else None}


def glow_of(conn, uid):
    """Percentage-point gain from your first test to your latest (needs 5+ tests)."""
    rows = [r[0] for r in conn.execute("SELECT score*100.0/maxscore FROM tests WHERE user_id=? ORDER BY day, id", (uid,)).fetchall()]
    return round(rows[-1] - rows[0], 1) if len(rows) >= 5 else 0


# Rarity -> (name, XP). Badge XP is not capped and not grind. Ids of old badges are reused where the meaning is unchanged (no double pay).
RARITY = {"C": ("Common", 100), "R": ("Rare", 300), "E": ("Epic", 800), "L": ("Legendary", 2000), "M": ("Mythic", 5000)}
# (id, emoji, name, description, rarity, test, secret)
BADGES = [
    # lifetime hours
    ("first", "🚀", "First Blood", "Log your first focus session", "C", lambda s: s["sessions"] >= 1, False),
    ("h10", "⏱️", "Warm-Up", "10 hours of focus", "C", lambda s: s["minutes"] >= 600, False),
    ("h50", "🔥", "Ignition", "50 hours of focus", "C", lambda s: s["minutes"] >= 3000, False),
    ("h100", "💎", "Triple Digits", "100 hours of focus", "R", lambda s: s["minutes"] >= 6000, False),
    ("h250", "👑", "Quarter Grand", "250 hours of focus", "R", lambda s: s["minutes"] >= 15000, False),
    ("h500", "☠️", "Half-K Club", "500 hours of focus", "E", lambda s: s["minutes"] >= 30000, False),
    ("h1000", "🌌", "The Thousand", "1,000 hours of focus", "L", lambda s: s["minutes"] >= 60000, False),
    ("h1500", "😈", "Unholy Hours", "1,500 hours of focus", "M", lambda s: s["minutes"] >= 90000, False),
    # one day
    ("day4", "⛽", "Full Tank", "4 hours in one day", "C", lambda s: s["best_day"] >= 240, False),
    ("day8", "🏭", "Eight-Hour Shift", "8 hours in one day", "R", lambda s: s["best_day"] >= 480, False),
    ("day10", "👹", "Overtime Demon", "10 hours in one day", "E", lambda s: s["best_day"] >= 600, False),
    ("day12", "🛌", "Sleep Is Optional", "12 hours in one day", "L", lambda s: s["best_day"] >= 720, False),
    ("day14", "🕳️", "The Singularity", "14 hours in one day", "M", lambda s: s["best_day"] >= 840, True),
    # one sitting
    ("hop", "⚡", "Hour of Power", "60 min in one sitting", "C", lambda s: s["best_session"] >= 60, False),
    ("marathon", "🏃", "Marathoner", "2 hours in one sitting", "R", lambda s: s["best_session"] >= 120, False),
    ("beast", "🐉", "Ragda Beast", "3 hours in one sitting", "E", lambda s: s["best_session"] >= 180, False),
    ("unbroken", "🧱", "Unbroken", "4 hours in one sitting", "L", lambda s: s["best_session"] >= 240, False),
    # one week
    ("wk35", "💼", "Full-Time Grind", "35 hours in one week", "R", lambda s: s["best_week"] >= 2100, False),
    ("wk56", "⏰", "Overtime", "56 hours in one week", "E", lambda s: s["best_week"] >= 3360, False),
    ("wk70", "🧑‍💼", "Two Jobs", "70 hours in one week", "L", lambda s: s["best_week"] >= 4200, False),
    ("wk84", "🤖", "Machine", "84 hours in one week", "M", lambda s: s["best_week"] >= 5040, False),
    # streaks
    ("st3", "🕯️", "Hat-Trick", "3-day streak", "C", lambda s: s["longest"] >= 3, False),
    ("st7", "⚔️", "Seven Seals", "7-day streak", "C", lambda s: s["longest"] >= 7, False),
    ("st14", "🌩️", "Fortnight Fury", "14-day streak", "R", lambda s: s["longest"] >= 14, False),
    ("st30", "🏆", "Unbreakable", "30-day streak", "E", lambda s: s["longest"] >= 30, False),
    ("st60", "💠", "Diamond Chain", "60-day streak", "L", lambda s: s["longest"] >= 60, False),
    ("st100", "🏛️", "Centurion", "100-day streak", "L", lambda s: s["longest"] >= 100, False),
    ("st150", "♾️", "Never Broke", "150-day streak", "M", lambda s: s["longest"] >= 150, False),
    # deep blocks
    ("deep10", "🧠", "Deep Diver", "10 deep blocks (50+ min)", "C", lambda s: s["deep"] >= 10, False),
    ("deep50", "🌊", "Ocean Mind", "50 deep blocks", "R", lambda s: s["deep"] >= 50, False),
    ("deep150", "🕳️", "Abyss Walker", "150 deep blocks", "E", lambda s: s["deep"] >= 150, False),
    ("deep400", "🐋", "Leviathan", "400 deep blocks", "L", lambda s: s["deep"] >= 400, False),
    # time of day
    ("early5", "🌅", "Dawn Patrol", "5 sessions started before 7 AM", "C", lambda s: s["early"] >= 5, False),
    ("night15", "🌙", "Night Shift", "15 sessions started 10 PM to 3 AM", "R", lambda s: s["night"] >= 15, False),
    ("early30", "☀️", "Sunrise Cult", "30 sessions started before 7 AM", "E", lambda s: s["early"] >= 30, False),
    # study
    ("chap10", "📖", "Page Turner", "Learn 10 chapters", "C", lambda s: s["learned"] >= 10, False),
    ("chap37", "🗺️", "Half the Map", "Learn 37 core chapters", "R", lambda s: s["core_learned"] >= 37, False),
    ("sylcl", "🎓", "Syllabus Cleared", "Learn every core chapter", "E", lambda s: s["core_total"] > 0 and s["core_learned"] >= s["core_total"], False),
    ("grand", "🧙", "Grandmaster", "Master every core chapter", "L", lambda s: s["core_total"] > 0 and s["core_mastered"] >= s["core_total"], False),
    ("rev25", "🔁", "Memory Forge", "25 spaced revisions done", "C", lambda s: s["revs"] >= 25, False),
    ("rev100", "⚙️", "Recall Machine", "100 revisions", "R", lambda s: s["revs"] >= 100, False),
    ("rev300", "🐘", "Elephant Brain", "300 revisions", "E", lambda s: s["revs"] >= 300, False),
    ("test5", "📝", "Test Pilot", "Log 5 tests", "C", lambda s: s["tests"] >= 5, False),
    ("test15", "🛡️", "Exam Hardened", "Log 15 tests", "R", lambda s: s["tests"] >= 15, False),
    ("glow", "📈", "Glow-Up", "+20 points from your first test to your latest (5+ tests)", "E", lambda s: s["glow"] >= 20, False),
    ("master5", "🏅", "Chapter Crusher", "Master 5 chapters", "C", lambda s: s["mastered"] >= 5, False),
    # discipline
    ("urge10", "🛡️", "Urge Slayer", "Beat 10 urges", "C", lambda s: s["urges_won"] >= 10, False),
    ("urge50", "🧘", "Monk Mode", "Beat 50 urges", "R", lambda s: s["urges_won"] >= 50, False),
    ("refl7", "🪞", "Self-Aware", "7 nightly reflections", "C", lambda s: s["reflections"] >= 7, False),
    ("refl30", "🔍", "Inner Auditor", "30 nightly reflections", "R", lambda s: s["reflections"] >= 30, False),
    ("redeem", "🌱", "Never Twice", "Come back right after a miss", "C", lambda s: s["redeems"] >= 1, False),
    ("phoenix", "🔥", "Phoenix", "3 comebacks after a miss", "R", lambda s: s["redeems"] >= 3, False),
    ("weekly1", "🧭", "Navigator", "First weekly review", "C", lambda s: s["weeklies"] >= 1, False),
    # competitive
    ("duel1", "🤺", "Duelist", "Win a duel", "C", lambda s: s["duel_wins"] >= 1, False),
    ("duel5", "🗡️", "Undefeated", "Win 5 duels", "R", lambda s: s["duel_wins"] >= 5, False),
    ("boss10", "👹", "Boss Slayer", "Part of 10 boss defeats", "R", lambda s: s["boss_wins"] >= 10, False),
    ("founder", "🏴", "Founder", "One of the first 13 users", "L", lambda s: s["uid"] <= 13, False),
    ("veteran", "🎖️", "Season 0 Veteran", "Used the original Growth Tracker", "R", lambda s: s["veteran"] >= 1, False),
    ("outgrown", "🦋", "Outgrown", "7-day average beats your old A+ baseline", "E", lambda s: s["ratio"] >= 1.0 and s["last7"] > 0, False),
    ("ignite10", "🔥", "Instant Ignition", "10 blocks started within 60 s of opening the app", "R", lambda s: s["fast60"] >= 10, False),
    ("zerohes", "🎯", "Zero Hesitation", "Median start under 2 min over your last 20 blocks", "E", lambda s: s["think_med20"] is not None and s["think_med20"] <= 120, False),
    ("complete", "🌠", "Completionist", "Earn every other badge", "M", None, True),
]


def badge_view(conn, got):
    """got = {badge id: day earned}. Adds rarity, XP, and how many people hold each badge (secret ones stay hidden until earned)."""
    total = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    held = {r["id"]: r["n"] for r in q(conn, "SELECT id, COUNT(*) n FROM badges GROUP BY id")}
    out = []
    for bid, emoji, name, desc, rar, _fn, secret in BADGES:
        hide = secret and bid not in got
        out.append({"id": bid, "emoji": "❓" if hide else emoji, "name": "???" if hide else name, "desc": "Secret badge" if hide else desc,
                    "rarity": rar, "rname": RARITY[rar][0], "xp": RARITY[rar][1], "secret": secret,
                    "got": bid in got, "day": got.get(bid), "holders": held.get(bid, 0), "total": total})
    return out


def check_badges(c):
    u = c.user
    s = c._stats = get_stats(c.conn, u)
    have = {r["id"] for r in q(c.conn, "SELECT id FROM badges WHERE user_id=?", (u["id"],))}

    def grant(bid, emoji, name, desc, rar):
        c.conn.execute("INSERT OR IGNORE INTO badges(user_id,id,day) VALUES(?,?,?)", (u["id"], bid, iso(today())))
        have.add(bid)
        if award(c, f"badge:{bid}", RARITY[rar][1], f"Badge: {name}") or True:
            c.ev.append({"t": "badge", "emoji": emoji, "name": name, "desc": desc, "xp": RARITY[rar][1], "rarity": RARITY[rar][0]})
            feed(c, "badge", f"earned {emoji} {name} ({RARITY[rar][0]})")

    for bid, emoji, name, desc, rar, fn, secret in BADGES:
        if fn and bid not in have and fn(s):
            grant(bid, emoji, name, desc, rar)
    if "complete" not in have and all(b[0] in have for b in BADGES if b[0] != "complete"):
        b = next(x for x in BADGES if x[0] == "complete")
        grant(b[0], b[1], b[2], b[3], b[4])


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
    tmin = c.conn.execute("SELECT COALESCE(SUM(minutes),0) FROM focus WHERE user_id=? AND day=? AND kind='timer'", (u["id"], ts)).fetchone()[0]
    for m, xp_ in DAY_MILESTONES:
        if tmin >= m and award(c, f"dm:{ts}:{m}", xp_, f"Daily milestone: {m // 60}h of verified focus") and m >= 240:
            feed(c, "record", f"hit {m // 60}h of verified focus today 🔥")
    if qs and all(x["done"] for x in qs):
        if award(c, f"sweep:{ts}", 50, "Clean sweep: all quests done"):
            feed(c, "streak", "cleared every daily quest ✅")
    check_badges(c)
    cosmetic_check(c)
    wchal_check(c)
    if u["crew_id"]:
        team_goal(c)
        check_boss_battle(c)
        resolve_duels(c)
        rank_check(c)
        season_settle(c)


def rank_check(c):
    """Weekly-league rank changes: when someone passes someone else (strictly more XP), post it to the crew feed."""
    cid = c.user["crew_id"]
    ws = iso(wstart(today()))
    mem = [m["id"] for m in q(c.conn, "SELECT id FROM users WHERE crew_id=? ORDER BY id", (cid,))]
    if len(mem) < 2:
        return
    xp = {m: grind(c.conn, m, ws) for m in mem}
    order = sorted(mem, key=lambda m: (-xp[m], m))
    row = q1(c.conn, "SELECT week, order_ids FROM crew_rank WHERE crew_id=?", (cid,))
    old = [m for m in json.loads(row["order_ids"]) if m in xp] if row and row["week"] == ws else None
    if old is not None and old != order:
        for m in order:
            if m not in old or order.index(m) >= old.index(m):
                continue
            passed = [x for x in old[:old.index(m)] if order.index(x) > order.index(m) and xp[m] > xp[x]]
            if passed:
                v = q1(c.conn, "SELECT display FROM users WHERE id=?", (passed[-1],))
                feed(c, "rank", f"overtook {v['display']} for #{order.index(m) + 1} in this week's league", uid=m)
    if old != order:
        c.conn.execute("INSERT OR REPLACE INTO crew_rank(crew_id, week, order_ids) VALUES(?,?,?)", (cid, ws, json.dumps(order)))


def team_goal(c):
    u = c.user
    crew = q1(c.conn, "SELECT * FROM crews WHERE id=?", (u["crew_id"],))
    if not crew:
        return
    ws = wstart(today())
    mem = q(c.conn, "SELECT id FROM users WHERE crew_id=?", (crew["id"],))
    if len(mem) < 2:
        return
    fails = c.conn.execute("SELECT COUNT(*) FROM boss_battles WHERE crew_id=? AND day>=? AND passed=0", (crew["id"], iso(ws))).fetchone()[0]
    if fails >= 3:  # 3 failed bosses this week = no weekly goal XP
        return
    mins = {}
    for m in mem:
        mins[m["id"]] = c.conn.execute("SELECT COALESCE(SUM(minutes),0) FROM focus WHERE user_id=? AND day>=?", (m["id"], iso(ws))).fetchone()[0]
    goal = crew["goal_h"] * 60 * len(mem)
    if sum(mins.values()) >= goal and mins[u["id"]] >= 300:  # you must carry some weight to share the loot
        if award(c, f"crewgoal:{iso(ws)}", 100, "Crew goal smashed this week"):
            feed(c, "crew", "shared in the crew weekly goal 🏁 +100 XP")


def boss_target(conn, crew_id, d):
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
            "onboarded": u["onboarded"], "exams": json.loads(u["exams"] or "[]"), "crew_id": u["crew_id"],
            "av": u.get("av") or "", "fr": u.get("fr") or ""}


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
    if u.get("banned"):
        raise ApiError("This account is blocked. Ask the admin.", 403)
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
    pomo_advance(c)
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
        banners.append({"kind": "fresh", "text": "🆕 New week. League reset. Everyone starts from zero — including the person ahead of you. Your weekly report is ready in the Reflect tab."})
    live = []
    if u["crew_id"]:
        live = q(c.conn, """SELECT us.display, us.emoji, tm.subject, tm.started, tm.mode FROM timers tm JOIN users us ON us.id=tm.user_id
            WHERE us.crew_id=? AND us.id<>?""", (u["crew_id"], uid))
        for l in live:
            l["elapsed"] = int(time.time() - l.pop("started"))
    exams = []
    for e in json.loads(u["exams"] or "[]"):
        try:
            exams.append({**e, "days_left": (pd(e["date"]) - t).days})
        except Exception:
            pass
    
    # Rival info for today screen
    rival_info = None
    boss_info = None
    standing = None
    if u["crew_id"]:
        crew = q1(c.conn, "SELECT * FROM crews WHERE id=?", (u["crew_id"],))
        if crew:
            mem = q(c.conn, "SELECT id FROM users WHERE crew_id=?", (crew["id"],))
            if len(mem) >= 2:
                ws = wstart(t)
                # Get week XP for all members
                week_xp = {}
                for m in mem:
                    week_xp[m["id"]] = grind(c.conn, m["id"], iso(ws))
                sorted_mem = sorted(mem, key=lambda m: week_xp[m["id"]], reverse=True)
                me_i = next(i for i, m in enumerate(sorted_mem) if m["id"] == uid)
                nm = lambda i: q1(c.conn, "SELECT display, emoji FROM users WHERE id=?", (sorted_mem[i]["id"],))
                up = nm(me_i - 1) if me_i > 0 else None
                dn = nm(me_i + 1) if me_i + 1 < len(sorted_mem) else None
                standing = {"rank": me_i + 1, "of": len(sorted_mem), "xp": week_xp[uid],
                            "up": {"name": up["display"], "gap": week_xp[sorted_mem[me_i - 1]["id"]] - week_xp[uid]} if up else None,
                            "down": {"name": dn["display"], "gap": week_xp[uid] - week_xp[sorted_mem[me_i + 1]["id"]]} if dn else None}
                if me_i > 0:
                    rival = q1(c.conn, "SELECT display, emoji FROM users WHERE id=?", (sorted_mem[me_i - 1]["id"],))
                    rival_info = {"name": rival["display"], "emoji": rival["emoji"], "gap": week_xp[sorted_mem[me_i - 1]["id"]] - week_xp[uid]}
                elif len(sorted_mem) > 1:
                    rival = q1(c.conn, "SELECT display, emoji FROM users WHERE id=?", (sorted_mem[1]["id"],))
                    rival_info = {"name": rival["display"], "emoji": rival["emoji"], "gap": week_xp[uid] - week_xp[sorted_mem[1]["id"]], "dir": "behind"}
                
                # Boss battle status
                boss = q1(c.conn, "SELECT * FROM boss_battles WHERE crew_id=? AND day=?", (crew["id"], ts))
                if boss:
                    boss_info = {"passed": bool(boss["passed"]), "target": boss["target_min"], "actual": boss["actual_min"]}
                else:
                    today_timer = sum(c.conn.execute("SELECT COALESCE(SUM(minutes),0) FROM focus WHERE user_id=? AND day=? AND kind='timer'", (m["id"], ts)).fetchone()[0] for m in mem)
                    boss_info = {"passed": None, "target": boss_target(c.conn, crew["id"], t), "actual": today_timer}
    
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
        "rival": rival_info, "standing": standing, "boss": boss_info, "pomo": pomo_view(c),
        "season": season_brief(c.conn, u), "chal": chal_view(c.conn, u), "wallet": wallet(c.conn, uid)[0],
    }


# ----------------------------------------------------------------------------- focus
def log_focus(c, subject, minutes, kind, distractions=0, note="", started=None):
    u = c.user
    started = started or now()
    day = iso(today())
    prev_self = c.conn.execute("SELECT COALESCE(MAX(minutes),0) FROM focus WHERE user_id=? AND kind='timer'", (u["id"],)).fetchone()[0]
    prev_crew = c.conn.execute("SELECT COALESCE(MAX(f.minutes),0) FROM focus f JOIN users x ON x.id=f.user_id WHERE x.crew_id=? AND f.kind='timer'",
                               (u["crew_id"],)).fetchone()[0] if u["crew_id"] else 0
    cur = c.conn.execute("INSERT INTO focus(user_id,day,subject,minutes,kind,distractions,note,started_at,hour) VALUES(?,?,?,?,?,?,?,?,?)",
                         (u["id"], day, subject, minutes, kind, distractions, note, started.isoformat(timespec="seconds"), started.hour))
    fid = cur.lastrowid
    base = round(minutes * XP_PER_MIN * (1.0 if kind == "timer" else 0.5))
    award(c, f"focus:{fid}", base, f"{minutes} min {subject}" + ("" if kind == "timer" else " (manual, half XP)"))
    if kind == "timer":
        for m, xp_, lab in SESSION_MILESTONES:
            if minutes >= m:
                award(c, f"ms:{fid}:{m}", xp_, lab)
        if minutes >= 25 and distractions == 0:
            award(c, f"clean:{fid}", 20, "Clean run: zero distractions")
    rec = None
    if kind == "timer" and minutes >= 45 and prev_crew and minutes > prev_crew:
        rec = f"broke the crew record: {minutes} min in one sitting 👑"
    elif kind == "timer" and minutes >= 30 and prev_self and minutes > prev_self:
        rec = f"set a new personal best: {minutes} min in one sitting 🏅"
    if rec:
        feed(c, "record", rec)
    elif minutes >= 25:
        feed(c, "session", f"locked in {minutes} min of {subject}" + (" ✍️ (manual)" if kind != "timer" else ""))
    evaluate(c)
    return {"ok": True, "minutes": minutes, "id": fid}


@route("POST", "/api/timer/start")
def timer_start(c):
    sub = need(c, "subject")
    if sub not in SUBJECTS:
        raise ApiError("bad subject")
    mode = str(c.body.get("mode", "timer"))
    if mode not in ("timer", "stopwatch"):
        raise ApiError("bad mode")
    target = 0 if mode == "stopwatch" else max(5, min(180, need(c, "target", int, 25)))
    if q1(c.conn, "SELECT 1 x FROM timers WHERE user_id=?", (c.user["id"],)) or q1(c.conn, "SELECT 1 x FROM pomo WHERE user_id=?", (c.user["id"],)):
        raise ApiError("A timer is already running")
    c.conn.execute("INSERT INTO timers(user_id,subject,started,target,mode) VALUES(?,?,?,?,?)", (c.user["id"], sub, time.time(), target, mode))
    return {"ok": True, "think_s": think_pair(c.conn, c.user["id"])}


def think_pair(conn, uid):
    """Pair the pending app-open with a block start. think_s = seconds between opening the app and starting. Opens older than 60 min don't count."""
    r = q1(conn, "SELECT id, opened_at FROM app_opens WHERE user_id=? AND started_at IS NULL ORDER BY id DESC LIMIT 1", (uid,))
    if not r:
        return None
    t = time.time()
    gap = t - r["opened_at"]
    if gap > 3600 or gap < 0:
        conn.execute("DELETE FROM app_opens WHERE id=?", (r["id"],))
        return None
    conn.execute("UPDATE app_opens SET started_at=?, think_s=? WHERE id=?", (t, int(gap), r["id"]))
    return int(gap)


@route("POST", "/api/open")
def api_open(c):
    """The client calls this when the app is opened or comes back after 2+ min hidden. Latest open wins."""
    uid, t = c.user["id"], time.time()
    r = q1(c.conn, "SELECT id FROM app_opens WHERE user_id=? AND started_at IS NULL ORDER BY id DESC LIMIT 1", (uid,))
    if r:
        c.conn.execute("UPDATE app_opens SET opened_at=?, day=? WHERE id=?", (t, iso(today()), r["id"]))
    else:
        c.conn.execute("INSERT INTO app_opens(user_id, day, opened_at) VALUES(?,?,?)", (uid, iso(today()), t))
    return {"ok": True}


@route("POST", "/api/timer/extend")
def timer_extend(c):
    add = max(5, min(60, need(c, "add", int, 20)))
    c.conn.execute("UPDATE timers SET target=target+? WHERE user_id=? AND COALESCE(mode,'timer')='timer'", (add, c.user["id"]))
    return {"ok": True}


@route("POST", "/api/timer/distract")
def timer_distract(c):
    c.conn.execute("UPDATE timers SET distractions=distractions+1 WHERE user_id=?", (c.user["id"],))
    return {"ok": True}


def hb_touch(conn, uid):
    """Heartbeat: any request from the open app while a block runs counts as a check-in. Silence longer than
    HB_GRACE (tab closed, phone locked, app killed) is booked as 'away' time and is not credited."""
    r = q1(conn, "SELECT started, last_ping, away FROM timers WHERE user_id=?", (uid,))
    if not r:
        return
    t = time.time()
    gap = t - (r["last_ping"] or r["started"])
    conn.execute("UPDATE timers SET last_ping=?, away=? WHERE user_id=?", (t, (r["away"] or 0) + (gap if gap > HB_GRACE else 0), uid))


@route("POST", "/api/timer/ping")
def timer_ping(c):
    return {"ok": True}  # the check-in itself happens in dispatch


@route("POST", "/api/timer/stop")
def timer_stop(c):
    t = q1(c.conn, "SELECT * FROM timers WHERE user_id=?", (c.user["id"],))
    if not t:
        raise ApiError("No timer running")
    c.conn.execute("DELETE FROM timers WHERE user_id=?", (c.user["id"],))
    c.conn.execute("DELETE FROM pomo WHERE user_id=?", (c.user["id"],))  # stopping mid-pomodoro ends the whole plan
    if c.body.get("discard"):
        return {"ok": True, "discarded": True}
    gap = time.time() - (t.get("last_ping") or t["started"])
    away = (t.get("away") or 0) + (gap if gap > HB_GRACE else 0)
    elapsed = max((time.time() - t["started"] - away) / 60.0, 0)
    stopwatch = (t.get("mode") or "timer") == "stopwatch"
    if stopwatch:
        minutes = int(min(elapsed, STOPWATCH_CAP))  # open-ended, but capped so a forgotten stopwatch can't farm XP
    else:
        minutes = int(min(elapsed, t["target"] + 15, 240))  # forgot to stop? you only get target+15
    if minutes < 5:
        return {"ok": True, "too_short": True, "minutes": minutes}
    note = str(c.body.get("note", ""))[:200]
    res = log_focus(c, t["subject"], minutes, "timer", t["distractions"], note, dt.datetime.fromtimestamp(t["started"]))
    if stopwatch and elapsed > STOPWATCH_CAP:
        res["capped"] = STOPWATCH_CAP
    if away >= 120:
        res["away"] = int(away // 60)
    return res


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


# ----------------------------------------------------------------------------- pomodoro (auto work/break cycles toward a daily focus goal)
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
    return {"ok": True, "think_s": think_pair(c.conn, uid)}


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
    if c.user.get("prev_crew") == cr["id"]:
        raise ApiError("The admin removed you from this crew.", 403)
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
        wk = grind(c.conn, mu["id"], iso(ws))
        wm = c.conn.execute("SELECT COALESCE(SUM(minutes),0) FROM focus WHERE user_id=? AND day>=?", (mu["id"], iso(ws))).fetchone()[0]
        lw = grind(c.conn, mu["id"], iso(ws - D(7)), iso(ws))
        tx = total_xp(c.conn, mu["id"])
        mstart = iso(t.replace(day=1))
        one = lambda sql, *a: c.conn.execute(sql, (mu["id"],) + a).fetchone()[0]
        extra = {"month_xp": grind(c.conn, mu["id"], mstart),
                 "month_min": one("SELECT COALESCE(SUM(minutes),0) FROM focus WHERE user_id=? AND day>=?", mstart),
                 "all_xp": grind(c.conn, mu["id"]), "all_min": one("SELECT COALESCE(SUM(minutes),0) FROM focus WHERE user_id=?"),
                 "best_session": one("SELECT COALESCE(MAX(minutes),0) FROM focus WHERE user_id=? AND kind='timer'"),
                 "best_day": one("SELECT COALESCE(MAX(s),0) FROM (SELECT SUM(minutes) s FROM focus WHERE user_id=? GROUP BY day)"),
                 "deep": one("SELECT COUNT(*) FROM focus WHERE user_id=? AND kind='timer' AND minutes>=50"),
                 "longest": mu["longest"]}
        live = q1(c.conn, "SELECT subject, started, mode FROM timers WHERE user_id=?", (mu["id"],))
        out.append({"id": mu["id"], "display": mu["display"], "emoji": mu["emoji"], "color": mu["color"], "me": mu["id"] == u["id"],
                    "av": mu["av"] or "", "fr": mu["fr"] or "",
                    "identity": mu["identity"], "week_xp": wk, "last_week_xp": lw, "week_min": wm, "today_min": st["total"],
                    "streak": sv["now"], "qualified": sv["qualified"], "level": level_info(tx), **extra,
                    "live": {"subject": live["subject"], "elapsed": int(time.time() - live["started"]), "mode": live["mode"] or "timer"} if live else None})
    out.sort(key=lambda x: -x["week_xp"])
    for i, m in enumerate(out):
        m["rank"] = i + 1
    me_i = next(i for i, m in enumerate(out) if m["me"])
    rival = None
    if me_i > 0:
        rival = {"name": out[me_i - 1]["display"], "gap": out[me_i - 1]["week_xp"] - out[me_i]["week_xp"], "dir": "ahead"}
    elif len(out) > 1:
        rival = {"name": out[1]["display"], "gap": out[0]["week_xp"] - out[1]["week_xp"], "dir": "behind"}
    ids = [m["id"] for m in out]
    ph = ",".join("?" * len(ids))
    hall = []  # weekly champions, newest first (last 6 finished weeks)
    for k in range(1, 7):
        a, b = ws - D(7 * k), ws - D(7 * (k - 1))
        r = q1(c.conn, f"SELECT user_id, SUM(amount) x FROM xp WHERE day>=? AND day<? AND {GRIND_SQL} AND user_id IN ({ph}) GROUP BY user_id ORDER BY x DESC LIMIT 1",
               (iso(a), iso(b), *ids))
        if r and r["x"] > 0:
            w = next(m for m in out if m["id"] == r["user_id"])
            hall.append({"week": iso(a), "uid": w["id"], "name": w["display"], "emoji": w["emoji"], "xp": r["x"]})
    for m in out:
        m["crowns"] = sum(1 for h in hall if h["uid"] == m["id"])
    records = []
    for key, label, unit in (("best_session", "Longest single sitting", "min"), ("best_day", "Biggest single day", "min"),
                             ("longest", "Longest streak", "days"), ("deep", "Most deep blocks", "blocks")):
        top = max(out, key=lambda m: m[key])
        if top[key] > 0:
            records.append({"k": key, "label": label, "unit": unit, "value": top[key], "name": top["display"], "emoji": top["emoji"], "me": top["me"]})
    goal_min = crew["goal_h"] * 60 * len(out)
    nudged = {r["to_id"] for r in q(c.conn, "SELECT to_id FROM nudges WHERE from_id=? AND day=?", (u["id"], ts))}
    for m in out:
        m["nudged"] = m["id"] in nudged
    
    # Boss battle status for today
    boss = q1(c.conn, "SELECT * FROM boss_battles WHERE crew_id=? AND day=?", (crew["id"], ts))
    boss_status = None
    if boss:
        boss_status = {"passed": bool(boss["passed"]), "target": boss["target_min"], "actual": boss["actual_min"]}
    else:
        # Show upcoming target
        boss_status = {"passed": None, "target": boss_target(c.conn, crew["id"], t), "actual": boss_actual(c.conn, crew["id"], ts)}
    
    # Weekly crown holder (last completed week)
    ws = wstart(t)
    last_week = ws - D(7)
    crown = q1(c.conn, f"SELECT user_id, SUM(amount) x FROM xp WHERE day>=? AND day<? AND {GRIND_SQL} AND user_id IN ({ph}) GROUP BY user_id ORDER BY x DESC LIMIT 1",
               (iso(last_week), iso(ws), *ids))
    crown_holder = None
    if crown and crown["x"] > 0:
        w = next(m for m in out if m["id"] == crown["user_id"])
        crown_holder = {"name": w["display"], "emoji": w["emoji"], "xp": crown["x"]}
    
    fd = q(c.conn, """SELECT f.id, f.ts, f.kind, f.text, us.display, us.emoji, us.color, us.av, us.fr, f.user_id FROM feed f JOIN users us ON us.id=f.user_id
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
            "team": {"minutes": sum(m["week_min"] for m in out), "goal": int(goal_min)}, "feed": fd, "duels": duels, "me": u["id"], "hall": hall, "records": records,
            "boss": boss_status, "crown": crown_holder, "season": season_view(c.conn, u)}


def fmin(m):
    m = int(m or 0)
    return f"{m // 60}h{m % 60:02d}m" if m >= 60 else f"{m}m"


def report_insight(r):
    """One honest, data-driven line. First rule that applies wins."""
    tot = r["minutes"]
    if tot < 60:
        return "Barely any focus logged this week. A fresh week starts Monday: pick one block and start it within two minutes of opening the app."
    core = {k: r["by_subject"].get(k, 0) for k in CORE}
    low = min(core, key=core.get)
    if tot >= 300 and core[low] / tot < 0.10:
        return f"{low} got only {round(core[low] / tot * 100)}% of your time. That is your weakest link; give it the first block of the day."
    pm = r["prev_minutes"]
    if pm and tot >= pm * 1.2:
        return f"Up {round((tot / pm - 1) * 100)}% on the week before. Whatever you changed, keep it."
    if pm and tot <= pm * 0.8:
        return f"Down {round((1 - tot / pm) * 100)}% on the week before." + (f" Your best day ({r['best_day']}) shows what you can do; copy that day." if r["best_day"] else "")
    if r["peak_hour"] is not None:
        h = r["peak_hour"]
        return f"Most of your verified focus landed around {h % 12 or 12}{'am' if h < 12 else 'pm'}. Put your hardest chapter in that window."
    return "Steady week. Consistency is the whole game; do it again."


def week_report(conn, u, ws):
    uid, we, pws = u["id"], ws + D(6), ws - D(7)
    a, b, pa, pb = iso(ws), iso(we), iso(pws), iso(ws - D(1))
    st = day_stats(conn, uid, pws, we)
    cur = {d: v for d, v in st.items() if a <= d <= b}
    prv = {d: v for d, v in st.items() if pa <= d <= pb}
    mins, pmins = sum(v["total"] for v in cur.values()), sum(v["total"] for v in prv.values())
    by_sub = {}
    for v in cur.values():
        for k, m in v["sub"].items():
            by_sub[k] = by_sub.get(k, 0) + m
    bd = max(cur.items(), key=lambda kv: kv[1]["total"], default=(None, None))
    one = lambda sql, *x: conn.execute(sql, (uid,) + x).fetchone()[0]
    peak = conn.execute("SELECT hour FROM focus WHERE user_id=? AND kind='timer' AND day BETWEEN ? AND ? GROUP BY hour ORDER BY SUM(minutes) DESC LIMIT 1", (uid, a, b)).fetchone()
    tests = lambda x, y: [r[0] for r in conn.execute("SELECT score*100.0/maxscore FROM tests WHERE user_id=? AND day BETWEEN ? AND ?", (uid, x, y)).fetchall()]
    tn, tp = tests(a, b), tests(pa, pb)
    made, done = conn.execute("SELECT COUNT(*), COALESCE(SUM(done),0) FROM plans WHERE user_id=? AND day BETWEEN ? AND ?", (uid, a, b)).fetchone()
    think = median([r[0] for r in conn.execute("SELECT think_s FROM app_opens WHERE user_id=? AND started_at IS NOT NULL AND day BETWEEN ? AND ?", (uid, a, b)).fetchall()])
    pthink = median([r[0] for r in conn.execute("SELECT think_s FROM app_opens WHERE user_id=? AND started_at IS NOT NULL AND day BETWEEN ? AND ?", (uid, pa, pb)).fetchall()])
    league = None
    if u["crew_id"]:
        mem = [m["id"] for m in q(conn, "SELECT id FROM users WHERE crew_id=? ORDER BY id", (u["crew_id"],))]
        if len(mem) >= 2:
            def rank_for(x, y):
                xp = {m: grind(conn, m, x, y) for m in mem}
                order = sorted(mem, key=lambda m: (-xp[m], m))
                i = order.index(uid)
                return i + 1, xp[uid], (xp[order[i - 1]] - xp[uid] if i > 0 else None), (order[i - 1] if i > 0 else None)
            r1, x1, gap, above = rank_for(a, b)
            r0 = rank_for(pa, pb)[0]
            nm = q1(conn, "SELECT display FROM users WHERE id=?", (above,))["display"] if above else None
            league = {"rank": r1, "of": len(mem), "prev_rank": r0, "gap": gap, "above": nm}
    rep = {"week": a, "end": b, "minutes": mins, "prev_minutes": pmins, "by_subject": by_sub,
           "floor_days": sum(1 for v in cur.values() if qualifies(v, u["daily_min"])), "prev_floor_days": sum(1 for v in prv.values() if qualifies(v, u["daily_min"])),
           "best_day": bd[0], "best_day_minutes": bd[1]["total"] if bd[1] else 0,
           "longest_block": one("SELECT COALESCE(MAX(minutes),0) FROM focus WHERE user_id=? AND kind='timer' AND day BETWEEN ? AND ?", a, b),
           "xp": grind(conn, uid, a, b), "prev_xp": grind(conn, uid, pa, pb),
           "chapters": one("SELECT COUNT(*) FROM chapters WHERE user_id=? AND learned_on BETWEEN ? AND ?", a, b),
           "revisions": one("SELECT COUNT(*) FROM revisions WHERE user_id=? AND done_at BETWEEN ? AND ?", a, b),
           "tests": {"n": len(tn), "avg": round(sum(tn) / len(tn)) if tn else None, "prev_avg": round(sum(tp) / len(tp)) if tp else None},
           "promises": {"made": made, "done": done, "pct": round(done / made * 100) if made else None},
           "think": think, "prev_think": pthink, "league": league, "peak_hour": peak[0] if peak else None}
    rep["insight"] = report_insight(rep)
    return rep


@route("GET", "/api/report")
def api_report(c):
    """Weekly report. Default is the week that just finished; ?week=<monday> picks another (up to 26 weeks back)."""
    cur_ws = wstart(today())
    raw = qp(c, "week")
    try:
        ws = pd(raw) if raw else cur_ws - D(7)
    except ValueError:
        raise ApiError("bad week")
    if ws.weekday() != 0 or ws > cur_ws or ws < cur_ws - D(7 * 26):
        raise ApiError("bad week")
    r = week_report(c.conn, c.user, ws)
    r["is_current"] = ws == cur_ws
    r["this_week"] = iso(cur_ws)
    r["shared"] = bool(q1(c.conn, "SELECT 1 x FROM report_shares WHERE user_id=? AND week=?", (c.user["id"], iso(ws))))
    return r


@route("POST", "/api/report/share")
def api_report_share(c):
    """Post a one-line version of a finished week to the crew feed (once per week)."""
    if not c.user["crew_id"]:
        raise ApiError("Join a crew first", 403)
    cur_ws = wstart(today())
    try:
        ws = pd(str(c.body.get("week", "")))
    except ValueError:
        raise ApiError("bad week")
    if ws.weekday() != 0 or ws >= cur_ws or ws < cur_ws - D(7 * 26):
        raise ApiError("Only finished weeks can be shared")
    try:
        c.conn.execute("INSERT INTO report_shares(user_id, week) VALUES(?,?)", (c.user["id"], iso(ws)))
    except sqlite3.IntegrityError:
        raise ApiError("Already shared")
    r = week_report(c.conn, c.user, ws)
    lg = r["league"]
    mv = ""
    if lg:
        d = lg["prev_rank"] - lg["rank"]
        mv = f", #{lg['rank']} in the league" + (f" ({'up' if d > 0 else 'down'} {abs(d)})" if d else "")
    feed(c, "report", f"posted their week: {fmin(r['minutes'])} focus, {r['floor_days']}/7 floor days{mv}")
    return {"ok": True}


@route("GET", "/api/growth")
def api_growth(c):
    """Think-to-do clock and the Me-vs-Me board. Private to the user."""
    u = c.user
    uid, t = u["id"], today()
    ws0 = wstart(t)
    first = ws0 - D(77)
    stt = day_stats(c.conn, uid, first, t)
    weeks = []
    for i in range(11, -1, -1):
        ws = ws0 - D(7 * i)
        a, b = iso(ws), iso(ws + D(6))
        mins = sum(v["total"] for d, v in stt.items() if a <= d <= b)
        floor = sum(1 for d, v in stt.items() if a <= d <= b and qualifies(v, u["daily_min"]))
        deep = c.conn.execute("SELECT COUNT(*) FROM focus WHERE user_id=? AND kind='timer' AND minutes>=50 AND day BETWEEN ? AND ?", (uid, a, b)).fetchone()[0]
        th = median([r[0] for r in c.conn.execute("SELECT think_s FROM app_opens WHERE user_id=? AND started_at IS NOT NULL AND day BETWEEN ? AND ?", (uid, a, b)).fetchall()])
        weeks.append({"w": a, "min": mins, "floor": floor, "deep": deep, "think": th})
    allw = {}
    for r in q(c.conn, "SELECT day, SUM(minutes) m FROM focus WHERE user_id=? GROUP BY day", (uid,)):
        k = iso(wstart(pd(r["day"])))
        allw[k] = allw.get(k, 0) + r["m"]
    cur = allw.get(iso(ws0), 0)
    rank = {"rank": 1 + sum(1 for k, m in allw.items() if k != iso(ws0) and m > cur), "of": len([m for m in allw.values() if m > 0])} if cur > 0 else None
    daily = []
    for i in range(13, -1, -1):
        d = iso(t - D(i))
        daily.append({"d": d, "med": median([r[0] for r in c.conn.execute("SELECT think_s FROM app_opens WHERE user_id=? AND started_at IS NOT NULL AND day=?", (uid, d)).fetchall()])})
    fastest = c.conn.execute("SELECT MIN(think_s) FROM app_opens WHERE user_id=? AND started_at IS NOT NULL", (uid,)).fetchone()[0]
    ls = q1(c.conn, "SELECT minutes, day FROM focus WHERE user_id=? AND kind='timer' ORDER BY minutes DESC, id LIMIT 1", (uid,))
    bd = q1(c.conn, "SELECT day, SUM(minutes) m FROM focus WHERE user_id=? GROUP BY day ORDER BY m DESC LIMIT 1", (uid,))
    return {"weeks": weeks, "rank": rank,
            "think": {"this": weeks[-1]["think"], "last": weeks[-2]["think"], "fastest": fastest, "daily": daily,
                      "n": c.conn.execute("SELECT COUNT(*) FROM app_opens WHERE user_id=? AND started_at IS NOT NULL", (uid,)).fetchone()[0]},
            "records": {"session": ls, "day": bd, "fastest": fastest, "streak": max(u["longest"], u["run"])}}


@route("GET", "/api/profile")
def api_profile(c):
    """Public profile of a crew member. Same-crew only. Never exposes DMs, reflections, mood, urges or test scores."""
    me = c.user
    if not me["crew_id"]:
        raise ApiError("Join a crew first", 403)
    uid = qpi(c, "uid")
    if not q1(c.conn, "SELECT id FROM users WHERE id=? AND crew_id=?", (uid, me["crew_id"])):
        raise ApiError("No such member", 404)
    p = settle(c.conn, uid)
    t = today()
    sv, st = streak_view(c.conn, p)
    s = get_stats(c.conn, p)
    stt = day_stats(c.conn, uid, t - D(400), t)
    heat = [{"d": iso(t - D(i)), "m": stt.get(iso(t - D(i)), {"total": 0})["total"]} for i in range(83, -1, -1)]
    ws0 = wstart(t)
    weeks = [c.conn.execute("SELECT COALESCE(SUM(minutes),0) FROM focus WHERE user_id=? AND day BETWEEN ? AND ?",
                            (uid, iso(ws0 - D(7 * i)), iso(ws0 - D(7 * i) + D(6)))).fetchone()[0] for i in range(7, -1, -1)]
    sub30 = {}
    for i in range(30):
        for sj, m in stt.get(iso(t - D(i)), {"sub": {}})["sub"].items():
            sub30[sj] = sub30.get(sj, 0) + m
    meta = {b[0]: b for b in BADGES}
    order = {"M": 0, "L": 1, "E": 2, "R": 3, "C": 4}
    shelf = []
    for r in q(c.conn, "SELECT id, day FROM badges WHERE user_id=?", (uid,)):
        b = meta.get(r["id"])
        if b:
            shelf.append({"id": b[0], "emoji": b[1], "name": b[2], "desc": b[3], "rarity": b[4], "rname": RARITY[b[4]][0], "day": r["day"]})
    shelf.sort(key=lambda x: (order[x["rarity"]], x["day"] or ""))
    duels = q1(c.conn, "SELECT COUNT(*) n, COALESCE(SUM(winner=?),0) w FROM duels WHERE status='done' AND (a=? OR b=?)", (uid, uid, uid))
    live = q1(c.conn, "SELECT subject, mode FROM timers WHERE user_id=?", (uid,))
    recent = q(c.conn, "SELECT ts, text FROM feed WHERE user_id=? AND kind<>'join' ORDER BY id DESC LIMIT 8", (uid,))
    return {"user": {"id": p["id"], "display": p["display"], "emoji": p["emoji"], "color": p["color"], "identity": p["identity"], "me": uid == me["id"],
                     "av": p["av"] or "", "fr": p["fr"] or "", "titles": season_titles(c.conn, p)},
            "level": level_info(total_xp(c.conn, uid)), "streak": {"now": sv["now"], "longest": max(p["longest"], sv["now"])},
            "live": live, "today_min": st["total"],
            "stats": {"hours": round(s["minutes"] / 60, 1), "xp": total_xp(c.conn, uid), "best_day": s["best_day"], "best_session": s["best_session"],
                      "deep": s["deep"], "floor_days": sum(1 for v in stt.values() if qualifies(v, p["daily_min"])), "sessions": s["sessions"]},
            "heat": heat, "weeks": weeks, "sub30": sub30, "badges": shelf, "badge_total": len(BADGES),
            "duels": {"played": duels["n"], "won": duels["w"]}, "recent": recent}


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
    return {"ladder": [{"level": l, "rank": n, "emoji": e, "xp": LEVEL_K * (l - 1) ** 2} for l, n, e in RANKS], "heat": heat, "hours": hours, "weeks": weeks, "ghost": ghost, "cum": cum, "outgrow": {"ratio": round(ratio, 2), "last7": last7, "baseline_h": u["baseline_h"]},
            "sub7": sub7, "chapters": {"total": ch["n"], "learned": ch["l"] or 0, "mastered": ch["mst"] or 0, "rate": rate, "left": left},
            "exams": exams, "mood": list(reversed(mood)), "urge_triggers": urg,
            "evidence": {"hours": round(s["minutes"] / 60, 1), "sessions": s["sessions"], "deep": s["deep"], "longest": max(u["longest"], u["run"]),
                         "days_hit": qdays, "revs": s["revs"], "urges_won": s["urges_won"], "tests": s["tests"], "mastered": s["mastered"],
                         "learned": s["learned"], "wins": wins},
            "badges": badge_view(c.conn, badges),
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
    return {r["id"]: {"display": r["display"], "emoji": r["emoji"], "color": r["color"], "av": r["av"] or "", "fr": r["fr"] or ""}
            for r in q(conn, "SELECT id, display, emoji, color, av, fr FROM users WHERE crew_id=?", (crew_id,))}


CHAT_EMOJIS = ["🔥", "💀", "😂", "👍", "❤️", "🫡", "💯"]
CHAT_EDIT_WINDOW = 30 * 60  # seconds you can edit your own message


def chat_clean(raw):
    text = str(raw or "")[:CHAT_MAX * 3].replace("\r\n", "\n")
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", text).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    if not text:
        raise ApiError("Say something first")
    if len(text) > CHAT_MAX:
        raise ApiError(f"Max {CHAT_MAX} characters")
    return text


def chat_reacts(conn, ids, uid):
    """({msg_id: {emoji: n}}, {msg_id: my emoji})"""
    re_, mine = {}, {}
    if ids:
        for r in q(conn, f"SELECT msg_id, emoji, user_id FROM msg_reacts WHERE msg_id IN ({','.join('?' * len(ids))})", list(ids)):
            d = re_.setdefault(r["msg_id"], {})
            d[r["emoji"]] = d.get(r["emoji"], 0) + 1
            if r["user_id"] == uid:
                mine[r["msg_id"]] = r["emoji"]
    return re_, mine


def chat_pack(conn, rows, uid):
    """DB rows -> what the client renders (adds reply preview, edited flag, reactions)."""
    if not rows:
        return []
    re_, mine = chat_reacts(conn, [r["id"] for r in rows], uid)
    rids = list({r["reply_to"] for r in rows if r.get("reply_to")})
    refs = {}
    if rids:
        refs = {r["id"]: r for r in q(conn, f"SELECT id, sender, body, deleted FROM messages WHERE id IN ({','.join('?' * len(rids))})", rids)}
    out = []
    for r in rows:
        m = {"id": r["id"], "uid": r["sender"], "ts": r["ts"], "text": r["body"], "edited": bool(r.get("edited"))}
        if r["id"] in re_:
            m["re"] = re_[r["id"]]
        if r["id"] in mine:
            m["mine"] = mine[r["id"]]
        rf = refs.get(r.get("reply_to"))
        if rf:
            m["reply"] = {"id": rf["id"], "uid": rf["sender"], "text": "deleted message" if rf["deleted"] else rf["body"][:90]}
        out.append(m)
    return out


def chat_states(conn, thread, first, uid):
    """Current edit/reaction state of recent messages, so open chats update live without a reload."""
    rows = q(conn, "SELECT id, body, edited FROM messages WHERE thread=? AND id>=? AND deleted=0 ORDER BY id DESC LIMIT 150", (thread, first))
    re_, mine = chat_reacts(conn, [r["id"] for r in rows], uid)
    out = {}
    for r in rows:
        st = {}
        if r["edited"]:
            st["ed"], st["t"] = 1, r["body"]
        if r["id"] in re_:
            st["re"] = re_[r["id"]]
        if r["id"] in mine:
            st["mine"] = mine[r["id"]]
        out[r["id"]] = st
    return out


def chat_fetch(conn, thread, after=0, before=0, limit=60):
    if after:
        rows = q(conn, "SELECT id,sender,ts,body,reply_to,edited FROM messages WHERE thread=? AND id>? AND deleted=0 ORDER BY id LIMIT 200", (thread, after))
        return rows, False
    rows = q(conn, "SELECT id,sender,ts,body,reply_to,edited FROM messages WHERE thread=? AND id<? AND deleted=0 ORDER BY id DESC LIMIT ?",
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
    return {"messages": chat_pack(c.conn, rows, u["id"]), "more": more, "deleted": deleted, "seq": CHAT_SEQ,
            "states": chat_states(c.conn, thread, first, u["id"]) if first else {},
            "people": chat_people(c.conn, u["crew_id"]), "unread": unread, "total": sum(unread.values())}


@route("POST", "/api/chat/send")
def chat_send(c):
    u = c.user
    thread, other = chat_thread(c, str(c.body.get("thread", "")))
    text = chat_clean(c.body.get("text"))
    recent = [t for t in CHAT_RATE.get(u["id"], []) if time.time() - t < 20]
    if len(recent) >= 10:
        raise ApiError("Slow down 😅", 429)
    CHAT_RATE[u["id"]] = recent + [time.time()]
    reply_to = None
    try:
        rid = int(c.body.get("reply_to") or 0)
    except (TypeError, ValueError):
        rid = 0
    if rid and q1(c.conn, "SELECT 1 x FROM messages WHERE id=? AND thread=? AND deleted=0", (rid, thread)):
        reply_to = rid
    ts = now().isoformat(timespec="seconds")
    cur = c.conn.execute("INSERT INTO messages(thread,sender,recip,ts,body,reply_to) VALUES(?,?,?,?,?,?)",
                         (thread, u["id"], other["id"] if other else None, ts, text, reply_to))
    chat_mark(c.conn, u["id"], thread, cur.lastrowid)
    row = q1(c.conn, "SELECT id,sender,ts,body,reply_to,edited FROM messages WHERE id=?", (cur.lastrowid,))
    msg = chat_pack(c.conn, [row], u["id"])[0]
    c.conn.commit()  # visible to waiting pollers before we wake them
    chat_bump()
    return {"message": msg}


@route("POST", "/api/chat/edit")
def chat_edit(c):
    m = q1(c.conn, "SELECT id, sender, ts, deleted FROM messages WHERE id=?", (need(c, "id", int),))
    if not m or m["deleted"] or m["sender"] != c.user["id"]:
        raise ApiError("You can only edit your own messages", 403)
    if (now() - dt.datetime.fromisoformat(m["ts"])).total_seconds() > CHAT_EDIT_WINDOW:
        raise ApiError("Too late to edit (30 min window)")
    text = chat_clean(c.body.get("text"))
    c.conn.execute("UPDATE messages SET body=?, edited=1 WHERE id=?", (text, m["id"]))
    c.conn.commit()
    chat_bump()
    return {"ok": True, "text": text}


@route("POST", "/api/chat/react")
def chat_react(c):
    u = c.user
    e = str(c.body.get("emoji", ""))
    if e not in CHAT_EMOJIS:
        raise ApiError("bad emoji")
    m = q1(c.conn, "SELECT id, thread, sender, recip, deleted FROM messages WHERE id=?", (need(c, "id", int),))
    if not m or m["deleted"]:
        raise ApiError("No such message", 404)
    ok = (m["thread"] == f"crew:{u['crew_id']}") if m["thread"].startswith("crew:") else (u["id"] in (m["sender"], m["recip"]))
    if not ok:
        raise ApiError("No such message", 404)
    cur = q1(c.conn, "SELECT emoji FROM msg_reacts WHERE msg_id=? AND user_id=?", (m["id"], u["id"]))
    if cur and cur["emoji"] == e:
        c.conn.execute("DELETE FROM msg_reacts WHERE msg_id=? AND user_id=?", (m["id"], u["id"]))
    else:
        c.conn.execute("INSERT OR REPLACE INTO msg_reacts(msg_id,user_id,emoji) VALUES(?,?,?)", (m["id"], u["id"], e))
    c.conn.commit()
    chat_bump()
    return {"ok": True}


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
    users = q(conn, f"""SELECT u.id, u.username, u.display, u.crew_id, u.banned, u.prev_crew,
        COALESCE((SELECT SUM(amount) FROM xp WHERE user_id=u.id),0) xp,
        COALESCE((SELECT SUM(amount) FROM xp WHERE user_id=u.id AND {GRIND_SQL}),0) grind,
        (SELECT MAX(day) FROM focus WHERE user_id=u.id) last_focus,
        (SELECT COUNT(*) FROM messages WHERE sender=u.id) msgs
        FROM users u ORDER BY grind DESC""")
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
    return (data, f"ragdamaxing-{now().strftime('%Y%m%d-%H%M')}.db", "application/octet-stream")


XP_SOURCES = {"focus": "Focus session", "deep": "Focus bonus", "clean": "Clean run", "marathon": "Marathon", "ms": "Session milestone",
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


# ----------------------------------------------------------------------------- seasons, weekly challenge, cosmetics
# A season is 4 weeks. Standing = grind XP earned inside it (the same number the weekly league ranks). To be eligible for a prize you must
# have put in 40 verified hours AND hit your floor on 14 days, so nobody wins by one lucky week or by logging manually.
SEASON_DAYS = 28
SEASON_ANCHOR = pd(env("SEASON_ANCHOR", "2026-10-12"))   # a Monday. Season 1 starts here, a new one every 28 days
SEASON_PRIZES = (30000, 15000, 8000)
SEASON_CAT_PRIZE = 5000
SEASON_MIN_MIN, SEASON_MIN_FLOOR = 40 * 60, 14
SEASON_CATS = (("hours", "Most Hours", "min", "min"), ("improved", "Most Improved", "min", "improved"), ("streak", "Iron Streak", "days", "floor_days"),
               ("deep", "Deep Diver", "blocks", "deep"), ("early", "Early Bird", "sessions", "early"))


def season_of(d):
    return (d - SEASON_ANCHOR).days // SEASON_DAYS + 1   # <= 0 before the anchor


def season_range(n):
    a = SEASON_ANCHOR + D((n - 1) * SEASON_DAYS)
    return a, a + D(SEASON_DAYS - 1)


def season_member(conn, u, n):
    """One member's numbers for season n. Only verified (timer) minutes count towards eligibility and the categories."""
    a, b = season_range(n)
    uid = u["id"]
    f = q1(conn, """SELECT COALESCE(SUM(CASE WHEN kind='timer' THEN minutes END),0) vm,
        COALESCE(SUM(CASE WHEN kind='timer' AND minutes>=50 THEN 1 END),0) deep,
        COALESCE(SUM(CASE WHEN kind='timer' AND hour<7 THEN 1 END),0) early
        FROM focus WHERE user_id=? AND day BETWEEN ? AND ?""", (uid, iso(a), iso(b)))
    floor_days = sum(1 for v in day_stats(conn, uid, a, b).values() if qualifies(v, u["daily_min"]))
    prev = 0
    if n > 1:
        pa, pb = season_range(n - 1)
        prev = conn.execute("SELECT COALESCE(SUM(minutes),0) FROM focus WHERE user_id=? AND kind='timer' AND day BETWEEN ? AND ?",
                            (uid, iso(pa), iso(pb))).fetchone()[0]
    return {"id": uid, "xp": grind(conn, uid, iso(a), iso(b + D(1))), "min": f["vm"], "floor_days": floor_days, "deep": f["deep"], "early": f["early"],
            "improved": f["vm"] - prev if prev > 0 else 0, "eligible": f["vm"] >= SEASON_MIN_MIN and floor_days >= SEASON_MIN_FLOOR}


def season_winners(rows):
    el = sorted([r for r in rows if r["eligible"]], key=lambda r: (-r["xp"], r["id"]))
    cats = {}
    for k, _label, _unit, field in SEASON_CATS:
        pool = [r for r in el if r[field] > 0]
        if pool:
            w = max(pool, key=lambda r: (r[field], -r["id"]))
            cats[k] = {"uid": w["id"], "value": w[field]}
    return [r["id"] for r in el[:3]], cats


def crew_members(conn, crew_id):
    return [m for m in q(conn, "SELECT * FROM users WHERE crew_id=?", (crew_id,)) if not m.get("banned")]


def season_settle(c):
    """Pay out every finished season this crew hasn't been paid for yet. Idempotent (results row + unique XP keys)."""
    cid, cur = c.user["crew_id"], season_of(today())
    if cur < 2:
        return
    done = {r["season"] for r in q(c.conn, "SELECT season FROM season_results WHERE crew_id=?", (cid,))}
    for n in range(1, cur):
        if n in done:
            continue
        mem = crew_members(c.conn, cid)
        rows = [season_member(c.conn, m, n) for m in mem]
        by = {m["id"]: m for m in mem}
        xp_of = {r["id"]: r["xp"] for r in rows}
        podium, cats = season_winners(rows)
        data = {"season": n, "members": len(rows), "eligible": sum(1 for r in rows if r["eligible"]),
                "podium": [{"uid": i, "name": by[i]["display"], "emoji": by[i]["emoji"], "xp": xp_of[i]} for i in podium],
                "cats": {k: {**v, "name": by[v["uid"]]["display"], "emoji": by[v["uid"]]["emoji"]} for k, v in cats.items()}}
        cur_ = c.conn.execute("INSERT OR IGNORE INTO season_results(crew_id, season, data) VALUES(?,?,?)", (cid, n, json.dumps(data)))
        if not cur_.rowcount:
            continue
        for i, uid in enumerate(podium):
            award(c, f"season:{n}:{i + 1}", SEASON_PRIZES[i], f"Season {n}: finished #{i + 1}", uid=uid, quiet=uid != c.user["id"])
            feed(c, "season", f"finished #{i + 1} in Season {n} 🏆 +{SEASON_PRIZES[i]:,} XP", uid=uid)
            if i == 0:
                grant_cosmetic(c, "crown", "season", uid=uid)
        labels = {k: lab for k, lab, _u, _f in SEASON_CATS}
        for k, v in cats.items():
            award(c, f"season:{n}:{k}", SEASON_CAT_PRIZE, f"Season {n}: {labels[k]}", uid=v["uid"], quiet=v["uid"] != c.user["id"])
            feed(c, "season", f"won {labels[k]} in Season {n} 🎖️ +{SEASON_CAT_PRIZE:,} XP", uid=v["uid"])


def season_view(conn, u):
    t = today()
    n = season_of(t)
    if not u["crew_id"]:
        return None
    if n < 1:
        return {"n": 0, "starts": iso(SEASON_ANCHOR), "days_to_start": (SEASON_ANCHOR - t).days}
    a, b = season_range(n)
    mem = crew_members(conn, u["crew_id"])
    by = {m["id"]: m for m in mem}
    rows = sorted([season_member(conn, m, n) for m in mem], key=lambda r: (-r["xp"], r["id"]))
    place, k = {}, 0
    for r in rows:
        if r["eligible"] and k < 3:
            k += 1
            place[r["id"]] = k
    _pod, cats = season_winners(rows)
    out = []
    for i, r in enumerate(rows):
        m = by[r["id"]]
        out.append({"id": r["id"], "name": m["display"], "emoji": m["emoji"], "color": m["color"], "av": m.get("av") or "", "fr": m.get("fr") or "",
                    "rank": i + 1, "xp": r["xp"], "hours": round(r["min"] / 60, 1), "floor_days": r["floor_days"], "deep": r["deep"], "early": r["early"],
                    "eligible": r["eligible"], "place": place.get(r["id"]), "me": r["id"] == u["id"]})
    leaders = []
    for key, label, unit, _f in SEASON_CATS:
        v = cats.get(key)
        if v:
            leaders.append({"k": key, "label": label, "unit": unit, "value": v["value"], "name": by[v["uid"]]["display"], "emoji": by[v["uid"]]["emoji"], "me": v["uid"] == u["id"]})
    hall = []
    for r in q(conn, "SELECT data FROM season_results WHERE crew_id=? ORDER BY season DESC LIMIT 6", (u["crew_id"],)):
        d = json.loads(r["data"])
        if d.get("podium"):
            hall.append(d)
    return {"n": n, "start": iso(a), "end": iso(b), "day": (t - a).days + 1, "days": SEASON_DAYS, "days_left": (b - t).days,
            "prizes": list(SEASON_PRIZES), "cat_prize": SEASON_CAT_PRIZE, "min_hours": SEASON_MIN_MIN // 60, "min_floor": SEASON_MIN_FLOOR,
            "rows": out, "cats": leaders, "hall": hall}


def season_brief(conn, u):
    v = season_view(conn, u)
    if not v:
        return None
    if v["n"] < 1:
        return {"n": 0, "days_to_start": v["days_to_start"]}
    me = next(r for r in v["rows"] if r["me"])
    above = v["rows"][me["rank"] - 2] if me["rank"] > 1 else None
    return {"n": v["n"], "day": v["day"], "days": v["days"], "days_left": v["days_left"], "rank": me["rank"], "of": len(v["rows"]), "xp": me["xp"],
            "hours": me["hours"], "floor_days": me["floor_days"], "eligible": me["eligible"], "place": me["place"],
            "min_hours": v["min_hours"], "min_floor": v["min_floor"],
            "chase": {"name": above["name"], "gap": above["xp"] - me["xp"]} if above else None}


def season_titles(conn, p):
    if not p["crew_id"]:
        return []
    out = []
    for r in q(conn, "SELECT data FROM season_results WHERE crew_id=? ORDER BY season", (p["crew_id"],)):
        d = json.loads(r["data"])
        place = next((i + 1 for i, x in enumerate(d.get("podium", [])) if x["uid"] == p["id"]), None)
        cats = [k for k, v in d.get("cats", {}).items() if v["uid"] == p["id"]]
        if place or cats:
            out.append({"season": d["season"], "place": place, "cats": cats})
    return out


# ---- weekly challenge: one rotating goal per week, paid in XP. Four of them unlock the Third Eye avatar.
WCHALLENGES = [  # id, name, description, goal, kind, reward XP
    ("iron", "Iron Week", "20 hours of verified focus this week", 1200, "min", 600),
    ("floor", "Six Floors", "Hit your daily floor on 6 days this week", 6, "floor", 500),
    ("deep", "Deep Work", "8 deep blocks (50+ min) this week", 8, "deep", 500),
    ("dawn", "Dawn Patrol", "4 blocks started before 7 AM this week", 4, "early", 400),
    ("triad", "Holy Trinity", "3 hours each of Physics, Chemistry and Maths this week", 180, "triad", 500),
    ("sit", "One Long Sitting", "A single 2-hour block this week", 120, "sit", 400),
]


def wchal_of(ws):
    return WCHALLENGES[((ws - SEASON_ANCHOR).days // 7) % len(WCHALLENGES)]


def wchal_progress(conn, u, ws, ch):
    uid, kind, a, b = u["id"], ch[4], iso(ws), iso(ws + D(6))
    one = lambda sql, *x: conn.execute(sql, (uid, a, b, *x)).fetchone()[0]
    base = "FROM focus WHERE user_id=? AND day BETWEEN ? AND ? AND kind='timer'"
    if kind == "min":
        return one("SELECT COALESCE(SUM(minutes),0) " + base)
    if kind == "deep":
        return one("SELECT COUNT(*) " + base + " AND minutes>=50")
    if kind == "early":
        return one("SELECT COUNT(*) " + base + " AND hour<7")
    if kind == "sit":
        return one("SELECT COALESCE(MAX(minutes),0) " + base)
    if kind == "triad":
        return min(one("SELECT COALESCE(SUM(minutes),0) " + base + " AND subject=?", sj) for sj in CORE)
    return sum(1 for v in day_stats(conn, uid, ws, ws + D(6)).values() if qualifies(v, u["daily_min"]))


def wchal_count(conn, uid):
    return conn.execute("SELECT COUNT(*) FROM xp WHERE user_id=? AND key LIKE 'wchal:%'", (uid,)).fetchone()[0]


def chal_view(conn, u):
    t = today()
    ws = wstart(t)
    ch = wchal_of(ws)
    have = wchal_progress(conn, u, ws, ch)
    done = bool(conn.execute("SELECT 1 FROM xp WHERE user_id=? AND key=?", (u["id"], f"wchal:{iso(ws)}")).fetchone())
    return {"id": ch[0], "name": ch[1], "desc": ch[2], "goal": ch[3], "have": min(have, ch[3]), "reward": ch[5], "done": done,
            "unit": "min" if ch[4] in ("min", "triad", "sit") else "n", "days_left": (ws + D(6) - t).days, "completed": wchal_count(conn, u["id"])}


def wchal_check(c):
    u = c.user
    ws = wstart(today())
    ch = wchal_of(ws)
    if wchal_progress(c.conn, u, ws, ch) >= ch[3] and award(c, f"wchal:{iso(ws)}", ch[5], f"Weekly challenge: {ch[1]}"):
        feed(c, "challenge", f"completed the weekly challenge: {ch[1]} 🎯")


# ---- cosmetics: avatars and frames. Bought with spare XP (wallet = lifetime XP - spent; your level never drops) or earned.
COSMETICS = [  # id, kind, name, rarity, price (None = earned), how to earn, progress (stat, need, unit, divisor), test
    {"id": "frost", "kind": "frame", "name": "Frost Ring", "rarity": "C", "price": 2500},
    {"id": "neon", "kind": "frame", "name": "Neon Pulse", "rarity": "R", "price": 8000},
    {"id": "ember", "kind": "frame", "name": "Ember Ring", "rarity": "R", "price": None, "how": "Hold a 14-day streak",
     "prog": ("longest", 14, "days", 1), "test": lambda s: s["longest"] >= 14},
    {"id": "void", "kind": "frame", "name": "Void Halo", "rarity": "E", "price": 30000},
    {"id": "crown", "kind": "frame", "name": "Gold Crown", "rarity": "L", "price": None, "how": "Finish a season in 1st place"},
    {"id": "ronin", "kind": "avatar", "name": "Ronin Mask", "rarity": "C", "price": 3500},
    {"id": "wolf", "kind": "avatar", "name": "Lone Wolf", "rarity": "R", "price": None, "how": "Log 100 hours of focus",
     "prog": ("minutes", 6000, "h", 60), "test": lambda s: s["minutes"] >= 6000},
    {"id": "skull", "kind": "avatar", "name": "Cyber Skull", "rarity": "R", "price": 12000},
    {"id": "eye", "kind": "avatar", "name": "Third Eye", "rarity": "E", "price": None, "how": "Complete 4 weekly challenges",
     "prog": ("wchal", 4, "challenges", 1), "test": lambda s: s["wchal"] >= 4},
    {"id": "phoenix", "kind": "avatar", "name": "Phoenix", "rarity": "L", "price": None, "how": "Sit for 4 hours straight (one stopwatch block)",
     "prog": ("best_session", 240, "min", 1), "test": lambda s: s["best_session"] >= 240},
]
COSMETIC_BY_ID = {x["id"]: x for x in COSMETICS}


def wallet(conn, uid):
    spent = conn.execute("SELECT COALESCE(SUM(cost),0) FROM cosmetics WHERE user_id=?", (uid,)).fetchone()[0]
    return max(0, total_xp(conn, uid) - spent), spent


def grant_cosmetic(c, item, src, uid=None, cost=0):
    uid = uid or c.user["id"]
    it = COSMETIC_BY_ID[item]
    cur = c.conn.execute("INSERT OR IGNORE INTO cosmetics(user_id,item,src,cost,day) VALUES(?,?,?,?,?)", (uid, item, src, cost, iso(today())))
    if not cur.rowcount:
        return False
    if uid == c.user["id"]:
        c.ev.append({"t": "cosmetic", "kind": it["kind"], "name": it["name"], "item": item, "rarity": RARITY[it["rarity"]][0], "src": src})
    if src != "buy" or it["rarity"] in ("E", "L"):
        feed(c, "cosmetic", f"{'bought' if src == 'buy' else 'unlocked'} the {it['name']} {it['kind']} ✨", uid=uid)
    return True


def cosmetic_check(c):
    u = c.user
    have = {r["item"] for r in q(c.conn, "SELECT item FROM cosmetics WHERE user_id=?", (u["id"],))}
    todo = [x for x in COSMETICS if x["id"] not in have and x.get("test")]
    if not todo:
        return
    s = dict(getattr(c, "_stats", None) or get_stats(c.conn, u))
    s["wchal"] = wchal_count(c.conn, u["id"])
    for x in todo:
        if x["test"](s):
            grant_cosmetic(c, x["id"], "earn")


def shop_view(conn, u):
    uid = u["id"]
    own = {r["item"]: r["src"] for r in q(conn, "SELECT item, src FROM cosmetics WHERE user_id=?", (uid,))}
    s = dict(get_stats(conn, u))
    s["wchal"] = wchal_count(conn, uid)
    items = []
    for x in COSMETICS:
        row = {"id": x["id"], "kind": x["kind"], "name": x["name"], "rarity": x["rarity"], "rname": RARITY[x["rarity"]][0], "price": x["price"],
               "how": x.get("how"), "owned": x["id"] in own, "src": own.get(x["id"])}
        if x.get("prog") and x["id"] not in own:
            k, need, unit, div = x["prog"]
            row["prog"] = {"have": round(min(s[k], need) / div, 1), "need": round(need / div, 1), "unit": unit}
        items.append(row)
    bal, spent = wallet(conn, uid)
    return {"items": items, "wallet": bal, "spent": spent, "equipped": {"avatar": u.get("av") or "", "frame": u.get("fr") or ""}, "chal": chal_view(conn, u)}


@route("GET", "/api/shop")
def api_shop(c):
    return shop_view(c.conn, c.user)


@route("POST", "/api/shop/buy")
def api_shop_buy(c):
    it = COSMETIC_BY_ID.get(need(c, "item"))
    if not it or it["price"] is None:
        raise ApiError("That one is not for sale. Earn it.")
    if q1(c.conn, "SELECT 1 x FROM cosmetics WHERE user_id=? AND item=?", (c.user["id"], it["id"])):
        raise ApiError("You already own that")
    bal, _ = wallet(c.conn, c.user["id"])
    if bal < it["price"]:
        raise ApiError(f"You need {it['price'] - bal:,} more XP")
    grant_cosmetic(c, it["id"], "buy", cost=it["price"])
    c.conn.execute("UPDATE users SET " + ("av" if it["kind"] == "avatar" else "fr") + "=? WHERE id=?", (it["id"], c.user["id"]))
    c.user = q1(c.conn, "SELECT * FROM users WHERE id=?", (c.user["id"],))
    return {"ok": True, "user": public_user(c.user), "wallet": wallet(c.conn, c.user["id"])[0]}


@route("POST", "/api/shop/equip")
def api_shop_equip(c):
    col = {"avatar": "av", "frame": "fr"}.get(need(c, "kind"))
    if not col:
        raise ApiError("bad kind")
    item = str(c.body.get("item") or "").strip()
    if item:
        it = COSMETIC_BY_ID.get(item)
        if not it or it["kind"] != need(c, "kind"):
            raise ApiError("bad item")
        if not q1(c.conn, "SELECT 1 x FROM cosmetics WHERE user_id=? AND item=?", (c.user["id"], item)):
            raise ApiError("You do not own that", 403)
    c.conn.execute(f"UPDATE users SET {col}=? WHERE id=?", (item, c.user["id"]))
    c.user = q1(c.conn, "SELECT * FROM users WHERE id=?", (c.user["id"],))
    return {"ok": True, "user": public_user(c.user)}


# ----------------------------------------------------------------------------- http
class Handler(BaseHTTPRequestHandler):
    server_version = "Ragdamaxing/4"
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
        if not (fp == STATIC or fp.startswith(STATIC + os.sep)) or not os.path.isfile(fp):
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
            if user and user.get("banned"):
                user = None
            if auth and not user:
                return self.send_json(401, {"error": "login"})
            c = Ctx(conn, user, body, parse_qs(p.query), self)
            before = level_of(total_xp(conn, user["id"])) if user and method == "POST" else None
            before_rank = level_info(total_xp(conn, user["id"]))["rank"] if before is not None else None
            res = fn(c)
            if user:
                hb_touch(conn, user["id"])
            if before is not None and c.user:
                after = level_of(total_xp(conn, c.user["id"]))
                if after > before:
                    li = level_info(total_xp(conn, c.user["id"]))
                    new_title = li["rank"] != before_rank
                    c.ev.append({"t": "levelup", "level": li["level"], "rank": li["rank"], "emoji": li["emoji"], "new_title": new_title})
                    feed(c, "levelup", f"reached level {li['level']} · {li['emoji']} {li['rank']} ⬆️" + (" · NEW TITLE" if new_title else ""))
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


def migrate(conn):
    """Add columns to tables that already exist in older databases. Safe to run on every start."""
    def cols(t):
        return {r[1] for r in conn.execute(f"PRAGMA table_info({t})")}
    for table, col, ddl in (("timers", "mode", "TEXT DEFAULT 'timer'"),
                            ("messages", "reply_to", "INTEGER"),
                            ("messages", "edited", "INTEGER DEFAULT 0"),
                            ("users", "banned", "INTEGER DEFAULT 0"),
                            ("users", "prev_crew", "INTEGER"),
                            ("users", "av", "TEXT DEFAULT ''"),
                            ("users", "fr", "TEXT DEFAULT ''"),
                            ("timers", "last_ping", "REAL"),
                            ("timers", "away", "REAL DEFAULT 0")):
        if col not in cols(table):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
            if col == "last_ping":
                conn.execute("UPDATE timers SET last_ping=?", (time.time(),))  # blocks already running at deploy time are not penalised
    if conn.execute("PRAGMA user_version").fetchone()[0] < 1:
        # v1: the boss used to be resolved (and failed) the moment a day began, so every stored failure is bogus
        conn.execute("DELETE FROM boss_battles WHERE passed=0")
        conn.execute("PRAGMA user_version=1")
    conn.commit()


def bootstrap():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = connect()
    conn.executescript(SCHEMA)
    migrate(conn)
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
    print(f"\n  RAGDAMAXING  ·  http://{BIND}:{PORT}")
    print(f"  Crew: {crew['name']}   Invite code: {crew['code']}")
    print(f"  Server time: {now().isoformat(timespec='seconds')} ({time.strftime('%Z %z')})   admins: {', '.join(sorted(ADMINS)) or 'none'}\n", flush=True)
    Server((BIND, PORT), Handler).serve_forever()
