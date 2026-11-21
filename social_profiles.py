"""
RAGDAMAXING social layer — profiles, avatars, banners and custom status.

A profile is readable only by its owner, a global admin, or someone the owner can
already DM (friend, shared server or same crew without a block). Every route goes
through that one check. Avatar/banner images are stored in the existing uploads
table under the private scope profile:<uid>, never attached to a message, and are
served only through the same visibility check.

Everything is stdlib and image bytes are sniffed, never trusted from the client.
"""
import hashlib
import os
import re
import time

import social_friends as FRIENDS
import social_media as MEDIA

CORE = DB = PERMS = None

MAX_AVATAR = 2 * 1024 * 1024
MAX_BANNER = 4 * 1024 * 1024
MAX_AVATAR_DIM = 1024
MAX_BANNER_DIM = 4096
MAX_STATUS = 80
MAX_EMOJI = 16
MAX_BIO = 160
MAX_PRONOUNS = 24
BANNER_STYLES = ("none", "aurora", "sunset", "mint", "mono", "blossom")
STATUS_RATE = 30
MEDIA_RATE = 20
RATE = {}
KINDS = ("avatar", "banner")


def _ts():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _rate(key, limit, window=600):
    now = time.time()
    recent = [t for t in RATE.get(key, []) if now - t < window]
    if len(recent) >= limit:
        raise CORE.ApiError("Slow down a second", 429)
    RATE[key] = recent + [now]


def _clean(v, limit=1000):
    s = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", str(v or ""))
    return re.sub(r"\s+", " ", s).strip()[:limit]


def img_url(uid, up):
    """Public URL for one profile image. Versioned by upload id so a new upload busts caches."""
    try:
        up = int(up or 0)
    except (TypeError, ValueError):
        up = 0
    return "/api/profile/img?uid=%d&kind=avatar&v=%d" % (int(uid), up) if up else ""


def _media_url(conn, uid, kind, up):
    """Only produce a URL when the upload row still exists and belongs to this user."""
    if not up:
        return ""
    row = conn.execute("SELECT id,disk FROM uploads WHERE id=? AND owner=? AND scope=?",
                       (int(up), int(uid), "profile:%d" % int(uid))).fetchone()
    if not row or not row["disk"]:
        return ""
    return "/api/profile/img?uid=%d&kind=%s&v=%d" % (int(uid), kind, int(up))


def status_json(text, emoji, ts=0):
    text = _clean(text, MAX_STATUS)
    emoji = _clean(emoji, MAX_EMOJI)
    if not text and not emoji:
        return {}
    return {"text": text, "emoji": emoji, "ts": float(ts or 0)}


def fields(row, uid=None):
    """Profile fields for a user card row that was LEFT JOINed with profiles."""
    try:
        up = row["avatar_upload"]
        st = status_json(row["status_text"], row["status_emoji"], row["status_ts"])
    except (KeyError, IndexError):
        up, st = 0, {}
    out = {"pimg": img_url(uid or row["id"], up)}
    if st:
        out["status"] = st
    return out


def can_view(conn, me, uid):
    """Owner, global admin, or a person the owner can DM. Blocks win over everything."""
    try:
        uid = int(uid)
    except (TypeError, ValueError):
        return False
    if not me or not uid:
        return False
    if int(me["id"]) == uid:
        return True
    if PERMS.is_global_admin(me):
        return True
    if FRIENDS.blocked_either(conn, me["id"], uid):
        return False
    return (FRIENDS.are_friends(conn, me["id"], uid)
            or FRIENDS.share_server(conn, me["id"], uid)
            or FRIENDS.same_crew(conn, me["id"], uid))


def social_card(conn, uid, viewer=None):
    """One profile's social block. Shared servers are relative to the viewer."""
    uid = int(uid)
    p = conn.execute("SELECT * FROM profiles WHERE user_id=?", (uid,)).fetchone()
    u = conn.execute("SELECT created_at FROM users WHERE id=?", (uid,)).fetchone()
    out = {"avatar": "", "banner": "", "status": {}, "since": (u["created_at"] or "")[:10] if u else "",
           "bio": "", "pronouns": "", "banner_style": "",
           "friend": False, "can_message": False, "shared": []}
    if p:
        out["avatar"] = _media_url(conn, uid, "avatar", p["avatar_upload"])
        out["banner"] = _media_url(conn, uid, "banner", p["banner_upload"])
        out["status"] = status_json(p["status_text"], p["status_emoji"], p["status_ts"])
        out["bio"] = p["bio"] or ""
        out["pronouns"] = p["pronouns"] or ""
        out["banner_style"] = p["banner_style"] or ""
    if viewer:
        viewer = int(viewer)
        out["friend"] = FRIENDS.are_friends(conn, viewer, uid)
        out["can_message"] = viewer != uid and FRIENDS.can_dm(conn, viewer, uid)
        if viewer != uid:
            out["shared"] = [r["name"] for r in conn.execute(
                """SELECT s.name FROM servers s
                   JOIN server_members a ON a.server_id=s.id AND a.user_id=?
                   JOIN server_members b ON b.server_id=s.id AND b.user_id=?
                   ORDER BY s.name COLLATE NOCASE LIMIT 12""", (viewer, uid)).fetchall()]
    return out


def profile_social(c, uid):
    conn, me = c.conn, c.user
    u = conn.execute("SELECT id,username,display,emoji,color,av,fr,identity FROM users WHERE id=?", (int(uid),)).fetchone()
    if not u or not can_view(conn, me, uid):
        raise CORE.ApiError("No such member", 404)
    social = social_card(conn, uid, me["id"])
    card = {"id": int(u["id"]), "username": u["username"], "display": u["display"], "emoji": u["emoji"],
            "color": u["color"], "av": u["av"] or "", "fr": u["fr"] or "", "pimg": social["avatar"],
            "identity": u["identity"] or "", "me": int(uid) == int(me["id"])}
    return {"user": card, "social": social}


# --------------------------------------------------------------------- API
def api_profile_social(c):
    return profile_social(c, CORE.qpi(c, "uid"))


def api_status(c):
    conn, u = c.conn, c.user
    raw = str(c.body.get("text") or "")
    emoji = str(c.body.get("emoji") or "")
    text = _clean(raw)
    emoji = _clean(emoji, MAX_EMOJI * 2)
    if len(text) > MAX_STATUS:
        raise CORE.ApiError("Status is %d characters max" % MAX_STATUS)
    if len(emoji) > MAX_EMOJI:
        raise CORE.ApiError("That emoji is too long")
    _rate("status:%d" % u["id"], STATUS_RATE)
    if text or emoji:
        ts = time.time()
    else:
        ts = 0
    conn.execute("""INSERT INTO profiles(user_id,status_text,status_emoji,status_ts,updated_at)
        VALUES(?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET
        status_text=excluded.status_text, status_emoji=excluded.status_emoji,
        status_ts=excluded.status_ts, updated_at=excluded.updated_at""",
                 (u["id"], text, emoji, ts, _ts()))
    conn.commit()
    return {"ok": True, "social": social_card(conn, u["id"], u["id"])}


def api_details(c):
    """Bio, pronouns and a banner gradient for the owner's own profile."""
    conn, u = c.conn, c.user
    b = c.body or {}
    bio = _clean(b.get("bio") or "", MAX_BIO + 20)
    pronouns = _clean(b.get("pronouns") or "", MAX_PRONOUNS + 8)
    style = str(b.get("banner_style") or "").strip().lower()
    if len(bio) > MAX_BIO:
        raise CORE.ApiError("Bio is %d characters max" % MAX_BIO)
    if len(pronouns) > MAX_PRONOUNS:
        raise CORE.ApiError("Pronouns are %d characters max" % MAX_PRONOUNS)
    if style and style not in BANNER_STYLES:
        raise CORE.ApiError("Pick one of the banner styles")
    _rate("details:%d" % u["id"], STATUS_RATE)
    conn.execute("""INSERT INTO profiles(user_id,bio,pronouns,banner_style,updated_at)
        VALUES(?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET
        bio=excluded.bio, pronouns=excluded.pronouns, banner_style=excluded.banner_style,
        updated_at=excluded.updated_at""",
                 (u["id"], bio, pronouns, style, _ts()))
    conn.commit()
    return {"ok": True, "social": social_card(conn, u["id"], u["id"])}


def _kind(c):
    kind = str(CORE.qp(c, "kind") or c.body.get("kind") or "").strip().lower()
    if kind not in KINDS:
        raise CORE.ApiError("bad profile image kind")
    return kind


def _drop_upload(conn, uid, up):
    """Remove one profile upload row and its bytes. Only ever touches this user's scope."""
    if not up:
        return
    row = conn.execute("SELECT id,disk FROM uploads WHERE id=? AND owner=? AND scope=?",
                       (int(up), int(uid), "profile:%d" % int(uid))).fetchone()
    if not row:
        return
    conn.execute("DELETE FROM uploads WHERE id=?", (row["id"],))
    try:
        os.remove(os.path.join(MEDIA.upload_dir(), row["disk"] or ""))
    except OSError:
        pass


def api_upload(c):
    conn, u = c.conn, c.user
    kind = _kind(c)
    raw = c.body.get("_raw") or b""
    if not raw:
        raise CORE.ApiError("Empty image")
    limit = MAX_AVATAR if kind == "avatar" else MAX_BANNER
    if len(raw) > limit:
        raise CORE.ApiError("Max %d MB for %s" % (limit // (1024 * 1024), kind), 413)
    _rate("media:%d" % u["id"], MEDIA_RATE)
    got = MEDIA.sniff(raw)
    if not got or got[0] not in MEDIA.IMAGE_MIMES:
        raise CORE.ApiError("Use a PNG, JPEG, GIF or WebP image")
    mime, ext = got
    declared = (c.h.headers.get("X-File-Type") or "").split(";")[0].strip().lower()
    if declared.startswith("image/") and declared != mime:
        raise CORE.ApiError("That image isn't what it claims to be")
    w, h = MEDIA.dims(mime, raw)
    cap = MAX_AVATAR_DIM if kind == "avatar" else MAX_BANNER_DIM
    if (w and w > cap) or (h and h > cap):
        raise CORE.ApiError("%s image is too large (%dx%d, max %d)" % (kind.title(), w, h, cap))

    prof = conn.execute("SELECT * FROM profiles WHERE user_id=?", (u["id"],)).fetchone()
    old = int(prof[kind + "_upload"] or 0) if prof else 0
    cur = conn.execute("""INSERT INTO uploads(owner,scope,server_id,channel_id,name,mime,size,w,h,sha,disk,created_at)
        VALUES(?,?,0,0,?,?,?,?,?,?,'',?)""",
                       (u["id"], "profile:%d" % u["id"], "%s.%s" % (kind, ext), mime, len(raw), w, h,
                        hashlib.sha256(raw).hexdigest(), _ts()))
    fid = int(cur.lastrowid)
    disk = "%d.%s" % (fid, ext)
    tmp = os.path.join(MEDIA.upload_dir(), disk + ".part")
    try:
        with open(tmp, "wb") as f:
            f.write(raw)
        os.replace(tmp, os.path.join(MEDIA.upload_dir(), disk))
    except OSError:
        conn.execute("DELETE FROM uploads WHERE id=?", (fid,))
        conn.commit()
        raise CORE.ApiError("Could not save the image", 500)
    conn.execute("UPDATE uploads SET disk=? WHERE id=?", (disk, fid))
    conn.execute("""INSERT INTO profiles(user_id,%s,updated_at) VALUES(?,?,?)
        ON CONFLICT(user_id) DO UPDATE SET %s=excluded.%s, updated_at=excluded.updated_at""" %
                 (kind + "_upload", kind + "_upload", kind + "_upload"),
                 (u["id"], fid, _ts()))
    if kind == "banner":
        conn.execute("UPDATE profiles SET banner_style='' WHERE user_id=?", (u["id"],))
    _drop_upload(conn, u["id"], old)
    conn.commit()
    return {"ok": True, "kind": kind, "social": social_card(conn, u["id"], u["id"])}


def api_clear(c):
    conn, u = c.conn, c.user
    kind = _kind(c)
    prof = conn.execute("SELECT * FROM profiles WHERE user_id=?", (u["id"],)).fetchone()
    old = int(prof[kind + "_upload"] or 0) if prof else 0
    if prof:
        conn.execute("UPDATE profiles SET %s=0, updated_at=? WHERE user_id=?" % (kind + "_upload"), (_ts(), u["id"]))
    _drop_upload(conn, u["id"], old)
    conn.commit()
    return {"ok": True, "social": social_card(conn, u["id"], u["id"])}


def api_img(c):
    uid = CORE.qpi(c, "uid")
    kind = str(CORE.qp(c, "kind") or "").strip().lower()
    if kind not in KINDS:
        raise CORE.ApiError("bad profile image kind")
    prof = c.conn.execute("SELECT * FROM profiles WHERE user_id=?", (uid,)).fetchone()
    if not prof or not c.conn.execute("SELECT 1 FROM users WHERE id=?", (uid,)).fetchone():
        raise CORE.ApiError("No such image", 404)
    if not can_view(c.conn, c.user, uid):
        raise CORE.ApiError("No such image", 404)
    up = int(prof[kind + "_upload"] or 0)
    if not up:
        raise CORE.ApiError("No such image", 404)
    row = c.conn.execute("SELECT * FROM uploads WHERE id=? AND owner=? AND scope=?",
                         (up, uid, "profile:%d" % uid)).fetchone()
    if not row or not row["disk"]:
        raise CORE.ApiError("No such image", 404)
    path = os.path.join(MEDIA.upload_dir(), row["disk"])
    if not os.path.isfile(path):
        raise CORE.ApiError("No such image", 404)
    c.h.send_media(path, row["name"] or "image", row["mime"] or "application/octet-stream",
                   inline=True, cache="private, max-age=86400",
                   etag=('"%s"' % row["sha"]) if row["sha"] else None)


def install(srv, db, permissions):
    global CORE, DB, PERMS
    CORE, DB, PERMS = srv, db, permissions
    srv.route("GET", "/api/profile/social")(api_profile_social)
    srv.route("POST", "/api/profile/status")(api_status)
    srv.route("POST", "/api/profile/details")(api_details)
    srv.route("POST", "/api/profile/upload")(api_upload)
    api_upload.raw = True
    api_upload.max_body = MAX_BANNER + 65536
    srv.route("POST", "/api/profile/clear")(api_clear)
    srv.route("GET", "/api/profile/img")(api_img)
    api_img.owns_response = True
