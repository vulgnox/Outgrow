'use strict';
/* RAGDAMAXING social management: server + channel settings, invites, members, roles,
   audit log, friends and blocks. Lives in the existing modal() from app.js. */

const PB = {
  view: 1, send: 2, attach: 4, react: 8, voice: 16, mention_all: 32, create_invite: 64,
  manage_server: 128, manage_channels: 256, manage_roles: 512, kick: 1024, ban: 2048,
  timeout: 4096, delete_messages: 8192, pin: 16384, music: 32768,
};
const PGROUPS = [
  ['General', ['view', 'send', 'attach', 'react', 'mention_all', 'create_invite']],
  ['Channels', ['manage_channels', 'manage_roles', 'manage_server']],
  ['Moderation', ['kick', 'timeout', 'ban', 'delete_messages', 'pin']],
  ['Voice', ['voice', 'music']],
];
const Manage = {};
const M = { sid: 0, data: null, view: 'home', role: 0, ch: 0 };

const mval = id => { const e = document.getElementById(id); return e ? e.value.trim() : ''; };
const copyText = t => { try { const p = navigator.clipboard && navigator.clipboard.writeText(t); if (p && p.catch) p.catch(() => { }); } catch (e) { } };
const pbits = names => names.reduce((a, n) => a | (PB[n] || 0), 0);
const canP = n => !!(M.data && (M.data.me.perms & PB[n]));

function titleOf() {
  const t = { home: 'Server', invites: 'Invites', members: 'Members', roles: 'Roles', audit: 'Audit log', overview: 'Overview', role: 'Edit role' };
  return t[M.view] || 'Server';
}

function roleNames(ids) {
  const all = (M.data && M.data.roles) || [];
  return ids.map(id => all.find(r => r.id === id)).filter(Boolean);
}

function permSummary(p) {
  const names = Object.keys(PB).filter(k => p & PB[k]);
  return names.length ? names.join(', ') : 'no extra permissions';
}

async function loadData(view) {
  M.data = await api('server?sid=' + M.sid);
  if (view === 'members' && (M.data.me.perms & PB.ban)) {
    const b = await api('bans?sid=' + M.sid);
    M.data.bans = b.bans || [];
  }
  if (view === 'audit') {
    const a = await api('audit?sid=' + M.sid);
    M.data.audit = a.audit || [];
  }
  return M.data;
}

Manage.open = async function (sid, view) {
  M.sid = sid || M.sid;
  M.view = view || 'home';
  M.role = 0;
  try { await loadData(M.view); } catch (e) { return; }
  Manage.render();
};

Manage.refresh = async function (view) {
  if (view) M.view = view;
  try { await loadData(M.view); } catch (e) { return; }
  Manage.render();
};

Manage.render = function () {
  if (!M.data) return;
  const d = M.data, s = d.server;
  const nav = (k, label) => `<button class="mg-tab ${M.view === k ? 'on' : ''}" data-mact="view" data-v="${k}">${label}</button>`;
  let body = '';
  if (M.view === 'home') body = mgHome();
  else if (M.view === 'invites') body = mgInvites();
  else if (M.view === 'members') body = mgMembers();
  else if (M.view === 'roles') body = mgRoles();
  else if (M.view === 'role') body = mgRole();
  else if (M.view === 'audit') body = mgAudit();
  else if (M.view === 'overview') body = mgOverview();
  modal(`<div class="mg">
    <div class="row between mg-top"><div class="grow min0"><div class="xs mut up">${esc(s.legacy ? 'Crew server' : 'Server')}</div><h2 class="ell">${esc(s.name)}</h2></div>
      <button class="btn-s ico" data-mact="close" aria-label="Close">${ic('x', 14)}</button></div>
    <div class="mg-tabs">${nav('home', 'Home')}${canP('create_invite') ? nav('invites', 'Invites') : ''}${nav('members', 'Members')}${canP('manage_roles') ? nav('roles', 'Roles') : ''}${canP('manage_server') ? nav('audit', 'Audit') : ''}${canP('manage_server') ? nav('overview', 'Settings') : ''}</div>
    <div class="mg-body">${body}</div></div>`, true);
};

function mgHome() {
  const d = M.data, s = d.server;
  const chans = d.channels.length, roles = d.roles.length, mem = d.members.length;
  return `<div class="mg-stats">
      <div><b>${mem}</b><span>members</span></div><div><b>${chans}</b><span>channels</span></div><div><b>${roles}</b><span>roles</span></div>
    </div>
    ${canP('create_invite') ? '<button class="btn-p btn-xl" data-mact="view" data-v="invites">Invite people</button>' : ''}
    <div class="mg-grid">
      <button class="mg-big" data-mact="view" data-v="members"><b>${ic('users', 22)}</b><span>Members</span></button>
      ${canP('manage_roles') ? `<button class="mg-big" data-mact="view" data-v="roles"><b>${ic('palette', 22)}</b><span>Roles</span></button>` : ''}
      ${canP('manage_server') ? `<button class="mg-big" data-mact="view" data-v="audit"><b>${ic('book', 22)}</b><span>Audit log</span></button>` : ''}
      ${canP('manage_server') ? `<button class="mg-big" data-mact="view" data-v="overview"><b>${ic('settings', 22)}</b><span>Settings</span></button>` : ''}
    </div>
    <p class="xs mut c mt12">Server id ${s.id} · ${s.legacy ? 'automatic for your crew' : 'your own server'}</p>`;
}

function mgInvites() {
  const inv = M.data.invites || [];
  return `<label>New invite link</label>
    <div class="row g8"><select id="mg_days" class="grow"><option value="7">Expires in 7 days</option><option value="1">Expires in 1 day</option><option value="30">Expires in 30 days</option><option value="0">Never expires</option></select>
      <select id="mg_uses" class="grow"><option value="0">Unlimited uses</option><option value="1">1 use</option><option value="5">5 uses</option><option value="25">25 uses</option></select></div>
    <button class="btn-p btn-xl mt8" data-mact="inv_new">Create invite</button>
    <div class="mg-list">${inv.length ? inv.map(i => `<div class="mg-row">
        <div class="grow min0"><div class="mg-code">${esc(i.code)}</div><div class="xs mut">${i.expires ? 'expires ' + esc(i.expires.slice(0, 10)) : 'never expires'} · ${i.uses}${i.max_uses ? '/' + i.max_uses : ''} uses</div></div>
        <button class="btn-s" data-mact="inv_copy" data-code="${esc(i.code)}">Copy</button>
        <button class="btn-s" data-mact="inv_revoke" data-code="${esc(i.code)}">Revoke</button></div>`).join('') : '<div class="mut sm c" style="padding:20px">No active invites.</div>'}</div>
    <p class="xs mut">Anyone with a code can join until it expires, is revoked, or runs out of uses. There is no public server directory.</p>`;
}

function mgMembers() {
  const d = M.data, me = d.me.id;
  return `<div class="mg-list">${d.members.map(m => {
    const rs = roleNames(m.roles).map(r => `<span class="pill" style="--rc:${esc(r.color || '#8b8ba3')}">${esc(r.name)}</span>`).join('');
    const mod = m.id === me ? '' : `<div class="mg-acts">
      ${canP('kick') ? `<button class="btn-s" data-mact="kick" data-uid="${m.id}" data-name="${esc(m.display)}">Kick</button>` : ''}
      ${canP('timeout') ? `<button class="btn-s" data-mact="timeout" data-uid="${m.id}" data-name="${esc(m.display)}">Timeout</button>` : ''}
      ${canP('ban') ? `<button class="btn-s" data-mact="ban" data-uid="${m.id}" data-name="${esc(m.display)}">Ban</button>` : ''}</div>`;
    return `<div class="mg-row"><span data-act="profile" data-id="${m.id}" style="cursor:pointer">${avatar(m.emoji, m.color, 'sm', null, m)}</span>
      <div class="grow min0"><div class="row g4"><b class="ell" data-act="profile" data-id="${m.id}" style="cursor:pointer">${esc(m.display)}</b>${m.owner ? '<span class="pill gold">owner</span>' : ''}</div>
        ${m.status && (m.status.text || m.status.emoji) ? `<div class="xs mut ell">${esc([m.status.emoji, m.status.text].filter(Boolean).join(' '))}</div>` : ''}
        <div class="row wrap g4 mt4">${rs || '<span class="xs mut">@everyone</span>'}${m.timeout > Date.now() / 1000 ? `<span class="pill d">timed out</span>` : ''}</div></div>${mod}</div>`;
  }).join('')}${canP('ban') && (d.bans || []).length ? `<div class="lbl2 mt12">Banned</div><div class="mg-list">${d.bans.map(b => `<div class="mg-row">
      <span>${avatar(b.emoji, b.color, 'sm', null, b)}</span><div class="grow min0"><b class="ell">${esc(b.display)}</b><div class="xs mut ell">${esc(b.reason || 'no reason given')}</div></div>
      <button class="btn-s" data-mact="unban" data-uid="${b.id}">Unban</button></div>`).join('')}</div>` : ''}</div>`;
}

function mgRoles() {
  return `<button class="btn-p btn-xl" data-mact="role_new">New role</button>
    <div class="mg-list">${M.data.roles.map(r => `<div class="mg-row" data-mact="role_open" data-id="${r.id}">
      <span class="mg-dot" style="background:${esc(r.color || '#8b8ba3')}"></span>
      <div class="grow min0"><b>${esc(r.name)}</b>${r.default ? ' <span class="xs mut">@everyone</span>' : ''}<div class="xs mut ell">${r.members.length} member${r.members.length === 1 ? '' : 's'} · ${esc(permSummary(r.perms))}</div></div>
      <span class="btn-s">Edit</span></div>`).join('')}</div>`;
}

function mgRole() {
  const r = (M.data.roles || []).find(x => x.id === M.role);
  if (!r) return '<div class="mut">That role is gone.</div>';
  const boxes = PGROUPS.map(([label, names]) => `<div class="mg-pgroup"><div class="lbl2">${label}</div>
      ${names.map(n => `<label class="mg-p"><input type="checkbox" id="mg_p_${n}" ${r.perms & PB[n] ? 'checked' : ''}> <span>${n.replace(/_/g, ' ')}</span></label>`).join('')}</div>`).join('');
  return `<div class="row g8"><input id="mg_rname" value="${esc(r.name)}" maxlength="30" ${r.default ? 'disabled' : ''} class="grow">
      <input id="mg_rcolor" type="color" value="${r.color || '#8b8ba3'}" style="width:56px;flex:none;padding:4px"></div>
    ${r.default ? '<p class="xs mut">@everyone applies to every member. That is where baseline permissions live.</p>' : ''}
    <div class="mg-perms">${boxes}</div>
    <div class="row g8 mt12"><button class="btn-p grow" data-mact="role_save" data-id="${r.id}">Save role</button>
      ${r.default ? '' : `<button class="btn-d" data-mact="role_del" data-id="${r.id}">Delete</button>`}</div>
    ${r.default ? '' : `<div class="lbl2 mt12">Members with this role</div><div class="mg-list">${M.data.members.map(m => {
      const on = m.roles.includes(r.id);
      return `<div class="mg-row"><span>${avatar(m.emoji, m.color, 'sm', null, m)}</span><b class="grow ell">${esc(m.display)}</b>
        <button class="btn-s ${on ? 'btn-g' : ''}" data-mact="role_toggle" data-role="${r.id}" data-uid="${m.id}" data-on="${on ? 1 : 0}">${on ? 'Remove' : 'Add'}</button></div>`;
    }).join('')}</div>`}`;
}

function mgAudit() {
  const rows = M.data.audit || [];
  if (!rows.length) return '<div class="mut sm c" style="padding:30px">Nothing logged yet.</div>';
  return `<div class="mg-list">${rows.map(a => `<div class="mg-audit"><div class="row between"><b>${esc(a.action)}</b><span class="xs mut">${esc((a.ts || '').replace('T', ' '))}</span></div>
      <div class="xs mut">${esc(a.display || 'system')}${a.target ? ' · ' + esc(a.target) : ''}</div></div>`).join('')}</div>`;
}

function mgOverview() {
  const s = M.data.server;
  return `<label>Server name</label><input id="mg_name" value="${esc(s.name)}" maxlength="30">
    <label>Icon (one emoji, or leave empty)</label><input id="mg_icon" value="${esc(s.icon)}" maxlength="8">
    <button class="btn-p btn-xl mt12" data-mact="server_save">Save</button>
    <div class="lbl2 mt12" style="color:var(--bad)">Danger zone</div>
    ${s.legacy ? '<p class="xs mut">This is your crew server. It is created automatically and cannot be deleted.</p>'
      : (M.data.me.owner ? `<button class="btn-d btn-xl" data-mact="server_delete">Delete this server</button>`
        : `<button class="btn-d btn-xl" data-mact="server_leave">Leave this server</button>`)}`;
}

/* ---------- channel settings ---------- */
Manage.channel = function (chId) {
  const srv = (C.servers || []).find(s => s.channels.some(c => c.id === chId));
  const ch = srv && srv.channels.find(c => c.id === chId);
  if (!ch) return;
  M.ch = chId;
  modal(`<div class="mg">
    <div class="row between mg-top"><div><div class="xs mut up">Channel</div><h2># ${esc(ch.name)}</h2></div><button class="btn-s ico" data-mact="close">${ic('x', 14)}</button></div>
    <label>Name</label><input id="mg_ch_name" value="${esc(ch.name)}" maxlength="24">
    <label>Topic</label><input id="mg_ch_topic" value="${esc(ch.topic || '')}" maxlength="120">
    <button class="btn-p btn-xl mt12" data-mact="ch_save">Save</button>
    <div class="lbl2 mt12" style="color:var(--bad)">Danger zone</div>
    <button class="btn-d btn-xl" data-mact="ch_delete">Delete channel</button>
    <p class="xs mut">Deleting a channel deletes its messages for everyone. This cannot be undone.</p></div>`, true);
};

/* ---------- create a channel ---------- */
Manage.newChannel = function () {
  const sid = C.sid;
  modal(`<div class="mg">
    <div class="row between mg-top"><h2>New channel</h2><button class="btn-s ico" data-mact="close">${ic('x', 14)}</button></div>
    <label>Name</label><input id="mg_newch" placeholder="memes" maxlength="24" autocapitalize="off" spellcheck="false">
    <label>Kind</label><select id="mg_newch_kind"><option value="text">Text</option><option value="voice">Voice</option></select>
    <button class="btn-p btn-xl mt12" data-mact="ch_new" data-sid="${sid}">Create channel</button>
    <p class="xs mut">Lowercase letters, numbers, dashes and underscores.</p></div>`, true);
};

/* ---------- add a server ---------- */
Manage.addServer = function () {
  modal(`<div class="mg">
    <div class="row between mg-top"><h2>Add a server</h2><button class="btn-s ico" data-mact="close">${ic('x', 14)}</button></div>
    <div class="mg-tabs"><button class="mg-tab on" data-mact="add_tab" data-v="join">Join</button><button class="mg-tab" data-mact="add_tab" data-v="create">Create</button></div>
    <div id="mg_add_body">${addBody('join')}</div></div>`, true);
};

function addBody(kind) {
  return kind === 'join'
    ? `<p class="sm mut">Paste an invite code from a friend.</p><input id="mg_code" placeholder="ABCD2345" autocapitalize="characters" maxlength="12" spellcheck="false">
       <button class="btn-p btn-xl mt12" data-mact="server_join">Join server</button>`
    : `<p class="sm mut">You can own up to 3 servers. Only people with an invite can join.</p>
       <label>Name</label><input id="mg_sname" placeholder="Study Hall" maxlength="30">
       <label>Icon (emoji, optional)</label><input id="mg_sicon" placeholder="📚" maxlength="8">
       <button class="btn-p btn-xl mt12" data-mact="server_new">Create server</button>`;
}

/* ---------- friends ---------- */
Manage.friends = async function () {
  let f;
  try { f = await api('friends'); } catch (e) { return; }
  M.friends = f;
      const card = (u, actions) => `<div class="mg-row"><span data-act="profile" data-id="${u.id}" style="cursor:pointer">${avatar(u.emoji, u.color, 'sm', null, u)}</span>
      <div class="grow min0"><b class="ell" data-act="profile" data-id="${u.id}" style="cursor:pointer">${esc(u.display)}</b><div class="xs mut">@${esc(u.username || u.display)}</div>
      ${u.status && (u.status.text || u.status.emoji) ? `<div class="xs mut ell">${esc([u.status.emoji, u.status.text].filter(Boolean).join(' '))}</div>` : ''}</div>${actions}</div>`;
  modal(`<div class="mg">
    <div class="row between mg-top"><h2>Friends</h2><button class="btn-s ico" data-mact="close">${ic('x', 14)}</button></div>
    <label>Add by username</label><div class="row g8"><input id="mg_fuser" placeholder="username" autocapitalize="off" spellcheck="false" class="grow"><button class="btn-p" data-mact="friend_add">Add</button></div>
    ${f.incoming.length ? `<div class="lbl2">Requests</div><div class="mg-list">${f.incoming.map(u => card(u,
      `<button class="btn-s" data-mact="friend_decline" data-uid="${u.id}">Decline</button><button class="btn-p btn-s" data-mact="friend_accept" data-uid="${u.id}">Accept</button>`)).join('')}</div>` : ''}
    ${f.outgoing.length ? `<div class="lbl2">Waiting on them</div><div class="mg-list">${f.outgoing.map(u => card(u, '<span class="xs mut">sent</span>')).join('')}</div>` : ''}
    <div class="lbl2">Friends (${f.friends.length})</div>
    <div class="mg-list">${f.friends.length ? f.friends.map(u => card(u,
      `<button class="btn-s" data-mact="friend_dm" data-uid="${u.id}">Message</button><button class="btn-s" data-mact="friend_remove" data-uid="${u.id}">Remove</button>`)).join('') : '<div class="mut sm c" style="padding:14px">No friends yet. A shared server also lets you DM someone.</div>'}</div>
    ${f.blocked.length ? `<div class="lbl2">Blocked</div><div class="mg-list">${f.blocked.map(u => card(u,
      `<button class="btn-s" data-mact="unblock" data-uid="${u.id}">Unblock</button>`)).join('')}</div>` : ''}
    <p class="xs mut mt12">Blocking stops DMs and friend requests both ways and hides their messages from you.</p></div>`, true);
};

/* ---------- actions ---------- */
async function reloadChat() {
  try { await Chat.load(); } catch (e) { }
  render();
}

const MA = {
  close: () => closeModal(),
  view: el => { M.view = el.dataset.v; Manage.render(); },
  mgInvites: () => { M.view = 'invites'; Manage.render(); },
  mgMembers: () => { M.view = 'members'; Manage.render(); },
  mgRoles: () => { M.view = 'roles'; Manage.render(); },
  mgAudit: () => { M.view = 'audit'; Manage.render(); },
  mgOverview: () => { M.view = 'overview'; Manage.render(); },

  inv_new: async () => {
    try {
      const r = await api('invite/create', { sid: M.sid, days: +mval('mg_days'), max_uses: +mval('mg_uses') });
      copyText(r.code);
      toast('Invite created', r.code + ' · copied');
      await Manage.refresh('invites');
    } catch (e) { }
  },
  inv_copy: el => { copyText(el.dataset.code); toast('Copied', el.dataset.code); },
  inv_revoke: async el => {
    if (!(await confirmSheet('Revoke this invite? The link stops working.', 'Revoke', true))) return;
    try { await api('invite/revoke', { sid: M.sid, code: el.dataset.code }); await Manage.refresh('invites'); } catch (e) { }
  },

  kick: async el => {
    if (!(await confirmSheet(`Kick ${el.dataset.name}? They can rejoin with an invite.`, 'Kick', true))) return;
    try { await api('mod/kick', { sid: M.sid, uid: +el.dataset.uid }); await reloadChat(); await Manage.refresh('members'); } catch (e) { }
  },
  timeout: el => {
    const uid = +el.dataset.uid, name = el.dataset.name;
    modal(`<div class="mg"><div class="row between mg-top"><h2>Timeout ${esc(name)}</h2><button class="btn-s ico" data-mact="close">${ic('x', 14)}</button></div>
      <p class="sm mut">They can read but not send, react or join voice.</p>
      <div class="mg-grid">${[10, 60, 360, 1440, 10080].map(m => `<button class="mg-big" data-mact="timeout_set" data-uid="${uid}" data-min="${m}"><b>${m < 60 ? m + 'm' : m < 1440 ? (m / 60) + 'h' : (m / 1440) + 'd'}</b><span>${m === 10 ? '10 minutes' : 'timeout'}</span></button>`).join('')}</div>
      <button class="btn-s btn-xl mt12" data-mact="timeout_off" data-uid="${uid}">Remove timeout</button></div>`, true);
  },
  timeout_set: async el => {
    try { await api('mod/timeout', { sid: M.sid, uid: +el.dataset.uid, minutes: +el.dataset.min, reason: 'moderator' }); toast('Timed out'); await Manage.open(M.sid, 'members'); } catch (e) { }
  },
  timeout_off: async el => {
    try { await api('mod/untimeout', { sid: M.sid, uid: +el.dataset.uid }); toast('Timeout removed'); await Manage.open(M.sid, 'members'); } catch (e) { }
  },
  unban: async el => {
    try { await api('mod/unban', { sid: M.sid, uid: +el.dataset.uid }); toast('Unbanned'); await Manage.refresh('members'); } catch (e) { }
  },
  ban: async el => {
    if (!(await confirmSheet(`Ban ${el.dataset.name}? They can't rejoin until unbanned.`, 'Ban', true))) return;
    try { await api('mod/ban', { sid: M.sid, uid: +el.dataset.uid, reason: 'moderator' }); await reloadChat(); await Manage.refresh('members'); } catch (e) { }
  },

  role_new: () => {
    M.role = 0;
    modal(`<div class="mg"><div class="row between mg-top"><h2>New role</h2><button class="btn-s ico" data-mact="close">${ic('x', 14)}</button></div>
      <label>Name</label><input id="mg_rname" placeholder="Helper" maxlength="30">
      <label>Colour</label><input id="mg_rcolor" type="color" value="#7c6af7">
      <div class="mg-perms">${PGROUPS.map(([label, names]) => `<div class="mg-pgroup"><div class="lbl2">${label}</div>${names.map(n => `<label class="mg-p"><input type="checkbox" id="mg_p_${n}"> <span>${n.replace(/_/g, ' ')}</span></label>`).join('')}</div>`).join('')}</div>
      <button class="btn-p btn-xl mt12" data-mact="role_create">Create role</button></div>`, true);
  },
  role_create: async () => {
    const names = Object.keys(PB).filter(n => { const e = document.getElementById('mg_p_' + n); return e && e.checked; });
    try {
      const r = await api('role/create', { sid: M.sid, name: mval('mg_rname'), color: mval('mg_rcolor'), perms: pbits(names) });
      M.role = r.role_id;
      toast('Role created');
      await Manage.refresh('role');
    } catch (e) { }
  },
  role_open: el => { M.role = +el.dataset.id; M.view = 'role'; Manage.render(); },
  role_save: async el => {
    const names = Object.keys(PB).filter(n => { const e = document.getElementById('mg_p_' + n); return e && e.checked; });
    try {
      await api('role/update', { sid: M.sid, role: +el.dataset.id, name: mval('mg_rname'), color: mval('mg_rcolor'), perms: pbits(names) });
      toast('Role saved');
      await Manage.refresh('role');
    } catch (e) { }
  },
  role_del: async el => {
    if (!(await confirmSheet('Delete this role? Members keep their other roles.', 'Delete', true))) return;
    try { await api('role/delete', { sid: M.sid, role: +el.dataset.id }); await reloadChat(); await Manage.refresh('roles'); } catch (e) { }
  },
  role_toggle: async el => {
    try {
      await api('role/assign', { sid: M.sid, role: +el.dataset.role, uid: +el.dataset.uid, on: !+el.dataset.on });
      await Manage.refresh('role');
    } catch (e) { }
  },

  server_save: async () => {
    try { await api('server/update', { sid: M.sid, name: mval('mg_name'), icon: mval('mg_icon') }); toast('Saved'); await reloadChat(); await Manage.refresh('home'); } catch (e) { }
  },
  server_delete: async () => {
    if (!(await confirmSheet('Delete this server, its channels and all its messages?', 'Delete server', true))) return;
    try { await api('server/delete', { sid: M.sid }); closeModal(); await reloadChat(); toast('Server deleted'); } catch (e) { }
  },
  server_leave: async () => {
    if (!(await confirmSheet('Leave this server?', 'Leave', true))) return;
    try { await api('server/leave', { sid: M.sid }); closeModal(); await reloadChat(); toast('Left the server'); } catch (e) { }
  },

  ch_new: async el => {
    try {
      const r = await api('channel/create', { sid: +el.dataset.sid, name: mval('mg_newch'), kind: mval('mg_newch_kind') });
      closeModal(); await Chat.load(); if (r.channel_id) await Chat.openChannel(r.channel_id); render();
    } catch (e) { }
  },
  ch_save: async () => {
    try { await api('channel/update', { ch: M.ch, name: mval('mg_ch_name'), topic: mval('mg_ch_topic') }); closeModal(); await reloadChat(); } catch (e) { }
  },
  ch_delete: async () => {
    if (!(await confirmSheet('Delete this channel and its messages?', 'Delete channel', true))) return;
    try { await api('channel/delete', { ch: M.ch }); closeModal(); C.thread = null; C.msgs = []; await reloadChat(); } catch (e) { }
  },

  add_tab: el => { const b = document.getElementById('mg_add_body'); if (b) b.innerHTML = addBody(el.dataset.v); document.querySelectorAll('.mg-tab').forEach(x => x.classList.toggle('on', x === el)); },
  server_new: async () => {
    try {
      const r = await api('server/create', { name: mval('mg_sname'), icon: mval('mg_sicon') });
      closeModal(); await Chat.load(); await openNew(r.server_id); render();
    } catch (e) { }
  },
  server_join: async () => {
    try {
      const r = await api('server/join', { code: mval('mg_code') });
      closeModal(); await Chat.load(); await openNew(r.server_id); render();
    } catch (e) { }
  },

  friend_add: async () => {
    try { await api('friend/request', { username: mval('mg_fuser') }); toast('Request sent'); await Manage.friends(); } catch (e) { }
  },
  friend_accept: async el => { try { await api('friend/accept', { uid: +el.dataset.uid }); await Manage.friends(); await reloadChat(); } catch (e) { } },
  friend_decline: async el => { try { await api('friend/decline', { uid: +el.dataset.uid }); await Manage.friends(); } catch (e) { } },
  friend_remove: async el => { try { await api('friend/remove', { uid: +el.dataset.uid }); await Manage.friends(); await reloadChat(); } catch (e) { } },
  friend_dm: el => { closeModal(); Chat.openDM(+el.dataset.uid); },
  unblock: async el => { try { await api('block', { uid: +el.dataset.uid, on: false }); await Manage.friends(); } catch (e) { } },
  report: el => { closeModal(); Manage.report(+el.dataset.id); },
};

async function openNew(sid) {
  const srv = (C.servers || []).find(s => s.id === sid);
  const ch = srv && (srv.channels.find(c => c.kind === 'text') || srv.channels[0]);
  C.sid = sid;
  if (ch) await Chat.openChannel(ch.id, true);
}

Manage.report = function (mid) {
  modal(`<div class="mg"><div class="row between mg-top"><h2>Report message</h2><button class="btn-s ico" data-mact="close">${ic('x', 14)}</button></div>
    <p class="sm mut">This goes to the app admins. The author is not told.</p>
    <label>What's wrong?</label><input id="mg_reason" placeholder="Spam, bullying, anything" maxlength="200">
    <button class="btn-d btn-xl mt12" data-mact="report_send" data-id="${mid}">Send report</button></div>`, true);
};

MA.report_send = async el => {
  try { await api('report', { id: +el.dataset.id, reason: mval('mg_reason') }); closeModal(); toast('Reported', 'Admins will see it.'); } catch (e) { }
};

document.addEventListener('click', e => {
  const el = e.target.closest('[data-mact]');
  if (!el) return;
  e.preventDefault();
  const fn = MA[el.dataset.mact];
  if (fn) { try { fn(el); } catch (x) { console.error(x); } }
});

window.Manage = Manage;
