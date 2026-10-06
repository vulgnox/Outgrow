# Hosting RAGDAMAXING on a VPS

RAGDAMAXING is plain Python 3 (standard library only) + one SQLite file. No Docker, no pip, no database server.
It needs about 50 MB of RAM and a few MB of disk, so a 1-core / 2 GB / 10 GB VPS is plenty.

Two people are involved: **the host** (owns the VPS) and **the owner** (owns the code, the data and the public URL).

---

## 1. Host: install (about 2 minutes)

On the VPS (Ubuntu 22.04+ or Debian 11+), as a user with sudo:

```bash
git clone https://github.com/<OWNER>/<REPO>.git /tmp/ragdamaxing-src
sudo bash /tmp/ragdamaxing-src/deploy/install.sh
```

That script (read it first, it is short) does everything:

- creates an unprivileged `ragdamaxing` user and puts the app in `/opt/ragdamaxing/app`
- installs `ragdamaxing.service` (sandboxed: it can only write to its own `data/` folder, max 400 MB RAM, 70% of one core)
- listens on `127.0.0.1:8765` only, so nothing is exposed to the internet until step 2
- sets the server clock to IST for the app only (the streak day rolls over at 3 AM IST, not UTC). The rest of the VPS is untouched
- installs a daily database backup (kept 14 days in `/opt/ragdamaxing/backups`)
- installs an **auto-update timer**: every 5 minutes it pulls the owner's latest push from GitHub, restarts the app, and **rolls back automatically** if the new version has a syntax error or fails to start

Config lives in `/etc/ragdamaxing.env`. After editing: `sudo systemctl restart ragdamaxing`.

## 2. Public HTTPS link (pick one)

Friends type a PIN into this app, so it must be HTTPS. No ports need to be opened on the VPS for A or B.

**A. Tailscale Funnel (free, no domain). Recommended.**
The owner makes the machine join *his* tailnet, so he keeps the URL even if the VPS changes later.

1. Owner: Tailscale admin console → Settings → Keys → *Generate auth key* (not reusable, 1 day expiry). Send it to the host privately.
2. Host:
   ```bash
   curl -fsSL https://tailscale.com/install.sh | sh
   sudo tailscale up --authkey=tskey-XXXXXXXX --hostname=ragdamaxing
   sudo tailscale funnel --bg 8765
   tailscale funnel status        # shows https://ragdamaxing.<tailnet>.ts.net
   ```
3. Owner: admin console → Machines → `ragdamaxing` → ⋯ → **Disable key expiry** (otherwise the link dies after ~6 months).

Do **not** add `--ssh` unless the host is happy to give the owner shell access to his VPS (Tailscale SSH can be allowed as root, depending on the tailnet ACL).

**B. Own domain + Cloudflare Tunnel or Caddy.** Works too. Point the tunnel/proxy at `http://127.0.0.1:8765`. Caddy needs ports 80/443 open; Cloudflare Tunnel needs none.

## 3. Owner: move the existing data (accounts, XP, streaks, chat all live in one file)

The new server starts empty. To keep everyone's accounts and history:

1. On the laptop, stop the old server so nothing diverges: `systemctl --user disable --now ragdamaxing.service`, and stop the funnel there.
2. Sign in to the old app as admin, Me → *Open server dashboard* → *Download database backup* (do this **before** stopping it; or copy `data/ragdamaxing.db` after stopping).
3. Send that `.db` file to the host **privately** (never GitHub: it contains PIN hashes and DMs).
4. Host:
   ```bash
   sudo systemctl stop ragdamaxing
   sudo install -m 644 -o ragdamaxing -g ragdamaxing ragdamaxing-XXXX.db /opt/ragdamaxing/app/data/ragdamaxing.db
   sudo systemctl start ragdamaxing
   ```
5. Owner: send friends the new link. They log in with the same username + PIN (they only need to log in again, and re-add the app to their home screen, because the URL changed).

## 4. Owner: control and stats

| What | How |
|---|---|
| Deploy a change | `git push` to GitHub. The VPS picks it up within 5 minutes. |
| Live stats | Me tab → **Server dashboard**: users, active today/7d, focus minutes, messages, RAM, load, disk, uptime, which commit is deployed |
| Backups | Same dashboard → **Download database backup** (take one every few days; the VPS also keeps 14 daily ones) |
| Friend forgot PIN | Same dashboard → **Reset PIN** (gives a one-time PIN, logs them out) |
| Who is admin | `RAGDAMAXING_ADMINS` in `/etc/ragdamaxing.env` (usernames, comma separated) |

## 5. Host: day-to-day

```bash
systemctl status ragdamaxing                 # is it running
journalctl -u ragdamaxing -n 50 --no-pager   # logs
journalctl -u ragdamaxing-update -n 20 --no-pager   # what the auto-updater did
sudo systemctl restart ragdamaxing
sudo systemctl disable --now ragdamaxing-update.timer   # turn auto-update off (then update by hand: sudo /usr/local/lib/ragdamaxing/update.sh)
sudo /usr/local/lib/ragdamaxing/backup.sh    # backup right now
```

Private repo? Add a read-only deploy key: GitHub repo → Settings → Deploy keys. Put the private key at `/opt/ragdamaxing/.ssh/id_ed25519` (owner `ragdamaxing`) and use the `git@github.com:...` clone URL.

## Honest trust notes

- Whoever hosts the VPS can read the database, including DMs and PIN hashes. DMs are private between members **inside the app**, not end-to-end encrypted. Host the crew's data with someone you trust.
- Auto-update means the owner's pushes run on the host's machine, but only as the sandboxed `ragdamaxing` user. The root-owned helper scripts in `/usr/local/lib/ragdamaxing` are copied once at install time and are never changed by a push.
