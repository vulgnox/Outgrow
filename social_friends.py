"""
RAGDAMAXING social layer — friends and blocks.

DM rule (doc default): you can DM a friend or someone you share a server with.
A block is one-way for seeing messages but cuts DMs and friend requests both ways.
"""
import social_profiles as PROFILES

CORE = DB = None


def _ts():
    return CORE.now().isoformat(timespec="seconds")


def _pair(a, b):
    return (int(a), int(b)) if int(a) < int(b) else (int(b), int(a))


def are_friends(conn, a, b):
    x, y = _pair(a, b)
    return bool(conn.execute("SELECT 1 FROM friends WHERE a=? AND b=?", (x, y)).fetchone())


def blocked_by(conn, blocker, target):
    return bool(conn.execute("SELECT 1 FROM blocks WHERE user_id=? AND blocked_id=?", (int(blocker), int(target))).fetchone())


def blocked_either(conn, a, b):
    return blocked_by(conn, a, b) or blocked_by(conn, b, a)


def share_server(conn, a, b):
    return bool(conn.execute(
        """SELECT 1 FROM server_members x JOIN server_members y ON y.server_id=x.server_id
           WHERE x.user_id=? AND y.user_id=? LIMIT 1""", (int(a), int(b))).fetchone())


def same_crew(conn, a, b):
    row = conn.execute("SELECT crew_id FROM users WHERE id=? AND crew_id IS NOT NULL AND crew_id=(SELECT crew_id FROM users WHERE id=?)",
                       (int(a), int(b))).fetchone()
    return bool(row)


def can_dm(conn, a, b):
    if int(a) == int(b) or blocked_either(conn, a, b):
        return False
    return are_friends(conn, a, b) or share_server(conn, a, b) or same_crew(conn, a, b)


def friends_of(conn, uid):
    return {int(r[0]) if int(r[0]) != int(uid) else int(r[1]) for r in conn.execute(
        "SELECT a,b FROM friends WHERE a=? OR b=?", (int(uid), int(uid))).fetchall()}


def block_set(conn, uid):
    return {int(r[0]) for r in conn.execute("SELECT blocked_id FROM blocks WHERE user_id=?", (int(uid),)).fetchall()}


def _card(r):
    out = {"id": int(r["id"]), "username": r["username"], "display": r["display"], "emoji": r["emoji"],
           "color": r["color"], "av": r["av"] or "", "fr": r["fr"] or ""}
    out.update(PROFILES.fields(r))
    return out


def _user(conn, uid):
    r = conn.execute("""SELECT u.id,u.username,u.display,u.emoji,u.color,u.av,u.fr,
            p.avatar_upload,p.status_text,p.status_emoji,p.status_ts
            FROM users u LEFT JOIN profiles p ON p.user_id=u.id WHERE u.id=?""", (int(uid),)).fetchone()
    return _card(r) if r else None


def api_friends(c):
    conn, u = c.conn, c.user
    uid = int(u["id"])
    out = {"friends": [], "incoming": [], "outgoing": [], "blocked": []}
    for r in conn.execute("SELECT a,b FROM friends WHERE a=? OR b=?", (uid, uid)):
        other = int(r[0]) if int(r[0]) != uid else int(r[1])
        card = _user(conn, other)
        if card:
            out["friends"].append(card)
    for r in conn.execute("SELECT f.from_id, f.ts FROM friend_reqs f WHERE f.to_id=?", (uid,)):
        card = _user(conn, r["from_id"])
        if card:
            card["ts"] = r["ts"]
            out["incoming"].append(card)
    for r in conn.execute("SELECT f.to_id, f.ts FROM friend_reqs f WHERE f.from_id=?", (uid,)):
        card = _user(conn, r["to_id"])
        if card:
            card["ts"] = r["ts"]
            out["outgoing"].append(card)
    for r in conn.execute("SELECT b.blocked_id, b.ts FROM blocks b WHERE b.user_id=?", (uid,)):
        card = _user(conn, r["blocked_id"])
        if card:
            card["ts"] = r["ts"]
            out["blocked"].append(card)
    out["friends"].sort(key=lambda x: x["display"].lower())
    return out


def api_friend_request(c):
    conn, u = c.conn, c.user
    uid = int(u["id"])
    target = c.body.get("uid")
    if target in (None, ""):
        name = str(c.body.get("username") or "").strip()
        if not name:
            raise CORE.ApiError("Who should I add?")
        row = conn.execute("SELECT id FROM users WHERE username=? COLLATE NOCASE", (name[:20],)).fetchone()
        if not row:
            raise CORE.ApiError("No user called @%s" % name[:20], 404)
        target = int(row["id"])
    try:
        target = int(target)
    except (TypeError, ValueError):
        raise CORE.ApiError("bad user")
    if target == uid:
        raise CORE.ApiError("That's you")
    if not conn.execute("SELECT 1 FROM users WHERE id=?", (target,)).fetchone():
        raise CORE.ApiError("No such user", 404)
    if blocked_either(conn, uid, target):
        raise CORE.ApiError("Friend request can't be sent", 403)
    if are_friends(conn, uid, target):
        return {"ok": True, "already": True}
    if conn.execute("SELECT 1 FROM friend_reqs WHERE from_id=? AND to_id=?", (target, uid)).fetchone():
        # they already asked you: accept instead of stacking a request
        conn.execute("INSERT OR IGNORE INTO friends(a,b,ts) VALUES(?,?,?)", (*_pair(uid, target), _ts()))
        conn.execute("DELETE FROM friend_reqs WHERE from_id=? AND to_id=?", (target, uid))
        conn.commit()
        return {"ok": True, "accepted": True}
    n = conn.execute("SELECT COUNT(*) FROM friend_reqs WHERE from_id=?", (uid,)).fetchone()[0]
    if n >= 100:
        raise CORE.ApiError("Too many pending requests")
    conn.execute("INSERT OR IGNORE INTO friend_reqs(from_id,to_id,ts) VALUES(?,?,?)", (uid, target, _ts()))
    conn.commit()
    return {"ok": True}


def api_friend_accept(c):
    conn, u = c.conn, c.user
    uid = int(u["id"])
    other = int(CORE.need(c, "uid", int))
    if not conn.execute("SELECT 1 FROM friend_reqs WHERE from_id=? AND to_id=?", (other, uid)).fetchone():
        raise CORE.ApiError("No request from them", 404)
    conn.execute("INSERT OR IGNORE INTO friends(a,b,ts) VALUES(?,?,?)", (*_pair(uid, other), _ts()))
    conn.execute("DELETE FROM friend_reqs WHERE from_id=? AND to_id=?", (other, uid))
    conn.commit()
    return {"ok": True}


def api_friend_decline(c):
    conn, u = c.conn, c.user
    other = int(CORE.need(c, "uid", int))
    conn.execute("DELETE FROM friend_reqs WHERE from_id=? AND to_id=?", (other, u["id"]))
    conn.commit()
    return {"ok": True}


def api_friend_remove(c):
    conn, u = c.conn, c.user
    other = int(CORE.need(c, "uid", int))
    a, b = _pair(u["id"], other)
    conn.execute("DELETE FROM friends WHERE a=? AND b=?", (a, b))
    conn.execute("DELETE FROM friend_reqs WHERE (from_id=? AND to_id=?) OR (from_id=? AND to_id=?)", (a, b, b, a))
    conn.commit()
    return {"ok": True}


def api_block(c):
    conn, u = c.conn, c.user
    other = int(CORE.need(c, "uid", int))
    if other == int(u["id"]):
        raise CORE.ApiError("That's you")
    on = bool(c.body.get("on", True))
    if on:
        conn.execute("INSERT OR REPLACE INTO blocks(user_id,blocked_id,ts) VALUES(?,?,?)", (u["id"], other, _ts()))
        a, b = _pair(u["id"], other)
        conn.execute("DELETE FROM friends WHERE a=? AND b=?", (a, b))
        conn.execute("DELETE FROM friend_reqs WHERE (from_id=? AND to_id=?) OR (from_id=? AND to_id=?)", (a, b, b, a))
    else:
        conn.execute("DELETE FROM blocks WHERE user_id=? AND blocked_id=?", (u["id"], other))
    conn.commit()
    return {"ok": True}


def install(srv, db):
    global CORE, DB
    CORE, DB = srv, db
    for method, path, fn in (
        ("GET", "/api/friends", api_friends),
        ("POST", "/api/friend/request", api_friend_request),
        ("POST", "/api/friend/accept", api_friend_accept),
        ("POST", "/api/friend/decline", api_friend_decline),
        ("POST", "/api/friend/remove", api_friend_remove),
        ("POST", "/api/block", api_block),
    ):
        srv.route(method, path)(fn)
