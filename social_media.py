"""
RAGDAMAXING social media: uploads, stickers and link previews.

Uploads are raw-body POSTs (the app's normal JSON dispatcher is bypassed for this
one route) and are scoped to a channel or a DM thread. A file is served only to
its uploader, or to someone who can currently view the thread it was posted in,
and only once it is attached to a live message. Everything is stdlib.

Stickers are a fixed catalog of emoji cards: no user-supplied images, no files.
Link previews are fetched server-side with an SSRF guard (http/https, ports
80/443, public IPs only, no redirects), a 3s timeout and a 256 KB read cap, then
cached in sqlite.
"""
import hashlib
import ipaddress
import json
import os
import re
import socket
import struct
import time
import urllib.parse
import urllib.request
from html.parser import HTMLParser

CORE = None
DB = None
PERMS = None
CHAT = None

MAX_UPLOAD = 8 * 1024 * 1024
MAX_FILES = 4
MAX_FILENAME = 80
MAX_IMAGE_PIXELS = 40_000_000   # rejects decompression bombs before a browser has to decode them
MAX_IMAGE_SIDE = 12000
UPLOAD_RATE = 30          # uploads per 10 minutes per user
PREVIEW_RATE = 30
PREVIEW_MAX_BYTES = 256 * 1024
PREVIEW_TTL = 7 * 86400
PREVIEW_TIMEOUT = 3.0

IMAGE_MIMES = ("image/png", "image/jpeg", "image/gif", "image/webp")
ALLOWED_MIMES = IMAGE_MIMES + ("application/pdf", "application/zip", "text/plain")

STICKERS = [
    {"id": "party", "e": "🎉", "label": "party"}, {"id": "hype", "e": "🔥", "label": "hype"},
    {"id": "gg", "e": "🏆", "label": "gg"}, {"id": "skull", "e": "💀", "label": "skull"},
    {"id": "cry", "e": "😭", "label": "cry"}, {"id": "laugh", "e": "😂", "label": "laugh"},
    {"id": "love", "e": "❤️", "label": "love"}, {"id": "pray", "e": "🙏", "label": "pray"},
    {"id": "salute", "e": "🫡", "label": "salute"}, {"id": "hundred", "e": "💯", "label": "100"},
    {"id": "flex", "e": "💪", "label": "flex"}, {"id": "eyes", "e": "👀", "label": "eyes"},
    {"id": "brain", "e": "🧠", "label": "brain"}, {"id": "coffee", "e": "☕", "label": "coffee"},
    {"id": "moon", "e": "🌙", "label": "moon"}, {"id": "sun", "e": "☀️", "label": "sun"},
    {"id": "rocket", "e": "🚀", "label": "rocket"}, {"id": "star", "e": "⭐", "label": "star"},
    {"id": "ghost", "e": "👻", "label": "ghost"}, {"id": "clown", "e": "🤡", "label": "clown"},
    {"id": "check", "e": "✅", "label": "check"}, {"id": "cross", "e": "❌", "label": "nope"},
    {"id": "sleep", "e": "😴", "label": "sleep"}, {"id": "rage", "e": "😡", "label": "rage"},
]
STICKER_BY_ID = {s["id"]: s for s in STICKERS}

UPLOAD_RATE_BY_USER = {}
PREVIEW_RATE_BY_USER = {}
URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)


def _ts():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _boot(c):
    DB.install(c.conn)


def _rate(bucket, uid, limit, window=600):
    now = time.time()
    recent = [t for t in bucket.get(uid, []) if now - t < window]
    if len(recent) >= limit:
        raise CORE.ApiError("Slow down 😅", 429)
    bucket[uid] = recent + [now]


# --------------------------------------------------------------------- file types
def clean_name(raw):
    name = urllib.parse.unquote(str(raw or ""))[:MAX_FILENAME * 2]
    name = name.replace("\\", "/").split("/")[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip().strip(".")
    return (name or "file")[:MAX_FILENAME]


def sniff(data):
    """Return (mime, ext) from magic bytes, or None. Never trust the client."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png", "png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg", "jpg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif", "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", "webp"
    if data[:5] == b"%PDF-":
        return "application/pdf", "pdf"
    if data[:4] == b"PK\x03\x04":
        return "application/zip", "zip"
    if _texty(data):
        return "text/plain", "txt"
    return None


def _texty(data):
    if not data or len(data) > 2 * 1024 * 1024:
        return False
    if b"\x00" in data:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    ctrl = sum(1 for b in data if b < 9 or (13 < b < 32))
    return ctrl <= max(1, len(data) // 100)


def dims(mime, d):
    try:
        if mime == "image/png":
            return struct.unpack(">II", d[16:24])
        if mime == "image/gif":
            return struct.unpack("<HH", d[6:10])
        if mime == "image/jpeg":
            i = 2
            while i < len(d) - 9:
                if d[i] != 0xFF:
                    i += 1
                    continue
                marker = d[i + 1]
                if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    h, w = struct.unpack(">HH", d[i + 5:i + 9])
                    return w, h
                if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
                    i += 2
                    continue
                ln = struct.unpack(">H", d[i + 2:i + 4])[0]
                if ln < 2:
                    break
                i += 2 + ln
            return 0, 0
        if mime == "image/webp":
            if d[12:16] == b"VP8X":
                return 1 + int.from_bytes(d[24:27], "little"), 1 + int.from_bytes(d[27:30], "little")
            if d[12:16] == b"VP8 ":
                w = int.from_bytes(d[26:28], "little") & 0x3FFF
                h = int.from_bytes(d[28:30], "little") & 0x3FFF
                return w, h
            if d[12:16] == b"VP8L":
                bits = int.from_bytes(d[21:25], "little")
                return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    except Exception:
        pass
    return 0, 0


# --------------------------------------------------------------------- uploads
def upload_dir():
    """Files live beside the database, so a temp/test DB never writes into the project data dir."""
    p = os.path.join(os.path.dirname(os.path.abspath(CORE.DB_PATH)), "uploads")
    os.makedirs(p, exist_ok=True)
    return p


def file_json(r):
    return {"id": int(r["id"]), "name": r["name"], "mime": r["mime"], "size": int(r["size"]),
            "w": int(r["w"] or 0), "h": int(r["h"] or 0)}


def msg_meta(conn, ids):
    """{message_id: [attachment, ...]} for a batch of messages."""
    if not ids:
        return {}
    ph = ",".join("?" * len(ids))
    out = {}
    for r in conn.execute("SELECT mf.msg_id, u.* FROM msg_files mf JOIN uploads u ON u.id=mf.upload_id "
                          "WHERE mf.msg_id IN (%s) ORDER BY mf.msg_id, mf.pos, u.id" % ph, list(ids)):
        out.setdefault(int(r["msg_id"]), []).append(file_json(r))
    return out


def parse_preview(raw):
    if not raw:
        return None
    try:
        p = json.loads(raw)
    except Exception:
        return None
    return p if isinstance(p, dict) and p.get("url") else None


def attach(conn, uid, thread, mid, ids):
    """Link uploads to a message. Only the same user, same thread, never reused."""
    if not ids:
        return []
    if not isinstance(ids, list):
        raise CORE.ApiError("bad files")
    if len(ids) > MAX_FILES:
        raise CORE.ApiError("Max %d files per message" % MAX_FILES)
    out = []
    for raw in ids:
        try:
            fid = int(raw)
        except (TypeError, ValueError):
            raise CORE.ApiError("bad file id")
        row = conn.execute("SELECT * FROM uploads WHERE id=? AND owner=? AND scope=?",
                           (fid, uid, thread)).fetchone()
        if not row:
            raise CORE.ApiError("That upload is not yours or belongs to another chat", 400)
        if conn.execute("SELECT 1 FROM msg_files WHERE upload_id=?", (fid,)).fetchone():
            raise CORE.ApiError("That file is already on a message")
        conn.execute("INSERT OR IGNORE INTO msg_files(msg_id,upload_id,pos) VALUES(?,?,?)",
                     (mid, fid, len(out)))
        out.append(file_json(row))
    return out


LAST_GC = [0.0]


def _gc(conn):
    """Hourly, on upload: drop abandoned/removed files after a day. Never touches fresh ones."""
    now = time.time()
    if now - LAST_GC[0] < 3600:
        return
    LAST_GC[0] = now
    cutoff = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now - 86400))
    rows = conn.execute(
        "SELECT id,disk FROM uploads WHERE created_at<? AND scope NOT LIKE 'profile:%' AND NOT EXISTS("
        "SELECT 1 FROM msg_files mf JOIN messages m ON m.id=mf.msg_id "
        "WHERE mf.upload_id=uploads.id AND m.deleted=0) AND NOT EXISTS("
        "SELECT 1 FROM server_assets a WHERE a.upload_id=uploads.id)", (cutoff,)).fetchall()
    for r in rows:
        try:
            os.remove(os.path.join(upload_dir(), r["disk"] or ""))
        except OSError:
            pass
        conn.execute("DELETE FROM msg_files WHERE upload_id=?", (r["id"],))
        conn.execute("DELETE FROM uploads WHERE id=?", (r["id"],))
    if rows:
        conn.commit()


def api_upload(c):
    _boot(c)
    conn, u = c.conn, c.user
    _gc(conn)
    raw = c.body.get("_raw") or b""
    if not raw:
        raise CORE.ApiError("Empty file")
    if len(raw) > MAX_UPLOAD:
        raise CORE.ApiError("Max 8 MB per file", 413)
    _rate(UPLOAD_RATE_BY_USER, u["id"], UPLOAD_RATE)

    asset_sid = CORE.qpi(c, "asset_server")
    ch_id = CORE.qpi(c, "ch")
    if asset_sid:
        if not PERMS.can(conn, u, asset_sid, "attach"):
            raise CORE.ApiError("You can't add expressions here", 403)
        scope, sid, cid = "asset:%s" % asset_sid, int(asset_sid), 0
    elif ch_id:
        ch = CHAT._channel(c, ch_id, "attach")
        scope, sid, cid = DB.thread_of(ch), int(ch["server_id"]), int(ch["id"])
    else:
        th, other = CORE.chat_thread(c, CORE.qp(c, "thread"))
        if not th.startswith("dm:"):
            raise CORE.ApiError("bad upload target", 400)
        scope, sid, cid = th, 0, 0

    declared = (c.h.headers.get("X-File-Type") or "").split(";")[0].strip().lower()
    got = sniff(raw)
    if not got:
        raise CORE.ApiError("That file type isn't allowed (images, PDF, ZIP or text)")
    mime, ext = got
    if declared.startswith("image/") and mime not in IMAGE_MIMES:
        raise CORE.ApiError("That file isn't the image it claims to be")
    if mime not in ALLOWED_MIMES:
        raise CORE.ApiError("That file type isn't allowed")
    if asset_sid and mime not in IMAGE_MIMES:
        raise CORE.ApiError("Custom emoji, stickers and GIFs must be images")
    if mime == "text/plain" and declared in ("application/json", "text/markdown", "text/csv"):
        mime = "text/plain"

    w, h = dims(mime, raw)
    if w and h and (w * h > MAX_IMAGE_PIXELS or max(w, h) > MAX_IMAGE_SIDE):
        raise CORE.ApiError("That image is too large (%dx%d); resize it first" % (w, h), 413)
    name = clean_name(c.h.headers.get("X-File-Name"))
    sha = hashlib.sha256(raw).hexdigest()
    cur = conn.execute("INSERT INTO uploads(owner,scope,server_id,channel_id,name,mime,size,w,h,sha,disk,created_at) "
                       "VALUES(?,?,?,?,?,?,?,?,?,?,'',?)",
                       (u["id"], scope, sid, cid, name, mime, len(raw), w, h, sha, _ts()))
    fid = int(cur.lastrowid)
    disk = "%d.%s" % (fid, ext)
    tmp = os.path.join(upload_dir(), disk + ".part")
    try:
        with open(tmp, "wb") as f:
            f.write(raw)
        os.replace(tmp, os.path.join(upload_dir(), disk))
    except OSError:
        conn.execute("DELETE FROM uploads WHERE id=?", (fid,))
        conn.commit()
        raise CORE.ApiError("Could not save the file", 500)
    conn.execute("UPDATE uploads SET disk=? WHERE id=?", (disk, fid))
    conn.commit()
    return {"file": {"id": fid, "name": name, "mime": mime, "size": len(raw), "w": w, "h": h}}


def _can_see(c, row):
    scope = row["scope"] or ""
    if scope.startswith("asset:"):
        try:
            return PERMS.can(c.conn, c.user, int(scope.split(":", 1)[1]), "view")
        except (TypeError, ValueError):
            return False
    if row["channel_id"]:
        ch = c.conn.execute("SELECT * FROM channels WHERE id=?", (int(row["channel_id"]),)).fetchone()
        if not ch:
            return False
        try:
            return PERMS.can(c.conn, c.user, ch["server_id"], "view", ch["id"])
        except Exception:
            return False
    th = row["scope"] or ""
    if th.startswith("dm:"):
        return str(c.user["id"]) in th.split(":")[1:]
    return False


def api_file(c):
    _boot(c)
    fid = CORE.qpi(c, "id")
    if not fid:
        raise CORE.ApiError("No such file", 404)
    row = c.conn.execute("SELECT * FROM uploads WHERE id=?", (fid,)).fetchone()
    if not row:
        raise CORE.ApiError("No such file", 404)
    mine = int(row["owner"]) == int(c.user["id"])
    if not mine:
        if not _can_see(c, row):
            raise CORE.ApiError("No such file", 404)
        attached = c.conn.execute(
            "SELECT 1 FROM msg_files mf JOIN messages m ON m.id=mf.msg_id WHERE mf.upload_id=? AND m.deleted=0",
            (fid,)).fetchone()
        expression = c.conn.execute("SELECT 1 FROM server_assets WHERE upload_id=?", (fid,)).fetchone()
        if not attached and not expression:
            raise CORE.ApiError("No such file", 404)
    path = os.path.join(upload_dir(), row["disk"] or "")
    if not row["disk"] or not os.path.isfile(path):
        raise CORE.ApiError("No such file", 404)
    image = row["mime"] in IMAGE_MIMES
    # Stream from disk instead of loading up to 8 MB into every request thread.
    # A strong ETag plus a private max-age makes repeat views free, while the
    # short attachment cache keeps revoked downloads from lingering too long.
    c.h.send_media(path, row["name"] or "file", row["mime"] or "application/octet-stream",
                   inline=image, cache="private, max-age=604800" if image else "private, max-age=3600",
                   etag=('"%s"' % row["sha"]) if row["sha"] else None)


# --------------------------------------------------------------------- previews
def first_url(text):
    m = URL_RE.search(text or "")
    if not m:
        return ""
    return m.group(0).rstrip(".,;:!?)]}>\"'")


def _url_key(url):
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]


def _safe_url(url):
    p = urllib.parse.urlsplit(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise ValueError("bad scheme")
    if p.username or p.password:
        raise ValueError("credentials in url")
    port = p.port or (443 if p.scheme == "https" else 80)
    if port not in (80, 443):
        raise ValueError("bad port")
    host = p.hostname.lower().strip(".")
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local") or host.endswith(".internal"):
        raise ValueError("private host")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        for info in socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP):
            if not ipaddress.ip_address(info[4][0]).is_global:
                raise ValueError("private ip")
    else:
        if not ip.is_global:
            raise ValueError("private ip")
    return urllib.parse.urlunsplit((p.scheme, p.netloc, p.path or "/", p.query, ""))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


class _Meta(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = []
        self.metas = {}
        self.in_title = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "title":
            self.in_title = True
        elif tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower().strip()
            val = (a.get("content") or "").strip()
            if key and val and key not in self.metas:
                self.metas[key] = val

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.in_title and data.strip() and len(self.title) < 8:
            self.title.append(data.strip())


def _squash(s, n):
    return re.sub(r"\s+", " ", str(s or "")).strip()[:n]


def parse_html(raw, base_url):
    try:
        html = raw.decode("utf-8", "ignore")
    except Exception:
        return None
    p = _Meta()
    try:
        p.feed(html)
    except Exception:
        return None
    m = p.metas
    title = m.get("og:title") or m.get("twitter:title") or " ".join(p.title) or m.get("title")
    desc = m.get("og:description") or m.get("twitter:description") or m.get("description")
    image = m.get("og:image:secure_url") or m.get("og:image") or m.get("twitter:image") or m.get("twitter:image:src")
    site = m.get("og:site_name")
    title = _squash(title, 140)
    desc = _squash(desc, 260)
    if not title and not desc and not image:
        return None
    if image:
        try:
            image = urllib.parse.urljoin(base_url, image)
            if urllib.parse.urlsplit(image).scheme != "https":
                image = ""
        except Exception:
            image = ""
    if not site:
        site = urllib.parse.urlsplit(base_url).hostname or ""
    return {"url": base_url, "title": title or (urllib.parse.urlsplit(base_url).hostname or base_url),
            "desc": desc, "image": image, "site": _squash(site, 60), "ts": time.time()}


def fetch_preview(url):
    try:
        safe = _safe_url(url)
    except ValueError:
        return None
    except Exception:
        return None
    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(safe, headers={
        "User-Agent": "Ragdamaxing/4 link preview", "Accept": "text/html,application/xhtml+xml"})
    try:
        with opener.open(req, timeout=PREVIEW_TIMEOUT) as r:
            ctype = (r.headers.get("Content-Type") or "").lower()
            if "html" not in ctype:
                return None
            final_url = r.geturl() or safe
            raw = r.read(PREVIEW_MAX_BYTES + 1)
    except Exception:
        return None
    if not raw:
        return None
    return parse_html(raw[:PREVIEW_MAX_BYTES], final_url)


def preview_for(conn, text, allow_fetch=True):
    """Cached preview for the first URL in a message body ('' when there is none)."""
    url = first_url(text)
    if not url:
        return ""
    key = _url_key(url)
    row = conn.execute("SELECT * FROM link_previews WHERE key=?", (key,)).fetchone()
    if row and time.time() - float(row["ts"] or 0) < PREVIEW_TTL:
        return json.dumps({"url": row["url"], "title": row["title"], "desc": row["desc"],
                           "image": row["image"], "site": row["site"]})
    if not allow_fetch:
        return ""
    card = fetch_preview(url)
    if not card:
        return ""
    conn.execute("INSERT OR REPLACE INTO link_previews(key,url,title,desc,image,site,ts) VALUES(?,?,?,?,?,?,?)",
                 (key, card["url"], card["title"], card["desc"], card["image"], card["site"], time.time()))
    return json.dumps({k: card[k] for k in ("url", "title", "desc", "image", "site")})


def api_preview(c):
    _boot(c)
    url = CORE.qp(c, "url")[:500]
    try:
        _safe_url(url)
    except ValueError:
        raise CORE.ApiError("That link can't be previewed")
    except Exception:
        raise CORE.ApiError("That link can't be previewed")
    _rate(PREVIEW_RATE_BY_USER, c.user["id"], PREVIEW_RATE)
    key = _url_key(url)
    row = c.conn.execute("SELECT * FROM link_previews WHERE key=?", (key,)).fetchone()
    if row and time.time() - float(row["ts"] or 0) < PREVIEW_TTL:
        return {"preview": {"url": row["url"], "title": row["title"], "desc": row["desc"],
                            "image": row["image"], "site": row["site"]}}
    card = fetch_preview(url)
    if not card:
        return {"preview": None}
    c.conn.execute("INSERT OR REPLACE INTO link_previews(key,url,title,desc,image,site,ts) VALUES(?,?,?,?,?,?,?)",
                   (key, card["url"], card["title"], card["desc"], card["image"], card["site"], time.time()))
    c.conn.commit()
    return {"preview": {k: card[k] for k in ("url", "title", "desc", "image", "site")}}


def api_stickers(c):
    return {"stickers": STICKERS}


# --------------------------------------------------------------------- install
def install(srv, db, permissions, chat):
    global CORE, DB, PERMS, CHAT
    CORE, DB, PERMS, CHAT = srv, db, permissions, chat
    srv.route("POST", "/api/upload")(api_upload)
    api_upload.raw = True
    api_upload.max_body = MAX_UPLOAD + 65536
    srv.route("GET", "/api/file")(api_file)
    api_file.owns_response = True
    srv.route("GET", "/api/preview")(api_preview)
    srv.route("GET", "/api/stickers")(api_stickers)
