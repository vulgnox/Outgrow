"""
RAGDAMAXING social layer — storage.

Everything here is additive: CREATE TABLE IF NOT EXISTS plus the default server
that maps a crew's old room to #general through channels.legacy_thread. Existing
messages rows are never rewritten or deleted.
"""
import time

import social_perms as perms

SCHEMA = """
CREATE TABLE IF NOT EXISTS servers(
 id INTEGER PRIMARY KEY, crew_id INTEGER, name TEXT, icon TEXT DEFAULT '', owner INTEGER DEFAULT 0,
 legacy INTEGER DEFAULT 0, created_at TEXT);
CREATE INDEX IF NOT EXISTS ix_servers_crew ON servers(crew_id);
CREATE TABLE IF NOT EXISTS server_members(
 server_id INTEGER, user_id INTEGER, joined_at TEXT, PRIMARY KEY(server_id, user_id));
CREATE INDEX IF NOT EXISTS ix_smembers_user ON server_members(user_id);
CREATE TABLE IF NOT EXISTS channels(
 id INTEGER PRIMARY KEY, server_id INTEGER, name TEXT, kind TEXT DEFAULT 'text', topic TEXT DEFAULT '',
 pos INTEGER DEFAULT 0, legacy_thread TEXT DEFAULT '', created_at TEXT);
CREATE INDEX IF NOT EXISTS ix_channels_server ON channels(server_id, pos);
CREATE TABLE IF NOT EXISTS roles(
 id INTEGER PRIMARY KEY, server_id INTEGER, name TEXT, color TEXT DEFAULT '',
 perms INTEGER DEFAULT 0, pos INTEGER DEFAULT 0, is_default INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_roles_server ON roles(server_id);
CREATE TABLE IF NOT EXISTS role_members(role_id INTEGER, user_id INTEGER, PRIMARY KEY(role_id, user_id));
CREATE TABLE IF NOT EXISTS invites(
 code TEXT PRIMARY KEY, server_id INTEGER, created_by INTEGER, created_at TEXT,
 expires TEXT, max_uses INTEGER DEFAULT 0, uses INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS audit(
 id INTEGER PRIMARY KEY, server_id INTEGER, actor INTEGER, action TEXT, target TEXT DEFAULT '', ts TEXT);
CREATE INDEX IF NOT EXISTS ix_audit_server ON audit(server_id, id);
CREATE TABLE IF NOT EXISTS bans(server_id INTEGER, user_id INTEGER, by_id INTEGER, ts TEXT, reason TEXT DEFAULT '',
 PRIMARY KEY(server_id, user_id));
CREATE TABLE IF NOT EXISTS timeouts(server_id INTEGER, user_id INTEGER, until REAL, by_id INTEGER, reason TEXT DEFAULT '',
 PRIMARY KEY(server_id, user_id));
CREATE TABLE IF NOT EXISTS msg_reacts2(msg_id INTEGER, user_id INTEGER, emoji TEXT, PRIMARY KEY(msg_id, user_id, emoji));
CREATE INDEX IF NOT EXISTS ix_reacts2_msg ON msg_reacts2(msg_id);
CREATE TABLE IF NOT EXISTS server_assets(
 id INTEGER PRIMARY KEY, server_id INTEGER, kind TEXT, name TEXT, slug TEXT, upload_id INTEGER,
 created_by INTEGER, active INTEGER DEFAULT 1, created_at TEXT,
 UNIQUE(server_id, kind, slug));
CREATE INDEX IF NOT EXISTS ix_server_assets_server ON server_assets(server_id, kind, id);
CREATE INDEX IF NOT EXISTS ix_server_assets_upload ON server_assets(upload_id);
CREATE INDEX IF NOT EXISTS ix_server_assets_active ON server_assets(server_id, kind, active, id);
CREATE TABLE IF NOT EXISTS friends(a INTEGER, b INTEGER, ts TEXT, PRIMARY KEY(a, b));
CREATE TABLE IF NOT EXISTS friend_reqs(from_id INTEGER, to_id INTEGER, ts TEXT, PRIMARY KEY(from_id, to_id));
CREATE TABLE IF NOT EXISTS blocks(user_id INTEGER, blocked_id INTEGER, ts TEXT, PRIMARY KEY(user_id, blocked_id));
CREATE TABLE IF NOT EXISTS reports(id INTEGER PRIMARY KEY, ts TEXT, reporter INTEGER, server_id INTEGER DEFAULT 0,
 message_id INTEGER, reason TEXT DEFAULT '', status TEXT DEFAULT 'open');
CREATE TABLE IF NOT EXISTS uploads(
 id INTEGER PRIMARY KEY, owner INTEGER, scope TEXT DEFAULT '', server_id INTEGER DEFAULT 0, channel_id INTEGER DEFAULT 0,
 name TEXT, mime TEXT, size INTEGER, w INTEGER DEFAULT 0, h INTEGER DEFAULT 0, sha TEXT, disk TEXT DEFAULT '', created_at TEXT);
CREATE INDEX IF NOT EXISTS ix_uploads_scope ON uploads(scope);
CREATE INDEX IF NOT EXISTS ix_uploads_owner_scope ON uploads(owner, scope);
CREATE TABLE IF NOT EXISTS msg_files(msg_id INTEGER, upload_id INTEGER, pos INTEGER DEFAULT 0,
 PRIMARY KEY(msg_id, upload_id));
CREATE INDEX IF NOT EXISTS ix_msgfiles_msg ON msg_files(msg_id);
CREATE INDEX IF NOT EXISTS ix_msgfiles_upload ON msg_files(upload_id);
CREATE TABLE IF NOT EXISTS link_previews(key TEXT PRIMARY KEY, url TEXT, title TEXT DEFAULT '', desc TEXT DEFAULT '',
 image TEXT DEFAULT '', site TEXT DEFAULT '', ts REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS profiles(
 user_id INTEGER PRIMARY KEY, avatar_upload INTEGER DEFAULT 0, banner_upload INTEGER DEFAULT 0,
 status_text TEXT DEFAULT '', status_emoji TEXT DEFAULT '', status_ts REAL DEFAULT 0,
 bio TEXT DEFAULT '', pronouns TEXT DEFAULT '', banner_style TEXT DEFAULT '', updated_at TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS social_meta(k TEXT PRIMARY KEY, v TEXT);
"""


def _ts():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def install(conn):
    """Create the tables, then give every existing crew its default server."""
    conn.executescript(SCHEMA)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(profiles)")}
    for name, decl in (("bio", "TEXT DEFAULT ''"), ("pronouns", "TEXT DEFAULT ''"), ("banner_style", "TEXT DEFAULT ''")):
        if name not in cols:
            conn.execute("ALTER TABLE profiles ADD COLUMN %s %s" % (name, decl))
    for row in conn.execute("SELECT id, name FROM crews ORDER BY id").fetchall():
        sync_crew(conn, row["id"], row["name"])
    copy_legacy_reacts(conn)
    # one-time: invites are a moderator action, not a default member right
    if not conn.execute("SELECT 1 FROM social_meta WHERE k='perms_v2'").fetchone():
        conn.execute("UPDATE roles SET perms=? WHERE is_default=1 AND perms=95", (perms.DEFAULT_EVERYONE,))
        conn.execute("INSERT OR REPLACE INTO social_meta(k,v) VALUES('perms_v2',?)", (_ts(),))
    conn.commit()


def ensure_roles(conn, sid):
    """A server always has an @everyone role; the owner gets an Admin role for management UI."""
    d = conn.execute("SELECT id FROM roles WHERE server_id=? AND is_default=1", (sid,)).fetchone()
    if not d:
        conn.execute("INSERT INTO roles(server_id,name,color,perms,pos,is_default) VALUES(?,?,?,?,0,1)",
                     (sid, "@everyone", "", perms.DEFAULT_EVERYONE))
    a = conn.execute("SELECT id FROM roles WHERE server_id=? AND name='Admin'", (sid,)).fetchone()
    if not a:
        conn.execute("INSERT INTO roles(server_id,name,color,perms,pos,is_default) VALUES(?,?,?,?,1,0)",
                     (sid, "Admin", "#f5b83d", perms.ALL))


def sync_crew(conn, crew_id, crew_name=None):
    """Make sure a crew has its default server, channels and one membership row per member.

    Idempotent. Returns the server id (or None when the user has no crew).
    """
    if not crew_id:
        return None
    s = conn.execute("SELECT id FROM servers WHERE crew_id=? AND legacy=1 ORDER BY id LIMIT 1", (crew_id,)).fetchone()
    if not s:
        if crew_name is None:
            cr = conn.execute("SELECT name FROM crews WHERE id=?", (crew_id,)).fetchone()
            crew_name = cr["name"] if cr else "Crew %s" % crew_id
        owner = conn.execute("SELECT id FROM users WHERE crew_id=? ORDER BY id LIMIT 1", (crew_id,)).fetchone()
        cur = conn.execute("INSERT INTO servers(crew_id,name,owner,legacy,created_at) VALUES(?,?,?,1,?)",
                           (crew_id, crew_name, owner["id"] if owner else 0, _ts()))
        sid = cur.lastrowid
        conn.execute("INSERT INTO channels(server_id,name,kind,topic,pos,legacy_thread,created_at) VALUES(?,?,?,?,?,?,?)",
                     (sid, "general", "text", "The whole crew. Everything from the old room is here.", 0, "crew:%s" % crew_id, _ts()))
        conn.execute("INSERT INTO channels(server_id,name,kind,topic,pos,legacy_thread,created_at) VALUES(?,?,?,?,?,?,?)",
                     (sid, "study-wins", "text", "Post what you finished. Proof beats plans.", 1, "", _ts()))
        ensure_roles(conn, sid)
        conn.commit()
    else:
        sid = int(s["id"])

    # who is about to join for the first time? Their crew history starts read, like the old room.
    fresh = [r["id"] for r in conn.execute(
        "SELECT id FROM users WHERE crew_id=? AND id NOT IN (SELECT user_id FROM server_members WHERE server_id=?)",
        (crew_id, sid)).fetchall()]
    conn.execute("INSERT OR IGNORE INTO server_members(server_id,user_id,joined_at) "
                 "SELECT ?, id, ? FROM users WHERE crew_id=?", (sid, _ts(), crew_id))
    if fresh:
        legacy = conn.execute("SELECT legacy_thread FROM channels WHERE server_id=? AND legacy_thread<>'' LIMIT 1", (sid,)).fetchone()
        if legacy:
            last = conn.execute("SELECT COALESCE(MAX(id),0) FROM messages WHERE thread=?", (legacy["legacy_thread"],)).fetchone()[0]
            for uid in fresh:
                conn.execute("INSERT OR IGNORE INTO chat_reads(user_id,thread,last_id) VALUES(?,?,?)",
                             (uid, legacy["legacy_thread"], last))
    return sid


def copy_legacy_reacts(conn):
    """One-way import into the multi-emoji table. Old rows stay where they are."""
    try:
        conn.execute("INSERT OR IGNORE INTO msg_reacts2(msg_id,user_id,emoji) "
                     "SELECT msg_id,user_id,emoji FROM msg_reacts")
    except Exception:
        pass


def server_of_channel(conn, ch_id):
    return conn.execute("SELECT * FROM channels WHERE id=?", (ch_id,)).fetchone()


def thread_of(ch):
    """#general reads and writes the old crew room, so history is untouched."""
    return ch["legacy_thread"] or "ch:%s" % ch["id"]


def default_channel(conn, sid):
    return conn.execute(
        "SELECT * FROM channels WHERE server_id=? AND kind='text' ORDER BY pos, id LIMIT 1", (sid,)).fetchone()


def channel_rows(conn, sid):
    return conn.execute("SELECT * FROM channels WHERE server_id=? ORDER BY pos, id", (sid,)).fetchall()


def member_ids(conn, sid):
    return [int(r[0]) for r in conn.execute("SELECT user_id FROM server_members WHERE server_id=?", (sid,)).fetchall()]


def member_count(conn, sid):
    return conn.execute("SELECT COUNT(*) FROM server_members WHERE server_id=?", (sid,)).fetchone()[0]
