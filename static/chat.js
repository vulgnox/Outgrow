'use strict';
/* RAGDAMAXING social chat: server rail + channel list + message pane, live over SSE.
   Loaded after app.js and uses its globals (S, api, esc, avatar, ago, toast, chatDay). */

const CH_EMOJI = ['🔥', '💀', '😂', '👍', '❤️', '🫡', '💯', '😭', '🎉', '👀', '🙏', '💪'];
const PAL_ICON = '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3a9 9 0 1 0 0 18c1.4 0 2.2-.9 2.2-2 0-.6-.3-1-.6-1.4-.3-.4-.6-.8-.6-1.3 0-1.1.9-2 2-2h1.8A4.2 4.2 0 0 0 21 10.1 9 9 0 0 0 12 3z"/><circle cx="8" cy="10" r="1.1" fill="currentColor" stroke="none"/><circle cx="12" cy="7.6" r="1.1" fill="currentColor" stroke="none"/><circle cx="16" cy="10" r="1.1" fill="currentColor" stroke="none"/></svg>';

const C = {
  loaded: false, error: '', servers: [], people: {}, dms: [], me: null, unread: 0,
  sid: 0, ch: 0, thread: null, msgs: [], more: false, loading: false,
  reply: null, edit: null, sel: null, typing: {}, reads: {}, pres: {},
  es: null, esTries: 0, view: 'chat', results: null, q: '',
  dmRun: 0, dmCtl: null, lastTyping: 0, lastRead: 0, syncAt: 0,
  draft: '', taFocus: false, files: [], prev: null, prevCache: {}, stickers: [],
  assets: [], assetSid: 0, assetsLoaded: false, assetTab: 'emoji',
  voice: { ch: 0, joined: false, connecting: false, muted: false, deafened: false, peers: {}, room: [], max: 8,
    err: '', speaking: false, lastSpeak: 0, local: null, ac: null, raf: 0, hb: null, ice: null,
    screen: false, screenTrack: null, screenStream: null, screenWant: 'smooth60', screenPreset: 'smooth60',
    screenMax: 3, screenAuto: true, screenOut: {}, screenIn: {}, screenIce: {}, screenStatsTimer: 0, screenStatsOn: false,
    screenStatsData: null, screenLogAt: 0, screenBadSince: 0, screenCleanSince: 0, screenDisplayFps: 0,
    screenRvcToken: 0, screenDropPrev: null, screenLowerAt: 0, synthStop: null },
};

// keep whatever is half-typed across full re-renders (server/channel changes re-render the view)
document.addEventListener('input', e => { if (e.target && e.target.id === 'soc_in') C.draft = e.target.value; });
document.addEventListener('focusin', e => { if (e.target && e.target.id === 'soc_in') C.taFocus = true; });
document.addEventListener('focusout', e => { if (e.target && e.target.id === 'soc_in') C.taFocus = false; });

const Chat = {};
const $id = id => document.getElementById(id);
const nearBottom = () => { const el = $id('soc_msgs'); return !el || el.scrollHeight - el.scrollTop - el.clientHeight < 120; };
const initials = n => String(n || '?').replace(/[^A-Za-z0-9 ]/g, '').trim().split(/\s+/).map(x => x[0] || '').join('').slice(0, 2).toUpperCase() || '#';

function norm(m) {
  m.mine = Array.isArray(m.mine) ? m.mine : (m.mine ? [m.mine] : []);
  m.re = m.re || {};
  return m;
}

function who(uid) { return (C.people[uid] || {}).display || 'Member'; }

function fmt(text) {
  let h = esc(text || '');
  (C.assets || []).forEach(a => {
    if (a.kind !== 'emoji') return;
    const t = ':' + a.slug + ':';
    if (h.includes(t)) h = h.split(t).join(`<img class="ce" src="/api/file?id=${a.upload}" alt="${esc(t)}" title="${esc(t)}" loading="lazy" decoding="async">`);
  });
  Object.values(C.people).forEach(p => {
    const n = esc(p.display || '');
    if (n) { const sn = esc(n); h = h.split('@' + sn).join(`<span class="men">@${sn}</span>`); }
  });
  return h.replace(/\n/g, '<br>');
}

const fmtSize = n => n < 1024 ? n + ' B' : n < 1048576 ? Math.round(n / 1024) + ' KB' : (n / 1048576).toFixed(1) + ' MB';
const hostOf = u => { try { return new URL(u).hostname.replace(/^www\./, ''); } catch (e) { return ''; } };
const assetById = id => (C.assets || []).find(a => a.id === +id);
const assetBySlug = slug => (C.assets || []).find(a => a.kind === 'emoji' && a.slug === slug);
const stickerOf = id => {
  const m = /^([ag])(\d+)$/.exec(String(id || ''));
  if (m) {
    const a = assetById(m[2]);
    if (a) return { img: '/api/file?id=' + a.upload, e: '', label: a.name, kind: a.kind };
  }
  return (C.stickers || []).find(s => s.id === id) || { e: '🏷️', label: String(id || 'sticker') };
};
const reactionAsset = e => { const m = /^:([a-z0-9_-]{2,24}):$/.exec(String(e || '')); return m ? assetBySlug(m[1]) : null; };
const reactionHTML = e => { const a = reactionAsset(e); return a ? `<img class="rx-ce" src="/api/file?id=${a.upload}" alt="${esc(e)}" title="${esc(e)}" loading="lazy" decoding="async">` : esc(e); };
const reactionChoices = () => CH_EMOJI.concat((C.assets || []).filter(a => a.kind === 'emoji' && a.active).map(a => ':' + a.slug + ':'));
const fileIcon = () => ic('file', 18);

function attHTML(f, mid) {
  const url = '/api/file?id=' + f.id;
  if (String(f.mime).startsWith('image/')) {
    return `<button type="button" class="att-img" data-cact="img" data-id="${f.id}" data-mid="${mid || ''}" aria-label="Open ${esc(f.name)}">
      <img src="${url}" alt="${esc(f.name)}" loading="lazy" decoding="async"><span class="att-zoom" aria-hidden="true">⤢</span></button>`;
  }
      return `<a class="att-file" href="${url}" download="${esc(f.name)}" title="Download ${esc(f.name)}"><span class="att-ic">${fileIcon(f.mime)}</span><span class="ell grow">${esc(f.name)}</span><span class="xs mut">${fmtSize(f.size)}</span><span class="att-dl" aria-hidden="true">${ic('download', 15)}</span></a>`;
}

function lpHTML(p) {
  return `<a class="lp" href="${esc(p.url)}" target="_blank" rel="noopener noreferrer nofollow">
    ${p.image ? `<img class="lp-i" src="${esc(p.image)}" alt="" loading="lazy" referrerpolicy="no-referrer">` : ''}
    <span class="lp-b"><span class="xs mut up ell">${esc(p.site || 'link')}</span><b class="ell">${esc(p.title || p.url)}</b>
      ${p.desc ? `<span class="lp-d">${esc(p.desc)}</span>` : ''}<span class="xs mut ell">${esc(hostOf(p.url))}</span></span></a>`;
}

function msgHTML(m, prev) {
  const p = C.people[m.uid] || { display: 'Member', emoji: '👤', color: '#8b8ba3' };
  const mine = m.uid === (S.user || {}).id;
  const grp = !!(prev && prev.uid === m.uid && (new Date(m.ts) - new Date(prev.ts)) < 300000);
  const ment = !mine && m.text && m.text.toLowerCase().includes('@' + String((S.user || {}).display || '').toLowerCase());
  const res = Object.entries(m.re && typeof m.re === 'object' ? m.re : {});
  const mineRx = Array.isArray(m.mine) ? m.mine : [];
  const rx = res.length
    ? `<div class="rxs" role="group" aria-label="Reactions">${res.map(([e, n]) => { return `<button class="rx ${mineRx.includes(e) ? 'me' : ''}" data-cact="react" data-id="${m.id}" data-e="${esc(e)}" title="${n} reaction${n === 1 ? '' : 's'} · ${mineRx.includes(e) ? 'click to remove yours' : 'click to add yours'}" aria-pressed="${mineRx.includes(e)}">${reactionHTML(e)}<b>${n}</b></button>`; }).join('')}<button class="rx rx-add" data-cact="rxopen" data-id="${m.id}" title="Add a reaction" aria-label="Add a reaction">${ic('plus', 12)}</button></div>` : '';
  const acts = `<div class="macts" role="group" aria-label="Message actions">
    <button class="ma ma-rx" data-cact="rxopen" data-id="${m.id}" title="Add a reaction" aria-label="Add a reaction">${ic('smile', 16)}</button>
    <button class="ma" data-cact="reply" data-id="${m.id}" title="Reply" aria-label="Reply">${ic('reply', 16)}</button>
    ${mine ? `<button class="ma" data-cact="edit" data-id="${m.id}" title="Edit" aria-label="Edit">${ic('edit', 16)}</button>` : ''}
    <button class="ma" data-cact="more" data-id="${m.id}" title="More actions" aria-label="More actions">${ic('more', 16)}</button></div>`;
  const qt = m.reply ? `<div class="qt" data-cact="jump" data-id="${m.reply.id}"><b>${esc(who(m.reply.uid))}</b> ${esc(m.reply.text)}</div>` : '';
  const st = m.sticker ? stickerOf(m.sticker) : null;
  const sticker = st ? (st.img
    ? `<div class="stk cust ${st.kind || ''}"><img src="${st.img}" alt="${esc(st.label)}" loading="lazy" decoding="async"></div>`
    : `<div class="stk"><span class="stk-e">${st.e}</span><span class="stk-l">${esc(st.label)}</span></div>`) : '';
  const files = Array.isArray(m.files) ? m.files : [];
  const atts = files.length ? `<div class="atts n${Math.min(files.length, 4)}">${files.map(f => attHTML(f, m.id)).join('')}</div>` : '';
  const lp = m.preview ? lpHTML(m.preview) : '';
  return `<div class="msg ${grp ? 'grp' : ''} ${ment ? 'ment' : ''}" data-mid="${m.id}">
    ${grp ? '<div class="av sp"></div>' : `<span data-act="profile" data-id="${m.uid}" style="cursor:pointer">${avatar(p.emoji, p.color, '', null, p)}</span>`}
    <div class="mb">${grp ? '' : `<div class="mh"><b style="color:${esc(p.color || '#b4b4be')}">${esc(p.display || 'Member')}</b><span class="xs mut">${chatClock(m.ts)}</span></div>`}
      ${qt}${sticker}${m.text ? `<div class="mt">${fmt(m.text)}${m.edited ? ' <span class="xs mut">(edited)</span>' : ''}</div>` : ''}${atts}${lp}${rx}</div>${acts}</div>`;
}

function paint() {
  const el = $id('soc_msgs'); if (!el) return;
  let h = '', prev = null, prevDay = '';
  if (C.more) h += '<div class="c mt8"><button class="btn-s" data-cact="older">Load earlier messages</button></div>';
  if (!C.msgs.length) h += `<div class="soc-empty">${C.loading ? 'Loading…' : 'No messages yet. Say something.'}</div>`;
  C.msgs.forEach(m => {
    const day = chatDay(m.ts);
    if (day !== prevDay) { h += `<div class="daysep"><span>${esc(day)}</span></div>`; prevDay = day; prev = null; }
    h += msgHTML(m, prev);
    prev = m;
  });
  el.innerHTML = h;
  el.scrollTop = el.scrollHeight;
  paintMeta();
}

function paintMeta() {
  const ty = $id('soc_typing');
  if (ty) {
    const names = Object.keys(C.typing).filter(u => Date.now() - C.typing[u] < 6500 && +u !== S.user.id).map(who);
    ty.textContent = names.length ? `${names.slice(0, 3).join(', ')} ${names.length > 1 ? 'are' : 'is'} typing…` : '';
  }
  const seen = $id('soc_seen');
  if (seen) {
    const lastMine = [...C.msgs].reverse().find(m => m.uid === (S.user || {}).id);
    const names = lastMine ? Object.entries(C.reads).filter(([u, id]) => +u !== S.user.id && +id >= lastMine.id).map(([u]) => who(u)) : [];
    seen.innerHTML = names.length ? `${ic('check', 12)} Seen by ${esc(names.slice(0, 3).join(', '))}${names.length > 3 ? ` +${names.length - 3}` : ''}` : '';
  }
}

function rerenderMsg(id) {
  const i = C.msgs.findIndex(m => m.id === id); if (i < 0) return;
  const el = document.querySelector(`#soc_msgs [data-mid="${id}"]`); if (!el) return;
  const prev = i ? C.msgs[i - 1] : null;
  el.outerHTML = msgHTML(C.msgs[i], prev && chatDay(prev.ts) === chatDay(C.msgs[i].ts) ? prev : null);
}

function appendMsg(m) {
  norm(m);
  if (C.msgs.some(x => x.id === m.id)) return;
  const el = $id('soc_msgs'); if (!el) { C.msgs.push(m); return; }
  const prev = C.msgs[C.msgs.length - 1] || null;
  const stick = nearBottom() || m.uid === (S.user || {}).id;
  let h = '';
  if (!prev || chatDay(prev.ts) !== chatDay(m.ts)) h += `<div class="daysep"><span>${esc(chatDay(m.ts))}</span></div>`;
  const grp = (!h && prev) ? prev : null;
  el.querySelector('.soc-empty')?.remove();
  el.insertAdjacentHTML('beforeend', msgHTML(m, grp));
  C.msgs.push(m);
  if (stick) el.scrollTop = el.scrollHeight;
  paintMeta();
}

function touchMsg(id, fn) {
  const m = C.msgs.find(x => x.id === id); if (!m) return null;
  fn(m); rerenderMsg(id); paintMeta();
  return m;
}

/* ---------- data ---------- */
Chat.load = async function () {
  try {
    const r = await api('servers');
    C.servers = r.servers || []; C.people = r.people || {}; C.dms = r.dms || []; C.me = r.me; C.unread = r.unread || 0;
    C.loaded = true; C.error = '';
    if (!C.stickers.length) api('stickers').then(x => { C.stickers = x.stickers || []; }).catch(() => { });
  } catch (e) {
    C.loaded = true; C.error = e.message === 'login' ? '' : 'Could not load chat.';
    return;
  }
  // a channel or server can disappear while you are in it (deleted, kicked, banned)
  if (C.thread && C.thread.kind === 'ch' && !C.servers.some(s => (s.channels || []).some(c => c.id === C.thread.id))) {
    C.thread = null; C.msgs = []; C.more = false;
  }
  if (C.voice.joined && !C.servers.some(s => (s.channels || []).some(c => c.id === C.voice.ch))) {
    voiceStop(true); C.thread = null; C.msgs = []; C.more = false;
  }
  const savedS = +localStorage.getItem('rg_soc_sid') || 0;
  if (!C.servers.some(s => s.id === C.sid)) C.sid = C.servers.some(s => s.id === savedS) ? savedS : (C.servers[0] || {}).id || 0;
  const srv = C.servers.find(s => s.id === C.sid);
  if (srv && !srv.channels.some(c => c.id === C.ch && c.kind === 'text')) {
    const savedC = +localStorage.getItem('rg_soc_ch') || 0;
    const pick = srv.channels.find(c => c.id === savedC && c.kind === 'text') || srv.channels.find(c => c.kind === 'text');
    C.ch = pick ? pick.id : 0;
  }
  if (!C.thread && C.ch) await Chat.openChannel(C.ch, true);
  Chat.connect();
  Chat.badge();
};

Chat.reset = function () {
  closeRx(); if (LB.open) lbClose();
  C.loaded = false; C.servers = []; C.dms = []; C.people = {}; C.msgs = []; C.thread = null; C.sid = 0; C.ch = 0;
  C.assets = []; C.assetSid = 0; C.assetsLoaded = false; C.assetTab = 'emoji';
  C.typing = {}; C.reads = {}; C.sel = C.reply = C.edit = null; C.results = null;
  voiceStop(true);
  Chat.stopDM();
  if (C.es) { try { C.es.close(); } catch (e) { } C.es = null; }
};

Chat.enter = function () { if (C.loaded) Chat.connect(); Chat.badge(); };

Chat.reload = async function () {
  const th = C.thread && C.thread.kind === 'ch' ? C.thread.id : 0;
  try { await Chat.load(); } catch (e) { }
  if (th && C.thread && C.thread.id === th && !C.msgs.length && C.ch === th) await Chat.openChannel(th, true);
  render();
  if (C.thread && C.thread.kind === 'ch') Chat.sync();
};
Chat.leave = function () { };

/* ---------- realtime ---------- */
Chat.connect = function () {
  if (C.es || !S.user) return;
  try {
    const es = new EventSource('/api/stream');
    C.es = es;
    es.onopen = () => { C.esTries = 0; Chat.sync(); };
    es.onerror = () => {
      C.esTries++;
      if (C.esTries > 6 && C.es) {
        try { C.es.close(); } catch (e) { }
        C.es = null;
        // No signaling path: drop the mic and every screen encoder instead of
        // leaving them hot until the server prunes the seat.
        if (C.voice.joined) { voiceStop(false); try { render(); } catch (e) { } }
      }
    };
    const on = (name, fn) => es.addEventListener(name, ev => { try { fn(JSON.parse(ev.data)); } catch (e) { } });
    on('msg', d => {
      if (d.ch === C.ch && C.thread && C.thread.kind === 'ch') {
        appendMsg(d.message);
        if (!document.hidden) Chat.read(d.message.id);
      }
      const s = C.servers.find(x => x.channels.some(c => c.id === d.ch));
      const ch = s && s.channels.find(c => c.id === d.ch);
      if (ch) {
        ch.last = { id: d.message.id, uid: d.message.uid, ts: d.message.ts, text: (d.message.text || '').slice(0, 80) };
        if (!(C.thread && C.thread.kind === 'ch' && C.ch === d.ch && !document.hidden)) {
          ch.unread = (ch.unread || 0) + 1; s.unread = (s.unread || 0) + 1; Chat.badge();
        }
      }
    });
    on('edit', d => { if (d.ch === C.ch) touchMsg(d.id, m => { m.text = d.text; m.edited = true; }); });
    on('del', d => {
      if (d.ch !== C.ch) return;
      const gone = new Set(d.ids || []);
      C.msgs = C.msgs.filter(m => !gone.has(m.id));
      (d.ids || []).forEach(id => document.querySelector(`#soc_msgs [data-mid="${id}"]`)?.remove());
      paintMeta();
    });
    on('react', d => { if (d.ch === C.ch) touchMsg(d.id, m => { m.re = d.re || {}; }); });
    on('typing', d => {
      if (d.ch !== C.ch) return;
      C.typing[d.uid] = Date.now(); paintMeta();
      clearTimeout(C._tyT);
      C._tyT = setTimeout(paintMeta, 7000);
    });
    on('read', d => { if (d.ch === C.ch) { C.reads[d.uid] = d.id; paintMeta(); } });
    on('presence', d => { C.pres[d.uid] = { on: !!d.online, name: d.name }; });
    on('voice', d => Chat.voiceEvent(d));
    on('music', d => { if (window.Music) Music.event(d); });
    on('channels', d => Chat.reload(d));
    on('members', d => Chat.reload(d));
    on('roles', d => Chat.reload(d));
    on('asset', d => {
      if (d.server !== C.sid || !d.asset) return;
      const i = (C.assets || []).findIndex(a => a.id === d.asset.id);
      if (i >= 0) C.assets[i] = d.asset; else C.assets.push(d.asset);
      C.assetsLoaded = true;
      refreshExpr();
      if (C.thread && C.thread.kind === 'ch') paint();
    });
    on('asset_del', d => {
      if (d.server !== C.sid) return;
      const a = (C.assets || []).find(x => x.id === d.id);
      if (a) a.active = false;
      refreshExpr();
    });
  } catch (e) { C.es = null; }
};

Chat.sync = async function () {
  if (!C.thread || C.thread.kind !== 'ch' || !S.user) return;
  const last = C.msgs.length ? C.msgs[C.msgs.length - 1].id : 0;
  const first = C.msgs.length ? C.msgs[0].id : 0;
  try {
    const r = await api(`ch/messages?ch=${C.ch}&after=${last}&first=${first}${document.hidden ? '' : '&mark=1'}`);
    if (C.thread.id !== r.channel.id) return;
    (r.messages || []).forEach(appendMsg);
    if (r.deleted && r.deleted.length) {
      const gone = new Set(r.deleted);
      C.msgs = C.msgs.filter(m => !gone.has(m.id));
      r.deleted.forEach(id => document.querySelector(`#soc_msgs [data-mid="${id}"]`)?.remove());
    }
    Object.assign(C.people, r.people || {}); Object.assign(C.reads, r.reads || {});
    C.typing = {}; (r.typing || []).forEach(u => { C.typing[u] = Date.now(); });
    paintMeta();
  } catch (e) { }
};

Chat.badge = function () {
  C.unread = (C.servers || []).reduce((a, s) => a + (s.unread || 0), 0) + (C.dms || []).reduce((a, d) => a + (d.unread || 0), 0);
  const b = document.querySelector('.nav button[data-v="chat"]'); if (!b) return;
  let i = b.querySelector('.nb');
  if (C.unread) { if (!i) { i = document.createElement('i'); i.className = 'nb'; b.appendChild(i); } i.textContent = C.unread > 9 ? '9+' : C.unread; }
  else if (i) i.remove();
};

/* ---------- navigation ---------- */
Chat.srv = function (id) {
  closeRx(); if (LB.open) lbClose();
  if (C.sid !== id) { C.assets = []; C.assetSid = 0; C.assetsLoaded = false; }
  C.sid = id; localStorage.setItem('rg_soc_sid', String(id));
  const srv = C.servers.find(s => s.id === id);
  const ch = srv && (srv.channels.find(c => c.kind === 'text') || srv.channels[0]);
  C.thread = null; C.msgs = [];
  if (ch) return Chat.openChannel(ch.id);
  render();
};

Chat.openDM = async function (uid) {
  closeRx(); if (LB.open) lbClose();
  Chat.stopDM();
  C.thread = { kind: 'dm', id: uid }; C.msgs = []; C.more = false; C.sel = C.reply = C.edit = null; C.draft = ''; C.files = []; C.prev = null;
  C.view = 'chat'; C.results = null;
  const my = ++C.dmRun;
  render();
  try {
    const r = await api('chat/messages?thread=' + encodeURIComponent('dm:' + uid) + '&mark=1');
    if (C.dmRun !== my) return;
    C.msgs = (r.messages || []).map(norm); C.more = !!r.more;
    Object.assign(C.people, r.people || {}); C.reads = {};
    C.loading = false; paint(); dmLoop(my);
    const d = C.dms.find(x => x.id === uid); if (d) { d.unread = 0; Chat.badge(); }
  } catch (e) { C.loading = false; }
};

Chat.openChannel = async function (id, silent) {
  closeRx(); if (LB.open) lbClose();
  Chat.stopDM();
  const srv = C.servers.find(s => s.channels.some(c => c.id === id));
  if (srv) {
    if (C.sid !== srv.id) { C.assets = []; C.assetSid = 0; C.assetsLoaded = false; }
    C.sid = srv.id;
  }
  const assetsReady = C.sid ? Chat.loadAssets(C.sid) : Promise.resolve([]);
  C.ch = id; C.thread = { kind: 'ch', id }; C.msgs = []; C.more = false; C.sel = C.reply = C.edit = null; C.draft = ''; C.files = []; C.prev = null;
  C.results = null; C.view = 'chat'; C.loading = true;
  localStorage.setItem('rg_soc_ch', String(id));
  if (!silent) render();
  try {
    const r = await api(`ch/messages?ch=${id}&mark=1`);
    if (!C.thread || C.thread.id !== id) return;
    await assetsReady;
    C.msgs = (r.messages || []).map(norm); C.more = !!r.more;
    Object.assign(C.people, r.people || {}); C.reads = r.reads || {};
    C.typing = {}; (r.typing || []).forEach(u => { C.typing[u] = Date.now(); });
    C.loading = false;
    const s = C.servers.find(x => x.id === C.sid); const ch = s && s.channels.find(c => c.id === id);
    if (ch) { ch.unread = 0; s.unread = s.channels.reduce((a, c) => a + (c.unread || 0), 0); Chat.badge(); }
    if (silent) return;
    paint();
    const ta = $id('soc_in'); if (ta && !matchMedia('(pointer:coarse)').matches) ta.focus();
  } catch (e) { C.loading = false; }
};

Chat.stopDM = function () {
  C.dmRun++;
  if (C.dmCtl) { try { C.dmCtl.abort(); } catch (e) { } C.dmCtl = null; }
};

async function dmLoop(my) {
  while (C.dmRun === my && C.thread && C.thread.kind === 'dm' && S.user) {
    const last = C.msgs.length ? C.msgs[C.msgs.length - 1].id : 0;
    const first = C.msgs.length ? C.msgs[0].id : 0;
    const ctl = new AbortController(); C.dmCtl = ctl;
    try {
      const res = await fetch(`/api/chat/messages?thread=${encodeURIComponent('dm:' + C.thread.id)}&after=${last}&first=${first}&wait=20${document.hidden ? '' : '&mark=1'}`, { signal: ctl.signal });
      if (C.dmRun !== my) return;
      if (!res.ok) throw new Error(res.status);
      const r = await res.json();
      if (C.dmRun !== my) return;
      (r.messages || []).forEach(m => { norm(m); if (!C.msgs.some(x => x.id === m.id)) { C.msgs.push(m); appendMsg(m); } });
      Object.assign(C.people, r.people || {});
      if (r.deleted && r.deleted.length) {
        const gone = new Set(r.deleted);
        C.msgs = C.msgs.filter(m => !gone.has(m.id));
        r.deleted.forEach(id => document.querySelector(`#soc_msgs [data-mid="${id}"]`)?.remove());
      }
      paintMeta();
    } catch (e) {
      if (C.dmRun !== my) return;
      await new Promise(ok => setTimeout(ok, 2500));
    }
  }
}

/* ---------- voice (WebRTC mesh over SSE signaling) ---------- */
function voiceChannelOf(id) {
  for (const s of C.servers || []) {
    const c = (s.channels || []).find(x => x.id === id);
    if (c) return { s, c };
  }
  return {};
}

function voiceAudioBox() {
  let b = document.getElementById('voice_audio');
  if (!b) { b = document.createElement('div'); b.id = 'voice_audio'; b.hidden = true; document.body.appendChild(b); }
  return b;
}

/* Screen share is its own video-only peer connection per viewer. The old
   attempt reused the audio mesh's blank-canvas transceiver, which kept an
   encoder alive for every peer and left the answerer's direction at recvonly
   on the first share. Separate connections make teardown and encodings exact. */
const SCREEN_PRESETS = {
  smooth60: { key: 'smooth60', label: '1080p60', name: 'Smooth 1080p60', w: 1920, h: 1080, fps: 60, kbps: 8000, hint: 'motion', note: 'Games and video · about 8 Mbps upload per viewer' },
  sharp30: { key: 'sharp30', label: '1080p30', name: 'Sharp 1080p30', w: 1920, h: 1080, fps: 30, kbps: 5000, hint: 'detail', note: 'Text, code and slides · about 5 Mbps per viewer' },
  lite720: { key: 'lite720', label: '720p30', name: 'Lite 720p30', w: 1280, h: 720, fps: 30, kbps: 2500, hint: 'motion', note: 'Weak uplink or many viewers · about 2.5 Mbps per viewer' },
};
const SCREEN_ORDER = ['smooth60', 'sharp30', 'lite720'];

function screenDebug() {
  try { return localStorage.getItem('streamDebug') === '1'; } catch (e) { return false; }
}

function screenSynthetic() {
  try {
    const loop = location.hostname === 'localhost' || location.hostname === '127.0.0.1';
    return loop && new URLSearchParams(location.search).get('synthetic') === '1';
  } catch (e) { return false; }
}

function screenSynthOpt(name) {
  try {
    if (!screenSynthetic()) return '';
    return new URLSearchParams(location.search).get(name) || '';
  } catch (e) { return ''; }
}

function screenPresetForViewers(n, want) {
  let idx = Math.max(0, SCREEN_ORDER.indexOf(want || 'smooth60'));
  if (n >= 5) idx = Math.max(idx, 2);
  else if (n >= 3) idx = Math.max(idx, 1);
  return SCREEN_ORDER[Math.min(idx, SCREEN_ORDER.length - 1)];
}

function screenViewers() {
  return Object.values(C.voice.screenOut || {}).filter(s => s && s.pc && s.answered).length;
}

async function screenCapture(key) {
  const p = SCREEN_PRESETS[key] || SCREEN_PRESETS.smooth60;
  if (screenSynthetic()) {
    const c = document.createElement('canvas'); c.width = p.w; c.height = p.h;
    const x = c.getContext('2d');
    let live = true, f = 0, timer = 0, px = -1, py = -1;
    const W = 240, H = 200, Y = Math.round((p.h - H) / 2);
    if (x) {
      // Static background once: repainting 2M pixels with a gradient and text
      // every frame is ~5 fps on headless software raster, which would cap the
      // capture before WebRTC is even involved.
      const g = x.createLinearGradient(0, 0, p.w, p.h);
      g.addColorStop(0, '#0b1020'); g.addColorStop(1, '#16324f');
      x.fillStyle = g; x.fillRect(0, 0, p.w, p.h);
      x.fillStyle = '#ffffff'; x.font = '52px monospace';
      x.fillText(p.w + 'x' + p.h + ' · synthetic 60fps', 40, 90);
      x.fillText('moving block = frames', 40, 165);
    }
    const draw = () => {
      if (!live) return;
      if (x) {
        if (px >= 0) { x.fillStyle = '#0b1020'; x.fillRect(px, py, W, H); }
        px = Math.round((Math.sin(f / 45) * 0.5 + 0.5) * (p.w - W));
        py = Y;
        x.fillStyle = '#3dd6a0'; x.fillRect(px, py, W, H);
      }
      f++;
      timer = setTimeout(draw, Math.max(1, Math.floor(1000 / p.fps) - 2));
    };
    draw();
    C.voice.synthStop = () => { live = false; clearTimeout(timer); };
    return c.captureStream(p.fps);
  }
  if (!navigator.mediaDevices || !navigator.mediaDevices.getDisplayMedia) {
    throw new Error('This browser does not support screen sharing.');
  }
  return navigator.mediaDevices.getDisplayMedia({
    video: {
      width: { ideal: p.w, max: p.w },
      height: { ideal: p.h, max: p.h },
      frameRate: { ideal: p.fps, max: p.fps },
      cursor: 'always',
    },
    audio: false,
    selfBrowserSurface: 'exclude',
    surfaceSwitching: 'include',
    systemAudio: 'exclude',
  });
}

async function screenApplyCapture(key) {
  const p = SCREEN_PRESETS[key];
  if (!p || !C.voice.screenTrack) return;
  try { C.voice.screenTrack.contentHint = p.hint; } catch (e) { }
  try {
    await C.voice.screenTrack.applyConstraints({
      width: { ideal: p.w, max: p.w },
      height: { ideal: p.h, max: p.h },
      frameRate: { ideal: p.fps, max: p.fps },
    });
  } catch (e) { }
}

async function screenCodecs(p, forceMime) {
  try {
    if (!window.RTCPeerConnection || !RTCRtpSender.getCapabilities) return null;
    const caps = RTCRtpSender.getCapabilities('video');
    if (!caps || !caps.codecs || !caps.codecs.length) return null;
    const mimes = ['video/H264', 'video/VP9', 'video/AV1', 'video/VP8'];
    const score = [];
    for (const mime of mimes) {
      let power = false;
      try {
        const info = await navigator.mediaCapabilities.encodingInfo({
          type: 'webrtc',
          video: { contentType: mime, width: p.w, height: p.h, bitrate: p.kbps * 1000, framerate: p.fps },
        });
        power = !!info.powerEfficient;
      } catch (e) { }
      score.push({ mime: mime.toLowerCase(), power: power });
    }
    // Hardware H264/VP9/AV1 first, VP8 last: CPU software VP8 at 1080p60 is
    // the classic qualityLimitationReason=cpu failure.
    const hw = score.filter(x => x.power && x.mime !== 'video/vp8');
    const rest = score.filter(x => !x.power && x.mime !== 'video/vp8');
    // No hardware encoder: libvpx realtime VP8 is usually faster than software
    // OpenH264/VP9 at 1080p. Hardware H264/VP9/AV1 still wins when available.
    let order = (hw.length
      ? hw.concat(rest).concat(score.filter(x => x.mime === 'video/vp8'))
      : score.filter(x => x.mime === 'video/vp8').concat(rest))
      .map(x => x.mime);
    // Safari/WebKit is H.264-first for WebRTC video; VP8 support is unreliable.
    if (/Safari\//.test(navigator.userAgent) && !/Chrome\//.test(navigator.userAgent)) {
      const at = order.indexOf('video/h264');
      if (at > 0) { order.splice(at, 1); order.unshift('video/h264'); }
    }
    const forced = forceMime || ('video/' + (screenSynthOpt('codec') || '').toLowerCase());
    if (forced && forced !== 'video/') {
      const at = order.indexOf(forced);
      if (at > 0) { order.splice(at, 1); order.unshift(forced); }
    }
    const byMime = {};
    caps.codecs.forEach(c => {
      const mime = String(c.mimeType || '').toLowerCase();
      if (!byMime[mime]) byMime[mime] = [];
      byMime[mime].push(c);
    });
    const out = [];
    order.forEach(mime => { (byMime[mime] || []).forEach(c => out.push(c)); });
    caps.codecs.forEach(c => { if (/rtx|red|ulpfec|flexfec/i.test(String(c.mimeType || ''))) out.push(c); });
    return out.length ? out : null;
  } catch (e) { return null; }
}

async function screenParams(s) {
  if (!s || !s.sender) return;
  const p = SCREEN_PRESETS[C.voice.screenPreset] || SCREEN_PRESETS.smooth60;
  try {
    const sp = s.sender.getParameters();
    if (!sp.encodings || !sp.encodings.length) sp.encodings = [{}];
    Object.assign(sp.encodings[0], {
      maxBitrate: p.kbps * 1000,
      maxFramerate: p.fps,
      scaleResolutionDownBy: 1,
      priority: 'high',
      networkPriority: 'high',
    });
    try { sp.degradationPreference = p.hint === 'detail' ? 'maintain-resolution' : 'maintain-framerate'; } catch (e) { }
    await s.sender.setParameters(sp);
  } catch (e) { }
}

function screenCloseOut(uid) {
  const s = C.voice.screenOut[uid];
  if (!s) return;
  clearTimeout(s.timer);
  try { if (s.pc) s.pc.close(); } catch (e) { }
  delete C.voice.screenOut[uid];
}

function screenCloseIn(uid) {
  const v = C.voice.screenIn[uid];
  delete C.voice.screenIce[uid];
  if (!v) return;
  try { if (v.pc) v.pc.close(); } catch (e) { }
  delete C.voice.screenIn[uid];
}

async function screenOffer(uid, retry) {
  if (!C.voice.screen || !C.voice.screenTrack || !C.voice.joined) return;
  if (C.voice.screenOut[uid] && !retry) return;
  screenCloseOut(uid);
  const pc = new RTCPeerConnection({
    iceServers: C.voice.ice || [{ urls: 'stun:stun.l.google.com:19302' }],
    iceCandidatePoolSize: 2,
  });
  const s = C.voice.screenOut[uid] = { pc: pc, pending: [], answered: false, retry: !!retry, last: {}, _statsPrev: {} };
  const p = SCREEN_PRESETS[C.voice.screenPreset] || SCREEN_PRESETS.smooth60;
  const codecs = retry ? await screenCodecs(p, 'video/h264') : await screenCodecs(p);
  let tr;
  try {
    tr = pc.addTransceiver(C.voice.screenTrack, {
      direction: 'sendonly',
      streams: [C.voice.screenStream],
      sendEncodings: [{
        maxBitrate: p.kbps * 1000,
        maxFramerate: p.fps,
        scaleResolutionDownBy: 1,
        priority: 'high',
        networkPriority: 'high',
      }],
    });
  } catch (e) {
    screenCloseOut(uid);
    return;
  }
  s.sender = tr.sender;
  if (codecs) { try { tr.setCodecPreferences(codecs); } catch (e) { } }
  pc.onicecandidate = e => {
    if (!e.candidate) return;
    const c = e.candidate.toJSON ? e.candidate.toJSON() : {
      candidate: e.candidate.candidate, sdpMid: e.candidate.sdpMid, sdpMLineIndex: e.candidate.sdpMLineIndex,
    };
    c.screen = true;
    api('voice/signal', { ch: C.voice.ch, to: uid, kind: 'ice', payload: c }).catch(() => { });
  };
  pc.onconnectionstatechange = () => {
    if (pc.connectionState === 'connected') { screenParams(s); paintScreen(); }
    else if (pc.connectionState === 'failed') { screenCloseOut(uid); paintScreen(); }
  };
  try {
    await pc.setLocalDescription(await pc.createOffer());
    await api('voice/signal', {
      ch: C.voice.ch, to: uid, kind: 'offer',
      payload: { type: 'offer', sdp: pc.localDescription.sdp, screen: true, preset: C.voice.screenPreset },
    });
  } catch (e) { screenCloseOut(uid); return; }
  clearTimeout(s.timer);
  if (!retry) {
    s.timer = setTimeout(() => {
      if (!s.answered && C.voice.screenOut[uid] === s && C.voice.screen) screenOffer(uid, true);
    }, 7000);
  }
  paintScreen();
}

async function screenOnSignal(uid, kind, payload) {
  if (!C.voice.joined) return;
  if (kind === 'offer') {
    screenCloseIn(uid);
    const pc = new RTCPeerConnection({
      iceServers: C.voice.ice || [{ urls: 'stun:stun.l.google.com:19302' }],
      iceCandidatePoolSize: 2,
    });
    const v = C.voice.screenIn[uid] = { pc: pc, pending: [], preset: payload.preset || '', stream: null, last: {}, _statsPrev: {} };
    pc.ontrack = e => {
      if (e.track.kind !== 'video') return;
      v.stream = e.streams[0] || new MediaStream([e.track]);
      try { if (e.receiver && 'jitterBufferTarget' in e.receiver) e.receiver.jitterBufferTarget = 0; } catch (x) { }
      C.voice.screenDropPrev = null;
      paintScreen();
      screenStatsMaybe();
    };
    pc.onicecandidate = e => {
      if (!e.candidate) return;
      const c = e.candidate.toJSON ? e.candidate.toJSON() : {
        candidate: e.candidate.candidate, sdpMid: e.candidate.sdpMid, sdpMLineIndex: e.candidate.sdpMLineIndex,
      };
      c.screen = true;
      api('voice/signal', { ch: C.voice.ch, to: uid, kind: 'ice', payload: c }).catch(() => { });
    };
    pc.onconnectionstatechange = () => {
      if (pc.connectionState === 'failed') { screenCloseIn(uid); paintScreen(); }
    };
    try {
      await pc.setRemoteDescription({ type: 'offer', sdp: payload.sdp });
      const early = (C.voice.screenIce[uid] || []).concat(v.pending.splice(0));
      delete C.voice.screenIce[uid];
      for (const c of early) { try { await pc.addIceCandidate(c); } catch (e) { } }
      const ans = await pc.createAnswer();
      await pc.setLocalDescription(ans);
      await api('voice/signal', {
        ch: C.voice.ch, to: uid, kind: 'answer',
        payload: { type: 'answer', sdp: ans.sdp, screen: true },
      });
      paintScreen();
      screenStatsMaybe();
    } catch (e) {
      screenCloseIn(uid);
      try {
        await api('voice/signal', {
          ch: C.voice.ch, to: uid, kind: 'answer',
          payload: { type: 'answer', sdp: 'v=0\r\n', screen: true, retry: true },
        });
      } catch (x) { }
      paintScreen();
    }
  } else if (kind === 'answer') {
    const s = C.voice.screenOut[uid];
    if (payload.retry) { screenOffer(uid, true); return; }
    if (!s || !s.pc) return;
    try {
      await s.pc.setRemoteDescription({ type: 'answer', sdp: payload.sdp });
      s.answered = true;
      clearTimeout(s.timer);
      for (const c of s.pending.splice(0)) { try { await s.pc.addIceCandidate(c); } catch (e) { } }
      await screenParams(s);
    } catch (e) { screenOffer(uid, true); }
    paintScreen();
  } else if (kind === 'ice') {
    const c = { candidate: payload.candidate, sdpMid: payload.sdpMid, sdpMLineIndex: payload.sdpMLineIndex, usernameFragment: payload.usernameFragment };
    const s = C.voice.screenOut[uid], v = C.voice.screenIn[uid];
    if (s && s.pc.remoteDescription) { try { await s.pc.addIceCandidate(c); } catch (e) { } }
    else if (v && v.pc.remoteDescription) { try { await v.pc.addIceCandidate(c); } catch (e) { } }
    else if (v) v.pending.push(c);
    else if (s) s.pending.push(c);
    else (C.voice.screenIce[uid] = C.voice.screenIce[uid] || []).push(c);
  } else if (kind === 'preset') {
    const v = C.voice.screenIn[uid];
    if (v && payload.preset) { v.preset = payload.preset; paintScreen(); }
  } else if (kind === 'lower') {
    const idx = SCREEN_ORDER.indexOf(C.voice.screenPreset);
    if (idx >= 0 && idx < SCREEN_ORDER.length - 1) screenApplyPreset(SCREEN_ORDER[idx + 1], true, 'viewer');
  }
}

function screenTeardown(notify) {
  const st = C.voice.screenTrack;
  C.voice.screen = false;
  C.voice.screenTrack = null;
  C.voice.screenStream = null;
  C.voice.screenBadSince = 0;
  C.voice.screenCleanSince = 0;
  C.voice.screenRvcToken = (C.voice.screenRvcToken || 0) + 1;
  Object.keys(C.voice.screenOut || {}).forEach(screenCloseOut);
  Object.keys(C.voice.screenIn || {}).forEach(screenCloseIn);
  C.voice.screenIce = {};
  clearInterval(C.voice.screenStatsTimer);
  C.voice.screenStatsTimer = 0;
  if (C.voice.synthStop) { try { C.voice.synthStop(); } catch (e) { } C.voice.synthStop = null; }
  try { if (st) st.stop(); } catch (e) { }
  const box = document.getElementById('screen_stats');
  if (box) { box.hidden = true; box.textContent = ''; }
  const me = (C.voice.room || []).find(p => p.uid === (S.user || {}).id);
  if (me) me.screen = false;
  C.voice.screenStatsData = null;
  if (notify && C.voice.joined) {
    api('voice/state', { ch: C.voice.ch, muted: C.voice.muted, deafened: C.voice.deafened, screen: false }).catch(() => { });
  }
}

async function screenApplyPreset(key, auto, why) {
  const p = SCREEN_PRESETS[key];
  if (!p) return;
  const prev = C.voice.screenPreset;
  C.voice.screenPreset = key;
  if (!C.voice.screen) return;
  C.voice.screenStartAt = Date.now();
  C.voice.screenBadSince = 0;
  await screenApplyCapture(key);
  await Promise.all(Object.values(C.voice.screenOut).map(screenParams));
  Object.keys(C.voice.screenOut).forEach(uid => {
    api('voice/signal', { ch: C.voice.ch, to: +uid, kind: 'preset', payload: { screen: true, preset: key } }).catch(() => { });
  });
  paintScreen();
  if (auto) {
    const whyTxt = why === 'cpu' ? 'CPU limit' : why === 'bandwidth' ? 'bandwidth limit'
      : why === 'viewers' ? 'more viewers' : why === 'clean' ? 'connection is clean' : 'viewer asked';
    toast(prev === key ? 'Screen quality' : 'Screen quality changed', p.name + ' · ' + whyTxt);
  }
}

function screenSyncViewers() {
  if (!C.voice.screen) return;
  const me = (S.user || {}).id;
  const cap = Math.max(1, C.voice.screenMax || 3);
  const others = (C.voice.room || []).filter(p => p.uid !== me).map(p => p.uid);
  const want = others.slice(0, cap);
  Object.keys(C.voice.screenOut).forEach(uid => { if (!want.includes(+uid)) screenCloseOut(uid); });
  const target = screenPresetForViewers(want.length, C.voice.screenWant || 'smooth60');
  if (SCREEN_ORDER.indexOf(target) > SCREEN_ORDER.indexOf(C.voice.screenPreset)) {
    screenApplyPreset(target, true, 'viewers');
  }
  want.forEach(uid => { if (!C.voice.screenOut[uid]) screenOffer(uid); });
  paintScreen();
}

/* ---- stream stats (debug overlay + one JSON line every 5 s) ---- */
function screenCountDisplayed() {
  const v = document.getElementById('voice_screen');
  if (!v || !v.requestVideoFrameCallback) return;
  const tok = (C.voice.screenRvcToken || 0) + 1;
  C.voice.screenRvcToken = tok;
  let n = 0, last = performance.now();
  const tick = () => {
    if (tok !== C.voice.screenRvcToken) return;
    n++;
    const now = performance.now();
    if (now - last >= 1000) {
      C.voice.screenDisplayFps = Math.round(n * 1000 / (now - last));
      n = 0; last = now;
    }
    v.requestVideoFrameCallback(tick);
  };
  v.requestVideoFrameCallback(tick);
}

async function screenGather() {
  const data = {
    at: Date.now(), preset: C.voice.screenPreset, want: C.voice.screenWant,
    viewers: 0, out: [], in: [], displayedFps: C.voice.screenDisplayFps || 0,
    capture: C.voice.screenTrack ? C.voice.screenTrack.getSettings() : null,
  };
  for (const uid in C.voice.screenOut) {
    const s = C.voice.screenOut[uid];
    if (!s || !s.pc) continue;
    let stats;
    try { stats = await s.pc.getStats(); } catch (e) { continue; }
    let out = null, src = null, pair = null, lc = null, rc = null;
    stats.forEach(r => {
      if (r.type === 'outbound-rtp' && r.kind === 'video') out = r;
      else if (r.type === 'media-source' && r.kind === 'video') src = r;
      else if (r.type === 'candidate-pair' && (r.selected || (r.state === 'succeeded' && r.nominated))) pair = r;
    });
    if (pair) stats.forEach(r => {
      if (r.type === 'local-candidate' && r.id === pair.localCandidateId) lc = r;
      if (r.type === 'remote-candidate' && r.id === pair.remoteCandidateId) rc = r;
    });
    const now = performance.now(), prev = s._statsPrev || {};
    const bitrate = out && prev.bytesSent != null
      ? Math.max(0, Math.round((out.bytesSent - prev.bytesSent) * 8000 / Math.max(1, now - prev.t))) : 0;
    s._statsPrev = { bytesSent: out ? out.bytesSent : (prev.bytesSent || 0), t: now };
    const row = {
      uid: +uid, state: s.pc.connectionState, answered: !!s.answered,
      w: out ? out.frameWidth || 0 : 0, h: out ? out.frameHeight || 0 : 0,
      fps: out ? +(out.framesPerSecond || 0).toFixed(1) : 0,
      bitrate: bitrate, target: out ? out.targetBitrate || 0 : 0,
      reason: out ? out.qualityLimitationReason || 'none' : 'none',
      encoder: out ? out.encoderImplementation || '' : '',
      power: out ? !!out.powerEfficientEncoder : false,
      encodeMs: out && out.framesEncoded ? +((out.totalEncodeTime || 0) * 1000 / out.framesEncoded).toFixed(1) : 0,
      nack: out ? out.nackCount || 0 : 0, pli: out ? out.pliCount || 0 : 0,
      srcW: src ? src.width || 0 : 0, srcH: src ? src.height || 0 : 0,
      srcFps: src ? +(src.framesPerSecond || 0).toFixed(1) : 0,
      rtt: pair && pair.currentRoundTripTime != null ? +(pair.currentRoundTripTime * 1000).toFixed(0) : 0,
      availOut: pair && pair.availableOutgoingBitrate ? Math.round(pair.availableOutgoingBitrate) : 0,
      local: lc ? lc.candidateType : '', remote: rc ? rc.candidateType : '',
    };
    s.lastStats = row;
    if (s.answered) data.viewers++;
    data.out.push(row);
  }
  for (const uid in C.voice.screenIn) {
    const v = C.voice.screenIn[uid];
    if (!v || !v.pc) continue;
    let stats;
    try { stats = await v.pc.getStats(); } catch (e) { continue; }
    let inc = null, pair = null, lc = null, rc = null;
    stats.forEach(r => {
      if (r.type === 'inbound-rtp' && r.kind === 'video') inc = r;
      else if (r.type === 'candidate-pair' && (r.selected || (r.state === 'succeeded' && r.nominated))) pair = r;
    });
    if (pair) stats.forEach(r => {
      if (r.type === 'local-candidate' && r.id === pair.localCandidateId) lc = r;
      if (r.type === 'remote-candidate' && r.id === pair.remoteCandidateId) rc = r;
    });
    const now = performance.now(), prev = v._statsPrev || {};
    const bitrate = inc && prev.bytesReceived != null
      ? Math.max(0, Math.round((inc.bytesReceived - prev.bytesReceived) * 8000 / Math.max(1, now - prev.t))) : 0;
    v._statsPrev = { bytesReceived: inc ? inc.bytesReceived : (prev.bytesReceived || 0), t: now };
    const row = {
      uid: +uid, state: v.pc.connectionState, preset: v.preset || '',
      w: inc ? inc.frameWidth || 0 : 0, h: inc ? inc.frameHeight || 0 : 0,
      fps: inc ? +(inc.framesPerSecond || 0).toFixed(1) : 0,
      bitrate: bitrate, dropped: inc ? inc.framesDropped || 0 : 0, lost: inc ? inc.packetsLost || 0 : 0,
      jitter: inc && inc.jitter != null ? +(inc.jitter * 1000).toFixed(0) : 0,
      freeze: inc ? inc.freezeCount || 0 : 0, decoder: inc ? inc.decoderImplementation || '' : '',
      rtt: pair && pair.currentRoundTripTime != null ? +(pair.currentRoundTripTime * 1000).toFixed(0) : 0,
      local: lc ? lc.candidateType : '', remote: rc ? rc.candidateType : '',
    };
    v.lastStats = row;
    data.in.push(row);
  }
  C.voice.screenStatsData = data;
  return data;
}

function renderScreenStats(data) {
  const box = document.getElementById('screen_stats');
  if (!box || !data) return;
  const show = C.voice.screenStatsOn || screenDebug();
  box.hidden = !show;
  if (!show) return;
  const p = SCREEN_PRESETS[data.preset] || SCREEN_PRESETS.smooth60;
  const lines = [p.label + ' · ' + data.viewers + ' viewer' + (data.viewers === 1 ? '' : 's') + ' · displayed ' + (data.displayedFps || 0) + ' fps'];
  data.out.forEach(x => {
    lines.push('→ ' + x.state + ' ' + x.w + 'x' + x.h + ' ' + x.fps + 'fps ' + (x.bitrate / 1e6).toFixed(2) + 'M/' + (x.target / 1e6).toFixed(1) + 'M ' + x.reason + ' ' + x.encoder + (x.power ? ' hw' : '') + ' enc ' + x.encodeMs + 'ms nack ' + x.nack + ' pli ' + x.pli);
    lines.push('   src ' + x.srcW + 'x' + x.srcH + ' ' + x.srcFps + 'fps · net ' + x.rtt + 'ms avail ' + (x.availOut / 1e6).toFixed(1) + 'M ' + x.local + '/' + x.remote);
  });
  data.in.forEach(x => {
    lines.push('← ' + x.state + ' ' + x.w + 'x' + x.h + ' ' + x.fps + 'fps ' + (x.bitrate / 1e6).toFixed(2) + 'M drop ' + x.dropped + ' lost ' + x.lost + ' jit ' + x.jitter + 'ms freeze ' + x.freeze + ' ' + x.decoder);
    lines.push('   net ' + x.rtt + 'ms ' + x.local + '/' + x.remote);
  });
  box.textContent = lines.join('\n');
}

function screenAutoQuality(data) {
  if (!C.voice.screen || !C.voice.screenAuto || !data.out.some(x => x.answered)) {
    C.voice.screenBadSince = 0; C.voice.screenCleanSince = 0;
    return;
  }
  const bad = data.out.some(x => x.reason === 'cpu' || x.reason === 'bandwidth');
  const idx = SCREEN_ORDER.indexOf(C.voice.screenPreset);
  const now = Date.now();
  // WebRTC always starts with a low bitrate and reports bandwidth during the
  // ramp. Give it 12 s before treating that as a real limit, or every share
  // instantly drops to 30 fps.
  if (now - (C.voice.screenStartAt || 0) < 12000) { C.voice.screenBadSince = 0; return; }
  if (bad) {
    C.voice.screenCleanSince = 0;
    if (!C.voice.screenBadSince) C.voice.screenBadSince = now;
    else if (now - C.voice.screenBadSince >= 5000 && idx >= 0 && idx < SCREEN_ORDER.length - 1) {
      const reason = data.out.some(x => x.reason === 'cpu') ? 'cpu' : 'bandwidth';
      C.voice.screenBadSince = 0;
      screenApplyPreset(SCREEN_ORDER[idx + 1], true, reason);
    }
  } else {
    C.voice.screenBadSince = 0;
    if (!C.voice.screenCleanSince) C.voice.screenCleanSince = now;
    else if (now - C.voice.screenCleanSince >= 30000 && idx > 0) {
      const target = screenPresetForViewers(data.viewers, C.voice.screenWant || 'smooth60');
      if (SCREEN_ORDER.indexOf(target) < idx) screenApplyPreset(target, true, 'clean');
      C.voice.screenCleanSince = now;
    }
  }
}

function screenLowerHint(data) {
  const v = data.in[0];
  if (!v) return;
  if (C.voice.screenDropPrev == null) { C.voice.screenDropPrev = v.dropped; return; }
  const grew = v.dropped - C.voice.screenDropPrev;
  C.voice.screenDropPrev = v.dropped;
  if (grew > 30 && Date.now() - (C.voice.screenLowerAt || 0) > 30000) {
    C.voice.screenLowerAt = Date.now();
    toast('Screen is dropping frames', 'Your device is struggling. Asking for a lower preset.');
    const uid = Object.keys(C.voice.screenIn)[0];
    if (uid) api('voice/signal', { ch: C.voice.ch, to: +uid, kind: 'lower', payload: { screen: true } }).catch(() => { });
  }
}

async function screenStatsTick() {
  if (!C.voice.joined) return;
  const data = await screenGather();
  const now = Date.now();
  if (C.voice.screenStatsOn || screenDebug()) renderScreenStats(data);
  if (now - (C.voice.screenLogAt || 0) >= 5000) {
    C.voice.screenLogAt = now;
    try { console.log('[screenstats] ' + JSON.stringify(data)); } catch (e) { }
  }
  screenAutoQuality(data);
  if (!C.voice.screen) screenLowerHint(data);
}

function screenStatsMaybe() {
  const active = C.voice.screen || Object.keys(C.voice.screenIn || {}).length > 0;
  if (active && !C.voice.screenStatsTimer) {
    C.voice.screenStatsTimer = setInterval(screenStatsTick, 1000);
    C.voice.screenLogAt = 0;
  } else if (!active && C.voice.screenStatsTimer) {
    clearInterval(C.voice.screenStatsTimer);
    C.voice.screenStatsTimer = 0;
    const box = document.getElementById('screen_stats');
    if (box) { box.hidden = true; box.textContent = ''; }
  }
  if (active) screenCountDisplayed();
}

function voiceStop(notify) {
  const ch = C.voice.ch;
  if (window.Music) Music.teardown();
  clearInterval(C.voice.hb); C.voice.hb = null;
  cancelAnimationFrame(C.voice.raf); C.voice.raf = 0;
  try { if (C.voice.ac) C.voice.ac.close(); } catch (e) { }
  C.voice.ac = null;
  screenTeardown(false);
  if (C.voice.local) { try { C.voice.local.getTracks().forEach(t => t.stop()); } catch (e) { } C.voice.local = null; }
  Object.keys(C.voice.peers || {}).forEach(uid => voiceDropPeer(+uid));
  C.voice.peers = {}; C.voice.room = [];
  C.voice.joined = false; C.voice.connecting = false; C.voice.ch = 0;
  C.voice.muted = false; C.voice.deafened = false; C.voice.speaking = false; C.voice.err = '';
  C.voice.ice = null;
  const box = document.getElementById('voice_audio'); if (box) box.replaceChildren();
  if (notify && ch) api('voice/leave', { ch }).catch(() => { });
}

function voiceDropPeer(uid) {
  const p = C.voice.peers[uid];
  if (!p) return;
  try { if (p.pc) p.pc.close(); } catch (e) { }
  if (p.audio) p.audio.remove();
  delete C.voice.peers[uid];
}

function voiceApply() {
  const track = C.voice.local && C.voice.local.getAudioTracks()[0];
  if (track) track.enabled = !C.voice.muted;
  Object.values(C.voice.peers).forEach(p => { if (p.audio) p.audio.muted = C.voice.deafened; });
}

function voicePeer(uid) {
  let p = C.voice.peers[uid];
  if (p && p.pc) return p.pc;
  if (!p) p = C.voice.peers[uid] = { pending: [] };
  const pc = new RTCPeerConnection({
    iceServers: C.voice.ice || [{ urls: 'stun:stun.l.google.com:19302' }],
    iceCandidatePoolSize: 4,
  });
  p.pc = pc;
  if (C.voice.local) C.voice.local.getTracks().forEach(t => pc.addTrack(t, C.voice.local));
  pc.onicecandidate = e => {
    if (!e.candidate) return;
    const c = e.candidate.toJSON ? e.candidate.toJSON() : {
      candidate: e.candidate.candidate, sdpMid: e.candidate.sdpMid, sdpMLineIndex: e.candidate.sdpMLineIndex,
    };
    api('voice/signal', { ch: C.voice.ch, to: uid, kind: 'ice', payload: c }).catch(() => { });
  };
  pc.ontrack = e => {
    if (e.track.kind !== 'audio') return;
    if (!p.audio) {
      p.audio = document.createElement('audio');
      p.audio.autoplay = true; p.audio.playsInline = true; p.audio.dataset.vuid = uid;
      voiceAudioBox().appendChild(p.audio);
    }
    p.stream = e.streams[0];
    p.audio.srcObject = e.streams[0];
    p.audio.muted = C.voice.deafened;
    p.audio.play().catch(() => { });
  };
  pc.onconnectionstatechange = () => {
    if (pc.connectionState === 'failed') { voiceDropPeer(uid); paintVoice(); }
  };
  return pc;
}

async function voiceFlush(uid) {
  const p = C.voice.peers[uid];
  if (!p || !p.pc) return;
  for (const c of p.pending.splice(0)) { try { await p.pc.addIceCandidate(c); } catch (e) { } }
}

Chat.voiceOffer = async function (uid) {
  try {
    const pc = voicePeer(uid);
    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    await api('voice/signal', { ch: C.voice.ch, to: uid, kind: 'offer', payload: { type: offer.type, sdp: offer.sdp } });
  } catch (e) { }
};

async function voiceOnSignal(d) {
  const uid = d.from;
  if (!uid) return;
  const payload = d.payload || {};
  if (payload.screen) { screenOnSignal(uid, d.kind, payload); return; }
  try {
    if (d.kind === 'offer') {
      const pc = voicePeer(uid);
      await pc.setRemoteDescription(payload);
      await voiceFlush(uid);
      const ans = await pc.createAnswer();
      await pc.setLocalDescription(ans);
      await api('voice/signal', { ch: C.voice.ch, to: uid, kind: 'answer', payload: { type: ans.type, sdp: ans.sdp } });
    } else if (d.kind === 'answer') {
      const pc = voicePeer(uid);
      await pc.setRemoteDescription(payload);
      await voiceFlush(uid);
    } else if (d.kind === 'ice') {
      const pc = voicePeer(uid);
      if (pc.remoteDescription && pc.remoteDescription.type) await pc.addIceCandidate(payload);
      else C.voice.peers[uid].pending.push(payload);
    }
  } catch (e) { }
}

Chat.voiceEvent = function (d) {
  if (!C.voice.joined || !d || d.ch !== C.voice.ch) return;
  if (d.type === 'join' && d.user) {
    C.voice.room = C.voice.room.filter(p => p.uid !== d.user.uid).concat(d.user);
    render(); paintScreen();
    if (C.voice.screen) screenSyncViewers();
  } else if (d.type === 'leave') {
    voiceDropPeer(d.uid);
    screenCloseOut(d.uid); screenCloseIn(d.uid);
    C.voice.room = C.voice.room.filter(p => p.uid !== d.uid);
    render(); paintScreen(); screenStatsMaybe();
  } else if (d.type === 'state') {
    const p = C.voice.room.find(x => x.uid === d.uid);
    if (p) { p.muted = d.muted; p.deafened = d.deafened; p.speaking = d.speaking; p.screen = !!d.screen; }
    if (!d.screen) screenCloseIn(d.uid);
    paintVoice(); paintScreen(); screenStatsMaybe();
  } else if (d.type === 'speaking') {
    const p = C.voice.room.find(x => x.uid === d.uid);
    if (p) p.speaking = !!d.on;
    paintVoice();
  } else if (d.type === 'signal') {
    voiceOnSignal(d);
  }
};

Chat.joinVoice = async function (chId) {
  if (C.voice.joined && C.voice.ch === chId) { ACT.vroom(); return; }
  if (C.voice.joined) voiceStop(true);
  C.voice.connecting = true; C.voice.err = ''; C.view = 'chat';
  render();
  try {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) throw new Error('Voice needs a secure page and a microphone');
    const local = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    C.voice.local = local;
    const r = await api('voice/join', { ch: chId });
    C.voice.ch = chId; C.voice.joined = true; C.voice.connecting = false;
    C.voice.room = r.participants || []; C.voice.max = r.max || 8;
    C.voice.ice = r.ice || null; C.voice.screenMax = r.screen_max || 3;
    if (window.Music) Music.attach(chId, r.music);
    C.ch = chId; C.thread = { kind: 'voice', id: chId }; C.msgs = []; C.more = false;
    C.sel = C.reply = C.edit = null; C.draft = ''; C.files = []; C.prev = null; C.results = null;
    voiceApply();
    (r.participants || []).filter(p => p.uid !== (S.user || {}).id).forEach(p => Chat.voiceOffer(p.uid));
    Chat.voiceMeter();
    C.voice.hb = setInterval(() => { if (C.voice.joined) api('voice/ping', { ch: C.voice.ch }).catch(() => { }); }, 15000);
    render(); paintScreen();
  } catch (e) {
    C.voice.connecting = false;
    if (C.voice.local) { try { C.voice.local.getTracks().forEach(t => t.stop()); } catch (x) { } C.voice.local = null; }
    C.voice.err = e && e.message ? e.message : 'Could not join voice';
    toast('Voice', e && e.name === 'NotAllowedError' ? 'Microphone permission was denied' : C.voice.err);
    render();
  }
};

Chat.leaveVoice = function () {
  const wasVoice = C.thread && C.thread.kind === 'voice';
  voiceStop(true);
  if (wasVoice) { C.thread = null; C.ch = 0; C.msgs = []; C.more = false; }
  render();
};

Chat.toggleMute = function () {
  if (!C.voice.joined) return;
  C.voice.muted = !C.voice.muted;
  if (!C.voice.muted) C.voice.deafened = false;
  if (C.voice.muted) C.voice.speaking = false;
  voiceApply();
  api('voice/state', { ch: C.voice.ch, muted: C.voice.muted, deafened: C.voice.deafened }).catch(() => { });
  paintVoice();
};

Chat.toggleDeafen = function () {
  if (!C.voice.joined) return;
  C.voice.deafened = !C.voice.deafened;
  if (C.voice.deafened) C.voice.muted = true;
  voiceApply();
  api('voice/state', { ch: C.voice.ch, muted: C.voice.muted, deafened: C.voice.deafened }).catch(() => { });
  if (window.Music) Music.setDeafened(C.voice.deafened);
  paintVoice();
};

function paintScreen() {
  const box = $id('voice_stage'), vid = $id('voice_screen');
  if (!box || !vid) { screenStatsMaybe(); return; }
  const me = (S.user || {}).id;
  const p = (C.voice.room || []).find(x => x.screen) ||
    (C.voice.screen ? { uid: me, name: 'You', screen: true } : null);
  if (!p) {
    box.classList.remove('on');
    vid.srcObject = null;
    C.voice.screenRvcToken = (C.voice.screenRvcToken || 0) + 1;
    C.voice.screenDisplayFps = 0;
    screenStatsMaybe();
    return;
  }
  const self = p.uid === me;
  const stream = self ? C.voice.screenStream : ((C.voice.screenIn[p.uid] || {}).stream || null);
  box.classList.add('on');
  box.classList.toggle('wait', !stream);
  const label = $id('voice_screen_label');
  if (label) label.textContent = self ? 'You are sharing your screen' : ((p.name || 'Member') + ' is sharing');
  const meta = $id('voice_screen_meta');
  if (meta) {
    if (self) {
      const preset = SCREEN_PRESETS[C.voice.screenPreset] || {};
      const n = screenViewers(), cap = C.voice.screenMax || 3;
      meta.textContent = (preset.label || '') + ' · ' + n + '/' + cap + ' viewer' + (cap === 1 ? '' : 's');
    } else {
      const v = C.voice.screenIn[p.uid];
      const preset = v && v.preset ? SCREEN_PRESETS[v.preset] : null;
      meta.textContent = stream ? ((preset ? preset.label + ' · ' : '') + (C.voice.screenDisplayFps || 0) + ' fps') : 'connecting…';
    }
  }
  const wait = box.querySelector('.vr-stage-wait');
  if (wait && !self) wait.textContent = 'Connecting to ' + (p.name || 'their') + '’s screen…';
  if (stream && vid.srcObject !== stream) {
    vid.srcObject = stream;
    C.voice.screenDisplayFps = 0;
    vid.play().catch(() => { });
    screenCountDisplayed();
  } else if (!stream) {
    vid.srcObject = null;
  }
  renderScreenStats(C.voice.screenStatsData);
  screenStatsMaybe();
}

Chat.stopScreen = function () {
  if (!C.voice.screen && !Object.keys(C.voice.screenOut || {}).length) return;
  const was = C.voice.screen;
  screenTeardown(was);
  paintVoice(); paintScreen();
};

Chat.startScreen = async function (key) {
  if (!C.voice.joined || C.voice.screen) return;
  const want = SCREEN_PRESETS[key] ? key : 'smooth60';
  C.voice.screenWant = want;
  let downgraded = false;
  let stream = null;
  try {
    stream = await screenCapture(want);
    const track = stream.getVideoTracks()[0];
    if (!track) throw new Error('No screen was selected');
    C.voice.screenStream = stream;
    C.voice.screenTrack = track;
    track.onended = () => Chat.stopScreen();
    const nViewers = Math.min(
      (C.voice.room || []).filter(x => x.uid !== (S.user || {}).id).length,
      Math.max(1, C.voice.screenMax || 3),
    );
    C.voice.screenPreset = screenPresetForViewers(nViewers, want);
    downgraded = C.voice.screenPreset !== want;
    await screenApplyCapture(C.voice.screenPreset);
    try { console.log('[screen] capture settings', track.getSettings()); } catch (e) { }
    await api('voice/state', { ch: C.voice.ch, muted: C.voice.muted, deafened: C.voice.deafened, screen: true });
    C.voice.screen = true;
    C.voice.screenAuto = screenSynthOpt('auto') !== '0';
    C.voice.screenStartAt = Date.now();
    C.voice.screenBadSince = 0; C.voice.screenCleanSince = 0; C.voice.screenLogAt = 0;
    const me = (C.voice.room || []).find(x => x.uid === (S.user || {}).id);
    if (me) me.screen = true;
    paintVoice(); paintScreen();
    screenStatsMaybe();
    screenSyncViewers();
  } catch (e) {
    if (stream) stream.getTracks().forEach(t => { try { t.stop(); } catch (x) { } });
    if (C.voice.synthStop) { try { C.voice.synthStop(); } catch (x) { } C.voice.synthStop = null; }
    C.voice.screen = false; C.voice.screenTrack = null; C.voice.screenStream = null;
    if (!e || !e.api) {
      const msg = e && e.name === 'NotAllowedError'
        ? 'Screen sharing was cancelled or blocked by the browser.'
        : (e && e.message) || 'Could not share screen';
      toast('Screen share', msg);
    }
    paintVoice(); paintScreen();
    return;
  }
  if (downgraded) toast('Screen quality', SCREEN_PRESETS[C.voice.screenPreset].label + ' for ' + nViewersText());
}

function nViewersText() {
  const n = Math.min((C.voice.room || []).filter(x => x.uid !== (S.user || {}).id).length, Math.max(1, C.voice.screenMax || 3));
  return n + ' viewer' + (n === 1 ? '' : 's');
}

Chat.pickScreen = function () {
  const cur = C.voice.screenWant || 'smooth60';
  const opt = key => {
    const p = SCREEN_PRESETS[key];
    return `<button class="sc-opt ${key === cur ? 'on' : ''}" data-cact="vstart" data-p="${key}">
      <span class="sc-rad">${key === cur ? '●' : '○'}</span>
      <span class="sc-tx"><b>${p.name}</b><em>${p.note}</em></span></button>`;
  };
  modal(`<div class="mg sc-pick"><div class="row between mg-top"><div><div class="xs mut up">Screen share</div><h2>Pick a quality</h2></div>
    <button class="btn-s ico" data-mact="close" aria-label="Close">${ic('x', 14)}</button></div>
    ${SCREEN_ORDER.map(opt).join('')}
    <p class="xs mut">1080p60 needs about 8 Mbps upload per viewer. Every viewer is a separate encoder, so 1–2 viewers is the honest limit; beyond that it steps down automatically.</p></div>`, true);
};

Chat.toggleScreen = function () {
  if (!C.voice.joined) return;
  if (C.voice.screen) { Chat.stopScreen(); return; }
  Chat.pickScreen();
};

Chat.toggleScreenStats = function () {
  C.voice.screenStatsOn = !(C.voice.screenStatsOn || screenDebug());
  try { localStorage.setItem('streamDebug', C.voice.screenStatsOn ? '1' : '0'); } catch (e) { }
  paintScreen();
};

Chat.screenSnapshot = function () {
  return {
    sharing: !!C.voice.screen, preset: C.voice.screenPreset, want: C.voice.screenWant,
    viewers: screenViewers(), max: C.voice.screenMax || 3, synthetic: screenSynthetic(),
    stats: C.voice.screenStatsData || null,
    out: Object.keys(C.voice.screenOut || {}).map(uid => {
      const s = C.voice.screenOut[uid];
      return { uid: +uid, answered: !!s.answered, state: s.pc && s.pc.connectionState, last: s.lastStats || null };
    }),
    in: Object.keys(C.voice.screenIn || {}).map(uid => {
      const v = C.voice.screenIn[uid];
      return { uid: +uid, state: v.pc && v.pc.connectionState, preset: v.preset || '', stream: !!v.stream, last: v.lastStats || null };
    }),
  };
};

Chat.voiceMeter = function () {
  cancelAnimationFrame(C.voice.raf);
  if (!C.voice.local) return;
  try {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return;
    const ac = new AC(); C.voice.ac = ac;
    const src = ac.createMediaStreamSource(C.voice.local);
    const an = ac.createAnalyser(); an.fftSize = 512; src.connect(an);
    const buf = new Uint8Array(an.fftSize);
    const tick = () => {
      if (!C.voice.joined || !C.voice.local) return;
      an.getByteTimeDomainData(buf);
      let sum = 0;
      for (let i = 0; i < buf.length; i++) { const x = (buf[i] - 128) / 128; sum += x * x; }
      const on = Math.sqrt(sum / buf.length) > 0.02 && !C.voice.muted;
      if (on !== C.voice.speaking && Date.now() - C.voice.lastSpeak > 300) {
        C.voice.speaking = on; C.voice.lastSpeak = Date.now();
        api('voice/speaking', { ch: C.voice.ch, on }).catch(() => { });
        const me = C.voice.room.find(p => p.uid === (S.user || {}).id);
        if (me) me.speaking = on;
        paintVoice();
      }
      C.voice.raf = requestAnimationFrame(tick);
    };
    tick();
  } catch (e) { }
};

function vTile(p) {
  const you = p.uid === (S.user || {}).id;
  return `<div class="vt ${p.speaking ? 'sp' : ''} ${p.muted ? 'mut' : ''}" data-vuid="${p.uid}">
    ${avatar(p.emoji, p.color, 'lg', null, p)}
    <b class="ell">${esc(p.name || 'Member')}${you ? ' <span class="you">you</span>' : ''}</b>
    <span class="vt-i">${p.muted ? ic('micOff', 12) : ''}${p.deafened ? ic('headphones', 12) : ''}${p.speaking ? '<span class="live-t">talking</span>' : ''}</span></div>`;
}

function voiceDockHTML() {
  if (C.voice.connecting) return `<div class="voice-dock" id="voice_dock"><span class="dot y"></span><b>Connecting to voice…</b></div>`;
  if (!C.voice.joined) return '';
  const { c } = voiceChannelOf(C.voice.ch);
  return `<div class="voice-dock" id="voice_dock"><span class="dot g"></span>
    <div class="grow min0"><b class="ell">${ic('volume', 14)} ${esc(c ? c.name : 'Voice')}</b><span class="xs mut"><span data-vcount>${(C.voice.room || []).length}</span> connected</span></div>
    <button class="btn-s" id="voice_mute_btn" data-cact="vmute">${C.voice.muted ? `${ic('micOff', 14)} Muted` : `${ic('mic', 14)} Mic`}</button>
    <button class="btn-s" id="voice_deaf_btn" data-cact="vdeaf">${C.voice.deafened ? `${ic('volumeOff', 14)} Deafened` : `${ic('headphones', 14)} Sound`}</button>
    <button class="btn-s" data-screen-btn data-cact="vscreen">${C.voice.screen ? `${ic('monitor', 14)} Stop` : `${ic('monitor', 14)} Screen`}</button>
    <button class="btn-s" data-cact="vroom">Open</button>
    <button class="btn-d btn-s" data-cact="vleave">Leave</button></div>`;
}

function voiceMiniHTML() {
  if (!C.voice.joined && !C.voice.connecting) return '';
  const { c } = voiceChannelOf(C.voice.ch);
  return `<button class="voice-mini" data-cact="vroom" id="voice_mini"><span class="dot ${C.voice.connecting ? 'y' : 'g'}"></span>
    <span class="ell grow">${C.voice.connecting ? 'Connecting…' : `${ic('volume', 14)} ${esc(c ? c.name : 'Voice')}`}</span>
    ${C.voice.connecting ? '' : `<span class="xs mut" data-vcount>${(C.voice.room || []).length}</span>`}</button>`;
}

function voiceRoomHTML() {
  const { c } = voiceChannelOf(C.voice.ch);
  const room = C.voice.room || [];
  const cap = C.voice.screenMax || 3;
  return `<div class="voice-room" id="voice_room">
    <div class="vr-top"><div><div class="xs mut up">Voice channel</div><h2 class="ell">${ic('volume', 17)} ${esc(c ? c.name : 'Voice')}</h2></div>
      <div class="xs mut"><span data-vcount>${room.length}</span>/${C.voice.max || 8} connected</div></div>
    ${window.Music ? Music.panelHTML() : ''}
    <div class="vr-stage" id="voice_stage"><div class="vr-stage-h"><span class="dot g"></span><b id="voice_screen_label">Screen share</b><span class="xs mut" id="voice_screen_meta"></span>
      <button class="btn-s ico sc-stats-btn" data-cact="vstats" aria-label="Stream stats" title="Stream stats">${ic('stats', 14)}</button>
      <button class="btn-s" data-screen-btn data-cact="vscreen">${C.voice.screen ? `${ic('monitor', 14)} Stop` : `${ic('monitor', 14)} Share`}</button></div>
      <video id="voice_screen" autoplay playsinline muted></video><div class="vr-stage-wait">Waiting for the screen…</div>
      <div class="sc-stats" id="screen_stats" hidden></div></div>
    <div class="vr-grid">${window.Music ? Music.tileHTML() : ''}${room.length ? room.map(vTile).join('') : (window.Music && Music.nowTrack() ? '' : '<div class="soc-empty">No one is here yet.</div>')}</div>
    <div class="vr-actions">
      <button class="btn-s" id="voice_mute_btn" data-cact="vmute">${C.voice.muted ? `${ic('micOff', 14)} Muted` : `${ic('mic', 14)} Mic`}</button>
      <button class="btn-s" id="voice_deaf_btn" data-cact="vdeaf">${C.voice.deafened ? `${ic('volumeOff', 14)} Deafened` : `${ic('headphones', 14)} Sound`}</button>
      <button class="btn-s" data-screen-btn data-cact="vscreen">${C.voice.screen ? `${ic('monitor', 14)} Stop sharing` : `${ic('monitor', 14)} Share screen`}</button>
      <button class="btn-d btn-s" data-cact="vleave">Leave voice</button>
    </div>
    <p class="xs mut c mt8">Peer-to-peer audio + screen · up to ${cap} screen viewer${cap === 1 ? '' : 's'} · headphones recommended.</p></div>`;
}

function paintVoice() {
  const by = {};
  (C.voice.room || []).forEach(p => { by[p.uid] = p; });
  document.querySelectorAll('.vt[data-vuid]').forEach(el => {
    const p = by[+el.dataset.vuid]; if (!p) return;
    el.classList.toggle('sp', !!p.speaking);
    el.classList.toggle('mut', !!p.muted);
    const i = el.querySelector('.vt-i');
    if (i) i.innerHTML = (p.muted ? ic('micOff', 12) : '') + (p.deafened ? ic('headphones', 12) : '') + (p.speaking ? '<span class="live-t">talking</span>' : '');
  });
  const count = (C.voice.room || []).length;
  document.querySelectorAll('[data-vcount]').forEach(el => { el.textContent = count; });
  const m = document.getElementById('voice_mute_btn');
  if (m) m.innerHTML = C.voice.muted ? `${ic('micOff', 14)} Muted` : `${ic('mic', 14)} Mic`;
  const d = document.getElementById('voice_deaf_btn');
  if (d) d.innerHTML = C.voice.deafened ? `${ic('volumeOff', 14)} Deafened` : `${ic('headphones', 14)} Sound`;
  document.querySelectorAll('[data-screen-btn]').forEach(b => { b.innerHTML = C.voice.screen ? `${ic('monitor', 14)} Stop sharing` : `${ic('monitor', 14)} Share screen`; });
  if (window.Music) { Music.setDeafened(C.voice.deafened); Music.paint(); }
  paintScreen();
}

/* ---------- view ---------- */
Chat.view = function () {
  if (C.error) return `<div class="card"><h2>Chat hit a snag</h2><p class="mut sm">${esc(C.error)}</p><button class="btn-s" data-cact="reload">Retry</button></div>`;
  if (!C.loaded) return '<div class="soc soc-load"><div class="sk"><i style="height:60px"></i><i style="height:220px"></i></div></div>';
  if (!C.servers.length) return `<div class="card"><h2>No server yet</h2><p class="mut sm">Your crew gets a server automatically. Join a crew from the Crew tab and it appears here.</p></div>`;

  const srv = C.servers.find(s => s.id === C.sid) || C.servers[0];
  const isDM = C.thread && C.thread.kind === 'dm';
  const isVoice = C.thread && C.thread.kind === 'voice';
  if (isVoice) setTimeout(paintScreen, 0);
  const dm = isDM ? (C.dms.find(d => d.id === C.thread.id) || C.people[C.thread.id] || null) : null;
  const ch = !isDM && srv ? srv.channels.find(c => c.id === C.ch) : null;
  const open = isDM || isVoice || !!ch;

  const rail = `<nav class="srail" aria-label="Servers">
    ${C.servers.map(s => `<button class="srv ${s.id === C.sid && !isDM ? 'on' : ''}" data-cact="srv" data-id="${s.id}" title="${esc(s.name)}" aria-label="${esc(s.name)}">${s.icon ? esc(s.icon) : esc(initials(s.name))}${s.unread ? `<i class="nb">${s.unread > 9 ? '9+' : s.unread}</i>` : ''}</button>`).join('')}
    <button class="srv add" data-cact="addserver" title="Add a server" aria-label="Add a server">${ic('plus', 18)}</button>
  </nav>`;

  const chans = srv ? srv.channels : [];
  const side = `<aside class="schan">
    <div class="schan-h row between"><div class="grow min0"><b class="ell">${esc(srv ? srv.name : 'Server')}</b><span class="xs mut">${srv ? srv.members : 0} members</span></div></div>
    <div class="schan-scroll">
      <div class="sgrp row between"><span>Text channels</span>${srv && (srv.perms & 256) ? `<button class="btn-s mg-add" data-cact="newchannel" aria-label="New channel">${ic('plus', 14)}</button>` : ''}</div>
      ${chans.filter(c => c.kind === 'text').map(c => `<button class="sch ${!isDM && c.id === C.ch ? 'on' : ''}" data-cact="ch" data-id="${c.id}">
        <span class="hash">#</span><span class="ell grow">${esc(c.name)}</span>${c.unread ? `<i class="ub">${c.unread > 99 ? '99+' : c.unread}</i>` : ''}</button>`).join('') || '<div class="soc-none">No channels yet.</div>'}
      ${chans.some(c => c.kind === 'voice') ? `<div class="sgrp">Voice</div>${chans.filter(c => c.kind === 'voice').map(c => `<button class="sch ${C.voice.ch === c.id ? 'on' : ''}" data-cact="voice" data-id="${c.id}"><span class="hash">${ic('volume', 14)}</span><span class="ell grow">${esc(c.name)}</span>${C.voice.ch === c.id ? `<i class="ub">${(C.voice.room || []).length}</i>` : ''}</button>`).join('')}` : ''}
      <div class="sgrp row between"><span>Direct messages</span><button class="btn-s mg-add" data-cact="friends" aria-label="Friends">${ic('plus', 14)}</button></div>
      ${C.dms.length ? C.dms.map(d => `<button class="sch ${isDM && C.thread.id === d.id ? 'on' : ''}" data-cact="dm" data-id="${d.id}">
        ${avatar(d.emoji, d.color, 'xs', null, d)}<span class="ell grow">${esc(d.display)}</span>${d.unread ? `<i class="ub">${d.unread}</i>` : ''}</button>`).join('') : '<div class="soc-none">No one else in the crew yet.</div>'}
    </div>
    ${voiceMiniHTML()}
    <div class="schan-foot"><button class="schan-me" data-act="profile" data-id="${C.me ? C.me.id : ''}" title="Your profile">
      ${C.me ? avatar(C.me.emoji, C.me.color, 'xs', null, C.me) : ''}<span class="xs mut ell">${C.me ? '@' + esc(C.me.display) : ''}</span></button><span class="dot g" title="live"></span></div>
  </aside>`;

  const head = isVoice
    ? `<div class="soc-head"><button class="btn-s ico soc-back" data-cact="back" aria-label="Back">${ic('left', 16)}</button><div class="grow"><b>${ic('volume', 15)} ${esc(ch ? ch.name : 'Voice')}</b><span class="xs mut"><span data-vcount>${(C.voice.room || []).length}</span> connected</span></div><button class="btn-d btn-s" data-cact="vleave">Leave</button></div>`
    : isDM
    ? `<div class="soc-head"><button class="btn-s ico soc-back" data-cact="back" aria-label="Back">${ic('left', 16)}</button>${dm ? avatar(dm.emoji, dm.color, 'sm', null, dm) : ''}<div class="grow"><b>${esc(dm ? dm.display : 'Direct message')}</b><span class="xs mut ell">${dm && dm.status && (dm.status.text || dm.status.emoji) ? esc([dm.status.emoji, dm.status.text].filter(Boolean).join(' ')) : 'private · only you two'}</span></div>
       <button class="btn-s ico" data-cact="appearance" aria-label="Chat appearance" title="Chat appearance">${PAL_ICON}</button></div>`
    : `<div class="soc-head"><button class="btn-s ico soc-back" data-cact="back" aria-label="Back">${ic('left', 16)}</button><div class="grow"><b># ${esc(ch ? ch.name : 'channel')}</b><span class="xs mut ell">${esc(ch ? ch.topic : '')}</span></div>
       <button class="btn-s ico" data-cact="search" aria-label="Search">${ic('search', 16)}</button>
       <button class="btn-s ico" data-cact="members" aria-label="Members">${ic('users', 16)}</button>
       <button class="btn-s ico" data-cact="appearance" aria-label="Chat appearance" title="Chat appearance">${PAL_ICON}</button>
       ${srv && (srv.perms & 256) ? `<button class="btn-s ico" data-cact="chsettings" aria-label="Channel settings">${ic('settings', 16)}</button>` : ''}
       <button class="btn-s ico" data-cact="servermenu" aria-label="Server menu">${ic('more', 16)}</button></div>`;

  const body = `<main class="smain">
    <div class="sm-wall" aria-hidden="true"></div>
    ${C.voice.joined && !isVoice ? voiceDockHTML() : ''}
    ${open ? head : '<div class="soc-empty big">Pick a channel to start.</div>'}
    ${isVoice ? voiceRoomHTML() : open ? `<div class="msgs soc-msgs" id="soc_msgs"></div>
      <div class="soc-meta"><span id="soc_typing" class="xs mut"></span><span id="soc_seen" class="xs mut"></span></div>
      ${C.results !== null ? `<div class="soc-search" id="soc_search">${searchHTML()}</div>` : ''}
      <div id="soc_ctx"></div>
      <div id="soc_prev" class="soc-prev"></div>
      <div class="soc-compose">
        <button class="btn-s ico soc-att" data-cact="attach" aria-label="Attach a file" title="Attach a file">${ic('attach', 17)}</button>
        <button class="btn-s ico soc-att" data-cact="stick" aria-label="Emoji, stickers and GIFs" title="Emoji, stickers and GIFs">${ic('smile', 17)}</button>
        <div class="soc-ment" id="soc_ment"></div>
        <div class="soc-inwrap"><div id="soc_files" class="up-strip"></div>
          <textarea id="soc_in" rows="1" maxlength="1000" placeholder="${isDM ? 'Message ' + esc(dm ? dm.display : '') : 'Message #' + esc(ch ? ch.name : '')}"></textarea></div>
        <button class="btn-p" data-cact="send">Send</button></div>
      <input type="file" id="soc_file" accept="image/png,image/jpeg,image/gif,image/webp,application/pdf,application/zip,text/plain,.txt,.md,.csv,.json" multiple hidden>` : ''}
  </main>`;

  return `<div class="soc" data-view="${open ? 'chat' : 'list'}">${rail}${side}${body}</div>`;
};

function searchHTML() {
  if (C.results === null) return '';
  if (C.results === false) return '<div class="soc-none">Type at least 2 characters.</div>';
  if (!C.results.length) return `<div class="soc-none">No matches for “${esc(C.q)}”.</div>`;
  return `<div class="soc-search-h"><b>${C.results.length} result${C.results.length > 1 ? 's' : ''}</b><button class="btn-s" data-cact="closesearch">Close</button></div>
    ${C.results.map(r => `<div class="sres" data-cact="jump" data-id="${r.id}"><b>${esc(who(r.uid))}</b><span class="xs mut">${esc(chatDay(r.ts))}</span><div class="sm ell">${esc(r.text)}</div></div>`).join('')}`;
}

Chat.afterRender = function () {
  if (!C.loaded || !S.user) return;
  Chat.connect();
  const el = $id('soc_msgs');
  if (el && C.thread && C.thread.kind !== 'voice') paint();
  paintFiles();
  paintVoice();
  const ta = $id('soc_in');
  if (ta && C.draft) { ta.value = C.draft; ta.style.height = 'auto'; ta.style.height = Math.min(ta.scrollHeight, 140) + 'px'; }
  if (ta && (C.taFocus || (!matchMedia('(pointer:coarse)').matches && !C.sel))) { ta.focus(); if (C.draft) ta.selectionStart = ta.selectionEnd = ta.value.length; }
  if (el) el.onscroll = () => {
    if (el.scrollTop < 30 && C.more && !C.loading) Chat.older();
    const t = $id('soc_typing'); if (t) t.classList.toggle('hide', el.scrollHeight - el.scrollTop - el.clientHeight < 200);
  };
  paintMeta();
};

/* ---------- actions ---------- */
Chat.older = async function () {
  if (!C.msgs.length || C.loading) return;
  const el = $id('soc_msgs'); if (!el) return;
  const h0 = el.scrollHeight;
  C.loading = true;
  try {
    if (C.thread.kind === 'ch') {
      const r = await api(`ch/messages?ch=${C.ch}&before=${C.msgs[0].id}`);
      C.msgs = (r.messages || []).map(norm).concat(C.msgs); C.more = !!r.more;
    } else {
      const r = await api(`chat/messages?thread=${encodeURIComponent('dm:' + C.thread.id)}&before=${C.msgs[0].id}`);
      C.msgs = (r.messages || []).map(norm).concat(C.msgs); C.more = !!r.more;
    }
    C.loading = false; paint();
    const el2 = $id('soc_msgs'); if (el2) el2.scrollTop = el2.scrollHeight - h0;
  } catch (e) { C.loading = false; }
};

Chat.send = async function () {
  const ta = $id('soc_in'); if (!ta || !C.thread) return;
  const text = ta.value.trim();
  const files = C.files.map(f => f.id);
  if (!text && !files.length) return;
  const editing = C.edit, reply = C.reply;
  if (editing && !text) return;
  if (!editing && text && window.Music && Music.slash(text)) {
    ta.value = ''; C.draft = ''; ta.style.height = 'auto';
    C.edit = null; C.reply = null; paintCtx();
    C.files = []; C.prev = null; paintFiles();
    return;
  }
  ta.value = ''; C.draft = ''; ta.style.height = 'auto';
  C.edit = null; C.reply = null; paintCtx();
  try {
    if (editing) {
      if (C.thread.kind === 'ch') {
        const r = await api('ch/edit', { ch: C.ch, id: editing, text });
        touchMsg(editing, m => { m.text = r.text; m.edited = true; });
      } else {
        const r = await api('chat/edit', { id: editing, text });
        touchMsg(editing, m => { m.text = r.text; m.edited = true; });
      }
      return;
    }
    if (C.thread.kind === 'ch') {
      const r = await api('ch/send', { ch: C.ch, text, reply_to: reply ? reply.id : undefined, files: files.length ? files : undefined });
      appendMsg(r.message);
      Chat.read(r.message.id);
    } else {
      const r = await api('chat/send', { thread: 'dm:' + C.thread.id, text, reply_to: reply ? reply.id : undefined, files: files.length ? files : undefined });
      appendMsg(r.message);
    }
    C.files = []; C.prev = null; paintFiles();
  } catch (e) { ta.value = text; C.draft = text; }
};

/* ---------- uploads, stickers, link previews ---------- */
function paintFiles() {
  const box = $id('soc_files'); if (!box) return;
  box.innerHTML = C.files.map(f => `<span class="up" title="${esc(f.name)}">${String(f.mime).startsWith('image/') ? `<img src="/api/file?id=${f.id}" alt="" loading="lazy" decoding="async">` : `<span class="up-i">${fileIcon(f.mime)}</span>`}<span class="up-n ell">${esc(f.name)}</span><button class="up-x" data-cact="unfile" data-id="${f.id}" aria-label="Remove">${ic('x', 12)}</button></span>`).join('');
  const pv = $id('soc_prev');
  if (!pv) return;
  pv.innerHTML = C.prev ? `<div class="pv">${lpHTML(C.prev)}<button class="up-x pv-x" data-cact="unprev" aria-label="Remove preview">${ic('x', 12)}</button></div>` : '';
}

Chat.pickAttach = function () { $id('soc_file')?.click(); };

Chat.addFiles = async function (list) {
  if (!C.thread) return;
  const room = Math.max(0, 4 - C.files.length);
  const files = [...list].slice(0, room);
  if (list.length > room) toast('Up to 4 files', 'Only the first ' + room + ' were added.');
  for (const f of files) {
    const q = C.thread.kind === 'ch' ? 'ch=' + C.ch : 'thread=' + encodeURIComponent('dm:' + C.thread.id);
    try {
      const send = await shrinkImage(f, 2560);
      if (send.size > 8 * 1024 * 1024) { toast('Too big', f.name + ' is over 8 MB'); continue; }
      const res = await fetch('/api/upload?' + q, {
        method: 'POST', body: send, credentials: 'same-origin',
        headers: { 'X-File-Name': encodeURIComponent(send.name || f.name), 'X-File-Type': send.type || 'application/octet-stream' },
      });
      const r = await res.json().catch(() => ({}));
      if (!res.ok) { toast('Upload failed', r.error || ('HTTP ' + res.status)); continue; }
      C.files.push(r.file); paintFiles();
    } catch (e) { toast('Upload failed', 'Check your connection'); }
  }
};

Chat.loadAssets = async function (sid) {
  sid = +sid || 0;
  if (!sid) { C.assets = []; C.assetSid = 0; C.assetsLoaded = false; return []; }
  if (C.assetSid === sid && C.assetsLoaded) return C.assets;
  try {
    const r = await api('ch/assets?server=' + sid);
    if (C.sid === sid) { C.assets = r.assets || []; C.assetSid = sid; C.assetsLoaded = true; }
    return r.assets || [];
  } catch (e) { return C.assets || []; }
};

function putAsset(a) {
  if (!a) return;
  const i = (C.assets || []).findIndex(x => x.id === a.id);
  if (i >= 0) C.assets[i] = a; else C.assets.push(a);
  C.assetsLoaded = true;
  refreshExpr();
  if (C.thread && C.thread.kind === 'ch') paint();
}

function refreshExpr() {
  const body = $id('expr_body'); if (body) body.innerHTML = Chat.assetBody();
}

Chat.assetTab = function (kind) {
  if (!['emoji', 'sticker', 'gif'].includes(kind)) return;
  C.assetTab = kind;
  document.querySelectorAll('.expr-tab').forEach(b => {
    const on = b.dataset.kind === kind;
    b.classList.toggle('on', on);
    b.setAttribute('aria-selected', on ? 'true' : 'false');
  });
  refreshExpr();
};

function exprTile(a, action, data, canDel) {
  const label = a.kind === 'emoji' ? `:${esc(a.slug)}:` : esc(a.name);
  return `<div class="expr-item"><button class="expr-main" data-cact="${action}" ${data} title="${esc(a.name)}">
    <img src="/api/file?id=${a.upload}" alt="${esc(a.name)}" loading="lazy" decoding="async"><span>${label}</span></button>
    ${canDel ? `<button class="expr-x" data-cact="assetDelete" data-id="${a.id}" aria-label="Remove ${esc(a.name)}" title="Remove">${ic('x', 10)}</button>` : ''}</div>`;
}

Chat.assetBody = function () {
  const kind = C.assetTab || 'emoji';
  const rows = (C.assets || []).filter(a => a.kind === kind && a.active);
  const srv = C.servers.find(s => s.id === C.sid) || {};
  const canDel = a => a.by === (S.user || {}).id || ((srv.perms || 0) & 128);
  if (kind === 'emoji') {
    return `<p class="expr-hint">Server emoji become text: anyone can type or pick <b>:name:</b>. They also work as reactions.</p>
      ${rows.length ? `<div class="expr-grid">${rows.map(a => exprTile(a, 'insertemoji', `data-slug="${esc(a.slug)}"`, canDel(a))).join('')}</div>`
        : '<div class="expr-empty">No custom emoji yet. Add the first one for this server.</div>'}`;
  }
  if (kind === 'sticker') {
    return `<p class="expr-hint">Custom stickers send as images in this server. The built-in set still works everywhere.</p>
      ${rows.length ? `<div class="expr-grid">${rows.map(a => exprTile(a, 'sendsticker', `data-id="a${a.id}"`, canDel(a))).join('')}</div>`
        : '<div class="expr-empty">No custom stickers yet.</div>'}
      <div class="expr-sub">Built-in stickers</div>
      <div class="stk-grid">${C.stickers.map(s => `<button data-cact="sendsticker" data-id="${s.id}" aria-label="${esc(s.label)}" title="${esc(s.label)}">${s.e}</button>`).join('')}</div>`;
  }
  return `<p class="expr-hint">GIFs from this server send like a big sticker, with your text if you add some.</p>
    ${rows.length ? `<div class="expr-grid gifs">${rows.map(a => exprTile(a, 'sendsticker', `data-id="g${a.id}"`, canDel(a))).join('')}</div>`
      : '<div class="expr-empty">No GIFs yet. Add a .gif under 4 MB.</div>'}`;
};

Chat.stickerPicker = async function () {
  if (!C.stickers.length) {
    try { const r = await api('stickers'); C.stickers = r.stickers || []; } catch (e) { }
  }
  if (C.thread && C.thread.kind !== 'ch') {
    modal(`<div class="mg"><div class="row between mg-top"><h2>Stickers</h2><button class="btn-s ico" data-mact="close" aria-label="Close">${ic('x', 14)}</button></div>
      <div class="stk-grid">${C.stickers.map(s => `<button data-cact="sendsticker" data-id="${s.id}" aria-label="${esc(s.label)}" title="${esc(s.label)}">${s.e}</button>`).join('')}</div>
      <p class="xs mut">Stickers send on their own, like a reaction you can see coming.</p></div>`, true);
    return;
  }
  await Chat.loadAssets(C.sid);
  if (!['emoji', 'sticker', 'gif'].includes(C.assetTab)) C.assetTab = 'emoji';
  const srv = C.servers.find(s => s.id === C.sid) || {};
  const canAdd = !!((srv.perms || 0) & 4);
  const tabs = [['emoji', 'Emoji'], ['sticker', 'Stickers'], ['gif', 'GIFs']];
  modal(`<div class="mg expr-modal">
    <div class="row between mg-top"><div><h2>Expressions</h2><p class="xs mut">This server's emoji, stickers and GIFs.</p></div>
      <div class="row g8">${canAdd ? `<button class="btn-s expr-add" data-cact="assetAdd">${ic('plus', 14)} Add</button>` : ''}<button class="btn-s ico" data-mact="close" aria-label="Close">${ic('x', 14)}</button></div></div>
    <div class="expr-tabs" role="tablist" aria-label="Expression type">${tabs.map(([k, l]) => `<button class="expr-tab ${C.assetTab === k ? 'on' : ''}" role="tab" aria-selected="${C.assetTab === k}" data-cact="assetTab" data-kind="${k}">${l}</button>`).join('')}</div>
    <div id="expr_body">${Chat.assetBody()}</div>
    <p class="xs mut expr-note">Members with Attach Files can add expressions. Only the uploader or a server manager can remove one.</p></div>`, true);
};

Chat.assetForm = function (kind) {
  kind = ['emoji', 'sticker', 'gif'].includes(kind) ? kind : 'emoji';
  const nm = kind === 'emoji' ? 'Emoji' : kind === 'sticker' ? 'Sticker' : 'GIF';
  const limit = kind === 'emoji' ? '2 MB · 512px' : kind === 'sticker' ? '4 MB · 1024px' : '4 MB · 1280px';
  modal(`<div class="mg expr-form"><div class="row between mg-top"><div><h2>Add ${nm}</h2><p class="xs mut">Shared with everyone in this server.</p></div><button class="btn-s ico" data-mact="close" aria-label="Close">${ic('x', 14)}</button></div>
    <label>Name</label><input id="expr_name" maxlength="24" placeholder="${kind === 'emoji' ? 'crew-heart' : 'study cat'}" autocapitalize="off" spellcheck="false">
    <label>Image</label><input id="expr_file" type="file" accept="image/png,image/jpeg,image/gif,image/webp">
    <p class="xs mut">${kind === 'emoji' ? 'An emoji token like :crew-heart:. ' : ''}PNG, JPG, WebP${kind === 'gif' ? ' or GIF' : ' or GIF'} · ${limit}.</p>
    <button class="btn-p btn-xl mt8" data-cact="assetSave" data-kind="${kind}">Add ${nm}</button></div>`, true);
};

Chat.saveAsset = async function (el) {
  const kind = el.dataset.kind;
  const file = ($id('expr_file') || {}).files && $id('expr_file').files[0];
  const name = (($id('expr_name') || {}).value || '').trim();
  if (!file) { toast('Pick an image first'); return; }
  if (!kind || !C.sid) return;
  const max = kind === 'emoji' ? 2 * 1024 * 1024 : 4 * 1024 * 1024;
  if (kind === 'gif' && file.type && file.type !== 'image/gif') { toast('A GIF slot needs a .gif file'); return; }
  el.disabled = true; el.textContent = 'Uploading…';
  try {
    const send = kind === 'gif' ? file : await shrinkImage(file, kind === 'emoji' ? 512 : kind === 'sticker' ? 1024 : 1280, 0.9);
    if (send.size > max) { toast('Too big', 'That file is over ' + (max / 1048576) + ' MB'); el.disabled = false; el.textContent = 'Add'; return; }
    const res = await fetch('/api/upload?asset_server=' + C.sid, {
      method: 'POST', body: send, credentials: 'same-origin',
      headers: { 'X-File-Name': encodeURIComponent(send.name || file.name || 'expression.png'), 'X-File-Type': send.type || 'application/octet-stream' },
    });
    const up = await res.json().catch(() => ({}));
    if (!res.ok) { toast('Upload failed', up.error || ('HTTP ' + res.status), 'err'); el.disabled = false; el.textContent = 'Add'; return; }
    const r = await api('ch/assets', { server: C.sid, kind, name: name || (file.name || '').replace(/\.[^.]+$/, ''), upload: up.file.id });
    putAsset(r.asset);
    toast('Added', ':' + r.asset.slug + ': is ready for the server.');
    closeModal();
    Chat.stickerPicker();
  } catch (e) {
    el.disabled = false; el.textContent = 'Add';
  }
};

Chat.assetDelete = async function (id) {
  const a = assetById(id); if (!a) return;
  if (!(await confirmSheet(`Remove ${a.name} from this server? Old messages keep it.`, 'Remove', true))) return;
  try {
    await api('ch/assets/delete', { id });
    a.active = false; refreshExpr(); if (C.thread && C.thread.kind === 'ch') paint();
    toast('Removed', 'It stays visible in old messages.');
  } catch (e) { }
};

Chat.insertEmoji = function (slug) {
  const token = ':' + slug + ':';
  if (typeof modalOpen === 'function' && modalOpen()) closeModal();
  const ta = $id('soc_in'); if (!ta) return;
  const start = ta.selectionStart == null ? ta.value.length : ta.selectionStart;
  const end = ta.selectionEnd == null ? start : ta.selectionEnd;
  ta.value = ta.value.slice(0, start) + token + ta.value.slice(end);
  C.draft = ta.value;
  ta.selectionStart = ta.selectionEnd = start + token.length;
  ta.dispatchEvent(new Event('input', { bubbles: true }));
  ta.focus();
};

Chat.sendSticker = async function (id) {
  if (!C.thread) return;
  try {
    const r = C.thread.kind === 'ch'
      ? await api('ch/send', { ch: C.ch, text: '', sticker: id })
      : await api('chat/send', { thread: 'dm:' + C.thread.id, text: '', sticker: id });
    appendMsg(r.message);
    if (C.thread.kind === 'ch') Chat.read(r.message.id);
  } catch (e) { }
};

let prevTimer = 0;
function maybePreview() {
  const ta = $id('soc_in'); if (!ta) return;
  clearTimeout(prevTimer);
  const m = /https?:\/\/[^\s<>"']+/i.exec(ta.value);
  const url = m ? m[0].replace(/[.,;:!?)\]}]+$/, '') : '';
  if (!url) { if (C.prev) { C.prev = null; paintFiles(); } return; }
  if (C.prev && C.prev.url === url) return;
  if (C.prevCache[url]) { C.prev = C.prevCache[url]; paintFiles(); return; }
  prevTimer = setTimeout(async () => {
    try {
      const r = await api('preview?url=' + encodeURIComponent(url));
      if (!r.preview) return;
      C.prevCache[url] = r.preview;
      const now = $id('soc_in');
      if (now && now.value.includes(url)) { C.prev = r.preview; paintFiles(); }
    } catch (e) { }
  }, 700);
}

Chat.read = function (id) {
  if (!C.thread || C.thread.kind !== 'ch') return;
  const now = Date.now();
  if (now - C.lastRead < 900) return;
  C.lastRead = now;
  api('ch/read', { ch: C.ch, id }).catch(() => { });
};

function paintCtx() {
  const el = $id('soc_ctx'); if (!el) return;
  el.innerHTML = C.edit ? `<div class="ctx">${ic('edit', 14)}<span class="ell">Editing your message</span><button class="btn-s ico" data-cact="cancel" aria-label="Cancel edit">${ic('x', 13)}</button></div>`
    : C.reply ? `<div class="ctx">${ic('reply', 14)}<span class="ell">Replying to <b>${esc(who(C.reply.uid))}</b>: ${esc(C.reply.text)}</span><button class="btn-s ico" data-cact="cancel" aria-label="Cancel reply">${ic('x', 13)}</button></div>` : '';
  paintMeta();
}

Chat.jump = async function (id) {
  let el = document.querySelector(`#soc_msgs [data-mid="${id}"]`);
  if (!el && C.thread && C.thread.kind === 'ch') {
    try {
      const r = await api(`ch/messages?ch=${C.ch}&around=${id}`);
      C.msgs = (r.messages || []).map(norm); C.more = true; paint();
      el = document.querySelector(`#soc_msgs [data-mid="${id}"]`);
    } catch (e) { }
  }
  if (el) { el.scrollIntoView({ block: 'center' }); el.classList.add('flash'); setTimeout(() => el.classList.remove('flash'), 1300); }
  else toast('That message is further up');
};

let searchTimer = 0;
function doSearch(v) {
  C.q = v;
  clearTimeout(searchTimer);
  if (v.trim().length < 2) { C.results = false; const s = $id('soc_search'); if (s) s.innerHTML = searchHTML(); return; }
  searchTimer = setTimeout(async () => {
    try {
      const r = await api('ch/search?ch=' + C.ch + '&q=' + encodeURIComponent(v.trim()));
      C.results = r.results || [];
      const s = $id('soc_search'); if (s) s.innerHTML = searchHTML();
    } catch (e) { }
  }, 280);
}

function showMent() {
  const ta = $id('soc_in'), box = $id('soc_ment'); if (!ta || !box) return;
  const m = /@([A-Za-z0-9_ ]{0,20})$/.exec(ta.value.slice(0, ta.selectionStart));
  if (!m) { box.innerHTML = ''; box.classList.remove('on'); return; }
  const q = m[1].toLowerCase();
  const hits = Object.entries(C.people).filter(([uid, p]) => +uid !== S.user.id && (!q || p.display.toLowerCase().includes(q))).slice(0, 6);
  if (!hits.length) { box.innerHTML = ''; box.classList.remove('on'); return; }
  box.innerHTML = hits.map(([uid, p]) => `<button class="ment-i" data-cact="ment" data-name="${esc(p.display)}">${avatar(p.emoji, p.color, 'xs', null, p)}<span>${esc(p.display)}</span></button>`).join('');
  box.classList.add('on');
}

/* ---------- reactions: a proper picker, not a wall of emoji ---------- */
let RX_AWAY = null;
function closeRx() {
  const p = $id('rx_pop'); if (p) p.remove();
  if (RX_AWAY) { document.removeEventListener('pointerdown', RX_AWAY, true); RX_AWAY = null; }
}

Chat.rxPicker = function (id, anchor) {
  const m = C.msgs.find(x => x.id === id); if (!m || !anchor) return;
  const cur = $id('rx_pop');
  if (cur && cur.dataset.id === String(id)) { closeRx(); return; }
  closeRx();
  const mine = Array.isArray(m.mine) ? m.mine : [];
  const pop = document.createElement('div');
  pop.id = 'rx_pop'; pop.className = 'rxpop'; pop.dataset.id = String(id); pop.setAttribute('role', 'dialog'); pop.setAttribute('aria-label', 'Add a reaction');
    pop.innerHTML = `<div class="rxpop-g">${reactionChoices().map(e => `<button class="rxpop-e ${mine.includes(e) ? 'on' : ''}" data-cact="react" data-id="${id}" data-e="${esc(e)}" aria-label="React ${esc(e)}" aria-pressed="${mine.includes(e)}">${reactionHTML(e)}</button>`).join('')}</div>
    <div class="rxpop-h">Tap yours again to remove it</div>`;
  document.body.appendChild(pop);
  const soc = document.querySelector('.soc');
  if (soc) {
    const cs = getComputedStyle(soc);
    ['--s1', '--s2', '--line2', '--tx', '--tx2', '--mut', '--acc', '--acc2', '--accbg', '--shadow'].forEach(k => {
      const v = cs.getPropertyValue(k).trim(); if (v) pop.style.setProperty(k, v);
    });
  }
  const r = anchor.getBoundingClientRect(), w = pop.offsetWidth || 268, h = pop.offsetHeight || 104;
  const left = Math.min(window.innerWidth - w - 10, Math.max(10, r.right - w));
  let top = r.top - h - 8;
  if (top < 8) top = Math.min(window.innerHeight - h - 10, r.bottom + 8);
  pop.style.left = Math.round(left) + 'px'; pop.style.top = Math.round(top) + 'px';
  RX_AWAY = e => { if (!e.target.closest('#rx_pop')) closeRx(); };
  setTimeout(() => document.addEventListener('pointerdown', RX_AWAY, true), 0);
  const sc = $id('soc_msgs');
  if (sc) sc.addEventListener('scroll', closeRx, { once: true, passive: true });
};

Chat.replyTo = function (id) {
  const m = C.msgs.find(x => x.id === id); if (!m) return;
  const wasEdit = C.edit;
  const hasFiles = Array.isArray(m.files) && m.files.length;
  C.reply = { id: m.id, uid: m.uid, text: (m.text || (hasFiles ? 'attachment' : m.sticker ? 'sticker' : 'message')).slice(0, 90) };
  C.edit = null;
  if (wasEdit) { const t = $id('soc_in'); if (t) { t.value = ''; C.draft = ''; } }
  if (typeof modalOpen === 'function' && modalOpen()) closeModal();
  closeRx();
  paintCtx();
  const ta = $id('soc_in'); if (ta) { ta.focus(); if (C.draft) ta.selectionStart = ta.selectionEnd = ta.value.length; }
};

Chat.msgSheet = function (id) {
  const m = C.msgs.find(x => x.id === id); if (!m) return;
  const p = C.people[m.uid] || { display: 'Member', emoji: '👤', color: '#8b8ba3' };
  const own = m.uid === (S.user || {}).id;
  const mine = Array.isArray(m.mine) ? m.mine : [];
  closeRx();
  modal(`<div class="msheet">
    <div class="msheet-head">${avatar(p.emoji, p.color, 'sm', null, p)}<div class="grow min0"><b class="ell">${esc(p.display || 'Member')}</b><span class="xs mut">${esc(chatClock(m.ts))} · ${esc(chatDay(m.ts))}</span></div>
      <button class="btn-s ico" data-cact="closesheet" aria-label="Close">${ic('x', 14)}</button></div>
    ${m.text ? `<div class="msheet-tx">${fmt(m.text)}</div>` : ''}
    <div class="msheet-rx" role="group" aria-label="Quick reactions">${reactionChoices().map(e => `<button class="rxpop-e ${mine.includes(e) ? 'on' : ''}" data-cact="react" data-id="${m.id}" data-e="${esc(e)}" aria-label="React ${esc(e)}" aria-pressed="${mine.includes(e)}">${reactionHTML(e)}</button>`).join('')}</div>
    <div class="msheet-acts">
      <button data-cact="reply" data-id="${m.id}"><span class="ms-ic">${ic('reply', 15)}</span><span>Reply</span></button>
      <button data-cact="copy" data-id="${m.id}"><span class="ms-ic">${ic('copy', 15)}</span><span>Copy text</span></button>
      ${own ? `<button data-cact="edit" data-id="${m.id}"><span class="ms-ic">${ic('edit', 15)}</span><span>Edit</span></button>
      <button class="danger" data-cact="del" data-id="${m.id}"><span class="ms-ic">${ic('trash', 15)}</span><span>Delete</span></button>`
        : `<button class="danger" data-cact="report" data-id="${m.id}"><span class="ms-ic">${ic('flag', 15)}</span><span>Report</span></button>`}
    </div></div>`);
};

Chat.copyMsg = function (id) {
  const m = C.msgs.find(x => x.id === id); if (!m) return;
  const text = String(m.text || '').trim();
  if (!text) {
    if (typeof modalOpen === 'function' && modalOpen()) closeModal();
    toast('Nothing to copy'); return;
  }
  const done = () => {
    if (typeof modalOpen === 'function' && modalOpen()) closeModal();
    toast('Copied');
  };
  try {
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(done, () => fallbackCopy(text, done));
      return;
    }
  } catch (e) { }
  fallbackCopy(text, done);
};

function fallbackCopy(text, done) {
  try {
    const ta = document.createElement('textarea');
    ta.value = text; ta.setAttribute('readonly', '');
    ta.style.cssText = 'position:fixed;top:-1000px;left:-1000px;opacity:0';
    document.body.appendChild(ta); ta.select(); ta.setSelectionRange(0, text.length);
    const ok = document.execCommand && document.execCommand('copy');
    ta.remove();
    if (ok) done(); else toast('Could not copy');
  } catch (e) { toast('Could not copy'); }
}

Chat.appearance = function () {
  closeRx();
  const body = (typeof Theme !== 'undefined') ? Theme.panelHTML('chat') : '<p class="sm mut">The appearance engine did not load. Reload the page and try again.</p>';
  modal(`<div class="mg chat-thp"><div class="row between mg-top"><div><div class="xs mut up">Crew chat</div><h2>Chat appearance</h2></div>
    <button class="btn-s ico" data-cact="closesheet" aria-label="Close">${ic('x', 14)}</button></div>${body}</div>`);
};

/* ---------- swipe to reply (touch) + long press for actions ---------- */
let SWP = null;
const swpClear = msg => {
  if (!msg) return;
  msg.classList.remove('swiping', 'swipe-ready', 'swipe-back');
  msg.style.transform = '';
};

function swipeStart(e) {
  if (e.pointerType === 'mouse' || e.isPrimary === false) return;
  if (LB.open || (typeof modalOpen === 'function' && modalOpen())) return;
  if (e.target.closest('button,a,input,textarea,select')) return;
  const msg = e.target.closest('#soc_msgs .msg'); if (!msg) return;
  if (SWP) { clearTimeout(SWP.hold); swpClear(SWP.msg); }
  SWP = { msg, id: +msg.dataset.mid, x: e.clientX, y: e.clientY, dx: 0, mode: '', hold: 0, pid: e.pointerId };
  SWP.hold = setTimeout(() => {
    if (!SWP || SWP.mode || SWP.dx) return;
    const id = SWP.id; SWP = null;
    try { navigator.vibrate && navigator.vibrate(9); } catch (x) { }
    Chat.msgSheet(id);
  }, 460);
}

function swipeMove(e) {
  if (!SWP || e.pointerId !== SWP.pid) return;
  const dx = e.clientX - SWP.x, dy = e.clientY - SWP.y;
  if (!SWP.mode) {
    if (Math.abs(dx) < 8 && Math.abs(dy) < 8) return;
    clearTimeout(SWP.hold);
    if (dx > 10 && Math.abs(dx) > Math.abs(dy) * 1.15) {
      SWP.mode = 'x'; SWP.msg.classList.add('swiping');
    } else { swpClear(SWP.msg); SWP = null; return; }
  }
  if (e.cancelable) e.preventDefault();
  const d = Math.max(0, Math.min(dx, 104));
  SWP.dx = d;
  SWP.msg.style.transform = `translate3d(${d}px,0,0)`;
  SWP.msg.classList.toggle('swipe-ready', d >= 62);
}

function swipeEnd(e) {
  if (!SWP || (e && e.pointerId !== SWP.pid)) return;
  clearTimeout(SWP.hold);
  const { msg, id, mode, dx } = SWP;
  SWP = null;
  msg.classList.add('swipe-back');
  msg.style.transform = '';
  msg.classList.remove('swiping', 'swipe-ready');
  setTimeout(() => msg.classList.remove('swipe-back'), 240);
  if (mode === 'x' && dx >= 62) {
    try { navigator.vibrate && navigator.vibrate(12); } catch (x) { }
    Chat.replyTo(id);
  }
}

document.addEventListener('pointerdown', swipeStart, { passive: true });
document.addEventListener('pointermove', swipeMove, { passive: false });
document.addEventListener('pointerup', swipeEnd, { passive: true });
document.addEventListener('pointercancel', swipeEnd, { passive: true });

/* ---------- image lightbox: zoom, pan, download ---------- */
const LB = { open: false, list: [], i: 0, scale: 1, x: 0, y: 0, drag: null, pinch: null, ptrs: new Map() };

function lbEl() {
  let el = $id('lbx'); if (el) return el;
  el = document.createElement('div');
  el.id = 'lbx'; el.className = 'lbx'; el.hidden = true;
  el.setAttribute('role', 'dialog'); el.setAttribute('aria-modal', 'true'); el.setAttribute('aria-label', 'Image viewer');
  el.innerHTML = `<div class="lbx-bar"><div class="lbx-title"></div><div class="lbx-tools">
      <button data-lb="out" title="Zoom out" aria-label="Zoom out">−</button>
      <button data-lb="zoom" class="lbx-zoom" title="Reset zoom" aria-label="Reset zoom">100%</button>
      <button data-lb="in" title="Zoom in" aria-label="Zoom in">＋</button>
      <a data-lb="dl" download title="Download" aria-label="Download">${ic('download', 16)}</a>
      <button data-lb="close" title="Close" aria-label="Close">${ic('x', 16)}</button></div></div>
    <div class="lbx-stage"><img alt=""></div>
    <div class="lbx-foot"><button data-lb="prev" aria-label="Previous image">‹</button><span class="lbx-count"></span><button data-lb="next" aria-label="Next image">›</button></div>
    <div class="lbx-hint">Scroll or pinch to zoom · drag to pan · double-click to reset</div>`;
  document.body.appendChild(el);
  const stage = el.querySelector('.lbx-stage');
  stage.addEventListener('wheel', e => { e.preventDefault(); lbScale(LB.scale * (e.deltaY < 0 ? 1.12 : 1 / 1.12)); }, { passive: false });
  stage.addEventListener('pointerdown', e => {
    if (!LB.open) return;
    e.stopPropagation();
    try { stage.setPointerCapture(e.pointerId); } catch (x) { }
    LB.ptrs.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (LB.ptrs.size === 1) { LB.drag = { x: e.clientX, y: e.clientY, ox: LB.x, oy: LB.y }; LB.pinch = null; }
    else if (LB.ptrs.size === 2) {
      const [a, b] = [...LB.ptrs.values()];
      LB.pinch = { d: Math.hypot(a.x - b.x, a.y - b.y) || 1, s: LB.scale };
      LB.drag = null;
    }
  });
  stage.addEventListener('pointermove', e => {
    if (!LB.ptrs.has(e.pointerId)) return;
    LB.ptrs.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (LB.ptrs.size === 2 && LB.pinch) {
      const [a, b] = [...LB.ptrs.values()];
      const d = Math.hypot(a.x - b.x, a.y - b.y) || 1;
      const ns = clamp(LB.pinch.s * d / LB.pinch.d, 1, 6);
      if (Math.abs(ns - LB.scale) > .004) { LB.scale = ns; lbApply(); }
    } else if (LB.drag && LB.scale > 1) {
      LB.x = LB.drag.ox + (e.clientX - LB.drag.x);
      LB.y = LB.drag.oy + (e.clientY - LB.drag.y);
      lbApply();
    }
  });
  const up = e => {
    if (!LB.ptrs.has(e.pointerId)) return;
    LB.ptrs.delete(e.pointerId); LB.pinch = null;
    if (LB.ptrs.size === 1) { const p = [...LB.ptrs.values()][0]; LB.drag = { x: p.x, y: p.y, ox: LB.x, oy: LB.y }; }
    else LB.drag = null;
  };
  stage.addEventListener('pointerup', up);
  stage.addEventListener('pointercancel', up);
  stage.addEventListener('click', e => { if (e.target === stage && LB.scale === 1) lbClose(); });
  const img = el.querySelector('img');
  img.addEventListener('dblclick', () => { if (LB.scale > 1) lbReset(); else { LB.scale = 2.4; lbApply(); } });
  return el;
}

function lbApply() {
  const el = $id('lbx'); if (!el) return;
  const img = el.querySelector('img'), stage = el.querySelector('.lbx-stage');
  const mx = stage.clientWidth * (LB.scale - 1) / 2, my = stage.clientHeight * (LB.scale - 1) / 2;
  LB.x = clamp(LB.x, -mx, mx); LB.y = clamp(LB.y, -my, my);
  img.style.transform = `translate(${LB.x}px,${LB.y}px) scale(${LB.scale})`;
  img.style.cursor = LB.scale > 1 ? 'grab' : 'zoom-in';
  el.classList.toggle('zoomed', LB.scale > 1);
  const z = el.querySelector('[data-lb="zoom"]'); if (z) z.textContent = Math.round(LB.scale * 100) + '%';
}

function lbReset() { LB.scale = 1; LB.x = 0; LB.y = 0; lbApply(); }
function lbScale(n) { LB.scale = clamp(n, 1, 6); if (LB.scale === 1) { LB.x = 0; LB.y = 0; } lbApply(); }

function lbImages() {
  const out = [];
  C.msgs.forEach(m => (m.files || []).forEach(f => { if (String(f.mime).startsWith('image/')) out.push(f); }));
  return out;
}

function lbShow() {
  const el = lbEl(), f = LB.list[LB.i]; if (!f) return lbClose();
  const img = el.querySelector('img');
  img.src = '/api/file?id=' + f.id; img.alt = f.name || 'image';
  el.querySelector('.lbx-title').textContent = f.name || 'image';
  const dl = el.querySelector('[data-lb="dl"]'); dl.href = img.src; dl.setAttribute('download', f.name || 'image');
  const count = el.querySelector('.lbx-count');
  count.textContent = LB.list.length > 1 ? `${LB.i + 1} / ${LB.list.length}` : '';
  el.querySelector('[data-lb="prev"]').hidden = LB.list.length < 2;
  el.querySelector('[data-lb="next"]').hidden = LB.list.length < 2;
  LB.x = 0; LB.y = 0; LB.scale = 1; lbApply();
}

function lbStep(d) {
  if (LB.list.length < 2) return;
  LB.i = (LB.i + d + LB.list.length) % LB.list.length;
  lbShow();
}

function lbClose() {
  LB.open = false;
  const el = $id('lbx'); if (el) el.hidden = true;
  document.body.classList.remove('noscroll');
  try { if (LB.opener && LB.opener.isConnected) LB.opener.focus({ preventScroll: true }); } catch (e) { }
}

Chat.lightbox = function (fid) {
  const list = lbImages();
  const i = list.findIndex(f => f.id === fid);
  if (i < 0) return;
  LB.list = list; LB.i = i; LB.open = true; LB.ptrs.clear(); LB.drag = null; LB.pinch = null;
  try { LB.opener = document.activeElement; } catch (e) { }
  const el = lbEl(); el.hidden = false;
  document.body.classList.add('noscroll');
  lbShow();
  setTimeout(() => { try { el.querySelector('[data-lb="close"]').focus({ preventScroll: true }); } catch (e) { } }, 0);
};

document.addEventListener('click', e => {
  const b = e.target.closest('[data-lb]'); if (!b) return;
  const act = b.dataset.lb;
  if (act === 'dl') {
    e.preventDefault();
    const f = LB.list[LB.i]; if (!f) return;
    const name = f.name || 'image';
    fetch('/api/file?id=' + f.id, { credentials: 'same-origin' })
      .then(r => { if (!r.ok) throw new Error(r.status); return r.blob(); })
      .then(blob => {
        const u = URL.createObjectURL(blob);
        const a = document.createElement('a'); a.href = u; a.download = name; a.rel = 'noopener';
        document.body.appendChild(a); a.click(); a.remove();
        setTimeout(() => URL.revokeObjectURL(u), 4000);
      })
      .catch(() => toast('Download failed', 'Try the original file link instead.', 'err'));
    return;
  }
  e.preventDefault();
  if (act === 'close') lbClose();
  else if (act === 'prev') lbStep(-1);
  else if (act === 'next') lbStep(1);
  else if (act === 'in') lbScale(LB.scale * 1.35);
  else if (act === 'out') lbScale(LB.scale / 1.35);
  else if (act === 'zoom') lbReset();
});

document.addEventListener('keydown', e => {
  if (!LB.open) return;
  if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); lbClose(); }
  else if (e.key === 'ArrowRight') { e.preventDefault(); lbStep(1); }
  else if (e.key === 'ArrowLeft') { e.preventDefault(); lbStep(-1); }
  else if (e.key === '+' || e.key === '=') { e.preventDefault(); lbScale(LB.scale * 1.35); }
  else if (e.key === '-') { e.preventDefault(); lbScale(LB.scale / 1.35); }
  else if (e.key === '0') { e.preventDefault(); lbReset(); }
}, true);

/* ---------- DOM events ---------- */
const ACT = {
  reload: () => Chat.load().then(render),
  addserver: () => Manage.addServer(),
  attach: () => Chat.pickAttach(),
  stick: () => Chat.stickerPicker(),
  assetTab: el => Chat.assetTab(el.dataset.kind),
  assetAdd: () => Chat.assetForm(C.assetTab),
  assetSave: el => Chat.saveAsset(el),
  assetDelete: el => Chat.assetDelete(+el.dataset.id),
  insertemoji: el => Chat.insertEmoji(el.dataset.slug),
  sendsticker: el => { closeModal(); Chat.sendSticker(el.dataset.id); },
  unfile: el => { C.files = C.files.filter(f => f.id !== +el.dataset.id); paintFiles(); },
  unprev: () => { C.prev = null; paintFiles(); },
  servermenu: () => Manage.open(C.sid),
  members: () => Manage.open(C.sid, 'members'),
  chsettings: () => Manage.channel(C.ch),
  newchannel: () => Manage.newChannel(),
  friends: () => Manage.friends(),
  report: el => { if (typeof modalOpen === 'function' && modalOpen()) closeModal(); Manage.report(+el.dataset.id); },
  srv: el => Chat.srv(+el.dataset.id),
  ch: el => { const id = +el.dataset.id; const { c } = voiceChannelOf(id); if (c && c.kind === 'voice') Chat.joinVoice(id); else Chat.openChannel(id); },
  voice: el => Chat.joinVoice(+el.dataset.id),
  vmute: () => Chat.toggleMute(),
  vdeaf: () => Chat.toggleDeafen(),
  vscreen: () => Chat.toggleScreen(),
  vstart: el => { closeModal(); if (C.voice.screen) screenApplyPreset(el.dataset.p, false); else Chat.startScreen(el.dataset.p); },
  vstats: () => Chat.toggleScreenStats(),
  vleave: () => Chat.leaveVoice(),
  vroom: () => { if (!C.voice.ch) return; C.ch = C.voice.ch; C.thread = { kind: 'voice', id: C.voice.ch }; C.view = 'chat'; C.msgs = []; C.more = false; render(); paintScreen(); },
  dm: el => Chat.openDM(+el.dataset.id),
  back: () => { C.view = 'list'; const s = document.querySelector('.soc'); if (s) s.dataset.view = 'list'; },
  send: () => Chat.send(),
  older: () => Chat.older(),
  sel: el => {
    const id = +el.dataset.id, old = C.sel;
    C.sel = C.sel === id ? null : id;
    if (old) rerenderMsg(old);
    if (C.sel) rerenderMsg(id);
  },
  react: async el => {
    const id = +el.dataset.id, e = el.dataset.e, m = C.msgs.find(x => x.id === id); if (!m || !C.thread) return;
    closeRx();
    if (typeof modalOpen === 'function' && modalOpen()) closeModal();
    const mine = Array.isArray(m.mine) ? m.mine : [];
    const on = mine.includes(e);
    if (!m.re || typeof m.re !== 'object') m.re = {};
    m.re[e] = (m.re[e] || 0) + (on ? -1 : 1);
    if (m.re[e] <= 0) delete m.re[e];
    m.mine = on ? mine.filter(x => x !== e) : mine.concat(e);
    rerenderMsg(id);
    try {
      if (C.thread.kind === 'ch') await api('ch/react', { ch: C.ch, id, emoji: e });
      else await api('chat/react', { id, emoji: e });
    } catch (x) { }
  },
  reply: el => Chat.replyTo(+el.dataset.id),
  edit: el => {
    const m = C.msgs.find(x => x.id === +el.dataset.id); if (!m) return;
    if (typeof modalOpen === 'function' && modalOpen()) closeModal();
    C.edit = m.id; C.reply = null; C.sel = null;
    const ta = $id('soc_in');
    if (ta) { ta.value = m.text; C.draft = m.text; ta.style.height = 'auto'; ta.style.height = Math.min(ta.scrollHeight, 140) + 'px'; ta.focus(); }
    paintCtx();
  },
  more: el => Chat.msgSheet(+el.dataset.id),
  rxopen: el => Chat.rxPicker(+el.dataset.id, el),
  copy: el => Chat.copyMsg(+el.dataset.id),
  closesheet: () => closeModal(),
  appearance: () => Chat.appearance(),
  img: el => Chat.lightbox(+el.dataset.id),
  cancel: () => { const ta = $id('soc_in'); if (C.edit) { if (ta) ta.value = ''; C.draft = ''; } C.edit = null; C.reply = null; paintCtx(); },
  del: async el => {
    const id = +el.dataset.id;
    if (typeof modalOpen === 'function' && modalOpen()) closeModal();
    if (!(await confirmSheet('Delete this message for everyone?', 'Delete', true))) return;
    try {
      if (C.thread.kind === 'ch') await api('ch/delete', { ch: C.ch, id }); else await api('chat/delete', { id });
      C.msgs = C.msgs.filter(m => m.id !== id); document.querySelector(`#soc_msgs [data-mid="${id}"]`)?.remove();
      if (C.edit === id) { C.edit = null; C.draft = ''; }
      if (C.reply && C.reply.id === id) C.reply = null;
      paintCtx(); paintMeta();
    } catch (e) { }
  },
  jump: el => { C.results = null; Chat.jump(+el.dataset.id); const s = $id('soc_search'); if (s) s.remove(); },
  search: () => { if (C.results === null) { C.results = false; C.q = ''; const m = document.querySelector('.smain'); if (m) m.insertAdjacentHTML('beforeend', `<div class="soc-search" id="soc_search">${searchHTML()}</div>`); } },
  closesearch: () => { C.results = null; $id('soc_search')?.remove(); },
  ment: el => {
    const ta = $id('soc_in'); if (!ta) return;
    const v = ta.value, pos = ta.selectionStart, pre = v.slice(0, pos).replace(/@[A-Za-z0-9_ ]*$/, '');
    ta.value = pre + '@' + el.dataset.name + ' ' + v.slice(pos);
    ta.focus(); ta.selectionStart = ta.selectionEnd = (pre + '@' + el.dataset.name + ' ').length;
    $id('soc_ment')?.classList.remove('on');
  },
};

document.addEventListener('click', e => {
  const el = e.target.closest('[data-cact]');
  if (!el) return;
  const appAct = e.target.closest('[data-act]');  // avatars, profile links etc. belong to app.js
  if (appAct && appAct !== el && el.contains(appAct)) return;
  e.preventDefault(); e.stopPropagation();
  const fn = ACT[el.dataset.cact];
  if (fn) { try { fn(el); } catch (x) { console.error(x); } }
}, true);

document.addEventListener('change', e => {
  if (e.target.id === 'soc_file') { Chat.addFiles(e.target.files || []); e.target.value = ''; }
});

document.addEventListener('paste', e => {
  if (e.target.id !== 'soc_in') return;
  const files = [...((e.clipboardData && e.clipboardData.items) || [])]
    .filter(i => i.kind === 'file').map(i => i.getAsFile()).filter(Boolean);
  if (!files.length) return;
  e.preventDefault();
  Chat.addFiles(files);
});

document.addEventListener('input', e => {
  if (e.target.id === 'soc_in') {
    const ta = e.target;
    ta.style.height = 'auto'; ta.style.height = Math.min(ta.scrollHeight, 140) + 'px';
    showMent();
    maybePreview();
    if (C.thread && C.thread.kind === 'ch' && !C.edit && Date.now() - C.lastTyping > 2500) {
      C.lastTyping = Date.now(); api('ch/typing', { ch: C.ch }).catch(() => { });
    }
  }
  if (e.target.id === 'soc_q') doSearch(e.target.value);
});

document.addEventListener('keydown', e => {
  if (e.target.id === 'soc_in' && e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    if (matchMedia('(pointer:coarse)').matches) return;
    e.preventDefault(); Chat.send();
  }
  if (e.target.id === 'soc_q' && e.key === 'Escape') ACT.closesearch();
  if (e.target.id === 'soc_in' && e.key === 'Escape') { $id('soc_ment')?.classList.remove('on'); }
  if (e.key === 'Escape') closeRx();
});

document.addEventListener('dblclick', e => {
  if (!e.target || e.target.id !== 'voice_screen') return;
  try {
    if (document.fullscreenElement) document.exitFullscreen().catch(() => { });
    else e.target.requestFullscreen().catch(() => { });
  } catch (x) { }
});

document.addEventListener('visibilitychange', () => {
  if (document.hidden || !S.user || S.tab !== 'chat' || !C.thread) return;
  if (C.thread.kind === 'ch' && C.msgs.length) { api('ch/read', { ch: C.ch, id: C.msgs[C.msgs.length - 1].id }).catch(() => { }); }
});

window.addEventListener('resize', () => { if (LB.open && LB.scale > 1) lbApply(); });

window.addEventListener('pagehide', () => {
  if (!C.voice.joined || !C.voice.ch) return;
  try { screenTeardown(false); } catch (e) { }
  try {
    fetch('/api/voice/leave', {
      method: 'POST', keepalive: true, credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ch: C.voice.ch }),
    });
  } catch (e) { }
});

/* cheap safety net: unread badge + catch-up if the stream slept */
setInterval(async () => {
  if (!S.user) return;
  C.unreadPoll = (C.unreadPoll || 0) + 1;
  if (C.unreadPoll % 4 === 0) {
    try {
      const r = await api('ch/unread');
      (C.servers || []).forEach(s => {
        let sum = 0;
        (s.channels || []).forEach(c => { const n = r.ch[String(c.id)] || 0; c.unread = n; sum += n; });
        s.unread = sum;
      });
      Chat.badge();
    } catch (e) { }
  }
}, 15000);

window.Chat = Chat;
