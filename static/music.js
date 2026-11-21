'use strict';
/* RAGDAMAXING music rooms: synchronized playback of the server's proxied stream.
   The server owns queue/now; this file only syncs <audio> to the server clock. */
const Music = {};
window.Music = Music;

(function () {
  const M = {
    ch: 0, state: null, offset: 0, rtt: 0, syncedAt: 0, clockTimer: 0, tickTimer: 0,
    audio: null, lastTrack: '', seekTo: null, blocked: false, retryTimer: 0, retries: 0,
    notice: '', err: '', qsig: '', results: null, searching: false, deafened: false, rateTimer: 0,
    volume: 0.8, userMute: false,
  };

  try {
    const v = parseFloat(localStorage.getItem('rg_music_vol'));
    if (isFinite(v)) M.volume = Math.max(0, Math.min(1, v));
    M.userMute = localStorage.getItem('rg_music_mute') === '1';
  } catch (e) { }

  const $m = id => document.getElementById(id);
  const fmt = s => {
    s = Math.max(0, Math.floor(+s || 0));
    return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
  };
  const dur = t => fmt((t && t.duration_s) || 0);
  const serverNow = () => Date.now() + M.offset;
  const current = () => (M.state && M.state.now) || null;
  const track = () => (current() && current().track) || null;

  function ensureAudio() {
    if (M.audio) return M.audio;
    const a = document.createElement('audio');
    a.id = 'music_audio';
    a.preload = 'auto';
    a.autoplay = true;
    a.playsInline = true;
    a.hidden = true;
    a.volume = M.volume;
    a.muted = M.userMute || M.deafened;
    a.addEventListener('loadedmetadata', () => {
      if (M.seekTo != null) { try { a.currentTime = M.seekTo; } catch (e) { } M.seekTo = null; }
      syncNow(true);
    });
    a.addEventListener('canplay', () => { M.err = ''; paint(); });
    a.addEventListener('playing', () => { M.blocked = false; M.err = ''; paint(); });
    a.addEventListener('error', () => {
      if (!M.ch || !track()) return;
      if (M.retries >= 4) { M.err = 'Could not play this track.'; paint(); return; }
      M.retries++;
      M.err = 'Buffering track…';
      clearTimeout(M.retryTimer);
      M.retryTimer = setTimeout(() => { if (M.ch && track()) { try { a.load(); } catch (e) { } syncNow(true); } }, 1200);
      paint();
    });
    document.body.appendChild(a);
    M.audio = a;
    return a;
  }

  function targetTime() {
    const n = current();
    if (!n) return 0;
    const at = n.paused_at_ms != null ? n.paused_at_ms : serverNow();
    return Math.max(0, (at - n.started_at_ms) / 1000);
  }

  function seek(force) {
    const a = ensureAudio(), n = current();
    if (!n) return;
    const target = targetTime();
    if (a.readyState < 1) { M.seekTo = target; return; }
    if (force || Math.abs(a.currentTime - target) > 0.3) {
      try { a.currentTime = target; } catch (e) { M.seekTo = target; }
    }
  }

  function syncNow(force) {
    const a = ensureAudio(), n = current();
    if (!M.ch || !M.state || !M.state.enabled || !n) {
      a.pause();
      if (a.getAttribute('src')) { a.removeAttribute('src'); try { a.load(); } catch (e) { } }
      M.lastTrack = ''; M.seekTo = null; M.blocked = false;
      return;
    }
    if (M.lastTrack !== n.track.id) {
      M.lastTrack = n.track.id;
      M.retries = 0; M.err = ''; M.blocked = false; M.seekTo = null;
      a.src = '/api/music/stream/' + encodeURIComponent(n.track.id) + '?ch=' + M.ch + '&v=' + (M.state.rev || 0);
      a.load();
      if (a.readyState < 1) M.seekTo = targetTime();
    }
    if (n.paused_at_ms != null) {
      a.pause();
      seek(true);
      a.playbackRate = 1;
      return;
    }
    const drift = a.readyState >= 1 ? a.currentTime - targetTime() : 0;
    if (Math.abs(drift) > 0.3) {
      seek(true);
      a.playbackRate = 1;
    } else if (Math.abs(drift) > 0.06) {
      a.playbackRate = drift > 0 ? 0.98 : 1.02;
      clearTimeout(M.rateTimer);
      M.rateTimer = setTimeout(() => { if (M.audio) M.audio.playbackRate = 1; }, 250);
    }
    if (a.paused && !M.blocked) {
      a.play().catch(() => { M.blocked = true; paint(); });
    }
  }

  async function syncClock() {
    if (!M.ch) return;
    const samples = [];
    for (let i = 0; i < 5; i++) {
      const t0 = Date.now();
      try {
        const r = await fetch('/api/time', { cache: 'no-store', credentials: 'same-origin' });
        if (!r.ok) break;
        const j = await r.json();
        const t1 = Date.now();
        if (!j || !isFinite(j.t)) break;
        samples.push({ off: j.t - (t0 + (t1 - t0) / 2), rtt: t1 - t0 });
      } catch (e) { break; }
    }
    if (samples.length) {
      samples.sort((a, b) => a.off - b.off);
      const m = samples[Math.floor(samples.length / 2)];
      M.offset = m.off; M.rtt = m.rtt; M.syncedAt = Date.now();
    }
    syncNow(false);
    paint();
  }

  function startTimers() {
    clearInterval(M.tickTimer);
    M.tickTimer = setInterval(tick, 250);
    clearInterval(M.clockTimer);
    M.clockTimer = setInterval(() => { if (M.ch && !document.hidden) syncClock(); }, 60000);
  }

  function tick() {
    if (!M.ch || !M.state) return;
    paintProgress();
    if (!M.state.enabled || !current() || current().paused_at_ms != null || M.blocked) return;
    const a = M.audio;
    if (!a || a.readyState < 1) return;
    const drift = a.currentTime - targetTime();
    if (Math.abs(drift) > 0.3) {
      seek(true);
      a.playbackRate = 1;
    } else if (Math.abs(drift) > 0.08 && !M.rateTimer) {
      a.playbackRate = drift > 0 ? 0.98 : 1.02;
      M.rateTimer = setTimeout(() => { if (M.audio) M.audio.playbackRate = 1; M.rateTimer = 0; }, 250);
    }
    if (a.paused && !M.blocked) a.play().catch(() => { M.blocked = true; paint(); });
  }

  function notice(msg) {
    M.notice = msg || '';
    paintNotice();
    if (!document.getElementById('music_panel')) toast('Music', msg);
  }

  function resultsHTML() {
    if (M.searching) return '<div class="mu-note">Searching YouTube…</div>';
    if (!M.results || !M.results.length) return M.results ? '<div class="mu-note">No results.</div>' : '';
    return '<div class="mu-results">' + M.results.map(r => `<button class="mu-res" data-mact="addresult" data-id="${esc(r.id)}">
      <span class="mu-res-p">${ic('plus', 15)}</span><span class="mu-res-t"><b class="ell">${esc(r.title)}</b>
      <span class="ell">${esc(r.artist || 'YouTube')} · ${dur(r)}</span></span></button>`).join('') + '</div>';
  }

  function queueHTML() {
    const q = (M.state && M.state.queue) || [];
    if (!q.length) return '<div class="mu-note">Queue is empty. Add a song above.</div>';
    return q.map((t, i) => `<div class="mu-q">
      <span class="mu-q-i">${i + 1}</span>
      <span class="mu-q-t"><b class="ell">${esc(t.title)}</b><span class="ell">${esc(t.artist || 'YouTube')} · ${esc(t.requester_name || '')}</span></span>
      <span class="mu-q-d">${dur(t)}</span>
      <button class="mu-x" data-mact="remove" data-i="${i}" aria-label="Remove ${esc(t.title)}" title="Remove">${ic('x', 13)}</button></div>`).join('');
  }

  function nowHTML() {
    const n = current(), t = track();
    if (!t) return `<div class="mu-np mu-idle"><div class="mu-art">${ic('music', 22)}</div><div class="mu-meta"><b>Nothing playing</b><span>Search below or type /play in chat.</span></div></div>`;
    const paused = n.paused_at_ms != null;
    return `<div class="mu-np">
      <div class="mu-art">${ic('music', 22)}</div>
      <div class="mu-meta"><b id="music_now_title" class="ell">${esc(t.title)}</b>
        <span id="music_now_sub" class="ell">${esc(t.artist || 'YouTube')} · added by ${esc(t.requester_name || 'someone')}</span>
        <div class="mu-bar"><i id="music_prog"></i></div>
        <div class="mu-time"><span id="music_cur">0:00</span><span>${dur(t)}</span></div></div>
      <div class="mu-ctls">
        <button class="mu-btn" data-mact="${paused ? 'resume' : 'pause'}" title="${paused ? 'Resume' : 'Pause'}">${paused ? ic('play', 14) : ic('pause', 14)}</button>
        <button class="mu-btn" data-mact="skip" title="Skip (or vote skip)">${ic('skip', 14)}</button>
        <button class="mu-btn" data-mact="loop" title="Loop: ${esc(M.state.loop)}">${M.state.loop === 'track' ? ic('repeat1', 14) : ic('repeat', 14)}</button>
        <button class="mu-btn" data-mact="mute" title="Mute music">${M.userMute ? ic('volumeOff', 14) : ic('volume', 14)}</button>
      </div></div>`;
  }

  function panelHTML() {
    const s = M.state;
    if (!s) return `<div class="mu" id="music_panel"><div class="mu-off"><b>${ic('music', 14)} Music</b><span>Join the voice room to load the player.</span></div></div>`;
    if (!s.enabled) return `<div class="mu" id="music_panel"><div class="mu-off"><b>${ic('music', 14)} Music</b><span>${esc(s.reason || 'Music is unavailable.')}</span></div></div>`;
    return `<div class="mu" id="music_panel" data-ch="${M.ch}">
      ${nowHTML()}
      <button class="mu-unblock" id="music_unblock" data-mact="unblock" ${M.blocked ? '' : 'hidden'}>Tap to hear music</button>
      <div class="mu-controls">
        <label class="mu-vol"><span>${ic('volumeLow', 14)}</span><input type="range" min="0" max="1" step="0.05" value="${M.volume}" data-mact="vol" aria-label="Music volume"></label>
        <span class="mu-vote" id="music_vote"></span>
      </div>
      <div class="mu-h"><b>Up next</b><span>${(s.queue || []).length}/${50}</span></div>
      <div class="mu-queue" id="music_queue">${queueHTML()}</div>
      <form class="mu-search" id="music_form"><input id="music_q" maxlength="120" placeholder="Search a song, or /play a link" autocomplete="off">
        <button class="btn-s" type="submit">Search</button></form>
      <div id="music_results">${resultsHTML()}</div>
      <div class="mu-notice" id="music_notice">${esc(M.notice || M.err || '')}</div></div>`;
  }

  function paintNotice() {
    const n = $m('music_notice'); if (n) n.textContent = M.notice || M.err || '';
    const v = $m('music_vote'); if (v) v.textContent = voteText();
  }

  function voteText() {
    const s = M.state; if (!s) return '';
    const n = (s.votes && s.votes.skip) || 0;
    if (!n) return '';
    return n + '/' + (s.vote_needed || 1) + ' votes to skip';
  }

  function paintProgress() {
    const t = track(); if (!t) return;
    const bar = $m('music_prog'), cur = $m('music_cur'); if (!bar) return;
    const target = targetTime(), total = Math.max(1, +t.duration_s || 1);
    bar.style.width = Math.min(100, target / total * 100) + '%';
    if (cur) cur.textContent = fmt(target);
  }

  function paint() {
    const p = $m('music_panel'); if (!p) return;
    const s = M.state;
    if (!s) return;
    const t = track();
    const np = p.querySelector('.mu-np');
    if (np && !!$m('music_now_title') !== !!t) np.outerHTML = nowHTML();
    const npTitle = $m('music_now_title');
    if (npTitle && t) { npTitle.textContent = t.title; }
    if (t && $m('music_now_sub')) $m('music_now_sub').textContent = (t.artist || 'YouTube') + ' · added by ' + (t.requester_name || 'someone');
    const qs = JSON.stringify((s.queue || []).map(x => x.id + ':' + x.requester));
    if (qs !== M.qsig) {
      M.qsig = qs;
      const q = $m('music_queue'); if (q) q.innerHTML = queueHTML();
    }
    const pauseBtn = p.querySelector('[data-mact="pause"],[data-mact="resume"]');
    if (pauseBtn && current()) {
      const paused = current().paused_at_ms != null;
      pauseBtn.dataset.mact = paused ? 'resume' : 'pause';
      pauseBtn.innerHTML = paused ? ic('play', 14) : ic('pause', 14);
    }
    const loopBtn = p.querySelector('[data-mact="loop"]');
    if (loopBtn) {
      loopBtn.innerHTML = s.loop === 'track' ? ic('repeat1', 14) : ic('repeat', 14);
      loopBtn.title = 'Loop: ' + s.loop;
    }
    const muteBtn = p.querySelector('[data-mact="mute"]');
    if (muteBtn) muteBtn.innerHTML = M.userMute ? ic('volumeOff', 14) : ic('volume', 14);
    const unblock = $m('music_unblock'); if (unblock) unblock.hidden = !M.blocked;
    paintProgress(); paintNotice();
  }

  async function action(kind, extra) {
    if (!M.ch) return;
    try {
      const r = await api('music/' + kind, Object.assign({ channel: M.ch }, extra || {}));
      if (r && r.channel) { M.state = r; apply(false); }
      paint();
      if (r && r.votes && r.votes.skip && r.votes.skip < (r.vote_needed || 1)) notice(r.votes.skip + '/' + r.vote_needed + ' votes to skip');
      else notice('');
    } catch (e) { notice(e && e.message ? e.message : 'Music action failed'); }
  }

  async function add(q) {
    if (!M.ch) { toast('Music', 'Join a voice room first'); return; }
    notice('Adding…');
    try {
      const r = await api('music/add', { channel: M.ch, query: q });
      M.state = r; apply(false); paint();
      const t = r && r.added;
      notice(t ? 'Added ' + t.title : 'Added');
    } catch (e) { notice(e && e.message ? e.message : 'Could not add that'); }
  }

  async function search(q) {
    if (!M.ch) { toast('Music', 'Join a voice room first'); return; }
    M.results = null; M.searching = true; M.notice = '';
    const box = $m('music_results'); if (box) box.innerHTML = resultsHTML();
    try {
      const r = await api('music/search?channel=' + M.ch + '&q=' + encodeURIComponent(q));
      M.results = r.results || [];
    } catch (e) { M.results = []; notice(e && e.message ? e.message : 'Search failed'); }
    M.searching = false;
    const b = $m('music_results'); if (b) b.innerHTML = resultsHTML();
  }

  Music.attach = function (ch, state) {
    if (M.ch && M.ch !== ch) Music.teardown();
    M.ch = ch; M.state = state || null; M.notice = ''; M.err = ''; M.results = null;
    M.lastTrack = ''; M.blocked = false; M.qsig = '';
    ensureAudio();
    startTimers();
    syncClock();
    apply(true);
    paint();
  };

  Music.teardown = function () {
    M.ch = 0; M.state = null; M.lastTrack = ''; M.results = null; M.notice = ''; M.err = ''; M.blocked = false;
    clearInterval(M.tickTimer); M.tickTimer = 0;
    clearInterval(M.clockTimer); M.clockTimer = 0;
    clearTimeout(M.retryTimer); M.retryTimer = 0;
    clearTimeout(M.rateTimer); M.rateTimer = 0;
    if (M.audio) { try { M.audio.pause(); M.audio.removeAttribute('src'); M.audio.load(); } catch (e) { } }
  };

  Music.event = function (d) {
    if (!d || d.channel !== M.ch) return;
    M.state = d;
    apply(false);
    paint();
  };

  function apply(force) {
    if (!M.state) return;
    if (!M.state.enabled) { syncNow(false); paint(); return; }
    syncNow(force);
  }

  Music.paint = paint;
  Music.panelHTML = panelHTML;
  Music.attached = function () { return M.ch > 0; };
  Music.nowTrack = function () { return track(); };
  Music.tileHTML = function () {
    const t = track();
    if (!t) return '';
    return `<div class="vt mu-bot"><div class="mu-bot-a">${ic('music', 24)}</div><b>Music</b><span class="vt-i ell">${esc(t.title)}</span></div>`;
  };
  Music.setDeafened = function (on) {
    M.deafened = !!on;
    if (M.audio) M.audio.muted = M.userMute || M.deafened;
    paint();
  };

  Music.slash = function (text) {
    const raw = String(text || '').trim();
    if (raw.charAt(0) !== '/') return false;
    const sp = raw.split(/\s+/);
    const cmd = sp[0].toLowerCase();
    const rest = raw.slice(sp[0].length).trim();
    if (!M.ch) { toast('Music', 'Join a voice room first'); return true; }
    if (cmd === '/play') {
      if (!rest) notice('Usage: /play <song or YouTube link>');
      else add(rest);
    } else if (cmd === '/skip') action('skip');
    else if (cmd === '/pause') action('pause');
    else if (cmd === '/resume') action('resume');
    else if (cmd === '/stop') action('stop');
    else if (cmd === '/loop') {
      const cur = (M.state && M.state.loop) || 'off';
      const mode = rest ? rest.toLowerCase() : (cur === 'off' ? 'track' : (cur === 'track' ? 'queue' : 'off'));
      if (!['off', 'track', 'queue'].includes(mode)) notice('Loop must be off, track or queue');
      else action('loop', { mode });
    } else if (cmd === '/np') {
      const t = track();
      notice(t ? 'Now playing: ' + t.title : 'Nothing is playing');
    } else if (cmd === '/queue') {
      const q = (M.state && M.state.queue) || [];
      notice(q.length ? q.slice(0, 5).map((t, i) => (i + 1) + '. ' + t.title).join(' · ') + (q.length > 5 ? ' …' : '') : 'Queue is empty');
    } else if (cmd === '/help') {
      notice('/play, /skip, /pause, /resume, /stop, /loop, /queue, /np');
    } else {
      notice('Unknown music command. Try /help');
    }
    return true;
  };

  document.addEventListener('submit', e => {
    if (!e.target || e.target.id !== 'music_form') return;
    e.preventDefault();
    const box = $m('music_q'); if (!box) return;
    const v = box.value.trim();
    if (!v) return;
    if (v.charAt(0) === '/') { Music.slash(v); box.value = ''; return; }
    if (/^[A-Za-z0-9_-]{11}$/.test(v) || /^https?:\/\//i.test(v)) { add(v); box.value = ''; return; }
    search(v);
  });

  document.addEventListener('click', e => {
    const el = e.target.closest('[data-mact]');
    if (!el) return;
    const act = el.dataset.mact;
    if (act === 'pause') action('pause');
    else if (act === 'resume') action('resume');
    else if (act === 'skip') action('skip');
    else if (act === 'loop') {
      const next = !M.state || M.state.loop === 'off' ? 'track' : M.state.loop === 'track' ? 'queue' : 'off';
      action('loop', { mode: next });
    } else if (act === 'mute') {
      M.userMute = !M.userMute;
      try { localStorage.setItem('rg_music_mute', M.userMute ? '1' : '0'); } catch (x) { }
      if (M.audio) M.audio.muted = M.userMute || M.deafened;
      paint();
    } else if (act === 'unblock') {
      M.blocked = false;
      if (M.audio) M.audio.play().catch(() => { M.blocked = true; paint(); });
    } else if (act === 'remove') {
      action('remove', { index: +el.dataset.i });
    } else if (act === 'addresult') {
      add(el.dataset.id);
    }
  });

  document.addEventListener('input', e => {
    if (!e.target || e.target.dataset.mact !== 'vol') return;
    M.volume = Math.max(0, Math.min(1, parseFloat(e.target.value) || 0));
    if (M.audio) M.audio.volume = M.volume;
    try { localStorage.setItem('rg_music_vol', String(M.volume)); } catch (x) { }
  });

  document.addEventListener('visibilitychange', () => {
    if (document.hidden || !M.ch) return;
    syncClock();
  });
})();