"""
RAGDAMAXING social layer — permissions.

One function, can(conn, user, server_id, perm, channel_id=None), is the only thing
an endpoint needs to ask. It answers from the stored role bitset, the owner flag,
global RAGDAMAXING admins, timeouts and bans. Nothing trusts a client-supplied
server or channel id without this check.
"""
import time

# permission bits, stored as an INTEGER on roles.perms
PERM = {
    "view": 1 << 0,
    "send": 1 << 1,
    "attach": 1 << 2,
    "react": 1 << 3,
    "voice": 1 << 4,
    "mention_all": 1 << 5,
    "create_invite": 1 << 6,
    "manage_server": 1 << 7,
    "manage_channels": 1 << 8,
    "manage_roles": 1 << 9,
    "kick": 1 << 10,
    "ban": 1 << 11,
    "timeout": 1 << 12,
    "delete_messages": 1 << 13,
    "pin": 1 << 14,
    "music": 1 << 15,
}

ALL = 0
for _v in set(PERM.values()):
    ALL |= _v

# conservative @everyone: talk, react, attach, join voice. Invites and moderation are roles.
DEFAULT_EVERYONE = 0
for _n in ("view", "send", "attach", "react", "voice", "music"):
    DEFAULT_EVERYONE |= PERM[_n]

MODERATOR = 0
for _n in ("view", "send", "attach", "react", "voice", "music", "mention_all", "create_invite",
           "kick", "timeout", "ban", "delete_messages", "manage_channels", "pin"):
    MODERATOR |= PERM[_n]

# a timeout blocks these; it does not stop reading or reacting to old messages? It stops talk.
TIMED_PERMS = {"send", "attach", "voice", "music", "mention_all"}

_ADMINS = set()


def install(srv):
    """Capture the RAGDAMAXING admin usernames from server.py."""
    global _ADMINS
    _ADMINS = srv.ADMINS


def bits(*names):
    v = 0
    for n in names:
        v |= PERM.get(n, 0)
    return v


def has(perms, name):
    return bool((perms or 0) & PERM.get(name, 0))


def is_global_admin(user):
    return bool(user) and str(user["username"]).lower() in _ADMINS


def perms_of(conn, uid, sid):
    """Union of the @everyone role and every role this member holds."""
    total = 0
    rows = conn.execute(
        """SELECT r.perms FROM roles r
           LEFT JOIN role_members rm ON rm.role_id=r.id
           WHERE r.server_id=? AND (r.is_default=1 OR rm.user_id=?)""",
        (sid, uid),
    ).fetchall()
    for r in rows:
        total |= int(r["perms"] or 0)
    if not rows:
        total = DEFAULT_EVERYONE
    return total


def is_member(conn, uid, sid):
    return bool(conn.execute("SELECT 1 FROM server_members WHERE server_id=? AND user_id=?", (sid, uid)).fetchone())


def timeout_until(conn, uid, sid):
    r = conn.execute("SELECT until FROM timeouts WHERE server_id=? AND user_id=?", (sid, uid)).fetchone()
    return (r["until"] or 0) if r else 0


def can(conn, user, sid, perm, channel_id=None):
    """The single gate. False on anything suspicious; never raises."""
    if not user or sid in (None, "", 0):
        return False
    try:
        sid = int(sid)
    except (TypeError, ValueError):
        return False
    srv = conn.execute("SELECT id, owner, crew_id FROM servers WHERE id=?", (sid,)).fetchone()
    if not srv:
        return False
    if channel_id is not None:
        try:
            cid = int(channel_id)
        except (TypeError, ValueError):
            return False
        ch = conn.execute("SELECT id, server_id FROM channels WHERE id=?", (cid,)).fetchone()
        if not ch or int(ch["server_id"]) != sid:
            return False
    if is_global_admin(user):
        return True
    if not is_member(conn, user["id"], sid):
        return False
    if srv["owner"] and int(srv["owner"]) == int(user["id"]):
        return True
    if conn.execute("SELECT 1 FROM bans WHERE server_id=? AND user_id=?", (sid, user["id"])).fetchone():
        return False
    if perm in TIMED_PERMS and timeout_until(conn, user["id"], sid) > time.time():
        return False
    return has(perms_of(conn, user["id"], sid), perm)


def audit(conn, sid, actor, action, target=""):
    conn.execute(
        "INSERT INTO audit(server_id,actor,action,target,ts) VALUES(?,?,?,?,?)",
        (sid, actor, action, str(target)[:200], time.strftime("%Y-%m-%dT%H:%M:%S")),
    )


def audit_rows(conn, sid, limit=60):
    return [dict(r) for r in conn.execute(
        """SELECT a.id, a.action, a.target, a.ts, u.display, u.emoji, u.color
           FROM audit a LEFT JOIN users u ON u.id=a.actor
           WHERE a.server_id=? ORDER BY a.id DESC LIMIT ?""",
        (sid, limit),
    ).fetchall()]
