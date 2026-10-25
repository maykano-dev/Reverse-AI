"use strict";

/* ReverseAI frontend — vanilla ES2020, no build step.
   The UI reads like a person working: a plan, a short reasoning timeline, tool
   cards with real output, sources, evidence, then the delivered file. */

// ---------------------------------------------------------------------------
// tiny helpers
// ---------------------------------------------------------------------------
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
};
const esc = (s) => {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : s;
  return d.innerHTML;
};
const fmtSize = (n) => {
  if (n == null) return "";
  if (n < 1024) return n + " B";
  if (n < 1048576) return (n / 1024).toFixed(1) + " KB";
  if (n < 1073741824) return (n / 1048576).toFixed(1) + " MB";
  return (n / 1073741824).toFixed(2) + " GB";
};
const fmtCost = (v) => (v == null ? "" : "$" + Number(v).toFixed(4));
const fmtTok = (n) => {
  n = Number(n || 0);
  if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(1) + "k";
  return String(n);
};
const fmtElapsed = (ms) => {
  const s = Math.max(0, Math.round(ms / 1000));
  return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
};
const hostOf = (u) => {
  try { return new URL(u).hostname.replace(/^www\./, ""); } catch (_) { return u; }
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------------------------------------------------------------------------
// icons (lucide-style stroke)
// ---------------------------------------------------------------------------
const P = {
  logo: '<path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.3 7 12 12 20.7 7"/><line x1="12" y1="22" x2="12" y2="12"/>',
  plus: '<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>',
  search: '<circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>',
  message: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
  memory: '<path d="M12 3a4 4 0 0 0-4 4v1a4 4 0 0 0-1 7.8V17a4 4 0 0 0 8 0v-1.2A4 4 0 0 0 16 8V7a4 4 0 0 0-4-4z"/><path d="M9 9h6M9 13h6"/>',
  clock: '<circle cx="12" cy="12" r="9"/><polyline points="12 7 12 12 15 14"/>',
  chart: '<line x1="4" y1="20" x2="20" y2="20"/><rect x="6" y="11" width="3" height="6"/><rect x="11" y="6" width="3" height="11"/><rect x="16" y="14" width="3" height="3"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
  globe: '<circle cx="12" cy="12" r="9"/><line x1="3" y1="12" x2="21" y2="12"/><path d="M12 3a14 14 0 0 1 3.5 9A14 14 0 0 1 12 21a14 14 0 0 1-3.5-9A14 14 0 0 1 12 3z"/>',
  cpu: '<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M9 2v2M15 2v2M9 20v2M15 20v2M2 9h2M2 15h2M20 9h2M20 15h2"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1A1.7 1.7 0 0 0 4.6 9a1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
  moon: '<path d="M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8z"/>',
  menu: '<line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/>',
  chevronLeft: '<polyline points="15 18 9 12 15 6"/>',
  chevronDown: '<polyline points="6 9 12 15 18 9"/>',
  arrowUp: '<line x1="12" y1="19" x2="12" y2="5"/><polyline points="5 12 12 5 19 12"/>',
  arrowDown: '<line x1="12" y1="5" x2="12" y2="19"/><polyline points="19 12 12 19 5 12"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor" stroke="none"/>',
  paperclip: '<path d="M21.4 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/>',
  mic: '<rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10v1a7 7 0 0 0 14 0v-1"/><line x1="12" y1="19" x2="12" y2="22"/>',
  x: '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>',
  file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/>',
  archive: '<rect x="2" y="4" width="20" height="5" rx="1"/><path d="M4 9v9a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9"/><line x1="10" y1="13" x2="14" y2="13"/>',
  check: '<polyline points="20 6 9 17 4 12"/>',
  alert: '<circle cx="12" cy="12" r="9"/><line x1="12" y1="8" x2="12" y2="13"/><line x1="12" y1="16" x2="12" y2="16"/>',
  sparkle: '<path d="M12 4l1.6 4.4L18 10l-4.4 1.6L12 16l-1.6-4.4L6 10l4.4-1.6z"/>',
  code: '<polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>',
  dot: '<circle cx="12" cy="12" r="3" fill="currentColor" stroke="none"/>',
  box: '<path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/>',
  copy: '<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
  terminal: '<polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/>',
  bars: '<line x1="6" y1="20" x2="6" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="18" y1="20" x2="18" y2="14"/>',
  thumbsUp: '<path d="M7 10v12"/><path d="M15 5.9L14 10h5.8a2 2 0 0 1 2 2.4l-1.4 6A2 2 0 0 1 18.4 20H7V10l4-7a2 2 0 0 1 4 0z"/>',
  thumbsDown: '<path d="M17 14V2"/><path d="M9 18.1L10 14H4.2a2 2 0 0 1-2-2.4l1.4-6A2 2 0 0 1 5.6 4H17v10l-4 7a2 2 0 0 1-4 0z"/>',
  trash: '<polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/>',
  external: '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/>',
  lock: '<rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>',
  book: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>',
  play: '<polygon points="6 3 20 12 6 21 6 3"/>',
  refresh: '<path d="M21 12a9 9 0 1 1-2.6-6.4"/><polyline points="21 3 21 9 15 9"/>',
  bookmark: '<path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>',
  undo: '<path d="M3 7v6h6"/><path d="M21 17a9 9 0 0 0-9-9 9 9 0 0 0-6 2.3L3 13"/>',
};
function ic(name, size) {
  const s = size || 18;
  return `<svg class="icon" width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${P[name] || P.sparkle}</svg>`;
}
function renderIcons(root) {
  $$("[data-icon]", root || document).forEach((n) => {
    if (n.dataset.done) return;
    n.innerHTML = ic(n.dataset.icon, n.dataset.size ? +n.dataset.size : 18);
    n.dataset.done = "1";
  });
}

// ---------------------------------------------------------------------------
// markdown (local, sanitized)
// ---------------------------------------------------------------------------
const _LONGDASH = /\s*[—–‒―−]\s*/g;
function dedashLine(line) {
  const m = line.match(/^(\s*(?:[-*+]\s+|\d+[.)]\s+))?([\s\S]*)$/);
  const marker = m[1] || "";
  let body = m[2]
    .replace(_LONGDASH, ", ")
    .replace(/\s+-\s+/g, ", ")
    .replace(/(\w)-(\w)/g, "$1 $2")
    .replace(/\s*,\s*,/g, ",")
    .replace(/[ \t]{2,}/g, " ")
    .replace(/\s+([,.;:!?])/g, "$1");
  return marker + body;
}
function deDash(text) {
  if (!text) return "";
  const parts = String(text).split(/(```[\s\S]*?```|`[^`]*`)/);
  return parts.map((p, i) => (i % 2 ? p : p.split("\n").map(dedashLine).join("\n"))).join("");
}
if (window.marked && window.marked.setOptions) {
  window.marked.setOptions({ gfm: true, breaks: true });
}
function md(text) {
  const clean = deDash(text || "");
  let html;
  try {
    if (window.marked) {
      const parse = window.marked.parse || window.marked;
      html = parse(clean, { gfm: true, breaks: true });
    } else {
      html = esc(clean).replace(/\n/g, "<br>");
    }
  } catch (_) {
    html = esc(clean).replace(/\n/g, "<br>");
  }
  if (window.DOMPurify) {
    try { html = window.DOMPurify.sanitize(html, { USE_PROFILES: { html: true } }); } catch (_) {}
  }
  return html;
}
function renderMd(node, text) {
  node.innerHTML = md(text);
  enhanceCodeBlocks(node);
}
function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) {
    return navigator.clipboard.writeText(text);
  }
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.style.position = "fixed";
  ta.style.opacity = "0";
  document.body.appendChild(ta);
  ta.select();
  try { document.execCommand("copy"); } catch (_) {}
  ta.remove();
  return Promise.resolve();
}
function enhanceCodeBlocks(root) {
  $$("pre", root).forEach((pre) => {
    if (pre.dataset.enh || pre.closest(".codeblock")) return;
    pre.dataset.enh = "1";
    const code = pre.querySelector("code");
    let lang = "code";
    if (code) {
      const m = (code.className || "").match(/language-([\w+-]+)/);
      if (m) lang = m[1];
    }
    const wrap = el("div", "codeblock");
    const bar = el("div", "cb-bar");
    bar.appendChild(el("span", "cb-lang", lang));
    const btn = el("button", "cb-copy");
    btn.title = "Copy code";
    btn.setAttribute("aria-label", "Copy code");
    btn.innerHTML = ic("copy", 14);
    btn.addEventListener("click", () => {
      const txt = code ? code.innerText : pre.innerText;
      copyText(txt);
      btn.innerHTML = ic("check", 14);
      setTimeout(() => { btn.innerHTML = ic("copy", 14); }, 1400);
    });
    bar.appendChild(btn);
    pre.parentNode.insertBefore(wrap, pre);
    wrap.appendChild(bar);
    wrap.appendChild(pre);
  });
}

// ---------------------------------------------------------------------------
// auth + api
// ---------------------------------------------------------------------------
const TOKEN_KEY = "rvai-token";
let authToken = (() => { try { return localStorage.getItem(TOKEN_KEY) || ""; } catch (_) { return ""; } })();
let authRequired = false;
let config = {};

function authHeaders(extra) {
  const h = Object.assign({}, extra || {});
  if (authToken) h.Authorization = "Bearer " + authToken;
  return h;
}
function withToken(url) {
  if (!authToken) return url;
  return url + (url.includes("?") ? "&" : "?") + "token=" + encodeURIComponent(authToken);
}
async function api(url, opts) {
  const o = Object.assign({}, opts || {});
  o.headers = authHeaders(o.headers);
  o.credentials = "same-origin";
  const r = await fetch(url, o);
  if (r.status === 401) {
    showAuth();
    throw new Error("unauthorized");
  }
  return r;
}
async function getJSON(url) {
  const r = await api(url);
  const b = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(b.error || ("HTTP " + r.status));
  return b;
}
async function postJSON(url, body) {
  const r = await api(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  return { status: r.status, body: await r.json().catch(() => ({})) };
}
function showAuth() {
  if (!authRequired) return;
  $("#authModal").classList.add("show");
  setTimeout(() => $("#authToken").focus(), 60);
}
function hideAuth() { $("#authModal").classList.remove("show"); }
async function submitAuth() {
  const val = $("#authToken").value.trim();
  const err = $("#authErr");
  err.textContent = "";
  if (!val) { err.textContent = "Enter the token."; return; }
  authToken = val;
  try {
    const r = await fetch("/jobs", { headers: authHeaders(), credentials: "same-origin" });
    if (r.status === 401) throw new Error("That token was not accepted.");
    try { localStorage.setItem(TOKEN_KEY, val); } catch (_) {}
    hideAuth();
    await bootData();
  } catch (e) {
    err.textContent = e.message || "Could not unlock.";
    authToken = "";
    try { localStorage.removeItem(TOKEN_KEY); } catch (_) {}
  }
}

// ---------------------------------------------------------------------------
// theme + state
// ---------------------------------------------------------------------------
function applyTheme(t) {
  document.documentElement.setAttribute("data-theme", t || "auto");
  try { localStorage.setItem("rvai-theme", t || "auto"); } catch (_) {}
  const sel = $("#themeSelect");
  if (sel) sel.value = t || "auto";
}
function cycleTheme() {
  const cur = document.documentElement.getAttribute("data-theme") || "auto";
  applyTheme(cur === "auto" ? "light" : cur === "light" ? "dark" : "auto");
}

let busy = false;
let conversationId = null;
let pendingTarget = null;
// Role is auto-delegated in the background from the request; no manual picker.
let template = "auto";
let permission = (() => { try { return localStorage.getItem("rvai-permission") || "write"; } catch (_) { return "write"; } })();
let attached = null;
let attachedPreview = null;  // object URL for an image thumbnail, when applicable
let currentUI = null;
let currentSrc = null;
let currentJobId = null;
let queue = [];
let templates = [];
let sessionArtifacts = [];
let views = {};
let viewOrder = [];

// ---------------------------------------------------------------------------
// boot
// ---------------------------------------------------------------------------
async function boot() {
  renderIcons();
  try { applyTheme(localStorage.getItem("rvai-theme") || "auto"); } catch (_) {}
  try { $("#notifyToggle").checked = localStorage.getItem("rvai-notify") === "1"; } catch (_) {}
  try { $("#speakToggle").checked = localStorage.getItem("rvai-speak") === "1"; } catch (_) {}
  $("#templateSelect").value = template;
  $("#permissionSelect").value = permission;
  try {
    config = await getJSON("/config");
    authRequired = !!config.auth_required;
    renderConfigInfo();
    if (authRequired && !authToken) showAuth();
  } catch (_) {}
  await bootData();
  registerSW();
  if (location.protocol === "file:") $("#fileBlock").classList.add("show");
}
async function bootData() {
  try { await loadTemplates(); } catch (e) { if (!/unauthorized/.test(e.message)) console.warn(e); }
  try { await loadHistory(); } catch (_) {}
  try { await loadCaps(); } catch (_) {}
  resumeActive();
}
function renderConfigInfo() {
  const s = $("#serverInfo");
  if (s) {
    s.textContent = config.ready
      ? `Ready · v${config.version} · memory, research, routines, durable runs`
      : "The server has no model key yet. Set one, then reload.";
  }
  const o = $("#ocrInfo");
  if (o) {
    const parts = [];
    if (config.ocr && config.ocr.unlimited) parts.push("Unlimited-OCR");
    if (config.ocr && config.ocr.tesseract) parts.push("Tesseract");
    o.textContent = parts.length ? parts.join(" + ") + " available" : "No OCR engine configured (optional)";
  }
  const t = $("#tokenState");
  if (t) t.textContent = authToken ? "A token is saved in this browser" : "No token needed on this device";
  if (config.ready === false) {
    const w = $("#welcome");
    if (w && !$("#readyNote")) {
      const n = el("div", "ready-note");
      n.id = "readyNote";
      n.textContent = "Almost ready. The server needs a model key (DEEPSEEK_API_KEY or another provider).";
      w.appendChild(n);
    }
  }
}

// ---------------------------------------------------------------------------
// templates
// ---------------------------------------------------------------------------
async function loadTemplates() {
  const data = await getJSON("/templates");
  templates = data.templates || [];
  const grid = $("#templateGrid");
  grid.innerHTML = "";
  templates.forEach((t) => {
    const card = el("button", "template-card");
    card.type = "button";
    card.dataset.id = t.id;
    card.innerHTML = `<span class="tc-ic">${ic(t.icon || "sparkle", 16)}</span>
      <span><span class="tc-name">${esc(t.name)}</span><span class="tc-desc">${esc(t.description)}</span></span>`;
    card.addEventListener("click", () => selectTemplate(t.id));
    grid.appendChild(card);
  });
  const sel = $("#templateSelect");
  sel.innerHTML = "";
  templates.forEach((t) => {
    const o = el("option", null, t.name);
    o.value = t.id;
    sel.appendChild(o);
  });
  const rsel = $("#routineTemplate");
  rsel.innerHTML = "";
  templates.forEach((t) => {
    const o = el("option", null, t.name);
    o.value = t.id;
    rsel.appendChild(o);
  });
  selectTemplate(template, false);
}
function selectTemplate(id, persist) {
  template = id || "general";
  if (persist !== false) {
    try { localStorage.setItem("rvai-template", template); } catch (_) {}
  }
  $$(".template-card").forEach((c) => c.classList.toggle("active", c.dataset.id === template));
  const sel = $("#templateSelect");
  if (sel) sel.value = template;
  renderSuggestions();
}
function renderSuggestions() {
  const t = templates.find((x) => x.id === template) || templates[0];
  const box = $("#suggest");
  if (!box) return;
  box.innerHTML = "";
  const items = (t && t.suggestions) || [
    "Explain what this file does in plain language.",
    "Look into this app and tell me what stands out.",
    "Build me something useful.",
  ];
  items.forEach((s) => {
    const c = el("button", "chip", s);
    c.type = "button";
    c.addEventListener("click", () => {
      $("#input").value = s;
      $("#input").focus();
      autosize();
    });
    box.appendChild(c);
  });
}

// ---------------------------------------------------------------------------
// sidebar / panels
// ---------------------------------------------------------------------------
function setSidebar(open) {
  $("#app").classList.toggle("side-open", !!open);
}
function newChat() {
  if (busy) stopRun();
  conversationId = null;
  pendingTarget = null;
  currentJobId = null;
  clearAttachment();
  queue = [];
  renderQueue();
  resetCanvas();
  const inner = $("#threadInner");
  inner.innerHTML = "";
  inner.appendChild(welcomeNode());
  renderSuggestions();
  setSidebar(false);
  $("#input").value = "";
  autosize();
  loadHistory();
}
function welcomeNode() {
  const w = el("div", "welcome");
  w.id = "welcome";
  w.innerHTML = `<div class="big">${ic("logo", 34)}</div>
    <h1>What should we build or take apart?</h1>
    <p>Drop in a binary, an app, an archive, or a website. I work in an isolated sandbox, show my reasoning as I go, and hand back a finished, verified result.</p>
    <div class="template-grid" id="templateGrid"></div>
    <div class="suggest" id="suggest"></div>`;
  setTimeout(() => {
    const grid = $("#templateGrid");
    templates.forEach((t) => {
      const card = el("button", "template-card");
      card.type = "button";
      card.dataset.id = t.id;
      card.innerHTML = `<span class="tc-ic">${ic(t.icon || "sparkle", 16)}</span>
        <span><span class="tc-name">${esc(t.name)}</span><span class="tc-desc">${esc(t.description)}</span></span>`;
      card.addEventListener("click", () => selectTemplate(t.id));
      grid.appendChild(card);
    });
    $$(".template-card").forEach((c) => c.classList.toggle("active", c.dataset.id === template));
    renderSuggestions();
  }, 0);
  return w;
}

// ---------------------------------------------------------------------------
// composer
// ---------------------------------------------------------------------------
const input = $("#input");
function autosize() {
  input.style.height = "auto";
  const max = Math.round(window.innerHeight * 0.42);
  const full = input.scrollHeight;
  input.style.height = Math.min(full, max) + "px";
  input.style.overflowY = full > max ? "auto" : "hidden";
}
input.addEventListener("input", autosize);
window.addEventListener("resize", autosize);
input.addEventListener("keydown", (e) => {
  if (e.key !== "Enter") return;
  if (e.ctrlKey || e.metaKey) {
    e.preventDefault();
    const s = input.selectionStart, en = input.selectionEnd;
    input.value = input.value.slice(0, s) + "\n" + input.value.slice(en);
    input.selectionStart = input.selectionEnd = s + 1;
    autosize();
  } else if (!e.shiftKey) {
    e.preventDefault();
    submit();
  }
});
$("#send").addEventListener("click", () => { if (busy) stopRun(); else submit(); });
$("#navNew").addEventListener("click", newChat);
$("#newMobile").addEventListener("click", newChat);
$("#menuBtn").addEventListener("click", () => {
  if (window.innerWidth >= 760) {
    $("#app").classList.toggle("collapsed");
  } else {
    setSidebar(!$("#app").classList.contains("side-open"));
  }
});
$("#scrim").addEventListener("click", () => setSidebar(false));
$("#collapseBtn").addEventListener("click", () => { $("#app").classList.add("collapsed"); setSidebar(false); });
$("#themeBtn").addEventListener("click", cycleTheme);
$("#settingsBtn").addEventListener("click", openSettings);
$("#templateSelect").addEventListener("change", (e) => selectTemplate(e.target.value));
$("#permissionSelect").addEventListener("change", (e) => {
  permission = e.target.value;
  try { localStorage.setItem("rvai-permission", permission); } catch (_) {}
});
$("#memoryQuick").addEventListener("click", openMemory);
$("#search").addEventListener("input", (e) => {
  const q = e.target.value.toLowerCase();
  $$("#convos .convo").forEach((c) => {
    c.style.display = (c.dataset.goal || "").includes(q) ? "" : "none";
  });
});
$("#navChats").addEventListener("click", () => { setSidebar(false); $("#thread").scrollTop = $("#thread").scrollHeight; });
$("#navMemory").addEventListener("click", () => { openMemory(); setSidebar(false); });
$("#navRoutines").addEventListener("click", () => { openRoutines(); setSidebar(false); });
$("#navUsage").addEventListener("click", () => { openUsage(); setSidebar(false); });
$("#navArtifacts").addEventListener("click", () => { showArtifacts(); setSidebar(false); });
$("#navBrowser").addEventListener("click", () => { openCanvas("preview"); setTimeout(() => $("#pvUrl").focus(), 200); setSidebar(false); });
$("#navHost").addEventListener("click", () => { openCanvas("caps"); setSidebar(false); });
$("#scrollBtn").addEventListener("click", () => { $("#thread").scrollTop = $("#thread").scrollHeight; });

function setBusy(on) {
  busy = on;
  const b = $("#send");
  b.classList.toggle("stop", on);
  b.innerHTML = on ? ic("stop", 18) : ic("arrowUp", 19);
  b.title = on ? "Stop" : "Send";
  b.setAttribute("aria-label", on ? "Stop" : "Send");
}
function submit() {
  const goal = input.value.trim();
  if (!goal) return;
  if (busy) {
    queue.push({ goal, attached });
    input.value = "";
    autosize();
    renderQueue();
    return;
  }
  send(goal);
}
function renderQueue() {
  const q = $("#queued");
  q.innerHTML = "";
  queue.forEach((m, i) => {
    const d = el("div", "qmsg");
    d.innerHTML = `<span class="qlabel">queued</span><span>${esc(m.goal.slice(0, 80))}</span><span class="qx">${ic("x", 13)}</span>`;
    d.querySelector(".qx").addEventListener("click", () => { queue.splice(i, 1); renderQueue(); });
    q.appendChild(d);
  });
}
function drainQueue() {
  if (queue.length && !busy) {
    const next = queue.shift();
    renderQueue();
    if (next.attached) { attached = next.attached; renderChip(); }
    input.value = next.goal;
    autosize();
    send(next.goal);
  }
}

// attachments
const ARCHIVE_KINDS = new Set(["zip", "gzip", "bzip2", "xz", "tar", "7z"]);
$("#attach").addEventListener("click", () => $("#fileInput").click());
$("#fileInput").addEventListener("change", (e) => {
  if (e.target.files[0]) uploadFile(e.target.files[0]);
  e.target.value = "";
});
async function uploadFile(file) {
  removeWelcome();
  const chip = $("#fileChip");
  attached = null;
  if (attachedPreview) { try { URL.revokeObjectURL(attachedPreview); } catch (_) {} attachedPreview = null; }
  if (file.type && file.type.startsWith("image/")) {
    try { attachedPreview = URL.createObjectURL(file); } catch (_) {}
  }
  const thumb = attachedPreview
    ? `<span class="fthumb"><img src="${attachedPreview}" alt=""></span>`
    : `<span class="fi">${ic("file", 16)}</span>`;
  chip.style.display = "flex";
  chip.classList.add("uploading");
  chip.innerHTML = `${thumb}<span><span class="fname">${esc(file.name)}</span> <span class="fmeta">${fmtSize(file.size)}</span></span>`;
  try {
    const r = await api("/upload", {
      method: "PUT",
      headers: { "X-Filename": file.name },
      body: file,
    });
    const b = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(b.error || "Upload failed");
    attached = b;
    renderChip();
  } catch (err) {
    chip.classList.remove("uploading");
    chip.innerHTML = `<span class="fi">${ic("alert", 16)}</span><span><span class="fname">${esc(file.name)}</span> <span class="fmeta" style="color:var(--danger)">${esc(err.message)}</span></span>`;
  }
}
function renderChip() {
  const chip = $("#fileChip");
  if (!attached) { chip.style.display = "none"; chip.innerHTML = ""; return; }
  chip.style.display = "flex";
  chip.classList.remove("uploading");
  const warn = ARCHIVE_KINDS.has(attached.kind);
  const kindLbl = attached.kind === "unknown" ? "file" : attached.kind;
  const archBit = (attached.arch && attached.arch !== "unknown")
    ? ` · ${attached.arch}${attached.bits ? " " + attached.bits + "-bit" : ""}` : "";
  const lead = attachedPreview
    ? `<span class="fthumb"><img src="${attachedPreview}" alt=""></span>`
    : `<span class="fi">${warn ? ic("archive", 16) : ic("file", 16)}</span>`;
  chip.innerHTML = `${lead}
    <span><span class="fname">${esc(attached.filename)}</span> <span class="fmeta">${fmtSize(attached.size)}${esc(archBit)}</span></span>
    <span class="kind ${warn ? "warn" : ""}">${esc(kindLbl)}</span>
    <span class="rm">${ic("x", 14)}</span>`;
  chip.querySelector(".rm").addEventListener("click", clearAttachment);
}
function clearAttachment() {
  attached = null;
  if (attachedPreview) { try { URL.revokeObjectURL(attachedPreview); } catch (_) {} attachedPreview = null; }
  const c = $("#fileChip");
  c.style.display = "none";
  c.innerHTML = "";
}

// drag & drop
let dragDepth = 0;
const overlay = $("#dropOverlay");
window.addEventListener("dragenter", (e) => {
  if (e.dataTransfer && Array.from(e.dataTransfer.types).includes("Files")) {
    dragDepth++;
    overlay.classList.add("show");
  }
});
window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("dragleave", () => {
  dragDepth = Math.max(0, dragDepth - 1);
  if (!dragDepth) overlay.classList.remove("show");
});
window.addEventListener("drop", (e) => {
  e.preventDefault();
  dragDepth = 0;
  overlay.classList.remove("show");
  const f = e.dataTransfer.files[0];
  if (f) uploadFile(f);
});

// speech input
let recognition = null;
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
if (!SR) $("#micBtn").style.display = "none";
else {
  $("#micBtn").addEventListener("click", () => {
    if (recognition) { try { recognition.stop(); } catch (_) {} return; }
    recognition = new SR();
    recognition.interimResults = true;
    recognition.lang = navigator.language || "en-US";
    $("#micBtn").classList.add("rec");
    let base = input.value;
    recognition.onresult = (ev) => {
      let text = "";
      for (let i = ev.resultIndex; i < ev.results.length; i++) text += ev.results[i][0].transcript;
      input.value = (base + " " + text).trim();
      autosize();
    };
    recognition.onend = () => {
      recognition = null;
      $("#micBtn").classList.remove("rec");
      input.focus();
    };
    recognition.onerror = () => { recognition = null; $("#micBtn").classList.remove("rec"); };
    try { recognition.start(); } catch (_) { recognition = null; $("#micBtn").classList.remove("rec"); }
  });
}
function speakIfEnabled(text) {
  if (localStorage.getItem("rvai-speak") !== "1") return;
  if (!("speechSynthesis" in window) || !text) return;
  try {
    const u = new SpeechSynthesisUtterance(text.slice(0, 1200));
    speechSynthesis.cancel();
    speechSynthesis.speak(u);
  } catch (_) {}
}

// ---------------------------------------------------------------------------
// turning: the reasoning timeline
// ---------------------------------------------------------------------------
function removeWelcome() { const w = $("#welcome"); if (w) w.remove(); }
function scrollDown() {
  const t = $("#thread");
  t.scrollTop = t.scrollHeight;
}
function userTurn(text) {
  removeWelcome();
  const t = el("div", "turn user");
  t.appendChild(el("div", "bubble", text));
  $("#threadInner").appendChild(t);
  scrollDown();
}
function aiTurn(jobId) {
  const t = el("div", "turn ai");
  const av = el("div", "avatar");
  av.innerHTML = ic("logo", 17);
  t.appendChild(av);
  const body = el("div", "ai-body");
  const think = el("div", "think");
  const bar = el("button", "thinking-bar");
  bar.type = "button";
  bar.innerHTML = `<span class="orbit"></span><span class="shimmer">Working through it</span>
    <span class="elapsed">0:00</span>
    <span class="stop-mini" role="button" aria-label="Stop">${ic("stop", 12)}</span>`;
  const label = bar.querySelector(".shimmer");
  const elapsed = bar.querySelector(".elapsed");
  const stopBtn = bar.querySelector(".stop-mini");
  stopBtn.addEventListener("click", (e) => { e.stopPropagation(); stopRun(); });
  bar.addEventListener("click", () => think.classList.toggle("closed"));
  const plan = el("div");
  const cot = el("div", "cot");
  think.appendChild(bar);
  think.appendChild(plan);
  think.appendChild(cot);
  body.appendChild(think);
  t.appendChild(body);
  $("#threadInner").appendChild(t);
  scrollDown();
  const ui = {
    turn: t, body, think, bar, label, elapsed, plan, cot,
    steps: 0, current: null, sources: [], seq: 0,
    start: Date.now(), timer: null, jobId: jobId || null, finished: false,
  };
  ui.timer = setInterval(() => {
    if (!ui.finished) ui.elapsed.textContent = fmtElapsed(Date.now() - ui.start);
  }, 1000);
  return ui;
}
function setThinking(ui, text) {
  if (!ui || ui.finished) return;
  ui.label.textContent = text;
}
function addPlan(ui, steps) {
  if (!ui || !steps || !steps.length) return;
  ui.plan.innerHTML = "";
  const box = el("div", "plan");
  const head = el("div", "plan-head");
  head.innerHTML = `<span>Plan</span><span class="chev">${ic("chevronDown", 14)}</span>`;
  head.addEventListener("click", () => box.classList.toggle("closed"));
  const body = el("div", "plan-body");
  steps.forEach((s, i) => {
    const row = el("div", "plan-step");
    row.dataset.step = s.id || ("step-" + i);
    if (s.status === "done") row.classList.add("done");
    if (s.status === "running") row.classList.add("active");
    row.innerHTML = `<span class="num">${i + 1}</span><span><b>${esc(s.title)}</b>${esc(s.detail || "")}</span>`;
    body.appendChild(row);
  });
  box.appendChild(head);
  box.appendChild(body);
  ui.plan.appendChild(box);
}
function addReason(ui, ev) {
  if (!ui) return;
  if (ui.current) ui.current.classList.remove("open");
  const step = el("div", "cot-step live");
  step.innerHTML = `<span class="dot">${ic("dot", 7)}</span>
    <button class="cot-trigger" type="button"><span class="ct-title">${esc(ev.title || "Working through it")}</span>
      <span class="ct-sub">${esc(ev.detail || "")}</span><span class="chev">${ic("chevronDown", 13)}</span></button>
    <div class="cot-content"></div>`;
  const trigger = step.querySelector(".cot-trigger");
  trigger.addEventListener("click", () => step.classList.toggle("open"));
  if (ev.detail) step.querySelector(".cot-content").appendChild(el("div", "cot-item", ev.detail));
  // Close previous live marker, open this one.
  $$(".cot-step.live", ui.cot).forEach((s) => s.classList.remove("live"));
  ui.cot.appendChild(step);
  ui.current = step;
  step.classList.add("open");
  ui.steps++;
  setThinking(ui, ev.title || "Working through it");
  scrollDown();
}
function addThought(ui, text) {
  if (!ui || !text) return;
  if (!ui.current) addReason(ui, { title: "Thinking it through", detail: "" });
  const node = el("div", "cot-item thought");
  node.innerHTML = md(text);
  enhanceCodeBlocks(node);
  ui.current.querySelector(".cot-content").appendChild(node);
  scrollDown();
}
function addToolResult(ui, ev) {
  if (!ui) return;
  if (!ui.current) addReason(ui, { title: ev.title || TOOL_LABELS[ev.name] || "Working", detail: "" });
  const card = el("div", "tool-card");
  const ok = !!ev.ok;
  const head = el("div", "tool-head " + (ok ? "ok" : "fail"));
  head.innerHTML = `<span class="ti">${ic(ok ? "check" : "alert", 14)}</span>
    <span class="tt">${esc(ev.title || TOOL_LABELS[ev.name] || "Tool result")}</span>
    <span class="state">${ok ? "done" : "failed"}</span>`;
  const body = el("div", "tool-body", (ev.content || "(no output)").slice(0, 12000));
  head.addEventListener("click", () => card.classList.toggle("open"));
  if (ev.content) {
    const view = el("span", "view", "details");
    view.addEventListener("click", (e) => {
      e.stopPropagation();
      const key = addView(ev.title || TOOL_LABELS[ev.name] || "Tool output", ev.content);
      showView(key);
    });
    head.appendChild(view);
  }
  card.appendChild(head);
  card.appendChild(body);
  ui.current.querySelector(".cot-content").appendChild(card);
  ui.current.classList.toggle("ok", ok);
  ui.current.classList.toggle("fail", !ok);
  ui.current.classList.remove("live");
  setThinking(ui, ok ? "Checking the next thing" : "Adjusting after a failed step");
  scrollDown();
}
function addFinding(ui, ev) {
  if (!ui) return;
  if (!ui.current) addReason(ui, { title: "Noting what I found", detail: "" });
  let row = ui.current.querySelector(".finding-row");
  if (!row) {
    row = el("div", "finding-row");
    ui.current.querySelector(".cot-content").appendChild(row);
  }
  const chip = el("span", "finding");
  chip.innerHTML = `<span class="tier ${esc(ev.tier || "observed")}">${esc(ev.tier || "observed")}</span><span>${esc(ev.claim || "")}</span>`;
  row.appendChild(chip);
}
function addSource(ui, ev) {
  if (!ui || !ev || !ev.url) return;
  if (ui.sources.some((s) => s.url === ev.url)) return;
  ui.sources.push(ev);
}
function addVerification(ui, ev) {
  if (!ui) return;
  if (!ui.current) addReason(ui, { title: "Proving the change", detail: "" });
  let card = ui.current.querySelector(".verify-card");
  if (!card) {
    card = el("div", "verify-card");
    card.innerHTML = `<div class="vh"><span>${ic("check", 13)}</span><span class="vt">Verification</span><span class="vbadge">running</span></div><div class="vbody"></div>`;
    ui.current.querySelector(".cot-content").appendChild(card);
  }
  const body = card.querySelector(".vbody");
  const badge = card.querySelector(".vbadge");
  if (ev.type === "verification_plan") {
    card.querySelector(".vt").textContent = ev.title || "Verification";
    const note = el("div", "verify-note", ev.detail || "");
    body.appendChild(note);
    return;
  }
  if (ev.type === "verification_attempt") {
    const row = el("div", "verify-attempt " + (ev.passed ? "pass" : "fail"));
    row.innerHTML = `<span class="vd"></span><span><b>Attempt ${ev.attempt || "?"} of ${ev.max_attempts || "?"}: ${ev.passed ? "passed" : "failed"}</b><br>${esc(ev.reason || ev.summary || "")}</span>`;
    body.appendChild(row);
    badge.textContent = ev.passed ? "passed" : "retrying";
    badge.className = "vbadge " + (ev.passed ? "pass" : "fail");
    return;
  }
  if (ev.type === "verification_repair") {
    body.appendChild(el("div", "verify-note", ev.detail || "Trying another candidate."));
    return;
  }
  if (ev.type === "verification" || ev.type === "delivery_blocked") {
    const ok = ev.type === "verification" && ev.verified;
    badge.textContent = ok ? "verified" : "not verified";
    badge.className = "vbadge " + (ok ? "pass" : "fail");
    const note = el("div", "verify-note", ev.reason || "");
    body.appendChild(note);
  }
}
function finishFinal(ui, ev, jobId) {
  if (!ui || ui.finished) return;
  ui.finished = true;
  clearInterval(ui.timer);
  if (ui.current) ui.current.classList.remove("live", "open");
  $$(".cot-step", ui.cot).forEach((s) => s.classList.remove("open"));
  ui.bar.classList.add("done");
  ui.bar.querySelector(".orbit").outerHTML = ic("check", 16);
  const n = ui.steps || ev.steps || 1;
  ui.label.textContent = ev.status === "cancelled"
    ? "Stopped"
    : (n <= 1 ? "Thought it through" : `Thought through ${n} steps`);
  ui.label.classList.remove("shimmer");
  ui.elapsed.textContent = fmtElapsed(Date.now() - ui.start);
  const stop = ui.bar.querySelector(".stop-mini");
  if (stop) stop.remove();
  $$(".plan-step", ui.plan).forEach((s) => s.classList.add("done"));
  ui.think.classList.add("closed");

  const ans = el("div", "answer");
  renderMd(ans, ev.answer || "_(no conclusion)_");
  ui.body.appendChild(ans);

  if (ev.status === "incomplete") {
    const note = el("div", "usage-line", "This turn reached its step limit. Ask me to continue and I'll pick up where I stopped.");
    ui.body.appendChild(note);
  }
  if (ev.status === "cancelled") {
    ui.body.appendChild(el("div", "usage-line", "Stopped. Nothing else was changed."));
  }

  const es = ev.evidence_summary || {};
  if (es.verified || es.observed || es.believed) {
    const row = el("div", "evi-row");
    ["verified", "observed", "believed"].forEach((tier) => {
      const b = el("button", "evi");
      b.type = "button";
      b.innerHTML = `<span class="tier ${tier}">${tier}</span> <b>${es[tier] || 0}</b>`;
      b.addEventListener("click", () => showReport(jobId));
      row.appendChild(b);
    });
    const rep = el("button", "evi");
    rep.type = "button";
    rep.innerHTML = `${ic("file", 13)} report`;
    rep.addEventListener("click", () => showReport(jobId));
    row.appendChild(rep);
    ui.body.appendChild(row);
  }

  renderSources(ui.body, ev.sources || ui.sources);
  const delivery = ev.delivery || {};
  if (delivery.allowed === false) {
    renderDeliveryBlocked(ui.body, delivery.reason, jobId);
  } else {
    renderArtifact(ui.body, ev.artifact_meta, ev.artifact, jobId);
  }
  renderFeedback(ui.body, jobId);

  const u = ev.usage || {};
  if (u.total_tokens) {
    const parts = [`${fmtTok(u.total_tokens)} tokens`];
    if (u.cost_usd != null) parts.push("~" + fmtCost(u.cost_usd));
    parts.push(`${ev.steps || ui.steps} steps`);
    ui.body.appendChild(el("div", "usage-line", parts.join(" · ")));
  }
  scrollDown();
  loadHistory();
  notifyDone(ev);
  speakIfEnabled(ev.answer || "");
  done();
}
function finishError(ui, msg) {
  if (!ui || ui.finished) return;
  ui.finished = true;
  clearInterval(ui.timer);
  ui.label.textContent = "Stopped";
  ui.label.classList.remove("shimmer");
  const stopBtn = ui.bar.querySelector(".stop-mini");
  if (stopBtn) stopBtn.remove();
  ui.bar.querySelector(".orbit").outerHTML = ic("alert", 16);
  ui.elapsed.textContent = fmtElapsed(Date.now() - ui.start);
  const stop = ui.bar.querySelector(".stop-mini");
  if (stop) stop.remove();
  const e = el("div", "answer");
  e.style.color = "var(--danger)";
  e.textContent = msg || "Something went wrong.";
  ui.body.appendChild(e);
  scrollDown();
  done();
}
function done() {
  setBusy(false);
  currentSrc = null;
  currentUI = null;
  currentJobId = null;
  try { localStorage.removeItem("rvai-active"); } catch (_) {}
  setTimeout(drainQueue, 180);
}
function notifyDone(ev) {
  if (localStorage.getItem("rvai-notify") !== "1") return;
  if (!("Notification" in window) || Notification.permission !== "granted") return;
  if (!document.hidden) return;
  try {
    new Notification("ReverseAI finished", {
      body: (ev.answer || "Your turn is ready.").slice(0, 140),
      tag: "reverseai-done",
    });
  } catch (_) {}
}

// ---------------------------------------------------------------------------
// send + stream
// ---------------------------------------------------------------------------
async function send(goal) {
  if (busy) return;
  setBusy(true);
  userTurn(goal);
  input.value = "";
  input.style.height = "auto";
  const payload = { goal, template, permission };
  if (attached) { payload.target = attached.path; clearAttachment(); }
  else if (pendingTarget) { payload.target = pendingTarget; pendingTarget = null; }
  if (conversationId) payload.conversation_id = conversationId;
  const ui = aiTurn();
  currentUI = ui;
  try {
    const { status, body } = await postJSON("/jobs/start", payload);
    if (status !== 200) {
      finishError(ui, body.error || "Could not start this turn.");
      return;
    }
    currentJobId = body.job_id;
    ui.jobId = body.job_id;
    if (body.conversation_id) conversationId = body.conversation_id;
    try {
      localStorage.setItem("rvai-active", JSON.stringify({
        jobId: body.job_id, cid: conversationId, goal, template, permission,
        startedAt: Date.now(),
      }));
    } catch (_) {}
    attachStream(body.job_id, ui, 0);
  } catch (err) {
    finishError(ui, err.message || "Connection failed.");
  }
}
function attachStream(jobId, ui, after) {
  if (currentSrc) currentSrc.close();
  const src = new EventSource(withToken(`/jobs/${jobId}/events?after=${after || 0}`));
  currentSrc = src;
  src.onmessage = (m) => {
    let ev;
    try { ev = JSON.parse(m.data); } catch (_) { return; }
    ui.seq++;
    handleEvent(ui, ev, jobId);
  };
  src.onerror = () => {
    src.close();
    if (currentSrc === src) currentSrc = null;
    if (!busy || !ui || ui.finished) return;
    // The event log is durable; reconnect from where we stopped.
    setTimeout(() => {
      if (!ui.finished && busy) attachStream(jobId, ui, ui.seq);
    }, 1200);
  };
}
function handleEvent(ui, ev, jobId) {
  switch (ev.type) {
    case "start":
      if (ev.plan) addPlan(ui, ev.plan);
      break;
    case "plan":
      addPlan(ui, ev.steps);
      break;
    case "step":
      if (ev.step) ui.modelStep = ev.step;
      break;
    case "reason":
      addReason(ui, ev);
      break;
    case "assistant":
      if (ev.content && ev.tool_calls && ev.tool_calls.length) addThought(ui, ev.content);
      break;
    case "tool_result":
      addToolResult(ui, ev);
      if (ev.name === "clone_website" && ev.ok && conversationId) {
        showPreview(`/preview/${conversationId}/index.html`, { local: true });
      }
      break;
    case "source":
      addSource(ui, ev);
      break;
    case "finding":
      addFinding(ui, ev);
      break;
    case "modification_plan":
      if (ev.plan && ev.plan.steps) addPlan(ui, ev.plan.steps);
      break;
    case "modification_step": {
      const row = ui.plan.querySelector(`.plan-step[data-step="${ev.step}"]`);
      if (row) {
        row.classList.toggle("done", ev.status === "done");
        row.classList.toggle("active", ev.status === "running");
      }
      break;
    }
    case "verification_plan":
    case "verification_attempt":
    case "verification_repair":
    case "verification":
    case "delivery_blocked":
      addVerification(ui, ev);
      break;
    case "final":
      srcClose();
      finishFinal(ui, ev, jobId);
      break;
    case "error":
      srcClose();
      finishError(ui, ev.error || "The turn failed.");
      break;
    default:
      break;
  }
}
function srcClose() {
  if (currentSrc) { currentSrc.close(); currentSrc = null; }
}
async function stopRun() {
  if (!busy) return;
  const jobId = (currentUI && currentUI.jobId) || currentJobId;
  if (jobId) {
    try { await postJSON(`/jobs/${jobId}/cancel`, {}); } catch (_) {}
  }
  srcClose();
  if (currentUI) finishError(currentUI, "Stopped. Nothing else will run.");
}

// ---------------------------------------------------------------------------
// sources, artifacts, feedback
// ---------------------------------------------------------------------------
function renderSources(container, sources) {
  if (!sources || !sources.length) return;
  const wrap = el("div", "sources");
  wrap.appendChild(el("div", "sources-title", "Sources"));
  const list = el("div", "source-list");
  sources.forEach((s) => {
    if (!/^https?:\/\//i.test(s.url || "")) return;
    const a = el("a", "source");
    a.href = s.url;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    const host = hostOf(s.url);
    const img = document.createElement("img");
    img.alt = "";
    img.src = `https://www.google.com/s2/favicons?domain=${encodeURIComponent(host)}&sz=64`;
    img.addEventListener("error", () => {
      const fb = el("span", "fav-fallback", (host[0] || "?").toUpperCase());
      img.replaceWith(fb);
    });
    const text = el("span");
    text.innerHTML = `<span class="src-t">${esc(s.title || host)}</span><span class="src-u">${esc(host)}</span>`;
    a.appendChild(img);
    a.appendChild(text);
    list.appendChild(a);
  });
  wrap.appendChild(list);
  container.appendChild(wrap);
}
function renderDeliveryBlocked(container, reason, jobId) {
  const card = el("div", "delivery-blocked");
  card.innerHTML = `<b>File withheld: not verified</b>${esc(reason || "No behavioral test passed in the sandbox.")}`;
  container.appendChild(card);
  addReportLink(container, jobId);
}
function addReportLink(container, jobId) {
  if (!jobId) return;
  const a = el("a", "report-link");
  a.href = withToken(`/jobs/${jobId}/report.html`);
  a.target = "_blank";
  a.rel = "noopener";
  a.innerHTML = `${ic("file", 13)} Verification report`;
  container.appendChild(a);
}
function renderArtifact(container, meta, name, jobId) {
  const m = meta || {};
  if (!m.name && !name) return;
  const fname = m.name || name || "artifact";
  const a = el("a", "artifact");
  a.href = withToken(`/jobs/${jobId}/artifact`);
  a.setAttribute("download", fname);
  const size = m.size ? fmtSize(m.size) : "";
  const sha = m.sha256 ? "sha256 " + m.sha256.slice(0, 10) : "";
  a.innerHTML = `<span class="ai">${ic("download", 18)}</span>
    <span class="at"><b>${esc(fname)}</b><span>${[size, sha].filter(Boolean).join(" · ") || "Delivered file"}</span></span>
    <span class="ad">${ic("download", 17)}</span>`;
  container.appendChild(a);
  addReportLink(container, jobId);
  if (!sessionArtifacts.some((x) => x.href === a.href)) {
    sessionArtifacts.unshift({ name: fname, href: a.href, goal: fname, size: m.size, sha: m.sha256 });
    updateArtCount();
  }
}
function renderFeedback(container, jobId) {
  const wrap = el("div", "feedback");
  wrap.innerHTML = `<span class="fb-q">Was this helpful?</span>
    <button class="fb-btn" data-r="up" aria-label="Helpful">${ic("thumbsUp", 15)}</button>
    <button class="fb-btn" data-r="down" aria-label="Not helpful">${ic("thumbsDown", 15)}</button>`;
  wrap.querySelectorAll(".fb-btn").forEach((b) => {
    b.addEventListener("click", async () => {
      wrap.querySelectorAll(".fb-btn").forEach((x) => x.disabled = true);
      try {
        await postJSON("/feedback", { job_id: jobId, rating: b.dataset.r });
        b.classList.add("on");
        const thanks = el("span", "fb-thanks", "Thanks, noted.");
        wrap.appendChild(thanks);
      } catch (_) {
        wrap.appendChild(el("span", "fb-thanks", "Could not save feedback."));
      }
    });
  });
  container.appendChild(wrap);
}

// ---------------------------------------------------------------------------
// history / reopen / resume
// ---------------------------------------------------------------------------
const TOOL_LABELS = {
  host_capabilities: "Checking the environment",
  analyze_binary: "Reading the file",
  read_bytes: "Looking at the bytes",
  list_strings: "Reading text in the file",
  disassemble: "Reading the machine code",
  list_functions: "Mapping functions",
  build_control_flow_graph: "Mapping control flow",
  analyze_apk: "Opening the app package",
  assess_heuristics: "Checking for risk signals",
  run_in_sandbox: "Running it in the sandbox",
  record_finding: "Writing down a finding",
  apply_byte_patch: "Changing a copy of the file",
  verify_against_original: "Comparing both versions",
  verify_modification: "Proving the change in the sandbox",
  differential_test: "Testing across a set of inputs",
  capture_behavior_corpus: "Recording the original behavior",
  choose_modification_strategy: "Choosing the safest way to change it",
  plan_and_modify: "Planning and making the change",
  check_execution_readiness: "Checking whether it can be run",
  build_world_model: "Building the system model",
  query_world_model: "Asking the system model",
  project_memory: "Consulting project memory",
  discover_opportunities: "Looking for opportunities",
  plan_discovery_mission: "Planning a discovery mission",
  form_hypotheses: "Forming hypotheses",
  simulate_change: "Simulating the change",
  search_architectures: "Comparing designs",
  plan_product: "Planning the product",
  select_model: "Choosing a model",
  build_proof_package: "Building the proof package",
  plan_mission: "Planning the mission",
  analyze_domain: "Analyzing the domain",
  forge_tool: "Forging a tool",
  export_tool_manifests: "Describing tools",
  capability_map: "Measuring capabilities",
  trust_check: "Checking the consequence",
  reality_check: "Separating prediction from observation",
  human_decision: "Naming the human decision",
  compression_plan: "Choosing the cheapest reliable path",
  reconstruction_plan: "Planning the reconstruction",
  create_workspace_checkpoint: "Taking a checkpoint",
  list_workspace_checkpoints: "Listing checkpoints",
  review_workspace_changes: "Reviewing the diff",
  restore_workspace_checkpoint: "Restoring a checkpoint",
  diff_modified: "Checking what changed",
  extract_archive: "Unpacking the archive safely",
  clone_website: "Rebuilding the site",
  add_imported_library: "Changing the file's structure",
  add_section: "Changing the file's structure",
  list_dir: "Looking through the project",
  read_file: "Reading a file",
  write_file: "Writing a file",
  edit_file: "Editing a file",
  run_command: "Running a step",
  decompile: "Decompiling the code",
  read_text_from_image: "Reading text from an image",
  web_search: "Searching the web",
  web_read: "Reading a page",
  remember: "Saving a note",
  recall: "Checking past notes",
  forget: "Removing a saved note",
  delegate: "Bringing in a specialist",
  list_skills: "Checking playbooks",
  read_skill: "Loading a playbook",
  schedule_routine: "Scheduling a routine",
};
function toolLabel(name) { return TOOL_LABELS[name] || "Working"; }

async function loadHistory() {
  let data;
  try { data = await getJSON("/jobs"); } catch (_) { return; }
  const jobs = data.jobs || [];
  const h = $("#convos");
  h.innerHTML = "";
  $("#recentCount").textContent = jobs.length ? String(jobs.length) : "";
  jobs.slice(0, 60).forEach((j) => {
    const it = el("button", "convo");
    it.type = "button";
    it.dataset.goal = (j.goal || "").toLowerCase();
    it.title = `${j.status || ""}${j.steps ? " · " + j.steps + " steps" : ""}`;
    const icon = el("span", "cv-ic");
    icon.innerHTML = ic(templateIcon(j.template), 9);
    it.appendChild(icon);
    it.appendChild(el("span", "cv-label", (j.goal || "(chat)").slice(0, 52)));
    const del = el("span", "cv-del");
    del.innerHTML = ic("x", 14);
    del.title = "Delete chat";
    del.addEventListener("click", (e) => {
      e.stopPropagation();
      deleteChat(j.id, it);
    });
    it.appendChild(del);
    it.addEventListener("click", () => {
      $$(".convo").forEach((c) => c.classList.remove("active"));
      it.classList.add("active");
      openConversation(j.id);
      setSidebar(false);
    });
    h.appendChild(it);
  });
}
function templateIcon(id) {
  const t = templates.find((x) => x.id === id);
  return t ? t.icon : "dot";
}
async function deleteChat(jobId, node) {
  try {
    await api(`/jobs/${jobId}`, { method: "DELETE" });
    node.remove();
  } catch (_) {}
}
async function openConversation(jobId) {
  if (busy) stopRun();
  let rec;
  try { rec = await getJSON(`/jobs/${jobId}`); } catch (_) { return; }
  if (!rec || rec.error) return;
  resetCanvas();
  queue = [];
  renderQueue();
  clearAttachment();
  conversationId = rec.conversation_id || null;
  pendingTarget = rec.target_path || null;
  currentJobId = jobId;
  const inner = $("#threadInner");
  inner.innerHTML = "";
  const msgs = rec.transcript || [];
  const toolResults = new Map();
  msgs.forEach((m) => { if (m.role === "tool") toolResults.set(m.tool_call_id, m.content || ""); });

  let hasUser = false;
  let finalAnswer = "";
  let archivedUI = null;
  msgs.forEach((m) => {
    if (m.role === "user") {
      if (m.tool_call_id || Array.isArray(m.content)) return;
      let text = String(m.content || "").split("\n\n[Attached target:")[0].replace(/^Goal:\s*/i, "").trim();
      if (text) { userTurn(text); hasUser = true; }
    } else if (m.role === "assistant") {
      const calls = m.tool_calls || [];
      if (calls.length) {
        if (!archivedUI) archivedUI = aiTurn(jobId);
        addPlan(archivedUI, (rec.plan || []));
        calls.forEach((call) => {
          const fn = call.function || call;
          const name = fn.name || "";
          const args = parseArgs(fn.arguments);
          addReason(archivedUI, { title: toolLabel(name), detail: "" });
          const out = toolResults.get(call.id) || "";
          addToolResult(archivedUI, { name, ok: true, title: toolLabel(name), content: out });
        });
        if (m.content) addThought(archivedUI, m.content);
      } else if (m.content) {
        finalAnswer = m.content;
      }
    }
  });
  if (!hasUser) userTurn(rec.goal || "(no goal recorded)");
  const answer = finalAnswer || rec.final_answer || "";
  if (archivedUI) {
    archivedUI.finished = true;
    clearInterval(archivedUI.timer);
    $$(".cot-step", archivedUI.cot).forEach((s) => s.classList.remove("open", "live"));
    archivedUI.think.classList.add("closed");
    archivedUI.label.classList.remove("shimmer");
    const n = archivedUI.steps || rec.steps || 1;
    archivedUI.label.textContent = n <= 1 ? "Thought it through" : `Thought through ${n} steps`;
    const ans = el("div", "answer");
    renderMd(ans, answer || "_(no conclusion)_");
    archivedUI.body.appendChild(ans);
    renderSources(archivedUI.body, rec.sources || []);
    if (rec.delivery && rec.delivery.allowed === false) {
      renderDeliveryBlocked(archivedUI.body, rec.delivery.reason, jobId);
    } else {
      renderArtifact(archivedUI.body, rec.artifact_meta, rec.artifact, jobId);
    }
    renderFeedback(archivedUI.body, jobId);
    if (rec.usage && rec.usage.total_tokens) {
      const parts = [`${fmtTok(rec.usage.total_tokens)} tokens`];
      if (rec.usage.cost_usd != null) parts.push("~" + fmtCost(rec.usage.cost_usd));
      archivedUI.body.appendChild(el("div", "usage-line", parts.join(" · ")));
    }
  } else {
    const t = el("div", "turn ai");
    const av = el("div", "avatar");
    av.innerHTML = ic("logo", 17);
    t.appendChild(av);
    const body = el("div", "ai-body");
    const ans = el("div", "answer");
    renderMd(ans, answer || "_(no conclusion)_");
    body.appendChild(ans);
    renderSources(body, rec.sources || []);
    if (rec.delivery && rec.delivery.allowed === false) {
      renderDeliveryBlocked(body, rec.delivery.reason, jobId);
    } else {
      renderArtifact(body, rec.artifact_meta, rec.artifact, jobId);
    }
    renderFeedback(body, jobId);
    t.appendChild(body);
    inner.appendChild(t);
  }
  buildReport($("#reportPane"), rec);
  scrollDown();
}
function parseArgs(raw) {
  if (!raw) return {};
  if (typeof raw === "object") return raw;
  try { return JSON.parse(raw); } catch (_) { return {}; }
}
function resumeActive() {
  let active;
  try { active = JSON.parse(localStorage.getItem("rvai-active") || "null"); } catch (_) { return; }
  if (!active || !active.jobId) return;
  if (Date.now() - (active.startedAt || 0) > 24 * 3600 * 1000) {
    try { localStorage.removeItem("rvai-active"); } catch (_) {}
    return;
  }
  if (authRequired && !authToken) return;
  resetCanvas();
  conversationId = active.cid || null;
  template = active.template || template;
  permission = active.permission || permission;
  $("#templateSelect").value = template;
  $("#permissionSelect").value = permission;
  removeWelcome();
  userTurn(active.goal || "Continue");
  const ui = aiTurn(active.jobId);
  currentUI = ui;
  currentJobId = active.jobId;
  setBusy(true);
  attachStream(active.jobId, ui, 0);
}

// ---------------------------------------------------------------------------
// report
// ---------------------------------------------------------------------------
function buildReport(pane, rec) {
  pane.innerHTML = "";
  const r = el("div", "report");
  r.appendChild(el("h3", null, rec.status === "completed" ? "Report" : "Status: " + (rec.status || "unknown")));
  const es = rec.evidence_summary || {};
  r.appendChild(el("div", "kv", `verified ${es.verified || 0} · observed ${es.observed || 0} · believed ${es.believed || 0}` +
    (rec.usage && rec.usage.total_tokens ? ` · ${fmtTok(rec.usage.total_tokens)} tokens` : "")));
  (rec.evidence || []).forEach((f) => {
    const d = el("div");
    d.style.cssText = "display:flex;gap:8px;margin-top:8px;font-size:13px;align-items:flex-start";
    d.innerHTML = `<span class="tier ${esc(f.confidence)}">${esc(f.confidence)}</span><span>${esc(f.claim)}</span>`;
    r.appendChild(d);
  });
  if (rec.verification) {
    r.appendChild(el("h3", null, "Verification"));
    const v = rec.verification;
    r.appendChild(el("div", "kv",
      `${v.verified ? "verified" : "not verified"} · ` +
      `${v.passed_tests || 0} passed test(s) · ` +
      `${v.tests_run != null ? v.tests_run : (v.attempts || []).length} attempt(s)`));
    if (v.reason) r.appendChild(el("div", "kv", v.reason));
    if (rec.delivery) {
      r.appendChild(el("div", "kv",
        `delivery: ${rec.delivery.allowed ? "allowed" : "blocked"} · ${rec.delivery.reason || ""}`));
    }
  }
  r.appendChild(el("h3", null, "Conclusion"));
  const concl = el("div", "answer");
  renderMd(concl, rec.final_answer || "(none)");
  r.appendChild(concl);
  if (rec.sources && rec.sources.length) {
    const src = el("div");
    r.appendChild(el("h3", null, "Sources"));
    rec.sources.forEach((s) => {
      const p = el("div", "kv");
      p.textContent = `${s.title || hostOf(s.url)} — ${s.url}`;
      r.appendChild(p);
    });
  }
  if (rec.error) {
    const e = el("div", "kv", "error: " + rec.error);
    e.style.color = "var(--danger)";
    r.appendChild(e);
  }
  pane.appendChild(r);
}
async function showReport(jobId) {
  let rec;
  try { rec = await getJSON(`/jobs/${jobId}`); } catch (_) { return; }
  buildReport($("#reportPane"), rec);
  openCanvas("report");
}

// ---------------------------------------------------------------------------
// memory
// ---------------------------------------------------------------------------
function openSheet(id) { $(id).classList.add("show"); }
function closeSheet(node) { node.classList.remove("show"); }
$$(".sheet").forEach((s) => s.addEventListener("click", (e) => { if (e.target === s) closeSheet(s); }));

async function openMemory() {
  openSheet("#memorySheet");
  await loadMemory();
}
async function loadMemory() {
  const list = $("#memoryList");
  list.innerHTML = "";
  let data;
  try { data = await getJSON("/memory"); } catch (e) { list.appendChild(el("div", "empty", e.message)); return; }
  const notes = data.notes || [];
  if (!notes.length) {
    list.appendChild(el("div", "empty", "No notes yet. The agent can save one when you ask it to remember something."));
    return;
  }
  notes.slice().reverse().forEach((n) => {
    const row = el("div", "sheet-row");
    const main = el("div", "sr-main");
    main.innerHTML = `<b>${esc(n.text)}</b><span>${esc((n.tags || []).join(", ") || n.source || "agent")} · ${new Date((n.created_at || 0) * 1000).toLocaleDateString()}</span>`;
    const x = el("span", "sr-x");
    x.innerHTML = ic("trash", 15);
    x.addEventListener("click", async () => {
      try { await api(`/memory/${n.id}`, { method: "DELETE" }); row.remove(); } catch (_) {}
    });
    row.appendChild(main);
    row.appendChild(x);
    list.appendChild(row);
  });
}
$("#memoryAdd").addEventListener("click", async () => {
  const text = $("#memoryText").value.trim();
  if (!text) return;
  const tags = $("#memoryTags").value.split(",").map((s) => s.trim()).filter(Boolean);
  try {
    await postJSON("/memory", { text, tags });
    $("#memoryText").value = "";
    $("#memoryTags").value = "";
    await loadMemory();
  } catch (e) { alert(e.message); }
});

// ---------------------------------------------------------------------------
// routines
// ---------------------------------------------------------------------------
function openRoutines() {
  openSheet("#routineSheet");
  loadRoutines();
}
function scheduleText(s) {
  if (!s) return "";
  if (s.kind === "daily") return "Every day at " + s.time;
  if (s.kind === "weekdays") return "Weekdays at " + s.time;
  if (s.kind === "weekly") return "Every week at " + s.time;
  if (s.kind === "every") return "Every " + s.minutes + " minutes";
  if (s.kind === "once") return "Once, " + s.at;
  return s.kind;
}
async function loadRoutines() {
  const list = $("#routineList");
  list.innerHTML = "";
  let data;
  try { data = await getJSON("/routines"); } catch (e) { list.appendChild(el("div", "empty", e.message)); return; }
  const rows = data.routines || [];
  if (!rows.length) {
    list.appendChild(el("div", "empty", "No routines yet. Create one above, or ask the agent to schedule it."));
    return;
  }
  rows.forEach((r) => {
    const row = el("div", "sheet-row");
    const main = el("div", "sr-main");
    main.innerHTML = `<b>${esc(r.name)}</b><span>${esc(scheduleText(r.schedule))}${r.next_run_iso ? " · next " + esc(r.next_run_iso) : ""}${r.enabled ? "" : " · paused"}</span>`;
    const run = el("span", "sr-x");
    run.innerHTML = ic("play", 14);
    run.title = "Run now";
    run.addEventListener("click", async () => {
      try { await postJSON(`/routines/${r.id}/run`, {}); await loadRoutines(); loadHistory(); } catch (_) {}
    });
    const x = el("span", "sr-x");
    x.innerHTML = ic("trash", 15);
    x.addEventListener("click", async () => {
      try { await api(`/routines/${r.id}`, { method: "DELETE" }); await loadRoutines(); } catch (_) {}
    });
    row.appendChild(main);
    row.appendChild(run);
    row.appendChild(x);
    list.appendChild(row);
  });
}
function onceAt(time) {
  const [hh, mm] = (time || "09:00").split(":").map(Number);
  const d = new Date();
  d.setSeconds(0, 0);
  d.setHours(hh || 9, mm || 0, 0, 0);
  if (d.getTime() <= Date.now()) d.setDate(d.getDate() + 1);
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}
$("#routineKind").addEventListener("change", (e) => {
  const k = e.target.value;
  $("#routineTime").style.display = k === "every" ? "none" : "";
  $("#routineEvery").style.display = k === "every" ? "" : "none";
});
$("#routineAdd").addEventListener("click", async () => {
  const goal = $("#routineGoal").value.trim();
  if (!goal) return;
  const kind = $("#routineKind").value;
  const time = $("#routineTime").value || "09:00";
  let schedule;
  if (kind === "every") schedule = { kind, minutes: Math.max(1, parseInt($("#routineEvery").value || "120", 10)) };
  else if (kind === "once") schedule = { kind, at: onceAt(time) };
  else schedule = { kind, time };
  try {
    await postJSON("/routines", {
      name: $("#routineName").value.trim() || goal.slice(0, 60),
      goal,
      schedule,
      template: $("#routineTemplate").value,
      permission,
    });
    $("#routineName").value = "";
    $("#routineGoal").value = "";
    await loadRoutines();
  } catch (e) { alert(e.message); }
});

// ---------------------------------------------------------------------------
// usage + settings
// ---------------------------------------------------------------------------
async function openUsage() {
  openSheet("#usageSheet");
  const body = $("#usageBody");
  body.innerHTML = "";
  let u;
  try { u = await getJSON("/usage"); } catch (e) { body.appendChild(el("div", "empty", e.message)); return; }
  const big = el("div", "usage-big");
  big.innerHTML = `<div class="ub"><b>${fmtTok(u.total_tokens)}</b><span>tokens</span></div>
    <div class="ub"><b>${u.cost_usd == null ? "—" : fmtCost(u.cost_usd)}</b><span>est. cost</span></div>
    <div class="ub"><b>${u.runs || 0}</b><span>runs</span></div>`;
  body.appendChild(big);
  if (u.budget_usd != null) {
    body.appendChild(el("div", "kv", `Monthly budget: ${fmtCost(u.budget_usd)} · remaining ${fmtCost(u.budget_remaining_usd)}`));
  }
  (u.by_day || []).slice().reverse().forEach((d) => {
    const row = el("div", "usage-day");
    row.innerHTML = `<span>${esc(d.date)}</span><span><b>${fmtTok(d.tokens)}</b> tokens · ${d.runs} runs${d.cost_usd ? " · " + fmtCost(d.cost_usd) : ""}</span>`;
    body.appendChild(row);
  });
  if (!(u.by_day || []).length) body.appendChild(el("div", "empty", "No runs yet."));
}
function openSettings() {
  openSheet("#settingsSheet");
  $("#tokenState").textContent = authToken ? "A token is saved in this browser" : "No token saved";
  $("#serverInfo").textContent = config.ready ? `Ready · v${config.version}` : "No model key configured";
  $("#ocrInfo").textContent = config.ocr && (config.ocr.unlimited || config.ocr.tesseract)
    ? [config.ocr.unlimited ? "Unlimited-OCR" : "", config.ocr.tesseract ? "Tesseract" : ""].filter(Boolean).join(" + ")
    : "No OCR engine configured";
}
$("#themeSelect").addEventListener("change", (e) => applyTheme(e.target.value));
$("#notifyToggle").addEventListener("change", async (e) => {
  if (e.target.checked && "Notification" in window) {
    const p = await Notification.requestPermission();
    if (p !== "granted") e.target.checked = false;
  }
  try { localStorage.setItem("rvai-notify", e.target.checked ? "1" : "0"); } catch (_) {}
});
$("#speakToggle").addEventListener("change", (e) => {
  try { localStorage.setItem("rvai-speak", e.target.checked ? "1" : "0"); } catch (_) {}
});
$("#tokenBtn").addEventListener("click", () => {
  authToken = "";
  try { localStorage.removeItem(TOKEN_KEY); } catch (_) {}
  $("#tokenState").textContent = "No token saved";
  showAuth();
});
$("#authGo").addEventListener("click", submitAuth);
$("#authToken").addEventListener("keydown", (e) => { if (e.key === "Enter") submitAuth(); });

// ---------------------------------------------------------------------------
// artifacts
// ---------------------------------------------------------------------------
function updateArtCount() {
  const c = $("#artCount");
  if (!c) return;
  if (sessionArtifacts.length) { c.style.display = ""; c.textContent = sessionArtifacts.length; }
  else c.style.display = "none";
}
async function showArtifacts() {
  openSheet("#artSheet");
  const list = $("#artList");
  list.innerHTML = "";
  let jobs = [];
  try { jobs = (await getJSON("/jobs")).jobs || []; } catch (_) {}
  const rows = [];
  const seen = new Set();
  sessionArtifacts.forEach((a) => {
    if (seen.has(a.href)) return;
    seen.add(a.href);
    rows.push({ ...a, goal: a.goal || "this session" });
  });
  jobs.forEach((j) => {
    if (!j.artifact) return;
    const href = withToken(`/jobs/${j.id}/artifact`);
    if (seen.has(href)) return;
    seen.add(href);
    rows.push({ name: j.artifact, href, goal: j.goal || "saved chat", cost: j.cost_usd });
  });
  if (!rows.length) {
    list.appendChild(el("div", "empty", "No delivered files yet. When I produce and verify a file, it appears here."));
    return;
  }
  rows.forEach((a) => {
    const row = el("a", "artifact");
    row.href = a.href;
    row.setAttribute("download", a.name);
    row.style.marginTop = "0";
    row.innerHTML = `<span class="ai">${ic("download", 18)}</span>
      <span class="at"><b>${esc(a.name)}</b><span>${esc(a.goal || "Delivered file")}${a.size ? " · " + fmtSize(a.size) : ""}${a.sha ? " · sha256 " + a.sha.slice(0, 10) : ""}</span></span>`;
    list.appendChild(row);
  });
}

// ---------------------------------------------------------------------------
// canvas / preview
// ---------------------------------------------------------------------------
function openCanvas(pane) {
  $("#canvas").classList.add("open");
  if (pane) {
    const tab = $(`.tab[data-pane="${pane}"]`);
    if (tab) tab.click();
  }
}
function resetCanvas() {
  views = {};
  viewOrder = [];
  $("#vdropMenu").innerHTML = "";
  $("#vdropLabel").textContent = "Tool output";
  $("#editorEmpty").style.display = "";
  $("#codeOut").style.display = "none";
  $("#codeOut").textContent = "";
  $("#reportPane").innerHTML = `<div class="canvas-empty"><div class="ce-big">${ic("file", 28)}</div>The plain-language report and evidence appear here when a turn finishes.</div>`;
  $("#pvFrame").style.display = "none";
  $("#pvEmpty").style.display = "";
  $("#pvFrame").src = "about:blank";
}
$$(".tab").forEach((t) => t.addEventListener("click", () => {
  $$(".tab").forEach((x) => x.classList.remove("active"));
  $$(".pane").forEach((x) => x.classList.remove("active"));
  t.classList.add("active");
  const pane = $("#" + t.dataset.pane + "Pane");
  if (pane) pane.classList.add("active");
}));
$("#closeCanvas").addEventListener("click", () => $("#canvas").classList.remove("open"));
$("#vdropBtn").addEventListener("click", (e) => { e.stopPropagation(); $("#vdrop").classList.toggle("open"); });
document.addEventListener("click", () => $("#vdrop").classList.remove("open"));
function addView(label, content) {
  const key = "v" + viewOrder.length;
  views[key] = content;
  viewOrder.push({ key, label });
  const menu = $("#vdropMenu");
  const o = el("div", "vopt", label);
  o.dataset.key = key;
  o.addEventListener("click", () => { showView(key); $("#vdrop").classList.remove("open"); });
  menu.appendChild(o);
  return key;
}
function showView(key) {
  const content = views[key];
  if (content == null) return;
  const label = (viewOrder.find((v) => v.key === key) || {}).label || "Tool output";
  $("#vdropLabel").textContent = label;
  $("#editorEmpty").style.display = "none";
  $("#codeOut").style.display = "block";
  $("#codeOut").textContent = content;
  $$(".vopt").forEach((o) => o.classList.toggle("sel", o.dataset.key === key));
  openCanvas("editor");
}
function showPreview(url, opts) {
  const f = $("#pvFrame");
  // Never give untrusted/cloned pages the app's origin. No allow-same-origin.
  f.sandbox = "allow-scripts allow-forms allow-popups";
  f.src = url;
  f.style.display = "block";
  $("#pvEmpty").style.display = "none";
  if (!(opts && opts.keepBar)) {
    $("#pvUrl").value = opts && opts.local ? "Built site (live preview)" : ((opts && opts.shown) || url);
  }
  openCanvas("preview");
}
function browse(u) {
  if (!u) return;
  if (!/^https?:\/\//i.test(u)) u = "https://" + u;
  showPreview("/proxy?url=" + encodeURIComponent(u), { shown: u, keepBar: true });
}
$("#pvGo").addEventListener("click", () => {
  const u = $("#pvUrl").value.trim();
  if (!u || u === "Built site (live preview)") return;
  browse(u);
});
$("#pvUrl").addEventListener("keydown", (e) => { if (e.key === "Enter") $("#pvGo").click(); });

// ---------------------------------------------------------------------------
// host capabilities
// ---------------------------------------------------------------------------
async function loadCaps() {
  let caps;
  try { caps = await getJSON("/caps"); } catch (_) { $("#hostText").textContent = "Host unavailable"; return; }
  $("#hostDot").classList.toggle("ok", !!caps.can_run_untrusted);
  $("#hostText").textContent = caps.can_run_untrusted
    ? (caps.bubblewrap ? "Namespace sandbox ready" : "Sandbox ready")
    : "No isolation available";
  $("#hostText").title = caps.best_isolation || "";
  const g = $("#capsGrid");
  g.innerHTML = "";
  Object.entries(caps).forEach(([k, v]) => {
    if (typeof v !== "boolean") return;
    const c = el("div", "cap" + (v ? " on" : ""));
    c.innerHTML = `<span class="mk"></span><span>${esc(k.replace(/_/g, " "))}</span>`;
    g.appendChild(c);
  });
}

// ---------------------------------------------------------------------------
// scroll + keyboard + PWA + service worker
// ---------------------------------------------------------------------------
$("#thread").addEventListener("scroll", () => {
  const t = $("#thread");
  const nearBottom = t.scrollHeight - t.scrollTop - t.clientHeight < 240;
  $("#scrollBtn").classList.toggle("show", !nearBottom);
});
document.addEventListener("keydown", (e) => {
  const mod = e.metaKey || e.ctrlKey;
  if (mod && e.key.toLowerCase() === "k") { e.preventDefault(); newChat(); return; }
  if (e.key === "Escape") {
    if ($("#authModal").classList.contains("show")) return;
    const open = $$(".sheet.show");
    if (open.length) { open.forEach(closeSheet); return; }
    if ($("#canvas").classList.contains("open")) { $("#canvas").classList.remove("open"); return; }
    if ($("#app").classList.contains("side-open")) { setSidebar(false); return; }
    if ($("#vdrop").classList.contains("open")) $("#vdrop").classList.remove("open");
  }
});
function registerSW() {
  if (!("serviceWorker" in navigator)) return;
  if (location.protocol !== "https:" && location.hostname !== "localhost" && location.hostname !== "127.0.0.1") return;
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}

// go
autosize();
boot();
try {
  const q = new URLSearchParams(location.search);
  if (q.get("new") === "1") setTimeout(() => newChat(), 250);
} catch (_) {}

// expose a few internals for debugging in the console (no UI impact)
window.reverseai = { newChat, openMemory, openRoutines, openUsage, showReport };
