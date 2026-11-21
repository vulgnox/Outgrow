"""Phase 3: uploads (channels + DMs), stickers, link previews, limits and membership checks."""
import base64
import hashlib
import http.cookiejar
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

PORT = 8804
BASE = f"http://127.0.0.1:{PORT}"
tmp = tempfile.mkdtemp()
DBPATH = os.path.join(tmp, "t.db")
env = dict(os.environ, PORT=str(PORT), RAGDAMAXING_DB=DBPATH, RAGDAMAXING_ADMINS="boss")
srv = subprocess.Popen([sys.executable, "server.py"], env=env, cwd=os.path.dirname(os.path.abspath(__file__)),
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
time.sleep(1.6)

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


class Client:
    def __init__(self):
        self.cj = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))

    def call(self, method, path, body=None):
        req = urllib.request.Request(BASE + path, method=method,
                                     data=json.dumps(body or {}).encode() if method == "POST" else None,
                                     headers={"Content-Type": "application/json"})
        try:
            with self.op.open(req) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def raw(self, path):
        req = urllib.request.Request(BASE + path)
        try:
            with self.op.open(req) as r:
                return r.status, r.read(), dict(r.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read(), dict(e.headers)

    def up(self, path, data, name="file.png", ctype="image/png"):
        req = urllib.request.Request(BASE + path, data=data, method="POST", headers={
            "X-File-Name": urllib.parse.quote(name),
            "X-File-Type": ctype,
            "Content-Type": "application/octet-stream",
        })
        try:
            with self.op.open(req) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")


ok = True


def check(name, cond, extra=""):
    global ok
    print(("PASS " if cond else "FAIL ") + name, extra if not cond else "")
    ok = ok and cond


def uid(cl):
    return cl.call("GET", "/api/me")[1]["user"]["id"]


def total(cl, ch):
    return cl.call("GET", f"/api/ch/messages?ch={ch}")[1]["messages"]


try:
    a, b, c = Client(), Client(), Client()
    a.call("POST", "/api/register", {"username": "owner", "pin": "1234", "crew_name": "Alpha"})
    code = a.call("GET", "/api/crew")[1]["crew"]["code"]
    b.call("POST", "/api/register", {"username": "member", "pin": "1234", "crew_code": code})
    c.call("POST", "/api/register", {"username": "outsider", "pin": "1234", "crew_name": "Beta"})
    ua, ub, uc = uid(a), uid(b), uid(c)
    sid = a.call("GET", "/api/servers")[1]["servers"][0]["id"]
    ch = a.call("GET", f"/api/server?sid={sid}")[1]["channels"][0]["id"]

    # ---------------------------------------------------------------- upload basics
    s, r = a.up(f"/api/upload?ch={ch}", PNG)
    check("owner uploads a PNG", s == 200 and r["file"]["mime"] == "image/png", r)
    fid = r["file"]["id"]
    check("image dimensions detected", r["file"]["w"] == 1 and r["file"]["h"] == 1, r)
    check("upload keeps a sane name", r["file"]["name"] == "file.png", r)

    s, body, hdrs = a.raw(f"/api/file?id={fid}")
    check("owner fetches unsent file", s == 200 and body == PNG, s)
    check("image served inline as image/png", hdrs.get("Content-Type") == "image/png"
          and "inline" in hdrs.get("Content-Disposition", ""), hdrs)
    check("file response is nosniff", hdrs.get("X-Content-Type-Options") == "nosniff", hdrs)

    s, body, _ = b.raw(f"/api/file?id={fid}")
    check("unattached file hidden from others", s == 404, s)

    s, body, _ = Client().raw(f"/api/file?id={fid}")
    check("file route needs login", s == 401, s)

    # ---------------------------------------------------------------- limits / validation
    s, r = a.up(f"/api/upload?ch={ch}", PNG + b"x" * (8 * 1024 * 1024))
    check("8 MB limit enforced", s == 413, (s, r))

    s, r = a.up(f"/api/upload?ch={ch}", b"<html>not a png</html>", "evil.png", "image/png")
    check("fake image rejected", s == 400, (s, r))

    s, r = a.up(f"/api/upload?ch={ch}", bytes(range(256)) * 4, "bin.dat", "application/octet-stream")
    check("unsupported binary rejected", s == 400, (s, r))

    s, r = a.up(f"/api/upload?ch={ch}", b"# notes\nhello\n", "notes.md", "text/markdown")
    check("text/markdown accepted as text", s == 200 and r["file"]["mime"] == "text/plain", r)
    notes = r["file"]["id"]

    s, r = a.up(f"/api/upload?ch={ch}", b"hello", "x.txt", "text/plain")
    check("non member cannot upload", c.up(f"/api/upload?ch={ch}", b"hello", "x.txt", "text/plain")[0] == 404)

    # ---------------------------------------------------------------- attach permission
    srvj = a.call("GET", f"/api/server?sid={sid}")[1]
    everyone = next(x for x in srvj["roles"] if x["default"])
    base = everyone["perms"]
    s, r = a.call("POST", "/api/role/update", {"sid": sid, "role": everyone["id"], "name": everyone["name"],
                                               "color": everyone["color"], "perms": base & ~4})
    check("role update for attach test", s == 200, r)
    s, r = b.up(f"/api/upload?ch={ch}", PNG)
    check("attach permission required to upload", s == 403, (s, r))
    a.call("POST", "/api/role/update", {"sid": sid, "role": everyone["id"], "name": everyone["name"],
                                        "color": everyone["color"], "perms": base})

    # ---------------------------------------------------------------- send + share
    s, r = a.call("POST", "/api/ch/send", {"ch": ch, "text": "look", "files": [fid]})
    check("message carries the file", s == 200 and r["message"]["files"][0]["id"] == fid, r)
    mid = r["message"]["id"]

    s, body, _ = b.raw(f"/api/file?id={fid}")
    check("member can fetch an attached file", s == 200 and body == PNG, s)
    s, body, _ = c.raw(f"/api/file?id={fid}")
    check("outsider cannot fetch an attached file", s == 404, s)

    s, r = b.call("POST", "/api/ch/send", {"ch": ch, "text": "steal", "files": [fid]})
    check("cannot re-attach an existing file", s == 400, (s, r))

    s, r = a.call("POST", "/api/ch/send", {"ch": ch, "text": "", "files": [notes]})
    check("caption optional with a file", s == 200 and r["message"]["text"] == "", r)
    s, body, hdrs = b.raw(f"/api/file?id={notes}")
    check("text file downloads as attachment", s == 200 and "attachment" in hdrs.get("Content-Disposition", ""), hdrs)

    ids = []
    for i in range(5):
        st, rr = a.up(f"/api/upload?ch={ch}", PNG, f"p{i}.png")
        if st == 200:
            ids.append(rr["file"]["id"])
    s, r = a.call("POST", "/api/ch/send", {"ch": ch, "text": "five", "files": ids})
    check("max 4 files per message", s == 400, (s, r))
    s, r = a.call("POST", "/api/ch/send", {"ch": ch, "text": "four", "files": ids[:4]})
    check("four files send fine", s == 200 and len(r["message"]["files"]) == 4, r)

    s, r = a.call("POST", "/api/ch/send", {"ch": ch, "text": "x", "files": [999999]})
    check("unknown upload id rejected", s == 400, (s, r))

    # files cannot cross channels
    s, ch2 = a.call("POST", "/api/channel/create", {"sid": sid, "name": "other"})
    ch2 = ch2["channel_id"]
    s, rr = a.up(f"/api/upload?ch={ch2}", PNG, "cross.png")
    s, r = a.call("POST", "/api/ch/send", {"ch": ch, "text": "cross", "files": [rr["file"]["id"]]})
    check("upload scoped to its channel", s == 400, (s, r))

    # ---------------------------------------------------------------- DMs
    s, rr = a.up(f"/api/upload?thread=dm:{ub}", PNG, "dm.png")
    check("DM upload by participant", s == 200, rr)
    dmf = rr["file"]["id"]
    s, body, _ = b.raw(f"/api/file?id={dmf}")
    check("DM file hidden before it is sent", s == 404, s)
    s, r = a.call("POST", "/api/chat/send", {"thread": f"dm:{ub}", "text": "dm pic", "files": [dmf]})
    check("DM message carries the file", s == 200 and r["message"]["files"][0]["id"] == dmf, r)
    dmid = r["message"]["id"]
    s, body, _ = b.raw(f"/api/file?id={dmf}")
    check("DM recipient can fetch it", s == 200 and body == PNG, s)
    s, r = c.up(f"/api/upload?thread=dm:{ub}", PNG, "sneak.png")
    check("outsider cannot upload into a DM", s in (403, 404), (s, r))
    s, body, _ = c.raw(f"/api/file?id={dmf}")
    check("outsider cannot fetch a DM file", s == 404, s)

    s, r = a.call("POST", "/api/chat/delete", {"id": dmid})
    check("delete DM message", s == 200, r)
    s, body, _ = b.raw(f"/api/file?id={dmf}")
    check("deleted message revokes recipient access", s == 404, s)
    s, body, _ = a.raw(f"/api/file?id={dmf}")
    check("uploader keeps their own file", s == 200, s)

    # ---------------------------------------------------------------- stickers
    s, r = a.call("GET", "/api/stickers")
    check("sticker catalog served", s == 200 and len(r["stickers"]) == 24, s)
    s, r = a.call("POST", "/api/ch/send", {"ch": ch, "text": "", "sticker": "party"})
    check("sticker sends without text", s == 200 and r["message"]["sticker"] == "party"
          and r["message"]["text"] == "", r)
    s, r = a.call("POST", "/api/ch/send", {"ch": ch, "text": "", "sticker": "nope"})
    check("unknown sticker rejected", s == 400, (s, r))
    s, r = a.call("POST", "/api/ch/send", {"ch": ch, "text": ""})
    check("empty message rejected", s == 400, (s, r))
    s, r = a.call("POST", "/api/chat/send", {"thread": f"dm:{ub}", "text": "", "sticker": "gg"})
    check("stickers work in DMs", s == 200 and r["message"]["sticker"] == "gg", r)

    # ---------------------------------------------------------------- previews
    url = "https://example.com/story"
    conn = sqlite3.connect(DBPATH)
    conn.execute("INSERT OR REPLACE INTO link_previews(key,url,title,desc,image,site,ts) VALUES(?,?,?,?,?,?,?)",
                 (hashlib.sha256(url.encode()).hexdigest()[:32], url, "A story", "What happened next", "", "Example", time.time()))
    conn.commit()
    conn.close()
    s, r = a.call("POST", "/api/ch/send", {"ch": ch, "text": f"read {url} today"})
    check("message attaches a cached preview", s == 200 and r["message"]["preview"]["title"] == "A story", r)
    s, r = a.call("GET", "/api/preview?url=" + urllib.parse.quote("http://127.0.0.1/", safe=""))
    check("SSRF: loopback preview blocked", s == 400, (s, r))
    s, r = a.call("GET", "/api/preview?url=" + urllib.parse.quote("file:///etc/passwd", safe=""))
    check("SSRF: file scheme rejected", s == 400, (s, r))
    s, r = a.call("GET", "/api/preview?url=" + urllib.parse.quote("http://10.0.0.5/x", safe=""))
    check("SSRF: private range blocked", s == 400, (s, r))
    s, r = a.call("GET", "/api/preview?url=" + urllib.parse.quote("http://127.0.0.1:8804/", safe=""))
    check("SSRF: odd ports blocked", s == 400, (s, r))

    # ---------------------------------------------------------------- cleanup on delete
    s, r = a.call("POST", "/api/ch/delete", {"ch": ch, "id": mid})
    check("delete message with attachment", s == 200, r)
    s, body, _ = b.raw(f"/api/file?id={fid}")
    check("channel file revoked after delete", s == 404, s)

    msgs = total(b, ch)
    check("server still reads the channel", isinstance(msgs, list) and len(msgs) >= 4, len(msgs))
    check("sticker message packed for readers", any(m.get("sticker") == "party" for m in msgs), msgs[-3:])
finally:
    srv.terminate()
    try:
        out, _ = srv.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        srv.kill()
        out = b""
    tail = str(out or "")[-1200:]
    if "Traceback" in tail:
        print(tail)

print("\nALL OK" if ok else "\nFAILURES")
sys.exit(0 if ok else 1)
