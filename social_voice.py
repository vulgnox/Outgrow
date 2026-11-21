"""
RAGDAMAXING social layer — voice rooms.

Voice is a peer-to-peer WebRTC mesh. This module owns only the room state and the
signaling relay: clients exchange SDP offers/answers and ICE candidates through
the existing /api/stream EventSource, so there is no websocket server to run.

Every route resolves the channel through social_chat._channel(), which enforces
server membership and the voice permission bit (including timeouts). Signals are
only relayed between two people currently in the same voice room, payloads are
size-capped, and joins are capped at MAX_ROOM peers.
"""
import base64
import hashlib
import hmac
import json
import os
import threading
import time

import social_profiles as PROFILES

CORE = DB = PERMS = CHAT = None

MAX_ROOM = 8              # mesh peers: 8 people = at most 7 connections per client
STALE = 45.0              # no heartbeat for this long = drop from the room
SIGNAL_RATE = 120         # signals per 10 minutes per user
SIGNAL_MAX = 32 * 1024
try:
    SCREEN_MAX = max(1, min(MAX_ROOM, int(os.environ.get("RAGDAMAXING_SCREEN_MAX_VIEWERS", "3"))))
except ValueError:
    SCREEN_MAX = 3
SPEAK_GAP = 0.20

TURN_URLS = [u.strip() for u in os.environ.get("TURN_URLS", "").split(",") if u.strip()]
TURN_SECRET = os.environ.get("TURN_SECRET", "")

LOCK = threading.RLock()
ROOMS = {}                # ch_id -> {uid: participant dict}
MY_ROOM = {}              # uid -> ch_id
RATE = {}                 # uid -> [signal timestamps]


def _now():
    return time.time()


def _voice_channel(c, ch_id, perm="view"):
    ch = CHAT._channel(c, ch_id, perm)
    if ch["kind"] != "voice":
        raise CORE.ApiError("That is not a voice channel", 400)
    return ch


def _rate(uid):
    now = _now()
    recent = [t for t in RATE.get(uid, []) if now - t < 600]
    if len(recent) >= SIGNAL_RATE:
        raise CORE.ApiError("Voice signaling is too fast", 429)
    RATE[uid] = recent + [now]


def _user_card(conn, uid):
    r = conn.execute(
        """SELECT u.id,u.display,u.emoji,u.color,u.av,u.fr,
                  p.avatar_upload,p.status_text,p.status_emoji,p.status_ts
           FROM users u LEFT JOIN profiles p ON p.user_id=u.id WHERE u.id=?""", (int(uid),)).fetchone()
    if not r:
        return None
    d = {"uid": int(r["id"]), "name": r["display"], "emoji": r["emoji"], "color": r["color"],
         "av": r["av"] or "", "fr": r["fr"] or ""}
    d.update(PROFILES.fields(r))
    return d


def _ice(uid):
    """ICE servers for a member. TURN credentials are short-lived and signed server-side."""
    servers = [{"urls": "stun:stun.l.google.com:19302"}]
    if TURN_URLS and TURN_SECRET:
        expiry = int(_now()) + 3600
        username = "%d:%d" % (expiry, int(uid))
        digest = hmac.new(TURN_SECRET.encode("utf-8"), username.encode("utf-8"), hashlib.sha1).digest()
        servers.append({
            "urls": TURN_URLS,
            "username": username,
            "credential": base64.b64encode(digest).decode("ascii"),
        })
    return servers


def _card(uid, p):
    return {"uid": int(uid), "name": p["name"], "emoji": p["emoji"], "color": p["color"],
            "av": p["av"], "fr": p["fr"], "pimg": p["pimg"],
            "muted": bool(p["muted"]), "deafened": bool(p["deafened"]),
            "speaking": bool(p["speaking"]), "screen": bool(p.get("screen")),
            "joined": p["joined"]}


def _emit(ch_id, data, exclude=None):
    with LOCK:
        users = set(ROOMS.get(int(ch_id), {}))
    if exclude:
        users -= set(exclude)
    if users and CHAT:
        CHAT.emit("voice", data, users)


def room_uids(ch_id):
    """Snapshot of who is currently seated in a voice room."""
    with LOCK:
        return set(ROOMS.get(int(ch_id), {}))


def _remove(uid, notify=True):
    uid = int(uid)
    with LOCK:
        ch_id = MY_ROOM.pop(uid, None)
        if not ch_id:
            return 0
        room = ROOMS.get(ch_id)
        if room:
            room.pop(uid, None)
            users = set(room)
            if not room:
                ROOMS.pop(ch_id, None)
        else:
            users = set()
    if notify and users and CHAT:
        CHAT.emit("voice", {"type": "leave", "ch": int(ch_id), "uid": uid}, users)
    if not users:
        try:
            import social_music
            social_music.on_empty(ch_id)
        except Exception:
            pass
    return int(ch_id)


def disconnect(uid):
    """Called when a user's last SSE connection closes: drop their voice seat."""
    try:
        _remove(int(uid))
    except Exception:
        pass


def drop_channel(ch_id):
    """A channel or server was deleted: remove its room without relaying to a dead channel."""
    ch_id = int(ch_id)
    with LOCK:
        room = ROOMS.pop(ch_id, {})
        for uid in list(room):
            if MY_ROOM.get(int(uid)) == ch_id:
                MY_ROOM.pop(int(uid), None)
    try:
        import social_music
        social_music.drop(ch_id)
    except Exception:
        pass


def drop_server(conn, sid):
    try:
        for r in conn.execute("SELECT id FROM channels WHERE server_id=?", (int(sid),)).fetchall():
            drop_channel(int(r["id"]))
    except Exception:
        pass


def _prune(conn, ch):
    """Drop silent seats and anyone who lost membership or voice permission."""
    ch_id = int(ch["id"])
    with LOCK:
        room = dict(ROOMS.get(ch_id, {}))
    now = _now()
    dead = []
    for uid, p in room.items():
        if now - float(p["seen"]) > STALE:
            dead.append(int(uid))
            continue
        row = conn.execute("SELECT * FROM users WHERE id=?", (int(uid),)).fetchone()
        if not row or not PERMS.can(conn, row, ch["server_id"], "voice", ch_id):
            dead.append(int(uid))
    for uid in dead:
        _remove(uid)
    with LOCK:
        return ROOMS.get(ch_id, {})


def api_room(c):
    ch = _voice_channel(c, CORE.qpi(c, "ch"), "view")
    room = _prune(c.conn, ch)
    with LOCK:
        parts = [_card(uid, p) for uid, p in sorted(room.items(), key=lambda x: x[1]["joined"])]
        mine = int(c.user["id"]) in room
    return {"ch": int(ch["id"]), "name": ch["name"], "server": int(ch["server_id"]),
            "participants": parts, "self": mine, "max": MAX_ROOM, "screen_max": SCREEN_MAX}


def api_join(c):
    CHAT._boot(c)
    ch = _voice_channel(c, CORE.qp(c, "ch") or c.body.get("ch"), "voice")
    ch_id, uid = int(ch["id"]), int(c.user["id"])
    _prune(c.conn, ch)
    with LOCK:
        room = ROOMS.get(ch_id, {})
        if uid not in room and len(room) >= MAX_ROOM:
            raise CORE.ApiError("This voice room is full (%d max)" % MAX_ROOM, 429)
    old = MY_ROOM.get(uid)
    if old and int(old) != ch_id:
        _remove(uid)

    card = _user_card(c.conn, uid)
    if not card:
        raise CORE.ApiError("No such member", 404)
    now = _now()
    with LOCK:
        room = ROOMS.setdefault(ch_id, {})
        p = room.get(uid)
        fresh = p is None
        if fresh:
            p = {"name": card["name"], "emoji": card["emoji"], "color": card["color"],
                 "av": card["av"], "fr": card["fr"], "pimg": card["pimg"],
                 "muted": False, "deafened": False, "speaking": False, "screen": False,
                 "joined": now, "seen": now, "speak_ts": 0}
            room[uid] = p
            MY_ROOM[uid] = ch_id
        else:
            p["seen"] = now
        parts = [_card(x, q) for x, q in sorted(room.items(), key=lambda x: x[1]["joined"])]
    if fresh:
        _emit(ch_id, {"type": "join", "ch": ch_id, "user": _card(uid, p)}, exclude={uid})
    try:
        import social_music
        music = social_music.snapshot(ch_id)
    except Exception:
        music = None
    return {"ch": ch_id, "name": ch["name"], "participants": parts, "self": True, "max": MAX_ROOM,
            "screen_max": SCREEN_MAX, "ice": _ice(uid), "music": music}


def api_leave(c):
    ch_id = CORE.qpi(c, "ch") or 0
    uid = int(c.user["id"])
    if MY_ROOM.get(uid) and (not ch_id or int(MY_ROOM[uid]) == int(ch_id)):
        _remove(uid)
    return {"ok": True}


def api_state(c):
    ch = _voice_channel(c, CORE.qp(c, "ch") or c.body.get("ch"), "voice")
    ch_id, uid = int(ch["id"]), int(c.user["id"])
    room = _prune(c.conn, ch)
    with LOCK:
        p = room.get(uid)
        if not p:
            raise CORE.ApiError("Join the voice channel first", 400)
        if "screen" in c.body:
            sharing = bool(c.body.get("screen"))
            if sharing and any(int(x) != uid and q.get("screen") for x, q in room.items()):
                raise CORE.ApiError("Someone else is already sharing their screen", 409)
            p["screen"] = sharing
        p["muted"] = bool(c.body.get("muted"))
        p["deafened"] = bool(c.body.get("deafened"))
        if p["deafened"]:
            p["muted"] = True
        if p["muted"]:
            p["speaking"] = False
        p["seen"] = _now()
        data = {"type": "state", "ch": ch_id, "uid": uid, "muted": p["muted"],
                "deafened": p["deafened"], "speaking": p["speaking"],
                "screen": bool(p.get("screen"))}
    CHAT.emit("voice", data, set(room))
    return {"ok": True, "muted": p["muted"], "deafened": p["deafened"],
            "screen": bool(p.get("screen"))}


def api_speaking(c):
    ch = _voice_channel(c, CORE.qp(c, "ch") or c.body.get("ch"), "voice")
    ch_id, uid = int(ch["id"]), int(c.user["id"])
    room = _prune(c.conn, ch)
    now = _now()
    with LOCK:
        p = room.get(uid)
        if not p:
            raise CORE.ApiError("Join the voice channel first", 400)
        p["seen"] = now
        if now - float(p.get("speak_ts") or 0) < SPEAK_GAP:
            return {"ok": True}
        p["speak_ts"] = now
        on = bool(c.body.get("on")) and not p["muted"]
        if bool(p["speaking"]) == on:
            return {"ok": True}
        p["speaking"] = on
    CHAT.emit("voice", {"type": "speaking", "ch": ch_id, "uid": uid, "on": on}, set(room))
    return {"ok": True, "speaking": on}


def api_signal(c):
    ch = _voice_channel(c, CORE.qp(c, "ch") or c.body.get("ch"), "voice")
    ch_id, uid = int(ch["id"]), int(c.user["id"])
    try:
        to = int(c.body.get("to") or 0)
    except (TypeError, ValueError):
        raise CORE.ApiError("bad voice target", 400)
    if not to or to == uid:
        raise CORE.ApiError("bad voice target", 400)
    room = _prune(c.conn, ch)
    with LOCK:
        if uid not in room:
            raise CORE.ApiError("Join the voice channel first", 400)
        if to not in room:
            raise CORE.ApiError("They are not in this voice room", 400)
        room[uid]["seen"] = _now()

    kind = str(c.body.get("kind") or "")
    payload = c.body.get("payload")
    if kind not in ("offer", "answer", "ice", "lower", "preset") or not isinstance(payload, dict):
        raise CORE.ApiError("bad voice signal", 400)
    if kind in ("offer", "answer"):
        if payload.get("type") != kind or not isinstance(payload.get("sdp"), str) or not payload["sdp"]:
            raise CORE.ApiError("bad voice signal", 400)
    elif kind == "lower":
        pass  # viewer asks the sharer for a lower preset; no extra payload needed
    elif kind == "preset":
        if not isinstance(payload.get("preset"), str) or len(payload["preset"]) > 24:
            raise CORE.ApiError("bad voice signal", 400)
    elif not isinstance(payload.get("candidate"), str):
        raise CORE.ApiError("bad voice signal", 400)
    if len(json.dumps(payload, separators=(",", ":"))) > SIGNAL_MAX:
        raise CORE.ApiError("Voice signal too large", 413)
    _rate(uid)
    CHAT.emit("voice", {"type": "signal", "ch": ch_id, "from": uid, "kind": kind, "payload": payload}, {to})
    return {"ok": True}


def api_ping(c):
    uid = int(c.user["id"])
    ch_id = MY_ROOM.get(uid)
    if ch_id:
        with LOCK:
            p = ROOMS.get(int(ch_id), {}).get(uid)
            if p:
                p["seen"] = _now()
    return {"ok": True, "ch": int(ch_id or 0)}


def install(srv, db, permissions, chat):
    global CORE, DB, PERMS, CHAT
    CORE, DB, PERMS, CHAT = srv, db, permissions, chat
    for method, path, fn in (
        ("GET", "/api/voice", api_room),
        ("POST", "/api/voice/join", api_join),
        ("POST", "/api/voice/leave", api_leave),
        ("POST", "/api/voice/state", api_state),
        ("POST", "/api/voice/speaking", api_speaking),
        ("POST", "/api/voice/signal", api_signal),
        ("POST", "/api/voice/ping", api_ping),
    ):
        srv.route(method, path)(fn)
