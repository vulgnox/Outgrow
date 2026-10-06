#!/usr/bin/env python3
"""Free, card-less persistence for OUTGROW on hosts with an ephemeral disk (Render free, HF Spaces, ...).

Keeps a gzip snapshot of the SQLite DB in a PRIVATE GitHub repo. Every push is a single force-pushed
commit, so the repo never grows. Stdlib only (needs the `git` binary).

  python3 ghsync.py supervise     restore -> run server.py -> push on change (and on shutdown). Container entrypoint.
  python3 ghsync.py seed <db>     one-off: upload an existing DB (run on your own machine to migrate your data)

Env:
  GH_BACKUP_REPO=owner/name       private repo that stores the backup
  GH_BACKUP_TOKEN=...             fine-grained PAT, Contents: read+write on that ONE repo
  GH_BACKUP_URL=...               optional full git URL (overrides the two above; used for tests)
  OUTGROW_DB                      DB path (default /app/data/outgrow.db)
  GH_SYNC_INTERVAL                seconds between change checks (default 60)
  GH_RESTORE_RETRIES              restore attempts before giving up (default 6)

Safety: if the backup repo can't be reached on boot, we REFUSE to start. Starting blank and then pushing
would overwrite the real backup with an empty database.
"""
import gzip
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(ROOT, "server.py")
DB = os.environ.get("OUTGROW_DB", "/app/data/outgrow.db")
INTERVAL = int(os.environ.get("GH_SYNC_INTERVAL", "60"))
RETRIES = int(os.environ.get("GH_RESTORE_RETRIES", "6"))
REPO = os.environ.get("GH_BACKUP_REPO", "")
TOKEN = os.environ.get("GH_BACKUP_TOKEN", "")
URL = os.environ.get("GH_BACKUP_URL") or (f"https://x-access-token:{TOKEN}@github.com/{REPO}.git" if REPO and TOKEN else "")
FILE = "outgrow.db.gz"
WORK = os.path.join(tempfile.gettempdir(), "og-sync")


def log(*a):
    print("[ghsync]", *a, flush=True)


def git(*args, cwd=None, check=True):
    r = subprocess.run(["git", "-c", "user.name=outgrow", "-c", "user.email=outgrow@localhost", *args],
                       cwd=cwd or WORK, env=dict(os.environ, GIT_TERMINAL_PROMPT="0"),
                       capture_output=True, text=True, timeout=180)
    if check and r.returncode:
        msg = (r.stderr or r.stdout or "").strip()
        if TOKEN:
            msg = msg.replace(TOKEN, "***")
        raise RuntimeError(f"git {args[0]} failed: {msg[:300]}")
    return r


def restore():
    """-> 'skip' (local DB already there) | 'restored' | 'empty' (no backup yet). Raises if the repo is unreachable."""
    if os.path.isfile(DB) and os.path.getsize(DB) > 0:
        return "skip"
    tmp = tempfile.mkdtemp()
    try:
        git("clone", "--quiet", "--depth", "1", URL, tmp + "/r", cwd=tmp)
        src = os.path.join(tmp, "r", FILE)
        if not os.path.isfile(src):
            return "empty"
        os.makedirs(os.path.dirname(DB), exist_ok=True)
        part = DB + ".restoring"
        with gzip.open(src, "rb") as f, open(part, "wb") as g:
            shutil.copyfileobj(f, g)
        chk = sqlite3.connect(part)
        ok = chk.execute("PRAGMA quick_check").fetchone()[0]
        chk.close()
        if ok != "ok":
            os.unlink(part)
            raise RuntimeError("backup failed integrity check: " + str(ok))
        os.replace(part, DB)
        return "restored"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def snapshot_push(src_path):
    os.makedirs(WORK, exist_ok=True)
    if not os.path.isdir(os.path.join(WORK, ".git")):
        git("init", "--quiet", "-b", "main")
        git("remote", "add", "origin", URL)
    snap = os.path.join(WORK, "snap.db")
    s, d = sqlite3.connect(src_path, timeout=15), sqlite3.connect(snap)
    s.backup(d)  # consistent copy even while the server is writing
    d.close()
    s.close()
    with open(snap, "rb") as f, gzip.open(os.path.join(WORK, FILE), "wb", 6) as g:
        shutil.copyfileobj(f, g)
    os.unlink(snap)
    git("add", FILE)
    has_head = git("rev-parse", "--verify", "HEAD", check=False).returncode == 0
    git("commit", "--quiet", "--allow-empty", *(["--amend"] if has_head else []), "-m", "snapshot")
    git("push", "--quiet", "--force", "origin", "HEAD:main")
    log("pushed snapshot", time.strftime("%H:%M:%S"))


def supervise():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    if not URL:
        log("WARNING: GH_BACKUP_REPO / GH_BACKUP_TOKEN not set. Running WITHOUT backup: data is lost on restart.")
        os.execv(sys.executable, [sys.executable, SERVER])
    state = None
    for i in range(RETRIES):
        try:
            state = restore()
            break
        except Exception as e:
            log(f"restore attempt {i + 1}/{RETRIES} failed: {e}")
            if i + 1 < RETRIES:
                time.sleep(5 * (i + 1))
    if state is None:
        sys.exit("[ghsync] cannot reach the backup repo. Refusing to start with an empty DB (would overwrite the backup).")
    log("restore:", state)

    proc = subprocess.Popen([sys.executable, SERVER])
    stop = threading.Event()

    def on_term(*_):
        stop.set()
        proc.terminate()

    signal.signal(signal.SIGTERM, on_term)
    signal.signal(signal.SIGINT, on_term)

    mon, last = None, None
    while not stop.is_set() and proc.poll() is None:
        stop.wait(min(INTERVAL, 5) if last is None else INTERVAL)
        try:
            if not os.path.isfile(DB):
                continue
            if mon is None:
                mon = sqlite3.connect(DB, timeout=10)
            v = mon.execute("PRAGMA data_version").fetchone()[0]  # changes whenever another connection commits
            if v != last:
                if last is not None or state in ("empty", "skip"):
                    snapshot_push(DB)
                last = v
        except Exception as e:
            log("push failed (will retry):", e)

    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        proc.kill()
    try:
        if os.path.isfile(DB):
            snapshot_push(DB)  # final flush after the server has exited
    except Exception as e:
        log("final push failed:", e)
    sys.exit(0 if stop.is_set() else (proc.returncode or 0))


def seed(path):
    if not URL:
        sys.exit("Set GH_BACKUP_REPO and GH_BACKUP_TOKEN first.")
    if not os.path.isfile(path):
        sys.exit(f"No such file: {path}")
    snapshot_push(path)
    log("seeded. Deploy now; the server restores this on first boot.")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "supervise"
    if cmd == "supervise":
        supervise()
    elif cmd == "seed" and len(sys.argv) > 2:
        seed(sys.argv[2])
    else:
        sys.exit(__doc__)
