/* Two-browser music-room smoke: sync, SSE skip, teardown. No packages.
 * Run: node tools/music_synthetic.mjs
 */
import { spawn } from 'node:child_process';
import { createServer } from 'node:http';
import { chmod, mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const APP = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const PORT = 8815;
const DEBUG_PORT = 9334;
const BASE = `http://127.0.0.1:${PORT}`;
const FAKE = path.join(APP, 'tests', 'fake_ytdlp.py');
const sleep = ms => new Promise(r => setTimeout(r, ms));
const failures = [];
const check = (name, ok, detail) => {
  console.log((ok ? 'PASS ' : 'FAIL ') + name + (ok ? '' : ' :: ' + JSON.stringify(detail)));
  if (!ok) failures.push(name);
};

function wav(seconds = 60) {
  const rate = 8000, n = rate * seconds;
  const b = Buffer.alloc(44 + n);
  b.write('RIFF', 0); b.writeUInt32LE(36 + n, 4); b.write('WAVE', 8); b.write('fmt ', 12);
  b.writeUInt32LE(16, 16); b.writeUInt16LE(1, 20); b.writeUInt16LE(1, 22);
  b.writeUInt32LE(rate, 24); b.writeUInt32LE(rate, 28); b.writeUInt16LE(1, 32); b.writeUInt16LE(8, 34);
  b.write('data', 36); b.writeUInt32LE(n, 40);
  for (let i = 44; i < b.length; i++) b[i] = 128 + Math.round(20 * Math.sin(i / 18));
  return b;
}

const AUDIO = wav();
let server = null, chrome = null, profile = '', dbDir = '', audioSrv = null, cdp = null;

async function req(method, p, body, cookie) {
  const r = await fetch(BASE + p, {
    method,
    headers: { 'Content-Type': 'application/json', ...(cookie ? { cookie } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const j = await r.json().catch(() => ({}));
  const setCookies = r.headers.getSetCookie ? r.headers.getSetCookie() : [];
  return { status: r.status, body: j, cookies: setCookies };
}

function cookieValue(setCookies, name) {
  for (const c of setCookies) if (c.startsWith(name + '=')) return c.slice(name.length + 1).split(';')[0];
  return '';
}

async function startServer() {
  await chmod(FAKE, 0o755);
  audioSrv = createServer((req, res) => {
    const m = /^bytes=(\d*)-(\d*)$/.exec(req.headers.range || '');
    let start = 0, end = AUDIO.length - 1, code = 200;
    if (m) {
      start = m[1] ? +m[1] : 0;
      end = m[2] ? Math.min(+m[2], AUDIO.length - 1) : AUDIO.length - 1;
      code = 206;
    }
    const body = AUDIO.subarray(start, end + 1);
    res.writeHead(code, { 'Content-Type': 'audio/wav', 'Content-Length': body.length, 'Accept-Ranges': 'bytes', ...(code === 206 ? { 'Content-Range': `bytes ${start}-${end}/${AUDIO.length}` } : {}) });
    res.end(body);
  });
  await new Promise(r => audioSrv.listen(0, '127.0.0.1', r));
  dbDir = await mkdtemp(path.join(tmpdir(), 'music-synth-'));
  const env = {
    ...process.env, PORT: String(PORT), RAGDAMAXING_DB: path.join(dbDir, 'music.db'),
    RAGDAMAXING_MUSIC: '1', RAGDAMAXING_YTDLP: FAKE, RAGDAMAXING_MUSIC_CACHE_MB: '10',
    RAGDAMAXING_MUSIC_CACHE_DIR: path.join(dbDir, 'cache'), FAKE_AUDIO_URL: `http://127.0.0.1:${audioSrv.address().port}/audio.wav`,
  };
  delete env.TURN_URLS; delete env.TURN_SECRET; delete env.RAGDAMAXING_MUSIC_REMOTE;
  server = spawn('python3', ['server.py'], { cwd: APP, env, stdio: ['ignore', 'pipe', 'pipe'] });
  let log = '';
  server.stdout.on('data', d => { log += d; });
  server.stderr.on('data', d => { log += d; });
  const end = Date.now() + 15000;
  while (Date.now() < end) {
    try { const r = await fetch(BASE + '/api/ping'); if (r.ok) return; } catch (e) { }
    await sleep(200);
  }
  throw new Error('server did not start:\n' + log.slice(-2500));
}

async function startChrome() {
  profile = await mkdtemp(path.join(tmpdir(), 'music-chrome-'));
  chrome = spawn('chromium', [
    '--headless=new', `--remote-debugging-port=${DEBUG_PORT}`, `--user-data-dir=${profile}`,
    '--no-first-run', '--no-default-browser-check', '--use-fake-ui-for-media-stream',
    '--use-fake-device-for-media-stream', '--autoplay-policy=no-user-gesture-required',
    '--disable-background-timer-throttling', '--disable-backgrounding-occluded-windows',
    '--disable-renderer-backgrounding', '--disable-dev-shm-usage', '--window-size=1280,900', 'about:blank',
  ], { stdio: ['ignore', 'ignore', 'pipe'] });
  let err = '';
  chrome.stderr.on('data', d => { err += d; });
  const end = Date.now() + 20000;
  while (Date.now() < end) {
    try {
      const r = await fetch(`http://127.0.0.1:${DEBUG_PORT}/json/version`);
      if (r.ok) return (await r.json()).webSocketDebuggerUrl;
    } catch (e) { }
    await sleep(200);
  }
  throw new Error('chromium did not start:\n' + err.slice(-2000));
}

async function connect(url) {
  const ws = new WebSocket(url);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = () => rej(new Error('cdp socket failed')); });
  let seq = 0;
  const waiting = new Map();
  ws.onmessage = ev => {
    let m; try { m = JSON.parse(ev.data); } catch (e) { return; }
    if (!m.id || !waiting.has(m.id)) return;
    const w = waiting.get(m.id); waiting.delete(m.id);
    if (m.error) w.rej(new Error(JSON.stringify(m.error))); else w.res(m.result);
  };
  const send = (method, params = {}, sessionId) => new Promise((res, rej) => {
    const id = ++seq; waiting.set(id, { res, rej });
    ws.send(JSON.stringify({ id, method, params, sessionId }));
  });
  return { ws, send };
}

async function openPage(cdp, token, label) {
  const ctx = await cdp.send('Target.createBrowserContext', { disposeOnDetach: false });
  const target = await cdp.send('Target.createTarget', { url: 'about:blank', browserContextId: ctx.browserContextId });
  const att = await cdp.send('Target.attachToTarget', { targetId: target.targetId, flatten: true });
  const sid = att.sessionId;
  const send = (m, p = {}) => cdp.send(m, p, sid);
  await send('Page.enable'); await send('Runtime.enable'); await send('Network.enable');
  await send('Network.setCookie', { name: 'og', value: token, url: BASE, httpOnly: true, sameSite: 'Lax' });
  await send('Page.addScriptToEvaluateOnNewDocument', {
    source: 'window.__errs=[];addEventListener("error",function(e){__errs.push(String(e.message||e.error))});addEventListener("unhandledrejection",function(e){__errs.push(String(e.reason&&e.reason.message||e.reason))});',
  });
  await send('Page.navigate', { url: BASE + '/' });
  const ev = async (expression, awaitPromise = false) => {
    const r = await send('Runtime.evaluate', { expression, awaitPromise, returnByValue: true });
    if (r.exceptionDetails) throw new Error(label + ' evaluate: ' + (r.exceptionDetails.exception && r.exceptionDetails.exception.description || r.exceptionDetails.text));
    return r.result ? r.result.value : undefined;
  };
  const end = Date.now() + 20000;
  while (Date.now() < end) {
    try { if (await ev('!!(window.Music && window.Chat && typeof S !== "undefined" && S.user)')) break; } catch (e) { }
    await sleep(200);
  }
  await ev('S.tab="chat"; Chat.load().then(function(){render();})', true);
  await until(ev, 'window.Chat && C.loaded === true', 15000, 'chat load');
  return { label, ev };
}

async function until(ev, expr, ms, label) {
  const end = Date.now() + ms;
  let last = null;
  while (Date.now() < end) {
    try { last = await ev(expr); if (last) return last; } catch (e) { last = e.message; }
    await sleep(200);
  }
  throw new Error('timeout waiting for ' + label + ' :: ' + expr + ' :: ' + JSON.stringify(last));
}

async function join(page, ch) {
  await page.ev(`Chat.joinVoice(${ch})`, true);
  await until(page.ev, 'C.voice.joined === true', 15000, 'voice join');
  await until(page.ev, 'window.Music && Music.attached()', 10000, 'music attach');
}

const probe = `(() => { const a = document.getElementById('music_audio'); const t = window.Music && Music.nowTrack(); return { t: a ? +a.currentTime.toFixed(3) : null, paused: a ? a.paused : null, ready: a ? a.readyState : 0, track: t ? t.id : '', title: document.getElementById('music_now_title') ? document.getElementById('music_now_title').textContent : '', errs: (window.__errs || []).slice(-4) }; })()`;

try {
  await startServer();
  const owner = await req('POST', '/api/register', { username: 'owner', pin: '1234', crew_name: 'MusicLab' });
  const ownerCookie = 'og=' + cookieValue(owner.cookies, 'og');
  const code = (await req('GET', '/api/crew', undefined, ownerCookie)).body.crew.code;
  const listener = await req('POST', '/api/register', { username: 'listener', pin: '1234', crew_code: code });
  const listenerCookie = 'og=' + cookieValue(listener.cookies, 'og');
  const sid = (await req('GET', '/api/servers', undefined, ownerCookie)).body.servers[0].id;
  const mk = await req('POST', '/api/channel/create', { sid, name: 'music-lab', kind: 'voice' }, ownerCookie);
  const ch = mk.body.channel_id;
  check('voice channel created', !!ch, mk);

  cdp = await connect(await startChrome());
  const o = await openPage(cdp, cookieValue(owner.cookies, 'og'), 'owner');
  const b = await openPage(cdp, cookieValue(listener.cookies, 'og'), 'listener');
  check('music.js loaded on both pages', await o.ev('typeof Music.attach === "function"') && await b.ev('typeof Music.attach === "function"'), {});

  await join(o, ch);
  await join(b, ch);
  check('music panel rendered', await o.ev('!!document.getElementById("music_panel")'), await o.ev('document.getElementById("music_panel") && document.getElementById("music_panel").textContent'));
  await o.ev('Music.slash("/play lofi")');
  await until(o.ev, 'Music.nowTrack() && Music.nowTrack().id === "tst00000001"', 15000, 'owner playback');
  await until(b.ev, 'Music.nowTrack() && Music.nowTrack().id === "tst00000001"', 15000, 'listener playback');
  await until(b.ev, '(() => { const a = document.getElementById("music_audio"); return a && a.readyState >= 2 && a.currentTime > 0.2; })()', 20000, 'listener audio started');
  await sleep(1200);
  const samples = [];
  for (let i = 0; i < 5; i++) {
    const [oa, ba] = await Promise.all([o.ev(probe), b.ev(probe)]);
    samples.push({ oa, ba, drift: oa.t != null && ba.t != null ? Math.abs(oa.t - ba.t) : 999 });
    await sleep(500);
  }
  const worst = Math.max(...samples.map(s => s.drift));
  check('two browsers stay within 500 ms', worst <= 0.5, samples);
  check('both players are playing', samples.every(s => s.oa.paused === false && s.ba.paused === false), samples);
  check('now-playing panel has the track', samples.some(s => /Fake Song/.test(s.oa.title)), samples[0]);
  const first = samples[samples.length - 1].oa.track;
  const queued = await o.ev('api("music/add", { channel: ' + ch + ', id: "tst00000002" })', true);
  check('second track queued', queued && queued.queue && queued.queue.length === 1, queued);
  await o.ev('Music.slash("/skip")');
  await until(b.ev, `Music.nowTrack() && Music.nowTrack().id !== '${first}'`, 10000, 'listener skip event');
  const [o2, b2] = await Promise.all([o.ev(probe), b.ev(probe)]);
  check('skip arrives on the other browser', o2.track === b2.track && o2.track !== first, { o2, b2 });

  await b.ev('Chat.leaveVoice()');
  await until(b.ev, 'C.voice.joined === false && !Music.nowTrack()', 8000, 'listener teardown');
  const gone = await b.ev(probe);
  check('leaving stops the listener audio', gone.paused === true && gone.track === '', gone);
  await o.ev('Music.slash("/stop")');
  await until(o.ev, '!Music.nowTrack()', 8000, 'owner stop');
  await o.ev('Chat.leaveVoice()');

  const errs = (await o.ev('window.__errs || []')).concat(await b.ev('window.__errs || []'));
  check('no uncaught browser errors', errs.length === 0, errs);
} catch (e) {
  failures.push('harness: ' + e.message);
  console.error('HARNESS ERROR\n' + (e.stack || e.message));
} finally {
  try { if (cdp) cdp.ws.close(); } catch (e) { }
  try { if (chrome) chrome.kill('SIGKILL'); } catch (e) { }
  try { if (server) server.kill('SIGKILL'); } catch (e) { }
  try { if (audioSrv) audioSrv.close(); } catch (e) { }
  await sleep(300);
  try { if (profile) await rm(profile, { recursive: true, force: true }); } catch (e) { }
  try { if (dbDir) await rm(dbDir, { recursive: true, force: true }); } catch (e) { }
}

console.log(failures.length ? '\nFAILURES: ' + failures.join(' | ') : '\nALL OK');
process.exit(failures.length ? 1 : 0);