"""
RAGDAMAXING social layer — servers, channels, roles, invites, moderation.

Every route goes through social_perms.can() with an explicit permission bit.
Invite-only: there is no discovery directory, only codes that can expire or be revoked.
"""
import re
import time

import social_profiles as PROFILES
import social_voice

CORE = DB = PERMS = CHAT = None

RATE = {}
SERVER_NAME = re.compile(r"[A-Za-z0-9 _.\-']{2,30}")
CHAN_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{1,23}")
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

MAX_OWNED = 3        # doc default: anyone can create, capped at 3 owned
MAX_JOINED = 10
MAX_CHANNELS = 30
MAX_ROLES = 25
MAX_INVITES = 20


def _ts():
    return CORE.now().isoformat(timespec="seconds")


def _clean(v, limit=200):
    return re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", str(v or "")).strip()[:limit]


def _sid(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        raise CORE.ApiError("bad server", 400)


def _uid(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        raise CORE.ApiError("bad member", 400)


def _server(c, sid, perm="view"):
    srv = c.conn.execute("SELECT * FROM servers WHERE id=?", (sid,)).fetchone()
    if not srv:
        raise CORE.ApiError("No such server", 404)
    if not PERMS.can(c.conn, c.user, sid, perm):
        if not PERMS.is_member(c.conn, c.user["id"], sid) and not PERMS.is_global_admin(c.user):
            raise CORE.ApiError("No such server", 404)
        raise CORE.ApiError("You don't have permission to do that", 403)
    return srv


def _top_pos(conn, uid, sid):
    return int(conn.execute(
        """SELECT COALESCE(MAX(r.pos),0) FROM roles r JOIN role_members rm ON rm.role_id=r.id
           WHERE r.server_id=? AND rm.user_id=?""", (sid, uid)).fetchone()[0])


def _is_owner(srv, user):
    return bool(srv["owner"] and int(srv["owner"]) == int(user["id"]))


def _act_on(conn, actor, srv, target_id):
    """Can actor kick/timeout/ban this member? Owner and global admins bypass role order."""
    if int(target_id) == int(actor["id"]):
        raise CORE.ApiError("You can't do that to yourself")
    target = conn.execute("SELECT id, username FROM users WHERE id=?", (target_id,)).fetchone()
    if not target or not PERMS.is_member(conn, target_id, srv["id"]):
        raise CORE.ApiError("No such member", 404)
    if PERMS.is_global_admin(actor):
        return target
    if PERMS.is_global_admin(target):
        raise CORE.ApiError("You can't moderate an admin", 403)
    if _is_owner(srv, actor):
        return target
    if _is_owner(srv, target):
        raise CORE.ApiError("You can't moderate the owner", 403)
    if _top_pos(conn, actor["id"], srv["id"]) <= _top_pos(conn, target_id, srv["id"]):
        raise CORE.ApiError("They are equal or higher in the role order", 403)
    return target


def _mask(conn, actor, srv, requested):
    """Never let someone grant a permission they do not hold themselves."""
    mine = PERMS.ALL if (_is_owner(srv, actor) or PERMS.is_global_admin(actor)) else PERMS.perms_of(conn, actor["id"], srv["id"])
    return int(requested) & mine & PERMS.ALL


def _can_edit_role(conn, actor, srv, role):
    if _is_owner(srv, actor) or PERMS.is_global_admin(actor):
        return True
    if role["is_default"]:
        return True
    return int(role["pos"] or 0) < _top_pos(conn, actor["id"], srv["id"])


def _emit(conn, sid, event="channels", extra=None, users=None):
    """Tell live clients that a server's shape changed. Explicit users win (deleted servers)."""
    if not CHAT:
        return
    if users is None:
        users = set(DB.member_ids(conn, sid))
    data = {"sid": int(sid)}
    if extra:
        data.update(extra)
    CHAT.emit(event, data, users)


def _role_json(conn, r, member_ids):
    return {"id": int(r["id"]), "name": r["name"], "color": r["color"] or "", "perms": int(r["perms"] or 0),
            "pos": int(r["pos"] or 0), "default": bool(r["is_default"]),
            "members": [int(x) for x in member_ids.get(int(r["id"]), [])]}


def _user_card(r):
    out = {"id": int(r["id"]), "username": r["username"], "display": r["display"], "emoji": r["emoji"],
           "color": r["color"], "av": r["av"] or "", "fr": r["fr"] or ""}
    out.update(PROFILES.fields(r))
    return out


# ----------------------------------------------------------------------------- servers
def api_server(c):
    conn, u = c.conn, c.user
    sid = _sid(CORE.qpi(c, "sid"))
    srv = _server(c, sid, "view")
    chans = [{"id": int(ch["id"]), "name": ch["name"], "kind": ch["kind"], "topic": ch["topic"] or "",
              "pos": int(ch["pos"] or 0)} for ch in DB.channel_rows(conn, sid)]
    roles = conn.execute("SELECT * FROM roles WHERE server_id=? ORDER BY pos, id", (sid,)).fetchall()
    rm = {}
    for row in conn.execute("SELECT rm.role_id, rm.user_id FROM role_members rm JOIN roles r ON r.id=rm.role_id WHERE r.server_id=?", (sid,)):
        rm.setdefault(int(row["role_id"]), []).append(int(row["user_id"]))
    members = []
    for row in conn.execute("""SELECT u.*, t.until, p.avatar_upload, p.status_text, p.status_emoji, p.status_ts
            FROM server_members m JOIN users u ON u.id=m.user_id
            LEFT JOIN timeouts t ON t.server_id=m.server_id AND t.user_id=m.user_id
            LEFT JOIN profiles p ON p.user_id=u.id
            WHERE m.server_id=? ORDER BY u.display COLLATE NOCASE""", (sid,)):
        card = _user_card(row)
        card["roles"] = [rid for rid, ids in rm.items() if int(row["id"]) in ids]
        card["timeout"] = int(row["until"] or 0)
        card["owner"] = bool(srv["owner"] and int(srv["owner"]) == int(row["id"]))
        members.append(card)
    mine = PERMS.ALL if (_is_owner(srv, u) or PERMS.is_global_admin(u)) else PERMS.perms_of(conn, u["id"], sid)
    out = {"server": {"id": int(srv["id"]), "name": srv["name"], "icon": srv["icon"] or "", "owner": int(srv["owner"] or 0),
                      "legacy": bool(srv["legacy"]), "crew_id": srv["crew_id"], "members": len(members)},
           "channels": chans,
           "roles": [_role_json(conn, r, rm) for r in roles],
           "members": members,
           "me": {"perms": mine, "owner": _is_owner(srv, u), "id": int(u["id"])}}
    if mine & PERMS.PERM["create_invite"]:
        out["invites"] = [{"code": r["code"], "created_at": r["created_at"], "expires": r["expires"] or "",
                           "max_uses": int(r["max_uses"] or 0), "uses": int(r["uses"] or 0)}
                          for r in conn.execute("SELECT * FROM invites WHERE server_id=? ORDER BY created_at DESC", (sid,))]
    return out


def api_server_create(c):
    conn, u = c.conn, c.user
    now = time.time()
    recent = [t for t in RATE.get("create:%s" % u["id"], []) if now - t < 86400]
    if len(recent) >= 5:
        raise CORE.ApiError("That's enough servers for one day", 429)
    name = _clean(c.body.get("name"), 40)
    if not SERVER_NAME.fullmatch(name):
        raise CORE.ApiError("Server name: 2-30 letters, numbers, spaces or . _ -")
    owned = conn.execute("SELECT COUNT(*) FROM servers WHERE owner=? AND legacy=0", (u["id"],)).fetchone()[0]
    if owned >= MAX_OWNED:
        raise CORE.ApiError("You already own %d servers. That's the cap." % MAX_OWNED, 403)
    icon = _clean(c.body.get("icon"), 8)
    cur = conn.execute("INSERT INTO servers(crew_id,name,icon,owner,legacy,created_at) VALUES(NULL,?,?,?,0,?)",
                       (name, icon, u["id"], _ts()))
    sid = cur.lastrowid
    conn.execute("INSERT INTO server_members(server_id,user_id,joined_at) VALUES(?,?,?)", (sid, u["id"], _ts()))
    DB.ensure_roles(conn, sid)
    conn.execute("INSERT INTO channels(server_id,name,kind,topic,pos,legacy_thread,created_at) VALUES(?,?,?,?,0,'',?)",
                 (sid, "general", "text", "Start here.", _ts()))
    PERMS.audit(conn, sid, u["id"], "server.create", name)
    conn.commit()
    RATE["create:%s" % u["id"]] = recent + [now]
    return {"server_id": int(sid)}


def api_server_update(c):
    conn, u = c.conn, c.user
    sid = _sid(c.body.get("sid"))
    srv = _server(c, sid, "manage_server")
    name = _clean(c.body.get("name"), 40) if "name" in c.body else None
    if name is not None:
        if not SERVER_NAME.fullmatch(name):
            raise CORE.ApiError("Server name: 2-30 letters, numbers, spaces or . _ -")
        conn.execute("UPDATE servers SET name=? WHERE id=?", (name, sid))
    if "icon" in c.body:
        conn.execute("UPDATE servers SET icon=? WHERE id=?", (_clean(c.body.get("icon"), 8), sid))
    PERMS.audit(conn, sid, u["id"], "server.update", name or "")
    conn.commit()
    _emit(conn, sid)
    return {"ok": True}


def api_server_delete(c):
    conn, u = c.conn, c.user
    sid = _sid(c.body.get("sid"))
    srv = _server(c, sid, "manage_server")
    if not _is_owner(srv, u) and not PERMS.is_global_admin(u):
        raise CORE.ApiError("Only the owner can delete a server", 403)
    if srv["legacy"]:
        raise CORE.ApiError("Your crew server is automatic and can't be deleted")
    users = set(DB.member_ids(conn, sid))
    for ch in DB.channel_rows(conn, sid):
        conn.execute("DELETE FROM messages WHERE thread=?", ("ch:%s" % ch["id"],))
        conn.execute("DELETE FROM chat_reads WHERE thread=?", ("ch:%s" % ch["id"],))
        social_voice.drop_channel(int(ch["id"]))
    conn.execute("DELETE FROM role_members WHERE role_id IN (SELECT id FROM roles WHERE server_id=?)", (sid,))
    for tb in ("channels", "roles", "invites", "audit", "bans", "timeouts", "server_members"):
        conn.execute("DELETE FROM %s WHERE server_id=?" % tb, (sid,))
    conn.execute("DELETE FROM servers WHERE id=?", (sid,))
    conn.commit()
    _emit(conn, sid, "channels", {"deleted": True}, users)
    return {"ok": True}


def api_server_join(c):
    conn, u = c.conn, c.user
    code = _clean(c.body.get("code"), 16).upper()
    inv = conn.execute("SELECT * FROM invites WHERE code=?", (code,)).fetchone()
    if not inv:
        raise CORE.ApiError("That invite code is not valid", 404)
    now = time.time()
    recent = [t for t in RATE.get("join:%s" % u["id"], []) if now - t < 3600]
    if len(recent) >= 10:
        raise CORE.ApiError("Too many invite joins. Try again later.", 429)
    if inv["expires"] and inv["expires"] < _ts():
        raise CORE.ApiError("That invite has expired", 410)
    if inv["max_uses"] and int(inv["uses"] or 0) >= int(inv["max_uses"]):
        raise CORE.ApiError("That invite has been used up", 410)
    sid = int(inv["server_id"])
    srv = conn.execute("SELECT * FROM servers WHERE id=?", (sid,)).fetchone()
    if not srv:
        raise CORE.ApiError("That server is gone", 404)
    if conn.execute("SELECT 1 FROM bans WHERE server_id=? AND user_id=?", (sid, u["id"])).fetchone():
        raise CORE.ApiError("You are banned from that server", 403)
    if PERMS.is_member(conn, u["id"], sid):
        return {"server_id": sid, "already": True}
    joined = conn.execute("SELECT COUNT(*) FROM server_members WHERE user_id=?", (u["id"],)).fetchone()[0]
    if joined >= MAX_JOINED:
        raise CORE.ApiError("You are in %d servers already. That's the cap." % MAX_JOINED, 403)
    conn.execute("INSERT INTO server_members(server_id,user_id,joined_at) VALUES(?,?,?)", (sid, u["id"], _ts()))
    conn.execute("UPDATE invites SET uses=uses+1 WHERE code=?", (code,))
    for ch in DB.channel_rows(conn, sid):
        th = DB.thread_of(ch)
        last = conn.execute("SELECT COALESCE(MAX(id),0) FROM messages WHERE thread=?", (th,)).fetchone()[0]
        conn.execute("INSERT OR IGNORE INTO chat_reads(user_id,thread,last_id) VALUES(?,?,?)", (u["id"], th, last))
    PERMS.audit(conn, sid, u["id"], "member.join", u["username"])
    conn.commit()
    RATE["join:%s" % u["id"]] = recent + [now]
    _emit(conn, sid, "members")
    return {"server_id": sid}


def api_server_leave(c):
    conn, u = c.conn, c.user
    sid = _sid(c.body.get("sid"))
    srv = _server(c, sid, "view")
    if _is_owner(srv, u) and not srv["legacy"]:
        raise CORE.ApiError("You own this server. Delete it or transfer it first.")
    if srv["legacy"]:
        raise CORE.ApiError("Your crew server is automatic. Change crews instead.")
    conn.execute("DELETE FROM server_members WHERE server_id=? AND user_id=?", (sid, u["id"]))
    PERMS.audit(conn, sid, u["id"], "member.leave", u["username"])
    conn.commit()
    _emit(conn, sid, "members")
    return {"ok": True}


# ----------------------------------------------------------------------------- invites
def api_invite_create(c):
    conn, u = c.conn, c.user
    sid = _sid(c.body.get("sid"))
    srv = _server(c, sid, "create_invite")
    n = conn.execute("SELECT COUNT(*) FROM invites WHERE server_id=?", (sid,)).fetchone()[0]
    if n >= MAX_INVITES:
        raise CORE.ApiError("Too many active invites. Revoke one first.")
    try:
        days = int(c.body.get("days", 7))
    except (TypeError, ValueError):
        days = 7
    days = max(0, min(days, 30))
    try:
        uses = int(c.body.get("max_uses", 0) or 0)
    except (TypeError, ValueError):
        uses = 0
    uses = max(0, min(uses, 100))
    for _ in range(20):
        code = "".join(CORE.random.choice(CODE_ALPHABET) for _ in range(8))
        if not conn.execute("SELECT 1 FROM invites WHERE code=?", (code,)).fetchone():
            break
    expires = (CORE.now() + CORE.D(days)).isoformat(timespec="seconds") if days else ""
    conn.execute("INSERT INTO invites(code,server_id,created_by,created_at,expires,max_uses,uses) VALUES(?,?,?,?,?,?,0)",
                 (code, sid, u["id"], _ts(), expires, uses))
    PERMS.audit(conn, sid, u["id"], "invite.create", code)
    conn.commit()
    return {"code": code, "expires": expires}


def api_invite_revoke(c):
    conn, u = c.conn, c.user
    sid = _sid(c.body.get("sid"))
    _server(c, sid, "create_invite")
    code = _clean(c.body.get("code"), 16).upper()
    conn.execute("DELETE FROM invites WHERE server_id=? AND code=?", (sid, code))
    PERMS.audit(conn, sid, u["id"], "invite.revoke", code)
    conn.commit()
    return {"ok": True}


# ----------------------------------------------------------------------------- channels
def api_channel_create(c):
    conn, u = c.conn, c.user
    sid = _sid(c.body.get("sid"))
    _server(c, sid, "manage_channels")
    kind = "voice" if str(c.body.get("kind")) == "voice" else "text"
    raw = _clean(c.body.get("name"), 40).lower().replace(" ", "-")
    name = re.sub(r"[^a-z0-9_-]", "", raw)[:24]
    if len(name) < 2 or not CHAN_NAME.fullmatch(name):
        raise CORE.ApiError("Channel name: 2-24 lowercase letters, numbers, - or _")
    count = conn.execute("SELECT COUNT(*) FROM channels WHERE server_id=?", (sid,)).fetchone()[0]
    if count >= MAX_CHANNELS:
        raise CORE.ApiError("This server has %d channels. That's the cap." % MAX_CHANNELS)
    base, n = name, 2
    while conn.execute("SELECT 1 FROM channels WHERE server_id=? AND name=?", (sid, name)).fetchone():
        name = "%s-%d" % (base, n)
        n += 1
    pos = conn.execute("SELECT COALESCE(MAX(pos),-1)+1 FROM channels WHERE server_id=?", (sid,)).fetchone()[0]
    cur = conn.execute("INSERT INTO channels(server_id,name,kind,topic,pos,legacy_thread,created_at) VALUES(?,?,?,?,?,'',?)",
                       (sid, name, kind, _clean(c.body.get("topic"), 120), pos, _ts()))
    PERMS.audit(conn, sid, u["id"], "channel.create", name)
    conn.commit()
    _emit(conn, sid)
    return {"channel_id": int(cur.lastrowid), "name": name}


def api_channel_update(c):
    conn, u = c.conn, c.user
    ch = c.conn.execute("SELECT * FROM channels WHERE id=?", (_sid(c.body.get("ch")),)).fetchone()
    if not ch:
        raise CORE.ApiError("No such channel", 404)
    _server(c, int(ch["server_id"]), "manage_channels")
    if "name" in c.body:
        raw = _clean(c.body.get("name"), 40).lower().replace(" ", "-")
        name = re.sub(r"[^a-z0-9_-]", "", raw)[:24]
        if not CHAN_NAME.fullmatch(name):
            raise CORE.ApiError("Channel name: 2-24 lowercase letters, numbers, - or _")
        clash = conn.execute("SELECT 1 FROM channels WHERE server_id=? AND name=? AND id<>?",
                             (ch["server_id"], name, ch["id"])).fetchone()
        if clash:
            raise CORE.ApiError("A channel with that name already exists")
        conn.execute("UPDATE channels SET name=? WHERE id=?", (name, ch["id"]))
    if "topic" in c.body:
        conn.execute("UPDATE channels SET topic=? WHERE id=?", (_clean(c.body.get("topic"), 120), ch["id"]))
    if "pos" in c.body:
        try:
            pos = max(0, min(int(c.body.get("pos")), 100))
        except (TypeError, ValueError):
            pos = 0
        conn.execute("UPDATE channels SET pos=? WHERE id=?", (pos, ch["id"]))
    PERMS.audit(conn, int(ch["server_id"]), u["id"], "channel.update", ch["name"])
    conn.commit()
    _emit(conn, int(ch["server_id"]))
    return {"ok": True}


def api_channel_delete(c):
    conn, u = c.conn, c.user
    ch = conn.execute("SELECT * FROM channels WHERE id=?", (_sid(c.body.get("ch")),)).fetchone()
    if not ch:
        raise CORE.ApiError("No such channel", 404)
    sid = int(ch["server_id"])
    _server(c, sid, "manage_channels")
    if ch["legacy_thread"]:
        raise CORE.ApiError("This channel holds your crew's old history and can't be deleted")
    text_ch = conn.execute("SELECT COUNT(*) FROM channels WHERE server_id=? AND kind='text'", (sid,)).fetchone()[0]
    if ch["kind"] == "text" and text_ch <= 1:
        raise CORE.ApiError("A server needs at least one text channel")
    conn.execute("DELETE FROM messages WHERE thread=?", ("ch:%s" % ch["id"],))
    conn.execute("DELETE FROM chat_reads WHERE thread=?", ("ch:%s" % ch["id"],))
    conn.execute("DELETE FROM channels WHERE id=?", (ch["id"],))
    social_voice.drop_channel(int(ch["id"]))
    PERMS.audit(conn, sid, u["id"], "channel.delete", ch["name"])
    conn.commit()
    _emit(conn, sid)
    return {"ok": True}


# ----------------------------------------------------------------------------- roles
def api_roles(c):
    conn = c.conn
    sid = _sid(CORE.qpi(c, "sid"))
    _server(c, sid, "view")
    roles = conn.execute("SELECT * FROM roles WHERE server_id=? ORDER BY pos, id", (sid,)).fetchall()
    rm = {}
    for row in conn.execute("SELECT rm.role_id, rm.user_id FROM role_members rm JOIN roles r ON r.id=rm.role_id WHERE r.server_id=?", (sid,)):
        rm.setdefault(int(row["role_id"]), []).append(int(row["user_id"]))
    return {"roles": [_role_json(conn, r, rm) for r in roles]}


def api_role_create(c):
    conn, u = c.conn, c.user
    sid = _sid(c.body.get("sid"))
    srv = _server(c, sid, "manage_roles")
    n = conn.execute("SELECT COUNT(*) FROM roles WHERE server_id=?", (sid,)).fetchone()[0]
    if n >= MAX_ROLES:
        raise CORE.ApiError("Too many roles")
    name = _clean(c.body.get("name"), 30)
    if not name:
        raise CORE.ApiError("Give the role a name")
    color = _clean(c.body.get("color"), 7)
    if color and not HEX.match(color):
        raise CORE.ApiError("Colour must be a hex value like #7c6af7")
    try:
        req = int(c.body.get("perms") or 0)
    except (TypeError, ValueError):
        req = 0
    perms = _mask(conn, u, srv, req)
    pos = int(conn.execute("SELECT COALESCE(MAX(pos),0)+1 FROM roles WHERE server_id=?", (sid,)).fetchone()[0])
    cur = conn.execute("INSERT INTO roles(server_id,name,color,perms,pos,is_default) VALUES(?,?,?,?,?,0)",
                       (sid, name, color, perms, pos))
    PERMS.audit(conn, sid, u["id"], "role.create", name)
    conn.commit()
    _emit(conn, sid, "roles")
    return {"role_id": int(cur.lastrowid)}


def api_role_update(c):
    conn, u = c.conn, c.user
    sid = _sid(c.body.get("sid"))
    srv = _server(c, sid, "manage_roles")
    role = conn.execute("SELECT * FROM roles WHERE id=? AND server_id=?", (_sid(c.body.get("role")), sid)).fetchone()
    if not role:
        raise CORE.ApiError("No such role", 404)
    if not _can_edit_role(conn, u, srv, role):
        raise CORE.ApiError("That role is above yours", 403)
    if "name" in c.body and not role["is_default"]:
        name = _clean(c.body.get("name"), 30)
        if not name:
            raise CORE.ApiError("Give the role a name")
        conn.execute("UPDATE roles SET name=? WHERE id=?", (name, role["id"]))
    if "color" in c.body:
        color = _clean(c.body.get("color"), 7)
        if color and not HEX.match(color):
            raise CORE.ApiError("Colour must be a hex value like #7c6af7")
        conn.execute("UPDATE roles SET color=? WHERE id=?", (color, role["id"]))
    if "perms" in c.body:
        try:
            req = int(c.body.get("perms") or 0)
        except (TypeError, ValueError):
            req = 0
        conn.execute("UPDATE roles SET perms=? WHERE id=?", (_mask(conn, u, srv, req), role["id"]))
    PERMS.audit(conn, sid, u["id"], "role.update", role["name"])
    conn.commit()
    _emit(conn, sid, "roles")
    return {"ok": True}


def api_role_delete(c):
    conn, u = c.conn, c.user
    sid = _sid(c.body.get("sid"))
    srv = _server(c, sid, "manage_roles")
    role = conn.execute("SELECT * FROM roles WHERE id=? AND server_id=?", (_sid(c.body.get("role")), sid)).fetchone()
    if not role:
        raise CORE.ApiError("No such role", 404)
    if role["is_default"]:
        raise CORE.ApiError("The @everyone role can't be deleted")
    if not _can_edit_role(conn, u, srv, role):
        raise CORE.ApiError("That role is above yours", 403)
    conn.execute("DELETE FROM role_members WHERE role_id=?", (role["id"],))
    conn.execute("DELETE FROM roles WHERE id=?", (role["id"],))
    PERMS.audit(conn, sid, u["id"], "role.delete", role["name"])
    conn.commit()
    _emit(conn, sid, "roles")
    return {"ok": True}


def api_role_assign(c):
    conn, u = c.conn, c.user
    sid = _sid(c.body.get("sid"))
    srv = _server(c, sid, "manage_roles")
    role = conn.execute("SELECT * FROM roles WHERE id=? AND server_id=?", (_sid(c.body.get("role")), sid)).fetchone()
    if not role:
        raise CORE.ApiError("No such role", 404)
    if role["is_default"]:
        raise CORE.ApiError("@everyone is automatic")
    if not _can_edit_role(conn, u, srv, role):
        raise CORE.ApiError("That role is above yours", 403)
    target = _uid(c.body.get("uid"))
    if not PERMS.is_member(conn, target, sid):
        raise CORE.ApiError("They are not in this server", 404)
    if _is_owner(srv, {"id": target}) and not (_is_owner(srv, u) or PERMS.is_global_admin(u)):
        raise CORE.ApiError("You can't change the owner's roles", 403)
    if role["perms"] & ~_mask(conn, u, srv, PERMS.ALL) and not (_is_owner(srv, u) or PERMS.is_global_admin(u)):
        raise CORE.ApiError("That role has permissions you don't hold", 403)
    on = bool(c.body.get("on", True))
    if on:
        conn.execute("INSERT OR IGNORE INTO role_members(role_id,user_id) VALUES(?,?)", (role["id"], target))
    else:
        conn.execute("DELETE FROM role_members WHERE role_id=? AND user_id=?", (role["id"], target))
    PERMS.audit(conn, sid, u["id"], "role.assign" if on else "role.unassign", "%s -> %s" % (role["name"], target))
    conn.commit()
    _emit(conn, sid, "roles")
    return {"ok": True}


# ----------------------------------------------------------------------------- moderation
def api_mod_kick(c):
    conn, u = c.conn, c.user
    sid = _sid(c.body.get("sid"))
    srv = _server(c, sid, "kick")
    target = _act_on(conn, u, srv, _uid(c.body.get("uid")))
    conn.execute("DELETE FROM server_members WHERE server_id=? AND user_id=?", (sid, target["id"]))
    PERMS.audit(conn, sid, u["id"], "member.kick", target["username"])
    conn.commit()
    _emit(conn, sid, "members")
    return {"ok": True}


def api_mod_timeout(c):
    conn, u = c.conn, c.user
    sid = _sid(c.body.get("sid"))
    srv = _server(c, sid, "timeout")
    target = _act_on(conn, u, srv, _uid(c.body.get("uid")))
    try:
        minutes = int(c.body.get("minutes") or 10)
    except (TypeError, ValueError):
        minutes = 10
    minutes = max(1, min(minutes, 7 * 24 * 60))
    until = time.time() + minutes * 60
    reason = _clean(c.body.get("reason"), 120)
    conn.execute("""INSERT INTO timeouts(server_id,user_id,until,by_id,reason) VALUES(?,?,?,?,?)
        ON CONFLICT(server_id,user_id) DO UPDATE SET until=excluded.until, by_id=excluded.by_id, reason=excluded.reason""",
                 (sid, target["id"], until, u["id"], reason))
    PERMS.audit(conn, sid, u["id"], "member.timeout", "%s %dm %s" % (target["username"], minutes, reason))
    conn.commit()
    _emit(conn, sid, "members")
    return {"ok": True, "until": until}


def api_mod_untimeout(c):
    conn, u = c.conn, c.user
    sid = _sid(c.body.get("sid"))
    _server(c, sid, "timeout")
    conn.execute("DELETE FROM timeouts WHERE server_id=? AND user_id=?", (sid, _uid(c.body.get("uid"))))
    PERMS.audit(conn, sid, u["id"], "member.untimeout", str(c.body.get("uid")))
    conn.commit()
    _emit(conn, sid, "members")
    return {"ok": True}


def api_mod_ban(c):
    conn, u = c.conn, c.user
    sid = _sid(c.body.get("sid"))
    srv = _server(c, sid, "ban")
    target = _act_on(conn, u, srv, _uid(c.body.get("uid")))
    conn.execute("INSERT OR REPLACE INTO bans(server_id,user_id,by_id,ts,reason) VALUES(?,?,?,?,?)",
                 (sid, target["id"], u["id"], _ts(), _clean(c.body.get("reason"), 120)))
    conn.execute("DELETE FROM server_members WHERE server_id=? AND user_id=?", (sid, target["id"]))
    conn.execute("DELETE FROM timeouts WHERE server_id=? AND user_id=?", (sid, target["id"]))
    PERMS.audit(conn, sid, u["id"], "member.ban", target["username"])
    conn.commit()
    _emit(conn, sid, "members")
    return {"ok": True}


def api_mod_unban(c):
    conn, u = c.conn, c.user
    sid = _sid(c.body.get("sid"))
    _server(c, sid, "ban")
    target = _uid(c.body.get("uid"))
    conn.execute("DELETE FROM bans WHERE server_id=? AND user_id=?", (sid, target))
    PERMS.audit(conn, sid, u["id"], "member.unban", str(target))
    conn.commit()
    return {"ok": True}


def api_bans(c):
    conn = c.conn
    sid = _sid(CORE.qpi(c, "sid"))
    _server(c, sid, "ban")
    rows = conn.execute("""SELECT b.user_id, b.ts, b.reason, u.username, u.display, u.emoji, u.color
        FROM bans b JOIN users u ON u.id=b.user_id WHERE b.server_id=? ORDER BY b.ts DESC""", (sid,)).fetchall()
    return {"bans": [{"id": int(r["user_id"]), "username": r["username"], "display": r["display"],
                      "emoji": r["emoji"], "color": r["color"], "ts": r["ts"], "reason": r["reason"] or ""} for r in rows]}


def api_audit(c):
    conn = c.conn
    sid = _sid(CORE.qpi(c, "sid"))
    _server(c, sid, "view")
    if not PERMS.can(conn, c.user, sid, "manage_server") and not PERMS.is_global_admin(c.user):
        raise CORE.ApiError("You don't have permission to do that", 403)
    return {"audit": PERMS.audit_rows(conn, sid, 80)}


# ----------------------------------------------------------------------------- reports
def api_report(c):
    conn, u = c.conn, c.user
    mid = CORE.need(c, "id", int)
    msg = conn.execute("SELECT id, thread, body FROM messages WHERE id=?", (mid,)).fetchone()
    if not msg:
        raise CORE.ApiError("No such message", 404)
    sid = 0
    if msg["thread"].startswith("ch:"):
        ch = conn.execute("SELECT * FROM channels WHERE id=?", (int(msg["thread"][3:]),)).fetchone()
        if not ch or not PERMS.can(conn, u, ch["server_id"], "view", ch["id"]):
            raise CORE.ApiError("No such message", 404)
        sid = int(ch["server_id"])
    elif msg["thread"].startswith("crew:"):
        if not u["crew_id"] or msg["thread"] != "crew:%s" % u["crew_id"]:
            raise CORE.ApiError("No such message", 404)
    else:
        raise CORE.ApiError("Only server messages can be reported")
    reason = _clean(c.body.get("reason"), 200) or "No reason given"
    conn.execute("INSERT INTO reports(ts,reporter,server_id,message_id,reason,status) VALUES(?,?,?,?,?, 'open')",
                 (_ts(), u["id"], sid, mid, reason))
    if sid:
        PERMS.audit(conn, sid, u["id"], "message.report", "msg %s" % mid)
    conn.commit()
    return {"ok": True}


def api_reports(c):
    if not PERMS.is_global_admin(c.user):
        raise CORE.ApiError("Admins only", 403)
    rows = c.conn.execute("""SELECT r.id, r.ts, r.server_id, r.message_id, r.reason, r.status,
            u.display, u.emoji, m.body, m.thread
        FROM reports r LEFT JOIN users u ON u.id=r.reporter LEFT JOIN messages m ON m.id=r.message_id
        WHERE r.status='open' ORDER BY r.id DESC LIMIT 100""").fetchall()
    return {"reports": [{"id": int(r["id"]), "ts": r["ts"], "server": int(r["server_id"] or 0),
                         "message": int(r["message_id"] or 0), "reason": r["reason"] or "",
                         "by": r["display"] or "?", "emoji": r["emoji"] or "", "text": (r["body"] or "")[:200]} for r in rows]}


def install(srv, db, permissions, chat):
    global CORE, DB, PERMS, CHAT
    CORE, DB, PERMS, CHAT = srv, db, permissions, chat
    routes = [
        ("GET", "/api/server", api_server),
        ("POST", "/api/server/create", api_server_create),
        ("POST", "/api/server/update", api_server_update),
        ("POST", "/api/server/delete", api_server_delete),
        ("POST", "/api/server/join", api_server_join),
        ("POST", "/api/server/leave", api_server_leave),
        ("POST", "/api/invite/create", api_invite_create),
        ("POST", "/api/invite/revoke", api_invite_revoke),
        ("POST", "/api/channel/create", api_channel_create),
        ("POST", "/api/channel/update", api_channel_update),
        ("POST", "/api/channel/delete", api_channel_delete),
        ("GET", "/api/roles", api_roles),
        ("POST", "/api/role/create", api_role_create),
        ("POST", "/api/role/update", api_role_update),
        ("POST", "/api/role/delete", api_role_delete),
        ("POST", "/api/role/assign", api_role_assign),
        ("POST", "/api/mod/kick", api_mod_kick),
        ("POST", "/api/mod/timeout", api_mod_timeout),
        ("POST", "/api/mod/untimeout", api_mod_untimeout),
        ("POST", "/api/mod/ban", api_mod_ban),
        ("POST", "/api/mod/unban", api_mod_unban),
        ("GET", "/api/bans", api_bans),
        ("GET", "/api/audit", api_audit),
        ("POST", "/api/report", api_report),
        ("GET", "/api/reports", api_reports),
    ]
    for method, path, fn in routes:
        srv.route(method, path)(fn)
