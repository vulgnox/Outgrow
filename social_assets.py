"""
RAGDAMAXING per-server custom expressions.

A server keeps its own emoji, stickers and GIFs. The files use the normal upload
pipeline (scope ``asset:<server>``), and this module owns only the catalog and
authorization rules. Assets are soft-deleted so old messages keep rendering.
"""
import re
import time

CORE = DB = PERMS = MEDIA = EMIT = None

KINDS = ("emoji", "sticker", "gif")
MAX_ASSETS = 120
KIND_MAX = {"emoji": 60, "sticker": 40, "gif": 30}
MAX_BYTES = {"emoji": 2 * 1024 * 1024, "sticker": 4 * 1024 * 1024, "gif": 4 * 1024 * 1024}
MAX_DIM = {"emoji": 512, "sticker": 1024, "gif": 1280}
SLUG_RE = re.compile(r"^[a-z0-9_-]{2,24}$")
REACTION_RE = re.compile(r"^:([a-z0-9_-]{2,24}):$")
STICKER_RE = re.compile(r"^([ag])(\d{1,9})$")


def _as_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _boot(c):
    DB.install(c.conn)
    if c.user and c.user.get("crew_id"):
        DB.sync_crew(c.conn, c.user["crew_id"])


def _asset_json(r):
    return {
        "id": int(r["id"]), "kind": r["kind"], "name": r["name"], "slug": r["slug"],
        "upload": int(r["upload_id"]), "mime": r["mime"], "size": int(r["size"] or 0),
        "w": int(r["w"] or 0), "h": int(r["h"] or 0), "by": int(r["created_by"] or 0),
        "active": bool(r["active"]),
    }


def _rows(conn, sid):
    return conn.execute(
        """SELECT a.*, u.mime, u.size, u.w, u.h FROM server_assets a
           JOIN uploads u ON u.id=a.upload_id WHERE a.server_id=?
           ORDER BY a.kind, a.active DESC, a.id""", (sid,)).fetchall()


def _one(conn, aid):
    return conn.execute(
        """SELECT a.*, u.mime, u.size, u.w, u.h FROM server_assets a
           JOIN uploads u ON u.id=a.upload_id WHERE a.id=?""", (aid,)).fetchone()


def _clean_name(raw):
    return re.sub(r"[\x00-\x1f\x7f]", "", str(raw or "")).strip()[:32]


def _slug(raw):
    s = re.sub(r"[^a-z0-9_-]+", "-", str(raw or "").lower().strip().strip(":")).strip("-")[:24]
    return s if len(s) >= 2 else "asset"


def _free_slug(conn, sid, kind, base):
    slug, n = base, 2
    while conn.execute("SELECT 1 FROM server_assets WHERE server_id=? AND kind=? AND slug=?",
                       (sid, kind, slug)).fetchone():
        suffix = "-%d" % n
        slug = base[:24 - len(suffix)] + suffix
        n += 1
    return slug


def _authorized(c, sid, perm="view"):
    if not sid or not PERMS.can(c.conn, c.user, sid, perm):
        if not PERMS.is_member(c.conn, c.user["id"], sid):
            raise CORE.ApiError("No such server", 404)
        raise CORE.ApiError("You don't have permission to do that", 403)


def api_assets(c):
    _boot(c)
    sid = CORE.qpi(c, "server")
    _authorized(c, sid)
    return {"assets": [_asset_json(r) for r in _rows(c.conn, sid)]}


def api_add(c):
    _boot(c)
    conn, u = c.conn, c.user
    sid = _as_int(c.body.get("server"))
    kind = str(c.body.get("kind") or "")
    _authorized(c, sid, "attach")
    if kind not in KINDS:
        raise CORE.ApiError("Pick emoji, sticker or GIF")
    n_total = conn.execute("SELECT COUNT(*) FROM server_assets WHERE server_id=? AND active=1", (sid,)).fetchone()[0]
    n_kind = conn.execute("SELECT COUNT(*) FROM server_assets WHERE server_id=? AND kind=? AND active=1",
                          (sid, kind)).fetchone()[0]
    if n_total >= MAX_ASSETS:
        raise CORE.ApiError("This server has reached %d expressions" % MAX_ASSETS)
    if n_kind >= KIND_MAX[kind]:
        raise CORE.ApiError("This server has reached its %s limit" % kind)

    fid = _as_int(c.body.get("upload"))
    row = conn.execute("SELECT * FROM uploads WHERE id=? AND owner=? AND scope=?",
                       (fid, u["id"], "asset:%s" % sid)).fetchone()
    if not row:
        raise CORE.ApiError("Upload that image first", 400)
    if row["mime"] not in MEDIA.IMAGE_MIMES:
        raise CORE.ApiError("Expressions must be images", 400)
    if kind == "gif" and row["mime"] != "image/gif":
        raise CORE.ApiError("A GIF slot needs a .gif file", 400)
    if int(row["size"] or 0) > MAX_BYTES[kind]:
        raise CORE.ApiError("That image is too large", 413)
    w, h = int(row["w"] or 0), int(row["h"] or 0)
    if not w or not h:
        raise CORE.ApiError("That image could not be read", 400)
    if w > MAX_DIM[kind] or h > MAX_DIM[kind]:
        raise CORE.ApiError("Keep this %s under %d×%d px" % (kind, MAX_DIM[kind], MAX_DIM[kind]))

    name = _clean_name(c.body.get("name")) or _slug(row["name"].rsplit(".", 1)[0] if row["name"] else "asset")
    slug = _free_slug(conn, sid, kind, _slug(name))
    cur = conn.execute(
        "INSERT INTO server_assets(server_id,kind,name,slug,upload_id,created_by,active,created_at) "
        "VALUES(?,?,?,?,?,?,1,?)",
        (sid, kind, name, slug, fid, u["id"], time.strftime("%Y-%m-%dT%H:%M:%S")))
    aid = cur.lastrowid
    PERMS.audit(conn, sid, u["id"], "asset.add", "%s %s" % (kind, slug))
    conn.commit()
    asset = _asset_json(_one(conn, aid))
    EMIT("asset", {"server": sid, "asset": asset}, DB.member_ids(conn, sid))
    return {"asset": asset}


def api_delete(c):
    _boot(c)
    conn, u = c.conn, c.user
    aid = _as_int(c.body.get("id"))
    row = conn.execute("SELECT * FROM server_assets WHERE id=?", (aid,)).fetchone()
    if not row:
        raise CORE.ApiError("No such expression", 404)
    sid = int(row["server_id"])
    _authorized(c, sid)
    if int(row["created_by"] or 0) != int(u["id"]) and not PERMS.can(conn, u, sid, "manage_server"):
        raise CORE.ApiError("Only its uploader or a server manager can remove this", 403)
    conn.execute("UPDATE server_assets SET active=0 WHERE id=?", (aid,))
    PERMS.audit(conn, sid, u["id"], "asset.delete", "%s %s" % (row["kind"], row["slug"]))
    conn.commit()
    EMIT("asset_del", {"server": sid, "id": aid}, DB.member_ids(conn, sid))
    return {"ok": True}


def sticker_ok(conn, sid, key):
    """True for an active custom sticker/GIF id like a12 or g7."""
    m = STICKER_RE.match(str(key or ""))
    if not m:
        return False
    kind = "sticker" if m.group(1) == "a" else "gif"
    row = conn.execute("SELECT kind,active FROM server_assets WHERE id=? AND server_id=?",
                       (int(m.group(2)), sid)).fetchone()
    return bool(row and row["active"] and row["kind"] == kind)


def reaction_ok(conn, sid, emoji):
    """True for an active custom emoji reaction token like :crew-heart:."""
    m = REACTION_RE.match(str(emoji or ""))
    if not m:
        return False
    row = conn.execute("SELECT 1 FROM server_assets WHERE server_id=? AND kind='emoji' AND slug=? AND active=1",
                       (sid, m.group(1))).fetchone()
    return bool(row)


def install(srv, core, db, perms, media, emit):
    global CORE, DB, PERMS, MEDIA, EMIT
    CORE, DB, PERMS, MEDIA, EMIT = core, db, perms, media, emit
    srv.route("GET", "/api/ch/assets")(api_assets)
    srv.route("POST", "/api/ch/assets")(api_add)
    srv.route("POST", "/api/ch/assets/delete")(api_delete)
