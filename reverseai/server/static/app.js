"use strict";

const $ = (s) => document.querySelector(s);
const el = (t, c, x) => { const n = document.createElement(t); if (c) n.className = c; if (x != null) n.textContent = x; return n; };
const esc = (s) => { const d = el("div"); d.textContent = s == null ? "" : s; return d.innerHTML; };

// ---------- professional icon set (Lucide-style, stroke = currentColor) ----------
const P = {
  logo: '<path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.3 7 12 12 20.7 7"/><line x1="12" y1="22" x2="12" y2="12"/>',
  plus: '<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>',
  globe: '<circle cx="12" cy="12" r="9"/><line x1="3" y1="12" x2="21" y2="12"/><path d="M12 3a14 14 0 0 1 3.5 9A14 14 0 0 1 12 21a14 14 0 0 1-3.5-9A14 14 0 0 1 12 3z"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
  cpu: '<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M9 2v2M15 2v2M9 20v2M15 20v2M2 9h2M2 15h2M20 9h2M20 15h2"/>',
  search: '<circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>',
  chevronLeft: '<polyline points="15 18 9 12 15 6"/>',
  menu: '<line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/>',
  moon: '<path d="M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8z"/>',
  arrowUp: '<line x1="12" y1="19" x2="12" y2="5"/><polyline points="5 12 12 5 19 12"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor" stroke="none"/>',
  paperclip: '<path d="M21.4 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/>',
  x: '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>',
  file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/>',
  archive: '<rect x="2" y="4" width="20" height="5" rx="1"/><path d="M4 9v9a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9"/><line x1="10" y1="13" x2="14" y2="13"/>',
  check: '<polyline points="20 6 9 17 4 12"/>',
  alert: '<circle cx="12" cy="12" r="9"/><line x1="12" y1="8" x2="12" y2="13"/><line x1="12" y1="16" x2="12" y2="16"/>',
  sparkle: '<path d="M12 4l1.6 4.4L18 10l-4.4 1.6L12 16l-1.6-4.4L6 10l4.4-1.6z"/>',
  code: '<polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>',
  dot: '<circle cx="12" cy="12" r="3" fill="currentColor" stroke="none"/>',
  box: '<path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/>',
};
function ic(name, size) {
  const s = size || 18;
  return `<svg class="icon" width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">${P[name] || ""}</svg>`;
}
function renderIcons(root) {
  (root || document).querySelectorAll("[data-icon]").forEach((n) => {
    if (!n.dataset.done) { n.innerHTML = ic(n.dataset.icon, n.dataset.size ? +n.dataset.size : 18); n.dataset.done = "1"; }
  });
}
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
  if (!text) return text || "";
  const parts = text.split(/(```[\s\S]*?```|`[^`]*`)/);
  return parts.map((p, i) => (i % 2 ? p : p.split("\n").map(dedashLine).join("\n"))).join("");
}
function md(text) {
  // De-dash, then render markdown (sanitized). Lists render as proper bullets,
  // so no literal dashes ever reach the user. Falls back to escaped text.
  const clean = deDash(text || "");
  try {
    if (window.marked && window.DOMPurify)
      return DOMPurify.sanitize(marked.parse(clean, { breaks: true }));
  } catch (_) {}
  return esc(clean).replace(/\n/g, "<br>");
}
async function getJSON(u) { const r = await fetch(u); return r.json(); }
async function postJSON(u, b) { const r = await fetch(u, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b) }); return { status: r.status, body: await r.json() }; }

// theme
function applyTheme(t) { document.documentElement.setAttribute("data-theme", t); try { localStorage.setItem("rvai-theme", t); } catch (_) {} }
try { const s = localStorage.getItem("rvai-theme"); if (s) applyTheme(s); } catch (_) {}
$("#themeBtn").addEventListener("click", () => { const c = document.documentElement.getAttribute("data-theme") || "auto"; applyTheme(c === "auto" ? "light" : c === "light" ? "dark" : "auto"); });

// editor + canvas
let editor; const views = {}; const viewOrder = [];
window.addEventListener("load", () => {
  editor = CodeMirror.fromTextArea($("#editor"), { lineNumbers: true, mode: "gas", lineWrapping: false });
});
function addView(label, content) {
  const key = "v" + viewOrder.length; views[key] = content; viewOrder.push({ key, label });
  const menu = $("#vdropMenu");
  const o = el("div", "vopt", label); o.dataset.key = key;
  o.onclick = () => { showView(key); $("#vdrop").classList.remove("open"); };
  menu.appendChild(o);
  return key;
}
function showView(key) {
  if (editor && views[key] != null) {
    openCanvas("editor");
    $("#editorEmpty").style.display = "none"; $("#editorHolder").style.display = "flex";
    const lbl = (viewOrder.find((v) => v.key === key) || {}).label || "tool output";
    $("#vdropLabel").textContent = lbl;
    document.querySelectorAll(".vopt").forEach((o) => o.classList.toggle("sel", o.dataset.key === key));
    editor.setValue(views[key]); setTimeout(() => editor.refresh(), 30);
  }
}
$("#vdropBtn").addEventListener("click", (e) => { e.stopPropagation(); $("#vdrop").classList.toggle("open"); });
document.addEventListener("click", () => $("#vdrop").classList.remove("open"));
function openCanvas(pane) {
  $("#canvas").classList.add("open");
  if (pane) document.querySelector(`.tab[data-pane="${pane}"]`).click();
  setTimeout(() => editor && editor.refresh(), 240);
}
$("#closeCanvas").addEventListener("click", () => $("#canvas").classList.remove("open"));

// built-in browser / preview
function showPreview(url, opts) {
  const f = $("#pvFrame");
  // Our own built site is same-origin (safe); external pages go through the
  // proxy and run as an opaque origin so they can't reach the app.
  const local = (opts && opts.local) || url.startsWith("/preview/");
  f.sandbox = local ? "allow-scripts allow-same-origin allow-forms allow-popups"
                    : "allow-scripts allow-forms allow-popups";
  f.src = url; f.style.display = "block";
  $("#pvEmpty").style.display = "none";
  if (!(opts && opts.keepBar))
    $("#pvUrl").value = local ? "built site · live preview" : (opts && opts.shown) || url;
  openCanvas("preview");
}
function browse(u) {
  if (!u) return;
  if (!/^https?:\/\//i.test(u)) u = "https://" + u;
  showPreview("/proxy?url=" + encodeURIComponent(u), { shown: u, keepBar: true });
}
function loadPreviewUrl() {
  const u = $("#pvUrl").value.trim();
  if (!u || u === "built site · live preview") return;
  browse(u);
}
$("#pvGo").addEventListener("click", loadPreviewUrl);
$("#pvUrl").addEventListener("keydown", (e) => { if (e.key === "Enter") loadPreviewUrl(); });
document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => {
  document.querySelectorAll(".tab").forEach((x) => x.classList.remove("active"));
  document.querySelectorAll(".pane").forEach((x) => x.classList.remove("active"));
  t.classList.add("active"); $("#" + t.dataset.pane + "Pane").classList.add("active");
  if (t.dataset.pane === "editor" && editor) setTimeout(() => editor.refresh(), 30);
}));

// composer autosize (grows as you type, like Claude)
const input = $("#input");
function autosize() {
  input.style.height = "auto";
  const max = Math.round(window.innerHeight * 0.45);
  const full = input.scrollHeight;
  input.style.height = Math.min(full, max) + "px";
  input.style.overflowY = full > max ? "auto" : "hidden";
}
input.addEventListener("input", autosize);
window.addEventListener("resize", autosize);
input.addEventListener("keydown", (e) => {
  if (e.key !== "Enter") return;
  if (e.ctrlKey || e.metaKey) {       // Ctrl/Cmd+Enter -> newline at cursor
    e.preventDefault();
    const s = input.selectionStart, en = input.selectionEnd;
    input.value = input.value.slice(0, s) + "\n" + input.value.slice(en);
    input.selectionStart = input.selectionEnd = s + 1;
    autosize();
  } else if (!e.shiftKey) {            // Enter -> send (Shift+Enter = newline, default)
    e.preventDefault();
    submit();
  }
});
$("#send").addEventListener("click", () => { if (busy) stopRun(); else submit(); });
let currentSrc = null, currentUI = null;
function stopRun() { if (currentSrc) currentSrc.close(); if (currentUI) finishError(currentUI, "stopped"); }

// ---- attachment (upload + drag/drop) ----
let attached = null; // { path, filename, size, kind }
const ARCHIVE_KINDS = new Set(["zip", "gzip", "bzip2", "xz", "tar", "7z"]);
$("#attach").addEventListener("click", () => $("#fileInput").click());
$("#fileInput").addEventListener("change", (e) => { if (e.target.files[0]) uploadFile(e.target.files[0]); e.target.value = ""; });
function fmtSize(n) { if (n < 1024) return n + " B"; if (n < 1048576) return (n / 1024).toFixed(1) + " KB"; if (n < 1073741824) return (n / 1048576).toFixed(1) + " MB"; return (n / 1073741824).toFixed(2) + " GB"; }
async function uploadFile(file) {
  removeWelcome();
  const chip = $("#fileChip"); attached = null;
  chip.style.display = "flex"; chip.classList.add("uploading");
  chip.innerHTML = `<span class="fi">${ic("file",16)}</span><span><span class="fname">${esc(file.name)}</span> <span class="fmeta">${fmtSize(file.size)}</span></span>`;
  try {
    const r = await fetch("/upload", { method: "PUT", headers: { "X-Filename": file.name }, body: file });
    const b = await r.json();
    if (!r.ok) throw new Error(b.error || "upload failed");
    attached = b; renderChip();
  } catch (err) {
    chip.classList.remove("uploading");
    chip.innerHTML = `<span class="fi">${ic("alert",16)}</span><span><span class="fname">${esc(file.name)}</span> <span class="fmeta" style="color:#ff453a">${esc(err.message)}</span></span><span class="rm" onclick="clearAttachment()">${ic("x",14)}</span>`;
  }
}
function renderChip() {
  const chip = $("#fileChip"); chip.classList.remove("uploading");
  const warn = ARCHIVE_KINDS.has(attached.kind);
  const kindLbl = attached.kind === "unknown" ? "file" : attached.kind;
  const archBit = (attached.arch && attached.arch !== "unknown")
    ? ` · ${attached.arch}${attached.bits ? " " + attached.bits + "-bit" : ""}` : "";
  chip.innerHTML = `<span class="fi">${warn ? ic("archive",16) : ic("file",16)}</span>
    <span><span class="fname">${esc(attached.filename)}</span> <span class="fmeta">${fmtSize(attached.size)}${esc(archBit)}</span></span>
    <span class="kind ${warn ? "warn" : ""}">${esc(kindLbl)}</span>
    <span class="rm" onclick="clearAttachment()">${ic("x",14)}</span>`;
}
function clearAttachment() { attached = null; const c = $("#fileChip"); c.style.display = "none"; c.innerHTML = ""; }
window.clearAttachment = clearAttachment;

// drag & drop
let dragDepth = 0;
const overlay = $("#dropOverlay");
window.addEventListener("dragenter", (e) => { if (e.dataTransfer && [...e.dataTransfer.types].includes("Files")) { dragDepth++; overlay.classList.add("show"); } });
window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("dragleave", () => { dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) overlay.classList.remove("show"); });
window.addEventListener("drop", (e) => { e.preventDefault(); dragDepth = 0; overlay.classList.remove("show"); const f = e.dataTransfer.files[0]; if (f) uploadFile(f); });

// ---- message queue ----
const queue = [];
function renderQueue() {
  const q = $("#queued"); q.innerHTML = "";
  queue.forEach((m, i) => { const d = el("div", "qmsg"); d.innerHTML = `<span class="qlabel">queued</span> <span>${esc(m.goal.slice(0, 70))}</span><span class="qx">${ic("x",13)}</span>`; d.querySelector(".qx").onclick = () => { queue.splice(i, 1); renderQueue(); }; q.appendChild(d); });
}
function submit() {
  if (busy) { // queue it
    const goal = input.value.trim(); if (!goal) return;
    queue.push({ goal, attached }); input.value = ""; autosize(); renderQueue();
    return;
  }
  send();
}
function drainQueue() { if (queue.length && !busy) { const next = queue.shift(); renderQueue(); input.value = next.goal; if (next.attached) { attached = next.attached; renderChip(); $("#fileChip").style.display = "flex"; } send(); } }
$("#navNew").addEventListener("click", newChat);
// sidebar collapse
$("#collapseBtn").addEventListener("click", () => $("#app").classList.add("collapsed"));
$("#expandBtn").addEventListener("click", () => $("#app").classList.remove("collapsed"));
// search filter
$("#search").addEventListener("input", (e) => {
  const q = e.target.value.toLowerCase();
  document.querySelectorAll("#convos .convo").forEach((c) => {
    c.style.display = c.dataset.goal && c.dataset.goal.includes(q) ? "" : "none";
  });
});
// host nav -> open canvas Host tab
$("#navHost").addEventListener("click", () => openCanvas("caps"));
// browser nav -> open the in-app browser (preview)
$("#navBrowser").addEventListener("click", () => { openCanvas("preview"); setTimeout(() => $("#pvUrl").focus(), 250); });
// artifacts
const sessionArtifacts = [];
$("#navArtifacts").addEventListener("click", showArtifacts);
$("#artSheet").addEventListener("click", (e) => { if (e.target.id === "artSheet") e.target.classList.remove("show"); });
function showArtifacts() {
  const list = $("#artList");
  list.innerHTML = sessionArtifacts.length ? "" :
    `<div class="canvas-empty" style="padding:28px"><div class="ce-big">${ic("download", 30)}</div>No delivered files yet. When I produce and verify a file, it appears here.</div>`;
  sessionArtifacts.forEach((a) => {
    const row = el("a", "artifact"); row.style.display = "flex"; row.style.marginTop = "8px";
    row.href = a.href; row.setAttribute("download", a.name);
    row.innerHTML = `<span class="ai">${ic("download",17)}</span><span class="at"><b>${esc(a.name)}</b><span>${esc(a.goal || "delivered file")}</span></span>`;
    list.appendChild(row);
  });
  $("#artSheet").classList.add("show");
}
// Reopen a past chat: rebuild the thread from its saved transcript so you can
// read it (and continue it if the conversation is still live on the server).
async function openConversation(jobId) {
  let rec; try { rec = await getJSON(`/jobs/${jobId}`); } catch (_) { return; }
  if (!rec || rec.error) return;
  resetCanvas(); queue.length = 0; renderQueue(); clearAttachment();
  inner.innerHTML = "";
  conversationId = rec.conversation_id || null;  // best-effort continue
  const msgs = rec.transcript || [];
  let lastAssistant = null;
  for (const m of msgs) {
    if (m.role === "user") {
      // skip tool-result user turns (they carry tool_call_id / array content)
      if (m.tool_call_id || Array.isArray(m.content)) continue;
      let text = (m.content || "").toString();
      text = text.split("\n\n[Attached target:")[0]
                 .replace(/^Goal:\s*/i, "").trim();
      if (text) userTurn(text);
    } else if (m.role === "assistant" && m.content) {
      lastAssistant = m.content;
    }
  }
  if (lastAssistant) {
    const t = el("div", "turn ai");
    const av = el("div", "avatar"); av.innerHTML = ic("logo", 17); t.appendChild(av);
    const body = el("div", "ai-body");
    const ans = el("div", "answer"); ans.innerHTML = md(lastAssistant);
    body.appendChild(ans); t.appendChild(body); inner.appendChild(t);
  }
  // offer the full report for this turn
  if (rec.final_answer) showReportInline(rec);
  scrollDown();
}
function showReportInline(rec) {
  // populate the Report canvas pane without forcing it open
  const pane = $("#reportPane"); if (!pane) return;
  buildReport(pane, rec);
}

async function deleteChat(jobId, node) {
  try {
    await fetch(`/jobs/${jobId}`, { method: "DELETE" });
    node.remove();
  } catch (_) {}
}

function updateArtCount() {
  const c = $("#artCount");
  if (sessionArtifacts.length) { c.style.display = ""; c.textContent = sessionArtifacts.length; }
  else c.style.display = "none";
}
function wireChips() {
  document.querySelectorAll(".chip").forEach((c) => c.onclick = () => { input.value = c.dataset.g; input.focus(); autosize(); });
}
wireChips();

const thread = $("#thread"); const inner = $("#threadInner");
let busy = false;
let conversationId = null;  // continues the same investigation across messages

// Friendly labels so the activity never exposes internal tool names.
const TOOL_LABELS = {
  host_capabilities: "Checking the environment",
  analyze_binary: "Analyzing the file",
  read_bytes: "Reading data",
  list_strings: "Reading text in the file",
  disassemble: "Disassembling code",
  list_functions: "Mapping functions",
  analyze_apk: "Analyzing the app",
  assess_heuristics: "Checking for risks",
  run_in_sandbox: "Running it safely",
  record_finding: "Noting a finding",
  apply_byte_patch: "Modifying the file",
  verify_against_original: "Verifying the change",
  diff_modified: "Comparing versions",
  extract_archive: "Unpacking the archive",
  clone_website: "Rebuilding the site",
  add_imported_library: "Modifying the file",
  add_section: "Modifying the file",
  list_dir: "Looking through files",
  read_file: "Reading a file",
  write_file: "Writing a file",
  edit_file: "Editing a file",
  run_command: "Running a step",
};
function toolLabel(name) { return TOOL_LABELS[name] || "Working"; }
function scrollDown() { thread.scrollTop = thread.scrollHeight; }
function removeWelcome() { const w = $("#welcome"); if (w) w.remove(); }

function resetCanvas() {
  viewOrder.length = 0; for (const k in views) delete views[k];
  $("#vdropMenu").innerHTML = ""; $("#vdropLabel").textContent = "tool output";
  $("#editorEmpty").style.display = ""; $("#editorHolder").style.display = "none";
  $("#reportPane").innerHTML = `<div class="canvas-empty"><div class="ce-big">${ic("file", 30)}</div>The plain-language report and evidence appear here when a turn completes.</div>`;
}
function newChat() {
  conversationId = null; clearAttachment(); queue.length = 0; renderQueue(); resetCanvas();
  inner.innerHTML = "";
  const w = el("div", "welcome"); w.id = "welcome";
  w.innerHTML = `<div class="big">${ic("logo", 46)}</div><h1>What can I build or break down for you?</h1>
    <p>Hand me a binary, an app, an archive, or a website, and tell me the goal. I work in an isolated sandbox and hand back a finished, verified result.</p>
    <div class="suggest">
      <div class="chip" data-g="Analyze this binary and tell me what it does, in plain language.">Analyze a binary</div>
      <div class="chip" data-g="Run this program safely in the sandbox and tell me what it does.">Run it safely</div>
      <div class="chip" data-g="Change this program's behavior and give me back a working modified file.">Modify &amp; deliver</div>
    </div>`;
  inner.appendChild(w); wireChips();
  document.querySelectorAll(".convo").forEach((c) => c.classList.remove("active"));
}

function userTurn(text) {
  removeWelcome();
  const t = el("div", "turn user"); const b = el("div", "bubble", text); t.appendChild(b); inner.appendChild(t); scrollDown();
}

function aiTurn() {
  const t = el("div", "turn ai");
  const av = el("div", "avatar"); av.innerHTML = ic("logo", 17); t.appendChild(av);
  const body = el("div", "ai-body");
  const work = el("div", "work");
  const head = el("div", "work-head");
  head.appendChild(el("span", "spin"));
  const label = el("span", null, "Thinking…"); head.appendChild(label);
  const chev = el("span", "chev", "▾"); head.appendChild(chev);
  head.addEventListener("click", () => work.classList.toggle("collapsed"));
  const wbody = el("div", "work-body");
  work.appendChild(head); work.appendChild(wbody);
  body.appendChild(work);
  t.appendChild(body); inner.appendChild(t); scrollDown();
  return { body, work, head, label, wbody };
}

function act(wbody, icon, html) {
  const a = el("div", "act"); a.innerHTML = `<span class="ic">${icon}</span><span class="tx">${html}</span>`;
  wbody.appendChild(a); scrollDown(); return a;
}

function setBusy(on) {
  busy = on;
  const b = $("#send");
  b.classList.toggle("stop", on);
  b.innerHTML = on ? ic("stop", 18) : ic("arrowUp", 19);
  b.title = on ? "Stop" : "Send";
}

async function send() {
  if (busy) return;
  const goal = input.value.trim(); if (!goal) return;
  setBusy(true);
  userTurn(goal);
  input.value = ""; input.style.height = "auto";
  const payload = { goal };
  if (attached) { payload.target = attached.path; clearAttachment(); }
  if (conversationId) payload.conversation_id = conversationId;
  const ui = aiTurn(); currentUI = ui;

  const { status, body } = await postJSON("/jobs/start", payload);
  if (status !== 200) { finishError(ui, body.error || "failed to start"); return; }
  const jobId = body.job_id;
  if (body.conversation_id) conversationId = body.conversation_id;
  const src = new EventSource(`/jobs/${jobId}/events`); currentSrc = src;
  let steps = 0;
  src.onmessage = (m) => {
    let ev; try { ev = JSON.parse(m.data); } catch (_) { return; }
    if (ev.type === "step") { steps = ev.step; ui.label.textContent = "Thinking…"; }
    else if (ev.type === "assistant") {
      if (ev.content) act(ui.wbody, ic("sparkle", 14), esc(deDash(ev.content)));
    }
    else if (ev.type === "tool_result") {
      const ok = ev.ok ? ic("check", 15) : ic("alert", 15);
      const a = act(ui.wbody, ok, `<b>${esc(toolLabel(ev.name))}</b>`);
      a.classList.add("tool", ev.ok ? "ok" : "fail");
      ui.label.textContent = "Working…";
      if (ev.content) { const key = addView(toolLabel(ev.name), ev.content); const v = el("span", "view", "view details"); v.addEventListener("click", () => showView(key)); a.querySelector(".tx").appendChild(v); }
      // When a site is built/cloned, show it live in the preview pane.
      if (ev.name === "clone_website" && ev.ok && conversationId) showPreview(`/preview/${conversationId}/index.html`);
    }
    else if (ev.type === "finding") {
      const a = act(ui.wbody, "", `<span class="tier ${ev.tier}">${ev.tier}</span> ${esc(ev.claim)}`);
    }
    else if (ev.type === "final") { src.close(); finishFinal(ui, jobId, ev, steps); if (ev.artifact) addArtifact(ui, ev.artifact, jobId); }
    else if (ev.type === "error") { src.close(); finishError(ui, ev.error); }
  };
  src.onerror = () => { src.close(); if (busy) finishError(ui, "connection lost"); };
}

function finishFinal(ui, jobId, ev, steps) {
  ui.work.classList.add("collapsed");
  ui.head.querySelector(".spin").remove();
  const mark = el("span", "donemark"); mark.innerHTML = ic("check", 15); mark.style.color = "var(--verified)";
  ui.head.insertBefore(mark, ui.head.firstChild);
  ui.label.textContent = `Worked through ${ev.steps || steps} step${(ev.steps || steps) === 1 ? "" : "s"}`;
  const ans = el("div", "answer"); ans.innerHTML = md(ev.answer || "_(no conclusion)_");
  ui.body.appendChild(ans);
  const es = ev.evidence_summary || {};
  if ((es.verified || es.observed || es.believed)) {
    const row = el("div", "evi-row");
    row.appendChild(evi("verified", es.verified || 0));
    row.appendChild(evi("observed", es.observed || 0));
    row.appendChild(evi("believed", es.believed || 0));
    const rep = el("span", "evi"); rep.style.cursor = "pointer"; rep.innerHTML = ic("file", 13) + " full report";
    rep.addEventListener("click", () => showReport(jobId));
    row.appendChild(rep);
    ui.body.appendChild(row);
  }
  scrollDown(); loadHistory(); done();
}
function evi(tier, n) { const e = el("span", "evi"); e.innerHTML = `<span class="tier ${tier}">${tier}</span> <b>${n}</b>`; return e; }
function finishError(ui, msg) {
  if (ui.head.querySelector(".spin")) ui.head.querySelector(".spin").remove();
  ui.label.textContent = "Stopped";
  const e = el("div", "answer"); e.innerHTML = `<span style="color:#ff453a">✗ ${esc(msg)}</span>`; ui.body.appendChild(e);
  scrollDown(); done();
}
function done() { setBusy(false); currentSrc = null; currentUI = null; setTimeout(drainQueue, 150); }

function addArtifact(ui, name, jobId) {
  const href = `/jobs/${jobId}/artifact`;
  const a = document.createElement("a");
  a.className = "artifact"; a.href = href; a.setAttribute("download", name);
  a.innerHTML = `<span class="ai">${ic("download",17)}</span><span class="at"><b>${esc(name)}</b><span>Delivered file · click to download</span></span>`;
  ui.body.appendChild(a); scrollDown();
  sessionArtifacts.unshift({ name, href, goal: name });
  updateArtCount();
}

// report + caps
function buildReport(pane, rec) {
  pane.innerHTML = "";
  const r = el("div", "report");
  r.appendChild(el("h3", null, rec.status === "completed" ? "Report" : `Status: ${rec.status}`));
  const es = rec.evidence_summary || {};
  r.appendChild(el("div", "kv", `verified ${es.verified || 0} · observed ${es.observed || 0} · believed ${es.believed || 0}` + (rec.usage && rec.usage.total_tokens ? ` · ${rec.usage.total_tokens} tokens` : "")));
  (rec.evidence || []).forEach((f) => {
    const d = el("div"); d.style.cssText = "display:flex;gap:8px;margin-top:8px;font-size:13px;align-items:flex-start";
    d.innerHTML = `<span class="tier ${f.confidence}">${f.confidence}</span><span>${esc(f.claim)}</span>`; r.appendChild(d);
  });
  r.appendChild(el("h3", null, "Conclusion"));
  const concl = el("div", "answer"); concl.innerHTML = md(rec.final_answer || "(none)");
  r.appendChild(concl);
  if (rec.error) { const e = el("div", "kv", "error: " + rec.error); e.style.color = "#ff453a"; r.appendChild(e); }
  pane.appendChild(r);
}
async function showReport(jobId) {
  let rec; try { rec = await getJSON(`/jobs/${jobId}`); } catch (_) { return; }
  if (rec.error) return;
  buildReport($("#reportPane"), rec); openCanvas("report");
}

async function loadCaps() {
  try {
    const caps = await getJSON("/caps");
    $("#hostDot").classList.toggle("ok", !!caps.can_run_untrusted);
    $("#hostText").textContent = caps.can_run_untrusted ? (caps.best_isolation || "sandbox ready") : "no isolation";
    const g = $("#capsGrid"); g.innerHTML = "";
    Object.entries(caps).forEach(([k, v]) => { if (typeof v !== "boolean") return; const c = el("div", "cap" + (v ? " on" : "")); c.appendChild(el("span", "mk")); c.appendChild(el("span", null, k)); g.appendChild(c); });
  } catch (_) { $("#hostText").textContent = "host unavailable"; }
}
async function loadHistory() {
  try {
    const { jobs } = await getJSON("/jobs"); const h = $("#convos"); h.innerHTML = "";
    (jobs || []).slice(0, 30).forEach((j) => {
      const it = el("div", "convo");
      it.dataset.goal = (j.goal || "").toLowerCase();
      it.title = `${j.status} · ${j.steps} steps`;
      const cvic=el("span","cv-ic");cvic.innerHTML=ic("dot",8);it.appendChild(cvic);
      const label = el("span", "cv-label", (j.goal || "(chat)").slice(0, 36));
      it.appendChild(label);
      const del = el("span", "cv-del"); del.innerHTML = ic("x",14);
      del.title = "Delete chat";
      del.addEventListener("click", (e) => { e.stopPropagation(); deleteChat(j.id, it); });
      it.appendChild(del);
      it.addEventListener("click", () => { document.querySelectorAll(".convo").forEach(c=>c.classList.remove("active")); it.classList.add("active"); openConversation(j.id); });
      h.appendChild(it);
    });
  } catch (_) {}
}
// Escape closes overlays / canvas
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if ($("#artSheet").classList.contains("show")) { $("#artSheet").classList.remove("show"); return; }
  if ($("#vdrop").classList.contains("open")) { $("#vdrop").classList.remove("open"); return; }
  if ($("#canvas").classList.contains("open")) $("#canvas").classList.remove("open");
});

if (window.innerWidth < 900) $("#app").classList.add("collapsed");
async function checkReady() {
  try {
    const c = await getJSON("/config");
    if (!c.ready) {
      const w = $("#welcome");
      if (w && !$("#readyNote")) {
        const n = el("div"); n.id = "readyNote";
        n.style.cssText = "margin:18px auto 0;max-width:460px;font-size:13px;color:var(--believed);background:rgba(208,133,0,.1);border:1px solid rgba(208,133,0,.25);border-radius:12px;padding:11px 14px;line-height:1.5";
        n.textContent = "Almost ready — connect a model by setting the provider API key on the server, then reload.";
        w.appendChild(n);
      }
    }
  } catch (_) {}
}

autosize();  // size the composer correctly on first paint (no stray scrollbar)

renderIcons();   // fill all static [data-icon] placeholders

// Opened as a file:// (no backend)? Show a full blocking notice instead of
// failing silently when the user tries to chat.
if (location.protocol === "file:") {
  $("#fileBlock").classList.add("show");
}
checkReady(); loadCaps(); loadHistory();
