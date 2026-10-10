'use strict';
/* RAGDAMAXING front-end. Vanilla JS, no build step. */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const pad = n => String(n).padStart(2, '0');
const fm = m => { m = Math.round(m || 0); return m >= 60 ? `${Math.floor(m / 60)}h ${pad(m % 60)}m` : `${m}m`; };
const clk = s => { s = Math.max(0, Math.floor(s)); const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60); return (h ? h + ':' + pad(m) : pad(m)) + ':' + pad(s % 60); };
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const SUBS = ['Physics', 'Chemistry', 'Maths', 'English', 'Other'];
const SCOL = { Physics: '#5aa9ff', Chemistry: '#34d3a0', Maths: '#f0b84a', English: '#f0709a', Other: '#9a9aa8' };
const XPM = 2;                      // XP per verified minute (mirrors the server)
const MS = [[25, 40, '25 min block'], [50, 100, 'Deep block'], [90, 220, 'Elite block'], [120, 400, 'Marathon'], [180, 800, 'Beast mode'], [240, 1600, 'Legend']];
const RING = 590.6;                 // circumference of the r=94 timer ring

const PREF = {
  get(k, d) { try { const v = localStorage.getItem('rg_' + k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem('rg_' + k, JSON.stringify(v)); } catch (e) { } },
};
const _pc = PREF.get('pomo', null);
const S = {
  tab: 'today', sub: 'chapters', user: null, today: null, crew: null, syl: null, tests: null, ins: null, refl: null, weekly: null,
  pickSub: SUBS.includes(PREF.get('sub', '')) ? PREF.get('sub', '') : 'Physics',
  pickDur: [25, 50, 90].includes(PREF.get('dur', 0)) ? PREF.get('dur', 25) : 25,
  pickMode: ['timer', 'stopwatch', 'pomo'].includes(PREF.get('mode', '')) ? PREF.get('mode', '') : 'timer',
  pomoCfg: _pc && +_pc.total && +_pc.work && +_pc.brk ? { total: +_pc.total, work: +_pc.work, brk: +_pc.brk } : { total: 120, work: 50, brk: 10 },
  crewPeriod: 'week', authMode: 'login', t0: 0, p0: 0, urge: null, urgeTrig: '', fs: false, fsClock: PREF.get('clock', 'digital'),
  lastPtr: 0, beepKey: null, beeped: false, msStep: 0, msgKey: '', syncing: 0,
};

/* ---------- icons (stroke, currentColor) ---------- */
const IC = {
  today: '<path d="M13 2 4 14h7l-1 8 9-12h-7z"/>',
  crew: '<circle cx="9" cy="8" r="3.2"/><path d="M3 20c0-3.3 2.7-6 6-6s6 2.7 6 6"/><circle cx="17" cy="9" r="2.5"/><path d="M17 14.2c2.5.3 4 2.2 4 5"/>',
  chat: '<path d="M4 5h16v11H9l-5 4z"/>',
  study: '<path d="M4 5.5C4 4.7 4.7 4 5.5 4H12v16H5.5C4.7 20 4 19.3 4 18.5z"/><path d="M20 5.5c0-.8-.7-1.5-1.5-1.5H12v16h6.5c.8 0 1.5-.7 1.5-1.5z"/>',
  reflect: '<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/>',
  me: '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4.4 3.6-8 8-8s8 3.6 8 8"/>',
  flame: '<path d="M12 3c1 3.5 5 5.5 5 10a5 5 0 0 1-10 0c0-2 1-3 2-4 0 1.5 1 2 1.5 2C10.5 8 11 5.5 12 3z"/>',
  shield: '<path d="M12 3 5 6v6c0 4.4 3 7.3 7 9 4-1.7 7-4.6 7-9V6z"/>',
  check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
  x: '<path d="M6 6l12 12M18 6 6 18"/>',
  expand: '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
  crown: '<path d="M3 8l4.5 4L12 5l4.5 7L21 8l-2 11H5z"/>',
  left: '<path d="m15 5-7 7 7 7"/>', right: '<path d="m9 5 7 7-7 7"/>',
  bolt: '<path d="M13 2 4 14h7l-1 8 9-12h-7z"/>',
};
const ic = (n, s = 18) => `<svg class="ic" width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${IC[n] || ''}</svg>`;

/* ---------- api ---------- */
function apiErr(msg) { const e = new Error(msg); e.api = true; return e; }
async function api(path, body) {
  let r, j;
  try {
    r = await fetch('/api/' + path, { method: body === undefined ? 'GET' : 'POST', headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) });
    j = await r.json().catch(() => ({}));
  } catch (e) { toast('No connection', 'Check your network and try again.', 'err'); throw apiErr('network'); }
  const authCall = path === 'login' || path === 'register';
  if (r.status === 401 && !authCall) { onLoggedOut(); throw apiErr('login'); }
  if (!r.ok) { toast(j.error || 'Something went wrong', '', 'err'); throw apiErr(j.error || 'error'); }
  if (j.events && j.events.length) handleEvents(j.events);
  return j;
}
function onLoggedOut() {
  S.user = null; S.ins = null; stopTick(); S.fs = false; $('#fs')?.remove(); document.body.classList.remove('noscroll');
  try { chatReset(); } catch (e) { }
  renderAuth();
}

/* ---------- feedback: toasts, confetti, sound ---------- */
function toast(t, sub = '', cls = '') {
  const box = $('#toasts'); if (!box) return;
  const d = document.createElement('div'); d.className = 'toast ' + cls;
  d.innerHTML = `<b>${esc(t)}</b>` + (sub ? `<small>${esc(sub)}</small>` : '');
  box.appendChild(d); while (box.children.length > 3) box.firstChild.remove();
  setTimeout(() => d.remove(), 3500);
}
function confetti() {
  const cols = ['#7c6af7', '#a99cff', '#3dd6a0', '#f2b441', '#ececf1'];
  for (let i = 0; i < 30; i++) {
    const s = document.createElement('i'); s.className = 'confetti';
    s.style.left = Math.random() * 100 + 'vw'; s.style.background = cols[i % cols.length]; s.style.animationDelay = Math.random() * .5 + 's';
    document.body.appendChild(s); setTimeout(() => s.remove(), 3000);
  }
}
let _ac = null;
function beep() {
  try {
    _ac = _ac || new (window.AudioContext || window.webkitAudioContext)();
    if (_ac.state === 'suspended') _ac.resume();
    [0, .2, .4].forEach((t, i) => { const o = _ac.createOscillator(), g = _ac.createGain(); o.frequency.value = 620 + i * 180; g.gain.value = .12; o.connect(g); g.connect(_ac.destination); o.start(_ac.currentTime + t); o.stop(_ac.currentTime + t + .14); });
    if (navigator.vibrate) navigator.vibrate([180, 90, 180]);
  } catch (e) { }
}
function handleEvents(evs) {
  const xp = evs.filter(e => e.t === 'xp');
  if (xp.length) {
    const sum = xp.reduce((a, e) => a + e.amount, 0), labs = xp.map(e => e.label);
    toast(`${sum >= 0 ? '+' : ''}${sum} XP`, labs.slice(0, 2).join(' · ') + (labs.length > 2 ? ` · +${labs.length - 2} more` : ''), 'xp');
    const b = $('.xp>i'); if (b) { b.classList.remove('bump'); void b.offsetWidth; b.classList.add('bump'); }
  }
  evs.filter(e => e.t === 'info').forEach(e => toast(e.text));
  evs.filter(e => e.t === 'badge').forEach(e => { toast(`${e.emoji} ${e.name}`, e.desc, 'badge'); confetti(); });
  const lu = evs.find(e => e.t === 'levelup');
  if (lu) {
    confetti();
    modal(`<div class="c lvl"><div class="xs mut up">LEVEL UP</div><div class="bignum">${lu.level}</div><div class="lvl-emo">${esc(lu.emoji || '')}</div><h2>${esc(lu.rank)}</h2>${lu.new_title ? '<div class="pill mt8">New title unlocked</div>' : ''}<p class="sm mut mt12">Another vote for the person you're becoming.</p><button class="btn-p btn-xl mt12" data-act="closeModal">Keep going</button></div>`);
  }
}
function modal(html, lock) {
  const m = $('#modal'); m.innerHTML = `<div role="dialog">${html}</div>`;
  m.classList.toggle('lock', !!lock); m.classList.remove('hidden'); document.body.classList.add('noscroll');
}
function closeModal() {
  const m = $('#modal'); m.classList.add('hidden'); m.classList.remove('lock'); m.innerHTML = '';
  if (!S.fs) document.body.classList.remove('noscroll');
}
const modalOpen = () => !$('#modal').classList.contains('hidden');

/* ---------- svg helpers ---------- */
function bars(vals, color, h = 70) {
  const mx = Math.max(...vals, 1), w = 100 / vals.length;
  return `<svg class="chart" viewBox="0 0 100 ${h}" preserveAspectRatio="none">` + vals.map((v, i) => { const bh = Math.max(v / mx * (h - 2), v ? 2 : 1); return `<rect x="${i * w + w * .15}" y="${h - bh}" width="${w * .7}" height="${bh}" rx="1" fill="${color}" opacity="${v ? 1 : .18}"/>`; }).join('') + '</svg>';
}
function lines(series, h = 60) {
  const all = series.flatMap(s => s.v.filter(x => x != null)); const mx = Math.max(...all, 1);
  return `<svg class="chart" viewBox="0 0 100 ${h}" preserveAspectRatio="none">` + series.map(s => {
    const pts = s.v.map((x, i) => x == null ? null : `${s.v.length > 1 ? i / (s.v.length - 1) * 100 : 50},${h - 3 - x / mx * (h - 8)}`).filter(Boolean).join(' ');
    return `<polyline points="${pts}" fill="none" stroke="${s.c}" stroke-width="${s.w || 2}" stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke" ${s.d ? 'stroke-dasharray="4 4"' : ''}/>`;
  }).join('') + '</svg>';
}

/* ---------- small ui pieces ---------- */
const lbl = (t, right = '') => `<div class="lbl"><span>${t}</span>${right ? `<span class="rt">${right}</span>` : ''}</div>`;
const seg = (items, cur, act) => `<div class="seg">${items.map(([k, n]) => `<button class="${cur === k ? 'on' : ''}" data-act="${act}" data-v="${esc(k)}">${n}</button>`).join('')}</div>`;
const ago = ts => { const s = (Date.now() - new Date(ts).getTime()) / 1000; if (s < 90) return 'now'; if (s < 3600) return Math.floor(s / 60) + 'm'; if (s < 86400) return Math.floor(s / 3600) + 'h'; return Math.floor(s / 86400) + 'd'; };
const avatar = (emo, col, cls = '') => `<div class="av ${cls}" style="background:${esc(col)}22;border-color:${esc(col)}">${esc(emo)}</div>`;

/* ---------- auth ---------- */
function renderAuth() {
  const reg = S.authMode === 'register';
  $('#app').innerHTML = `<div class="auth"><div class="logo">RAGDAMAXING</div>
  <p class="tag">Outwork the old you. Track it, prove it, together.</p>
  <div class="card col">
    <input id="a_user" placeholder="Username" autocapitalize="off" autocomplete="username" spellcheck="false">
    <input id="a_pin" type="password" placeholder="PIN or password (4+ characters)" autocomplete="${reg ? 'new-password' : 'current-password'}">
    ${reg ? `<input id="a_code" placeholder="Crew invite code" autocapitalize="characters" spellcheck="false"><div class="mut xs c">or start your own</div><input id="a_cname" placeholder="New crew name">` : ''}
    <button class="btn-p btn-xl" data-act="${reg ? 'register' : 'login'}">${reg ? 'Join the grind' : 'Log in'}</button>
    <button class="btn-text" data-act="authMode">${reg ? 'I already have an account' : 'New here? Create an account'}</button>
  </div></div>`;
  closeModal(); $('.nav')?.remove(); $('.fab')?.remove();
}

/* ---------- navigation + rendering ---------- */
const TABS = [['today', 'today', 'Today'], ['crew', 'crew', 'Crew'], ['chat', 'chat', 'Chat'], ['study', 'study', 'Study'], ['reflect', 'reflect', 'Reflect'], ['me', 'me', 'Me']];
let _navSeq = 0;
async function loadTab(tab) {
  if (tab === 'today') setToday(await api('today'));
  else if (tab === 'crew') S.crew = await api('crew');
  else if (tab === 'study') {
    const [syl, te] = await Promise.all([api('syllabus'), api('tests')]); S.syl = syl; S.tests = te;
    if (!S.ins) S.ins = await api('insights');
  }
  else if (tab === 'reflect') { const [r, w] = await Promise.all([api('reflect'), api('weekly')]); S.refl = r; S.weekly = w; }
  else if (tab === 'me') S.ins = await api('insights');
  else if (tab === 'chat') await chatLoadThreads();
}
async function go(tab) {
  const changed = tab !== S.tab, seq = ++_navSeq;
  S.tab = tab; chatStop(); if (tab === 'chat') CH.open = null;
  try { await loadTab(tab); } catch (e) { if (e.message === 'login') return; }
  if (seq !== _navSeq) return;
  render(); if (changed) window.scrollTo(0, 0);
}
/* reload the current tab's data and redraw WITHOUT jumping the page back to the top */
async function refresh() {
  const seq = ++_navSeq;
  try { await loadTab(S.tab); } catch (e) { if (e.message === 'login') return; }
  if (seq !== _navSeq) return;
  render();
}
function ensureNav() {
  let nav = $('.nav');
  if (!nav) {
    nav = document.createElement('nav'); nav.className = 'nav';
    nav.innerHTML = '<div>' + TABS.map(t => `<button data-act="tab" data-v="${t[0]}">${ic(t[1], 21)}<span>${t[2]}</span></button>`).join('') + '</div>';
    document.body.appendChild(nav);
  }
  $$('.nav button').forEach(b => b.classList.toggle('on', b.dataset.v === S.tab));
  chatBadge();
}
function render() {
  if (!S.user) return renderAuth();
  const y = window.scrollY, openK = $$('details[open][data-k]').map(d => d.dataset.k);
  const views = { today: vToday, crew: vCrew, chat: vChat, study: vStudy, reflect: vReflect, me: vMe };
  let v;
  try { v = views[S.tab](); }
  catch (e) { console.error(e); v = '<section class="card c"><div class="b">This tab hit a snag.</div><p class="sm mut">Reload to try again.</p><button class="btn-s" data-act="reload">Reload</button></section>'; }
  $('#app').innerHTML = v;
  $('.fab')?.remove();
  if (S.tab === 'today' && S.today && !S.fs) { const f = document.createElement('button'); f.className = 'fab'; f.dataset.act = 'urge'; f.textContent = "I'm tempted"; document.body.appendChild(f); }
  openK.forEach(k => { const d = document.querySelector(`details[data-k="${k}"]`); if (d) d.open = true; });
  ensureNav();
  if (S.tab === 'chat') chatAfterRender();
  if (S.tab === 'today') startTick(); else stopTick();
  if (S.tab !== 'chat') window.scrollTo(0, y);
}

/* ---------- boot ---------- */
async function boot() {
  try { const me = await api('me'); S.user = me.user; await go(S.tab); if (!S.user.onboarded) onboard(); }
  catch (e) { if (!S.user) renderAuth(); }
}
/* ---------- timer engine ---------- */
function setToday(t) {
  S.today = t; const n = Date.now();
  S.t0 = t.timer ? n - t.timer.elapsed * 1000 : 0;
  S.p0 = t.pomo ? n - t.pomo.elapsed * 1000 : 0;
}
/* single source of truth for "what is the clock doing right now" (null = nothing running) */
function timerState() {
  const T = S.today; if (!T) return null;
  const tm = T.timer, po = T.pomo, n = Date.now();
  if (tm) {
    const sw = tm.mode === 'stopwatch', el = (n - S.t0) / 1000, tot = sw ? 0 : tm.target * 60;
    return { kind: sw ? 'stopwatch' : 'work', subject: tm.subject, el, tot, rem: tot - el, sw, tm, po, key: 't' + tm.started };
  }
  if (po && po.phase === 'break') {
    const el = (n - S.p0) / 1000;
    return { kind: 'break', subject: po.subject, el, tot: po.phase_len, rem: po.phase_len - el, sw: false, tm: null, po, key: 'b' + po.block };
  }
  return null;
}
const msStep = mins => MS.filter(m => mins >= m[0]).length;
function startTick() { stopTick(); tickOnce(); }
function stopTick() { clearTimeout(S._tt); S._tt = null; }
function tickOnce() {
  clearTimeout(S._tt);
  if (!S.user || !S.today) return;
  if (S.tab !== 'today' && !S.fs) return;
  const st = timerState();
  if (!st) { if (S.fs) { exitFullscreenFocus(true); if (S.tab === 'today') render(); } return; }
  paintTimer(st);
  S._tt = setTimeout(tickOnce, S.fs ? 250 : 500);
}
function timerMsg(st, mins) {
  const po = st.po;
  if (st.kind === 'break') return st.rem > 0 ? ['brk', 'Step away from the screen. Water, stretch, eyes off.'] : ['brk0', 'Break over. Next block is starting…'];
  if (st.kind === 'stopwatch') {
    const step = msStep(mins), hit = MS[step - 1], nx = MS[step];
    if (!step) return ['sw0', `First milestone at 25 min (+${MS[0][1]} XP). Zero distractions to 25 = +20 XP.`];
    return ['sw' + step, `<b>${hit[2]}</b> reached, +${hit[1]} XP banked.${nx ? ` Next: ${nx[0]} min.` : ' You are at the cap. Log it.'}`];
  }
  if (st.rem > 0) return ['run', po ? 'Stay on this one. Your break is next.' : 'Phone away. One tab. Pen in hand.'];
  return po ? ['done', 'Block complete. Logging it and starting your break…']
    : ['done', 'Block complete. Log it, or <button class="btn-s" data-act="extend">Keep going +20 min</button>'];
}
function paintTimer(st) {
  const mins = Math.floor(st.el / 60);
  if (S.beepKey !== st.key) { S.beepKey = st.key; S.beeped = !st.sw && st.rem <= 0; S.msStep = st.sw ? msStep(mins) : 0; S.msgKey = ''; }
  if (st.sw) { const step = msStep(mins); if (step > S.msStep) { S.msStep = step; beep(); } }
  else if (st.rem <= 0) {
    if (!S.beeped) { S.beeped = true; beep(); }
    if (st.po && st.rem <= -1) syncToday();     // pomodoro: the server logs the block and starts the break / next block
  }
  const time = st.sw ? clk(st.el) : st.kind === 'break' ? clk(Math.max(st.rem, 0)) : st.rem >= 0 ? clk(st.rem) : '+' + clk(-st.rem);
  const frac = st.sw ? (st.el % 3600) / 3600 : clamp(st.el / st.tot, 0, 1);
  const c = $('#clock'); if (c) c.textContent = time;
  const rg = $('#ringc'); if (rg) rg.style.strokeDashoffset = RING * (1 - frac);
  const sub = st.kind === 'stopwatch' ? `${mins} min · ${mins * XPM} XP banked`
    : st.kind === 'break' ? `Block ${st.po.block} of ${st.po.blocks} done`
      : st.rem < 0 ? 'Overtime · bonus focus' : `${mins} min in${st.po ? ` · block ${st.po.block} of ${st.po.blocks}` : ''}`;
  const ts = $('#tsub'); if (ts) ts.textContent = sub;
  const [mk, mh] = timerMsg(st, mins);
  if (mk !== S.msgKey) { S.msgKey = mk; const tmg = $('#tmsg'); if (tmg) tmg.innerHTML = mh; }
  if (S.fs) paintFS(st, time, frac, mins, mk, mh);
}
async function syncToday() {
  if (Date.now() - S.syncing < 4000) return;
  S.syncing = Date.now();
  try {
    setToday(await api('today'));
    if (S.fs) { const st = timerState(); if (!st) exitFullscreenFocus(true); else { S.fsKey = ''; } }
    if (S.tab === 'today') render();
  } catch (e) { }
}
async function finishTimer(body) {
  const r = await api('timer/stop', body || {});
  if (r.discarded) { /* nothing to log */ }
  else if (r.too_short) toast('Under 5 minutes, not logged', 'Even 5 counts. Go again.');
  else { if (r.capped) toast('Stopwatch capped at 4h', 'Time past that does not count.'); if (r.minutes >= 25) beep(); }
  S.beepKey = null;
  try { setToday(await api('today')); } catch (e) { }
  exitFullscreenFocus(true);
  render();
  return r;
}

/* ---------- fullscreen focus mode ---------- */
const FS_CLOCKS = [['digital', 'Digital'], ['analog', 'Dial'], ['minimal', 'Minimal'], ['progress', 'Blocks'], ['orbit', 'Orbit']];
let fsWake = null;
async function requestWakeLock() {
  try { if ('wakeLock' in navigator && !fsWake && S.fs) { fsWake = await navigator.wakeLock.request('screen'); fsWake.addEventListener('release', () => { fsWake = null; }); } } catch (e) { fsWake = null; }
}
function releaseWakeLock() { try { if (fsWake) fsWake.release().catch(() => { }); } catch (e) { } fsWake = null; }

function enterFullscreenFocus() {
  const st = timerState(); if (!st) return;
  if (!FS_CLOCKS.some(c => c[0] === S.fsClock)) S.fsClock = 'digital';
  S.fs = true; S.fsKey = ''; S.fsClockKey = '';
  $('.fab')?.remove(); document.body.classList.add('noscroll');
  let o = $('#fs'); if (o) o.remove();
  o = document.createElement('div'); o.id = 'fs'; o.className = 'fs';
  o.innerHTML = `<div class="fs-top"><div class="fs-sub"><i class="sd" id="fs-dot"></i><span id="fs-subj"></span><span class="pill" id="fs-blk"></span></div>
    <div class="fs-style"><button data-act="fsClockPrev" aria-label="Previous clock style">${ic('left', 16)}</button><span id="fs-cname"></span><button data-act="fsClockNext" aria-label="Next clock style">${ic('right', 16)}</button></div>
    <button class="fs-x" data-act="exitFullscreenFocus" aria-label="Exit focus mode">${ic('x', 20)}</button></div>
    <div class="fs-center" id="fs-clock"></div><div class="fs-next" id="fs-next"></div><div class="fs-bot" id="fs-bot"></div>`;
  document.body.appendChild(o);
  S.fsNative = false;
  try { const p = o.requestFullscreen && o.requestFullscreen({ navigationUI: 'hide' }); if (p && p.then) p.then(() => { S.fsNative = true; }).catch(() => { }); } catch (e) { }
  const wake = () => { o.classList.remove('idle'); clearTimeout(S._fsHide); S._fsHide = setTimeout(() => o.classList.add('idle'), 5000); };
  ['pointermove', 'pointerdown', 'keydown'].forEach(ev => o.addEventListener(ev, wake)); wake();
  let sx = null; const ca = $('#fs-clock');
  ca.addEventListener('touchstart', e => { sx = e.touches[0].clientX; }, { passive: true });
  ca.addEventListener('touchend', e => { if (sx === null) return; const dx = e.changedTouches[0].clientX - sx; sx = null; if (Math.abs(dx) > 60) fsStep(dx < 0 ? 1 : -1); }, { passive: true });
  requestWakeLock(); startTick();
}
function exitFullscreenFocus(noRender) {
  if (!S.fs) return;
  S.fs = false; clearTimeout(S._fsHide); releaseWakeLock();
  $('#fs')?.remove(); if (!modalOpen()) document.body.classList.remove('noscroll');
  if (document.fullscreenElement) { try { document.exitFullscreen().catch(() => { }); } catch (e) { } }
  if (noRender !== true && S.user && S.tab === 'today') render();
}
function fsStep(d) {
  const i = FS_CLOCKS.findIndex(c => c[0] === S.fsClock);
  S.fsClock = FS_CLOCKS[(i + d + FS_CLOCKS.length) % FS_CLOCKS.length][0]; PREF.set('clock', S.fsClock); S.fsClockKey = '';
  const st = timerState(); if (st) tickOnce();
}
function fsDial() {
  let t = ''; for (let i = 0; i < 60; i++) { const a = i * 6 * Math.PI / 180, r1 = i % 5 ? 112 : 104, s = Math.sin(a), c = -Math.cos(a); t += `<line x1="${(140 + 118 * s).toFixed(1)}" y1="${(140 + 118 * c).toFixed(1)}" x2="${(140 + r1 * s).toFixed(1)}" y2="${(140 + r1 * c).toFixed(1)}"/>`; }
  return t;
}
function fsBuildClock(type, st) {
  const lab = '<div class="fs-label" id="fs-label"></div>';
  if (type === 'analog') return `<div class="fsc analog"><svg viewBox="0 0 280 280" class="fs-svg"><g class="ticks">${fsDial()}</g><circle class="trk" cx="140" cy="140" r="92" fill="none"/><circle id="fs-arc" class="arc" cx="140" cy="140" r="92" fill="none" stroke-dasharray="578.1" stroke-dashoffset="578.1" transform="rotate(-90 140 140)"/><line id="fs-hand" class="hand" x1="140" y1="140" x2="140" y2="58" transform="rotate(0 140 140)"/><circle cx="140" cy="140" r="5" class="pivot"/></svg><div class="fs-time" id="fs-time"></div>${lab}</div>`;
  if (type === 'minimal') return `<div class="fsc minimal"><div class="fs-time" id="fs-time"></div><div class="fs-line"><i id="fs-bar"></i></div>${lab}</div>`;
  if (type === 'progress') {
    const n = st.sw ? 10 : Math.max(1, Math.min(24, Math.ceil(st.tot / 1500)));
    return `<div class="fsc progress"><div class="fs-time" id="fs-time"></div><div class="fs-blocks" id="fs-blocks">${'<i></i>'.repeat(n)}</div>${lab}</div>`;
  }
  if (type === 'orbit') return `<div class="fsc orbit"><svg viewBox="0 0 300 300" class="fs-svg"><circle class="trk dash" cx="150" cy="150" r="130" fill="none"/><circle id="fs-arc" class="arc" cx="150" cy="150" r="130" fill="none" stroke-dasharray="816.8" stroke-dashoffset="816.8" transform="rotate(-90 150 150)"/><g id="fs-orb" transform="rotate(0 150 150)"><circle class="orb" cx="150" cy="20" r="7"/></g><circle id="fs-pulse" class="pulse" cx="150" cy="150" r="100" fill="none"/></svg><div class="fs-time" id="fs-time"></div>${lab}</div>`;
  return `<div class="fsc digital"><div class="fs-time big" id="fs-time"></div>${lab}</div>`;
}
function fsBotHtml(st) {
  const po = st.po;
  if (st.kind === 'break') return '<button class="fs-btn" data-act="skipBreak">Skip break</button><button class="fs-btn" data-act="endPlan">End plan</button>';
  return `<button class="fs-btn" data-act="distract">Lost focus (<span id="fs-dcount">${st.tm.distractions}</span>)</button><button class="fs-btn primary" data-act="logAndExitFocus">${po ? 'End plan & log' : 'Log & exit'}</button>`;
}
function paintFS(st, time, frac, mins, mk, mh) {
  const root = $('#fs'); if (!root) return;
  const col = SCOL[st.subject] || '#9a9aa8';
  root.style.setProperty('--sc', col); root.dataset.kind = st.kind; root.dataset.over = (!st.sw && st.rem < 0 && st.kind !== 'break') ? '1' : '0';
  const setT = (id, v) => { const e = $(id); if (e && e.textContent !== v) e.textContent = v; };
  setT('#fs-subj', st.kind === 'break' ? 'Break' : st.subject);
  setT('#fs-blk', st.po ? `Block ${st.po.block}/${st.po.blocks}` : '');
  const blk = $('#fs-blk'); if (blk) blk.style.display = st.po ? '' : 'none';
  setT('#fs-cname', (FS_CLOCKS.find(c => c[0] === S.fsClock) || FS_CLOCKS[0])[1]);
  if (S.fsClockKey !== S.fsClock + st.kind + st.key) { S.fsClockKey = S.fsClock + st.kind + st.key; $('#fs-clock').innerHTML = fsBuildClock(S.fsClock, st); root.dataset.clock = S.fsClock; }
  if (S.fsKey !== st.key + st.kind) { S.fsKey = st.key + st.kind; $('#fs-bot').innerHTML = fsBotHtml(st); }
  setT('#fs-time', time);
  const label = st.kind === 'stopwatch' ? `Stopwatch · ${mins} min · ${mins * XPM} XP banked`
    : st.kind === 'break' ? `${st.po.is_long ? 'Long break' : 'Short break'} · next block ${st.po.next_len} min`
      : st.rem < 0 ? 'Overtime' : `${mins} of ${st.tm.target} min`;
  setT('#fs-label', label);
  const arc = $('#fs-arc'); if (arc) { const C = +arc.getAttribute('stroke-dasharray'); arc.style.strokeDashoffset = C * (1 - frac); }
  const hand = $('#fs-hand'); if (hand) hand.setAttribute('transform', `rotate(${(frac * 360).toFixed(2)} 140 140)`);
  const orb = $('#fs-orb'); if (orb) orb.setAttribute('transform', `rotate(${(frac * 360).toFixed(2)} 150 150)`);
  const pu = $('#fs-pulse'); if (pu) pu.setAttribute('r', (60 + 40 * (st.sw ? (st.el % 60) / 60 : 1 - frac)).toFixed(1));
  const bar = $('#fs-bar'); if (bar) bar.style.width = (frac * 100).toFixed(2) + '%';
  const bl = $('#fs-blocks'); if (bl) { const done = Math.floor(st.el / 1500); Array.from(bl.children).forEach((b, i) => { b.className = i < done ? 'on' : i === done ? 'cur' : ''; if (i === done && st.tot) b.style.setProperty('--p', clamp((st.el - i * 1500) / Math.min(1500, st.tot - i * 1500 || 1500), 0, 1)); }); }
  let nx = '';
  if (st.kind === 'break') nx = `${st.po.done} of ${st.po.total} min done · ${fm(st.po.total - st.po.done)} to go`;
  else {
    const lim = st.sw ? 241 : st.tot / 60, next = MS.find(m => mins < m[0] && m[0] <= lim);
    nx = next ? `Next · ${next[2]} at ${next[0]} min · +${next[1]} XP` : (st.sw ? 'Every milestone reached. Log it when you are done.' : 'Block target reached');
  }
  setT('#fs-next', nx);
}

/* ---------- pomodoro helpers (mirror the server so the preview is honest) ---------- */
function pomoPlan(total, work) { const out = []; let rem = total; while (rem >= 5) { const n = rem - work < 5 ? rem : work; out.push(n); rem -= n; } return out; }
function pomoNorm(c) { return { total: clamp(Math.round(+c.total) || 120, 30, 720), work: clamp(Math.round(+c.work) || 50, 15, 120), brk: clamp(Math.round(+c.brk) || 10, 3, 30) }; }
function pomoCalc(c) {
  const plan = pomoPlan(c.total, c.work), every = c.work <= 30 ? 4 : 3, long = Math.max(c.brk * 2, 15);
  let wall = c.total; for (let i = 1; i < plan.length; i++) wall += (i % every === 0 ? long : c.brk);
  return { plan, every, long, wall };
}
function pomoPrev() { const c = pomoNorm(S.pomoCfg), p = pomoCalc(c); return `${p.plan.length} block${p.plan.length === 1 ? '' : 's'} · ${c.work} min work · ${c.brk} min break (${p.long} min every ${p.every}) · about ${fm(p.wall)} on the clock`; }
/* ---------- TODAY ---------- */
function focusIdle() {
  const mode = S.pickMode, sub = S.pickSub;
  let body, label;
  if (mode === 'timer') { body = `<div class="xs mut mb4">Length</div>${seg([[25, '25 min'], [50, '50 min'], [90, '90 min']], S.pickDur, 'pickDur')}`; label = `Start ${sub} · ${S.pickDur} min`; }
  else if (mode === 'stopwatch') { body = `<p class="sm mut">No countdown. Go as long as you can and finish when you're done. ${XPM} XP per minute, with milestone bonuses at 25, 50, 90, 120, 180 and 240 min. Counts as verified.</p>`; label = `Start ${sub} · stopwatch`; }
  else {
    const c = S.pomoCfg;
    body = `<div class="grid3"><div><label>Total (min)</label><input id="pomo_total" type="number" inputmode="numeric" value="${c.total}" min="30" max="720" step="15"></div>
      <div><label>Work (min)</label><input id="pomo_work" type="number" inputmode="numeric" value="${c.work}" min="15" max="120" step="5"></div>
      <div><label>Break (min)</label><input id="pomo_brk" type="number" inputmode="numeric" value="${c.brk}" min="3" max="30" step="1"></div></div>
      <div class="sm mut mt8" id="pomo_prev">${pomoPrev()}</div>`;
    label = `Start pomodoro · ${fm(pomoNorm(c).total)}`;
  }
  return `<section class="card focus">${lbl('Focus')}
    <div class="chips">${SUBS.map(s => `<button class="chip ${sub === s ? 'on' : ''}" data-act="pickSub" data-v="${s}"><i class="sd" style="background:${SCOL[s]}"></i>${s}</button>`).join('')}</div>
    <div class="mt12">${seg([['timer', 'Timer'], ['stopwatch', 'Stopwatch'], ['pomo', 'Pomodoro']], mode, 'pickMode')}</div>
    <div class="mt12">${body}</div>
    <button class="btn-p btn-xl mt12" data-act="${mode === 'pomo' ? 'startPomo' : 'startTimer'}">${esc(label)}</button>
    <button class="btn-text" data-act="start5">Can't start? Just 5 minutes. That's the deal.</button>
    <details data-k="manual"><summary>Studied offline? Log it (half XP)</summary>
      <div class="row g8 mt8"><select id="mf_s">${SUBS.map(s => `<option ${s === sub ? 'selected' : ''}>${s}</option>`).join('')}</select><input id="mf_m" type="number" inputmode="numeric" placeholder="min" style="width:96px"><button data-act="manual">Log</button></div></details></section>`;
}
function ringSvg(col) {
  return `<div class="ring"><svg width="210" height="210" viewBox="0 0 210 210"><circle class="rt" cx="105" cy="105" r="94" fill="none" stroke-width="10"/><circle id="ringc" class="rp" cx="105" cy="105" r="94" fill="none" stroke="${col}" stroke-width="10" stroke-linecap="round" stroke-dasharray="${RING}" stroke-dashoffset="${RING}"/></svg>
    <div class="in"><div class="clock" id="clock">--:--</div><div class="xs mut" id="tsub"></div></div></div>`;
}
function focusRun(st) {
  const tm = st.tm, po = st.po, col = SCOL[st.subject] || '#9a9aa8';
  const tag = st.sw ? 'Stopwatch' : po ? `Block ${po.block} of ${po.blocks}` : `${tm.target} min block`;
  return `<section class="card focus run">
    <div class="row between"><div class="row g8"><i class="sd" style="background:${col}"></i><b>${esc(st.subject)}</b></div><span class="pill">${tag}</span></div>
    ${ringSvg(col)}
    ${po ? `<div class="xs mut c">${fm(po.done)} of ${fm(po.total)} done · long break every ${po.every} blocks</div>` : ''}
    <div class="tmsg" id="tmsg"></div>
    <div class="row g8 center mt8"><button class="btn-s" data-act="distract">Lost focus · <span id="dcount">${tm.distractions}</span></button><button class="btn-s" data-act="enterFullscreenFocus">${ic('expand', 15)} Fullscreen</button></div>
    <div class="row g8 mt12"><button class="btn-g btn-lg grow" data-act="stopTimer">${po ? 'End plan & log' : 'Finish & log'}</button><button class="btn-d btn-lg" data-act="discard">Discard</button></div></section>`;
}
function focusBreak(st) {
  const po = st.po;
  return `<section class="card focus run brk">
    <div class="row between"><b>${po.is_long ? 'Long break' : 'Short break'}</b><span class="pill">Block ${po.block} of ${po.blocks} done</span></div>
    ${ringSvg('#3dd6a0')}
    <div class="xs mut c">${fm(po.done)} of ${fm(po.total)} done · next block ${po.next_len} min of ${esc(po.subject)}</div>
    <div class="tmsg" id="tmsg"></div>
    <div class="row g8 center mt8"><button class="btn-s" data-act="enterFullscreenFocus">${ic('expand', 15)} Fullscreen</button></div>
    <div class="row g8 mt12"><button class="btn-p btn-lg grow" data-act="skipBreak">Skip break</button><button class="btn-d btn-lg" data-act="endPlan">End plan</button></div></section>`;
}
function vToday() {
  const T = S.today, L = T.level, sv = T.streak, u = T.user, floor = T.daily_min, m = T.today.total;
  let h = `<section class="card hero">
    <div class="row between"><div class="row g12">${avatar(u.emoji, u.color, 'lg')}<div><div class="h2">${esc(u.display)}</div><div class="xs mut">Level ${L.level} · ${esc(L.emoji)} ${esc(L.rank)}</div></div></div>
      <div class="streak ${sv.at_risk ? 'risk' : ''}"><span class="sn">${ic('flame', 20)}${sv.now}</span><span class="xs mut">${sv.at_risk ? 'at risk' : 'day streak'}</span></div></div>
    <div class="bar xp mt12"><i style="width:${L.pct}%"></i></div>
    <div class="row between xs mut mt4"><span>${(L.xp - L.lo).toLocaleString()} / ${(L.hi - L.lo).toLocaleString()} XP to level ${L.level + 1}</span><span>+${T.xp_today} today</span></div>
    <div class="row between xs mut mt4"><span>${L.next_rank ? `Next title · Lv ${L.next_at}: ${esc(L.next_emoji)} ${esc(L.next_rank)}` : 'Top title reached'}</span><span class="row g4">${ic('shield', 13)} ${sv.freezes} freeze${sv.freezes === 1 ? '' : 's'}</span></div>
    ${u.identity ? `<div class="quote">I am ${esc(u.identity)}</div>` : ''}
    ${T.exams.length ? `<div class="chips mt8">${T.exams.map(e => `<span class="pill">${esc(e.name)} · ${e.days_left}d</span>`).join('')}</div>` : ''}</section>`;
  T.banners.forEach(b => h += `<div class="note ${esc(b.kind)}">${esc(b.text)}</div>`);

  /* competition pulse: rival gap, daily boss, who is live */
  let p = '';
  if (T.rival) {
    const ahead = !T.rival.dir;
    p += `<div class="prow"><span class="pl">${ahead ? 'Chasing' : 'Defending'}</span><span><b>${esc(T.rival.name)}</b> ${esc(T.rival.emoji)} is <b>${T.rival.gap} XP</b> ${ahead ? 'ahead of you' : 'behind you'} this week.${ahead ? ' One deep block closes the gap.' : ''}</span></div>`;
  }
  if (T.boss) {
    const b = T.boss, pct = Math.round(clamp(b.actual / Math.max(b.target, 1) * 100, 0, 100));
    const stt = b.passed === true ? ['Defeated', 'g'] : b.passed === false ? ['Failed', 'd'] : ['Active', ''];
    p += `<div class="prow col"><div class="row between"><span class="pl">Daily boss</span><span class="pill ${stt[1]}">${stt[0]}</span></div>
      <div class="bar mt4 ${b.passed === true ? 'g' : ''}"><i style="width:${pct}%"></i></div>
      <div class="row between xs mut mt4"><span>${fm(b.actual)} of ${fm(b.target)} crew focus today</span><span>${pct}%</span></div></div>`;
  }
  if (T.live.length) p += `<div class="prow"><span class="dot live"></span><span><b>${T.live.map(l => `${esc(l.display)} (${esc(l.subject)} · ${fm(l.elapsed / 60)})`).join(', ')}</b> ${T.live.length > 1 ? 'are' : 'is'} locked in right now.${timerState() ? '' : ' Join them.'}</span></div>`;
  if (p) h += `<section class="card pulse">${p}</section>`;

  const st = timerState();
  h += st ? (st.kind === 'break' ? focusBreak(st) : focusRun(st)) : focusIdle();

  /* today's progress */
  const stretch = Math.max(T.stretch_min, floor * 2);
  h += `<section class="card">${lbl('Today', `<b class="num">${fm(m)}</b>`)}
    <div class="bar ${m >= floor ? 'g' : ''}"><i style="width:${Math.min(m / stretch * 100, 100)}%"></i><span class="tick" style="left:${floor / stretch * 100}%"></span></div>
    <div class="row between xs mut mt4"><span>${sv.qualified ? 'Floor hit. Streak is safe.' : `Floor ${floor} min · ${Math.max(floor - m, 0)} to go`}</span><span>Old-you bar ${fm(T.stretch_min)}</span></div>
    ${Object.keys(T.today.sub).length ? `<div class="chips mt8">${Object.entries(T.today.sub).map(([s, mm]) => `<span class="pill" style="background:${SCOL[s]}22;color:${SCOL[s]}">${esc(s)} ${fm(mm)}</span>`).join('')}</div>` : ''}
    <div class="xs mut mt8">A streak day needs ${floor} min, at least half of it on the timer.</div>
    ${T.chest.available ? `<button class="btn-p btn-xl mt12" data-act="chest">Open today's chest</button>` : T.chest.opened ? `<div class="xs mut mt8">Today's chest: <b class="tx">${esc(T.chest.reward)}</b></div>` : ''}
    ${T.sessions.length ? `<div class="lbl2">Blocks today</div>${T.sessions.map(s => `<div class="q"><i class="sd" style="background:${SCOL[s.subject]}"></i><div class="grow">${esc(s.subject)}</div><b class="num">${fm(s.minutes)}</b><span class="xs mut w64">${s.kind === 'timer' ? 'Verified' : 'Manual'}</span>${s.kind === 'manual' ? `<button class="btn-s ico" data-act="delFocus" data-id="${s.id}" aria-label="Remove">${ic('x', 14)}</button>` : ''}</div>`).join('')}` : ''}</section>`;

  /* quests */
  h += `<section class="card">${lbl('Daily quests', `${T.quests.filter(q => q.done).length}/${T.quests.length}`)}${T.quests.map(q => `<div class="q"><div class="chk ${q.done ? 'on' : ''}">${q.done ? ic('check', 14) : ''}</div><div class="grow">${esc(q.text)}<div class="bar thin mt4"><i style="width:${Math.min(q.prog / Math.max(q.goal, 1) * 100, 100)}%"></i></div></div><span class="pill">+${q.xp}</span></div>`).join('')}</section>`;

  /* promises */
  h += `<section class="card">${lbl("Today's promises")}${T.plan.length ? T.plan.map(pl => `<div class="q"><button class="chk ${pl.done ? 'on' : ''}" data-act="togglePlan" data-id="${pl.id}" aria-label="Toggle">${pl.done ? ic('check', 14) : ''}</button><div class="grow ${pl.done ? 'mut' : ''}">${esc(pl.text)}${pl.cue ? `<div class="xs mut">${esc(pl.cue)}</div>` : ''}</div><button class="btn-s ico" data-act="delPlan" data-id="${pl.id}" aria-label="Delete">${ic('x', 14)}</button></div>`).join('') : '<div class="mut sm">Nothing planned. A plan made at night beats willpower in the morning.</div>'}
    <details data-k="plan"><summary>Add a promise</summary><input id="pl_t" placeholder="e.g. Integration Ex 7.2 Q1-10" maxlength="120"><div style="height:6px"></div><input id="pl_c" placeholder="When and where? e.g. 6 PM, desk, phone in another room" maxlength="120"><div class="row g8 mt8"><button class="grow" data-act="addPlan" data-v="today">Add for today</button><button class="grow" data-act="addPlan" data-v="tomorrow">Add for tomorrow</button></div></details>
    ${T.plan_tomorrow.length ? `<div class="xs mut mt8">Tomorrow: ${T.plan_tomorrow.map(x => esc(x.text)).join(' · ')}</div>` : ''}</section>`;
  if (T.due.length) h += `<section class="card">${lbl(`Revise now (${T.due.length})`, '<button class="btn-s" data-act="tab" data-v="study" data-sub="revise">Open</button>')}${T.due.slice(0, 3).map(d => `<div class="q"><div class="grow"><b>${esc(d.name)}</b> <span class="xs mut">${esc(d.subject)}</span></div></div>`).join('')}</section>`;
  h += `<section class="card">${lbl('Body and discipline')}<div class="chips">${T.habit_defs.map(x => `<button class="chip ${T.habits.includes(x.id) ? 'on' : ''}" data-act="habit" data-id="${x.id}">${esc(x.emoji)} ${esc(x.name)} <span class="xs op">+${x.xp}</span></button>`).join('')}</div></section>`;
  return h;
}

/* ---------- CREW ---------- */
const PK = { week: ['week_xp', 'week_min'], month: ['month_xp', 'month_min'], all: ['all_xp', 'all_min'] };
const pv = m => ({ xp: m[PK[S.crewPeriod][0]], min: m[PK[S.crewPeriod][1]] });
const crewSorted = C => C.members.slice().sort((a, b) => pv(b).xp - pv(a).xp);
function vCrew() {
  const C = S.crew;
  if (!C.crew) return `<section class="card"><h2>No crew yet</h2><p class="mut sm">Competition works. Join your friends.</p><input id="cj" placeholder="Invite code" autocapitalize="characters"><button class="btn-p btn-xl mt8" data-act="joinCrew">Join crew</button><div class="mut xs c" style="margin:12px 0">or</div><input id="cn" placeholder="New crew name"><button class="btn-xl mt8" data-act="createCrew">Create crew</button></section>`;
  const sorted = crewSorted(C), meI = Math.max(sorted.findIndex(m => m.me), 0), me = sorted[meI], top = Math.max(...sorted.map(m => pv(m).xp), 1);
  const gap = meI > 0 ? `${pv(sorted[meI - 1]).xp - pv(me).xp} XP behind <b>${esc(sorted[meI - 1].display)}</b>. One deep block closes it.`
    : sorted.length > 1 ? `Leading by ${pv(me).xp - pv(sorted[1]).xp} XP over <b>${esc(sorted[1].display)}</b>. Don't coast.` : 'Invite friends to start competing.';
  const per = { week: 'This week', month: 'This month', all: 'All time' }[S.crewPeriod];
  let h = `<section class="card hero"><div class="row between"><div><h2>${esc(C.crew.name)}</h2><div class="xs mut mt4">Invite code <button class="code" data-act="copy" data-v="${esc(C.crew.code)}">${esc(C.crew.code)}</button></div></div>
    <div class="c"><div class="xs mut">${per} rank</div><div class="bignum sm">#${meI + 1}<span class="mut of"> / ${sorted.length}</span></div></div></div>
    <div class="sm mt12">${gap}</div>
    ${C.crown ? `<div class="crownline">${ic('crown', 15)}<span><b>${esc(C.crown.name)}</b> ${esc(C.crown.emoji)} held the crown last week with ${C.crown.xp.toLocaleString()} XP</span></div>` : ''}</section>`;

  h += `<section class="card">${seg([['week', 'Week'], ['month', 'Month'], ['all', 'All time']], S.crewPeriod, 'crewPeriod')}
    <div class="lbl2">${{ week: "This week's league", month: 'This month', all: 'All-time legends' }[S.crewPeriod]}</div>
    ${sorted.map((m, i) => {
    const p = pv(m), dot = m.live ? '<span class="dot live"></span>' : m.qualified ? '<span class="dot g"></span>' : m.today_min > 0 ? '<span class="dot y"></span>' : '<span class="dot"></span>';
    return `<div class="lb ${m.me ? 'me' : ''}"><div class="rk ${i < 3 ? 'top' + (i + 1) : ''}">${i === 0 ? ic('crown', 16) : i + 1}</div>${avatar(m.emoji, m.color)}
      <div class="grow lbm"><div class="lbn"><b class="ell">${esc(m.display)}</b>${m.me ? '<span class="you">you</span>' : ''}${m.crowns ? `<span class="xs mut">${ic('crown', 11)}×${m.crowns}</span>` : ''}${dot}</div>
        <div class="xs mut ell">Lv ${m.level.level} ${esc(m.level.emoji)} ${esc(m.level.rank)} · ${ic('flame', 11)}${m.streak} · today ${fm(m.today_min)}${m.live ? ` · <span class="live-t">live: ${esc(m.live.subject)}</span>` : ''}</div>
        <div class="bar thin mt4"><i style="width:${Math.round(p.xp / top * 100)}%;background:${esc(m.color)}"></i></div></div>
      <div class="lbx"><b class="num">${p.xp.toLocaleString()}</b><div class="xs mut">XP · ${fm(p.min)}</div>${!m.me && !m.qualified ? `<button class="btn-s nudge" ${m.nudged ? 'disabled' : ''} data-act="nudge" data-id="${m.id}">${m.nudged ? 'Nudged' : 'Nudge'}</button>` : ''}</div></div>`;
  }).join('')}
    <div class="xs mut mt8"><span class="dot live"></span> live · <span class="dot g"></span> floor hit · <span class="dot y"></span> some work · <span class="dot"></span> nothing yet. A nudge gives you +5 XP. The league resets every Monday.</div></section>`;

  const tp = Math.round(Math.min(C.team.minutes / Math.max(C.team.goal, 1) * 100, 100));
  h += `<section class="card">${lbl('Crew weekly goal', `<b class="num">${fm(C.team.minutes)} / ${fm(C.team.goal)}</b>`)}<div class="bar o"><i style="width:${tp}%"></i></div><div class="xs mut mt8">Hit it together for +100 XP each. You must log 5h+ yourself to share the loot. Nobody free-rides.</div></section>`;
  if (C.boss) {
    const b = C.boss, pct = Math.round(clamp(b.actual / Math.max(b.target, 1) * 100, 0, 100)), stt = b.passed === true ? ['Defeated', 'g'] : b.passed === false ? ['Failed', 'd'] : ['Active', ''];
    h += `<section class="card">${lbl('Daily boss battle', `<span class="pill ${stt[1]}">${stt[0]}</span>`)}<div class="bignum sm c">${fm(b.actual)} <span class="mut of">/ ${fm(b.target)}</span></div><div class="bar mt8 ${b.passed === true ? 'g' : ''}"><i style="width:${pct}%"></i></div>
      <div class="xs mut mt8">${b.passed === true ? 'Everyone got +50 XP.' : b.passed === false ? 'The crew missed the target. Three fails in a week disables the weekly goal XP.' : 'Verified timer minutes only. The target resets at 3 AM.'}</div></section>`;
  }
  if (C.records && C.records.length) h += `<section class="card">${lbl('Crew records')}${C.records.map(r => `<div class="q"><div class="grow sm">${esc(r.label)}</div><div class="rt2"><b class="num">${r.unit === 'min' ? fm(r.value) : r.value + ' ' + r.unit}</b><div class="xs mut">${esc(r.emoji)} ${esc(r.name)}${r.me ? ' (you, defend it)' : ''}</div></div></div>`).join('')}<div class="xs mut mt8">Break one in a verified session and the whole crew sees it.</div></section>`;
  if (C.hall && C.hall.length) h += `<section class="card">${lbl('Weekly champions')}${C.hall.map(x => `<div class="q"><span class="xs mut w64">wk ${esc(x.week.slice(5))}</span><div class="grow">${esc(x.emoji)} <b>${esc(x.name)}</b></div><span class="pill">${x.xp.toLocaleString()} XP</span></div>`).join('')}</section>`;
  const others = C.members.filter(m => !m.me);
  h += `<section class="card">${lbl('Duels')}${C.duels.length ? C.duels.map(d => `<div class="q"><div class="grow"><b>${esc(d.an)}</b> vs <b>${esc(d.bn)}</b> <span class="xs mut">${d.days}d · most focus minutes wins</span>${d.status === 'active' ? `<div class="xs">${fm(d.a_min)} vs ${fm(d.b_min)} · ends ${esc(d.end)}</div>` : '<div class="xs mut">Waiting for accept…</div>'}</div>${d.status === 'pending' && d.b === C.me ? `<button class="btn-p btn-s" data-act="acceptDuel" data-id="${d.id}">Accept</button>` : ''}</div>`).join('') : '<div class="mut sm">No duels running. Pick a rival.</div>'}
    ${others.length ? `<div class="row g8 mt12"><select id="du_o">${others.map(m => `<option value="${m.id}">${esc(m.display)}</option>`).join('')}</select><select id="du_d" style="width:84px"><option value="3">3d</option><option value="7" selected>7d</option><option value="14">14d</option></select><button data-act="duel">Challenge</button></div>` : ''}</section>`;
  h += `<section class="card">${lbl('Crew feed')}${C.feed.length ? C.feed.map(f => `<div class="feed"><div class="row g8">${avatar(f.emoji, f.color, 'sm')}<div class="grow sm"><b>${esc(f.display)}</b> ${esc(f.text).replace(/\*\*/g, '')}</div><span class="xs mut">${ago(f.ts)}</span></div>
    <div class="rxrow">${['🔥', '💪', '👏', '😤', '🫡'].map(e => `<button class="rx ${f.mine === e ? 'me' : ''}" data-act="react" data-id="${f.id}" data-e="${e}">${e}${f.reactions[e] ? ' ' + f.reactions[e] : ''}</button>`).join('')}</div></div>`).join('') : '<div class="mut sm">Quiet. Be the first to move.</div>'}</section>`;
  return h;
}
/* ---------- STUDY (syllabus / revise / tests) ---------- */
function vStudy() {
  const tabs = [['chapters', 'Chapters'], ['revise', 'Revise'], ['tests', 'Tests']];
  let h = seg(tabs, S.sub, 'sub');
  if (S.sub === 'chapters') {
    const chs = S.syl.chapters, ins = S.ins, ch = ins?.chapters;
    if (ch) h += `<section class="card hero">${lbl('Syllabus map')}<div class="grid3"><div class="stat"><b>${ch.left}</b><span class="xs mut">untouched</span></div><div class="stat"><b>${ch.learned}</b><span class="xs mut">learned</span></div><div class="stat"><b>${ch.mastered}</b><span class="xs mut">mastered</span></div></div>
      ${(ins.exams || []).map(e => `<div class="sm mt8">${esc(e.name)}: <b>${e.days_left} days</b> left. You need <b>${e.need_per_week}</b> new chapters a week; current pace is <b>${ch.rate.toFixed(1)}</b>. ${ch.rate >= e.need_per_week ? '<span class="good">On pace.</span>' : '<span class="warn">Behind pace. Go narrower on weightage, wider on PYQs.</span>'}</div>`).join('')}</section>`;
    h += `<div class="xs mut" style="margin:4px 2px 0">Each tick moves a chapter up: learned, practiced, mastered. Marking it learned schedules revisions on day 1, 3, 7, 14 and 30. Mastered means you scored well on it in a test.</div>`;
    SUBS.forEach(sub => {
      const list = chs.filter(c => c.subject === sub); if (!list.length) return;
      const l = list.filter(c => c.status >= 1).length, mst = list.filter(c => c.status >= 3).length;
      h += `<section class="card"><div class="row between"><h2 style="color:${SCOL[sub]}">${sub}</h2><span class="xs mut">${l}/${list.length} learned · ${mst} mastered</span></div><div class="bar mt8"><i style="width:${l / list.length * 100}%;background:${SCOL[sub]}"></i></div>`;
      ['11', '12', '+'].forEach(g => {
        const gl = list.filter(c => c.grade === g); if (!gl.length) return;
        h += `<div class="lbl2">${g === '+' ? 'Added by you' : 'Class ' + g}</div>` + gl.map(c => `<div class="ch"><div class="grow ${c.status >= 3 ? 'mut' : ''}">${esc(c.name)}</div><div class="steps">${[[1, 'Learned'], [2, 'Practiced'], [3, 'Mastered']].map(([n, t]) => `<button class="${c.status >= n ? 'on' : ''}" title="${t}" aria-label="${t}" data-act="chap" data-id="${c.id}" data-s="${c.status === n ? n - 1 : n}">${ic('check', 14)}</button>`).join('')}</div></div>`).join('');
      });
      h += `<details data-k="addch-${sub}"><summary>Add a chapter or topic to ${sub}</summary><div class="row g8 mt8"><input id="ca_${sub}" placeholder="Name" maxlength="60"><button data-act="addChap" data-v="${sub}">Add</button></div></details></section>`;
    });
  }
  if (S.sub === 'revise') {
    const due = S.syl.revisions.filter(r => r.due <= S.syl.today), up = S.syl.revisions.filter(r => r.due > S.syl.today);
    h += `<section class="card hero">${lbl('Active recall queue', due.length ? `${due.length} due` : '')}<p class="sm mut">Close the book. Write everything you remember for 3 minutes. Then rate honestly. Honest "blank" ratings are what make you win.</p>
      ${due.length ? due.map(r => `<div class="q wrapq"><div class="grow"><b>${esc(r.name)}</b> <span class="xs mut">${esc(r.subject)} · review #${r.stage + 1}${r.due < S.syl.today ? ' · overdue' : ''}</span></div><div class="row g4"><button class="btn-g btn-s" data-act="rev" data-id="${r.id}" data-r="solid">Solid</button><button class="btn-s" data-act="rev" data-id="${r.id}" data-r="shaky">Shaky</button><button class="btn-d btn-s" data-act="rev" data-id="${r.id}" data-r="blank">Blank</button></div></div>`).join('') : '<div class="c mut" style="padding:18px 0">Nothing due. Learn something new and it gets scheduled.</div>'}</section>`;
    if (up.length) h += `<section class="card">${lbl('Coming up')}${up.slice(0, 12).map(r => `<div class="q"><div class="grow">${esc(r.name)} <span class="xs mut">${esc(r.subject)}</span></div><span class="xs mut">${esc(r.due)}</span></div>`).join('')}</section>`;
  }
  if (S.sub === 'tests') {
    const T = S.tests, ts = T.tests, pct = ts.map(t => Math.round(t.score / t.maxscore * 100));
    h += `<section class="card">${lbl('Log a test or PYQ paper')}<div class="grid2"><div><label>Name</label><input id="t_n" placeholder="Mock 3 / PYQ 2024" maxlength="60"></div><div><label>Subject</label><select id="t_s"><option>All</option>${SUBS.map(s => `<option>${s}</option>`).join('')}</select></div>
      <div><label>Score</label><input id="t_sc" type="number" inputmode="decimal"></div><div><label>Out of</label><input id="t_mx" type="number" inputmode="decimal" value="300"></div></div>
      <label>Where did you lose marks? (number of questions)</label><div class="grid3"><input id="t_c" type="number" inputmode="numeric" placeholder="Concept gap"><input id="t_si" type="number" inputmode="numeric" placeholder="Silly mistake"><input id="t_t" type="number" inputmode="numeric" placeholder="Out of time"></div>
      <button class="btn-p btn-xl mt12" data-act="addTest">Save (+80 XP)</button></section>`;
    if (pct.length > 1) h += `<section class="card">${lbl('Score trend')}${lines([{ v: pct, c: '#3dd6a0', w: 2.5 }])}<div class="row between xs mut"><span>${pct[0]}%</span><span>latest ${pct[pct.length - 1]}% (${pct[pct.length - 1] - pct[0] >= 0 ? '+' : ''}${pct[pct.length - 1] - pct[0]} since first)</span></div></section>`;
    const e = T.errors, tot = e.concept + e.silly + e.time;
    if (tot) {
      const top = Object.entries(e).sort((a, b) => b[1] - a[1])[0][0];
      const advice = { concept: 'Most lost marks are concept gaps. Stop doing new questions. Re-learn the 3 weakest chapters, then do 10 PYQs per chapter.', silly: 'Most lost marks are silly mistakes: you know it, you botched it. Fix the process. Circle units and signs, re-read the question, keep 10 minutes at the end to re-check.', time: 'Most lost marks are time. Practice in timed sections, skip and return, and stop sinking 6 minutes into one question.' }[top];
      h += `<section class="card">${lbl('Error autopsy', 'last 8 tests')}<div class="grid3"><div class="stat"><b>${e.concept}</b><span class="xs mut">concept</span></div><div class="stat"><b>${e.silly}</b><span class="xs mut">silly</span></div><div class="stat"><b>${e.time}</b><span class="xs mut">time</span></div></div><div class="sm mt8">${advice}</div></section>`;
    }
    h += `<section class="card">${lbl('History')}${ts.length ? ts.slice().reverse().map(t => `<div class="q"><div class="grow">${esc(t.name)} <span class="xs mut">${esc(t.subject)} · ${esc(t.day)}</span></div><b class="num">${t.score}/${t.maxscore}</b><span class="pill">${Math.round(t.score / t.maxscore * 100)}%</span></div>`).join('') : '<div class="mut sm">No tests yet. Feelings lie; scores do not.</div>'}</section>`;
  }
  return h;
}

/* ---------- REFLECT ---------- */
function vReflect() {
  const R = S.refl, W = S.weekly, t = R.today, miss = R.minutes < R.daily_min;
  const scale = (id, v, lo, hi) => `<div class="scale" id="${id}">${[1, 2, 3, 4, 5].map(i => `<span class="${(v || 3) === i ? 'on' : ''}" data-act="mood" data-g="${id}" data-v="${i}">${i}</span>`).join('')}</div><div class="row between xs mut mt4"><span>${lo}</span><span>${hi}</span></div>`;
  let h = `<section class="card hero"><h2>Tonight's reflection</h2><p class="sm mut">60 seconds. Not a diary, a debugging session. ${t ? '<b class="good">Done for today. You can still edit it.</b>' : '+40 XP'}</p>
    <label>Mood</label>${scale('f_mood', t?.mood, 'Low', 'High')}<label>Energy</label>${scale('f_energy', t?.energy, 'Drained', 'Charged')}
    <label>One specific win today (small counts: "did 12 integration problems")</label><textarea id="f_win">${esc(t?.win || '')}</textarea>
    <label>Where did time leak, and what triggered it? (describe, don't judge)</label><textarea id="f_leak">${esc(t?.leak || '')}</textarea>
    ${miss ? `<label>You're under your floor today. What would you say to a friend in your exact spot?</label><textarea id="f_kind" placeholder="Kind, specific, forward-looking.">${esc(t?.kind_note || '')}</textarea>` : `<input type="hidden" id="f_kind" value="${esc(t?.kind_note || '')}">`}
    <label>Tomorrow's one thing (becomes a promise)</label><input id="f_tom" value="${esc(t?.tomorrow || '')}" placeholder="e.g. Integration by parts, 15 problems">
    <label>When and where exactly?</label><input id="f_cue" placeholder="After breakfast, desk, phone in the other room">
    <button class="btn-p btn-xl mt12" data-act="saveReflect">Save reflection</button></section>`;
  const s = W.summary, ex = W.existing, d = s.minutes - s.prev_minutes;
  h += `<section class="card">${lbl('Weekly review', `Week of ${esc(s.week)}`)}<p class="sm mut">The data first, then the decision. +100 XP.</p><div class="grid3"><div class="stat"><b>${fm(s.minutes)}</b><span class="xs mut">focus</span></div><div class="stat"><b>${s.qualified_days}/7</b><span class="xs mut">floor days</span></div><div class="stat"><b>${d < 0 ? '-' : '+'}${fm(Math.abs(d))}</b><span class="xs mut">vs last week</span></div></div>
    ${Object.keys(s.by_subject).length ? `<div class="chips mt8">${Object.entries(s.by_subject).map(([k, v]) => `<span class="pill" style="background:${SCOL[k]}22;color:${SCOL[k]}">${esc(k)} ${fm(v)}</span>`).join('')}</div>` : ''}
    <label>Best moment of the week</label><input id="w_best" value="${esc(ex?.best || '')}"><label>Biggest leak</label><input id="w_leak" value="${esc(ex?.leak || '')}">
    <label>One thing I'll change next week (just one)</label><input id="w_chg" value="${esc(ex?.change || '')}">
    <label>Pre-mortem: it's next Sunday and the week went badly. Why?</label><input id="w_pre" value="${esc(ex?.premortem || '')}">
    <label>So: if that happens, then I will…</label><input id="w_if" value="${esc(ex?.ifthen || '')}"><button class="btn-xl mt12" data-act="saveWeekly">Save weekly review</button></section>`;
  if (R.history.length) h += `<section class="card">${lbl('Journal')}${R.history.map(r => `<div class="feed"><div class="row between"><b>${esc(r.day)}</b><span class="xs mut">mood ${r.mood}/5 · energy ${r.energy}/5</span></div><div class="sm">${esc(r.win)}</div>${r.leak ? `<div class="sm mut">Leak: ${esc(r.leak)}</div>` : ''}${r.kind_note ? `<div class="sm acc">${esc(r.kind_note)}</div>` : ''}</div>`).join('')}</section>`;
  return h;
}

/* ---------- ME ---------- */
function vMe() {
  const I = S.ins, u = S.user, L = I.level, e = I.evidence, og = I.outgrow, pct = Math.round(og.ratio * 100);
  const hm = I.heat.map(c => { const a = c.f ? '#5aa9ff66' : c.m === 0 ? '#17171c' : `rgba(124,106,247,${Math.min(.25 + c.m / 240 * .75, 1)})`; return `<i title="${esc(c.d)}: ${fm(c.m)}${c.f ? ' (freeze)' : ''}" style="background:${a}"></i>`; }).join('');
  const hrmx = Math.max(...I.hours, 1), best = I.hours.indexOf(Math.max(...I.hours));
  let h = `<section class="card hero"><div class="row g12">${avatar(u.emoji, u.color, 'xl')}<div class="grow"><h2>${esc(u.display)}</h2><div class="mut sm">Level ${L.level} · ${esc(L.emoji)} ${esc(L.rank)} · ${L.xp.toLocaleString()} XP</div></div></div>
    <div class="bar xp mt12"><i style="width:${L.pct}%"></i></div>
    <details data-k="ladder"><summary>Title ladder · ${I.ladder.length} titles · ${L.next_rank ? 'next: ' + esc(L.next_emoji) + ' ' + esc(L.next_rank) + ' at Lv ' + L.next_at : 'top title reached'}</summary>${I.ladder.map(r => `<div class="q" style="opacity:${L.level >= r.level ? 1 : .4}"><span class="lad-e">${esc(r.emoji)}</span><div class="grow ${L.rank === r.rank ? 'b' : ''}">${esc(r.rank)}${L.rank === r.rank ? ' <span class="pill">you</span>' : ''}</div><span class="xs mut">Lv ${r.level} · ${(60 * (r.level - 1) ** 2).toLocaleString()} XP</span></div>`).join('')}</details></section>`;
  h += `<section class="card">${lbl('The Ragda meter')}<p class="sm mut">Your last 7 days against the old A+ you (${og.baseline_h}h a day).</p><div class="row between"><div class="bignum" style="color:${pct >= 100 ? 'var(--good)' : 'var(--tx)'}">${pct}%</div><div class="sm rt-text">${pct >= 130 ? 'You are Ragdamaxed. The old you cannot keep up.' : pct >= 100 ? 'You matched the A+ you. Now pass them.' : pct >= 60 ? 'Closing in. Keep stacking days.' : 'The gap is real. The gap is also closable.'}</div></div>
    <div class="bar mt8 ${pct >= 100 ? 'g' : ''}"><i style="width:${Math.min(pct, 100)}%"></i></div>
    ${I.ghost ? `<div class="lbl2">You vs your best week</div>${lines([{ v: I.ghost.cum, c: '#7c7c88', d: 1, w: 2 }, { v: I.cum, c: '#3dd6a0', w: 3 }])}<div class="xs mut">Dashed is your best week (${fm(I.ghost.total)}). Green is this week.</div>` : ''}</section>`;
  h += `<section class="card">${lbl('Evidence locker')}<p class="sm mut">When your brain says "I'm a failure", read the court record.</p><div class="grid3"><div class="stat"><b>${e.hours}h</b><span class="xs mut">focused</span></div><div class="stat"><b>${e.days_hit}</b><span class="xs mut">floor days</span></div><div class="stat"><b>${e.longest}</b><span class="xs mut">best streak</span></div><div class="stat"><b>${e.deep}</b><span class="xs mut">deep blocks</span></div><div class="stat"><b>${e.urges_won}</b><span class="xs mut">urges beaten</span></div><div class="stat"><b>${e.learned}</b><span class="xs mut">chapters</span></div></div>
    ${e.wins.length ? '<div class="lbl2">Your own wins</div>' + e.wins.map(w => `<div class="sm" style="padding:3px 0">${esc(w.win)} <span class="xs mut">${esc(w.day)}</span></div>`).join('') : ''}</section>`;
  h += `<section class="card">${lbl('Last 12 weeks')}<div class="heat">${hm}</div><div class="xs mut mt8">Brighter means more focus. Blue means a streak freeze saved you.</div></section>`;
  h += `<section class="card">${lbl('Weekly hours')}${bars(I.weeks.map(w => w.m), '#7c6af7')}<div class="row between xs mut"><span>8 weeks ago</span><span>this week ${fm(I.weeks[7].m)}</span></div></section>`;
  if (I.hours.some(x => x)) h += `<section class="card">${lbl('Your best focus hours')}<div class="hrs">${I.hours.map(x => `<i style="height:${x / hrmx * 100}%"></i>`).join('')}</div><div class="row between xs mut mt4"><span>12am</span><span>6am</span><span>12pm</span><span>6pm</span><span>12am</span></div><div class="sm mt8">Peak: <b>${best % 12 || 12}${best < 12 ? 'am' : 'pm'}</b>. Put your hardest chapter there.</div></section>`;
  if (Object.keys(I.sub7).length) { const tot = Object.values(I.sub7).reduce((a, b) => a + b, 0); h += `<section class="card">${lbl('Subject balance', '7 days')}${Object.entries(I.sub7).sort((a, b) => b[1] - a[1]).map(([s, m]) => `<div class="row g8" style="margin:8px 0"><span class="sm w78">${esc(s)}</span><div class="bar grow"><i style="width:${m / tot * 100}%;background:${SCOL[s] || '#9a9aa8'}"></i></div><span class="xs mut w56 r">${fm(m)}</span></div>`).join('')}</section>`; }
  if (I.urge_triggers.length) h += `<section class="card">${lbl('Your triggers')}<div class="chips">${I.urge_triggers.map(t => `<span class="pill">${esc(t.trigger)} ×${t.n}</span>`).join('')}</div></section>`;
  h += `<section class="card">${lbl('Badges', `${I.badges.filter(b => b.got).length}/${I.badges.length}`)}<div class="grid3">${I.badges.map(b => `<div class="badge ${b.got ? '' : 'off'}"><s>${esc(b.emoji)}</s><b>${esc(b.name)}</b><div class="xs mut">${esc(b.desc)}</div></div>`).join('')}</div></section>`;
  if (u.admin) h += `<section class="card">${lbl('Server')}<p class="sm mut">You run this crew. Live stats, PIN resets, moderation, backups.</p><button class="btn-xl" data-act="admin">Open server dashboard</button></section>`;
  h += `<section class="card">${lbl('Settings')}<label>Display name</label><input id="s_name" value="${esc(u.display)}" maxlength="20"><label>Identity: "I am becoming someone who…"</label><input id="s_id" value="${esc(u.identity)}" placeholder="shows up before he feels like it" maxlength="140">
    <div class="grid2"><div><label>Old A+ you studied (hrs/day)</label><input id="s_base" type="number" step="0.5" value="${u.baseline_h}"></div><div><label>Daily floor (min)</label><input id="s_floor" type="number" value="${u.daily_min}"></div></div>
    <label>Exams (name and date)</label>${[0, 1, 2].map(i => { const x = u.exams[i] || {}; return `<div class="row g8" style="margin-bottom:6px"><input id="s_en${i}" placeholder="JEE Main" value="${esc(x.name || '')}"><input id="s_ed${i}" type="date" value="${esc(x.date || '')}" style="width:156px"></div>`; }).join('')}
    <label>Avatar emoji and colour</label><div class="row g8"><input id="s_emo" value="${esc(u.emoji)}" style="width:84px"><input id="s_col" type="color" value="${esc(u.color)}" style="width:72px;padding:3px"></div>
    <button class="btn-p btn-xl mt12" data-act="saveSettings">Save</button><button class="btn-xl mt8" data-act="notif">Enable alerts when friends start a block</button><button class="btn-d btn-xl mt8" data-act="logout">Log out</button></section>`;
  if (I.xp_log.length) h += `<section class="card">${lbl('Recent XP')}${I.xp_log.map(x => `<div class="row between sm" style="padding:4px 0"><span class="mut">${esc(x.label)}</span><b class="num">${x.amount > 0 ? '+' : ''}${x.amount}</b></div>`).join('')}</section>`;
  return h;
}

/* ---------- onboarding & urge ---------- */
function onboard() {
  modal(`<h2>Set the terms.</h2><p class="mut sm">You were an A+ student. That person still exists, they just need a system. Set the bar they'd set.</p>
  <label>Who are you becoming? ("I am someone who…")</label><input id="o_id" placeholder="studies before he's motivated" maxlength="140">
  <label>On your best A+ days, how many hours a day did you study?</label><input id="o_base" type="number" step="0.5" value="5">
  <label>Your daily floor (minutes). The minimum that keeps the streak alive, even on bad days.</label><input id="o_floor" type="number" value="45">
  <label>Exam 1 (name and date)</label><div class="row g8"><input id="o_n1" placeholder="JEE Main" value="JEE Main"><input id="o_d1" type="date" style="width:156px"></div>
  <label>Exam 2</label><div class="row g8"><input id="o_n2" placeholder="CBSE Boards" value="CBSE Boards"><input id="o_d2" type="date" style="width:156px"></div>
  <button class="btn-p btn-xl mt12" data-act="saveOnboard">Let's go</button>`, true);
}
function urgeFlow() {
  const trig = ['Instagram', 'Reels/Shorts', 'YouTube', 'Gaming', 'Texting', 'Overthinking', 'Just tired', 'Other'];
  modal(`<h2>Urge surfing</h2><p class="sm mut">An urge peaks and passes in about 90 seconds if you don't feed it. Name it. Ride it.</p><div class="chips mt12">${trig.map(t => `<button class="chip" data-act="urgeStart" data-v="${t}">${t}</button>`).join('')}</div><button class="btn-xl mt12" data-act="closeModal">Cancel</button>`);
}
function urgeRun(trigger) {
  S.urge = { trigger, left: 90 }; S.urgeTrig = trigger;
  modal(`<div class="c"><div class="xs mut">${esc(trigger)} urge</div><div class="bignum" id="ur_n">90</div><p class="b acc" id="ur_t">Breathe in…</p><p class="sm mut">Notice where you feel it. You don't have to obey it.</p>
    <button class="btn-p btn-xl" data-act="urgeDone" data-v="redirected">Start 5 minutes of study instead</button><button class="btn-g btn-xl mt8" data-act="urgeDone" data-v="resisted">It passed. I'm good</button><button class="btn-xl mt8" data-act="urgeDone" data-v="gave_in">I gave in (no judgement, log it)</button></div>`, true);
  const step = () => {
    const U = S.urge; if (!U) return;
    const n = $('#ur_n'), tx = $('#ur_t'); if (!n) { S.urge = null; return; }
    n.textContent = U.left; const ph = U.left % 14;
    tx.textContent = U.left <= 0 ? 'The wave has passed.' : ph > 10 ? 'Breathe in…' : ph > 6 ? 'Hold…' : 'Out, slowly…';
    if (U.left <= 0) return;
    U.left--; S._ut = setTimeout(step, 1000);
  };
  clearTimeout(S._ut); step();
}
/* ---------- actions ---------- */
const val = id => ($('#' + id) || {}).value;
const A = {
  reload() { location.reload(); },
  async login() { try { const r = await api('login', { username: val('a_user'), pin: val('a_pin') }); S.user = r.user; S.tab = 'today'; await go('today'); if (!S.user.onboarded) onboard(); } catch (e) { } },
  async register() { try { const r = await api('register', { username: val('a_user'), pin: val('a_pin'), crew_code: val('a_code'), crew_name: val('a_cname') }); S.user = r.user; S.tab = 'today'; await go('today'); onboard(); } catch (e) { } },
  authMode() { S.authMode = S.authMode === 'login' ? 'register' : 'login'; renderAuth(); },
  async logout() { try { await api('logout', {}); } catch (e) { } onLoggedOut(); },
  closeModal() { clearTimeout(S._ut); S.urge = null; closeModal(); },
  async tab(el) { if (el.dataset.sub) S.sub = el.dataset.sub; await go(el.dataset.v); },
  pickSub(el) { S.pickSub = el.dataset.v; PREF.set('sub', S.pickSub); render(); },
  pickDur(el) { S.pickDur = +el.dataset.v; PREF.set('dur', S.pickDur); render(); },
  pickMode(el) { S.pickMode = el.dataset.v; PREF.set('mode', S.pickMode); render(); },
  crewPeriod(el) { S.crewPeriod = el.dataset.v; render(); },
  async startTimer() { await api('timer/start', { subject: S.pickSub, target: S.pickDur, mode: S.pickMode === 'stopwatch' ? 'stopwatch' : 'timer' }); await refresh(); },
  async start5() { await api('timer/start', { subject: S.pickSub, target: 5 }); await refresh(); },
  async startPomo() {
    const c = pomoNorm(S.pomoCfg); S.pomoCfg = c; PREF.set('pomo', c);
    await api('pomo/start', { subject: S.pickSub, total: c.total, work: c.work, brk: c.brk }); await refresh();
  },
  async skipBreak() { await api('pomo/skip', {}); await refresh(); },
  async endPlan() { if (!confirm('End the pomodoro plan? Completed blocks stay logged.')) return; await api('pomo/stop', {}); S.beepKey = null; await refresh(); },
  async extend() { await api('timer/extend', { add: 20 }); S.beeped = false; S.msgKey = ''; await refresh(); },
  async distract() {
    await api('timer/distract', {});
    if (S.today?.timer) { S.today.timer.distractions++; $$('#dcount,#fs-dcount').forEach(n => { n.textContent = S.today.timer.distractions; }); }
  },
  async stopTimer() { if (S.today?.pomo && !confirm('End the pomodoro plan and log this block?')) return; await finishTimer(); },
  async discard() { if (confirm('Discard this block? Nothing will be logged.')) await finishTimer({ discard: true }); },
  async manual() { await api('focus', { subject: val('mf_s'), minutes: +val('mf_m') }); await refresh(); },
  async delFocus(el) { await api('focus/delete', { id: +el.dataset.id }); await refresh(); },
  async habit(el) { const on = S.today.habits.includes(el.dataset.id); await api('habit', { habit: el.dataset.id, done: !on }); await refresh(); },
  async chest() {
    const r = await api('chest', {}); confetti();
    modal(`<div class="c"><div class="xs mut up">${esc(r.tier.toUpperCase())}</div><div class="bignum">${esc(r.label)}</div><p class="sm mut mt8">Daily chest opened. Come back tomorrow.</p><button class="btn-p btn-xl mt12" data-act="closeModal">Nice</button></div>`);
    await refresh();
  },
  async addPlan(el) { const t = val('pl_t'); if (!t) return toast('Write the task first'); await api('plan', { when: el.dataset.v, text: t, cue: val('pl_c') }); await refresh(); },
  async togglePlan(el) { await api('plan/toggle', { id: +el.dataset.id }); await refresh(); },
  async delPlan(el) { await api('plan/delete', { id: +el.dataset.id }); await refresh(); },
  urge() { urgeFlow(); }, urgeStart(el) { urgeRun(el.dataset.v); },
  async urgeDone(el) {
    const tr = S.urgeTrig || 'Other', o = el.dataset.v; clearTimeout(S._ut); S.urge = null;
    try { await api('urge', { outcome: o, trigger: tr }); } catch (e) { closeModal(); return; }
    closeModal();
    if (o === 'redirected') { try { await api('timer/start', { subject: S.pickSub, target: 5 }); } catch (e) { } }
    else if (o === 'gave_in') toast('Logged. No shame.', 'What would make the next one easier?');
    await refresh();
  },
  sub(el) { S.sub = el.dataset.v; render(); },
  async chap(el) { await api('chapter', { id: +el.dataset.id, status: +el.dataset.s }); [S.syl, S.ins] = await Promise.all([api('syllabus'), api('insights')]); render(); },
  async addChap(el) { const n = val('ca_' + el.dataset.v); if (!n) return; await api('chapter/add', { subject: el.dataset.v, name: n }); S.syl = await api('syllabus'); render(); },
  async rev(el) { await api('revision', { id: +el.dataset.id, result: el.dataset.r }); S.syl = await api('syllabus'); render(); },
  async addTest() {
    const sc = val('t_sc'), mx = val('t_mx'); if (sc === '' || !mx) return toast('Enter your score and the maximum');
    await api('test', { name: val('t_n') || 'Test', kind: 'mock', subject: val('t_s'), score: +sc, max: +mx, concept: +val('t_c') || 0, silly: +val('t_si') || 0, time: +val('t_t') || 0 });
    S.tests = await api('tests'); render();
  },
  mood(el) { $$(`#${el.dataset.g} span`).forEach(s => s.classList.remove('on')); el.classList.add('on'); },
  async saveReflect() {
    const g = id => { const x = $$(`#${id} span`).findIndex(s => s.classList.contains('on')); return x < 0 ? 3 : x + 1; };
    await api('reflect', { mood: g('f_mood'), energy: g('f_energy'), win: val('f_win'), leak: val('f_leak'), kind_note: val('f_kind'), tomorrow: val('f_tom'), cue: val('f_cue') });
    toast('Reflection saved', 'Tomorrow is already planned.'); await refresh();
  },
  async saveWeekly() { await api('weekly', { best: val('w_best'), leak: val('w_leak'), change: val('w_chg'), premortem: val('w_pre'), ifthen: val('w_if') }); toast('Weekly review saved'); await refresh(); },
  async joinCrew() { await api('crew/join', { code: val('cj') }); await refresh(); },
  async createCrew() { await api('crew/create', { name: val('cn') }); await refresh(); },
  async nudge(el) { await api('nudge', { to: +el.dataset.id }); toast('Nudged'); await refresh(); },
  async react(el) { await api('react', { feed_id: +el.dataset.id, emoji: el.dataset.e }); S.crew = await api('crew'); render(); },
  async duel() { await api('duel', { opponent: +val('du_o'), days: +val('du_d') }); toast('Challenge sent'); await refresh(); },
  async acceptDuel(el) { await api('duel/accept', { id: +el.dataset.id }); await refresh(); },
  copy(el) { try { navigator.clipboard?.writeText(el.dataset.v); toast('Invite code copied'); } catch (e) { toast('Copy failed', el.dataset.v); } },
  async saveOnboard() {
    const ex = [[val('o_n1'), val('o_d1')], [val('o_n2'), val('o_d2')]].filter(x => x[1]).map(x => ({ name: x[0] || 'Exam', date: x[1] }));
    const r = await api('settings', { identity: val('o_id'), baseline_h: +val('o_base'), daily_min: +val('o_floor'), exams: ex.length ? ex : undefined, onboarded: true }); S.user = r.user; closeModal(); await refresh();
  },
  async saveSettings() {
    const ex = [0, 1, 2].map(i => ({ name: val('s_en' + i) || 'Exam', date: val('s_ed' + i) })).filter(x => x.date);
    const r = await api('settings', { display: val('s_name'), identity: val('s_id'), baseline_h: +val('s_base'), daily_min: +val('s_floor'), exams: ex, emoji: val('s_emo'), color: val('s_col') }); S.user = r.user; toast('Saved'); await refresh();
  },
  async notif() { if (!('Notification' in window)) return toast('Not supported here'); const p = await Notification.requestPermission(); toast(p === 'granted' ? 'Alerts on while the app is open' : 'Blocked'); },
  enterFullscreenFocus() { enterFullscreenFocus(); },
  exitFullscreenFocus() { exitFullscreenFocus(); },
  fsClockNext() { fsStep(1); },
  fsClockPrev() { fsStep(-1); },
  async logAndExitFocus() { if (S.today?.pomo && !confirm('End the pomodoro plan and log this block?')) return; try { await finishTimer(); } catch (e) { } },
};
/* one click handler for the whole app. A busy flag stops double taps from double submitting. */
document.addEventListener('click', async e => {
  const el = e.target.closest('[data-act]'); if (!el || !A[el.dataset.act]) return;
  e.preventDefault();
  if (el.dataset.busy) return;
  el.dataset.busy = '1'; el.classList.add('busy');
  try { await A[el.dataset.act](el, e); }
  catch (x) { if (!x || !x.api) console.error(x); }
  finally { delete el.dataset.busy; el.classList.remove('busy'); }
});
document.addEventListener('pointerdown', () => { S.lastPtr = Date.now(); }, { passive: true });
$('#modal').addEventListener('click', e => { if (e.target.id === 'modal' && !$('#modal').classList.contains('lock')) A.closeModal(); });
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') { if (S.fs) exitFullscreenFocus(); else if (modalOpen() && !$('#modal').classList.contains('lock')) A.closeModal(); return; }
  if (e.key === 'Enter' && S.user === null && e.target.closest && e.target.closest('.auth') && e.target.tagName === 'INPUT') A[S.authMode === 'login' ? 'login' : 'register']();
});
document.addEventListener('input', e => {
  const id = e.target.id || '';
  if (id.startsWith('pomo_')) {
    S.pomoCfg = { total: +val('pomo_total'), work: +val('pomo_work'), brk: +val('pomo_brk') };
    const p = $('#pomo_prev'); if (p) p.textContent = pomoPrev();
  }
});
document.addEventListener('fullscreenchange', () => { if (!document.fullscreenElement && S.fs && S.fsNative) { exitFullscreenFocus(); } });
document.addEventListener('visibilitychange', () => {
  if (document.hidden || !S.user) return;
  if (S.fs) requestWakeLock();
  if (S.tab === 'today' && S.today && (S.today.timer || S.today.pomo)) { syncToday(); tickOnce(); }
});
/* ---------- CHAT: text only. Crew room + private DMs ---------- */
const CH = { threads: [], people: {}, open: null, msgs: [], more: false, seq: -1, unread: {}, total: 0, run: 0, ctl: null, notified: 0, loading: false, reply: null, sel: null, edit: null };
let chatSending = false;
const chatKey = k => encodeURIComponent(k);
const chatClock = ts => new Date(ts).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
function chatDay(ts) {
  const d = new Date(ts), n = new Date(), y = new Date(); y.setDate(n.getDate() - 1);
  return d.toDateString() === n.toDateString() ? 'Today' : d.toDateString() === y.toDateString() ? 'Yesterday' : d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
}
async function chatLoadThreads() {
  const r = await api('chat/threads');
  Object.assign(CH, { threads: r.threads, people: r.people, unread: r.unread, total: r.total, seq: r.seq });
}
function chatStop() { CH.run++; if (CH.ctl) { try { CH.ctl.abort(); } catch (e) { } CH.ctl = null; } }
function chatReset() { chatStop(); Object.assign(CH, { threads: [], people: {}, open: null, msgs: [], more: false, seq: -1, unread: {}, total: 0, notified: 0 }); }
function chatBadge() {
  const b = document.querySelector('.nav button[data-v="chat"]'); if (!b) return;
  let i = b.querySelector('.nb');
  if (CH.total) { if (!i) { i = document.createElement('i'); i.className = 'nb'; b.appendChild(i); } i.textContent = CH.total > 9 ? '9+' : CH.total; } else if (i) i.remove();
}
function chatNearBottom() { const el = $('#chat_msgs'); return !el || el.scrollHeight - el.scrollTop - el.clientHeight < 90; }

function vChat() {
  if (!CH.threads.length) return '<div class="card"><h2>Chat needs a crew</h2><p class="mut">Join your crew from the Crew tab first.</p></div>';
  if (!CH.open) return vThreads();
  const t = CH.threads.find(x => x.key === CH.open) || {};
  const head = t.kind === 'dm'
    ? `<div class="av" style="width:30px;height:30px;font-size:15px;background:${esc(t.color)}33">${esc(t.emoji)}</div><b>${esc(t.title)}</b><span class="xs mut">private</span>`
    : `<b># ${esc(t.title || 'crew')}</b><span class="xs mut">whole crew</span>`;
  return `<div class="chat"><div class="chat-h row"><button class="btn-s" data-act="chatBack">←</button>${head}</div><div class="msgs" id="chat_msgs"></div>
    <div id="chat_ctx"></div><div class="composer"><textarea id="chat_in" rows="1" maxlength="1000" placeholder="${t.kind === 'dm' ? 'Message ' + esc(t.title) : 'Message the crew'}"></textarea><button class="btn-p" data-act="chatSend">Send</button></div></div>`;
}
function vThreads() {
  const row = t => {
    const l = t.last, who = l ? (l.uid === S.user.id ? 'You: ' : t.kind === 'crew' ? esc((CH.people[l.uid] || {}).display || '') + ': ' : '') : '';
    const av = t.kind === 'crew' ? '<div class="av" style="background:#7c5cff33;border:2px solid #7c5cff">#</div>' : `<div class="av" style="background:${esc(t.color)}33;border:2px solid ${esc(t.color)}">${esc(t.emoji)}</div>`;
    return `<div class="q thread" data-act="chatOpen" data-v="${esc(t.key)}">${av}<div class="grow" style="min-width:0"><div class="row between"><b>${esc(t.title)}</b><span class="xs mut">${l ? ago(l.ts) : ''}</span></div>
      <div class="xs mut ell">${l ? who + esc(l.text) : 'No messages yet'}</div></div>${t.unread ? `<span class="ub">${t.unread}</span>` : ''}</div>`;
  };
  const crew = CH.threads.filter(t => t.kind === 'crew'), dms = CH.threads.filter(t => t.kind === 'dm');
  return `<div class="card"><h3>Crew room</h3>${crew.map(row).join('')}<div class="xs mut" style="margin-top:6px">Text only. No media, no files. Nothing to scroll, nothing to get lost in.</div></div>
    <div class="card"><h3>Direct messages</h3>${dms.length ? dms.map(row).join('') : '<div class="mut sm">No one else in the crew yet. Share the invite code.</div>'}<div class="xs mut" style="margin-top:6px">Only you and them can see a DM inside the app.</div></div>`;
}
function chatAfterRender() { if (CH.open) { chatPaint(true); chatCtx(); const ta = $('#chat_in'); if (ta && !matchMedia('(pointer:coarse)').matches) ta.focus(); } }

function chatPaint(stick) {
  const el = $('#chat_msgs'); if (!el) return;
  let h = CH.more ? '<div class="c"><button class="btn-s" data-act="chatOlder">Load earlier messages</button></div>' : '';
  if (!CH.msgs.length && !CH.loading) h += '<div class="mut sm c" style="margin:40px 0">No messages yet. Say hi 👋</div>';
  let prev = null, prevDay = '';
  CH.msgs.forEach(m => {
    const day = chatDay(m.ts);
    if (day !== prevDay) { h += `<div class="daysep"><span>${esc(day)}</span></div>`; prevDay = day; prev = null; }
    const p = CH.people[m.uid] || { display: 'Member', emoji: '👤', color: '#8b8ba3' };
    const grp = prev && prev.uid === m.uid && (new Date(m.ts) - new Date(prev.ts)) < 5 * 60e3;
    const mine = m.uid === S.user.id, sel = CH.sel === m.id;
    const ment = !mine && m.text.toLowerCase().includes('@' + String(S.user.display).toLowerCase());
    const canEdit = mine && (Date.now() - new Date(m.ts).getTime()) < 24 * 3600e3; // server enforces the real 30 min window
    const rx = m.re ? `<div class="rxs">${Object.entries(m.re).map(([e, n]) => `<span class="rx ${m.mine === e ? 'me' : ''}" data-act="chatReact" data-id="${m.id}" data-e="${e}">${e} ${n}</span>`).join('')}</div>` : '';
    const acts = sel ? `<div class="acts">${CHAT_EMOJIS.map(e => `<button class="${m.mine === e ? 'on' : ''}" data-act="chatReact" data-id="${m.id}" data-e="${e}">${e}</button>`).join('')}<button data-act="chatReply" data-id="${m.id}" title="Reply">↩</button>${canEdit ? `<button data-act="chatEdit" data-id="${m.id}" title="Edit">✏️</button>` : ''}${mine ? `<button data-act="chatDel" data-id="${m.id}" title="Delete">🗑</button>` : ''}</div>` : '';
    const qt = m.reply ? `<div class="qt" data-act="chatJump" data-id="${m.reply.id}"><b>${esc((CH.people[m.reply.uid] || {}).display || 'Member')}</b> ${esc(m.reply.text)}</div>` : '';
    h += `<div class="msg ${grp ? 'grp' : ''} ${ment ? 'ment' : ''} ${sel ? 'sel' : ''}" data-act="chatSel" data-id="${m.id}" data-mid="${m.id}">${grp ? '<div class="av sp"></div>' : `<div class="av" style="background:${esc(p.color)}33;border:2px solid ${esc(p.color)}">${esc(p.emoji)}</div>`}
      <div class="mb">${grp ? '' : `<div class="mh"><b style="color:${esc(p.color)}" data-act="chatMention" data-v="${esc(p.display)}">${esc(p.display)}</b><span class="xs mut">${chatClock(m.ts)}</span></div>`}${qt}<div class="mt">${chatFmt(m.text)}${m.edited ? ' <span class="xs mut">(edited)</span>' : ''}</div>${rx}${acts}</div></div>`;
    prev = m;
  });
  el.innerHTML = h;
  if (stick) el.scrollTop = el.scrollHeight;
}

function chatApply(r) {
  Object.assign(CH, { seq: r.seq, unread: r.unread, total: r.total }); Object.assign(CH.people, r.people);
  const stick = chatNearBottom(); let changed = false;
  const have = new Set(CH.msgs.map(m => m.id)), fresh = r.messages.filter(m => !have.has(m.id));
  if (fresh.length) { CH.msgs.push(...fresh); changed = true; }
  if (r.deleted && r.deleted.length) { const gone = new Set(r.deleted), n = CH.msgs.length; CH.msgs = CH.msgs.filter(m => !gone.has(m.id)); changed = changed || CH.msgs.length !== n; }
  if (r.states) CH.msgs.forEach(m => {
    const st = r.states[m.id]; if (!st) return;
    const sig = JSON.stringify([m.re, m.mine, m.text, m.edited]);
    m.re = st.re; m.mine = st.mine; if (st.ed) { m.edited = true; m.text = st.t; }
    if (sig !== JSON.stringify([m.re, m.mine, m.text, m.edited])) changed = true;
  });
  if (changed) chatPaint(stick);
  const theirs = fresh.filter(m => m.uid !== S.user.id);
  if (theirs.length && document.hidden && 'Notification' in window && Notification.permission === 'granted') {
    const m = theirs[theirs.length - 1]; new Notification(`💬 ${(CH.people[m.uid] || {}).display || 'New message'}`, { body: m.text.slice(0, 80) });
  }
  chatBadge();
}

async function chatOpen(key) {
  chatStop(); CH.open = key; CH.msgs = []; CH.more = false; CH.loading = true; CH.reply = CH.sel = CH.edit = null; render();
  try {
    const r = await api('chat/messages?thread=' + chatKey(key) + (document.hidden ? '' : '&mark=1'));
    CH.msgs = r.messages; CH.more = r.more; Object.assign(CH, { seq: r.seq, unread: r.unread, total: r.total }); Object.assign(CH.people, r.people);
    CH.loading = false; chatPaint(true); chatBadge(); chatLoop();
  } catch (e) { CH.loading = false; }
}
async function chatLoop() {
  const my = ++CH.run; let fails = 0;
  while (CH.run === my && S.user && S.tab === 'chat' && CH.open) {
    const last = CH.msgs.length ? CH.msgs[CH.msgs.length - 1].id : 0, first = CH.msgs.length ? CH.msgs[0].id : 0;
    const ctl = new AbortController(); CH.ctl = ctl;
    try {
      const res = await fetch(`/api/chat/messages?thread=${chatKey(CH.open)}&after=${last}&first=${first}&seq=${CH.seq}&wait=20${document.hidden ? '' : '&mark=1'}`, { signal: ctl.signal });
      if (res.status === 401) { S.user = null; renderAuth(); return; }
      if (!res.ok) throw new Error(res.status);
      const r = await res.json();
      if (CH.run !== my) return;
      fails = 0; chatApply(r);
    } catch (e) {
      if (CH.run !== my) return;
      fails++; await new Promise(ok => setTimeout(ok, Math.min(1000 * fails, 8000)));
    }
  }
}
const CHAT_EMOJIS = ['🔥', '💀', '😂', '👍', '❤️', '🫡', '💯'];
function chatFmt(t) {
  let h = esc(t);
  Object.values(CH.people).forEach(p => { const e = esc(p.display); if (e) h = h.split('@' + e).join(`<span class="men">@${e}</span>`); });
  return h;
}
function chatCtx() {
  const el = $('#chat_ctx'); if (!el) return;
  const who = id => (CH.people[id] || { display: 'Member' }).display;
  el.innerHTML = CH.edit ? '<div class="ctx"><span class="ell">✏️ Editing your message</span><button class="btn-s" data-act="chatCancel">✕</button></div>'
    : CH.reply ? `<div class="ctx"><span class="ell">↩ Replying to <b>${esc(who(CH.reply.uid))}</b>: ${esc(CH.reply.text)}</span><button class="btn-s" data-act="chatCancel">✕</button></div>` : '';
}
async function chatSend() {
  const ta = $('#chat_in'); if (!ta || chatSending) return;
  const text = ta.value.trim(); if (!text) return;
  chatSending = true;
  try {
    if (CH.edit) {
      const r = await api('chat/edit', { id: CH.edit, text });
      const m = CH.msgs.find(x => x.id === CH.edit); if (m) { m.text = r.text; m.edited = true; }
      CH.edit = null;
    } else {
      const r = await api('chat/send', { thread: CH.open, text, reply_to: CH.reply ? CH.reply.id : undefined });
      if (!CH.msgs.some(m => m.id === r.message.id)) CH.msgs.push(r.message);
      CH.reply = null;
    }
    ta.value = ''; ta.style.height = 'auto';
    chatCtx(); chatPaint(true);
  } catch (e) { } finally { chatSending = false; ta.focus(); }
}
function chatSel(el) { const id = +el.dataset.id; CH.sel = CH.sel === id ? null : id; chatPaint(false); }
async function chatReact(el) {
  const id = +el.dataset.id, e = el.dataset.e, m = CH.msgs.find(x => x.id === id); if (!m) return;
  m.re = m.re || {};
  if (m.mine) { m.re[m.mine] = (m.re[m.mine] || 1) - 1; if (!m.re[m.mine]) delete m.re[m.mine]; }
  if (m.mine === e) m.mine = undefined; else { m.re[e] = (m.re[e] || 0) + 1; m.mine = e; }
  if (!Object.keys(m.re).length) m.re = undefined;
  CH.sel = null; chatPaint(false);
  try { await api('chat/react', { id, emoji: e }); } catch (x) { }
}
function chatReply(el) {
  const m = CH.msgs.find(x => x.id === +el.dataset.id); if (!m) return;
  CH.reply = { id: m.id, uid: m.uid, text: m.text.slice(0, 90) }; CH.edit = null; CH.sel = null;
  chatPaint(false); chatCtx(); const ta = $('#chat_in'); if (ta) ta.focus();
}
function chatEdit(el) {
  const m = CH.msgs.find(x => x.id === +el.dataset.id); if (!m) return;
  CH.edit = m.id; CH.reply = null; CH.sel = null;
  const ta = $('#chat_in'); if (ta) { ta.value = m.text; ta.focus(); ta.style.height = 'auto'; ta.style.height = Math.min(ta.scrollHeight, 120) + 'px'; }
  chatPaint(false); chatCtx();
}
function chatCancel() { if (CH.edit) { const ta = $('#chat_in'); if (ta) ta.value = ''; } CH.edit = null; CH.reply = null; chatCtx(); }
function chatJump(el) {
  const t = document.querySelector(`[data-mid="${el.dataset.id}"]`);
  if (t) { t.scrollIntoView({ block: 'center' }); t.classList.add('flash'); setTimeout(() => t.classList.remove('flash'), 1300); } else toast('That message is further up', 'Tap "Load earlier messages"');
}
function chatMention(el) { const ta = $('#chat_in'); if (!ta) return; ta.value += (ta.value && !ta.value.endsWith(' ') ? ' ' : '') + '@' + el.dataset.v + ' '; ta.focus(); }
async function chatOlder() {
  const first = CH.msgs.length ? CH.msgs[0].id : 0; if (!first) return;
  try {
    const r = await api(`chat/messages?thread=${chatKey(CH.open)}&before=${first}`);
    const el = $('#chat_msgs'), h0 = el.scrollHeight;
    CH.msgs = r.messages.concat(CH.msgs); CH.more = r.more; Object.assign(CH.people, r.people);
    chatPaint(false); el.scrollTop = el.scrollHeight - h0;
  } catch (e) { }
}
Object.assign(A, {
  chatOpen(el) { return chatOpen(el.dataset.v); },
  async chatBack() { chatStop(); CH.open = null; try { await chatLoadThreads(); } catch (e) { } render(); },
  chatSend, chatOlder, chatSel, chatReact, chatReply, chatEdit, chatCancel, chatJump, chatMention,
  async chatDel(el) { if (!confirm('Delete this message for everyone?')) return; try { await api('chat/delete', { id: +el.dataset.id }); CH.msgs = CH.msgs.filter(m => m.id !== +el.dataset.id); chatPaint(false); } catch (e) { } },
  admin: adminOpen,
  async adminReset(el) { if (!confirm(`Reset PIN for @${el.dataset.v}? They get logged out.`)) return; try { const r = await api('admin/resetpin', { username: el.dataset.v }); prompt(`New PIN for ${r.username} (send it to them privately):`, r.pin); } catch (e) { } },
});
document.addEventListener('input', e => { if (e.target.id === 'chat_in') { e.target.style.height = 'auto'; e.target.style.height = Math.min(e.target.scrollHeight, 120) + 'px'; } });
document.addEventListener('keydown', e => { if (e.target.id === 'chat_in' && e.key === 'Enter' && !e.shiftKey && !e.isComposing && !matchMedia('(pointer:coarse)').matches) { e.preventDefault(); chatSend(); } });
document.addEventListener('visibilitychange', () => {
  if (document.hidden || !S.user || S.tab !== 'chat' || !CH.open || !CH.msgs.length) return;
  fetch('/api/chat/read', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ thread: CH.open, id: CH.msgs[CH.msgs.length - 1].id }) }).catch(() => { });
});
/* unread badge + alerts while you're anywhere except inside a conversation */
setInterval(async () => {
  if (!S.user || (S.tab === 'chat' && CH.open)) return;
  try {
    const res = await fetch('/api/chat/unread'); if (!res.ok) return;
    const r = await res.json(); CH.total = r.total; CH.unread = r.unread; chatBadge();
    if (r.latest && r.latest.id > CH.notified) {
      if (CH.notified && 'Notification' in window && Notification.permission === 'granted') new Notification(`💬 ${r.latest.from}`, { body: r.latest.text });
      CH.notified = r.latest.id;
    }
    if (S.tab === 'chat' && !CH.open && !document.hidden) { await chatLoadThreads(); render(); }
  } catch (e) { }
}, 12000);

/* ---------- admin dashboard (only for RAGDAMAXING_ADMINS) ---------- */
const fmUp = s => s >= 86400 ? Math.floor(s / 86400) + 'd ' + Math.floor(s % 86400 / 3600) + 'h' : s >= 3600 ? Math.floor(s / 3600) + 'h ' + Math.floor(s % 3600 / 60) + 'm' : Math.floor(s / 60) + 'm';
const admStat = (n, l) => `<div class="stat"><b>${n}</b><span class="xs mut">${l}</span></div>`;
let adminLastId = null, adminUser = '';
async function adminOpen() {
  try {
    const r = await api('admin/stats'); S.adm = r;
    modal(`<div class="row between"><h2>Server</h2><button class="btn-s ico" data-act="closeModal" aria-label="Close">${ic('x', 16)}</button></div>
      <div class="seg mt8" id="adminTabs">${[['overview', 'Overview'], ['activity', 'Activity'], ['xp', 'XP adjust'], ['moderate', 'Moderate']].map(([k, n]) => `<button class="${k === 'overview' ? 'on' : ''}" data-act="adminTab" data-v="${k}">${n}</button>`).join('')}</div>
      <div id="adminTabContent" class="mt12"></div>`);
    adminShowTab('overview');
  } catch (e) { }
}
function adminShowTab(tab) {
  $$('#adminTabs button').forEach(c => c.classList.toggle('on', c.dataset.v === tab));
  const r = S.adm, el = $('#adminTabContent'); if (!r || !el) return;
  const a = r.app, v = r.server;
  if (tab === 'overview') {
    el.innerHTML = `<div class="grid3">${admStat(a.users, 'users')}${admStat(a.active_today, 'active today')}${admStat(a.active_7d, 'active 7d')}${admStat(fm(a.focus_min_today), 'focus today')}${admStat(a.messages_today, 'msgs today')}${admStat(a.messages_total, 'msgs total')}</div>
      <div class="xs mut mt8" style="line-height:1.7">Up ${fmUp(v.uptime_s)} · RAM ${v.rss_mb ?? '?'} MB · load ${v.load.join(' ')} · DB ${v.db_kb} KB · disk free ${v.disk_free_gb}/${v.disk_total_gb} GB · ${v.threads} threads · python ${esc(v.python)} · build ${esc(v.version)} · ${esc(v.time)} ${esc(v.tz)}</div>
      <div class="lbl2">People</div>${r.users.map(u => `<div class="q"><div class="grow sm"><b>${esc(u.display)}</b> <span class="xs mut">@${esc(u.username)}${u.admin ? ' · admin' : ''}${u.banned ? ' · blocked' : ''}</span><div class="xs mut">${u.xp} XP (grind ${u.grind}) · last focus ${esc(u.last_focus || 'never')} · ${u.msgs} msgs</div></div><button class="btn-s" data-act="adminReset" data-v="${esc(u.username)}">Reset PIN</button></div>`).join('')}
      <a class="btn btn-xl c mt12" style="display:block;text-decoration:none" href="/api/admin/backup" download>Download database backup</a>`;
  } else if (tab === 'activity') {
    adminLoadActivity(true);
  } else if (tab === 'xp') {
    el.innerHTML = `<p class="sm mut">Positive adds, negative subtracts. Counts for the leaderboard unless "side XP" is ticked.</p>
      <select id="admXpUser">${r.users.map(u => `<option value="${u.id}">${esc(u.display)} (@${esc(u.username)}) · ${u.xp} XP</option>`).join('')}</select>
      <div class="grid2 mt8"><input id="admXpAmt" type="number" placeholder="Amount (500 or -200)"><input id="admXpReason" placeholder="Reason" maxlength="80"></div>
      <label class="row g8"><input id="admXpSide" type="checkbox" style="width:auto"> <span>Side XP (doesn't count for the leaderboard)</span></label>
      <button class="btn-p btn-xl mt12" data-act="adminXpSubmit">Apply</button>`;
  } else if (tab === 'moderate') {
    const rows = r.users.filter(u => u.id !== S.user.id && !u.admin);
    el.innerHTML = `<p class="sm mut">Block means they cannot log in. Kick removes them from the crew.</p>` + (rows.map(u => `<div class="q wrapq"><div class="grow sm"><b>${esc(u.display)}</b> <span class="xs mut">@${esc(u.username)}</span><div class="xs mut">${u.banned ? '<span class="bad">Blocked</span>' : 'Active'} · ${u.crew_id ? 'In crew' : 'No crew'} · ${u.xp} XP</div></div>
      <div class="row g4"><button class="btn-s ${u.banned ? 'btn-g' : 'btn-d'}" data-act="adminBlock" data-id="${u.id}" data-on="${u.banned ? 0 : 1}">${u.banned ? 'Unblock' : 'Block'}</button>${u.crew_id ? `<button class="btn-s btn-d" data-act="adminKick" data-id="${u.id}">Kick</button>` : ''}</div></div>`).join('') || '<div class="mut sm">No other users.</div>');
  }
}
async function adminLoadActivity(reset) {
  const el = $('#adminTabContent'); if (!el) return;
  if (reset) {
    adminLastId = null;
    el.innerHTML = `<div class="row g8"><select id="actFilterUser"><option value="">Everyone</option>${S.adm.users.map(u => `<option value="${u.id}" ${String(u.id) === adminUser ? 'selected' : ''}>${esc(u.display)}</option>`).join('')}</select></div>
      <div id="actList" class="mt8"></div><div class="c mt12"><button class="btn-s" id="actMore" data-act="adminActivityMore" disabled>Loading…</button></div>`;
  }
  try {
    const r = await api(`admin/activity?limit=100${adminUser ? '&user=' + adminUser : ''}${adminLastId ? '&before=' + adminLastId : ''}`);
    const list = $('#actList'); if (!list) return;
    r.events.forEach(ev => {
      list.insertAdjacentHTML('beforeend', `<div class="q wrapq"><div class="grow sm"><b>${esc(ev.display)}</b> <span class="xs mut">@${esc(ev.username)}</span>${ev.grind ? ' <span class="pill g">grind</span>' : ''}${ev.revoked ? ' <span class="pill d">revoked</span>' : ''}
        <div class="xs mut">${esc(ev.day)} ${esc(ev.ts.slice(11, 19))} · ${esc(ev.src)} · ${ev.amount > 0 ? '+' : ''}${ev.amount} XP · ${esc(ev.label)}</div></div>
        ${!ev.revoked && !ev.key.startsWith('admin:') && !ev.key.startsWith('adm0:') ? `<button class="btn-s btn-d" data-act="adminRevoke" data-id="${ev.id}">Revoke</button>` : ''}</div>`);
      adminLastId = ev.id;
    });
    const btn = $('#actMore'); if (btn) { btn.disabled = !r.more; btn.textContent = r.more ? 'Load more' : 'End of log'; }
  } catch (e) { }
}
Object.assign(A, {
  adminTab(el) { adminShowTab(el.dataset.v); },
  adminActivityMore() { return adminLoadActivity(false); },
  async adminXpSubmit() {
    const uid = +val('admXpUser'), amt = +val('admXpAmt'), reason = val('admXpReason'), side = $('#admXpSide').checked;
    if (!amt) return toast('Enter an amount');
    await api('admin/xp', { id: uid, amount: amt, reason, side }); toast('XP adjusted'); S.adm = await api('admin/stats'); adminShowTab('activity');
  },
  async adminBlock(el) { await api('admin/block', { id: +el.dataset.id, blocked: !!+el.dataset.on }); toast(+el.dataset.on ? 'Blocked' : 'Unblocked'); S.adm = await api('admin/stats'); adminShowTab('moderate'); },
  async adminKick(el) { if (!confirm('Kick from crew? They cannot rejoin with the same code.')) return; await api('admin/kick', { id: +el.dataset.id }); toast('Kicked'); S.adm = await api('admin/stats'); adminShowTab('moderate'); },
  async adminRevoke(el) { if (!confirm('Revoke this XP event? This adds a negative entry to undo it.')) return; await api('admin/revoke', { id: +el.dataset.id }); toast('Revoked'); adminLoadActivity(true); },
});
document.addEventListener('change', e => { if (e.target.id === 'actFilterUser') { adminUser = e.target.value; adminLoadActivity(true); } });

/* ---------- live presence: refresh the visible tab without ever interrupting you ---------- */
let seenLive = new Set();
setInterval(async () => {
  if (!S.user || document.hidden || S.fs) return;
  const ae = document.activeElement, typing = ae && /INPUT|TEXTAREA|SELECT/.test(ae.tagName);
  if (typing || S.urge || modalOpen() || Date.now() - S.lastPtr < 2500) return;
  try {
    if (S.tab === 'today') {
      const t = await api('today'), running = !!(S.today?.timer || S.today?.pomo);
      setToday(t);
      t.live.forEach(l => { const k = l.display + l.subject; if (!seenLive.has(k) && 'Notification' in window && Notification.permission === 'granted') new Notification(`${l.display} is locked in on ${l.subject}`, { body: 'Join them. Start a block.' }); seenLive.add(k); });
      if (!(running && (t.timer || t.pomo))) render();
    } else if (S.tab === 'crew') { S.crew = await api('crew'); render(); }
  } catch (e) { }
}, 25000);

boot();
