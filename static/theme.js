'use strict';
/* RAGDAMAXING appearance engine.
   Two completely independent scopes:
     app  -> every token on :root (cards, nav, timer, everything)
     chat -> only --c-* tokens, consumed by .soc in chat.css
   Saved per browser in localStorage; custom wallpapers are blobs in IndexedDB
   (localStorage would blow up on a GIF). No server round-trip, no flash: this
   file runs in <head>, before the app scripts. */
window.Theme = (function () {
  const APP_KEY = 'rg_theme_app_v1';
  const CHAT_KEY = 'rg_theme_chat_v1';
  const UI_KEY = 'rg_ui_v1';
  const FX_KEY = 'rg_ui_fx_v1';
  const DB_NAME = 'ragda_theme';
  const UI_STYLES = [['glass', 'Glass', 'Frosted depth'], ['3d', '3D', 'Raised edges'], ['flat', 'Flat', 'Clean lines']];
  const FX_DEFAULT = { opacity: 88, blur: 12, depth: 80 };
  const FX_RANGE = { opacity: [35, 100], blur: [0, 24], depth: [0, 100] };

  const DEFAULT = { mode: 'dark', preset: 'default', accent: '', accent2: '', accent3: '', accent4: '', accent5: '', bg: 'none', blur: 0, dim: 32, image: false };
  const CHAT_DEFAULT = Object.assign({}, DEFAULT, { follow: true });

  const BASE = {
    dark: {
      bg: '#09090b', s1: '#0f0f12', s2: '#16161a', s3: '#1e1e24', line: '#212127', line2: '#2d2d35',
      tx: '#ececf1', tx2: '#b4b4be', mut: '#80808c', rail: '#0b0b0f', panel: '#0e0e13', dock: '#111115',
    },
    light: {
      bg: '#f5f5f9', s1: '#ffffff', s2: '#f2f2f7', s3: '#e9e9f1', line: '#e6e6ee', line2: '#d6d6e1',
      tx: '#18181f', tx2: '#4e4e5e', mut: '#7b7b8b', rail: '#eeeef5', panel: '#fafaff', dock: '#ffffff',
    },
  };

  const PRESETS = {
    default: {
      name: 'Signature', accent: { dark: '#7c6af7', light: '#6a58e8' },
      accents: { data: { dark: '#5aa9ff', light: '#1f6fd0' }, ambient: { dark: '#ff7a5c', light: '#c03d6d' }, gold: { dark: '#f5b83d', light: '#a56a00' } },
      pal: {},
    },
    rose: {
      name: 'Rosé Pine', accent: { dark: '#c4a7e7', light: '#806a9a' },
      accents: { data: { dark: '#9ccfd8', light: '#3f7d86' }, ambient: { dark: '#ebbcba', light: '#b4636a' }, gold: { dark: '#f6c177', light: '#9a6a1f' } },
      pal: {
        dark: {
          bg: '#191724', s1: '#1f1d2e', s2: '#26233a', s3: '#2f2b46', line: '#2a2740', line2: '#3b3757',
          tx: '#e0def4', tx2: '#b6b0d6', mut: '#908caa', rail: '#15131f', panel: '#1b1929', dock: '#211e31',
        },
        light: {
          bg: '#faf4ed', s1: '#fffaf3', s2: '#f2e9e1', s3: '#e9dfd5', line: '#e6d9cd', line2: '#d8c9bb',
          tx: '#575279', tx2: '#6e6a86', mut: '#9893a5', rail: '#f3e9e0', panel: '#fffaf3', dock: '#fffaf3',
        },
      },
    },
    moss: {
      name: 'Evergreen', accent: { dark: '#3dd6a0', light: '#147a59' },
      accents: { data: { dark: '#8bd450', light: '#3f7d20' }, ambient: { dark: '#f2b441', light: '#a56a00' }, gold: { dark: '#e9c46a', light: '#8a6510' } },
      pal: {
        dark: {
          bg: '#08110d', s1: '#0d1712', s2: '#122019', s3: '#173026', line: '#152820', line2: '#214032',
          tx: '#e4f4ea', tx2: '#a7c7b5', mut: '#7b9788', rail: '#07100c', panel: '#0b1510', dock: '#101d17',
        },
        light: {
          bg: '#f3f8f5', s1: '#ffffff', s2: '#edf5f0', s3: '#e0eee7', line: '#dcebe3', line2: '#c9ddd2',
          tx: '#14241c', tx2: '#456052', mut: '#6f8a7c', rail: '#eaf3ee', panel: '#fbfefc', dock: '#ffffff',
        },
      },
    },
    tide: {
      name: 'Tide', accent: { dark: '#5aa9ff', light: '#1f6fd0' },
      accents: { data: { dark: '#3dd6a0', light: '#147a59' }, ambient: { dark: '#f4a261', light: '#b35c1e' }, gold: { dark: '#ffd166', light: '#8a6510' } },
      pal: {
        dark: {
          bg: '#070d16', s1: '#0c1420', s2: '#111c2b', s3: '#16273a', line: '#152233', line2: '#203349',
          tx: '#e6effa', tx2: '#a8bdd6', mut: '#7b91aa', rail: '#060b12', panel: '#0a121d', dock: '#0f1a28',
        },
        light: {
          bg: '#f3f7fc', s1: '#ffffff', s2: '#edf3fa', s3: '#e2ebf6', line: '#dee8f4', line2: '#cbdaeb',
          tx: '#10202f', tx2: '#435c72', mut: '#6f8499', rail: '#eaf2fa', panel: '#fbfdff', dock: '#ffffff',
        },
      },
    },
    graphite: {
      name: 'Graphite', accent: { dark: '#b6c0d2', light: '#566173' },
      accents: { data: { dark: '#8fa3bf', light: '#4a5a70' }, ambient: { dark: '#b6c0d2', light: '#566173' }, gold: { dark: '#d4b483', light: '#7a5a20' } },
      pal: {
        dark: {
          bg: '#0a0a0c', s1: '#101012', s2: '#17171a', s3: '#202024', line: '#222226', line2: '#2e2e34',
          tx: '#ececef', tx2: '#b6b6bd', mut: '#82828b', rail: '#0c0c0e', panel: '#0f0f11', dock: '#131316',
        },
        light: {
          bg: '#f4f5f7', s1: '#ffffff', s2: '#f0f1f4', s3: '#e6e8ec', line: '#e3e5e9', line2: '#d3d6dc',
          tx: '#191a1d', tx2: '#4e5057', mut: '#797c84', rail: '#edeef2', panel: '#fafbfc', dock: '#ffffff',
        },
      },
    },
    bloom: {
      name: 'Blossom', accent: { dark: '#f0709a', light: '#c03d6d' },
      accents: { data: { dark: '#c4a7e7', light: '#7b5aa0' }, ambient: { dark: '#ffd6a5', light: '#b06a3a' }, gold: { dark: '#ffb3c8', light: '#a03a5a' } },
      pal: {
        dark: {
          bg: '#140d12', s1: '#1d131a', s2: '#251821', s3: '#2f1f2a', line: '#2a1b24', line2: '#3d2835',
          tx: '#f6e8ef', tx2: '#cba8b9', mut: '#a1818f', rail: '#110b0f', panel: '#1a1117', dock: '#211620',
        },
        light: {
          bg: '#fdf4f7', s1: '#ffffff', s2: '#fbeef3', s3: '#f6e2ea', line: '#f4e1e9', line2: '#ecd0dc',
          tx: '#2a1520', tx2: '#6a4254', mut: '#95707f', rail: '#fbebf1', panel: '#fffafc', dock: '#ffffff',
        },
      },
    },
  };

  const ACCENTS = ['#7c6af7', '#c4a7e7', '#5aa9ff', '#3dd6a0', '#a3e635', '#f5b83d', '#ff7a5c', '#f0709a', '#ff5468', '#b6c0d2'];

  const BGS = {
    aurora: m => m === 'dark'
      ? 'radial-gradient(120% 85% at 10% 0%, #2b1e5e 0%, transparent 58%), radial-gradient(85% 70% at 94% 6%, #0d4a44 0%, transparent 55%), radial-gradient(110% 90% at 52% 110%, #4a1733 0%, transparent 62%), linear-gradient(#09090b,#09090b)'
      : 'radial-gradient(120% 85% at 10% 0%, #ddd4ff 0%, transparent 60%), radial-gradient(85% 70% at 94% 6%, #d2f4ea 0%, transparent 58%), radial-gradient(110% 90% at 52% 110%, #ffe0ec 0%, transparent 64%), linear-gradient(#f7f5ff,#f7f5ff)',
    ember: m => m === 'dark'
      ? 'radial-gradient(110% 80% at 12% 4%, #4a1f0c 0%, transparent 56%), radial-gradient(90% 70% at 90% 18%, #3a2608 0%, transparent 55%), radial-gradient(100% 90% at 48% 110%, #2a0d12 0%, transparent 60%), linear-gradient(#0b0908,#0b0908)'
      : 'radial-gradient(110% 80% at 12% 4%, #ffe0c7 0%, transparent 58%), radial-gradient(90% 70% at 90% 18%, #fff0c9 0%, transparent 56%), radial-gradient(100% 90% at 48% 110%, #ffdcd6 0%, transparent 62%), linear-gradient(#fdf8f3,#fdf8f3)',
    tide: m => m === 'dark'
      ? 'radial-gradient(120% 80% at 8% 0%, #0d2a4a 0%, transparent 58%), radial-gradient(90% 70% at 92% 10%, #0a3f3f 0%, transparent 55%), radial-gradient(100% 90% at 50% 108%, #101a3a 0%, transparent 62%), linear-gradient(#070d16,#070d16)'
      : 'radial-gradient(120% 80% at 8% 0%, #d6e8ff 0%, transparent 60%), radial-gradient(90% 70% at 92% 10%, #d2f3f0 0%, transparent 58%), radial-gradient(100% 90% at 50% 108%, #dfe4ff 0%, transparent 64%), linear-gradient(#f4f9ff,#f4f9ff)',
    bloom: m => m === 'dark'
      ? 'radial-gradient(115% 85% at 14% 0%, #3c1530 0%, transparent 56%), radial-gradient(90% 70% at 92% 12%, #2a1030 0%, transparent 55%), radial-gradient(100% 90% at 50% 110%, #421327 0%, transparent 62%), linear-gradient(#120c12,#120c12)'
      : 'radial-gradient(115% 85% at 14% 0%, #ffd9e8 0%, transparent 58%), radial-gradient(90% 70% at 92% 12%, #eeddff 0%, transparent 57%), radial-gradient(100% 90% at 50% 110%, #ffe1e1 0%, transparent 64%), linear-gradient(#fdf6fa,#fdf6fa)',
    graphite: m => m === 'dark'
      ? 'radial-gradient(120% 90% at 20% 0%, #232329 0%, transparent 60%), radial-gradient(90% 70% at 90% 20%, #1a1d26 0%, transparent 58%), linear-gradient(#08080a,#08080a)'
      : 'radial-gradient(120% 90% at 20% 0%, #e9eaf0 0%, transparent 62%), radial-gradient(90% 70% at 90% 20%, #e6edf5 0%, transparent 60%), linear-gradient(#f6f7f9,#f6f7f9)',
  };

  const ICON = {
    sun: '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M19.1 4.9l-1.4 1.4M6.3 17.7l-1.4 1.4"/></svg>',
    moon: '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z"/></svg>',
    up: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 16V4M7 9l5-5 5 5M4 20h16"/></svg>',
    check: '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="m5 12.5 4.5 4.5L19 7.5"/></svg>',
    x: '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18"/></svg>',
  };

  /* ---------- colour math ---------- */
  const hex2rgb = h => {
    h = String(h || '#000').replace('#', '');
    if (h.length === 3) h = h.split('').map(c => c + c).join('');
    return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
  };
  const mix = (a, b, t) => {
    const A = hex2rgb(a), B = hex2rgb(b);
    return '#' + A.map((v, i) => Math.round(v + (B[i] - v) * t).toString(16).padStart(2, '0')).join('');
  };
  const lum = h => {
    const c = hex2rgb(h).map(v => { v /= 255; return v <= .03928 ? v / 12.92 : Math.pow((v + .055) / 1.055, 2.4); });
    return .2126 * c[0] + .7152 * c[1] + .0722 * c[2];
  };
  const rgba = (h, a) => { const [r, g, b] = hex2rgb(h); return `rgba(${r},${g},${b},${a})`; };

  /* ---------- state ---------- */
  const state = { app: load(APP_KEY, false), chat: load(CHAT_KEY, true), ui: loadUI(), fx: loadFX() };
  const urls = {};
  const urlRevoked = {};

  function customChat(s) {
    return !!(s.accent || s.accent2 || s.accent3 || s.accent4 || s.accent5 || s.image
      || (s.bg && s.bg !== 'none') || (s.mode && s.mode !== 'dark') || (s.preset && s.preset !== 'default')
      || s.blur || (s.dim != null && +s.dim !== DEFAULT.dim));
  }

  function loadUI() {
    try { const v = localStorage.getItem(UI_KEY); if (UI_STYLES.some(x => x[0] === v)) return v; } catch (e) { }
    return 'glass';
  }

  function loadFX() {
    let raw = null;
    try { raw = JSON.parse(localStorage.getItem(FX_KEY) || 'null'); } catch (e) { raw = null; }
    const out = Object.assign({}, FX_DEFAULT);
    if (raw && typeof raw === 'object') {
      Object.keys(FX_DEFAULT).forEach(k => {
        const n = +raw[k];
        if (Number.isFinite(n)) out[k] = Math.max(FX_RANGE[k][0], Math.min(FX_RANGE[k][1], Math.round(n)));
      });
    }
    return out;
  }

  function saveFX() {
    try { localStorage.setItem(FX_KEY, JSON.stringify(state.fx)); } catch (e) { }
  }

  function load(key, chat) {
    let raw = null;
    try { const v = localStorage.getItem(key); raw = v ? JSON.parse(v) : null; } catch (e) { raw = null; }
    const s = raw && typeof raw === 'object' ? raw : {};
    const out = Object.assign({}, chat ? CHAT_DEFAULT : DEFAULT, s);
    if (chat) out.follow = typeof s.follow === 'boolean' ? s.follow : !customChat(s);
    if (out.mode !== 'dark' && out.mode !== 'light') out.mode = 'dark';
    if (!PRESETS[out.preset]) out.preset = 'default';
    if (!BGS[out.bg] && out.bg !== 'none' && out.bg !== 'custom') out.bg = 'none';
    out.image = !!out.image;
    if (out.bg === 'custom' && !out.image) out.bg = 'none';
    ['accent', 'accent2', 'accent3', 'accent4', 'accent5'].forEach(k => {
      if (!/^#[0-9a-f]{6}$/i.test(out[k] || '')) out[k] = '';
    });
    out.dim = Math.max(0, Math.min(85, +out.dim || 0));
    out.blur = Math.max(0, Math.min(24, +out.blur || 0));
    return out;
  }

  function effective(scope) {
    const s = state[scope];
    return scope === 'chat' && s.follow ? Object.assign({}, state.app, { follow: true }) : s;
  }

  function presetSet(key, mode) {
    const p = PRESETS[key] || PRESETS.default;
    const primary = p.accent[mode];
    const roles = p.accents || {};
    return {
      primary,
      secondary: mix(primary, mode === 'dark' ? '#ffffff' : '#000000', mode === 'dark' ? .24 : .14),
      data: (roles.data && roles.data[mode]) || primary,
      ambient: (roles.ambient && roles.ambient[mode]) || primary,
      gold: (roles.gold && roles.gold[mode]) || '#f5b83d',
    };
  }

  function accentsFor(s) {
    const auto = presetSet(s.preset, s.mode);
    return {
      primary: s.accent || auto.primary,
      secondary: s.accent2 || auto.secondary,
      data: s.accent3 || auto.data,
      ambient: s.accent4 || auto.ambient,
      gold: s.accent5 || auto.gold,
    };
  }

  function save(scope) {
    try { localStorage.setItem(scope === 'chat' ? CHAT_KEY : APP_KEY, JSON.stringify(state[scope])); } catch (e) { }
  }

  function palette(scope) {
    const s = effective(scope);
    const preset = PRESETS[s.preset] || PRESETS.default;
    const pal = Object.assign({}, BASE[s.mode], (preset.pal && preset.pal[s.mode]) || {});
    const a = accentsFor(s);
    return { pal, accent: a.primary, accent2: a.secondary, accent3: a.data, accent4: a.ambient, accent5: a.gold };
  }

  /* ---------- IndexedDB wallpapers ---------- */
  let dbp = null;
  function db() {
    if (dbp) return dbp;
    dbp = new Promise((ok, no) => {
      try {
        const r = indexedDB.open(DB_NAME, 1);
        r.onupgradeneeded = () => { if (!r.result.objectStoreNames.contains('img')) r.result.createObjectStore('img'); };
        r.onsuccess = () => ok(r.result);
        r.onerror = () => no(r.error);
      } catch (e) { no(e); }
    });
    return dbp;
  }
  async function idbGet(key) {
    const d = await db();
    return new Promise((ok, no) => {
      const r = d.transaction('img', 'readonly').objectStore('img').get(key);
      r.onsuccess = () => ok(r.result || null); r.onerror = () => no(r.error);
    });
  }
  async function idbPut(key, blob) {
    const d = await db();
    return new Promise((ok, no) => {
      const tx = d.transaction('img', 'readwrite');
      tx.objectStore('img').put(blob, key);
      tx.oncomplete = () => ok(true); tx.onerror = () => no(tx.error);
    });
  }
  async function idbDel(key) {
    const d = await db();
    return new Promise((ok, no) => {
      const tx = d.transaction('img', 'readwrite');
      tx.objectStore('img').delete(key);
      tx.oncomplete = () => ok(true); tx.onerror = () => no(tx.error);
    });
  }

  function setUrl(scope, blob) {
    if (urls[scope]) { try { URL.revokeObjectURL(urls[scope]); } catch (e) { } }
    urls[scope] = blob ? URL.createObjectURL(blob) : '';
    urlRevoked[scope] = !blob;
  }

  async function hydrate(scope) {
    if (scope === 'chat' && state.chat.follow) return;
    if (!state[scope].image) return;
    try {
      const blob = await idbGet('wall:' + scope);
      if (!blob) { state[scope].image = false; state[scope].bg = state[scope].bg === 'custom' ? 'none' : state[scope].bg; save(scope); apply(); return; }
      setUrl(scope, blob);
      apply();
      refresh(scope);
    } catch (e) { }
  }

  /* ---------- follow / detach ---------- */
  let chatSeq = 0;

  function detach(scope, keepImage = true) {
    if (scope !== 'chat' || !state.chat.follow) return;
    const seq = ++chatSeq;
    const app = Object.assign({}, state.app);
    state.chat = Object.assign({}, app, { follow: false });
    save('chat');
    if (app.image && keepImage) {
      (async () => {
        try {
          const blob = await idbGet('wall:app');
          if (seq !== chatSeq) return;
          if (!blob) throw new Error('missing');
          await idbPut('wall:chat', blob);
          if (seq !== chatSeq) return;
          setUrl('chat', blob);
        } catch (e) {
          if (seq !== chatSeq) return;
          state.chat.image = false;
          if (state.chat.bg === 'custom') state.chat.bg = 'none';
        }
        save('chat'); apply(); refresh('chat');
      })();
    } else if (!keepImage) {
      state.chat.image = false;
      if (state.chat.bg === 'custom') state.chat.bg = 'none';
      save('chat');
    }
  }

  function follow(scope) {
    if (scope !== 'chat') return;
    chatSeq++;
    idbDel('wall:chat').catch(() => { });
    setUrl('chat', null);
    state.chat = Object.assign({}, CHAT_DEFAULT, { follow: true });
    save('chat'); apply(); refresh('chat');
  }

  /* ---------- apply ---------- */
  function apply() {
    const root = document.documentElement;
    const app = palette('app'), chat = palette('chat');
    const appS = state.app, chatS = effective('chat');

    Object.keys(app.pal).forEach(k => root.style.setProperty('--' + k, app.pal[k]));
    root.style.setProperty('--acc', app.accent);
    root.style.setProperty('--acc2', app.accent2);
    root.style.setProperty('--acc3', app.accent3);
    root.style.setProperty('--acc4', app.accent4);
    root.style.setProperty('--acc5', app.accent5);
    root.style.setProperty('--accbg', rgba(app.accent, appS.mode === 'dark' ? .16 : .12));
    root.style.setProperty('--acc2bg', rgba(app.accent2, appS.mode === 'dark' ? .16 : .12));
    root.style.setProperty('--acc3bg', rgba(app.accent3, appS.mode === 'dark' ? .16 : .12));
    root.style.setProperty('--acc4bg', rgba(app.accent4, appS.mode === 'dark' ? .16 : .12));
    root.style.setProperty('--acc5bg', rgba(app.accent5, appS.mode === 'dark' ? .16 : .12));
    root.style.setProperty('--acc-soft', rgba(app.accent, appS.mode === 'dark' ? .28 : .2));
    root.style.setProperty('--onacc', lum(app.accent) > .30 ? '#141018' : '#ffffff');
    root.style.setProperty('--overlay', appS.mode === 'dark' ? 'rgba(0,0,0,.72)' : 'rgba(24,24,35,.38)');
    root.style.setProperty('--shadow', appS.mode === 'dark' ? 'rgba(0,0,0,.78)' : 'rgba(24,24,40,.14)');

    Object.keys(chat.pal).forEach(k => root.style.setProperty('--c-' + k, chat.pal[k]));
    root.style.setProperty('--c-acc', chat.accent);
    root.style.setProperty('--c-acc2', chat.accent2);
    root.style.setProperty('--c-acc3', chat.accent3);
    root.style.setProperty('--c-acc4', chat.accent4);
    root.style.setProperty('--c-acc5', chat.accent5);
    root.style.setProperty('--c-accbg', rgba(chat.accent, chatS.mode === 'dark' ? .16 : .12));
    root.style.setProperty('--c-acc2bg', rgba(chat.accent2, chatS.mode === 'dark' ? .16 : .12));
    root.style.setProperty('--c-acc3bg', rgba(chat.accent3, chatS.mode === 'dark' ? .16 : .12));
    root.style.setProperty('--c-acc4bg', rgba(chat.accent4, chatS.mode === 'dark' ? .16 : .12));
    root.style.setProperty('--c-acc5bg', rgba(chat.accent5, chatS.mode === 'dark' ? .16 : .12));
    root.style.setProperty('--c-onacc', lum(chat.accent) > .30 ? '#141018' : '#ffffff');

    root.dataset.theme = appS.mode;
    root.dataset.chatTheme = chatS.mode;
    root.dataset.ui = state.ui;
    root.style.setProperty('--ui-glass-blur', state.fx.blur + 'px');
    root.style.setProperty('--ui-depth', (state.fx.depth / 100).toFixed(2));
    root.style.setProperty('--ui-a1', state.fx.opacity + '%');
    root.style.setProperty('--ui-a2', Math.max(20, state.fx.opacity - 18) + '%');
    root.style.setProperty('--ui-a3', Math.max(30, state.fx.opacity - 10) + '%');
    root.style.setProperty('--ui-a4', Math.max(20, state.fx.opacity - 34) + '%');
    root.style.colorScheme = appS.mode;
    document.body && document.body.classList.toggle('th-wall', appS.bg !== 'none');

    applyWall('app', appS, app.pal, urls.app);
    applyWall('chat', chatS, chat.pal, chatS.follow ? urls.app : urls.chat);

    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.content = app.pal.bg;
  }

  function applyWall(scope, s, pal, url) {
    const root = document.documentElement;
    let wall = 'none';
    if (s.bg === 'custom' && url) wall = `url("${url}")`;
    else if (BGS[s.bg]) wall = BGS[s.bg](s.mode);
    const dim = s.bg === 'none' ? 0 : s.dim / 100;
    const shade = s.mode === 'dark' ? `rgba(6,6,10,${dim})` : `rgba(250,250,255,${Math.min(.92, dim + .14)})`;
    const pre = scope === 'chat' ? '--c-' : '--';
    root.style.setProperty(pre + 'wall', wall);
    root.style.setProperty(pre + 'wall-dim', shade);
    root.style.setProperty(pre + 'wall-blur', s.blur + 'px');
    root.style.setProperty(pre + 'wall-on', wall === 'none' ? '0' : '1');
  }

  /* ---------- upload ---------- */
  const RASTER = ['image/png', 'image/jpeg', 'image/gif', 'image/webp'];
  async function upload(scope, file) {
    if (!file) return { ok: false };
    if (!RASTER.includes(file.type)) return { ok: false, msg: 'Pick a PNG, JPG, WebP or GIF' };
    if (file.size > 10 * 1024 * 1024) return { ok: false, msg: 'Keep wallpapers under 10 MB' };
    detach(scope, false);
    if (scope === 'chat') chatSeq++;
    try {
      await idbPut('wall:' + scope, file);
      setUrl(scope, file);
      state[scope].image = true;
      state[scope].bg = 'custom';
      save(scope); apply(); refresh(scope);
      return { ok: true };
    } catch (e) {
      return { ok: false, msg: 'Could not save that image here' };
    }
  }

  function clearImage(scope) {
    detach(scope, false);
    if (scope === 'chat') chatSeq++;
    idbDel('wall:' + scope).catch(() => { });
    setUrl(scope, null);
    state[scope].image = false;
    if (state[scope].bg === 'custom') state[scope].bg = 'none';
    save(scope); apply(); refresh(scope);
  }

  /* ---------- panel ---------- */
  function presetCard(scope, key, s) {
    const p = PRESETS[key];
    const pal = Object.assign({}, BASE[s.mode], (p.pal && p.pal[s.mode]) || {});
    const set = presetSet(key, s.mode);
    const on = s.preset === key;
    return `<button type="button" class="thp-preset ${on ? 'on' : ''}" data-th="preset" data-v="${key}" aria-pressed="${on}">
      <span class="thp-swatch" style="--a:${set.primary};--b:${pal.bg};--c:${pal.s2}">
        <i class="thp-dot1" style="background:${set.primary}"></i><i class="thp-dot2" style="background:${set.secondary}"></i><i class="thp-dot3" style="background:${set.data}"></i><i class="thp-dot4" style="background:${set.ambient}"></i><i class="thp-dot5" style="background:${set.gold}"></i>
        <span class="thp-check">${ICON.check}</span>
      </span>
      <span class="thp-pname">${p.name}</span>
    </button>`;
  }

  function fxRow(label, key, unit) {
    return `<label><span>${label} <b>${state.fx[key]}${unit}</b></span><input type="range" min="${FX_RANGE[key][0]}" max="${FX_RANGE[key][1]}" step="1" value="${state.fx[key]}" data-th="fx" data-key="${key}" aria-label="${label}"></label>`;
  }

  function roleRow(n, label, desc, color, custom) {
    return `<div class="thp-role">
      <span class="thp-role-chip" style="--c:${color}"><input type="color" data-th="rolePick" data-role="${n}" value="${color}" aria-label="${label} colour"></span>
      <span class="thp-role-tx"><b>${label}</b><small>${desc}</small></span>
      ${custom ? `<button type="button" class="thp-auto" data-th="roleAuto" data-role="${n}" title="Use the palette colour">Auto</button>` : '<span class="thp-auto">Auto</span>'}
    </div>`;
  }

  function bgTile(scope, key, s) {
    const on = s.bg === key;
    const style = key === 'none' ? '' : `style="background-image:${BGS[key](s.mode)}"`;
    return `<button type="button" class="thp-bg ${key === 'none' ? 'none' : ''} ${on ? 'on' : ''}" ${style} data-th="bg" data-v="${key}" aria-pressed="${on}" title="${key === 'none' ? 'No wallpaper' : key}">
      ${key === 'none' ? `<span class="thp-bgnone">${ICON.x}</span>` : ''}
      <span class="thp-bgtag">${key === 'none' ? 'None' : key[0].toUpperCase() + key.slice(1)}</span>
      ${on ? `<span class="thp-check">${ICON.check}</span>` : ''}
    </button>`;
  }

  function panel(scope) {
    const s = effective(scope), p = palette(scope), preset = PRESETS[s.preset] || PRESETS.default;
    const isChat = scope === 'chat';
    const following = isChat && s.follow;
    const imgSrc = following ? (urls.app || '') : (urls[scope] || '');
    const custom = s.image ? `<button type="button" class="thp-bg custom ${s.bg === 'custom' ? 'on' : ''}" data-th="bg" data-v="custom" aria-pressed="${s.bg === 'custom'}" title="Your image" ${imgSrc ? `style="background-image:url(${imgSrc})"` : ''}>
      <span class="thp-bgtag">Yours</span>${s.bg === 'custom' ? `<span class="thp-check">${ICON.check}</span>` : ''}</button>` : '';
    return `<div class="thp" data-theme-panel="${scope}">
      <div class="thp-modes" role="group" aria-label="Colour mode">
        <button type="button" class="thp-mode ${s.mode === 'dark' ? 'on' : ''}" data-th="mode" data-v="dark" aria-pressed="${s.mode === 'dark'}">${ICON.moon}<span>Dark</span></button>
        <button type="button" class="thp-mode ${s.mode === 'light' ? 'on' : ''}" data-th="mode" data-v="light" aria-pressed="${s.mode === 'light'}">${ICON.sun}<span>Light</span></button>
      </div>
      ${isChat ? '' : `<div class="thp-lab"><span>Surface style</span><small>Glass · 3D · Flat · whole app</small></div>
      <div class="thp-ui" role="group" aria-label="Surface style">${UI_STYLES.map(([v, name, desc]) => `<button type="button" class="thp-ui-btn ${state.ui === v ? 'on' : ''}" data-th="ui" data-v="${v}" aria-pressed="${state.ui === v}"><b>${name}</b><small>${desc}</small></button>`).join('')}</div>
      <div class="thp-lab"><span>Effect strength</span><small>Tune the finish</small></div>
      <div class="thp-fx">${fxRow('Glass opacity', 'opacity', '%')}${fxRow('Glass blur', 'blur', 'px')}${fxRow('3D depth', 'depth', '%')}</div>
      <button type="button" class="thp-fx-reset" data-th="fxReset">Reset effect strengths</button>`}
      ${isChat ? `<div class="thp-scope ${following ? 'on' : ''}"><span class="thp-scope-dot"></span><span class="grow"><b>${following ? 'Following app theme' : 'Chat has its own theme'}</b><small>${following ? 'Change anything below to make it independent.' : 'Your app theme stays exactly as it is.'}</small></span>${following ? '' : '<button type="button" class="btn-s thp-follow-btn" data-th="follow">Match app</button>'}</div>` : ''}

      <div class="thp-lab"><span>Palette</span><small>${isChat ? 'Chat only' : 'Whole app'} · 6 palettes · dark + light</small></div>
      <div class="thp-presets">${Object.keys(PRESETS).map(k => presetCard(scope, k, s)).join('')}</div>

      <div class="thp-lab"><span>Accent</span><small>${preset.name}${s.accent ? ' · custom' : ''}</small></div>
      <div class="thp-acc">
        ${ACCENTS.map(c => `<button type="button" class="thp-dot ${p.accent.toLowerCase() === c.toLowerCase() ? 'on' : ''}" style="--c:${c}" data-th="accent" data-v="${c}" aria-label="Accent ${c}" aria-pressed="${p.accent.toLowerCase() === c.toLowerCase()}"></button>`).join('')}
        <label class="thp-dot thp-pick" style="--c:${p.accent}" title="Custom accent">
          <input type="color" data-th="accentPick" value="${p.accent}" aria-label="Custom accent colour">
          <span>+</span>
        </label>
        ${s.accent ? '<button type="button" class="thp-resetacc" data-th="accentReset">Use palette</button>' : ''}
      </div>

      <div class="thp-lab"><span>Role accents</span><small>${isChat ? 'Chat only' : 'Whole app'} · 4 roles</small></div>
      <div class="thp-roles">
        ${roleRow(2, 'Secondary', 'Pills, links, mentions', p.accent2, s.accent2)}
        ${roleRow(3, 'Data', 'Charts, heatmaps, progress', p.accent3, s.accent3)}
        ${roleRow(4, 'Ambient', 'Hero gradients, glows', p.accent4, s.accent4)}
        ${roleRow(5, 'Achievement', 'Streaks, crowns, podium', p.accent5, s.accent5)}
      </div>
      <button type="button" class="thp-harmonise" data-th="harmonise">Reset roles to palette</button>

      <div class="thp-lab"><span>Background</span><small>${following ? 'From your app theme' : 'Image, GIF or gradient'}</small></div>
      <div class="thp-bgs">${bgTile(scope, 'none', s)}${Object.keys(BGS).map(k => bgTile(scope, k, s)).join('')}${custom}</div>
      <label class="thp-drop" data-th="drop">
        <span class="thp-drop-ic">${ICON.up}</span>
        <span class="thp-drop-tx"><b>${s.image ? 'Replace wallpaper' : 'Upload a wallpaper'}</b><small>PNG, JPG, WebP or GIF · up to 10 MB · stored on this device</small></span>
        <input type="file" accept="image/png,image/jpeg,image/gif,image/webp" data-th="file">
      </label>
      ${s.image && !following ? '<button type="button" class="btn-s thp-clear" data-th="clearimg">Remove uploaded wallpaper</button>' : ''}

      <div class="thp-tune ${s.bg === 'none' ? 'off' : ''}">
        <label><span>Dim <b>${Math.round(s.dim)}%</b></span><input type="range" min="0" max="85" step="1" value="${Math.round(s.dim)}" data-th="dim" aria-label="Background dim"></label>
        <label><span>Blur <b>${Math.round(s.blur)}px</b></span><input type="range" min="0" max="24" step="1" value="${Math.round(s.blur)}" data-th="blur" aria-label="Background blur"></label>
      </div>

      <div class="thp-foot">
        ${isChat && following ? '<span class="thp-follow-note">Using the app theme</span>' : `<button type="button" class="btn-s" data-th="reset">Reset ${isChat ? 'chat' : 'app'} theme</button>`}
        <span class="thp-live"><i></i>Live preview</span>
      </div>
      <p class="thp-note">${isChat
        ? 'The chat starts on your app theme. Change anything here and it becomes independent; the app stays untouched.'
        : 'The app theme is the base for the crew chat. Open a channel and tap the palette only if you want the chat to diverge.'}</p>
    </div>`;
  }

  function refresh(scope) {
    document.querySelectorAll(`[data-theme-panel="${scope}"]`).forEach(el => {
      const tmp = document.createElement('div');
      tmp.innerHTML = panel(scope);
      const fresh = tmp.firstElementChild;
      if (fresh) el.replaceWith(fresh);
    });
  }

  function set(scope, patch, rerender) {
    detach(scope);
    Object.assign(state[scope], patch);
    save(scope); apply();
    if (rerender !== false) refresh(scope);
  }

  /* ---------- events (delegated once; both panels use them) ---------- */
  function scopeOf(el) {
    const p = el.closest('[data-theme-panel]');
    return p ? p.dataset.themePanel : 'app';
  }

  function onClick(e) {
    const el = e.target.closest('[data-th]');
    if (!el || el.tagName === 'INPUT') return;
    const th = el.dataset.th;
    if (!th) return;
    const scope = scopeOf(el);
    if (th === 'preset') { e.preventDefault(); set(scope, { preset: el.dataset.v, accent: '' }); }
    else if (th === 'mode') { e.preventDefault(); set(scope, { mode: el.dataset.v }); }
    else if (th === 'accent') { e.preventDefault(); set(scope, { accent: el.dataset.v }); }
    else if (th === 'accentReset') { e.preventDefault(); set(scope, { accent: '' }); }
    else if (th === 'follow') { e.preventDefault(); follow(scope); }
    else if (th === 'ui') { e.preventDefault(); state.ui = el.dataset.v; try { localStorage.setItem(UI_KEY, state.ui); } catch (x) { } apply(); refresh(scope); }
    else if (th === 'fxReset') { e.preventDefault(); state.fx = Object.assign({}, FX_DEFAULT); saveFX(); apply(); refresh(scope); }
    else if (th === 'roleAuto') {
      e.preventDefault(); detach(scope);
      state[scope]['accent' + el.dataset.role] = '';
      save(scope); apply(); refresh(scope);
    } else if (th === 'harmonise') {
      e.preventDefault();
      const keys = ['accent2', 'accent3', 'accent4', 'accent5'];
      if (!keys.some(k => state[scope][k])) return;
      detach(scope);
      keys.forEach(k => { state[scope][k] = ''; });
      save(scope); apply(); refresh(scope);
    }
    else if (th === 'bg') {
      e.preventDefault();
      const v = el.dataset.v;
      if (v === 'custom' && !urls[scope] && !(scope === 'chat' && state.chat.follow && urls.app)) return;
      set(scope, { bg: v });
    } else if (th === 'clearimg') { e.preventDefault(); clearImage(scope); }
    else if (th === 'reset') {
      e.preventDefault();
      if (scope === 'chat') { follow(scope); return; }
      idbDel('wall:app').catch(() => { }); setUrl('app', null);
      state.app = Object.assign({}, DEFAULT);
      save('app'); apply(); refresh('app');
    }
  }

  function onInput(e) {
    const el = e.target.closest('[data-th]');
    if (!el) return;
    const scope = scopeOf(el);
    if (el.dataset.th === 'dim') {
      detach(scope);
      state[scope].dim = +el.value;
      save(scope); apply();
      const b = el.closest('label') && el.closest('label').querySelector('b');
      if (b) b.textContent = Math.round(state[scope].dim) + '%';
    } else if (el.dataset.th === 'blur') {
      detach(scope);
      state[scope].blur = +el.value;
      save(scope); apply();
      const b = el.closest('label') && el.closest('label').querySelector('b');
      if (b) b.textContent = Math.round(state[scope].blur) + 'px';
    } else if (el.dataset.th === 'fx') {
      const key = el.dataset.key;
      if (!Object.prototype.hasOwnProperty.call(FX_DEFAULT, key)) return;
      state.fx[key] = +el.value;
      saveFX(); apply();
      const b = el.closest('label') && el.closest('label').querySelector('b');
      if (b) b.textContent = state.fx[key] + (key === 'blur' ? 'px' : '%');
    } else if (el.dataset.th === 'accentPick') {
      detach(scope);
      state[scope].accent = el.value;
      apply();
      const box = el.closest('.thp-acc');
      if (box) box.querySelectorAll('.thp-dot').forEach(d => d.classList.toggle('on', (d.dataset.v || '').toLowerCase() === el.value.toLowerCase()));
    } else if (el.dataset.th === 'rolePick') {
      detach(scope);
      const n = el.dataset.role || '2';
      state[scope]['accent' + n] = el.value;
      apply();
      const chip = el.closest('.thp-role-chip');
      if (chip) chip.style.setProperty('--c', el.value);
    }
  }

  async function onChange(e) {
    const el = e.target.closest('[data-th]');
    if (!el) return;
    const scope = scopeOf(el);
    if (el.dataset.th === 'file') {
      const f = el.files && el.files[0];
      if (!f) return;
      const r = await upload(scope, f);
      if (!r.ok) {
        if (window.toast) toast('Wallpaper', r.msg || 'Could not use that image', 'err');
        el.value = '';
      }
    } else if (el.dataset.th === 'accentPick' || el.dataset.th === 'rolePick' || el.dataset.th === 'dim' || el.dataset.th === 'blur') {
      save(scope); refresh(scope);
    }
  }

  function onDrop(e) {
    const zone = e.target.closest('[data-th="drop"]');
    if (!zone) return;
    e.preventDefault();
    zone.classList.remove('over');
    const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
    if (!f) return;
    const scope = scopeOf(zone);
    upload(scope, f).then(r => { if (!r.ok && window.toast) toast('Wallpaper', r.msg || 'Could not use that image', 'err'); });
  }

  function onDrag(e) {
    const zone = e.target.closest('[data-th="drop"]');
    if (!zone) return;
    if (e.type === 'dragover') { e.preventDefault(); zone.classList.add('over'); }
    else zone.classList.remove('over');
  }

  document.addEventListener('click', onClick);
  document.addEventListener('input', onInput);
  document.addEventListener('change', onChange);
  document.addEventListener('dragover', onDrag);
  document.addEventListener('dragleave', onDrag);
  document.addEventListener('drop', onDrop);

  /* boot: vars exist before first paint; wallpapers stream in from IndexedDB */
  apply();
  hydrate('app');
  hydrate('chat');
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', apply, { once: true });
  else apply();

  return {
    panelHTML: panel,
    refresh: refresh,
    apply: apply,
    state: state,
    presets: PRESETS,
    accents: ACCENTS,
    palette: palette,
  };
})();
