"""Custom server expressions: per-server emoji, stickers, GIFs and reactions."""
import base64
import http.cookiejar
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

PORT = 8807
BASE = f"http://127.0.0.1:{PORT}"
tmp = tempfile.mkdtemp()
env = dict(os.environ, PORT=str(PORT), RAGDAMAXING_DB=os.path.join(tmp, "t.db"),
           RAGDAMAXING_ADMINS="boss")
srv = subprocess.Popen([sys.executable, "server.py"], env=env,
                       cwd=os.path.dirname(os.path.abspath(__file__)),
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
time.sleep(1.6)

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
GIF = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")


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
        try:
            with self.op.open(urllib.request.Request(BASE + path)) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

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


try:
    a, b, c = Client(), Client(), Client()
    a.call("POST", "/api/register", {"username": "owner", "pin": "1234", "crew_name": "Assets"})
    code = a.call("GET", "/api/crew")[1]["crew"]["code"]
    b.call("POST", "/api/register", {"username": "member", "pin": "1234", "crew_code": code})
    c.call("POST", "/api/register", {"username": "outsider", "pin": "1234", "crew_name": "Elsewhere"})
    servers = a.call("GET", "/api/servers")[1]["servers"]
    sid = servers[0]["id"]
    ch = a.call("GET", f"/api/server?sid={sid}")[1]["channels"][0]["id"]

    s, r = c.call("GET", f"/api/ch/assets?server={sid}")
    check("outsider cannot list server expressions", s == 404, (s, r))

    s, r = a.up(f"/api/upload?asset_server={sid}", PNG, "heart.png")
    check("owner uploads an expression image", s == 200, (s, r))
    emoji_upload = r.get("file", {}).get("id")

    s, r = a.call("POST", "/api/ch/assets", {"server": sid, "kind": "emoji", "name": "crew-heart", "upload": emoji_upload})
    check("owner adds custom emoji", s == 200 and r["asset"]["slug"] == "crew-heart", (s, r))
    emoji_id = r.get("asset", {}).get("id")

    s, r = b.up(f"/api/upload?asset_server={sid}", PNG, "cat.png")
    sticker_upload = r.get("file", {}).get("id")
    s, r = b.call("POST", "/api/ch/assets", {"server": sid, "kind": "sticker", "name": "study cat", "upload": sticker_upload})
    check("member adds a custom sticker", s == 200 and r["asset"]["kind"] == "sticker", (s, r))
    sticker_id = r.get("asset", {}).get("id")

    s, r = b.up(f"/api/upload?asset_server={sid}", GIF, "hype.gif", "image/gif")
    gif_upload = r.get("file", {}).get("id")
    s, r = b.call("POST", "/api/ch/assets", {"server": sid, "kind": "gif", "name": "hype", "upload": gif_upload})
    check("member adds a custom GIF", s == 200 and r["asset"]["kind"] == "gif", (s, r))
    gif_id = r.get("asset", {}).get("id")

    s, r = b.call("GET", f"/api/ch/assets?server={sid}")
    kinds = {x["kind"] for x in r.get("assets", [])}
    check("members see all three expression types", s == 200 and kinds == {"emoji", "sticker", "gif"}, r)
    check("custom emoji appears in the server catalog", any(x["id"] == emoji_id for x in r["assets"]), r)

    s, r = b.raw(f"/api/file?id={emoji_upload}")
    check("another member can fetch the expression image", s == 200 and r == PNG, (s, len(r)))
    s, r = c.raw(f"/api/file?id={emoji_upload}")
    check("outsider cannot fetch the expression image", s == 404, (s, r))

    s, r = b.call("POST", "/api/ch/send", {"ch": ch, "text": "hello :crew-heart:"})
    check("custom emoji can be sent in text", s == 200 and "crew-heart" in r["message"]["text"], (s, r))
    s, r = b.call("POST", "/api/ch/send", {"ch": ch, "text": "", "sticker": "a%d" % sticker_id})
    check("custom sticker sends", s == 200 and r["message"]["sticker"] == "a%d" % sticker_id, (s, r))
    s, r = b.call("POST", "/api/ch/send", {"ch": ch, "text": "", "sticker": "g%d" % gif_id})
    check("custom GIF sends", s == 200 and r["message"]["sticker"] == "g%d" % gif_id, (s, r))
    mid = r["message"]["id"]

    s, r = b.call("POST", "/api/ch/react", {"ch": ch, "id": mid, "emoji": ":crew-heart:"})
    check("custom emoji works as a reaction", s == 200 and ":crew-heart:" in r.get("re", {}), (s, r))
    s, r = b.call("POST", "/api/ch/react", {"ch": ch, "id": mid, "emoji": ":missing:"})
    check("unknown custom reaction rejected", s == 400, (s, r))

    s, r = a.call("POST", "/api/ch/assets", {"server": sid, "kind": "gif", "name": "not-a-gif", "upload": emoji_upload})
    check("GIF slot rejects a non-GIF", s == 400, (s, r))
    s, r = c.up(f"/api/upload?asset_server={sid}", PNG)
    check("outsider cannot upload expressions", s == 403, (s, r))

    s, r = b.call("POST", "/api/ch/assets/delete", {"id": sticker_id})
    check("uploader can remove their sticker", s == 200, (s, r))
    s, r = b.call("GET", f"/api/ch/assets?server={sid}")
    gone = next(x for x in r["assets"] if x["id"] == sticker_id)
    check("removed expression is inactive but retained", gone["active"] is False, gone)
    s, r = a.call("POST", "/api/ch/assets/delete", {"id": emoji_id})
    check("server owner can remove an expression", s == 200, (s, r))
    s, r = b.call("POST", "/api/ch/assets/delete", {"id": emoji_id})
    check("non-owner cannot remove another member's expression", s in (403, 404), (s, r))

    print("RESULT", "PASS" if ok else "FAIL")
except Exception:
    import traceback
    traceback.print_exc()
    ok = False
finally:
    srv.terminate()
    try:
        srv.wait(timeout=5)
    except subprocess.TimeoutExpired:
        srv.kill()
    out = srv.stdout.read() if srv.stdout else ""
    if out and not ok:
        print("--- server output ---\n" + out[-3000:])
    sys.exit(0 if ok else 1)
