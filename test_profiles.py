"""Phase 4: profiles, avatars, banners, custom status, visibility and image access."""
import base64
import http.cookiejar
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

PORT = 8805
BASE = f"http://127.0.0.1:{PORT}"
tmp = tempfile.mkdtemp()
DBPATH = os.path.join(tmp, "t.db")
UPDIR = os.path.join(tmp, "uploads")
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

    def up(self, path, data, name="image.png", ctype="image/png"):
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


def path_of(url):
    p = urllib.parse.urlsplit(url)
    return p.path + "?" + p.query


def upload_id(url):
    m = re.search(r"[?&]v=(\d+)", url or "")
    return int(m.group(1)) if m else 0


try:
    a, b, c, d, boss = Client(), Client(), Client(), Client(), Client()
    a.call("POST", "/api/register", {"username": "owner", "pin": "1234", "crew_name": "Alpha"})
    code = a.call("GET", "/api/crew")[1]["crew"]["code"]
    b.call("POST", "/api/register", {"username": "member", "pin": "1234", "crew_code": code})
    c.call("POST", "/api/register", {"username": "friend", "pin": "1234", "crew_name": "Beta"})
    d.call("POST", "/api/register", {"username": "outsider", "pin": "1234", "crew_name": "Gamma"})
    boss.call("POST", "/api/register", {"username": "boss", "pin": "1234", "crew_name": "BossCrew"})
    for cl in (a, b, c, d, boss):
        cl.call("GET", "/api/servers")
    ua, ub, uc, ud = uid(a), uid(b), uid(c), uid(d)
    alpha_sid = a.call("GET", "/api/servers")[1]["servers"][0]["id"]
    c.call("GET", "/api/servers")

    # ---------------------------------------------------------------- profile visibility
    s, r = a.call("GET", f"/api/profile?uid={ua}")
    check("own profile loads", s == 200 and r["user"]["id"] == ua, r)
    check("profile has a social block", "social" in r and isinstance(r["social"], dict), r.keys())
    check("profile starts with no avatar or banner",
          r["social"]["avatar"] == "" and r["social"]["banner"] == "", r["social"])
    check("profile starts with no status", r["social"]["status"] == {}, r["social"]["status"])
    check("profile starts with an empty bio and banner style",
          r["social"]["bio"] == "" and r["social"]["pronouns"] == "" and r["social"]["banner_style"] == "", r["social"])
    check("profile keeps public stats", "level" in r and "stats" in r and "heat" in r, r.keys())
    check("profile leaks no private tables",
          not ({"reflections", "mood", "urges", "tests", "dms"} & set(r.keys())), r.keys())

    s, r = b.call("GET", f"/api/profile?uid={ua}")
    check("same-crew member can view profile", s == 200 and r["user"]["me"] is False, r)
    check("same-crew profile carries social identity", r["social"]["since"] != "", r["social"])
    check("outsider blocked before friendship", c.call("GET", f"/api/profile?uid={ua}")[0] == 404)
    check("stranger blocked", d.call("GET", f"/api/profile?uid={ua}")[0] == 404)
    check("profile needs login", Client().call("GET", f"/api/profile?uid={ua}")[0] == 401)
    check("unknown uid is 404", a.call("GET", "/api/profile?uid=999999")[0] == 404)
    check("bad uid is 404", a.call("GET", "/api/profile?uid=nope")[0] == 404)

    s, r = b.call("GET", f"/api/profile/social?uid={ua}")
    check("social endpoint returns the card", s == 200 and r["user"]["id"] == ua and "social" in r, r)
    check("social endpoint is membership-checked", c.call("GET", f"/api/profile/social?uid={ua}")[0] == 404)
    check("social endpoint needs login", Client().call("GET", f"/api/profile/social?uid={ua}")[0] == 401)

    # ---------------------------------------------------------------- custom status
    s, r = a.call("POST", "/api/profile/status", {"text": "grinding integrals", "emoji": "📚"})
    check("set custom status", s == 200 and r["social"]["status"]["text"] == "grinding integrals"
          and r["social"]["status"]["emoji"] == "📚", r)
    s, r = b.call("GET", f"/api/profile?uid={ua}")
    check("status is visible to members", s == 200 and r["social"]["status"]["text"] == "grinding integrals", r)
    check("status is not visible to outsiders", c.call("GET", f"/api/profile?uid={ua}")[0] == 404)
    check("status length is capped", a.call("POST", "/api/profile/status", {"text": "x" * 81})[0] == 400)
    check("status emoji length is capped", a.call("POST", "/api/profile/status", {"emoji": "📚" * 17})[0] == 400)

    b.call("POST", "/api/profile/status", {"text": "member status", "emoji": "🫡"})
    s, r = a.call("GET", f"/api/profile?uid={ub}")
    check("each user owns their status", s == 200 and r["social"]["status"]["text"] == "member status", r)
    s, r = b.call("GET", f"/api/profile?uid={ua}")
    check("another user's status update did not change mine",
          r["social"]["status"]["text"] == "grinding integrals", r["social"]["status"])
    s, r = a.call("POST", "/api/profile/status", {"text": "", "emoji": ""})
    check("clear status", s == 200 and r["social"]["status"] == {}, r)
    a.call("POST", "/api/profile/status", {"text": "ready to grind", "emoji": "🔥"})

    # ---------------------------------------------------------------- bio, pronouns, banner gradient
    s, r = a.call("POST", "/api/profile/details", {
        "bio": "Chasing a 9.2 GPA one deep block at a time.", "pronouns": "he / him", "banner_style": "aurora"})
    check("save profile details", s == 200 and r["social"]["bio"].startswith("Chasing")
          and r["social"]["pronouns"] == "he / him" and r["social"]["banner_style"] == "aurora", r)
    check("details do not erase the status", r["social"]["status"].get("text") == "ready to grind", r["social"])
    s, r = b.call("GET", f"/api/profile?uid={ua}")
    check("details are visible to the crew", s == 200 and r["social"]["banner_style"] == "aurora"
          and r["social"]["pronouns"] == "he / him", r)
    check("details are hidden from outsiders", c.call("GET", f"/api/profile?uid={ua}")[0] == 404)
    check("bio is capped", a.call("POST", "/api/profile/details", {"bio": "x" * 161})[0] == 400)
    check("pronouns are capped", a.call("POST", "/api/profile/details", {"pronouns": "x" * 25})[0] == 400)
    check("unknown banner style rejected",
          a.call("POST", "/api/profile/details", {"banner_style": "neon-vaporwave"})[0] == 400)
    check("unknown banner style leaves the saved style alone",
          a.call("GET", f"/api/profile?uid={ua}")[1]["social"]["banner_style"] == "aurora")
    check("profile details need login", Client().call("POST", "/api/profile/details", {"bio": "x"})[0] == 401)

    s, r = b.call("GET", "/api/servers")
    check("status appears in chat people cards",
          r["people"][str(ua)].get("status", {}).get("text") == "ready to grind", r["people"].get(str(ua)))
    s, r = b.call("GET", f"/api/server?sid={alpha_sid}")
    am = next((m for m in r["members"] if m["id"] == ua), None)
    check("status appears in server member cards", am and am.get("status", {}).get("text") == "ready to grind", am)

    # ---------------------------------------------------------------- avatar upload/serving
    s, r = a.up("/api/profile/upload?kind=avatar", PNG, "me.png")
    check("upload avatar", s == 200 and r["social"]["avatar"], r)
    av = r["social"]["avatar"]
    check("avatar url is scoped to the profile route", "kind=avatar" in av and "uid=%d" % ua in av, av)
    s, body, hdrs = a.raw(path_of(av))
    check("owner fetches avatar", s == 200 and body == PNG, s)
    check("avatar is served inline as an image", hdrs.get("Content-Type") == "image/png"
          and "inline" in hdrs.get("Content-Disposition", ""), hdrs)
    check("avatar response is nosniff", hdrs.get("X-Content-Type-Options") == "nosniff", hdrs)
    s, body, _ = b.raw(path_of(av))
    check("same-crew member fetches avatar", s == 200 and body == PNG, s)
    check("outsider cannot fetch avatar", c.raw(path_of(av))[0] == 404)
    check("anonymous cannot fetch avatar", Client().raw(path_of(av))[0] == 401)

    s, r = b.call("GET", "/api/servers")
    check("avatar appears in chat people cards", r["people"][str(ua)].get("pimg") == av, r["people"].get(str(ua)))
    s, r = b.call("GET", f"/api/server?sid={alpha_sid}")
    am = next((m for m in r["members"] if m["id"] == ua), None)
    check("avatar appears in server member cards", am and am.get("pimg") == av, am)
    s, r = a.call("GET", "/api/me")
    check("avatar appears on /api/me", r["user"].get("pimg") == av, r["user"])

    # ---------------------------------------------------------------- friendship opens cross-crew profiles
    a.call("POST", "/api/friend/request", {"username": "friend"})
    c.call("POST", "/api/friend/accept", {"uid": ua})
    s, r = c.call("GET", f"/api/profile?uid={ua}")
    check("friend across crews can view profile", s == 200 and r["social"]["friend"] is True, r)
    check("friend can fetch avatar", c.raw(path_of(av))[0] == 200)
    s, r = c.call("GET", "/api/friends")
    fr = next((x for x in r["friends"] if x["id"] == ua), None)
    check("avatar and status appear in friend cards",
          fr and fr.get("pimg") == av and fr.get("status", {}).get("text") == "ready to grind", fr)

    # ---------------------------------------------------------------- banner + limits
    s, r = a.up("/api/profile/upload?kind=banner", PNG, "banner.png")
    check("upload banner", s == 200 and r["social"]["banner"], r)
    check("uploading a banner clears the gradient choice", r["social"]["banner_style"] == "", r["social"])
    ban = r["social"]["banner"]
    s, body, hdrs = b.raw(path_of(ban))
    check("member fetches banner", s == 200 and body == PNG and hdrs.get("Content-Type") == "image/png", s)
    check("friend fetches banner", c.raw(path_of(ban))[0] == 200)
    check("outsider cannot fetch banner", d.raw(path_of(ban))[0] == 404)

    check("avatar size limit", a.up("/api/profile/upload?kind=avatar",
                                    PNG + b"x" * (2 * 1024 * 1024))[0] == 413)
    check("banner size limit", a.up("/api/profile/upload?kind=banner",
                                    PNG + b"x" * (4 * 1024 * 1024))[0] == 413)
    check("fake image rejected", a.up("/api/profile/upload?kind=avatar",
                                      b"<html>not an image</html>", "evil.png", "image/png")[0] == 400)
    check("non-image rejected", a.up("/api/profile/upload?kind=banner",
                                     b"%PDF-1.4\nnot really", "x.pdf", "application/pdf")[0] == 400)
    check("avatar upload needs login", Client().up("/api/profile/upload?kind=avatar", PNG)[0] == 401)
    check("invalid image kind rejected", a.up("/api/profile/upload?kind=weird", PNG)[0] == 400)
    check("invalid image route kind rejected", a.call("GET", f"/api/profile/img?uid={ua}&kind=weird")[0] == 400)
    check("image route hides users with no avatar", a.call("GET", f"/api/profile/img?uid={ub}&kind=avatar")[0] == 404)

    # ---------------------------------------------------------------- replace + clear
    old_av = upload_id(av)
    s, r = a.up("/api/profile/upload?kind=avatar", PNG, "new.png")
    new_av = r["social"]["avatar"]
    check("replacing an avatar returns a new version", s == 200 and upload_id(new_av) != old_av, (old_av, new_av))
    db = sqlite3.connect(DBPATH)
    old_row = db.execute("SELECT id,disk FROM uploads WHERE id=?", (old_av,)).fetchone()
    db.close()
    check("old avatar upload row is deleted", old_row is None, old_row)
    check("old avatar bytes are deleted", not os.path.exists(os.path.join(UPDIR, "%d.png" % old_av)))
    check("new avatar still serves", b.raw(path_of(new_av))[0] == 200)

    s, r = a.call("POST", "/api/profile/clear", {"kind": "avatar"})
    check("clear avatar", s == 200 and r["social"]["avatar"] == "" and r["social"]["banner"] == ban, r)
    check("cleared avatar is gone", a.call("GET", f"/api/profile/img?uid={ua}&kind=avatar")[0] == 404)
    check("banner survives an avatar clear", b.raw(path_of(ban))[0] == 200)
    s, r = a.call("POST", "/api/profile/clear", {"kind": "banner"})
    check("clear banner", s == 200 and r["social"]["banner"] == "", r)
    check("cleared banner is gone", a.call("GET", f"/api/profile/img?uid={ua}&kind=banner")[0] == 404)
    check("invalid clear kind rejected", a.call("POST", "/api/profile/clear", {"kind": "weird"})[0] == 400)
    check("clear without a set image is harmless",
          a.call("POST", "/api/profile/clear", {"kind": "avatar"})[0] == 200)

    # ---------------------------------------------------------------- block + admin
    c.up("/api/profile/upload?kind=avatar", PNG, "friend.png")
    s, r = c.call("GET", f"/api/profile?uid={uc}")
    cav = r["social"]["avatar"]
    check("friend avatar serves before the block", a.raw(path_of(cav))[0] == 200)
    c.call("POST", "/api/block", {"uid": ua, "on": True})
    check("block hides the profile", a.call("GET", f"/api/profile?uid={uc}")[0] == 404)
    check("block revokes avatar access", a.raw(path_of(cav))[0] == 404)
    check("blocked user keeps their own avatar", c.raw(path_of(cav))[0] == 200)
    check("block does not hide your own profile", a.call("GET", f"/api/profile?uid={ua}")[0] == 200)
    check("block is symmetric for profile viewing", c.call("GET", f"/api/profile?uid={ua}")[0] == 404)
    c.call("POST", "/api/block", {"uid": ua, "on": False})
    check("unblock does not restore a removed friendship", a.call("GET", f"/api/profile?uid={uc}")[0] == 404)
    check("global admin can view any profile", boss.call("GET", f"/api/profile?uid={uc}")[0] == 200)
    check("global admin can fetch the avatar", boss.raw(path_of(cav))[0] == 200)

    # ---------------------------------------------------------------- regression: chat still packs people
    s, r = b.call("GET", f"/api/ch/messages?ch={a.call('GET', f'/api/server?sid={alpha_sid}')[1]['channels'][0]['id']}")
    check("channel read still works with profiles joined", s == 200 and "people" in r, r)
finally:
    srv.terminate()
    try:
        out, _ = srv.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        srv.kill()
        out = b""
    tail = str(out or "")[-1600:]
    if "Traceback" in tail:
        print(tail)

print("\nALL OK" if ok else "\nFAILURES")
sys.exit(0 if ok else 1)
