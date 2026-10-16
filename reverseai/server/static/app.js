"use strict";

// ---------- helpers ----------
const $ = (sel) => document.querySelector(sel);
const el = (tag, cls, txt) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (txt != null) n.textContent = txt;
  return n;
};
async function getJSON(url) { const r = await fetch(url); return r.json(); }
async function postJSON(url, body) {
  const r = await fetch(url, { method: "POST",
    headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  return { status: r.status, body: await r.json() };
}

// ---------- theme ----------
const themeBtn = $("#themeBtn");
function applyTheme(t) {
  document.documentElement.setAttribute("data-theme", t);
  try { localStorage.setItem("rvai-theme", t); } catch (_) {}
}
try { const saved = localStorage.getItem("rvai-theme"); if (saved) applyTheme(saved); } catch (_) {}
themeBtn.addEventListener("click", () => {
  const cur = document.documentElement.getAttribute("data-theme") || "auto";
  applyTheme(cur === "auto" ? "light" : cur === "light" ? "dark" : "auto");
});

// ---------- editor ----------
let editor;
window.addEventListener("load", () => {
  editor = CodeMirror.fromTextArea($("#editor"), {
    lineNumbers: true, mode: "gas", readOnly: false, lineWrapping: false,
    theme: "default",
  });
  editor.setValue("// Tool outputs (disassembly, hex, strings, file contents)\n// will load here as the agent works.\n");
});
const views = {};
function addView(key, label, content) {
  views[key] = content;
  const sel = $("#viewSelect");
  const opt = el("option", null, label);
  opt.value = key;
  sel.appendChild(opt);
  sel.value = key;
  loadView(key);
}
function loadView(key) { if (editor && views[key] != null) editor.setValue(views[key]); }
$("#viewSelect").addEventListener("change", (e) => loadView(e.target.value));

// ---------- tabs ----------
document.querySelectorAll(".tab").forEach((t) => {
  t.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((x) => x.classList.remove("active"));
    document.querySelectorAll(".pane").forEach((x) => x.classList.remove("active"));
    t.classList.add("active");
    const pane = { report: "#reportPane", editor: "#editorPane", caps: "#capsPane" }[t.dataset.pane];
    $(pane).classList.add("active");
    if (t.dataset.pane === "editor" && editor) setTimeout(() => editor.refresh(), 30);
  });
});

// ---------- capabilities ----------
async function loadCaps() {
  try {
    const caps = await getJSON("/caps");
    $("#capsPill").textContent = caps.can_run_untrusted
      ? "sandbox ready · " + (caps.bubblewrap ? "bubblewrap" : caps.qiling ? "qiling" : "container")
      : "no isolation — execution limited";
    const grid = $("#capsGrid");
    grid.innerHTML = "";
    Object.entries(caps).forEach(([k, v]) => {
      if (typeof v !== "boolean") return;
      const c = el("div", "cap" + (v ? " on" : ""));
      c.appendChild(el("span", "mk"));
      c.appendChild(el("span", null, k));
      grid.appendChild(c);
    });
  } catch (_) { $("#capsPill").textContent = "host unavailable"; }
}

// ---------- history ----------
async function loadHistory() {
  try {
    const { jobs } = await getJSON("/jobs");
    const h = $("#history");
    h.innerHTML = "";
    (jobs || []).slice(0, 12).forEach((j) => {
      const item = el("div", "hist-item", (j.goal || "(job)").slice(0, 60));
      item.title = `${j.status} · ${j.steps} steps`;
      item.addEventListener("click", () => showReport(j.id));
      h.appendChild(item);
    });
  } catch (_) {}
}

// ---------- stream ----------
const stream = $("#stream");
let source = null;
function clearStream() { stream.innerHTML = ""; }
function add(node) { node.classList.add("stream-item"); stream.appendChild(node); stream.scrollTop = stream.scrollHeight; }

function renderStep(n) { const s = el("div", "step-sep", "Step " + n); add(s); }
function renderAssistant(content, calls) {
  if (content) add(Object.assign(el("div", "assistant", content), {}));
  (calls || []).forEach((c) => {
    const d = el("div", "assistant");
    d.innerHTML = `<span class="muted">→ calling</span> <b style="font-family:var(--font-mono)">${esc(c.name)}</b>`;
    add(d);
  });
}
function renderTool(ev) {
  const wrap = el("div", "tool");
  const head = el("div", "tool-head");
  head.appendChild(el("span", "tool-name", ev.name));
  head.appendChild(el("span", "badge " + (ev.permission || "read"), ev.permission || "read"));
  head.appendChild(el("span", "badge " + (ev.ok ? "ok" : "fail"), ev.ok ? "ok" : "fail"));
  const body = el("div", "tool-body");
  const pre = el("pre", null, ev.content || "(no output)");
  body.appendChild(pre);
  body.style.display = "none";
  head.addEventListener("click", () => {
    body.style.display = body.style.display === "none" ? "block" : "none";
  });
  wrap.appendChild(head); wrap.appendChild(body);
  add(wrap);
  if (ev.content) addView("v" + Object.keys(views).length, `${ev.name}`, ev.content);
}
function renderFinding(ev) {
  const f = el("div", "finding");
  f.appendChild(el("span", "tier " + ev.tier, ev.tier));
  f.appendChild(el("span", null, ev.claim));
  add(f);
}
function esc(s) { const d = el("div"); d.textContent = s; return d.innerHTML; }

function setLive(on) {
  $("#statusDot").classList.toggle("live", on);
  $("#runBtn").disabled = on;
  $("#runBtn").textContent = on ? "Investigating…" : "Start investigation";
  $("#activityMeta").textContent = on ? "running" : "";
}

async function run() {
  const goal = $("#goal").value.trim();
  if (!goal) { $("#goal").focus(); return; }
  const payload = {
    goal,
    target: $("#target").value.trim() || null,
    project_dir: $("#project").value.trim() || null,
    provider: $("#provider").value,
    permission: $("#permission").value,
  };
  clearStream(); setLive(true);
  const { status, body } = await postJSON("/jobs/start", payload);
  if (status !== 200) {
    setLive(false);
    add(Object.assign(el("div", "assistant"), { innerHTML:
      `<span style="color:#ff453a">✗ ${esc(body.error || "failed to start")}</span>` }));
    return;
  }
  const jobId = body.job_id;
  if (source) source.close();
  source = new EventSource(`/jobs/${jobId}/events`);
  source.onmessage = (m) => {
    let ev; try { ev = JSON.parse(m.data); } catch (_) { return; }
    if (ev.type === "step") renderStep(ev.step);
    else if (ev.type === "assistant") renderAssistant(ev.content, ev.tool_calls);
    else if (ev.type === "tool_result") renderTool(ev);
    else if (ev.type === "finding") renderFinding(ev);
    else if (ev.type === "final") { source.close(); setLive(false); showReport(jobId); loadHistory(); }
    else if (ev.type === "error") {
      source.close(); setLive(false);
      add(Object.assign(el("div", "assistant"), { innerHTML:
        `<span style="color:#ff453a">✗ ${esc(ev.error)}</span>` }));
    }
  };
  source.onerror = () => { setLive(false); if (source) source.close(); };
}
$("#runBtn").addEventListener("click", run);

// ---------- report ----------
async function showReport(jobId) {
  let rec; try { rec = await getJSON(`/jobs/${jobId}`); } catch (_) { return; }
  if (rec.error) return;
  const pane = $("#reportPane");
  pane.innerHTML = "";
  const r = el("div", "report");
  r.appendChild(el("h3", null, rec.status === "completed" ? "Investigation report" : `Status: ${rec.status}`));
  r.appendChild(el("div", "kv", `job ${rec.id} · ${rec.steps} steps · ${rec.status}`));
  const es = rec.evidence_summary || {};
  r.appendChild(el("div", "kv",
    `evidence — verified ${es.verified||0} · observed ${es.observed||0} · believed ${es.believed||0}`));
  if (rec.usage && rec.usage.total_tokens)
    r.appendChild(el("div", "kv", `tokens: ${rec.usage.total_tokens}`));

  (rec.evidence || []).forEach((f) => {
    const d = el("div", "finding"); d.style.marginTop = "8px";
    d.appendChild(el("span", "tier " + f.confidence, f.confidence));
    d.appendChild(el("span", null, f.claim));
    r.appendChild(d);
  });
  const ans = el("pre", null, rec.final_answer || "(no conclusion)");
  ans.style.marginTop = "14px";
  r.appendChild(el("h3", null, "Conclusion"));
  r.appendChild(ans);
  if (rec.error) {
    const e = el("div", "kv", "error: " + rec.error); e.style.color = "#ff453a"; r.appendChild(e);
  }
  pane.appendChild(r);
  // switch to report tab
  document.querySelector('.tab[data-pane="report"]').click();
}

// ---------- boot ----------
loadCaps();
loadHistory();
