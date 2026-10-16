"use strict";

const $ = (s) => document.querySelector(s);
const el = (t, c, x) => { const n = document.createElement(t); if (c) n.className = c; if (x != null) n.textContent = x; return n; };
const esc = (s) => { const d = el("div"); d.textContent = s == null ? "" : s; return d.innerHTML; };
function md(text) {
  // Render markdown, sanitized. Falls back to escaped plain text if libs missing.
  try {
    if (window.marked && window.DOMPurify)
      return DOMPurify.sanitize(marked.parse(text || "", { breaks: true }));
  } catch (_) {}
  return esc(text).replace(/\n/g, "<br>");
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
document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => {
  document.querySelectorAll(".tab").forEach((x) => x.classList.remove("active"));
  document.querySelectorAll(".pane").forEach((x) => x.classList.remove("active"));
  t.classList.add("active"); $("#" + t.dataset.pane + "Pane").classList.add("active");
  if (t.dataset.pane === "editor" && editor) setTimeout(() => editor.refresh(), 30);
}));

// composer autosize (grows as you type, like Claude)
const input = $("#input");
function autosize() { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, Math.round(window.innerHeight * 0.45)) + "px"; }
input.addEventListener("input", autosize);
input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); } });
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
  chip.innerHTML = `<span class="fi">📄</span><span><span class="fname">${esc(file.name)}</span> <span class="fmeta">${fmtSize(file.size)}</span></span>`;
  try {
    const r = await fetch("/upload", { method: "PUT", headers: { "X-Filename": file.name }, body: file });
    const b = await r.json();
    if (!r.ok) throw new Error(b.error || "upload failed");
    attached = b; renderChip();
  } catch (err) {
    chip.classList.remove("uploading");
    chip.innerHTML = `<span class="fi">⚠︎</span><span><span class="fname">${esc(file.name)}</span> <span class="fmeta" style="color:#ff453a">${esc(err.message)}</span></span><span class="rm" onclick="clearAttachment()">✕</span>`;
  }
}
function renderChip() {
  const chip = $("#fileChip"); chip.classList.remove("uploading");
  const warn = ARCHIVE_KINDS.has(attached.kind);
  const kindLbl = attached.kind === "unknown" ? "file" : attached.kind;
  chip.innerHTML = `<span class="fi">${warn ? "🗜️" : "📄"}</span>
    <span><span class="fname">${esc(attached.filename)}</span> <span class="fmeta">${fmtSize(attached.size)}</span></span>
    <span class="kind ${warn ? "warn" : ""}">${esc(kindLbl)}</span>
    <span class="rm" onclick="clearAttachment()">✕</span>`;
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
  queue.forEach((m, i) => { const d = el("div", "qmsg"); d.innerHTML = `<span>⏎ queued:</span> <span>${esc(m.goal.slice(0, 70))}</span><span class="qx">✕</span>`; d.querySelector(".qx").onclick = () => { queue.splice(i, 1); renderQueue(); }; q.appendChild(d); });
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
$("#newChat").addEventListener("click", newChat);
function wireChips() {
  document.querySelectorAll(".chip").forEach((c) => c.onclick = () => { input.value = c.dataset.g; input.focus(); autosize(); });
}
wireChips();

const thread = $("#thread"); const inner = $("#threadInner");
let busy = false;
let conversationId = null;  // continues the same investigation across messages
function scrollDown() { thread.scrollTop = thread.scrollHeight; }
function removeWelcome() { const w = $("#welcome"); if (w) w.remove(); }

function resetCanvas() {
  viewOrder.length = 0; for (const k in views) delete views[k];
  $("#vdropMenu").innerHTML = ""; $("#vdropLabel").textContent = "tool output";
  $("#editorEmpty").style.display = ""; $("#editorHolder").style.display = "none";
  $("#reportPane").innerHTML = '<div class="canvas-empty"><div class="ce-big">✦</div>The plain-language report and evidence appear here when a turn completes.</div>';
}
function newChat() {
  conversationId = null; clearAttachment(); queue.length = 0; renderQueue(); resetCanvas();
  inner.innerHTML = "";
  const w = el("div", "welcome"); w.id = "welcome";
  w.innerHTML = `<div class="big">✦</div><h1>What should we reverse-engineer?</h1>
    <p>Drop a binary (Windows PE, Linux ELF, or macOS/iOS Mach-O) or archive and tell me what you want. I'll investigate it, work in an isolated sandbox, and deliver the result.</p>
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
  t.appendChild(el("div", "avatar", "✦"));
  const body = el("div", "ai-body");
  const work = el("div", "work");
  const head = el("div", "work-head");
  head.appendChild(el("span", "spin"));
  const label = el("span", null, "Investigating…"); head.appendChild(label);
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
  b.innerHTML = on ? "■" : "↑";
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
    if (ev.type === "step") { steps = ev.step; ui.label.textContent = `Investigating… step ${ev.step}`; }
    else if (ev.type === "assistant") {
      if (ev.content) act(ui.wbody, "💭", esc(ev.content));
      (ev.tool_calls || []).forEach((c) => {});
    }
    else if (ev.type === "tool_result") {
      const ok = ev.ok ? "✓" : "✗";
      const a = act(ui.wbody, ok, `<b>${esc(ev.name)}</b>`);
      a.classList.add("tool");
      if (ev.content) { const key = addView(ev.name, ev.content); const v = el("span", "view", "view output"); v.addEventListener("click", () => showView(key)); a.querySelector(".tx").appendChild(v); }
    }
    else if (ev.type === "finding") {
      const a = act(ui.wbody, "", `<span class="tier ${ev.tier}">${ev.tier}</span> ${esc(ev.claim)}`);
    }
    else if (ev.type === "final") { src.close(); finishFinal(ui, jobId, ev, steps); if (ev.artifact) addArtifact(ui, ev.artifact); }
    else if (ev.type === "error") { src.close(); finishError(ui, ev.error); }
  };
  src.onerror = () => { src.close(); if (busy) finishError(ui, "connection lost"); };
}

function finishFinal(ui, jobId, ev, steps) {
  ui.work.classList.add("collapsed");
  ui.head.querySelector(".spin").remove();
  const ic = el("span", null, "✓"); ic.style.color = "var(--verified)"; ic.style.width = "14px"; ic.style.textAlign = "center";
  ui.head.insertBefore(ic, ui.head.firstChild);
  ui.label.textContent = `Worked through ${ev.steps || steps} step${(ev.steps || steps) === 1 ? "" : "s"}`;
  const ans = el("div", "answer"); ans.innerHTML = md(ev.answer || "_(no conclusion)_");
  ui.body.appendChild(ans);
  const es = ev.evidence_summary || {};
  if ((es.verified || es.observed || es.believed)) {
    const row = el("div", "evi-row");
    row.appendChild(evi("verified", es.verified || 0));
    row.appendChild(evi("observed", es.observed || 0));
    row.appendChild(evi("believed", es.believed || 0));
    const rep = el("span", "evi"); rep.style.cursor = "pointer"; rep.innerHTML = "📄 full report";
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

function addArtifact(ui, name) {
  if (!conversationId) return;
  const a = document.createElement("a");
  a.className = "artifact"; a.href = `/conversations/${conversationId}/artifact`;
  a.setAttribute("download", name);
  a.innerHTML = `<span class="ai">↓</span><span class="at"><b>${esc(name)}</b><span>Delivered file · click to download</span></span>`;
  ui.body.appendChild(a); scrollDown();
}

// report + caps
async function showReport(jobId) {
  let rec; try { rec = await getJSON(`/jobs/${jobId}`); } catch (_) { return; }
  if (rec.error) return;
  const pane = $("#reportPane"); pane.innerHTML = "";
  const r = el("div", "report");
  r.appendChild(el("h3", null, rec.status === "completed" ? "Investigation report" : `Status: ${rec.status}`));
  r.appendChild(el("div", "kv", `${rec.id} · ${rec.steps} steps · ${rec.status}`));
  const es = rec.evidence_summary || {};
  r.appendChild(el("div", "kv", `evidence — verified ${es.verified || 0} · observed ${es.observed || 0} · believed ${es.believed || 0}`));
  if (rec.usage && rec.usage.total_tokens) r.appendChild(el("div", "kv", `tokens: ${rec.usage.total_tokens}`));
  (rec.evidence || []).forEach((f) => {
    const d = el("div"); d.style.cssText = "display:flex;gap:8px;margin-top:8px;font-size:13px;align-items:flex-start";
    d.innerHTML = `<span class="tier ${f.confidence}">${f.confidence}</span><span>${esc(f.claim)}</span>`; r.appendChild(d);
  });
  r.appendChild(el("h3", null, "Conclusion")); const pre = el("pre", null, rec.final_answer || "(none)"); r.appendChild(pre);
  if (rec.error) { const e = el("div", "kv", "error: " + rec.error); e.style.color = "#ff453a"; r.appendChild(e); }
  pane.appendChild(r); openCanvas("report");
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
    (jobs || []).slice(0, 20).forEach((j) => { const it = el("div", "convo", (j.goal || "(job)").slice(0, 44)); it.title = `${j.status} · ${j.steps} steps`; it.addEventListener("click", () => showReport(j.id)); h.appendChild(it); });
  } catch (_) {}
}
loadCaps(); loadHistory();
