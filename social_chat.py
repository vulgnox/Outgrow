"""
RAGDAMAXING social layer — realtime + channel chat API.

Registered from server.py with one call at the bottom:

    social_chat.install(sys.modules[__name__], social_db, social_perms)

Routes are additive. Channel messages live in the existing messages table under the
thread key ch:<channel_id>, except #general which maps to crew:<id> so the old room's
history is exactly the same conversation.
"""
import itertools
import json
import queue
import threading
import time

import social_assets as ASSETS
import social_friends
import social_media as MEDIA
import social_profiles as PROFILES
import social_voice

CORE = None
DB = None
PERMS = None

CHAT_EMOJIS = ["🔥", "💀", "😂", "👍", "❤️", "🫡", "💯", "😭", "🎉", "👀", "🙏", "💪"]
EDIT_WINDOW = 30 * 60

RATE = {}        # user_id -> [send timestamps]
TYPING = {}      # channel_id -> {user_id: last typing ts}
CLIENTS = {}     # connection id -> _Client
LOCK = threading.Lock()
_SEQ = itertools.count(1)


class _Client:
    __slots__ = ("uid", "q", "dead")

    def __init__(self, uid):
        self.uid = uid
        self.q = queue.Queue(maxsize=200)
        self.dead = False


# ----------------------------------------------------------------------------- helpers
def _ts():
    return CORE.now().isoformat(timespec="seconds")


def _as_int(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _boot(c):
    if c.user and c.user.get("crew_id"):
        DB.sync_crew(c.conn, c.user["crew_id"])


def _me(conn, u):
    out = {"id": u["id"], "display": u["display"], "emoji": u["emoji"], "color": u["color"],
           "av": u.get("av") or "", "fr": u.get("fr") or ""}
    p = conn.execute("SELECT * FROM profiles WHERE user_id=?", (u["id"],)).fetchone()
    if p:
        out.update(PROFILES.fields(p, u["id"]))
    return out


def _people(conn, sid):
    out = {}
    for r in conn.execute(
            """SELECT u.id, u.username, u.display, u.emoji, u.color, u.av, u.fr,
                      p.avatar_upload, p.status_text, p.status_emoji, p.status_ts
               FROM server_members m JOIN users u ON u.id=m.user_id
               LEFT JOIN profiles p ON p.user_id=u.id WHERE m.server_id=?""", (sid,)):
        d = {"username": r["username"], "display": r["display"], "emoji": r["emoji"],
             "color": r["color"], "av": r["av"] or "", "fr": r["fr"] or ""}
        d.update(PROFILES.fields(r))
        out[int(r["id"])] = d
    return out


def _read(conn, uid, thread):
    r = conn.execute("SELECT last_id FROM chat_reads WHERE user_id=? AND thread=?", (uid, thread)).fetchone()
    return int(r["last_id"] or 0) if r else 0


def _mark_read(conn, uid, thread, last_id):
    if not last_id:
        return
    conn.execute("""INSERT INTO chat_reads(user_id,thread,last_id) VALUES(?,?,?)
        ON CONFLICT(user_id,thread) DO UPDATE SET last_id=MAX(last_id, excluded.last_id)""",
                 (uid, thread, int(last_id)))


def _reads(conn, sid, thread):
    out = {}
    for r in conn.execute(
            """SELECT m.user_id, r.last_id FROM server_members m
               JOIN chat_reads r ON r.user_id=m.user_id AND r.thread=?
               WHERE m.server_id=?""", (thread, sid)):
        out[int(r["user_id"])] = int(r["last_id"] or 0)
    return out


def _reactions(conn, ids, uid):
    counts, mine = {}, {}
    if not ids:
        return counts, mine
    ph = ",".join("?" * len(ids))
    for r in conn.execute("SELECT msg_id,user_id,emoji FROM msg_reacts2 WHERE msg_id IN (%s)" % ph, list(ids)):
        d = counts.setdefault(int(r["msg_id"]), {})
        d[r["emoji"]] = d.get(r["emoji"], 0) + 1
        if int(r["user_id"]) == int(uid):
            mine.setdefault(int(r["msg_id"]), []).append(r["emoji"])
    return counts, mine


def _pack(conn, rows, uid):
    if not rows:
        return []
    counts, mine = _reactions(conn, [r["id"] for r in rows], uid)
    rids = sorted({int(r["reply_to"]) for r in rows if r["reply_to"]})
    refs = {}
    if rids:
        ph = ",".join("?" * len(rids))
        for r in conn.execute("SELECT id,sender,body,deleted,sticker FROM messages WHERE id IN (%s)" % ph, rids):
            refs[int(r["id"])] = r
    meta = MEDIA.msg_meta(conn, [int(r["id"]) for r in rows])
    out = []
    for r in rows:
        m = {"id": int(r["id"]), "uid": int(r["sender"]), "ts": r["ts"], "text": r["body"],
             "edited": bool(r["edited"]), "re": counts.get(int(r["id"]), {}), "mine": mine.get(int(r["id"]), [])}
        if r["sticker"]:
            m["sticker"] = r["sticker"]
        pv = MEDIA.parse_preview(r["preview"])
        if pv:
            m["preview"] = pv
        if meta.get(int(r["id"])):
            m["files"] = meta[int(r["id"])]
        ref = refs.get(int(r["reply_to"])) if r["reply_to"] else None
        if ref:
            label = "deleted message" if ref["deleted"] else (ref["body"] or ("sticker" if ref["sticker"] else "attachment"))
            m["reply"] = {"id": int(ref["id"]), "uid": int(ref["sender"]), "text": label[:90]}
        out.append(m)
    return out


def _fetch(conn, thread, after=0, before=0, around=0, limit=60):
    cols = "id,sender,ts,body,reply_to,edited,sticker,preview"
    if around:
        a = conn.execute("SELECT %s FROM messages WHERE thread=? AND id<=? AND deleted=0 ORDER BY id DESC LIMIT 25"
                         % cols, (thread, around)).fetchall()
        b = conn.execute("SELECT %s FROM messages WHERE thread=? AND id>? AND deleted=0 ORDER BY id LIMIT 25"
                         % cols, (thread, around)).fetchall()
        return list(reversed(a)) + list(b), True
    if after:
        rows = conn.execute("SELECT %s FROM messages WHERE thread=? AND id>? AND deleted=0 ORDER BY id LIMIT 200"
                            % cols, (thread, after)).fetchall()
        return rows, False
    rows = conn.execute("SELECT %s FROM messages WHERE thread=? AND id<? AND deleted=0 ORDER BY id DESC LIMIT ?"
                        % cols, (thread, before or 2 ** 62, limit + 1)).fetchall()
    return rows[:limit][::-1], len(rows) > limit


def _channel(c, ch_id, perm="view"):
    try:
        cid = int(ch_id)
    except (TypeError, ValueError):
        raise CORE.ApiError("bad channel", 400)
    ch = c.conn.execute("SELECT * FROM channels WHERE id=?", (cid,)).fetchone()
    if not ch:
        raise CORE.ApiError("No such channel", 404)
    if not PERMS.can(c.conn, c.user, ch["server_id"], perm, ch["id"]):
        # 404 for non-members, 403 for members who lack the bit: never confirm a channel exists
        if not PERMS.is_member(c.conn, c.user["id"], ch["server_id"]) and not PERMS.is_global_admin(c.user):
            raise CORE.ApiError("No such channel", 404)
        raise CORE.ApiError("You don't have permission to do that", 403)
    return ch


def _ch_json(ch):
    return {"id": int(ch["id"]), "server": int(ch["server_id"]), "name": ch["name"], "kind": ch["kind"],
            "topic": ch["topic"] or "", "pos": ch["pos"] or 0}


def _server_recipients(conn, sid):
    return set(DB.member_ids(conn, sid))


def _typing_list(ch_id, exclude):
    now = time.time()
    d = TYPING.get(int(ch_id), {})
    return [int(uid) for uid, ts in d.items() if now - ts < 6 and int(uid) != int(exclude)]


def _server_members_online(conn, uid, sid):
    return set(DB.member_ids(conn, sid)) | {uid}


# ----------------------------------------------------------------------------- SSE
def emit(event, data, users=None, exclude=None):
    """Push one event to live connections. Never blocks a request thread."""
    with LOCK:
        targets = list(CLIENTS.values())
    for cl in targets:
        if users is not None and cl.uid not in users:
            continue
        if exclude and cl.uid in exclude:
            continue
        try:
            cl.q.put_nowait((event, data))
        except queue.Full:
            cl.dead = True


def stream(c):
    """GET /api/stream — one EventSource per open tab, capped at 3 per user."""
    if not CORE:
        raise CORE.ApiError("social layer unavailable", 503)
    uid = int(c.user["id"])
    with LOCK:
        if sum(1 for x in CLIENTS.values() if x.uid == uid) >= 3:
            raise CORE.ApiError("Too many live connections (max 3). Close another tab.", 429)
        cid = next(_SEQ)
        cl = _Client(uid)
        CLIENTS[cid] = cl

    h = c.h
    h.send_response(200)
    h.send_header("Content-Type", "text/event-stream; charset=utf-8")
    h.send_header("Cache-Control", "no-cache, no-store, no-transform")
    h.send_header("Connection", "keep-alive")
    h.send_header("X-Accel-Buffering", "no")
    h.end_headers()

    def write(chunk):
        h.wfile.write(chunk.encode("utf-8"))
        h.wfile.flush()

    peers = set()
    try:
        write("retry: 3000\n\n")
        write("event: hello\ndata: %s\n\n" % json.dumps({"uid": uid, "ts": _ts()}, ensure_ascii=False))

        sids = [int(r[0]) for r in c.conn.execute("SELECT server_id FROM server_members WHERE user_id=?", (uid,)).fetchall()]
        peers = set()
        for sid in sids:
            peers |= set(DB.member_ids(c.conn, sid))
        if peers:
            emit("presence", {"uid": uid, "name": c.user["display"], "online": True}, peers, exclude={uid})

        while not cl.dead:
            try:
                ev, data = cl.q.get(timeout=20)
            except queue.Empty:
                write(": hb %s\n\n" % _ts())
                continue
            write("id: %s\nevent: %s\ndata: %s\n\n" % (next(_SEQ), ev, json.dumps(data, ensure_ascii=False)))
    except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError):
        pass
    finally:
        with LOCK:
            CLIENTS.pop(cid, None)
            left = sum(1 for x in CLIENTS.values() if x.uid == uid)
        if not left:
            social_voice.disconnect(uid)
            if peers:
                emit("presence", {"uid": uid, "name": c.user["display"], "online": False}, peers, exclude={uid})


# ----------------------------------------------------------------------------- API: servers + channels
def api_servers(c):
    _boot(c)
    conn, u = c.conn, c.user
    sids = [int(r[0]) for r in conn.execute("SELECT server_id FROM server_members WHERE user_id=? ORDER BY server_id",
                                           (u["id"],)).fetchall()]
    servers, people = [], {}
    for sid in sids:
        srv = conn.execute("SELECT * FROM servers WHERE id=?", (sid,)).fetchone()
        if not srv:
            continue
        chans, total_unread = [], 0
        for ch in DB.channel_rows(conn, sid):
            th = DB.thread_of(ch)
            last = conn.execute("SELECT id,sender,ts,body FROM messages WHERE thread=? AND deleted=0 ORDER BY id DESC LIMIT 1",
                                (th,)).fetchone()
            unread = conn.execute("SELECT COUNT(*) FROM messages WHERE thread=? AND id>? AND deleted=0 AND sender<>?",
                                  (th, _read(conn, u["id"], th), u["id"])).fetchone()[0]
            total_unread += int(unread)
            chans.append({
                "id": int(ch["id"]), "name": ch["name"], "kind": ch["kind"], "topic": ch["topic"] or "",
                "pos": ch["pos"] or 0, "unread": int(unread),
                "last": ({"id": int(last["id"]), "uid": int(last["sender"]), "ts": last["ts"],
                          "text": (last["body"] or "")[:80]} if last else None),
            })
        people.update(_people(conn, sid))
        perms = PERMS.perms_of(conn, u["id"], sid)
        if srv["owner"] and int(srv["owner"]) == int(u["id"]):
            perms = PERMS.ALL
        servers.append({
            "id": sid, "name": srv["name"], "icon": srv["icon"] or "", "owner": int(srv["owner"] or 0),
            "legacy": bool(srv["legacy"]), "channels": chans, "unread": total_unread,
            "members": DB.member_count(conn, sid), "perms": perms,
        })

    dms, seen_uids = [], set()
    legacy_unread = {}
    blocked = social_friends.block_set(conn, u["id"])
    if u.get("crew_id"):
        legacy_unread = CORE.chat_unread(conn, u)
        for m in conn.execute("""SELECT u.id,u.display,u.emoji,u.color,u.av,u.fr,
                p.avatar_upload,p.status_text,p.status_emoji,p.status_ts
                FROM users u LEFT JOIN profiles p ON p.user_id=u.id
                WHERE u.crew_id=? AND u.id<>? ORDER BY u.display COLLATE NOCASE""", (u["crew_id"], u["id"])).fetchall():
            seen_uids.add(int(m["id"]))
            if int(m["id"]) in blocked:
                continue
            d = {"id": int(m["id"]), "display": m["display"], "emoji": m["emoji"], "color": m["color"],
                 "av": m["av"] or "", "fr": m["fr"] or "", "unread": int(legacy_unread.get("dm:%s" % m["id"], 0))}
            d.update(PROFILES.fields(m))
            dms.append(d)
    for fid in sorted(social_friends.friends_of(conn, u["id"])):
        if fid in seen_uids or fid in blocked:
            continue
        m = conn.execute("""SELECT u.id,u.display,u.emoji,u.color,u.av,u.fr,
                p.avatar_upload,p.status_text,p.status_emoji,p.status_ts
                FROM users u LEFT JOIN profiles p ON p.user_id=u.id WHERE u.id=?""", (fid,)).fetchone()
        if not m:
            continue
        d = {"id": int(m["id"]), "display": m["display"], "emoji": m["emoji"], "color": m["color"],
             "av": m["av"] or "", "fr": m["fr"] or "", "unread": int(legacy_unread.get("dm:%s" % m["id"], 0))}
        d.update(PROFILES.fields(m))
        dms.append(d)

    return {"servers": servers, "people": people, "dms": dms, "me": _me(conn, u),
            "unread": sum(s["unread"] for s in servers) + sum(d["unread"] for d in dms)}


def api_channel_messages(c):
    _boot(c)
    conn, u = c.conn, c.user
    ch = _channel(c, CORE.qpi(c, "ch"), "view")
    th = DB.thread_of(ch)
    after, before, around = CORE.qpi(c, "after"), CORE.qpi(c, "before"), CORE.qpi(c, "around")
    first = CORE.qpi(c, "first")
    rows, more = _fetch(conn, th, after, before, around)
    blocked = social_friends.block_set(conn, u["id"])
    if blocked:
        rows = [r for r in rows if int(r["sender"]) not in blocked]
    if CORE.qp(c, "mark") == "1" and rows:
        _mark_read(conn, u["id"], th, rows[-1]["id"])
    deleted = []
    if first:
        deleted = [int(r[0]) for r in conn.execute(
            "SELECT id FROM messages WHERE thread=? AND deleted=1 AND id>=? ORDER BY id DESC LIMIT 100",
            (th, first)).fetchall()]
    return {
        "channel": _ch_json(ch), "messages": _pack(conn, rows, u["id"]), "more": more, "deleted": deleted,
        "people": _people(conn, ch["server_id"]), "me": _me(conn, u), "thread": th,
        "reads": _reads(conn, ch["server_id"], th), "typing": _typing_list(ch["id"], u["id"]),
    }


def api_send(c):
    _boot(c)
    conn, u = c.conn, c.user
    ch = _channel(c, c.body.get("ch"), "send")
    th = DB.thread_of(ch)
    sticker = str(c.body.get("sticker") or "")[:40]
    files = c.body.get("files") or []
    if sticker and sticker not in MEDIA.STICKER_BY_ID and not ASSETS.sticker_ok(conn, ch["server_id"], sticker):
        raise CORE.ApiError("Unknown sticker")
    if sticker and sticker not in MEDIA.STICKER_BY_ID and not PERMS.can(conn, u, ch["server_id"], "attach", ch["id"]):
        raise CORE.ApiError("You can't send custom stickers here", 403)
    if files and not PERMS.can(conn, u, ch["server_id"], "attach", ch["id"]):
        raise CORE.ApiError("You can't attach files here", 403)
    raw = str(c.body.get("text") or "")
    if not raw.strip() and not sticker and not files:
        raise CORE.ApiError("Say something first")
    text = CORE.chat_clean(raw) if raw.strip() else ""
    now = time.time()
    recent = [t for t in RATE.get(u["id"], []) if now - t < 10]
    if len(recent) >= 10:
        raise CORE.ApiError("Slow down 😅", 429)
    RATE[u["id"]] = recent + [now]

    reply_to = None
    rid = _as_int(c.body.get("reply_to"))
    if rid and conn.execute("SELECT 1 FROM messages WHERE id=? AND thread=? AND deleted=0", (rid, th)).fetchone():
        reply_to = rid

    preview = MEDIA.preview_for(conn, text) if text else ""
    cur = conn.execute("INSERT INTO messages(thread,sender,recip,ts,body,reply_to,sticker,preview) VALUES(?,?,NULL,?,?,?,?,?)",
                       (th, u["id"], _ts(), text, reply_to, sticker, preview))
    mid = cur.lastrowid
    MEDIA.attach(conn, u["id"], th, mid, files)
    _mark_read(conn, u["id"], th, mid)
    row = conn.execute("SELECT id,sender,ts,body,reply_to,edited,sticker,preview FROM messages WHERE id=?", (mid,)).fetchone()
    msg = _pack(conn, [row], u["id"])[0]
    conn.commit()
    emit("msg", {"ch": int(ch["id"]), "message": msg}, _server_recipients(conn, ch["server_id"]))
    return {"message": msg}


def api_edit(c):
    _boot(c)
    conn, u = c.conn, c.user
    ch = _channel(c, c.body.get("ch"), "send")
    th = DB.thread_of(ch)
    mid = CORE.need(c, "id", int)
    m = conn.execute("SELECT id,sender,ts,deleted FROM messages WHERE id=? AND thread=?", (mid, th)).fetchone()
    if not m or m["deleted"]:
        raise CORE.ApiError("No such message", 404)
    if int(m["sender"]) != int(u["id"]):
        raise CORE.ApiError("You can only edit your own messages", 403)
    try:
        age = (CORE.now() - CORE.dt.datetime.fromisoformat(m["ts"])).total_seconds()
    except Exception:
        age = 0
    if age > EDIT_WINDOW:
        raise CORE.ApiError("Too late to edit (30 min window)")
    text = CORE.chat_clean(c.body.get("text"))
    conn.execute("UPDATE messages SET body=?, edited=1 WHERE id=?", (text, mid))
    conn.commit()
    emit("edit", {"ch": int(ch["id"]), "id": int(mid), "text": text}, _server_recipients(conn, ch["server_id"]))
    return {"ok": True, "text": text}


def api_delete(c):
    _boot(c)
    conn, u = c.conn, c.user
    ch = _channel(c, c.body.get("ch"), "view")
    th = DB.thread_of(ch)
    mid = CORE.need(c, "id", int)
    m = conn.execute("SELECT id,sender FROM messages WHERE id=? AND thread=? AND deleted=0", (mid, th)).fetchone()
    if not m:
        raise CORE.ApiError("No such message", 404)
    own = int(m["sender"]) == int(u["id"])
    if not own and not PERMS.can(conn, u, ch["server_id"], "delete_messages", ch["id"]):
        raise CORE.ApiError("You can't delete that message", 403)
    conn.execute("UPDATE messages SET deleted=1, body='' WHERE id=?", (mid,))
    if not own:
        PERMS.audit(conn, ch["server_id"], u["id"], "message.delete", "msg %s" % mid)
    conn.commit()
    emit("del", {"ch": int(ch["id"]), "ids": [int(mid)]}, _server_recipients(conn, ch["server_id"]))
    return {"ok": True}


def api_react(c):
    _boot(c)
    conn, u = c.conn, c.user
    ch = _channel(c, c.body.get("ch"), "react")
    th = DB.thread_of(ch)
    mid = CORE.need(c, "id", int)
    e = str(c.body.get("emoji") or "")
    if e not in CHAT_EMOJIS and not ASSETS.reaction_ok(conn, ch["server_id"], e):
        raise CORE.ApiError("bad emoji")
    m = conn.execute("SELECT sender FROM messages WHERE id=? AND thread=? AND deleted=0", (mid, th)).fetchone()
    if not m:
        raise CORE.ApiError("No such message", 404)
    if social_friends.blocked_by(conn, int(m["sender"]), u["id"]):
        raise CORE.ApiError("No such message", 404)
    cur = conn.execute("SELECT 1 FROM msg_reacts2 WHERE msg_id=? AND user_id=? AND emoji=?", (mid, u["id"], e)).fetchone()
    if cur:
        conn.execute("DELETE FROM msg_reacts2 WHERE msg_id=? AND user_id=? AND emoji=?", (mid, u["id"], e))
    else:
        conn.execute("INSERT OR IGNORE INTO msg_reacts2(msg_id,user_id,emoji) VALUES(?,?,?)", (mid, u["id"], e))
    conn.commit()
    counts, mine = _reactions(conn, [mid], u["id"])
    emit("react", {"ch": int(ch["id"]), "id": int(mid), "re": counts.get(int(mid), {})},
         _server_recipients(conn, ch["server_id"]))
    return {"ok": True, "re": counts.get(int(mid), {}), "mine": mine.get(int(mid), [])}


def api_typing(c):
    _boot(c)
    ch = _channel(c, c.body.get("ch"), "send")
    uid = int(c.user["id"])
    TYPING.setdefault(int(ch["id"]), {})[uid] = time.time()
    emit("typing", {"ch": int(ch["id"]), "uid": uid, "name": c.user["display"]},
         _server_recipients(c.conn, ch["server_id"]), exclude={uid})
    return {"ok": True}


def api_read(c):
    _boot(c)
    ch = _channel(c, c.body.get("ch"), "view")
    mid = CORE.need(c, "id", int)
    _mark_read(c.conn, c.user["id"], DB.thread_of(ch), mid)
    c.conn.commit()
    emit("read", {"ch": int(ch["id"]), "uid": int(c.user["id"]), "id": mid},
         _server_recipients(c.conn, ch["server_id"]))
    return {"ok": True}


def api_search(c):
    _boot(c)
    ch = _channel(c, CORE.qpi(c, "ch"), "view")
    q = str(CORE.qp(c, "q") or "").strip()[:80]
    if len(q) < 2:
        return {"results": [], "q": q}
    like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    rows = c.conn.execute("""SELECT id,sender,ts,body FROM messages
        WHERE thread=? AND deleted=0 AND body LIKE ? ESCAPE '\\' ORDER BY id DESC LIMIT 40""",
                          (DB.thread_of(ch), like)).fetchall()
    return {"results": [{"id": int(r["id"]), "uid": int(r["sender"]), "ts": r["ts"], "text": r["body"]} for r in rows],
            "q": q, "channel": _ch_json(ch)}


def api_unread(c):
    _boot(c)
    conn, u = c.conn, c.user
    counts, total = {}, 0
    for ch in conn.execute("""SELECT c.* FROM channels c JOIN server_members m ON m.server_id=c.server_id
            WHERE m.user_id=? ORDER BY c.server_id, c.pos""", (u["id"],)).fetchall():
        th = DB.thread_of(ch)
        n = conn.execute("SELECT COUNT(*) FROM messages WHERE thread=? AND id>? AND deleted=0 AND sender<>?",
                         (th, _read(conn, u["id"], th), u["id"])).fetchone()[0]
        counts[str(ch["id"])] = int(n)
        total += int(n)
    return {"total": total, "ch": counts}


# ----------------------------------------------------------------------------- installation
def install(srv, db, permissions):
    global CORE, DB, PERMS
    CORE, DB, PERMS = srv, db, permissions
    permissions.install(srv)
    srv.route("GET", "/api/servers")(api_servers)
    srv.route("GET", "/api/ch/messages")(api_channel_messages)
    srv.route("POST", "/api/ch/send")(api_send)
    srv.route("POST", "/api/ch/edit")(api_edit)
    srv.route("POST", "/api/ch/delete")(api_delete)
    srv.route("POST", "/api/ch/react")(api_react)
    srv.route("POST", "/api/ch/typing")(api_typing)
    srv.route("POST", "/api/ch/read")(api_read)
    srv.route("GET", "/api/ch/search")(api_search)
    srv.route("GET", "/api/ch/unread")(api_unread)
    ASSETS.install(srv, CORE, DB, PERMS, MEDIA, emit)
    stream.sse = True
    srv.ROUTES[("GET", "/api/stream")] = (stream, True)
