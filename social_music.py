"""
RAGDAMAXING music rooms.

The bot is server state, not a WebRTC peer: one proxy serves the same bytes to
every browser in a voice room and each browser aligns its <audio> element to the
server clock. YouTube is only ever resolved by yt-dlp with a validated video id;
no client-supplied URL reaches a subprocess or the network layer.
"""
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import social_chat as CHAT
import social_perms as PERMS
import social_voice as VOICE

CORE = DB = None

ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
ALLOWED_HOSTS = {"youtube.com", "www.youtube.com", "music.youtube.com", "youtu.be", "m.youtube.com"}
LOOP_MODES = ("off", "track", "queue")
MIME = {"m4a": "audio/mp4", "mp4": "audio/mp4", "webm": "audio/webm", "opus": "audio/ogg",
        "ogg": "audio/ogg", "mp3": "audio/mpeg", "aac": "audio/aac", "wav": "audio/wav"}

ENABLED = False
REASON = ""
PROVIDER = None
CACHE_DIR = ""
CACHE_MB = 300
CACHE_TTL = 2 * 3600
MAX_MIN = 20
QUEUE_MAX = 50
ADD_RATE = 6
SEARCH_RATE = 10
YOUTUBE_TIMEOUT = 20
MAX_TRACK_BYTES = 64 * 1024 * 1024

LOCK = threading.RLock()
STATE = {}                 # channel id -> queue/now/loop/votes/history
SOURCES = {}               # video id -> resolved direct stream metadata
SOURCE_LOCK = threading.Lock()
_CACHE_LOCKS = {}
_CACHE_LOCKS_LOCK = threading.Lock()
_RATE = {}                 # (kind, uid) -> [timestamps]
_SEARCH_CACHE = {}         # normalized query -> (expires, results)
_SEARCH_LOCK = threading.Lock()


class MusicError(Exception):
    def __init__(self, msg, code=400):
        super().__init__(msg)
        self.msg, self.code = msg, code


def _env(name, default=""):
    return os.environ.get("RAGDAMAXING_" + name, default)


def _int_env(name, default, low, high):
    try:
        return max(low, min(high, int(_env(name, str(default)))))
    except (TypeError, ValueError):
        return default


def _now_ms():
    return int(time.time() * 1000)


def _clean_query(q):
    q = str(q or "").strip()
    q = "".join(ch for ch in q if ch == "\t" or ch >= " ")
    if not q:
        raise MusicError("Search for a song first", 400)
    if len(q) > 120:
        q = q[:120]
    if q.startswith("-"):
        raise MusicError("That search starts with a dash", 400)
    return q


def _looks_like_video_ref(s):
    """A malformed URL/id must be rejected, not silently turned into a search."""
    low = str(s or "").strip().lower()
    return ("://" in low or low.startswith(("www.", "youtube.com", "youtu.be", "m.youtube.com", "music.youtube.com"))
            or re.fullmatch(r"[A-Za-z0-9_-]{10,13}", low) is not None)


def parse_id(raw):
    """Return a validated 11-character YouTube id, or raise MusicError.

    Only the five documented YouTube hosts are accepted. Playlists, channels,
    other schemes, credentials, odd ports and non-video paths are rejected before
    anything is handed to yt-dlp.
    """
    s = str(raw or "").strip()
    if not s or len(s) > 2048:
        raise MusicError("Paste a YouTube video link or 11-character id", 400)
    if ID_RE.fullmatch(s):
        return s
    if s.startswith("-") or "\x00" in s:
        raise MusicError("That is not a YouTube video link", 400)
    if not re.match(r"^[a-z][a-z0-9+.-]*://", s, re.I):
        s = "https://" + s
    try:
        u = urllib.parse.urlparse(s)
        port = u.port
    except ValueError:
        raise MusicError("That is not a YouTube video link", 400)
    if u.scheme not in ("http", "https") or u.username or u.password:
        raise MusicError("Only YouTube video links are supported", 400)
    host = (u.hostname or "").lower()
    if host not in ALLOWED_HOSTS or port not in (None, 80, 443):
        raise MusicError("Only youtube.com, music.youtube.com and youtu.be links are supported", 400)
    path = u.path or ""
    if host == "youtu.be":
        parts = [p for p in path.split("/") if p]
        if len(parts) != 1:
            raise MusicError("That link is not a single video", 400)
        vid = parts[0]
    else:
        if path in ("/watch", "/watch/"):
            qs = urllib.parse.parse_qs(u.query, keep_blank_values=True)
            if "list" in qs or "start_radio" in qs:
                raise MusicError("Playlists are not supported — link one video", 400)
            vid = (qs.get("v") or [""])[0]
        else:
            m = re.fullmatch(r"/(?:shorts|embed)/([A-Za-z0-9_-]{11})/?", path)
            if not m:
                raise MusicError("That link is not a single video", 400)
            vid = m.group(1)
    if not ID_RE.fullmatch(vid or ""):
        raise MusicError("That link is not a valid YouTube video", 400)
    return vid


def _mime_for(ext):
    return MIME.get(str(ext or "").lower().lstrip("."), "audio/mp4")


def _headers(raw):
    out = {}
    if not isinstance(raw, dict):
        return out
    for k in ("User-Agent", "Referer", "Accept", "Accept-Language", "Origin"):
        v = raw.get(k) or raw.get(k.lower())
        if isinstance(v, str) and v:
            out[k] = v[:500]
    return out


# --------------------------------------------------------------------- providers
class YtdlpProvider:
    name = "ytdlp"

    def __init__(self, path, timeout=20, cookies=""):
        self.path = path
        self.timeout = max(1, int(timeout))
        self.cookies = cookies if cookies and os.path.isfile(cookies) else ""
        self.sem = threading.BoundedSemaphore(2)

    def _run(self, args, timeout=None):
        if not self.sem.acquire(timeout=5):
            raise MusicError("Music lookup is busy — try again in a moment", 503)
        proc = None
        try:
            cmd = [self.path]
            if self.cookies:
                cmd += ["--cookies", self.cookies]
            cmd += args
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        text=True, encoding="utf-8", errors="replace",
                                        start_new_session=True)
                out, err = proc.communicate(timeout=timeout or self.timeout)
            except subprocess.TimeoutExpired:
                if proc:
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    except Exception:
                        try:
                            proc.kill()
                        except Exception:
                            pass
                    try:
                        proc.communicate(timeout=3)
                    except Exception:
                        pass
                raise MusicError("Music lookup timed out — try again", 504)
        finally:
            self.sem.release()
        if proc.returncode != 0:
            low = (err or "").lower()
            if "sign in to confirm" in low or "not a bot" in low or "cookies" in low:
                print("[music] yt-dlp bot check: " + (err or "").strip()[-500:], file=sys.stderr, flush=True)
                raise MusicError("YouTube is asking this server to sign in (bot check). Music is unavailable right now.", 503)
            print("[music] yt-dlp failed: " + (err or "").strip()[-500:], file=sys.stderr, flush=True)
            raise MusicError("Could not load that track", 502)
        return out

    def _search_result(self, info):
        vid = str(info.get("id") or "")
        if not ID_RE.fullmatch(vid):
            return None
        title = str(info.get("title") or info.get("fulltitle") or vid)[:160]
        artist = str(info.get("uploader") or info.get("channel") or info.get("artist") or "YouTube")[:100]
        try:
            dur = int(float(info.get("duration") or 0))
        except (TypeError, ValueError):
            dur = 0
        return {"id": vid, "title": title, "artist": artist, "duration_s": max(0, dur)}

    def search(self, query, limit=5):
        q = _clean_query(query)
        limit = max(1, min(5, int(limit)))
        out = self._run(["--no-warnings", "--no-playlist", "--flat-playlist", "--dump-json", "--",
                         "ytsearch%d:%s" % (limit, q)])
        results = []
        for line in (out or "").splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                info = json.loads(line)
            except ValueError:
                continue
            r = self._search_result(info)
            if r:
                results.append(r)
        return results[:limit]

    def resolve(self, video_id):
        vid = parse_id(video_id)
        out = self._run(["--no-warnings", "--no-playlist", "-f", "bestaudio[ext=m4a]/bestaudio",
                         "--dump-single-json", "--", "https://www.youtube.com/watch?v=" + vid])
        try:
            info = json.loads((out or "").strip())
        except ValueError:
            raise MusicError("Could not read that track", 502)
        if info.get("is_live"):
            raise MusicError("Live streams are not supported", 400)
        direct = info.get("url")
        if not direct and isinstance(info.get("requested_downloads"), list) and info["requested_downloads"]:
            direct = info["requested_downloads"][0].get("url")
        if not direct and isinstance(info.get("formats"), list) and info["formats"]:
            direct = info["formats"][-1].get("url")
        if not isinstance(direct, str) or urllib.parse.urlparse(direct).scheme not in ("http", "https"):
            raise MusicError("Could not get an audio stream for that track", 502)
        try:
            dur = int(float(info.get("duration") or 0))
        except (TypeError, ValueError):
            dur = 0
        ext = str(info.get("ext") or "m4a").lower()
        expires = info.get("expires")
        try:
            expires = float(expires)
        except (TypeError, ValueError):
            expires = time.time() + 3600
        if expires < 10_000_000_000:
            expires = time.time() + 3600
        return {
            "url": direct, "mime": _mime_for(ext), "headers": _headers(info.get("http_headers")),
            "expires": expires, "title": str(info.get("title") or vid)[:160],
            "artist": str(info.get("uploader") or info.get("channel") or "YouTube")[:100],
            "duration_s": max(0, dur), "is_live": False, "ext": ext,
        }


class RemoteProvider:
    """Tiny client for a Range-capable resolver running on a residential IP."""
    name = "remote"

    def __init__(self, base):
        u = urllib.parse.urlparse(base)
        if u.scheme not in ("http", "https") or not u.netloc or u.username or u.password:
            raise MusicError("RAGDAMAXING_MUSIC_REMOTE must be an http(s) base URL", 400)
        self.base = base.rstrip("/")

    def _get(self, path):
        req = urllib.request.Request(self.base + path, headers={"Accept": "application/json",
                                                                 "User-Agent": "RAGDAMAXING-music/1"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                raw = r.read(2 * 1024 * 1024)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            print("[music] remote resolver failed: %s" % type(e).__name__, file=sys.stderr, flush=True)
            raise MusicError("Music resolver is unavailable right now", 503)
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError:
            raise MusicError("Music resolver returned a bad response", 502)

    def search(self, query, limit=5):
        q = _clean_query(query)
        data = self._get("/search?q=" + urllib.parse.quote(q, safe="") + "&limit=%d" % max(1, min(5, int(limit))))
        rows = data.get("results", data) if isinstance(data, dict) else data
        out = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict) or not ID_RE.fullmatch(str(row.get("id") or "")):
                continue
            try:
                dur = int(float(row.get("duration_s", row.get("duration", 0)) or 0))
            except (TypeError, ValueError):
                dur = 0
            out.append({"id": str(row["id"]), "title": str(row.get("title") or row["id"])[:160],
                        "artist": str(row.get("artist") or row.get("uploader") or "YouTube")[:100],
                        "duration_s": max(0, dur)})
        return out[:max(1, min(5, int(limit)))]

    def resolve(self, video_id):
        vid = parse_id(video_id)
        return {"url": self.base + "/stream/" + urllib.parse.quote(vid, safe=""), "mime": "audio/mp4",
                "headers": {}, "expires": time.time() + 3600, "title": vid, "artist": "YouTube",
                "duration_s": 0, "is_live": False, "ext": "m4a"}


# --------------------------------------------------------------------- config/cache
def configure(srv):
    global ENABLED, REASON, PROVIDER, CACHE_DIR, CACHE_MB, MAX_MIN, QUEUE_MAX, YOUTUBE_TIMEOUT
    ENABLED = str(_env("MUSIC", "0")).strip().lower() in ("1", "true", "yes", "on")
    CACHE_MB = _int_env("MUSIC_CACHE_MB", 300, 1, 5000)
    MAX_MIN = _int_env("MUSIC_MAX_MIN", 20, 1, 180)
    QUEUE_MAX = _int_env("MUSIC_QUEUE_MAX", 50, 1, 200)
    YOUTUBE_TIMEOUT = _int_env("MUSIC_TIMEOUT", 20, 2, 120)
    CACHE_DIR = _env("MUSIC_CACHE_DIR", "").strip() or os.path.join(os.path.dirname(srv.DB_PATH), "music_cache")
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
    except OSError:
        CACHE_DIR = ""
    remote = _env("MUSIC_REMOTE", "").strip()
    path = _env("YTDLP", "").strip() or shutil.which("yt-dlp") or ""
    try:
        PROVIDER = RemoteProvider(remote) if remote else None
        if PROVIDER is None and path:
            found = path if os.path.isfile(path) else shutil.which(path)
            if found:
                PROVIDER = YtdlpProvider(found, YOUTUBE_TIMEOUT, _env("YTDLP_COOKIES", "").strip())
    except MusicError as e:
        print("[music] " + e.msg, file=sys.stderr, flush=True)
        PROVIDER = None
    if not ENABLED:
        REASON = "Music is off on this server (set RAGDAMAXING_MUSIC=1 to enable it)."
    elif PROVIDER is None:
        REASON = "Music is off: yt-dlp is not installed on the server."
    else:
        REASON = ""


def migrate(conn):
    if not conn.execute("SELECT 1 FROM social_meta WHERE k='music_perm_v1'").fetchone():
        conn.execute("UPDATE roles SET perms=perms | ? WHERE is_default=1 OR name='Admin'", (PERMS.PERM["music"],))
        conn.execute("INSERT OR REPLACE INTO social_meta(k,v) VALUES('music_perm_v1',?)",
                     (time.strftime("%Y-%m-%dT%H:%M:%S"),))
        conn.commit()


def _cache_path(video_id):
    return os.path.join(CACHE_DIR, video_id + ".audio")


def _meta_path(video_id):
    return os.path.join(CACHE_DIR, video_id + ".json")


def _read_meta(video_id):
    try:
        with open(_meta_path(video_id), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def clean_cache():
    """Delete expired cache entries, stale temp files and the LRU tail over the cap."""
    if not CACHE_DIR or not os.path.isdir(CACHE_DIR):
        return
    now = time.time()
    total = 0
    files = []
    try:
        entries = list(os.scandir(CACHE_DIR))
    except OSError:
        return
    for e in entries:
        try:
            if not e.is_file():
                continue
            name = e.name
            st = e.stat()
            if name.endswith(".part"):
                if now - st.st_mtime > 600:
                    try:
                        os.unlink(e.path)
                    except OSError:
                        pass
                continue
            if name.endswith(".audio"):
                if now - st.st_mtime > CACHE_TTL:
                    try:
                        os.unlink(e.path)
                    except OSError:
                        pass
                    continue
                files.append((st.st_mtime, st.st_size, e.path))
                total += st.st_size
            elif name.endswith(".json"):
                base = name[:-5]
                if not os.path.exists(os.path.join(CACHE_DIR, base + ".audio")):
                    try:
                        os.unlink(e.path)
                    except OSError:
                        pass
        except OSError:
            continue
    if total <= CACHE_MB * 1024 * 1024:
        return
    for _mtime, size, path in sorted(files):
        try:
            os.unlink(path)
            total -= size
            meta = os.path.join(CACHE_DIR, os.path.basename(path)[:-6] + ".json")
            if os.path.exists(meta):
                os.unlink(meta)
        except OSError:
            pass
        if total <= CACHE_MB * 1024 * 1024:
            break


def _cache_lock(video_id):
    with _CACHE_LOCKS_LOCK:
        return _CACHE_LOCKS.setdefault(video_id, threading.Lock())


# --------------------------------------------------------------------- state helpers
def _state(ch_id):
    return STATE.setdefault(int(ch_id), {"queue": [], "now": None, "loop": "off", "votes": {},
                                         "history": [], "timer": None, "timer_token": 0, "rev": 0})


def _public_track(t):
    return {"id": t["id"], "title": t["title"], "artist": t["artist"], "duration_s": t["duration_s"],
            "requester": t["requester"], "requester_name": t["requester_name"], "added": t.get("added", 0)}


def _vote_needed(ch_id):
    return max(1, len(VOICE.room_uids(ch_id)) // 2 + 1)


def snapshot(ch_id):
    ch_id = int(ch_id)
    needed = _vote_needed(ch_id)
    with LOCK:
        st = STATE.get(ch_id)
        if not st:
            return {"channel": ch_id, "enabled": bool(ENABLED and PROVIDER), "reason": REASON,
                    "queue": [], "now": None, "loop": "off", "votes": {}, "vote_needed": needed,
                    "server_ms": _now_ms(), "rev": 0}
        now = st["now"]
        return {"channel": ch_id, "enabled": bool(ENABLED and PROVIDER), "reason": REASON,
                "queue": [_public_track(t) for t in st["queue"]],
                "now": None if not now else {"track": _public_track(now["track"]),
                                             "started_at_ms": now["started_at_ms"],
                                             "paused_at_ms": now.get("paused_at_ms")},
                "loop": st["loop"], "votes": {k: len(v) for k, v in st["votes"].items() if v},
                "vote_needed": needed, "server_ms": _now_ms(), "rev": st["rev"]}


def _emit(ch_id):
    users = VOICE.room_uids(ch_id)
    if users and CHAT:
        CHAT.emit("music", snapshot(ch_id), users)


def _cancel_timer_locked(st):
    t = st.get("timer")
    if t:
        try:
            t.cancel()
        except Exception:
            pass
    st["timer"] = None
    st["timer_token"] = int(st.get("timer_token") or 0) + 1


def _timer_fire(ch_id, token):
    ch_id = int(ch_id)
    with LOCK:
        st = STATE.get(ch_id)
        if not st or st.get("timer_token") != token:
            return
        _advance_locked(ch_id, st)
        st["rev"] += 1
    _emit(ch_id)


def _play_locked(ch_id, st, track):
    st["now"] = {"track": track, "started_at_ms": _now_ms(), "paused_at_ms": None}
    st["votes"] = {}
    _schedule_locked_for(ch_id, st)


def _schedule_locked_for(ch_id, st):
    _cancel_timer_locked(st)
    now = st.get("now")
    if not now or now.get("paused_at_ms") is not None:
        return
    duration = float(now["track"].get("duration_s") or 0)
    if duration <= 0:
        return
    remaining = duration - max(0.0, (_now_ms() - now["started_at_ms"]) / 1000.0)
    token = st["timer_token"]
    t = threading.Timer(max(0.25, remaining + 0.25), _timer_fire, args=(ch_id, token))
    t.daemon = True
    st["timer"] = t
    t.start()


def _advance_locked(ch_id, st):
    cur = st.get("now")
    if not cur:
        st["now"] = None
        _cancel_timer_locked(st)
        return
    if st["loop"] == "track":
        cur["started_at_ms"] = _now_ms()
        cur["paused_at_ms"] = None
        st["votes"] = {}
        _schedule_locked_for(ch_id, st)
        return
    if st["loop"] == "queue":
        st["history"].append(cur["track"])
        st["history"] = st["history"][-QUEUE_MAX:]
    if not st["queue"] and st["loop"] == "queue" and st["history"]:
        st["queue"] = st["history"]
        st["history"] = []
    if st["queue"]:
        track = st["queue"].pop(0)
        st["now"] = {"track": track, "started_at_ms": _now_ms(), "paused_at_ms": None}
        st["votes"] = {}
        _schedule_locked_for(ch_id, st)
    else:
        st["now"] = None
        st["votes"] = {}
        _cancel_timer_locked(st)


def _room_required(ch_id, uid):
    if int(uid) not in VOICE.room_uids(ch_id):
        raise CORE.ApiError("Join the voice room first", 403)


def _channel(c, raw, perm="music"):
    try:
        ch_id = int(raw or 0)
    except (TypeError, ValueError):
        raise CORE.ApiError("bad channel", 400)
    if not ch_id:
        raise CORE.ApiError("Pick a voice room", 400)
    ch = CHAT._channel(c, ch_id, perm)
    if ch["kind"] != "voice":
        raise CORE.ApiError("That is not a voice channel", 400)
    return ch


def _ch_id(c):
    raw = CORE.qpi(c, "channel") or CORE.qpi(c, "ch")
    if not raw and c.body:
        raw = c.body.get("channel") or c.body.get("ch")
    return raw


def _disabled():
    if not ENABLED or PROVIDER is None:
        raise CORE.ApiError(REASON or "Music is unavailable", 503)


def _rate(kind, uid, limit):
    now = time.time()
    key = (kind, int(uid))
    recent = [t for t in _RATE.get(key, []) if now - t < 60]
    if len(recent) >= limit:
        raise CORE.ApiError("Slow down — try again in a minute", 429)
    _RATE[key] = recent + [now]


def _is_mod(c, ch):
    return PERMS.can(c.conn, c.user, ch["server_id"], "manage_channels", ch["id"])


def _can_control(c, ch, st):
    now = st.get("now")
    return bool(now and int(now["track"]["requester"]) == int(c.user["id"])) or _is_mod(c, ch)


# --------------------------------------------------------------------- API
CHECK_VIDEO = "jNQXAC9IVRw"  # a stable public video used only for the health check


def api_check(c):
    """Production-facing health check for music resolution.

    Reports whether the feature is enabled, whether the configured cookies file
    exists, and whether a real YouTube resolve succeeds, so failures are visible
    without SSH-ing into the host.
    """
    cookies_path = _env("YTDLP_COOKIES", "").strip()
    out = {
        "enabled": bool(ENABLED and PROVIDER is not None),
        "reason": REASON,
        "provider": getattr(PROVIDER, "name", None),
        "yt_dlp": getattr(PROVIDER, "path", None) if isinstance(PROVIDER, YtdlpProvider) else None,
        "cookies_configured": bool(cookies_path),
        "cookies_path": cookies_path or None,
        "cookies_exists": bool(cookies_path and os.path.isfile(cookies_path)),
        "check_video": CHECK_VIDEO,
        "resolve_ok": False,
        "resolve_error": None,
        "checked_at_ms": _now_ms(),
    }
    if not ENABLED or PROVIDER is None:
        out["resolve_error"] = REASON or "music is unavailable"
        return out
    try:
        src = PROVIDER.resolve(CHECK_VIDEO)
        out["resolve_ok"] = True
        out["title"] = src.get("title")
    except MusicError as e:
        out["resolve_error"] = e.msg
        out["resolve_code"] = e.code
    except Exception as e:
        out["resolve_error"] = type(e).__name__
    return out


def api_time(c):
    return {"t": _now_ms()}


def api_state(c):
    ch = _channel(c, _ch_id(c))
    snap = snapshot(ch["id"])
    snap["in_room"] = int(c.user["id"]) in VOICE.room_uids(ch["id"])
    return snap


def api_search(c):
    _disabled()
    ch = _channel(c, _ch_id(c))
    q = _clean_query(CORE.qp(c, "q"))
    _rate("search", c.user["id"], SEARCH_RATE)
    key = q.lower()
    now = time.time()
    with _SEARCH_LOCK:
        hit = _SEARCH_CACHE.get(key)
        if hit and hit[0] > now:
            return {"results": hit[1], "cached": True, "channel": int(ch["id"])}
    try:
        results = PROVIDER.search(q, 5)
    except MusicError as e:
        raise CORE.ApiError(e.msg, e.code)
    with _SEARCH_LOCK:
        if len(_SEARCH_CACHE) > 200:
            for k in sorted(_SEARCH_CACHE, key=lambda x: _SEARCH_CACHE[x][0])[:50]:
                _SEARCH_CACHE.pop(k, None)
        _SEARCH_CACHE[key] = (now + 600, results)
    return {"results": results, "cached": False, "channel": int(ch["id"])}


def api_add(c):
    _disabled()
    ch = _channel(c, _ch_id(c))
    uid = int(c.user["id"])
    _room_required(ch["id"], uid)
    _rate("add", uid, ADD_RATE)
    raw_id = c.body.get("id")
    raw_query = c.body.get("query") or c.body.get("q") or ""
    meta = None
    try:
        if raw_id:
            vid = parse_id(raw_id)
        elif str(raw_query).strip():
            q = _clean_query(raw_query)
            try:
                vid = parse_id(q)
            except MusicError:
                if _looks_like_video_ref(q):
                    raise
                found = PROVIDER.search(q, 1)
                if not found:
                    raise CORE.ApiError("No results for that", 404)
                vid, meta = found[0]["id"], found[0]
        else:
            raise CORE.ApiError("Send a song or a YouTube link", 400)
    except MusicError as e:
        raise CORE.ApiError(e.msg, e.code)
    with LOCK:
        st = _state(ch["id"])
        if len(st["queue"]) >= QUEUE_MAX:
            raise CORE.ApiError("The queue is full (%d max)" % QUEUE_MAX, 429)
        if sum(1 for t in st["queue"] if int(t["requester"]) == uid) >= 10:
            raise CORE.ApiError("You already have 10 tracks queued", 429)
    try:
        src = PROVIDER.resolve(vid)
    except MusicError as e:
        raise CORE.ApiError(e.msg, e.code)
    dur = int(src.get("duration_s") or (meta or {}).get("duration_s") or 0)
    if dur > MAX_MIN * 60:
        raise CORE.ApiError("That track is longer than %d minutes" % MAX_MIN, 400)
    if src.get("is_live"):
        raise CORE.ApiError("Live streams are not supported", 400)
    with SOURCE_LOCK:
        SOURCES[vid] = src
    track = {"id": vid, "title": (src.get("title") or (meta or {}).get("title") or vid)[:160],
             "artist": (src.get("artist") or (meta or {}).get("artist") or "YouTube")[:100],
             "duration_s": max(0, dur), "requester": uid, "requester_name": c.user["display"],
             "added": int(time.time())}
    with LOCK:
        st = _state(ch["id"])
        if len(st["queue"]) >= QUEUE_MAX:
            raise CORE.ApiError("The queue is full (%d max)" % QUEUE_MAX, 429)
        if sum(1 for t in st["queue"] if int(t["requester"]) == uid) >= 10:
            raise CORE.ApiError("You already have 10 tracks queued", 429)
        if st["now"] is None:
            _play_locked(ch["id"], st, track)
        else:
            st["queue"].append(track)
        st["rev"] += 1
    _emit(ch["id"])
    snap = snapshot(ch["id"])
    snap["added"] = _public_track(track)
    return snap


def _control_action(c, kind, payload=None):
    _disabled()
    ch = _channel(c, _ch_id(c))
    uid = int(c.user["id"])
    _room_required(ch["id"], uid)
    with LOCK:
        st = _state(ch["id"])
        now = st.get("now")
        if kind in ("skip", "pause", "resume", "stop") and not now:
            raise CORE.ApiError("Nothing is playing", 400)
        if kind == "loop":
            mode = str((payload or {}).get("mode") or "off").lower()
            if mode not in LOOP_MODES:
                raise CORE.ApiError("Loop must be off, track or queue", 400)
            if not _can_control(c, ch, st):
                raise CORE.ApiError("Only the requester or a moderator can change loop", 403)
            st["loop"] = mode
        elif kind == "pause":
            if not _can_control(c, ch, st):
                raise CORE.ApiError("Only the requester or a moderator can pause", 403)
            if now.get("paused_at_ms") is None:
                now["paused_at_ms"] = _now_ms()
                _cancel_timer_locked(st)
        elif kind == "resume":
            if not _can_control(c, ch, st):
                raise CORE.ApiError("Only the requester or a moderator can resume", 403)
            if now.get("paused_at_ms") is not None:
                now["started_at_ms"] += max(0, _now_ms() - now["paused_at_ms"])
                now["paused_at_ms"] = None
                _schedule_locked_for(ch["id"], st)
        elif kind in ("skip", "stop"):
            if _can_control(c, ch, st):
                if kind == "skip":
                    _advance_locked(ch["id"], st)
                else:
                    st["now"] = None
                    st["votes"] = {}
                    _cancel_timer_locked(st)
            else:
                key = kind
                voters = st["votes"].setdefault(key, set())
                voters.add(uid)
                if len(voters) >= _vote_needed(ch["id"]):
                    if kind == "skip":
                        _advance_locked(ch["id"], st)
                    else:
                        st["now"] = None
                        _cancel_timer_locked(st)
                    st["votes"] = {}
        elif kind == "remove":
            try:
                idx = int((payload or {}).get("index"))
            except (TypeError, ValueError):
                raise CORE.ApiError("bad queue item", 400)
            if idx < 0 or idx >= len(st["queue"]):
                raise CORE.ApiError("That queue item is gone", 404)
            track = st["queue"][idx]
            if _is_mod(c, ch):
                st["queue"].pop(idx)
            elif int(track["requester"]) == uid:
                st["queue"].pop(idx)
            else:
                key = "remove:" + track["id"]
                voters = st["votes"].setdefault(key, set())
                voters.add(uid)
                if len(voters) >= _vote_needed(ch["id"]):
                    st["queue"].pop(idx)
                    st["votes"].pop(key, None)
        st["rev"] += 1
    _emit(ch["id"])
    snap = snapshot(ch["id"])
    snap["vote_needed"] = _vote_needed(ch["id"])
    return snap


def api_skip(c):
    return _control_action(c, "skip", c.body)


def api_pause(c):
    return _control_action(c, "pause", c.body)


def api_resume(c):
    return _control_action(c, "resume", c.body)


def api_stop(c):
    return _control_action(c, "stop", c.body)


def api_remove(c):
    return _control_action(c, "remove", c.body)


def api_loop(c):
    return _control_action(c, "loop", c.body)


# --------------------------------------------------------------------- stream proxy
def _valid_cache(video_id):
    path = _cache_path(video_id)
    try:
        st = os.stat(path)
    except OSError:
        return ""
    if st.st_size <= 0 or time.time() - st.st_mtime > CACHE_TTL:
        try:
            os.unlink(path)
        except OSError:
            pass
        return ""
    return path


def _source(video_id):
    now = time.time()
    with SOURCE_LOCK:
        src = SOURCES.get(video_id)
    if src and float(src.get("expires") or 0) > now + 30:
        return src
    src = PROVIDER.resolve(video_id)
    with SOURCE_LOCK:
        SOURCES[video_id] = src
    return src


def _download(src, video_id):
    path = _cache_path(video_id)
    meta = _meta_path(video_id)
    tmp = "%s.%d.%d.part" % (path, os.getpid(), threading.get_ident())
    url = str(src.get("url") or "")
    if urllib.parse.urlparse(url).scheme not in ("http", "https"):
        raise MusicError("Could not get an audio stream for that track", 502)
    headers = dict(src.get("headers") or {})
    headers.setdefault("User-Agent", "Mozilla/5.0")
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as r, open(tmp, "wb") as f:
            total = 0
            while True:
                chunk = r.read(64 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_TRACK_BYTES:
                    raise MusicError("That track is too large to cache", 502)
                f.write(chunk)
            if total <= 0:
                raise MusicError("The audio stream was empty", 502)
        os.replace(tmp, path)
        with open(meta, "w", encoding="utf-8") as f:
            json.dump({"mime": src.get("mime") or "audio/mp4", "size": os.path.getsize(path),
                       "title": src.get("title") or ""}, f)
        os.utime(path, None)
    except MusicError:
        raise
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, TimeoutError) as e:
        raise MusicError("Could not fetch that track's audio", 502)
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass
    return path


def _ensure_cache(video_id):
    path = _valid_cache(video_id)
    if path:
        return path
    with _cache_lock(video_id):
        path = _valid_cache(video_id)
        if path:
            return path
        try:
            src = _source(video_id)
            return _download(src, video_id)
        except urllib.error.HTTPError as e:
            if e.code in (403, 410):
                with SOURCE_LOCK:
                    SOURCES.pop(video_id, None)
                src = _source(video_id)
                return _download(src, video_id)
            raise MusicError("Could not fetch that track's audio", 502)
        except urllib.error.URLError:
            raise MusicError("Could not fetch that track's audio", 502)
        finally:
            clean_cache()


def _serve(c, path):
    meta = _read_meta(os.path.basename(path)[:-6])
    mime = meta.get("mime") or "audio/mp4"
    try:
        size = os.path.getsize(path)
    except OSError:
        raise CORE.ApiError("Track cache disappeared", 404)
    if size <= 0:
        raise CORE.ApiError("Track cache is empty", 404)
    rng = (c.h.headers.get("Range") or "").strip()
    start, end = 0, size - 1
    status = 200
    if rng:
        m = re.fullmatch(r"bytes=(\d*)-(\d*)", rng)
        if not m or (not m.group(1) and not m.group(2)):
            c.h.send_response(416)
            c.h.send_header("Content-Range", "bytes */%d" % size)
            c.h.send_header("Content-Length", "0")
            c.h.end_headers()
            return
        if not m.group(1):
            suffix = int(m.group(2))
            start = max(0, size - suffix)
        else:
            start = int(m.group(1))
            end = int(m.group(2)) if m.group(2) else size - 1
        if start >= size or end < start:
            c.h.send_response(416)
            c.h.send_header("Content-Range", "bytes */%d" % size)
            c.h.send_header("Content-Length", "0")
            c.h.end_headers()
            return
        end = min(end, size - 1)
        status = 206
    length = end - start + 1
    c.h.send_response(status)
    c.h.send_header("Content-Type", mime)
    c.h.send_header("Content-Length", str(length))
    c.h.send_header("Accept-Ranges", "bytes")
    c.h.send_header("Content-Disposition", "inline")
    c.h.send_header("Cache-Control", "private, max-age=3600")
    c.h.send_header("X-Content-Type-Options", "nosniff")
    if status == 206:
        c.h.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, size))
    c.h.end_headers()
    try:
        with open(path, "rb") as f:
            f.seek(start)
            left = length
            while left > 0:
                chunk = f.read(min(64 * 1024, left))
                if not chunk:
                    break
                c.h.wfile.write(chunk)
                left -= len(chunk)
        try:
            os.utime(path, None)
        except OSError:
            pass
    except (BrokenPipeError, ConnectionResetError, TimeoutError):
        pass


def api_stream(c):
    _disabled()
    ch = _channel(c, _ch_id(c))
    uid = int(c.user["id"])
    _room_required(ch["id"], uid)
    vid = str(getattr(c, "tail", "") or "").strip("/")
    if not ID_RE.fullmatch(vid):
        raise CORE.ApiError("bad track id", 400)
    with LOCK:
        st = STATE.get(ch["id"])
        ids = []
        if st and st.get("now"):
            ids.append(st["now"]["track"]["id"])
        if st:
            ids.extend(t["id"] for t in st["queue"])
    if vid not in ids:
        raise CORE.ApiError("That track is not in this room's queue", 404)
    path = _ensure_cache(vid)
    _serve(c, path)


api_stream.owns_response = True


# --------------------------------------------------------------------- hooks/install
def on_empty(ch_id):
    with LOCK:
        st = STATE.get(int(ch_id))
        if not st:
            return
        st["now"] = None
        st["votes"] = {}
        _cancel_timer_locked(st)
        st["rev"] += 1


def drop(ch_id):
    with LOCK:
        st = STATE.pop(int(ch_id), None)
        if st:
            _cancel_timer_locked(st)


def install(srv, db, permissions, chat, voice):
    global CORE, DB
    CORE, DB = srv, db
    configure(srv)

    srv.route("GET", "/api/music/check", auth=False)(api_check)

    for method, path, fn in (
        ("GET", "/api/time", api_time),
        ("GET", "/api/music/state", api_state),
        ("GET", "/api/music/search", api_search),
        ("POST", "/api/music/add", api_add),
        ("POST", "/api/music/skip", api_skip),
        ("POST", "/api/music/next", api_skip),
        ("POST", "/api/music/pause", api_pause),
        ("POST", "/api/music/resume", api_resume),
        ("POST", "/api/music/stop", api_stop),
        ("POST", "/api/music/remove", api_remove),
        ("POST", "/api/music/loop", api_loop),
    ):
        srv.route(method, path, auth=(path != "/api/time"))(fn)
    srv.route_prefix("GET", "/api/music/stream/")(api_stream)


def bootstrap(conn):
    """Called from server.bootstrap after the social tables exist."""
    try:
        migrate(conn)
    except Exception as e:
        print("[music] permission migration failed: %s" % type(e).__name__, file=sys.stderr, flush=True)
    try:
        clean_cache()
    except Exception:
        pass