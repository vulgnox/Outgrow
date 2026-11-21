/* Synthetic screen-share pipeline test (no packages).
 *
 * Starts the app on a temp DB, drives Chromium over CDP, replaces real
 * getDisplayMedia with a moving 1920x1080 canvas (?synthetic=1 is loopback
 * only), and asserts sender/receiver stats for 1 and 2 viewers.
 *
 * Run: node tools/screen_synthetic.mjs
 */
import { spawn } from 'node:child_process';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const APP = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const PORT = 8814;
const DEBUG_PORT = 9333;
const BASE = `http://127.0.0.1:${PORT}`;
const sleep = ms => new Promise(r => setTimeout(r, ms));
const SECONDS = Math.max(5, +(process.env.SCREEN_SECONDS || 20));
const RUNS = process.env.SCREEN_RUNS || 'both';
const AUTO = process.env.SCREEN_AUTO || '1';
const CODEC = process.env.SCREEN_CODEC || '';
const STRICT = process.env.SCREEN_STRICT === '1';
const perf = (name, ok, detail) => {
  if (STRICT) check(name, ok, detail);
  else console.log((ok ? 'MEASURED OK ' : 'MEASURED LOW ') + name + ' :: ' + JSON.stringify(detail));
};

let server = null, chrome = null, profile = '', dbDir = '';
const failures = [];

function check(name, ok, detail) {
  console.log((ok ? 'PASS ' : 'FAIL ') + name + (ok ? '' : ' :: ' + JSON.stringify(detail)));
  if (!ok) failures.push(name);
}

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
  for (const c of setCookies) {
    if (c.startsWith(name + '=')) return c.slice(name.length + 1).split(';')[0];
  }
  return '';
}

async function startServer() {
  dbDir = await mkdtemp(path.join(tmpdir(), 'screen-synth-'));
  const env = {
    ...process.env,
    PORT: String(PORT),
    RAGDAMAXING_DB: path.join(dbDir, 'screen.db'),
    RAGDAMAXING_ADMINS: 'boss',
    RAGDAMAXING_SCREEN_MAX_VIEWERS: '3',
  };
  delete env.TURN_URLS;
  delete env.TURN_SECRET;
  server = spawn('python3', ['server.py'], { cwd: APP, env, stdio: ['ignore', 'pipe', 'pipe'] });
  let log = '';
  server.stdout.on('data', d => { log += d; });
  server.stderr.on('data', d => { log += d; });
  const end = Date.now() + 15000;
  while (Date.now() < end) {
    try {
      const r = await fetch(BASE + '/api/ping');
      if (r.ok) return;
    } catch (e) { }
    await sleep(200);
  }
  throw new Error('server did not start:\n' + log.slice(-2000));
}

async function startChrome() {
  profile = await mkdtemp(path.join(tmpdir(), 'screen-chrome-'));
  chrome = spawn('chromium', [
    '--headless=new',
    `--remote-debugging-port=${DEBUG_PORT}`,
    `--user-data-dir=${profile}`,
    '--no-first-run',
    '--no-default-browser-check',
    '--use-fake-ui-for-media-stream',
    '--use-fake-device-for-media-stream',
    '--autoplay-policy=no-user-gesture-required',
    '--disable-background-timer-throttling',
    '--disable-backgrounding-occluded-windows',
    '--disable-renderer-backgrounding',
    '--disable-dev-shm-usage',
    '--window-size=1280,900',
    'about:blank',
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

async function cdpConnect(url) {
  const ws = new WebSocket(url);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = () => rej(new Error('cdp socket failed')); });
  let seq = 0;
  const waiting = new Map();
  ws.onmessage = ev => {
    let m;
    try { m = JSON.parse(ev.data); } catch (e) { return; }
    if (!m.id || !waiting.has(m.id)) return;
    const w = waiting.get(m.id); waiting.delete(m.id);
    if (m.error) w.rej(new Error(JSON.stringify(m.error)));
    else w.res(m.result);
  };
  const send = (method, params = {}, sessionId) => new Promise((res, rej) => {
    const id = ++seq;
    waiting.set(id, { res, rej });
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
  await send('Page.enable');
  await send('Runtime.enable');
  await send('Network.enable');
  await send('Network.setCookie', { name: 'og', value: token, url: BASE, httpOnly: true, sameSite: 'Lax' });
  const q = new URLSearchParams({ synthetic: '1', auto: AUTO });
  if (CODEC) q.set('codec', CODEC);
  await send('Page.navigate', { url: BASE + '/?' + q.toString() });

  const ev = async (expression, awaitPromise = false) => {
    const r = await send('Runtime.evaluate', { expression, awaitPromise, returnByValue: true });
    if (r.exceptionDetails) {
      const d = r.exceptionDetails;
      throw new Error(label + ' evaluate: ' + (d.exception && d.exception.description || d.text) + '\n' + expression);
    }
    return r.result ? r.result.value : undefined;
  };

  const end = Date.now() + 25000;
  while (Date.now() < end) {
    try { if (await ev('!!(window.Chat && window.S && S.user)')) break; } catch (e) { }
    await sleep(200);
  }
  await ev('S.tab = "chat"; Chat.load().then(function(){ render(); })', true);
  await ev('Chat.loaded === true', true).catch(() => { });
  return { label, ev, send, sid };
}

async function until(page, expr, ms, label) {
  const end = Date.now() + ms;
  let last = null;
  while (Date.now() < end) {
    try { last = await page.ev(expr); if (last) return last; } catch (e) { last = e.message; }
    await sleep(250);
  }
  throw new Error('timeout waiting for ' + label + ' on ' + page.label + ' :: ' + expr + ' :: ' + JSON.stringify(last));
}

async function join(page, ch) {
  await page.ev(`Chat.joinVoice(${ch})`, true);
  await until(page, 'C.voice.joined === true', 15000, 'voice join');
}

async function waitPeers(page, n) {
  await until(page, `Object.values(C.voice.peers).length >= ${n} && Object.values(C.voice.peers).every(p => p.pc && p.pc.connectionState === "connected")`, 25000, n + ' connected peers');
}

async function sample(owner, viewers, seconds) {
  const rows = [];
  const end = Date.now() + seconds * 1000;
  while (Date.now() < end) {
    await sleep(2000);
    const snap = await owner.ev('Chat.screenSnapshot()');
    const vs = [];
    for (const v of viewers) vs.push(await v.ev('Chat.screenSnapshot()'));
    rows.push({ at: Date.now(), owner: snap, viewers: vs });
  }
  return rows;
}

function summarize(rows, viewers) {
  const out = [];
  for (const r of rows) for (const s of r.owner.out) {
    const x = s.last; if (!x) continue;
    let t = out.find(o => o.uid === s.uid);
    if (!t) { t = { uid: s.uid, fps: [], w: [], reason: {}, bitrate: [], srcFps: [] }; out.push(t); }
    t.fps.push(x.fps); t.w.push(x.w); t.bitrate.push(x.bitrate); t.srcFps.push(x.srcFps);
    t.reason[x.reason] = (t.reason[x.reason] || 0) + 1;
  }
  const ins = [];
  for (const r of rows) r.viewers.forEach((snap, i) => {
    for (const s of snap.in) {
      const x = s.last; if (!x) continue;
      let t = ins.find(o => o.uid === s.uid);
      if (!t) { t = { uid: s.uid, fps: [], w: [], dropped: [], freeze: [], bitrate: [] }; ins.push(t); }
      t.fps.push(x.fps); t.w.push(x.w); t.bitrate.push(x.bitrate); t.dropped.push(x.dropped); t.freeze.push(x.freeze);
    }
  });
  const avg = a => a.length ? +(a.reduce((s, n) => s + n, 0) / a.length).toFixed(1) : 0;
  const min = a => a.length ? Math.min(...a) : 0;
  const last = rows[rows.length - 1] || {};
  return {
    sender: out.map(o => ({ uid: o.uid, avgFps: avg(o.fps), minFps: min(o.fps), width: min(o.w), avgMbps: +(avg(o.bitrate) / 1e6).toFixed(2), avgSrcFps: avg(o.srcFps), reasons: o.reason })),
    viewers: ins.map(o => ({ uid: o.uid, avgFps: avg(o.fps), minFps: min(o.fps), width: min(o.w), avgMbps: +(avg(o.bitrate) / 1e6).toFixed(2), dropped: o.dropped.length ? o.dropped[o.dropped.length - 1] - o.dropped[0] : 0, freezes: o.freeze.length ? o.freeze[o.freeze.length - 1] - o.freeze[0] : 0 })),
    capture: last.owner && last.owner.stats && last.owner.stats.capture,
    role: last.owner && last.owner.stats && { preset: last.owner.stats.preset, viewers: last.owner.stats.viewers },
    lastOut: last.owner && last.owner.stats && last.owner.stats.out,
    lastIn: last.viewers && last.viewers[0] && last.viewers[0].stats && last.viewers[0].stats.in,
  };
}

let cdp = null;
try {
  await startServer();

  const owner = await req('POST', '/api/register', { username: 'owner', pin: '1234', crew_name: 'ScreenLab' });
  const ownerCookie = 'og=' + cookieValue(owner.cookies, 'og');
  check('owner registered', owner.status === 200 && ownerCookie.length > 4, owner);
  const crew = await req('GET', '/api/crew', undefined, ownerCookie);
  const code = crew.body.crew && crew.body.crew.code;
  const v1 = await req('POST', '/api/register', { username: 'viewer1', pin: '1234', crew_code: code });
  const v2 = await req('POST', '/api/register', { username: 'viewer2', pin: '1234', crew_code: code });
  const v1Cookie = 'og=' + cookieValue(v1.cookies, 'og');
  const v2Cookie = 'og=' + cookieValue(v2.cookies, 'og');
  check('viewers registered', v1.status === 200 && v2.status === 200, { v1, v2 });

  const servers = await req('GET', '/api/servers', undefined, ownerCookie);
  const sid = servers.body.servers && servers.body.servers[0] && servers.body.servers[0].id;
  const mk = await req('POST', '/api/channel/create', { sid, name: 'screen-lab', kind: 'voice' }, ownerCookie);
  const ch = mk.body.channel_id;
  check('voice channel created', !!ch, mk);

  cdp = await cdpConnect(await startChrome());
  const o = await openPage(cdp, cookieValue(owner.cookies, 'og'), 'owner');
  const a = await openPage(cdp, cookieValue(v1.cookies, 'og'), 'viewer1');
  const b = await openPage(cdp, cookieValue(v2.cookies, 'og'), 'viewer2');
  check('three pages loaded', true, {});

  const ouid = await o.ev('S.user.id');
  await join(o, ch);
  await join(a, ch);
  await waitPeers(o, 1);
  await waitPeers(a, 1);
  const snap0 = await o.ev('Chat.screenSnapshot()');
  check('screen viewer cap is 3', snap0.max === 3, snap0);
  check('synthetic capture source is active', snap0.synthetic === true, snap0);

  // ---- 1 viewer: 1080p60 for 20 s
  await o.ev("Chat.startScreen('smooth60')", true);
  await until(o, 'C.voice.screen === true', 15000, 'sharing started');
  await until(a, 'Chat.screenSnapshot().in.length === 1 && Chat.screenSnapshot().in[0].stream === true', 20000, 'viewer screen stream');
  await until(a, 'Chat.screenSnapshot().in[0].state === "connected"', 20000, 'viewer screen pc connected');
  await sleep(8000);
  const run1 = await sample(o, [a], SECONDS);
  const sum1 = summarize(run1.slice(1), 1);
  check('1 viewer: capture is 1920 wide', (sum1.capture || {}).width === 1920, sum1);
  perf('1 viewer: sender 1920 wide', (sum1.lastOut || []).every(x => x.w === 1920), sum1);
  perf('1 viewer: sender >= 55 fps', sum1.sender.every(s => s.avgFps >= 55), sum1);
  perf('1 viewer: capture >= 55 fps', sum1.sender.every(s => s.avgSrcFps >= 55), sum1);
  perf('1 viewer: receiver >= 50 fps', sum1.viewers.every(s => s.avgFps >= 50), sum1);
  perf('1 viewer: receiver 1920 wide', (sum1.lastIn || []).every(x => x.w === 1920), sum1);
  perf('1 viewer: no freezes', sum1.viewers.every(s => s.freezes === 0), sum1);
  check('1 viewer: frames are flowing', (sum1.viewers[0] || {}).avgFps > 0, sum1);
  if (AUTO === '0') check('1 viewer: preset stays smooth60', sum1.role && sum1.role.preset === 'smooth60', sum1);
  await sleep(1500);
  const afterOwner = await o.ev('Chat.screenSnapshot()');
  const afterViewer = await a.ev('Chat.screenSnapshot()');
  check('1 viewer: viewer sees the active preset', (afterViewer.in[0] || {}).preset === afterOwner.preset, { owner: afterOwner.preset, viewer: afterViewer.in });
  console.log('RUN1 ' + JSON.stringify(sum1));

  await o.ev('Chat.stopScreen()');
  await until(a, 'Chat.screenSnapshot().in.length === 0', 10000, 'viewer teardown after stop');
  check('stop closes the viewer screen pc', true, {});

  // ---- 2 viewers: 1080p60 for 20 s
  if (RUNS !== '1') {
  await join(b, ch);
  await waitPeers(o, 2);
  await waitPeers(b, 2);
  await o.ev("Chat.startScreen('smooth60')", true);
  await until(o, 'C.voice.screen === true', 15000, 'second sharing started');
  await until(a, 'Chat.screenSnapshot().in.length === 1 && Chat.screenSnapshot().in[0].stream === true', 20000, 'viewer1 second stream');
  await until(b, 'Chat.screenSnapshot().in.length === 1 && Chat.screenSnapshot().in[0].stream === true', 20000, 'viewer2 second stream');
  await until(a, 'Chat.screenSnapshot().in[0].state === "connected"', 20000, 'viewer1 second pc');
  await until(b, 'Chat.screenSnapshot().in[0].state === "connected"', 20000, 'viewer2 second pc');
  await sleep(8000);
  const run2 = await sample(o, [a, b], SECONDS);
  const sum2 = summarize(run2.slice(1), 2);
  check('2 viewers: capture is 1920 wide', (sum2.capture || {}).width === 1920, sum2);
  perf('2 viewers: sender 1920 wide', (sum2.lastOut || []).every(x => x.w === 1920), sum2);
  perf('2 viewers: sender >= 55 fps', sum2.sender.every(s => s.avgFps >= 55), sum2);
  perf('2 viewers: receiver >= 50 fps', sum2.viewers.every(s => s.avgFps >= 50), sum2);
  perf('2 viewers: receiver 1920 wide', (sum2.lastIn || []).every(x => x.w === 1920), sum2);
  perf('2 viewers: no freezes', sum2.viewers.every(s => s.freezes === 0), sum2);
  check('2 viewers: two screen pcs', (await o.ev('Chat.screenSnapshot().out.length')) === 2, await o.ev('Chat.screenSnapshot()'));
  console.log('RUN2 ' + JSON.stringify(sum2));

  await o.ev('Chat.stopScreen()');
  }
  await o.ev('Chat.leaveVoice()');
  await until(o, 'C.voice.joined === false && C.voice.screen === false', 5000, 'clean leave');
  check('leave tears down sharing', true, {});
} catch (e) {
  failures.push('harness: ' + e.message);
  console.error('HARNESS ERROR\n' + (e.stack || e.message));
} finally {
  try { if (cdp) cdp.ws.close(); } catch (e) { }
  try { if (chrome) chrome.kill('SIGKILL'); } catch (e) { }
  try { if (server) server.kill('SIGKILL'); } catch (e) { }
  await sleep(300);
  try { if (profile) await rm(profile, { recursive: true, force: true }); } catch (e) { }
  try { if (dbDir) await rm(dbDir, { recursive: true, force: true }); } catch (e) { }
}

console.log(failures.length ? '\nFAILURES: ' + failures.join(' | ') : '\nALL OK');
process.exit(failures.length ? 1 : 0);
