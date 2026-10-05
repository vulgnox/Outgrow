# Hosting OUTGROW on a VPS

OUTGROW is plain Python 3 (standard library only) + one SQLite file. No Docker, no pip, no database server.
It needs about 50 MB of RAM and a few MB of disk, so a 1-core / 2 GB / 10 GB VPS is plenty.

Two people are involved: **the host** (owns the VPS) and **the owner** (owns the code, the data and the public URL).

---

## 1. Host: install (about 2 minutes)

On the VPS (Ubuntu 22.04+ or Debian 11+), as a user with sudo:

```bash
git clone https://github.com/<OWNER>/<REPO>.git /tmp/outgrow-src
sudo bash /tmp/outgrow-src/deploy/install.sh
```

That script (read it first, it is short) does everything:

- creates an unprivileged `outgrow` user and puts the app in `/opt/outgrow/app`
- installs `outgrow.service` (sandboxed: it can only write to its own `data/` folder, max 400 MB RAM, 70% of one core)
- listens on `127.0.0.1:8765` only, so nothing is exposed to the internet until step 2
- sets the server clock to IST for the app only (the streak day rolls over at 3 AM IST, not UTC). The rest of the VPS is untouched
- installs a daily database backup (kept 14 days in `/opt/outgrow/backups`)
- installs an **auto-update timer**: every 5 minutes it pulls the owner's latest push from GitHub, restarts the app, and **rolls back automatically** if the new version has a syntax error or fails to start

Config lives in `/etc/outgrow.env`. After editing: `sudo systemctl restart outgrow`.

## 2. Public HTTPS link (pick one)

Friends type a PIN into this app, so it must be HTTPS. No ports need to be opened on the VPS for A or B.

**A. Tailscale Funnel (free, no domain). Recommended.**
The owner makes the machine join *his* tailnet, so he keeps the URL even if the VPS changes later.

1. Owner: Tailscale admin console → Settings → Keys → *Generate auth key* (not reusable, 1 day expiry). Send it to the host privately.
2. Host:
   ```bash
   curl -fsSL https://tailscale.com/install.sh | sh
   sudo tailscale up --authkey=tskey-XXXXXXXX --hostname=outgrow
   sudo tailscale funnel --bg 8765
   tailscale funnel status        # shows https://outgrow.<tailnet>.ts.net
   ```
3. Owner: admin console → Machines → `outgrow` → ⋯ → **Disable key expiry** (otherwise the link dies after ~6 months).

Do **not** add `--ssh` unless the host is happy to give the owner shell access to his VPS (Tailscale SSH can be allowed as root, depending on the tailnet ACL).

**B. Own domain + Cloudflare Tunnel or Caddy.** Works too. Point the tunnel/proxy at `http://127.0.0.1:8765`. Caddy needs ports 80/443 open; Cloudflare Tunnel needs none.

## 3. Owner: move the existing data (accounts, XP, streaks, chat all live in one file)

The new server starts empty. To keep everyone's accounts and history:

1. On the laptop, stop the old server so nothing diverges: `systemctl --user disable --now outgrow.service`, and stop the funnel there.
2. Sign in to the old app as admin, Me → *Open server dashboard* → *Download database backup* (do this **before** stopping it; or copy `data/outgrow.db` after stopping).
3. Send that `.db` file to the host **privately** (never GitHub: it contains PIN hashes and DMs).
4. Host:
   ```bash
   sudo systemctl stop outgrow
   sudo install -m 644 -o outgrow -g outgrow outgrow-XXXX.db /opt/outgrow/app/data/outgrow.db
   sudo systemctl start outgrow
   ```
5. Owner: send friends the new link. They log in with the same username + PIN (they only need to log in again, and re-add the app to their home screen, because the URL changed).

## 4. Owner: control and stats

| What | How |
|---|---|
| Deploy a change | `git push` to GitHub. The VPS picks it up within 5 minutes. |
| Live stats | Me tab → **Server dashboard**: users, active today/7d, focus minutes, messages, RAM, load, disk, uptime, which commit is deployed |
| Backups | Same dashboard → **Download database backup** (take one every few days; the VPS also keeps 14 daily ones) |
| Friend forgot PIN | Same dashboard → **Reset PIN** (gives a one-time PIN, logs them out) |
| Who is admin | `OUTGROW_ADMINS` in `/etc/outgrow.env` (usernames, comma separated) |

## 5. Host: day-to-day

```bash
systemctl status outgrow                 # is it running
journalctl -u outgrow -n 50 --no-pager   # logs
journalctl -u outgrow-update -n 20 --no-pager   # what the auto-updater did
sudo systemctl restart outgrow
sudo systemctl disable --now outgrow-update.timer   # turn auto-update off (then update by hand: sudo /usr/local/lib/outgrow/update.sh)
sudo /usr/local/lib/outgrow/backup.sh    # backup right now
```

Private repo? Add a read-only deploy key: GitHub repo → Settings → Deploy keys. Put the private key at `/opt/outgrow/.ssh/id_ed25519` (owner `outgrow`) and use the `git@github.com:...` clone URL.

## Honest trust notes

- Whoever hosts the VPS can read the database, including DMs and PIN hashes. DMs are private between members **inside the app**, not end-to-end encrypted. Host the crew's data with someone you trust.
- Auto-update means the owner's pushes run on the host's machine, but only as the sandboxed `outgrow` user. The root-owned helper scripts in `/usr/local/lib/outgrow` are copied once at install time and are never changed by a push.
