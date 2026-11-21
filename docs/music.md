# Music rooms

The music bot is **off by default**. It adds `/play` and a small player to voice
rooms, with one proxied stream and server-clock synchronization for everyone in
the room. It uses `yt-dlp` as an external tool; the app itself is still stdlib-only
Python.

## What it needs

* `yt-dlp` on `PATH`, or an absolute path in `RAGDAMAXING_YTDLP`.
* A JavaScript runtime for current YouTube extraction. Recent yt-dlp releases
  use Deno by default; Node also works (`--js-runtimes node` in yt-dlp's config).
  Check with `yt-dlp -v` and look at `JS runtimes:`.
* Writable disk for the cache. In production this is `data/music_cache` beside
  `data/outgrow.db`.

Do **not** commit the binary, Deno, Node, cookies, or the cache.

## Enable it

Set these in the app environment (compose `.env` or the container environment):

```sh
RAGDAMAXING_MUSIC=1
RAGDAMAXING_YTDLP=/usr/local/bin/yt-dlp        # optional if it is on PATH
# RAGDAMAXING_YTDLP_COOKIES=/run/secrets/yt-cookies.txt   # optional, see below
# RAGDAMAXING_MUSIC_REMOTE=http://resolver-host:8788       # optional, see below
```

Optional limits:

```sh
RAGDAMAXING_MUSIC_MAX_MIN=20
RAGDAMAXING_MUSIC_QUEUE_MAX=50
RAGDAMAXING_MUSIC_CACHE_MB=300
RAGDAMAXING_MUSIC_CACHE_DIR=/app/data/music_cache
RAGDAMAXING_MUSIC_TIMEOUT=20
```

If the binary is missing, the app still boots and the voice room shows
"Music is off: yt-dlp is not installed on the server." Nothing else is affected.

## Install on the VPS

The app container does not currently include yt-dlp or a JS runtime. The clean
host-side setup on a Debian/Ubuntu VPS is:

```sh
sudo apt-get update
sudo apt-get install -y python3 ffmpeg unzip
sudo curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp_linux \
  -o /usr/local/bin/yt-dlp
sudo chmod 755 /usr/local/bin/yt-dlp
# Deno (one option)
curl -fsSL https://deno.land/install.sh | sh
```

If the app runs in Docker, mount the binary and runtime into the container, or
build them into the image. The container must be able to reach both YouTube and
the CDN URLs yt-dlp returns. Then set the env vars and rebuild/restart.

Test from the same network namespace as the app:

```sh
yt-dlp -v
yt-dlp --no-playlist -f 'bestaudio[ext=m4a]/bestaudio' -g 'ytsearch1:test'
```

If that prints a URL, the resolver path is working. If it prints
`Sign in to confirm you're not a bot`, see R-2 below.

## Keeping yt-dlp current

YouTube changes break extractors; the fix is a newer binary. A weekly timer is
enough:

```ini
# /etc/systemd/system/yt-dlp-update.service
[Unit]
Description=Update yt-dlp
[Service]
Type=oneshot
ExecStart=/usr/local/bin/yt-dlp -U
```

```ini
# /etc/systemd/system/yt-dlp-update.timer
[Unit]
Description=Weekly yt-dlp update
[Timer]
OnCalendar=weekly
Persistent=true
[Install]
WantedBy=timers.target
```

Then `sudo systemctl enable --now yt-dlp-update.timer`. If the binary is distro
managed, use the package manager instead.

## Tests

```sh
cd growth_tracker_v3
python3 test_music.py       # fake yt-dlp, queue, permissions, Range/cache
python3 test_voice.py       # voice room regression
python3 test_api.py         # main app regression
node --check static/music.js
```

`test_music.py` uses `tests/fake_ytdlp.py` and never contacts YouTube.

## R-2: datacenter IP bot checks

AWS and most VPS providers are commonly challenged. The app logs the real
yt-dlp stderr line beginning `[music] yt-dlp bot check:` and shows listeners a
short "music is unavailable right now" message. Mitigations, in order:

1. **Remote resolver on a residential IP** (best). Run a tiny resolver at home
   that answers `GET /search?q=` and `GET /stream/<id>` with Range support, then
   set `RAGDAMAXING_MUSIC_REMOTE` to its base URL. The app's provider interface
   already supports this shape. Keep it on a private network (Tailscale/WireGuard),
   not the public internet.
2. **Throwaway cookies file.** Export cookies from a disposable Google account
   (never the main account) and point `RAGDAMAXING_YTDLP_COOKIES` at a file
   readable only by the service. The path is passed to yt-dlp; its contents are
   never logged or served. This can still stop working and puts that account at
   risk.
3. **PO-token helper.** More moving parts; only if the first two are impossible.

Never promise music will always work. yt-dlp itself breaks when YouTube changes.

## Remote resolver contract

The optional service should provide:

* `GET /search?q=<urlencoded>&limit=5` → JSON list or `{"results": [...]}` with
  `id`, `title`, `artist`, `duration_s`.
* `GET /stream/<11-char-id>` → audio bytes with normal `Range`/`206` handling.

Ids are always validated to `^[A-Za-z0-9_-]{11}$` before the app calls either
endpoint. The app still proxies the bytes and caches them; the resolver is not
exposed to browsers.

## Operational notes

* Cache entries live in `data/music_cache`, are pruned above the MB cap, and
  expire after 2 hours. A track is downloaded once and then served with real
  byte ranges, so seeking and late joiners are cheap.
* The stream endpoint requires a login and an actual seat in that voice room;
  the track must be in that room's queue or currently playing.
* Queue/state is in memory. Restarting the app stops playback and clears queues.
* `/play`, `/skip`, `/pause`, `/resume`, `/stop`, `/loop`, `/queue`, `/np` work
  from the voice-room search box and from any chat while connected to voice.
* Only the requester, a moderator (`manage_channels`), or a >50% room vote can
  skip/stop/remove. The `music` role permission defaults on for `@everyone`.
* ToS: pulling YouTube audio and stripping ads is against YouTube's terms. This
  is intended for a private friends server, not a public or advertised service.
  Keep the flag off unless the owner accepts that risk.
