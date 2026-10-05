'use strict';
/* OUTGROW front-end. Vanilla JS, no build step. */
const $ = (s, r = document) => r.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fm = m => { m = Math.round(m || 0); return m >= 60 ? `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, '0')}m` : `${m}m`; };
const SUBS = ['Physics', 'Chemistry', 'Maths', 'English', 'Other'];
const SCOL = { Physics: '#3ea6ff', Chemistry: '#22d3a6', Maths: '#ffb020', English: '#ff5c8a', Other: '#9aa0b4' };
const S = { tab: 'today', sub: 'chapters', user: null, today: null, crew: null, syl: null, tests: null, ins: null, refl: null, weekly: null, pickSub: 'Physics', pickDur: 25, authMode: 'login', t0: 0, beeped: false, urge: null };

/* ---------- api ---------- */
async function api(path, body) {
  const r = await fetch('/api/' + path, { method: body === undefined ? 'GET' : 'POST', headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) });
  const j = await r.json().catch(() => ({}));
  if (r.status === 401) { S.user = null; renderAuth(); throw new Error('login'); }
  if (!r.ok) { toast(j.error || 'Something broke', '', 'err'); throw new Error(j.error || 'error'); }
  if (j.events && j.events.length) handleEvents(j.events);
  return j;
}

/* ---------- feedback: toasts, confetti, sound ---------- */
function toast(t, sub = '', cls = '') {
  const d = document.createElement('div'); d.className = 'toast ' + cls; d.innerHTML = esc(t) + (sub ? `<small>${esc(sub)}</small>` : '');
  $('#toasts').appendChild(d); setTimeout(() => d.remove(), 3700);
}
function confetti() {
  const cols = ['#7c5cff', '#22d3a6', '#ffb020', '#ff5c8a', '#3ea6ff'];
  for (let i = 0; i < 46; i++) {
    const s = document.createElement('i'); s.className = 'confetti';
    s.style.left = Math.random() * 100 + 'vw'; s.style.background = cols[i % 5]; s.style.animationDelay = Math.random() * .6 + 's'; s.style.transform = `rotate(${Math.random() * 360}deg)`;
    document.body.appendChild(s); setTimeout(() => s.remove(), 3200);
  }
}
function beep() {
  try {
    const a = new (window.AudioContext || window.webkitAudioContext)();
    [0, .22, .44].forEach((t, i) => { const o = a.createOscillator(), g = a.createGain(); o.frequency.value = 660 + i * 220; g.gain.value = .16; o.connect(g); g.connect(a.destination); o.start(a.currentTime + t); o.stop(a.currentTime + t + .16); });
    if (navigator.vibrate) navigator.vibrate([200, 100, 200]);
  } catch (e) { }
}
function handleEvents(evs) {
  const xp = evs.filter(e => e.t === 'xp');
  if (xp.length) { const sum = xp.reduce((a, e) => a + e.amount, 0); toast(`+${sum} XP`, xp.slice(0, 3).map(e => e.label).join(' · ')); }
  evs.filter(e => e.t === 'badge').forEach(e => { toast(`${e.emoji} ${e.name}`, e.desc, 'badge'); confetti(); });
  const lu = evs.find(e => e.t === 'levelup');
  if (lu) { confetti(); modal(`<div class="c"><div class="big">LEVEL ${lu.level}</div><h2 style="color:var(--acc2)">${esc(lu.rank)}</h2><p class="mut">Another vote for the person you're becoming.</p><button class="btn-p btn-xl" data-act="closeModal">Keep going</button></div>`); }
}
function modal(html) { const m = $('#modal'); m.innerHTML = `<div>${html}</div>`; m.classList.remove('hidden'); }
function closeModal() { $('#modal').classList.add('hidden'); $('#modal').innerHTML = ''; }

/* ---------- svg helpers ---------- */
function bars(vals, color, h = 70) {
  const mx = Math.max(...vals, 1), w = 100 / vals.length;
  return `<svg class="chart" viewBox="0 0 100 ${h}" preserveAspectRatio="none">` + vals.map((v, i) => { const bh = Math.max(v / mx * (h - 2), v ? 2 : 1); return `<rect x="${i * w + w * .15}" y="${h - bh}" width="${w * .7}" height="${bh}" rx="1" fill="${color}" opacity="${v ? 1 : .2}"/>`; }).join('') + '</svg>';
}
function lines(series, h = 60) {
  const all = series.flatMap(s => s.v.filter(x => x != null)); const mx = Math.max(...all, 1);
  return `<svg class="chart" viewBox="0 0 100 ${h}" preserveAspectRatio="none">` + series.map(s => {
    const pts = s.v.map((x, i) => x == null ? null : `${s.v.length > 1 ? i / (s.v.length - 1) * 100 : 50},${h - 3 - x / mx * (h - 8)}`).filter(Boolean).join(' ');
    return `<polyline points="${pts}" fill="none" stroke="${s.c}" stroke-width="${s.w || 2}" stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke" ${s.d ? 'stroke-dasharray="4 4"' : ''}/>`;
  }).join('') + '</svg>';
}

/* ---------- auth ---------- */
function renderAuth() {
  const reg = S.authMode === 'register';
  $('#app').innerHTML = `<div class="auth"><div class="logo">OUTGROW</div>
  <p class="mut">The old you was an A+ student. The next one outgrows them. Track it. Prove it. Together.</p>
  <div class="card col">
    <input id="a_user" placeholder="Username" autocapitalize="off" autocomplete="username">
    <input id="a_pin" type="password" placeholder="PIN / password (4+ chars)" autocomplete="${reg ? 'new-password' : 'current-password'}">
    ${reg ? `<input id="a_code" placeholder="Crew invite code (from a friend)" autocapitalize="characters"><div class="mut sm c">— or —</div><input id="a_cname" placeholder="Start a new crew (name)">` : ''}
    <button class="btn-p btn-xl" data-act="${reg ? 'register' : 'login'}">${reg ? 'Join the grind' : 'Log in'}</button>
    <button data-act="authMode">${reg ? 'I already have an account' : 'New here? Create account'}</button>
  </div></div>`;
  $('#modal').classList.add('hidden'); document.querySelector('.nav')?.remove();
}

/* ---------- boot ---------- */
async function boot() {
  try { const me = await api('me'); S.user = me.user; await go(S.tab); if (!S.user.onboarded) onboard(); }
  catch (e) { if (!S.user) renderAuth(); }
}
async function go(tab) {
  S.tab = tab;
  chatStop(); if (tab === 'chat') CH.open = null;
  try {
    if (tab === 'today') S.today = await api('today');
    if (tab === 'crew') S.crew = await api('crew');
    if (tab === 'study') {
      const [syl, te] = await Promise.all([api('syllabus'), api('tests')]); S.syl = syl; S.tests = te;
      S.ins = S.ins || await api('insights');
    }
    if (tab === 'reflect') { const [r, w] = await Promise.all([api('reflect'), api('weekly')]); S.refl = r; S.weekly = w; }
    if (tab === 'me') S.ins = await api('insights');
    if (tab === 'chat') await chatLoadThreads();
  } catch (e) { if (e.message === 'login') return; }
  render(); window.scrollTo(0, 0);
}
function render() {
  if (!S.user) return renderAuth();
  const v = { today: vToday, crew: vCrew, chat: vChat, study: vStudy, reflect: vReflect, me: vMe }[S.tab]();
  const tabs = [['today', '⚡', 'Today'], ['crew', '👥', 'Crew'], ['chat', '💬', 'Chat'], ['study', '📚', 'Study'], ['reflect', '🪞', 'Reflect'], ['me', '🧬', 'Me']];
  $('#app').innerHTML = v + (S.tab === 'today' ? '<button class="fab" data-act="urge">🧠 I\'m tempted</button>' : '');
  document.querySelector('.nav')?.remove();
  const nav = document.createElement('div'); nav.className = 'nav';
  nav.innerHTML = '<div>' + tabs.map(t => `<button class="${S.tab === t[0] ? 'on' : ''}" data-act="tab" data-v="${t[0]}"><span>${t[1]}</span>${t[2]}${t[0] === 'chat' && CH.total ? `<i class="nb">${CH.total > 9 ? '9+' : CH.total}</i>` : ''}</button>`).join('') + '</div>';
  document.body.appendChild(nav);
  if (S.tab === 'chat') chatAfterRender();
  if (S.tab === 'today' && S.today?.timer) { S.t0 = Date.now() - S.today.timer.elapsed * 1000; S.beeped = S.today.timer.elapsed >= S.today.timer.target * 60; tick(); }
}

/* ---------- TODAY ---------- */
function vToday() {
  const T = S.today, L = T.level, sv = T.streak, u = T.user;
  const floor = T.daily_min, stretch = Math.max(T.stretch_min, floor * 2), m = T.today.total;
  const ex = T.exams[0];
  let h = `<div class="card glow"><div class="row between"><div><div class="xs mut">${esc(u.emoji)} ${esc(u.display)} · LEVEL ${L.level}</div><h2 style="font-size:22px">${esc(L.rank)}</h2></div>
    <div class="c"><div style="font-size:30px">${sv.at_risk ? '⏳' : '🔥'}</div><div class="b">${sv.now}</div><div class="xs mut">day streak</div></div></div>
    <div class="bar" style="margin:10px 0 4px"><i style="width:${L.pct}%"></i></div>
    <div class="row between xs mut"><span>${L.xp - L.lo} / ${L.hi - L.lo} XP to next level</span><span>❄️ ${sv.freezes} freeze${sv.freezes === 1 ? '' : 's'} · +${T.xp_today} XP today</span></div>
    ${u.identity ? `<div class="quote">I am ${esc(u.identity)}</div>` : ''}
    ${ex ? `<div class="row wrap" style="gap:6px;margin-top:4px">${T.exams.map(e => `<span class="pill">${esc(e.name)} · ${e.days_left}d</span>`).join('')}</div>` : ''}</div>`;
  T.banners.forEach(b => h += `<div class="banner ${b.kind}">${esc(b.text)}</div>`);
  if (T.live.length) h += `<div class="live-strip"><span class="dot live"></span> <b>${T.live.map(l => `${esc(l.display)} (${esc(l.subject)} · ${fm(l.elapsed / 60)})`).join(', ')}</b> ${T.live.length > 1 ? 'are' : 'is'} locked in right now.${T.timer ? '' : ' Join them — start a block.'}</div>`;
  /* focus card */
  if (T.timer) {
    const tm = T.timer;
    h += `<div class="card glow c"><h3>${esc(tm.subject)} · ${tm.target} min block</h3>
      <div class="ring"><svg width="210" height="210" viewBox="0 0 210 210"><circle cx="105" cy="105" r="94" stroke="#222234" stroke-width="12" fill="none"/><circle id="ringc" cx="105" cy="105" r="94" stroke="${SCOL[tm.subject]}" stroke-width="12" fill="none" stroke-linecap="round" stroke-dasharray="590.6" stroke-dashoffset="590.6"/></svg>
      <div class="in"><div class="clock" id="clock" style="font-size:52px">--:--</div><div class="xs mut" id="tsub"></div></div></div>
      <div class="row wrap" style="justify-content:center;margin-top:6px"><button data-act="distract">😵 Lost focus (<span id="dcount">${tm.distractions}</span>)</button></div>
      <p class="xs mut" id="tmsg">Phone away. One tab. Pen in hand.</p>
      <div class="row"><button class="btn-g grow" data-act="stopTimer">✅ Finish & log</button><button class="btn-d" data-act="discard">Discard</button></div></div>`;
  } else {
    h += `<div class="card"><h3>Start a focus block</h3><div class="row wrap" style="margin:10px 0">${SUBS.map(s => `<span class="chip ${S.pickSub === s ? 'on' : ''}" data-act="pickSub" data-v="${s}">${s}</span>`).join('')}</div>
      <div class="row wrap" style="margin-bottom:12px">${[25, 50, 90].map(d => `<span class="chip ${S.pickDur === d ? 'on' : ''}" data-act="pickDur" data-v="${d}">${d} min</span>`).join('')}</div>
      <button class="btn-p btn-xl" data-act="startTimer">▶ START ${S.pickSub.toUpperCase()}</button>
      <button class="btn-xl" style="margin-top:8px;padding:12px;font-size:15px" data-act="start5">😮‍💨 Can't start? Just 5 minutes. That's the deal.</button>
      <details><summary>Studied offline? Log it (counts half XP)</summary>
        <div class="row"><select id="mf_s">${SUBS.map(s => `<option ${s === S.pickSub ? 'selected' : ''}>${s}</option>`).join('')}</select><input id="mf_m" type="number" inputmode="numeric" placeholder="min" style="width:90px"><button data-act="manual">Log</button></div></details></div>`;
  }
  /* progress toward floor / old-self stretch */
  h += `<div class="card"><div class="row between"><h3>Today</h3><b>${fm(m)}</b></div>
    <div class="bar ${m >= floor ? 'g' : ''}" style="margin:10px 0 6px"><i style="width:${Math.min(m / stretch * 100, 100)}%"></i><span class="tick" style="left:${floor / stretch * 100}%"></span></div>
    <div class="row between xs mut"><span>${sv.qualified ? '✅ Floor hit — streak safe' : `Floor: ${floor} min (${Math.max(floor - m, 0)} to go)`}</span><span>Old-you bar: ${fm(T.stretch_min)}</span></div>
    ${Object.keys(T.today.sub).length ? `<div class="row wrap" style="margin-top:8px;gap:6px">${Object.entries(T.today.sub).map(([s, mm]) => `<span class="pill" style="background:${SCOL[s]}33;color:${SCOL[s]}">${s} ${fm(mm)}</span>`).join('')}</div>` : ''}
    <div class="xs mut" style="margin-top:6px">Streak days need ${floor} min with half of it on the timer.</div></div>`;
  if (T.chest.available) h += `<div class="card glow c"><div style="font-size:44px">🎁</div><div class="b">Daily chest unlocked</div><div class="xs mut">Mystery reward. Rare ones are rarer.</div><button class="btn-p" style="margin-top:8px" data-act="chest">Open it</button></div>`;
  else if (T.chest.opened) h += `<div class="card c xs mut">🎁 Today's chest: <b style="color:var(--tx)">${esc(T.chest.reward)}</b></div>`;
  /* quests */
  h += `<div class="card"><h3>Daily quests</h3>${T.quests.map(q => `<div class="q"><div class="chk ${q.done ? 'on' : ''}">${q.done ? '✓' : ''}</div><div class="grow">${esc(q.text)}<div class="bar" style="height:5px;margin-top:5px"><i style="width:${Math.min(q.prog / Math.max(q.goal, 1) * 100, 100)}%"></i></div></div><span class="pill">+${q.xp}</span></div>`).join('')}</div>`;
  /* plan */
  h += `<div class="card"><h3>Today's promises</h3>${T.plan.length ? T.plan.map(p => `<div class="q"><div class="chk ${p.done ? 'on' : ''}" data-act="togglePlan" data-id="${p.id}">${p.done ? '✓' : ''}</div><div class="grow ${p.done ? 'mut' : ''}">${esc(p.text)}${p.cue ? `<div class="xs mut">↳ ${esc(p.cue)}</div>` : ''}</div><button class="btn-s" data-act="delPlan" data-id="${p.id}">✕</button></div>`).join('') : '<div class="mut sm" style="padding:6px 0">Nothing planned. A plan made at night beats willpower in the morning.</div>'}
    <details><summary>+ Add a promise (with an if-then cue)</summary><input id="pl_t" placeholder="e.g. Integration Ex 7.2 Q1-10"><div style="height:6px"></div><input id="pl_c" placeholder="When/where? e.g. 6 PM at my desk, phone in other room"><div class="row" style="margin-top:8px"><button class="grow" data-act="addPlan" data-v="today">Add for today</button><button class="grow" data-act="addPlan" data-v="tomorrow">Add for tomorrow</button></div></details>
    ${T.plan_tomorrow.length ? `<div class="xs mut" style="margin-top:6px">Tomorrow: ${T.plan_tomorrow.map(p => esc(p.text)).join(' · ')}</div>` : ''}</div>`;
  if (T.due.length) h += `<div class="card"><div class="row between"><h3>🔁 Revise now (${T.due.length})</h3><button class="btn-s" data-act="tab" data-v="study" data-sub="revise">Open</button></div>${T.due.slice(0, 3).map(d => `<div class="q"><div class="grow"><b>${esc(d.name)}</b> <span class="xs mut">${d.subject}</span></div></div>`).join('')}</div>`;
  h += `<div class="card"><h3>Body & discipline</h3><div class="row wrap" style="margin-top:10px">${T.habit_defs.map(x => `<span class="chip ${T.habits.includes(x.id) ? 'on' : ''}" data-act="habit" data-id="${x.id}">${x.emoji} ${esc(x.name)} <span class="xs" style="opacity:.7">+${x.xp}</span></span>`).join('')}</div></div>`;
  if (T.sessions.length) h += `<div class="card"><h3>Today's blocks</h3>${T.sessions.map(s => `<div class="q"><span class="dot" style="background:${SCOL[s.subject]}"></span><div class="grow">${esc(s.subject)}</div><b>${fm(s.minutes)}</b><span class="xs mut">${s.kind === 'timer' ? '⏱ verified' : '✍️ manual'}</span>${s.kind === 'manual' ? `<button class="btn-s" data-act="delFocus" data-id="${s.id}">✕</button>` : ''}</div>`).join('')}</div>`;
  return h;
}
function tick() {
  const tm = S.today?.timer; if (!tm || S.tab !== 'today') return;
  const el = (Date.now() - S.t0) / 1000, tot = tm.target * 60, rem = tot - el;
  const c = $('#clock'); if (!c) return;
  const a = Math.abs(rem), mm = Math.floor(a / 60), ss = Math.floor(a % 60);
  c.textContent = (rem < 0 ? '+' : '') + String(mm).padStart(2, '0') + ':' + String(ss).padStart(2, '0');
  $('#ringc').style.strokeDashoffset = 590.6 * (1 - Math.min(el / tot, 1));
  $('#tsub').textContent = rem < 0 ? 'overtime — bonus focus' : `${Math.floor(el / 60)} min in`;
  if (rem <= 0 && !S.beeped) {
    S.beeped = true; beep();
    $('#tmsg').innerHTML = tm.target <= 5 ? '<b>5 minutes done. The hard part is over.</b> <button class="btn-p btn-s" data-act="extend">Keep going +20</button>' : '<b>Block complete.</b> Log it, then take a real break.';
  }
  clearTimeout(S._tt); S._tt = setTimeout(tick, 500);
}

/* ---------- CREW ---------- */
function vCrew() {
  const C = S.crew;
  if (!C.crew) return `<div class="card"><h2>No crew yet</h2><p class="mut">Competition works. Join your friends.</p><input id="cj" placeholder="Invite code"><div style="height:8px"></div><button class="btn-p btn-xl" data-act="joinCrew">Join crew</button><div class="mut c sm" style="margin:10px 0">— or —</div><input id="cn" placeholder="New crew name"><div style="height:8px"></div><button class="btn-xl" data-act="createCrew">Create crew</button></div>`;
  const me = C.members.find(m => m.me);
  const tp = Math.min(C.team.minutes / Math.max(C.team.goal, 1) * 100, 100);
  let h = `<div class="card glow"><div class="row between"><div><h2>${esc(C.crew.name)}</h2><div class="xs mut">Invite code: <b style="color:var(--acc2);letter-spacing:.15em" data-act="copy" data-v="${esc(C.crew.code)}">${esc(C.crew.code)}</b> (tap to copy)</div></div><div class="c"><div class="xs mut">YOUR RANK</div><div class="big" style="font-size:30px">#${me.rank}</div></div></div>
    ${C.rival ? `<div class="sm" style="margin-top:8px">${C.rival.dir === 'ahead' ? `🎯 <b>${esc(C.rival.name)}</b> is <b>${C.rival.gap} XP</b> ahead of you this week. One deep block closes it.` : `🛡️ <b>${esc(C.rival.name)}</b> is only <b>${C.rival.gap} XP</b> behind. Don't coast.`}</div>` : ''}</div>`;
  h += `<div class="card"><div class="row between"><h3>Crew weekly goal</h3><b>${fm(C.team.minutes)} / ${fm(C.team.goal)}</b></div><div class="bar o" style="margin:10px 0 4px"><i style="width:${tp}%"></i></div><div class="xs mut">Hit it together = +100 XP each (you must log 5h+ yourself to share the loot). Nobody free-rides.</div></div>`;
  h += `<div class="card"><h3>This week's league</h3><table class="tbl">${C.members.map(m => {
    const st = m.live ? '<span class="dot live"></span>' : m.qualified ? '<span class="dot g"></span>' : m.today_min > 0 ? '<span class="dot y"></span>' : '<span class="dot"></span>';
    return `<tr><td style="width:22px" class="mut">${m.rank}</td><td style="width:42px"><div class="av" style="background:${m.color}33;border:2px solid ${m.color}">${esc(m.emoji)}</div></td>
      <td><b>${esc(m.display)}${m.me ? ' (you)' : ''}</b> ${st}<div class="xs mut">Lv ${m.level.level} ${esc(m.level.rank)} · 🔥${m.streak} · today ${fm(m.today_min)}${m.live ? ` · <span style="color:var(--good)">live: ${esc(m.live.subject)}</span>` : ''}</div></td>
      <td class="c"><b>${m.week_xp}</b><div class="xs mut">XP · ${fm(m.week_min)}</div></td>
      <td style="width:50px">${!m.me && !m.qualified ? `<button class="btn-s" ${m.nudged ? 'disabled style="opacity:.4"' : ''} data-act="nudge" data-id="${m.id}">👊</button>` : ''}</td></tr>`;
  }).join('')}</table><div class="xs mut">● live now · ● floor hit · ● some work · ○ nothing yet. 👊 = nudge (+5 XP for you). League resets every Monday: fresh start for everyone.</div></div>`;
  const others = C.members.filter(m => !m.me);
  h += `<div class="card"><div class="row between"><h3>⚔️ Duels</h3></div>${C.duels.length ? C.duels.map(d => `<div class="q"><div class="grow"><b>${esc(d.an)}</b> vs <b>${esc(d.bn)}</b> <span class="xs mut">${d.days}d · most focus minutes wins</span>${d.status === 'active' ? `<div class="xs">${fm(d.a_min)} — ${fm(d.b_min)} · ends ${d.end}</div>` : '<div class="xs mut">waiting for accept…</div>'}</div>${d.status === 'pending' && d.b === C.me ? `<button class="btn-p btn-s" data-act="acceptDuel" data-id="${d.id}">Accept</button>` : ''}</div>`).join('') : '<div class="mut sm">No duels. Pick a victim.</div>'}
    ${others.length ? `<div class="row" style="margin-top:8px"><select id="du_o">${others.map(m => `<option value="${m.id}">${esc(m.display)}</option>`).join('')}</select><select id="du_d" style="width:90px"><option value="3">3d</option><option value="7" selected>7d</option><option value="14">14d</option></select><button data-act="duel">Challenge</button></div>` : ''}</div>`;
  h += `<div class="card"><h3>Crew feed</h3>${C.feed.length ? C.feed.map(f => `<div class="feed"><div class="row"><div class="av" style="width:28px;height:28px;font-size:14px;background:${f.color}33">${esc(f.emoji)}</div><div class="grow sm"><b>${esc(f.display)}</b> ${esc(f.text)}</div><span class="xs mut">${ago(f.ts)}</span></div>
    <div>${['🔥', '💪', '👏', '😤', '🫡'].map(e => `<span class="rx ${f.mine === e ? 'me' : ''}" data-act="react" data-id="${f.id}" data-e="${e}">${e}${f.reactions[e] ? ' ' + f.reactions[e] : ''}</span>`).join('')}</div></div>`).join('') : '<div class="mut sm">Quiet. Be the first to move.</div>'}</div>`;
  return h;
}
function ago(ts) { const s = (Date.now() - new Date(ts).getTime()) / 1000; if (s < 90) return 'now'; if (s < 3600) return Math.floor(s / 60) + 'm'; if (s < 86400) return Math.floor(s / 3600) + 'h'; return Math.floor(s / 86400) + 'd'; }

/* ---------- STUDY (syllabus / revise / tests) ---------- */
function vStudy() {
  const tabs = [['chapters', '📖 Chapters'], ['revise', '🔁 Revise'], ['tests', '📝 Tests']];
  let h = `<div class="sub-tabs">${tabs.map(t => `<span class="chip ${S.sub === t[0] ? 'on' : ''}" data-act="sub" data-v="${t[0]}">${t[1]}</span>`).join('')}</div>`;
  if (S.sub === 'chapters') {
    const chs = S.syl.chapters, ins = S.ins, ch = ins?.chapters;
    if (ch) h += `<div class="card glow"><h3>Syllabus war map</h3><div class="grid3" style="margin-top:10px"><div class="stat"><b>${ch.left}</b><span class="xs mut">untouched</span></div><div class="stat"><b>${ch.learned}</b><span class="xs mut">learned</span></div><div class="stat"><b>${ch.mastered}</b><span class="xs mut">mastered</span></div></div>
      ${ins.exams.map(e => `<div class="sm" style="margin-top:8px">${esc(e.name)}: <b>${e.days_left} days</b> → you need <b>${e.need_per_week}</b> new chapters/week. Current pace: <b>${ch.rate.toFixed(1)}</b>/week. ${ch.rate >= e.need_per_week ? '✅ On pace.' : '⚠️ Behind pace — go narrower on weightage, wider on PYQs.'}</div>`).join('')}</div>`;
    h += `<div class="xs mut" style="margin:4px 2px">Tap 📖 learned → 🔁 revisions auto-schedule (day 1, 3, 7, 14, 30). ✍️ practiced · 🏆 mastered (scored well in a test).</div>`;
    ['Physics', 'Chemistry', 'Maths', 'English', 'Other'].forEach(sub => {
      const list = chs.filter(c => c.subject === sub); if (!list.length) return;
      const l = list.filter(c => c.status >= 1).length, mst = list.filter(c => c.status >= 3).length;
      h += `<div class="card"><div class="row between"><h2 style="color:${SCOL[sub]}">${sub}</h2><span class="xs mut">${l}/${list.length} learned · ${mst} mastered</span></div><div class="bar" style="margin:8px 0"><i style="width:${l / list.length * 100}%;background:${SCOL[sub]}"></i></div>`;
      ['11', '12', '+'].forEach(g => {
        const gl = list.filter(c => c.grade === g); if (!gl.length) return;
        h += `<div class="xs mut" style="margin-top:8px">${g === '+' ? 'ADDED BY YOU' : 'CLASS ' + g}</div>` + gl.map(c => `<div class="ch"><div class="grow ${c.status >= 3 ? 'mut' : ''}">${esc(c.name)}</div><div class="st">${[[1, '📖'], [2, '✍️'], [3, '🏆']].map(([n, e]) => `<button class="${c.status >= n ? 'on' : ''}" data-act="chap" data-id="${c.id}" data-s="${c.status === n ? n - 1 : n}">${e}</button>`).join('')}</div></div>`).join('');
      });
      h += `<details><summary>+ add a chapter/topic to ${sub}</summary><div class="row"><input id="ca_${sub}" placeholder="Name"><button data-act="addChap" data-v="${sub}">Add</button></div></details></div>`;
    });
  }
  if (S.sub === 'revise') {
    const due = S.syl.revisions.filter(r => r.due <= S.syl.today), up = S.syl.revisions.filter(r => r.due > S.syl.today);
    h += `<div class="card glow"><h3>Active recall queue</h3><p class="sm mut">Close the book. Write everything you remember for 3 minutes. Then rate honestly — honest "blank" ratings are what make you win.</p>
      ${due.length ? due.map(r => `<div class="q" style="flex-wrap:wrap"><div class="grow"><b>${esc(r.name)}</b> <span class="xs mut">${r.subject} · review #${r.stage + 1}${r.due < S.syl.today ? ' · overdue' : ''}</span></div><div class="row"><button class="btn-g btn-s" data-act="rev" data-id="${r.id}" data-r="solid">✅ Solid</button><button class="btn-s" data-act="rev" data-id="${r.id}" data-r="shaky">😬 Shaky</button><button class="btn-d btn-s" data-act="rev" data-id="${r.id}" data-r="blank">❌ Blank</button></div></div>`).join('') : '<div class="c" style="padding:16px">🎉 Nothing due. Learn something new → it will be scheduled.</div>'}</div>`;
    if (up.length) h += `<div class="card"><h3>Coming up</h3>${up.slice(0, 12).map(r => `<div class="q"><div class="grow">${esc(r.name)} <span class="xs mut">${r.subject}</span></div><span class="xs mut">${r.due}</span></div>`).join('')}</div>`;
  }
  if (S.sub === 'tests') {
    const T = S.tests, ts = T.tests, pct = ts.map(t => Math.round(t.score / t.maxscore * 100));
    h += `<div class="card"><h3>Log a test / PYQ paper</h3><div class="grid2"><div><label>Name</label><input id="t_n" placeholder="Mock 3 / PYQ 2024"></div><div><label>Subject</label><select id="t_s"><option>All</option>${SUBS.map(s => `<option>${s}</option>`).join('')}</select></div>
      <div><label>Score</label><input id="t_sc" type="number" inputmode="decimal"></div><div><label>Out of</label><input id="t_mx" type="number" inputmode="decimal" value="300"></div></div>
      <label>Where did you lose marks? (count of questions)</label><div class="grid3"><input id="t_c" type="number" inputmode="numeric" placeholder="Concept gap"><input id="t_si" type="number" inputmode="numeric" placeholder="Silly mistake"><input id="t_t" type="number" inputmode="numeric" placeholder="Ran out of time"></div>
      <div style="height:10px"></div><button class="btn-p btn-xl" data-act="addTest">Save (+80 XP)</button></div>`;
    if (pct.length > 1) h += `<div class="card"><h3>Score trend</h3>${lines([{ v: pct, c: '#22d3a6', w: 2.5 }])}<div class="row between xs mut"><span>${pct[0]}%</span><span>latest ${pct[pct.length - 1]}% (${pct[pct.length - 1] - pct[0] >= 0 ? '+' : ''}${pct[pct.length - 1] - pct[0]} since first)</span></div></div>`;
    const e = T.errors, tot = e.concept + e.silly + e.time;
    if (tot) {
      const top = Object.entries(e).sort((a, b) => b[1] - a[1])[0][0];
      const advice = { concept: 'Most lost marks are CONCEPT gaps. Stop doing new questions. Re-learn the 3 weakest chapters, then do 10 PYQs per chapter.', silly: 'Most lost marks are SILLY mistakes — you know it, you botched it. Fix process: circle units/signs, re-read the question, reserve 10 min at the end to re-check.', time: 'Most lost marks are TIME. Practice in timed sections, skip-and-return, and stop sinking 6 minutes into one question.' }[top];
      h += `<div class="card"><h3>Error autopsy (last 8 tests)</h3><div class="grid3" style="margin:10px 0"><div class="stat"><b>${e.concept}</b><span class="xs mut">concept</span></div><div class="stat"><b>${e.silly}</b><span class="xs mut">silly</span></div><div class="stat"><b>${e.time}</b><span class="xs mut">time</span></div></div><div class="sm">${advice}</div></div>`;
    }
    h += `<div class="card"><h3>History</h3>${ts.length ? ts.slice().reverse().map(t => `<div class="q"><div class="grow">${esc(t.name)} <span class="xs mut">${t.subject} · ${t.day}</span></div><b>${t.score}/${t.maxscore}</b><span class="pill">${Math.round(t.score / t.maxscore * 100)}%</span></div>`).join('') : '<div class="mut sm">No tests yet. Feelings lie; scores don\'t.</div>'}</div>`;
  }
  return h;
}

/* ---------- REFLECT ---------- */
function vReflect() {
  const R = S.refl, W = S.weekly, t = R.today, miss = R.minutes < R.daily_min;
  const moodRow = (id, v) => `<div class="mood" id="${id}">${['😞', '😕', '😐', '🙂', '😄'].map((e, i) => `<span class="${(v || 3) === i + 1 ? 'on' : ''}" data-act="mood" data-g="${id}" data-v="${i + 1}">${e}</span>`).join('')}</div>`;
  let h = `<div class="card glow"><h2>Tonight's reflection</h2><p class="sm mut">60 seconds. Not a diary — a debugging session. ${t ? '<b style="color:var(--good)">Done for today ✓ (you can edit it).</b>' : '+40 XP'}</p>
    <label>Mood</label>${moodRow('f_mood', t?.mood)}<label>Energy</label>${moodRow('f_energy', t?.energy)}
    <label>One specific WIN today (small counts: "did 12 integration problems")</label><textarea id="f_win">${esc(t?.win || '')}</textarea>
    <label>Where did time leak, and what triggered it? (describe, don't judge)</label><textarea id="f_leak">${esc(t?.leak || '')}</textarea>
    ${miss ? `<label>You're under your floor today. What would you say to a friend in your exact spot?</label><textarea id="f_kind" placeholder="Kind, specific, forward-looking.">${esc(t?.kind_note || '')}</textarea>` : `<input type="hidden" id="f_kind" value="${esc(t?.kind_note || '')}">`}
    <label>Tomorrow's ONE thing (becomes a promise)</label><input id="f_tom" value="${esc(t?.tomorrow || '')}" placeholder="e.g. Integration by parts, 15 problems">
    <label>When & where exactly? (implementation intention)</label><input id="f_cue" placeholder="After breakfast, desk, phone in the other room"><div style="height:12px"></div><button class="btn-p btn-xl" data-act="saveReflect">Save reflection</button></div>`;
  const s = W.summary, ex = W.existing, d = s.minutes - s.prev_minutes;
  h += `<div class="card"><h2>Weekly review</h2><p class="sm mut">Week of ${s.week}. The data first, then the decision. +100 XP.</p><div class="grid3" style="margin:10px 0"><div class="stat"><b>${fm(s.minutes)}</b><span class="xs mut">focus</span></div><div class="stat"><b>${s.qualified_days}/7</b><span class="xs mut">floor days</span></div><div class="stat"><b>${d >= 0 ? '+' : ''}${fm(Math.abs(d)).replace(/^/, d < 0 ? '-' : '')}</b><span class="xs mut">vs last wk</span></div></div>
    ${Object.keys(s.by_subject).length ? `<div class="row wrap" style="gap:6px">${Object.entries(s.by_subject).map(([k, v]) => `<span class="pill" style="background:${SCOL[k]}33;color:${SCOL[k]}">${k} ${fm(v)}</span>`).join('')}</div>` : ''}
    <label>Best moment of the week</label><input id="w_best" value="${esc(ex?.best || '')}"><label>Biggest leak</label><input id="w_leak" value="${esc(ex?.leak || '')}">
    <label>ONE thing I'll change next week (just one)</label><input id="w_chg" value="${esc(ex?.change || '')}">
    <label>Pre-mortem: it's next Sunday and the week went badly. Why?</label><input id="w_pre" value="${esc(ex?.premortem || '')}">
    <label>So: IF that happens, THEN I will…</label><input id="w_if" value="${esc(ex?.ifthen || '')}"><div style="height:12px"></div><button class="btn-xl" data-act="saveWeekly">Save weekly review</button></div>`;
  if (R.history.length) h += `<div class="card"><h3>Journal</h3>${R.history.map(r => `<div class="feed"><div class="row between"><b>${r.day}</b><span>${['😞', '😕', '😐', '🙂', '😄'][r.mood - 1]} ⚡${r.energy}/5</span></div><div class="sm">🏆 ${esc(r.win)}</div>${r.leak ? `<div class="sm mut">🕳 ${esc(r.leak)}</div>` : ''}${r.kind_note ? `<div class="sm" style="color:var(--acc2)">💬 ${esc(r.kind_note)}</div>` : ''}</div>`).join('')}</div>`;
  return h;
}

/* ---------- ME ---------- */
function vMe() {
  const I = S.ins, u = S.user, L = I.level, e = I.evidence, og = I.outgrow;
  const pct = Math.round(og.ratio * 100);
  const hm = I.heat.map(c => { const a = c.f ? '#3ea6ff66' : c.m === 0 ? '#1b1b2a' : `rgba(124,92,255,${Math.min(.25 + c.m / 240 * .75, 1)})`; return `<i title="${c.d}: ${fm(c.m)}${c.f ? ' ❄️' : ''}" style="background:${a}"></i>`; }).join('');
  const hrmx = Math.max(...I.hours, 1);
  const best = I.hours.indexOf(Math.max(...I.hours));
  let h = `<div class="card glow"><div class="row"><div class="av" style="width:56px;height:56px;font-size:30px;background:${u.color}33;border:2px solid ${u.color}">${esc(u.emoji)}</div><div class="grow"><h2>${esc(u.display)}</h2><div class="mut sm">Level ${L.level} · ${esc(L.rank)} · ${L.xp} XP</div></div></div>
    <div class="bar" style="margin:12px 0 4px"><i style="width:${L.pct}%"></i></div></div>`;
  h += `<div class="card"><h3>The Outgrow meter</h3><p class="sm mut">Your last 7 days vs. the old A+ you (${og.baseline_h}h/day).</p><div class="row between"><div class="big" style="color:${pct >= 100 ? 'var(--good)' : 'var(--acc2)'}">${pct}%</div><div class="sm" style="text-align:right">${pct >= 130 ? '🦋 You have outgrown them.' : pct >= 100 ? '🔥 You matched the A+ you. Now pass them.' : pct >= 60 ? 'Closing in. Keep stacking days.' : 'The gap is real. The gap is also closable.'}</div></div>
    <div class="bar ${pct >= 100 ? 'g' : ''}" style="margin:8px 0"><i style="width:${Math.min(pct, 100)}%"></i></div>`;
  if (I.ghost) h += `<h3 style="margin-top:14px">You vs your best week (ghost)</h3>${lines([{ v: I.ghost.cum, c: '#8b8ba3', d: 1, w: 2 }, { v: I.cum, c: '#22d3a6', w: 3 }])}<div class="xs mut">Grey dashed = your best week (${fm(I.ghost.total)}). Green = this week.</div>`;
  h += `</div>`;
  h += `<div class="card"><h3>Evidence locker</h3><p class="sm mut">When your brain says "I'm a failure", read the court record.</p><div class="grid3" style="margin:8px 0"><div class="stat"><b>${e.hours}h</b><span class="xs mut">focused</span></div><div class="stat"><b>${e.days_hit}</b><span class="xs mut">floor days</span></div><div class="stat"><b>${e.longest}</b><span class="xs mut">best streak</span></div><div class="stat"><b>${e.deep}</b><span class="xs mut">deep blocks</span></div><div class="stat"><b>${e.urges_won}</b><span class="xs mut">urges beaten</span></div><div class="stat"><b>${e.learned}</b><span class="xs mut">chapters</span></div></div>
    ${e.wins.length ? '<h3 style="margin-top:8px">Your own wins</h3>' + e.wins.map(w => `<div class="sm" style="padding:3px 0">🏆 ${esc(w.win)} <span class="xs mut">${w.day}</span></div>`).join('') : ''}</div>`;
  h += `<div class="card"><h3>Last 12 weeks</h3><div class="heat" style="margin:10px 0">${hm}</div><div class="xs mut">Brighter = more focus · blue = streak freeze saved you</div></div>`;
  h += `<div class="card"><h3>Weekly hours</h3>${bars(I.weeks.map(w => w.m), '#7c5cff')}<div class="row between xs mut"><span>8 wks ago</span><span>this week ${fm(I.weeks[7].m)}</span></div></div>`;
  if (I.hours.some(x => x)) h += `<div class="card"><h3>Your best focus hours</h3><div class="hrs" style="margin:10px 0">${I.hours.map(x => `<i style="height:${x / hrmx * 100}%"></i>`).join('')}</div><div class="row between xs mut"><span>12am</span><span>6am</span><span>12pm</span><span>6pm</span><span>12am</span></div><div class="sm" style="margin-top:6px">Peak: <b>${best % 12 || 12}${best < 12 ? 'am' : 'pm'}</b>. Put your hardest chapter there.</div></div>`;
  if (Object.keys(I.sub7).length) { const tot = Object.values(I.sub7).reduce((a, b) => a + b, 0); h += `<div class="card"><h3>Subject balance (7 days)</h3>${Object.entries(I.sub7).sort((a, b) => b[1] - a[1]).map(([s, m]) => `<div class="row" style="margin:6px 0"><span style="width:78px" class="sm">${s}</span><div class="bar grow"><i style="width:${m / tot * 100}%;background:${SCOL[s]}"></i></div><span class="xs mut" style="width:56px;text-align:right">${fm(m)}</span></div>`).join('')}</div>`; }
  if (I.urge_triggers.length) h += `<div class="card"><h3>Your triggers</h3>${I.urge_triggers.map(t => `<span class="pill" style="margin-right:6px">${esc(t.trigger)} ×${t.n}</span>`).join('')}</div>`;
  h += `<div class="card"><h3>Badges (${I.badges.filter(b => b.got).length}/${I.badges.length})</h3><div class="grid3" style="margin-top:10px">${I.badges.map(b => `<div class="badge ${b.got ? '' : 'off'}"><s>${b.emoji}</s><b>${esc(b.name)}</b><div class="xs mut">${esc(b.desc)}</div></div>`).join('')}</div></div>`;
  if (u.admin) h += `<div class="card"><h3>Server</h3><p class="sm mut">You run this crew. Live stats, PIN resets, database backup.</p><button class="btn-xl" data-act="admin">🛠️ Open server dashboard</button></div>`;
  h += `<div class="card"><h3>Settings</h3><label>Display name</label><input id="s_name" value="${esc(u.display)}"><label>Identity: "I am becoming someone who…"</label><input id="s_id" value="${esc(u.identity)}" placeholder="shows up before he feels like it">
    <div class="grid2"><div><label>Old A+ you studied (hrs/day)</label><input id="s_base" type="number" step="0.5" value="${u.baseline_h}"></div><div><label>Daily floor (min)</label><input id="s_floor" type="number" value="${u.daily_min}"></div></div>
    <label>Exams (name + date)</label>${[0, 1, 2].map(i => { const x = u.exams[i] || {}; return `<div class="row" style="margin-bottom:6px"><input id="s_en${i}" placeholder="JEE Main" value="${esc(x.name || '')}"><input id="s_ed${i}" type="date" value="${x.date || ''}" style="width:150px"></div>`; }).join('')}
    <label>Avatar emoji & color</label><div class="row"><input id="s_emo" value="${esc(u.emoji)}" style="width:80px"><input id="s_col" type="color" value="${u.color}" style="width:70px;padding:3px"></div><div style="height:12px"></div>
    <button class="btn-p btn-xl" data-act="saveSettings">Save</button><button style="margin-top:8px;width:100%" data-act="notif">🔔 Enable alerts when friends start a block</button><button class="btn-d" style="margin-top:8px;width:100%" data-act="logout">Log out</button></div>`;
  if (I.xp_log.length) h += `<div class="card"><h3>Recent XP</h3>${I.xp_log.map(x => `<div class="row between sm" style="padding:3px 0"><span class="mut">${esc(x.label)}</span><b>+${x.amount}</b></div>`).join('')}</div>`;
  return h;
}

/* ---------- onboarding & urge ---------- */
function onboard() {
  modal(`<h2>Set the terms.</h2><p class="mut sm">You were an A+ student. That person still exists — they just need a system. Set the bar they'd set.</p>
  <label>Who are you becoming? ("I am someone who…")</label><input id="o_id" placeholder="studies before he's motivated">
  <label>On your best A+ days, how many hours/day did you study?</label><input id="o_base" type="number" step="0.5" value="5">
  <label>Your daily FLOOR (minutes) — the minimum that keeps the streak alive, even on bad days</label><input id="o_floor" type="number" value="45">
  <label>Exam #1 (name + date)</label><div class="row"><input id="o_n1" placeholder="JEE Main" value="JEE Main"><input id="o_d1" type="date" style="width:150px"></div>
  <label>Exam #2</label><div class="row"><input id="o_n2" placeholder="CBSE Boards" value="CBSE Boards"><input id="o_d2" type="date" style="width:150px"></div><div style="height:14px"></div>
  <button class="btn-p btn-xl" data-act="saveOnboard">Let's go</button>`);
}
function urgeFlow() {
  const trig = ['Instagram', 'Reels/Shorts', 'YouTube', 'Gaming', 'Texting', 'Overthinking', 'Just tired', 'Other'];
  modal(`<h2>🧠 Urge surfing</h2><p class="sm mut">An urge peaks and passes in about 90 seconds if you don't feed it. Name it. Ride it.</p><div class="row wrap">${trig.map(t => `<span class="chip" data-act="urgeStart" data-v="${t}">${t}</span>`).join('')}</div><button style="margin-top:14px;width:100%" data-act="closeModal">Cancel</button>`);
}
function urgeRun(trigger) {
  S.urge = { trigger, left: 90 };
  const draw = () => {
    const U = S.urge; if (!U) return;
    const ph = U.left % 14; const breathe = ph > 10 ? 'Breathe in…' : ph > 6 ? 'Hold…' : 'Out, slowly…';
    $('#modal').innerHTML = `<div class="c"><h3>${esc(trigger)} urge</h3><div class="big" style="font-size:72px">${U.left}</div><p class="b" style="color:var(--acc2)">${breathe}</p><p class="sm mut">Notice where you feel it. You don't have to obey it.</p>
      <button class="btn-p btn-xl" data-act="urgeDone" data-v="redirected">Start 5 minutes of study instead</button><button class="btn-g btn-xl" style="margin-top:8px" data-act="urgeDone" data-v="resisted">It passed. I'm good ✓</button><button style="margin-top:8px;width:100%" data-act="urgeDone" data-v="gave_in">I gave in (no judgement — log it)</button></div>`;
    if (U.left <= 0) { S.urge = null; return; }
    U.left--; S._ut = setTimeout(draw, 1000);
  };
  clearTimeout(S._ut); draw();
}

/* ---------- actions ---------- */
const val = id => ($('#' + id) || {}).value;
const A = {
  async login() { try { const r = await api('login', { username: val('a_user'), pin: val('a_pin') }); S.user = r.user; await go('today'); if (!S.user.onboarded) onboard(); } catch (e) { } },
  async register() { try { const r = await api('register', { username: val('a_user'), pin: val('a_pin'), crew_code: val('a_code'), crew_name: val('a_cname') }); S.user = r.user; await go('today'); onboard(); } catch (e) { } },
  authMode() { S.authMode = S.authMode === 'login' ? 'register' : 'login'; renderAuth(); },
  async logout() { await api('logout', {}); chatReset(); S.user = null; S.ins = null; renderAuth(); },
  closeModal() { clearTimeout(S._ut); S.urge = null; closeModal(); },
  async tab(el) { if (el.dataset.sub) S.sub = el.dataset.sub; await go(el.dataset.v); },
  pickSub(el) { S.pickSub = el.dataset.v; render(); },
  pickDur(el) { S.pickDur = +el.dataset.v; render(); },
  async startTimer() { await api('timer/start', { subject: S.pickSub, target: S.pickDur }); await go('today'); },
  async start5() { await api('timer/start', { subject: S.pickSub, target: 5 }); await go('today'); },
  async extend() { await api('timer/extend', { add: 20 }); await go('today'); },
  async distract() { await api('timer/distract', {}); const d = $('#dcount'); if (d) d.textContent = +d.textContent + 1; S.today.timer.distractions++; },
  async stopTimer() { const r = await api('timer/stop', {}); if (r.too_short) toast('Under 5 minutes — not logged', 'Even 5 counts. Go again.'); else if (r.minutes >= 25) beep(); await go('today'); },
  async discard() { if (confirm('Discard this block? Nothing will be logged.')) { await api('timer/stop', { discard: true }); await go('today'); } },
  async manual() { await api('focus', { subject: val('mf_s'), minutes: +val('mf_m') }); await go('today'); },
  async delFocus(el) { await api('focus/delete', { id: +el.dataset.id }); await go('today'); },
  async habit(el) { const on = S.today.habits.includes(el.dataset.id); await api('habit', { habit: el.dataset.id, done: !on }); await go('today'); },
  async chest() { const r = await api('chest', {}); confetti(); modal(`<div class="c"><div style="font-size:64px">${r.tier === 'epic' ? '💎' : r.tier === 'rare' ? '🎁' : '📦'}</div><h2>${esc(r.label)}</h2><div class="mut">${r.tier.toUpperCase()}</div><button class="btn-p btn-xl" style="margin-top:12px" data-act="closeModal">Nice</button></div>`); await go('today'); },
  async addPlan(el) { const t = val('pl_t'); if (!t) return toast('Write the task first'); await api('plan', { when: el.dataset.v, text: t, cue: val('pl_c') }); await go('today'); },
  async togglePlan(el) { await api('plan/toggle', { id: +el.dataset.id }); await go('today'); },
  async delPlan(el) { await api('plan/delete', { id: +el.dataset.id }); await go('today'); },
  urge() { urgeFlow(); }, urgeStart(el) { urgeRun(el.dataset.v); },
  async urgeDone(el) {
    const tr = S.urge?.trigger || ($('#modal h3')?.textContent || '').replace(' urge', ''); const o = el.dataset.v; clearTimeout(S._ut); S.urge = null;
    await api('urge', { outcome: o, trigger: tr }); closeModal();
    if (o === 'redirected') { await api('timer/start', { subject: S.pickSub, target: 5 }); } else if (o === 'gave_in') toast('Logged. No shame.', 'What would make the next one easier?');
    await go('today');
  },
  async sub(el) { S.sub = el.dataset.v; render(); },
  async chap(el) { await api('chapter', { id: +el.dataset.id, status: +el.dataset.s }); S.syl = await api('syllabus'); S.ins = await api('insights'); render(); },
  async addChap(el) { const n = val('ca_' + el.dataset.v); if (!n) return; await api('chapter/add', { subject: el.dataset.v, name: n }); S.syl = await api('syllabus'); render(); },
  async rev(el) { await api('revision', { id: +el.dataset.id, result: el.dataset.r }); S.syl = await api('syllabus'); render(); },
  async addTest() { await api('test', { name: val('t_n') || 'Test', kind: 'mock', subject: val('t_s'), score: +val('t_sc'), max: +val('t_mx'), concept: +val('t_c') || 0, silly: +val('t_si') || 0, time: +val('t_t') || 0 }); S.tests = await api('tests'); render(); },
  mood(el) { document.querySelectorAll(`#${el.dataset.g} span`).forEach(s => s.classList.remove('on')); el.classList.add('on'); },
  async saveReflect() {
    const g = id => { const x = [...document.querySelectorAll(`#${id} span`)].findIndex(s => s.classList.contains('on')); return x < 0 ? 3 : x + 1; };
    await api('reflect', { mood: g('f_mood'), energy: g('f_energy'), win: val('f_win'), leak: val('f_leak'), kind_note: val('f_kind'), tomorrow: val('f_tom'), cue: val('f_cue') }); toast('Reflection saved', 'Tomorrow is already planned.'); await go('reflect');
  },
  async saveWeekly() { await api('weekly', { best: val('w_best'), leak: val('w_leak'), change: val('w_chg'), premortem: val('w_pre'), ifthen: val('w_if') }); toast('Weekly review saved'); await go('reflect'); },
  async joinCrew() { await api('crew/join', { code: val('cj') }); await go('crew'); },
  async createCrew() { await api('crew/create', { name: val('cn') }); await go('crew'); },
  async nudge(el) { await api('nudge', { to: +el.dataset.id }); toast('Nudged 👊'); await go('crew'); },
  async react(el) { await api('react', { feed_id: +el.dataset.id, emoji: el.dataset.e }); S.crew = await api('crew'); render(); },
  async duel() { await api('duel', { opponent: +val('du_o'), days: +val('du_d') }); toast('Challenge sent ⚔️'); await go('crew'); },
  async acceptDuel(el) { await api('duel/accept', { id: +el.dataset.id }); await go('crew'); },
  copy(el) { navigator.clipboard?.writeText(el.dataset.v); toast('Invite code copied'); },
  async saveOnboard() {
    const ex = [[val('o_n1'), val('o_d1')], [val('o_n2'), val('o_d2')]].filter(x => x[1]).map(x => ({ name: x[0] || 'Exam', date: x[1] }));
    const r = await api('settings', { identity: val('o_id'), baseline_h: +val('o_base'), daily_min: +val('o_floor'), exams: ex.length ? ex : undefined, onboarded: true }); S.user = r.user; closeModal(); await go('today');
  },
  async saveSettings() {
    const ex = [0, 1, 2].map(i => ({ name: val('s_en' + i) || 'Exam', date: val('s_ed' + i) })).filter(x => x.date);
    const r = await api('settings', { display: val('s_name'), identity: val('s_id'), baseline_h: +val('s_base'), daily_min: +val('s_floor'), exams: ex, emoji: val('s_emo'), color: val('s_col') }); S.user = r.user; toast('Saved'); await go('me');
  },
  async notif() { if (!('Notification' in window)) return toast('Not supported here'); const p = await Notification.requestPermission(); toast(p === 'granted' ? 'Alerts on while the app is open' : 'Blocked'); },
};
document.addEventListener('click', e => { const el = e.target.closest('[data-act]'); if (el && A[el.dataset.act]) { e.preventDefault(); A[el.dataset.act](el, e); } });
document.addEventListener('keydown', e => { if (e.key === 'Enter' && S.user === null && ($('#a_pin') === document.activeElement || $('#a_user') === document.activeElement)) A[S.authMode === 'login' ? 'login' : 'register'](); });

/* ---------- CHAT: text only. Crew room + private DMs ---------- */
const CH = { threads: [], people: {}, open: null, msgs: [], more: false, seq: -1, unread: {}, total: 0, run: 0, ctl: null, notified: 0, loading: false };
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
    <div class="composer"><textarea id="chat_in" rows="1" maxlength="1000" placeholder="${t.kind === 'dm' ? 'Message ' + esc(t.title) : 'Message the crew'}"></textarea><button class="btn-p" data-act="chatSend">Send</button></div></div>`;
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
function chatAfterRender() { if (CH.open) { chatPaint(true); const ta = $('#chat_in'); if (ta && !matchMedia('(pointer:coarse)').matches) ta.focus(); } }

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
    h += `<div class="msg ${grp ? 'grp' : ''}">${grp ? '<div class="av sp"></div>' : `<div class="av" style="background:${esc(p.color)}33;border:2px solid ${esc(p.color)}">${esc(p.emoji)}</div>`}
      <div class="mb">${grp ? '' : `<div class="mh"><b style="color:${esc(p.color)}">${esc(p.display)}</b><span class="xs mut">${chatClock(m.ts)}</span></div>`}<div class="mt">${esc(m.text)}</div></div>
      ${m.uid === S.user.id ? `<button class="mx" data-act="chatDel" data-id="${m.id}" title="Delete">🗑</button>` : ''}</div>`;
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
  if (changed) chatPaint(stick);
  const theirs = fresh.filter(m => m.uid !== S.user.id);
  if (theirs.length && document.hidden && 'Notification' in window && Notification.permission === 'granted') {
    const m = theirs[theirs.length - 1]; new Notification(`💬 ${(CH.people[m.uid] || {}).display || 'New message'}`, { body: m.text.slice(0, 80) });
  }
  chatBadge();
}

async function chatOpen(key) {
  chatStop(); CH.open = key; CH.msgs = []; CH.more = false; CH.loading = true; render();
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
async function chatSend() {
  const ta = $('#chat_in'); if (!ta || chatSending) return;
  const text = ta.value.trim(); if (!text) return;
  chatSending = true;
  try {
    const r = await api('chat/send', { thread: CH.open, text });
    ta.value = ''; ta.style.height = 'auto';
    if (!CH.msgs.some(m => m.id === r.message.id)) CH.msgs.push(r.message);
    chatPaint(true);
  } catch (e) { } finally { chatSending = false; ta.focus(); }
}
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
  chatSend, chatOlder,
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

/* ---------- admin dashboard (only for OUTGROW_ADMINS) ---------- */
const fmUp = s => s >= 86400 ? Math.floor(s / 86400) + 'd ' + Math.floor(s % 86400 / 3600) + 'h' : s >= 3600 ? Math.floor(s / 3600) + 'h ' + Math.floor(s % 3600 / 60) + 'm' : Math.floor(s / 60) + 'm';
async function adminOpen() {
  try {
    const r = await api('admin/stats'), a = r.app, v = r.server;
    const st = (n, l) => `<div class="stat"><b>${n}</b><span class="xs mut">${l}</span></div>`;
    modal(`<h2>🛠️ Server</h2>
      <div class="grid3" style="margin:10px 0">${st(a.users, 'users')}${st(a.active_today, 'active today')}${st(a.active_7d, 'active 7d')}${st(fm(a.focus_min_today), 'focus today')}${st(a.messages_today, 'msgs today')}${st(a.messages_total, 'msgs total')}</div>
      <div class="xs mut" style="line-height:1.7">Up ${fmUp(v.uptime_s)} · RAM ${v.rss_mb ?? '?'} MB · load ${v.load.join(' ')} · DB ${v.db_kb} KB · disk free ${v.disk_free_gb}/${v.disk_total_gb} GB · ${v.threads} threads · python ${esc(v.python)} · build ${esc(v.version)} · ${esc(v.time)} ${esc(v.tz)}</div>
      <h3 style="margin-top:14px">People</h3>${r.users.map(u => `<div class="q"><div class="grow sm"><b>${esc(u.display)}</b> <span class="xs mut">@${esc(u.username)}${u.admin ? ' · admin' : ''}</span><div class="xs mut">${u.xp} XP · last focus ${esc(u.last_focus || 'never')} · ${u.msgs} msgs</div></div><button class="btn-s" data-act="adminReset" data-v="${esc(u.username)}">Reset PIN</button></div>`).join('')}
      <a class="btn btn-xl c" style="display:block;margin-top:12px;text-decoration:none" href="/api/admin/backup" download>⬇️ Download database backup</a>
      <button class="btn-xl" style="margin-top:8px" data-act="closeModal">Close</button>`);
  } catch (e) { }
}

/* ---------- live presence: poll, notify when friends start ---------- */
let seenLive = new Set();
setInterval(async () => {
  if (!S.user || document.hidden) return;
  const ae = document.activeElement; const typing = ae && /INPUT|TEXTAREA|SELECT/.test(ae.tagName);
  try {
    if (S.tab === 'today' && !typing && !S.urge && $('#modal').classList.contains('hidden')) {
      const t = await api('today'); const wasTimer = !!S.today?.timer; S.today = t;
      t.live.forEach(l => { const k = l.display + l.subject; if (!seenLive.has(k) && 'Notification' in window && Notification.permission === 'granted') new Notification(`${l.display} is locked in on ${l.subject}`, { body: 'Join them. Start a block.' }); seenLive.add(k); });
      if (!(wasTimer && t.timer)) render(); else { const lv = $('.live-strip'); }
    } else if (S.tab === 'crew' && !typing) { S.crew = await api('crew'); render(); }
  } catch (e) { }
}, 25000);

boot();
