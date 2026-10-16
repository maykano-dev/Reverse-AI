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
let editor; const views = {};
window.addEventListener("load", () => {
  editor = CodeMirror.fromTextArea($("#editor"), { lineNumbers: true, mode: "gas", lineWrapping: false });
  editor.setValue("// Tool outputs (disassembly, hex, strings, files) load here.\n");
});
function addView(label, content) {
  const key = "v" + Object.keys(views).length; views[key] = content;
  const sel = $("#viewSelect"); const o = el("option", null, label); o.value = key; sel.appendChild(o);
  return key;
}
function showView(key) { if (editor && views[key] != null) { openCanvas("editor"); $("#viewSelect").value = key; editor.setValue(views[key]); setTimeout(() => editor.refresh(), 30); } }
$("#viewSelect").addEventListener("change", (e) => showView(e.target.value));
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

// composer autosize
const input = $("#input");
input.addEventListener("input", () => { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 200) + "px"; });
input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); if (!busy) send(); } });
$("#send").addEventListener("click", () => { if (busy) stopRun(); else send(); });
let currentSrc = null, currentUI = null;
function stopRun() { if (currentSrc) currentSrc.close(); if (currentUI) finishError(currentUI, "stopped"); }
$("#newChat").addEventListener("click", newChat);
document.querySelectorAll(".chip").forEach((c) => c.addEventListener("click", () => { input.value = c.dataset.g; input.focus(); input.dispatchEvent(new Event("input")); }));

const thread = $("#thread"); const inner = $("#threadInner");
let busy = false;
function scrollDown() { thread.scrollTop = thread.scrollHeight; }
function removeWelcome() { const w = $("#welcome"); if (w) w.remove(); }

function newChat() {
  inner.innerHTML = "";
  const w = el("div", "welcome"); w.id = "welcome";
  w.innerHTML = `<div class="big">✦</div><h1>What should we reverse-engineer?</h1>
    <p>Hand me a binary (Windows PE, Linux ELF, or macOS/iOS Mach-O) and a goal. I'll investigate it, work in an isolated sandbox, and show you every step.</p>`;
  inner.appendChild(w);
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
  const payload = { goal, target: $("#target").value.trim() || null, provider: $("#provider").value, permission: $("#permission").value };
  const ui = aiTurn(); currentUI = ui;

  const { status, body } = await postJSON("/jobs/start", payload);
  if (status !== 200) { finishError(ui, body.error || "failed to start"); return; }
  const jobId = body.job_id;
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
    else if (ev.type === "final") { src.close(); finishFinal(ui, jobId, ev, steps); }
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
function done() { setBusy(false); currentSrc = null; currentUI = null; }

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
