#!/usr/bin/env node
/*
 Headless boot smoke test (no npm deps, no Playwright).

   node tests/smoke_cdp.mjs

 Starts server.py on a throwaway DB, drives /usr/bin/chromium over the DevTools
 protocol with Node's global WebSocket, registers a user, then opens every tab.

 Fails on: an uncaught exception, console.error, a log error, or any HTTP
 4xx/5xx (except /favicon.ico). The exhaustive [data-act] click sweep from
 agent_help.md 6.3 is not implemented yet; this covers boot + all six tabs.

 Env: CHROME, PYTHON, SMOKE_PORT, SMOKE_CDP_PORT.
*/
import { spawn } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const PY = process.env.PYTHON || "python3";
const CHROME = process.env.CHROME || "/usr/bin/chromium";
const PORT = Number(process.env.SMOKE_PORT || 8801);
const DBG = Number(process.env.SMOKE_CDP_PORT || 9333);
const BASE = `http://127.0.0.1:${PORT}`;
const work = mkdtempSync(path.join(tmpdir(), "rag-smoke-"));
const wait = ms => new Promise(r => setTimeout(r, ms));

async function until(fn, ms = 15000, step = 150) {
  const end = Date.now() + ms;
  let last;
  while (Date.now() < end) {
    try {
      const v = await fn();
      if (v) return v;
    } catch (e) {
      last = e;
    }
    await wait(step);
  }
  throw last || new Error("timeout");
}

class CDP {
  constructor(ws) {
    this.ws = ws;
    this.id = 0;
    this.pending = new Map();
    this.on = {};
    ws.onmessage = ev => {
      const m = JSON.parse(ev.data);
      if (m.id) {
        const p = this.pending.get(m.id);
        if (!p) return;
        this.pending.delete(m.id);
        m.error ? p.reject(new Error(m.error.message)) : p.resolve(m.result);
      } else if (m.method && this.on[m.method]) {
        this.on[m.method](m.params);
      }
    };
  }

  static async open(url) {
    const ws = new WebSocket(url);
    await new Promise((res, rej) => {
      ws.onopen = res;
      ws.onerror = () => rej(new Error("could not connect to the DevTools socket"));
    });
    return new CDP(ws);
  }

  send(method, params = {}) {
    const id = ++this.id;
    this.ws.send(JSON.stringify({ id, method, params }));
    return new Promise((resolve, reject) => this.pending.set(id, { resolve, reject }));
  }

  close() {
    try { this.ws.close(); } catch {}
  }
}

let server, chrome, cdp;
const problems = [];

try {
  server = spawn(PY, ["server.py"], {
    cwd: ROOT,
    env: { ...process.env, PORT: String(PORT), RAGDAMAXING_DB: path.join(work, "t.db"), RAGDAMAXING_BIND: "127.0.0.1", RAGDAMAXING_ADMINS: "smoke" },
    stdio: ["ignore", "pipe", "pipe"],
    detached: true,
  });
  let srvErr = "";
  server.stderr.on("data", d => { srvErr += d; });
  await until(async () => (await fetch(BASE + "/api/ping")).ok, 15000);

  chrome = spawn(CHROME, [
    "--headless=new", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
    `--remote-debugging-port=${DBG}`, `--user-data-dir=${path.join(work, "chr")}`, "about:blank",
  ], { stdio: "ignore", detached: true });

  const target = await until(async () => {
    const list = await (await fetch(`http://127.0.0.1:${DBG}/json`)).json();
    return list.find(t => t.type === "page" && t.webSocketDebuggerUrl);
  }, 20000);

  cdp = await CDP.open(target.webSocketDebuggerUrl);
  cdp.on["Runtime.exceptionThrown"] = p =>
    problems.push("uncaught: " + (p.exceptionDetails?.exception?.description || p.exceptionDetails?.text));
  cdp.on["Runtime.consoleAPICalled"] = p => {
    if (p.type === "error") problems.push("console.error: " + p.args.map(a => a.value ?? a.description ?? "").join(" "));
  };
  cdp.on["Log.entryAdded"] = p => { if (p.entry?.level === "error") problems.push("log: " + p.entry.text); };
  cdp.on["Network.responseReceived"] = p => {
    const r = p.response;
    if (r.status >= 400 && !r.url.endsWith("/favicon.ico")) problems.push(`http ${r.status} ${r.url}`);
  };

  await cdp.send("Runtime.enable");
  await cdp.send("Log.enable");
  await cdp.send("Network.enable");
  await cdp.send("Page.enable");
  await cdp.send("Emulation.setDeviceMetricsOverride", { width: 412, height: 860, deviceScaleFactor: 2, mobile: true });

  await cdp.send("Page.navigate", { url: BASE + "/" });
  await until(() => cdp.send("Runtime.evaluate", { expression: 'document.readyState === "complete"', returnByValue: true }).then(r => r.result.value), 15000);

  const reg = await cdp.send("Runtime.evaluate", {
    expression: `(async () => (await fetch('/api/register', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({username:'smoke', pin:'1234', crew_name:'Smoke Crew'})})).status)()`,
    awaitPromise: true,
    returnByValue: true,
  });
  if (reg.result.value !== 200) throw new Error("register failed with " + reg.result.value);

  await cdp.send("Page.navigate", { url: BASE + "/" });
  await until(() => cdp.send("Runtime.evaluate", { expression: 'document.readyState === "complete" && typeof S !== "undefined" && !!S.user', returnByValue: true }).then(r => r.result.value), 15000);

  for (const tab of ["today", "crew", "chat", "study", "reflect", "me"]) {
    const r = await cdp.send("Runtime.evaluate", {
      expression: `(async () => { await go(${JSON.stringify(tab)}); return { tab: S.tab, len: document.getElementById('app').textContent.length, nav: !!document.querySelector('.nav') }; })()`,
      awaitPromise: true,
      returnByValue: true,
    });
    const v = r.result.value;
    if (!v || v.tab !== tab || v.len < 20 || !v.nav) problems.push(`tab ${tab} did not render (${JSON.stringify(v)})`);
    await wait(250);
  }

  // P-09: render() must patch the existing DOM, not replace it.
  const morph = await cdp.send("Runtime.evaluate", {
    expression: `(async () => {
      await go('today');
      const app = document.getElementById('app');
      const first = app.firstElementChild, sec = app.querySelector('section');
      render();
      return { app: document.getElementById('app') === app, first: app.firstElementChild === first, sec: app.querySelector('section') === sec };
    })()`,
    awaitPromise: true, returnByValue: true,
  });
  const m = morph.result.value;
  if (!m || !m.app || !m.first || !m.sec) problems.push("P-09: render() replaced DOM nodes " + JSON.stringify(m));

  // P-09: a focused input keeps focus (and its uncommitted value) across a render.
  const focus = await cdp.send("Runtime.evaluate", {
    expression: `(async () => {
      await go('reflect');
      const inp = document.getElementById('d_title');
      if (!inp) return { skip: 'no diary input' };
      inp.value = 'keep me'; inp.focus();
      render();
      return { same: document.activeElement === inp, value: document.getElementById('d_title').value };
    })()`,
    awaitPromise: true, returnByValue: true,
  });
  const f = focus.result.value;
  if (f && f.skip) console.log("SMOKE NOTE: focus check skipped (" + f.skip + ")");
  else if (!f || !f.same || f.value !== 'keep me') problems.push("P-09: focus/value lost on render " + JSON.stringify(f));

  // P-10: a new message appends; the existing message node is not rebuilt.
  const chat = await cdp.send("Runtime.evaluate", {
    expression: `(async () => {
      await go('chat');
      const t = (CH.threads || []).find(x => x.kind === 'crew') || (CH.threads || [])[0];
      if (!t) return { skip: 'no thread' };
      await chatOpen(t.key);
      const ta = document.getElementById('chat_in');
      ta.value = 'smoke one'; await chatSend();
      const first = document.querySelector('.msg[data-mid]'), id = first && first.dataset.mid;
      ta.value = 'smoke two'; await chatSend();
      return { id, same: !!first && document.querySelector('.msg[data-mid="' + id + '"]') === first,
               count: document.querySelectorAll('.msg[data-mid]').length };
    })()`,
    awaitPromise: true, returnByValue: true,
  });
  const c = chat.result.value;
  if (c && c.skip) console.log("SMOKE NOTE: chat check skipped (" + c.skip + ")");
  else if (!c || !c.same || c.count !== 2) problems.push("P-10: chat did not append in place " + JSON.stringify(c));

  if (problems.length) {
    console.error("SMOKE FAILED");
    for (const p of [...new Set(problems)]) console.error(" - " + p);
    if (srvErr) console.error("server stderr:\n" + srvErr.split("\n").slice(-10).join("\n"));
    process.exitCode = 1;
  } else {
    console.log("SMOKE OK: boot, register, 6 tabs, 0 exceptions / console errors / 4xx-5xx");
  }
} finally {
  cdp?.close();
  for (const p of [chrome, server]) {
    if (!p?.pid) continue;
    try { process.kill(-p.pid, "SIGTERM"); } catch { try { p.kill("SIGTERM"); } catch {} }
  }
  await wait(400);
  rmSync(work, { recursive: true, force: true });
}
