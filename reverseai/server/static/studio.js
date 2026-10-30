"use strict";
/* ReverseAI Studio — edit a generated deck, document, or sheet in the app,
   re-render it to a real file, export to other formats, and present.
   Shares helpers ($, el, esc, ic, withToken, getJSON, postJSON, send,
   openCanvas, conversationId, renderIcons) with app.js (same global scope). */

let studio = null; // { cid, filename, kind, name, spec, active }

function stToast(msg, kind) {
  let host = $("#stToastHost");
  if (!host) {
    host = el("div", "st-toast-host");
    host.id = "stToastHost";
    document.body.appendChild(host);
  }
  const t = el("div", "st-toast" + (kind ? " " + kind : ""), msg);
  host.appendChild(t);
  requestAnimationFrame(() => t.classList.add("in"));
  setTimeout(() => { t.classList.remove("in"); setTimeout(() => t.remove(), 300); }, 2600);
}

async function openStudio(cid, filename) {
  const pane = $("#studioPane");
  $("#studioTab").style.display = "";
  openCanvas("studio");
  pane.innerHTML = `<div class="st-loading">${ic("layout", 22)}<span>Opening ${esc(filename)}…</span></div>`;
  renderIcons(pane);
  try {
    const data = await getJSON(`/studio/${cid}/${encodeURIComponent(filename)}`);
    studio = {
      cid, filename, kind: data.kind, name: data.name || filename,
      spec: data.spec || {}, active: 0,
    };
    renderStudio();
  } catch (e) {
    pane.innerHTML = `<div class="st-empty"><div class="ce-big" data-icon="alert" data-size="26"></div>
      <p>Could not open this file for editing.</p><span class="st-sub">${esc(e.message || "")}</span></div>`;
    renderIcons(pane);
  }
}

function stKind() { return studio ? studio.kind : ""; }
function isDeck() { return stKind() === "pptx"; }
function isSheet() { return stKind() === "xlsx" || stKind() === "csv"; }

// --- shell ----------------------------------------------------------------
function renderStudio() {
  const pane = $("#studioPane");
  pane.innerHTML = "";
  const bar = el("div", "st-bar");
  const kindLabel = { pptx: "Presentation", docx: "Document", pdf: "PDF",
    md: "Markdown", html: "Web page", xlsx: "Spreadsheet", txt: "Text" }[studio.kind]
    || studio.kind.toUpperCase();
  bar.innerHTML = `<span class="st-file">${ic(isDeck() ? "layout" : "file", 16)}
      <b>${esc(studio.filename)}</b><span class="st-kind">${kindLabel}</span></span>
    <span class="st-saved" id="stSaved"></span>
    <span class="st-grow"></span>`;
  const actions = el("div", "st-actions");
  if (isDeck()) {
    const present = el("button", "st-btn", "");
    present.innerHTML = `${ic("present", 15)}<span>Present</span>`;
    present.addEventListener("click", startPresent);
    actions.appendChild(present);
  }
  const save = el("button", "st-btn st-btn-primary");
  save.id = "stSaveBtn";
  save.innerHTML = `${ic("check", 15)}<span>Save</span>`;
  save.addEventListener("click", () => saveStudio());
  actions.appendChild(save);

  const exportWrap = el("div", "st-export");
  const exBtn = el("button", "st-btn");
  exBtn.innerHTML = `${ic("download", 15)}<span>Export</span>${ic("chevronDown", 12)}`;
  const menu = el("div", "st-export-menu");
  const formats = isDeck() ? [["pptx", "PowerPoint (.pptx)"], ["pdf", "PDF (.pdf)"]]
    : isSheet() ? [[studio.kind, studio.kind.toUpperCase()], ["csv", "CSV (.csv)"]]
    : [[studio.kind, studio.kind.toUpperCase() + " (." + studio.kind + ")"],
       ["pdf", "PDF (.pdf)"], ["docx", "Word (.docx)"], ["md", "Markdown (.md)"]];
  const seen = new Set();
  formats.forEach(([fmt, lbl]) => {
    if (seen.has(fmt)) return; seen.add(fmt);
    const o = el("button", "st-export-opt", lbl);
    o.addEventListener("click", () => { menu.classList.remove("open"); exportAs(fmt); });
    menu.appendChild(o);
  });
  exBtn.addEventListener("click", (e) => { e.stopPropagation(); menu.classList.toggle("open"); });
  document.addEventListener("click", () => menu.classList.remove("open"));
  exportWrap.appendChild(exBtn);
  exportWrap.appendChild(menu);
  actions.appendChild(exportWrap);
  bar.appendChild(actions);
  pane.appendChild(bar);

  const body = el("div", "st-work");
  pane.appendChild(body);
  if (isDeck()) renderDeck(body);
  else if (isSheet()) renderSheet(body);
  else renderDoc(body);

  renderAskBar(pane);
  renderIcons(pane);
}

function renderAskBar(pane) {
  const ask = el("div", "st-ask");
  ask.innerHTML = `<span class="st-ask-ic">${ic("sparkle", 15)}</span>`;
  const inp = el("input", "st-ask-input");
  inp.placeholder = isDeck() ? "Ask to change this deck: \"add a slide on pricing\"…"
    : "Ask to change this file…";
  const go = el("button", "st-ask-go", "Ask");
  const fire = () => {
    const t = inp.value.trim();
    if (!t) return;
    if (typeof busy !== "undefined" && busy) { stToast("Finish the current turn first.", "warn"); return; }
    inp.value = "";
    stToast("Asked. Save your manual edits first if you made any.", "");
    send(`Update the file ${studio.filename}: ${t}`);
  };
  go.addEventListener("click", fire);
  inp.addEventListener("keydown", (e) => { if (e.key === "Enter") fire(); });
  ask.appendChild(inp);
  ask.appendChild(go);
  pane.appendChild(ask);
}

function markDirty() {
  const s = $("#stSaved");
  if (s) { s.textContent = "Unsaved changes"; s.className = "st-saved dirty"; }
}
function markSaved() {
  const s = $("#stSaved");
  if (s) { s.textContent = "Saved"; s.className = "st-saved ok"; }
}

// --- deck editor ----------------------------------------------------------
// Mirror of the server-side theme presets so the editor previews real colors.
const STUDIO_PALETTE = {
  light:    { bg: "FFFFFF", surface: "F3F5F9", ink: "16181D", muted: "5C6672", accent: "2D6CDF", accent2: "7C5CFF", on_accent: "FFFFFF" },
  slate:    { bg: "F7F8FA", surface: "FFFFFF", ink: "1B2230", muted: "5A6676", accent: "4457F2", accent2: "12B5A5", on_accent: "FFFFFF" },
  midnight: { bg: "0E1526", surface: "18233E", ink: "EEF3FF", muted: "9DB2D6", accent: "4F8CFF", accent2: "C98BFF", on_accent: "FFFFFF" },
  aurora:   { bg: "07121A", surface: "0E2230", ink: "EAFBFF", muted: "8FC7D6", accent: "2AD6B5", accent2: "4FA6FF", on_accent: "04221C" },
  sunset:   { bg: "1C1020", surface: "2C1630", ink: "FFF0EC", muted: "E3A6B8", accent: "FF6B4A", accent2: "FFB24A", on_accent: "2A0C08" },
  forest:   { bg: "0C1A12", surface: "12271B", ink: "ECFBEF", muted: "97C4A6", accent: "35C06A", accent2: "9BD94F", on_accent: "05240F" },
  mono:     { bg: "121316", surface: "1D1F24", ink: "F4F5F7", muted: "A2A7B0", accent: "E8EAED", accent2: "9AA0AA", on_accent: "121316" },
  ocean:    { bg: "F4F8FB", surface: "FFFFFF", ink: "0B2B3A", muted: "4A7084", accent: "0E7FB5", accent2: "12B5A5", on_accent: "FFFFFF" },
  coral:    { bg: "FFF7F3", surface: "FFFFFF", ink: "3A1A14", muted: "8A5A4E", accent: "E8553B", accent2: "F2A03D", on_accent: "FFFFFF" },
  paper:    { bg: "F6F1E7", surface: "FFFDF8", ink: "2A2114", muted: "6B5E49", accent: "9A5B2E", accent2: "4E7A4C", on_accent: "FFFDF8" },
  grape:    { bg: "150E24", surface: "241A3C", ink: "F3EEFF", muted: "B4A3D6", accent: "A06BFF", accent2: "FF7AC2", on_accent: "FFFFFF" },
  ember:    { bg: "1A1310", surface: "2A1E18", ink: "FFF2EC", muted: "D0A694", accent: "FF7A2F", accent2: "FFC24A", on_accent: "2A0C04" },
  steel:    { bg: "0F1620", surface: "1A2531", ink: "EAF1F8", muted: "9BB0C2", accent: "5BA3D0", accent2: "7FD1C1", on_accent: "051018" },
  rose:     { bg: "FBF4F6", surface: "FFFFFF", ink: "34121E", muted: "8A5566", accent: "D23D74", accent2: "8A5BF2", on_accent: "FFFFFF" },
};
const STUDIO_THEMES = ["light", "slate", "midnight", "aurora", "sunset", "forest", "mono",
  "ocean", "coral", "paper", "grape", "ember", "steel", "rose"];
const STUDIO_LAYOUTS = ["cover", "content", "two-column", "section", "quote", "statement", "image", "diagram", "cards"];

function normHex(c) { return String(c || "").replace(/^#/, "").toUpperCase(); }
function deckTheme() {
  const th = studio.spec.theme;
  if (typeof th === "string") return STUDIO_PALETTE[th.toLowerCase()] || STUDIO_PALETTE.light;
  if (th && typeof th === "object") {
    const base = Object.assign({}, STUDIO_PALETTE[(th.preset || "").toLowerCase()] || STUDIO_PALETTE.light);
    ["bg", "surface", "ink", "muted", "accent", "on_accent"].forEach((k) => {
      if (th[k]) base[k] = normHex(th[k]);
    });
    return base;
  }
  return STUDIO_PALETTE.light;
}
function currentThemeName() {
  const th = studio.spec.theme;
  if (typeof th === "string") return th.toLowerCase();
  if (th && typeof th === "object" && th.preset) return String(th.preset).toLowerCase();
  return "light";
}
function slideLayout(s) {
  if (s.layout) return s.layout.toLowerCase();
  if (s.cards && s.cards.length) return "cards";
  if ((s.shapes && s.shapes.length) || (s.steps && s.steps.length)) return "diagram";
  if (s.quote) return "quote";
  if ((s.svg || s.chart || s.image || s.image_data) && !(s.bullets && s.bullets.length)) return "image";
  if (s.columns && s.columns.length) return "two-column";
  if (!(s.bullets && s.bullets.length) && s.subtitle) return "cover";
  return "content";
}

function deckSlides() {
  if (!Array.isArray(studio.spec.slides)) studio.spec.slides = [];
  if (!studio.spec.slides.length) studio.spec.slides.push({ title: "", subtitle: "", bullets: [] });
  return studio.spec.slides;
}

function renderDeck(body) {
  body.classList.add("st-deck");
  const rail = el("div", "st-rail");
  rail.id = "stRail";
  const stage = el("div", "st-stage");
  stage.id = "stStage";
  // theme picker at the top of the rail
  const themeRow = el("div", "st-theme-row");
  themeRow.innerHTML = `<span class="st-theme-label">Theme</span>`;
  const sel = el("select", "st-theme-sel");
  STUDIO_THEMES.forEach((name) => {
    const o = el("option", null, name.charAt(0).toUpperCase() + name.slice(1));
    o.value = name;
    sel.appendChild(o);
  });
  sel.value = currentThemeName();
  sel.addEventListener("change", () => {
    syncDeckFromDom();
    studio.spec.theme = sel.value;
    renderRail(); renderStage(); markDirty();
  });
  themeRow.appendChild(sel);
  rail.appendChild(themeRow);
  body.appendChild(rail);
  body.appendChild(stage);
  const addBtn = el("button", "st-rail-add");
  addBtn.innerHTML = `${ic("plus", 15)}<span>Add slide</span>`;
  addBtn.addEventListener("click", () => {
    syncDeckFromDom();
    deckSlides().splice(studio.active + 1, 0, { title: "", subtitle: "", bullets: [] });
    studio.active += 1;
    renderRail(); renderStage(); markDirty();
  });
  rail.appendChild(addBtn);
  renderRail();
  renderStage();
}

function renderRail() {
  const rail = $("#stRail");
  if (!rail) return;
  rail.querySelectorAll(".st-thumb").forEach((n) => n.remove());
  const slides = deckSlides();
  const pal = deckTheme();
  const addBtn = rail.querySelector(".st-rail-add");
  slides.forEach((s, i) => {
    const layout = slideLayout(s);
    const isSection = layout === "section";
    const bg = s.bg ? normHex(s.bg) : (isSection ? pal.accent : pal.bg);
    const ink = isSection ? pal.on_accent : pal.ink;
    const accent = s.accent ? normHex(s.accent) : pal.accent;
    const th = el("div", "st-thumb" + (i === studio.active ? " active" : ""));
    const mini = el("div", "st-thumb-mini");
    mini.style.background = "#" + bg;
    const label = s.title || s.quote || (layout.charAt(0).toUpperCase() + layout.slice(1));
    const lines = (s.bullets || (s.columns || []).flat() || []);
    mini.innerHTML = `<div class="st-thumb-t" style="color:#${ink}">${esc(label)}</div>` +
      (lines.length ? `<div class="st-thumb-lines">${
        lines.slice(0, 4).map(() => `<i style="background:#${accent}"></i>`).join("")}</div>` : "");
    th.appendChild(el("span", "st-thumb-n", String(i + 1)));
    th.appendChild(mini);
    th.addEventListener("click", () => {
      syncDeckFromDom(); studio.active = i; renderRail(); renderStage();
    });
    rail.insertBefore(th, addBtn);
  });
}

function editable(tag, cls, text, ph) {
  const n = el(tag, cls);
  n.contentEditable = "true";
  n.spellcheck = false;
  if (text) n.textContent = text;
  if (ph) n.dataset.ph = ph;
  n.addEventListener("input", markDirty);
  return n;
}

function addPointBtn(container, label) {
  const b = el("button", "st-add-bullet");
  b.innerHTML = `${ic("plus", 13)}<span>${label || "Add point"}</span>`;
  b.addEventListener("click", () => {
    const row = bulletRow("");
    container.appendChild(row);
    const ed = row.querySelector(".st-bullet-text");
    if (ed) ed.focus();
    markDirty();
  });
  return b;
}

function renderStage() {
  const stage = $("#stStage");
  if (!stage) return;
  const slides = deckSlides();
  studio.active = Math.max(0, Math.min(studio.active, slides.length - 1));
  const s = slides[studio.active];
  const pal = deckTheme();
  const layout = slideLayout(s);
  const isSection = layout === "section";
  stage.innerHTML = "";

  const tools = el("div", "st-stage-tools");
  // layout picker
  const lsel = el("select", "st-layout-sel");
  lsel.title = "Slide layout";
  STUDIO_LAYOUTS.forEach((name) => {
    const o = el("option", null, name.replace("-", " "));
    o.value = name;
    lsel.appendChild(o);
  });
  lsel.value = layout;
  lsel.addEventListener("change", () => {
    syncDeckFromDom();
    s.layout = lsel.value;
    renderRail(); renderStage(); markDirty();
  });
  tools.appendChild(lsel);
  const mk = (icon, label, fn, danger) => {
    const b = el("button", "st-tool" + (danger ? " danger" : ""));
    b.title = label; b.setAttribute("aria-label", label);
    b.innerHTML = ic(icon, 15);
    b.addEventListener("click", fn);
    return b;
  };
  tools.appendChild(mk("chevronLeft", "Move slide up", () => moveSlide(-1)));
  tools.appendChild(mk("chevronRight", "Move slide down", () => moveSlide(1)));
  tools.appendChild(mk("copy", "Duplicate slide", duplicateSlide));
  tools.appendChild(mk("trash", "Delete slide", deleteSlide, true));
  stage.appendChild(tools);

  const card = el("div", "st-slide st-layout-" + layout);
  const bg = s.bg ? normHex(s.bg) : (isSection ? pal.accent : pal.bg);
  const accent = s.accent ? normHex(s.accent) : pal.accent;
  const ink = isSection ? pal.on_accent : pal.ink;
  const muted = isSection ? pal.on_accent : pal.muted;
  card.style.background = "#" + bg;
  card.style.setProperty("--st-ink", "#" + ink);
  card.style.setProperty("--st-muted", "#" + muted);
  card.style.setProperty("--st-accent", "#" + accent);

  const title = editable("h2", "st-slide-title", s.title || "", "Slide title");

  if (layout === "quote") {
    const q = editable("div", "st-slide-quote", s.quote || s.title || "", "Quote");
    const attr = editable("div", "st-slide-attr", s.attribution || "", "Attribution (optional)");
    card.appendChild(el("div", "st-quote-mark", "“"));
    card.appendChild(q);
    card.appendChild(attr);
  } else if (layout === "cover" || layout === "section" || layout === "statement") {
    card.appendChild(title);
    card.appendChild(editable("div", "st-slide-sub", s.subtitle || "", "Subtitle (optional)"));
  } else if (layout === "two-column") {
    card.appendChild(title);
    const cols = el("div", "st-cols");
    const data = (s.columns && s.columns.length) ? s.columns.slice(0, 2) : [[], []];
    while (data.length < 2) data.push([]);
    data.forEach((col) => {
      const colEl = el("div", "st-col");
      const list = el("div", "st-slide-bullets");
      (col || []).forEach((b) => list.appendChild(bulletRow(b)));
      colEl.appendChild(list);
      colEl.appendChild(addPointBtn(list));
      cols.appendChild(colEl);
    });
    card.appendChild(cols);
  } else if (layout === "image") {
    card.appendChild(title);
    const holder = el("div", "st-img-holder");
    const refreshImg = () => {
      holder.innerHTML = "";
      if (s.image) {
        const img = el("img", "st-img-preview");
        img.src = withToken(`/preview/${studio.cid}/${s.image}`);
        img.alt = "slide image";
        holder.appendChild(img);
      } else {
        const note = el("div", "st-img-note");
        note.innerHTML = `${ic("file", 15)}<span>No image yet. Upload one, or ask the AI to add one below.</span>`;
        holder.appendChild(note);
      }
      const up = el("button", "st-img-btn");
      up.innerHTML = `${ic("plus", 13)}<span>${s.image ? "Replace image" : "Upload image"}</span>`;
      up.addEventListener("click", () => pickStudioImage((b) => {
        s.image = b.src; s.image_w = b.width; s.image_h = b.height; delete s.image_data;
        refreshImg(); renderRail(); markDirty();
      }));
      holder.appendChild(up);
    };
    refreshImg();
    card.appendChild(holder);
  } else if (layout === "diagram") {
    card.appendChild(title);
    if (!Array.isArray(s.shapes)) s.shapes = [];
    const canvas = el("div", "st-diag-canvas");
    canvas.id = "stDiag";
    const tools = el("div", "st-diag-tools");
    const boxCount = () => s.shapes.filter((x) => x && /^(rect|roundrect|ellipse)$/i.test(x.type || "rect")).length;
    const addBox = el("button", "st-diag-btn");
    addBox.innerHTML = `${ic("plus", 13)}<span>Box</span>`;
    addBox.addEventListener("click", () => {
      const n = boxCount();
      s.shapes.push({ type: "roundrect", x: 8 + (n % 3) * 30, y: 20 + Math.floor(n / 3) * 26,
        w: 24, h: 18, color: DIAG_COLORS[n % DIAG_COLORS.length], text: "Label", text_color: "FFFFFF" });
      renderDiagramEditor(canvas, s); markDirty();
    });
    const addArrow = el("button", "st-diag-btn");
    addArrow.innerHTML = `${ic("plus", 13)}<span>Arrow</span>`;
    addArrow.addEventListener("click", () => {
      s.shapes.push({ type: "arrow", x: 20, y: 72, x2: 55, y2: 72, color: normHex(ink) });
      renderDiagramEditor(canvas, s); markDirty();
    });
    const addText = el("button", "st-diag-btn");
    addText.innerHTML = `${ic("plus", 13)}<span>Text</span>`;
    addText.addEventListener("click", () => {
      s.shapes.push({ type: "text", x: 10, y: 15, w: 40, text: "Caption", color: normHex(ink) });
      renderDiagramEditor(canvas, s, accent); markDirty();
    });
    tools.appendChild(addBox); tools.appendChild(addArrow); tools.appendChild(addText);
    card.appendChild(canvas);
    card.appendChild(tools);
    renderDiagramEditor(canvas, s, accent);
  } else {
    // content
    card.appendChild(title);
    card.appendChild(editable("div", "st-slide-sub", s.subtitle || "", "Subtitle (optional)"));
    const bullets = el("div", "st-slide-bullets");
    bullets.id = "stBullets";
    (s.bullets || []).forEach((b) => bullets.appendChild(bulletRow(b)));
    card.appendChild(bullets);
    const actionsRow = el("div", "st-content-actions");
    actionsRow.appendChild(addPointBtn(bullets));
    const imgBtn = el("div", "st-content-img");
    const refreshCImg = () => {
      imgBtn.innerHTML = "";
      if (s.image) {
        const img = el("img", "st-img-thumb");
        img.src = withToken(`/preview/${studio.cid}/${s.image}`);
        imgBtn.appendChild(img);
        const rm = el("button", "st-add-bullet");
        rm.innerHTML = `${ic("x", 12)}<span>Remove image</span>`;
        rm.addEventListener("click", () => {
          delete s.image; delete s.image_w; delete s.image_h; delete s.image_data;
          refreshCImg(); renderRail(); markDirty();
        });
        imgBtn.appendChild(rm);
      } else {
        const add = el("button", "st-add-bullet");
        add.innerHTML = `${ic("plus", 13)}<span>Add image</span>`;
        add.addEventListener("click", () => pickStudioImage((b) => {
          s.image = b.src; s.image_w = b.width; s.image_h = b.height;
          refreshCImg(); renderRail(); markDirty();
        }));
        imgBtn.appendChild(add);
      }
    };
    refreshCImg();
    actionsRow.appendChild(imgBtn);
    card.appendChild(actionsRow);
  }
  stage.appendChild(card);
}

function bulletRow(text) {
  const row = el("div", "st-bullet");
  row.innerHTML = `<span class="st-bullet-dot"></span>`;
  const ed = editable("div", "st-bullet-text", text, "Point");
  ed.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      const row2 = bulletRow("");
      row.after(row2);
      row2.querySelector(".st-bullet-text").focus();
      markDirty();
    } else if (e.key === "Backspace" && !ed.textContent) {
      e.preventDefault();
      const prev = row.previousElementSibling;
      row.remove();
      if (prev && prev.querySelector) {
        const p = prev.querySelector(".st-bullet-text");
        if (p) { p.focus(); placeCaretEnd(p); }
      }
      markDirty();
    }
  });
  const del = el("button", "st-bullet-x");
  del.innerHTML = ic("x", 12);
  del.title = "Remove point";
  del.addEventListener("click", () => { row.remove(); markDirty(); });
  row.appendChild(ed);
  row.appendChild(del);
  return row;
}

function placeCaretEnd(node) {
  try {
    const r = document.createRange();
    r.selectNodeContents(node); r.collapse(false);
    const sel = window.getSelection();
    sel.removeAllRanges(); sel.addRange(r);
  } catch (_) {}
}

// Upload an image into the conversation's assets and return {src,width,height}.
function pickStudioImage(onDone) {
  const inp = document.createElement("input");
  inp.type = "file";
  inp.accept = "image/png,image/jpeg";
  inp.addEventListener("change", async () => {
    const file = inp.files && inp.files[0];
    if (!file) return;
    stToast("Uploading image…", "");
    try {
      const r = await api(`/studio/${studio.cid}/${encodeURIComponent(studio.filename)}/image`, {
        method: "PUT",
        headers: { "X-Filename": file.name, "Content-Type": file.type || "application/octet-stream" },
        body: file,
      });
      const b = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(b.error || "upload failed");
      stToast("Image added. Save to update the file.", "ok");
      onDone(b);
    } catch (e) {
      stToast(e.message || "Upload failed", "warn");
    }
  });
  inp.click();
}

// --- visual diagram editor ------------------------------------------------
const DIAG_COLORS = ["2D6CDF", "12B5A5", "35C06A", "FF9F0A", "FF375F", "7C5CFF", "E8560A", "5A6676"];
function nextDiagColor(cur) {
  const i = DIAG_COLORS.indexOf(normHex(cur));
  return DIAG_COLORS[(i + 1) % DIAG_COLORS.length];
}
function dragPercent(node, rectFn, onMove) {
  node.addEventListener("mousedown", (e) => {
    if (e.target.closest(".st-diag-ctl, .st-diag-handle, [contenteditable]")) return;
    e.preventDefault();
    let px = e.clientX, py = e.clientY;
    const rect = rectFn();
    const move = (ev) => {
      onMove((ev.clientX - px) / rect.width * 100, (ev.clientY - py) / rect.height * 100);
      px = ev.clientX; py = ev.clientY;
    };
    const up = () => {
      document.removeEventListener("mousemove", move);
      document.removeEventListener("mouseup", up);
      markDirty();
    };
    document.addEventListener("mousemove", move);
    document.addEventListener("mouseup", up);
  });
}
function renderDiagramEditor(canvas, slide) {
  canvas.innerHTML = "";
  const shapes = slide.shapes || [];
  const NS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("class", "st-diag-svg");
  svg.setAttribute("viewBox", "0 0 100 100");
  svg.setAttribute("preserveAspectRatio", "none");
  const defs = document.createElementNS(NS, "defs");
  defs.innerHTML = '<marker id="stArrow" markerWidth="6" markerHeight="6" refX="4.5" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 z" fill="context-stroke"/></marker>';
  svg.appendChild(defs);
  canvas.appendChild(svg);
  const rectFn = () => canvas.getBoundingClientRect();

  shapes.forEach((sh, idx) => {
    if (!sh || typeof sh !== "object") return;
    const kind = String(sh.type || "rect").toLowerCase();
    if (kind === "arrow" || kind === "line") {
      diagArrow(svg, canvas, slide, sh, idx, rectFn);
    } else {
      diagBox(canvas, slide, sh, idx, kind, rectFn);
    }
  });
}
function diagBox(canvas, slide, sh, idx, kind, rectFn) {
  const box = el("div", "st-diag-box" + (kind === "ellipse" ? " ellipse" : "") + (kind === "text" ? " textonly" : ""));
  box.style.left = (sh.x || 0) + "%";
  box.style.top = (sh.y || 0) + "%";
  box.style.width = (sh.w || 24) + "%";
  if (kind !== "text") {
    box.style.height = (sh.h || 18) + "%";
    box.style.background = "#" + (sh.color ? normHex(sh.color) : "2D6CDF");
  }
  const tc = kind === "text"
    ? (sh.color ? normHex(sh.color) : "111111")
    : (sh.text_color ? normHex(sh.text_color) : "FFFFFF");
  const txt = el("div", "st-diag-text");
  txt.contentEditable = "true";
  txt.spellcheck = false;
  txt.textContent = sh.text || "";
  txt.style.color = "#" + tc;
  txt.addEventListener("input", () => { sh.text = txt.textContent; markDirty(); });
  box.appendChild(txt);
  const del = el("button", "st-diag-ctl del");
  del.innerHTML = ic("x", 11);
  del.title = "Delete";
  del.addEventListener("click", () => { slide.shapes.splice(idx, 1); renderDiagramEditor(canvas, slide); markDirty(); });
  box.appendChild(del);
  if (kind !== "text") {
    const col = el("button", "st-diag-ctl col");
    col.title = "Color";
    col.style.background = "#" + (sh.color ? normHex(sh.color) : "2D6CDF");
    col.addEventListener("click", () => { sh.color = nextDiagColor(sh.color); renderDiagramEditor(canvas, slide); markDirty(); });
    box.appendChild(col);
    const h = el("div", "st-diag-handle");
    h.addEventListener("mousedown", (e) => {
      e.preventDefault(); e.stopPropagation();
      let px = e.clientX, py = e.clientY;
      const rect = rectFn();
      const move = (ev) => {
        sh.w = Math.max(6, (sh.w || 24) + (ev.clientX - px) / rect.width * 100);
        sh.h = Math.max(5, (sh.h || 18) + (ev.clientY - py) / rect.height * 100);
        box.style.width = sh.w + "%"; box.style.height = sh.h + "%";
        px = ev.clientX; py = ev.clientY;
      };
      const up = () => { document.removeEventListener("mousemove", move); document.removeEventListener("mouseup", up); markDirty(); };
      document.addEventListener("mousemove", move);
      document.addEventListener("mouseup", up);
    });
    box.appendChild(h);
  }
  dragPercent(box, rectFn, (dx, dy) => {
    sh.x = Math.max(0, Math.min(98, (sh.x || 0) + dx));
    sh.y = Math.max(0, Math.min(98, (sh.y || 0) + dy));
    box.style.left = sh.x + "%"; box.style.top = sh.y + "%";
  });
  canvas.appendChild(box);
}
function diagArrow(svg, canvas, slide, sh, idx, rectFn) {
  const NS = "http://www.w3.org/2000/svg";
  const col = "#" + (sh.color ? normHex(sh.color) : "5A6676");
  const line = document.createElementNS(NS, "line");
  const setLine = () => {
    line.setAttribute("x1", sh.x || 0); line.setAttribute("y1", sh.y || 0);
    line.setAttribute("x2", sh.x2 || 0); line.setAttribute("y2", sh.y2 || 0);
  };
  line.setAttribute("stroke", col);
  line.setAttribute("stroke-width", "0.9");
  if (String(sh.type).toLowerCase() === "arrow") line.setAttribute("marker-end", "url(#stArrow)");
  setLine();
  svg.appendChild(line);
  const endpoint = (xk, yk) => {
    const hd = el("div", "st-diag-end");
    const place = () => { hd.style.left = (sh[xk] || 0) + "%"; hd.style.top = (sh[yk] || 0) + "%"; };
    place();
    hd.addEventListener("mousedown", (e) => {
      e.preventDefault(); e.stopPropagation();
      const rect = rectFn();
      const move = (ev) => {
        sh[xk] = Math.max(0, Math.min(100, (ev.clientX - rect.left) / rect.width * 100));
        sh[yk] = Math.max(0, Math.min(100, (ev.clientY - rect.top) / rect.height * 100));
        setLine(); place();
      };
      const up = () => { document.removeEventListener("mousemove", move); document.removeEventListener("mouseup", up); markDirty(); };
      document.addEventListener("mousemove", move);
      document.addEventListener("mouseup", up);
    });
    canvas.appendChild(hd);
  };
  endpoint("x", "y"); endpoint("x2", "y2");
  const del = el("button", "st-diag-ctl del endpt");
  del.innerHTML = ic("x", 11);
  del.title = "Delete arrow";
  del.style.left = (((sh.x || 0) + (sh.x2 || 0)) / 2) + "%";
  del.style.top = (((sh.y || 0) + (sh.y2 || 0)) / 2) + "%";
  del.addEventListener("click", () => { slide.shapes.splice(idx, 1); renderDiagramEditor(canvas, slide); markDirty(); });
  canvas.appendChild(del);
}

function syncDeckFromDom() {
  const stage = $("#stStage");
  if (!stage || !isDeck()) return;
  const s = deckSlides()[studio.active];
  if (!s) return;
  const t = stage.querySelector(".st-slide-title");
  const sub = stage.querySelector(".st-slide-sub");
  if (t) s.title = t.textContent.trim();
  if (sub) s.subtitle = sub.textContent.trim();
  const q = stage.querySelector(".st-slide-quote");
  const attr = stage.querySelector(".st-slide-attr");
  if (q) s.quote = q.textContent.trim();
  if (attr) s.attribution = attr.textContent.trim();
  const cols = stage.querySelectorAll(".st-col");
  if (cols.length) {
    s.columns = Array.from(cols).map((c) =>
      Array.from(c.querySelectorAll(".st-bullet-text"))
        .map((n) => n.textContent.trim()).filter(Boolean));
  } else {
    // single bullet list (content): read only the main list
    const list = stage.querySelector("#stBullets");
    if (list) {
      s.bullets = Array.from(list.querySelectorAll(".st-bullet-text"))
        .map((n) => n.textContent.trim()).filter(Boolean);
    }
  }
}

function moveSlide(dir) {
  syncDeckFromDom();
  const slides = deckSlides();
  const j = studio.active + dir;
  if (j < 0 || j >= slides.length) return;
  const [m] = slides.splice(studio.active, 1);
  slides.splice(j, 0, m);
  studio.active = j;
  renderRail(); renderStage(); markDirty();
}
function duplicateSlide() {
  syncDeckFromDom();
  const slides = deckSlides();
  const copy = JSON.parse(JSON.stringify(slides[studio.active]));
  slides.splice(studio.active + 1, 0, copy);
  studio.active += 1;
  renderRail(); renderStage(); markDirty();
}
function deleteSlide() {
  const slides = deckSlides();
  if (slides.length <= 1) { stToast("A deck needs at least one slide.", "warn"); return; }
  slides.splice(studio.active, 1);
  studio.active = Math.max(0, studio.active - 1);
  renderRail(); renderStage(); markDirty();
}

// --- document editor ------------------------------------------------------
function docBlocks() {
  if (!Array.isArray(studio.spec.blocks)) studio.spec.blocks = [];
  return studio.spec.blocks;
}
function renderDoc(body) {
  body.classList.add("st-doc");
  const page = el("div", "st-page");
  const title = editable("h1", "st-doc-title", studio.spec.title || "", "Title");
  const sub = editable("div", "st-doc-sub", studio.spec.subtitle || "", "Subtitle (optional)");
  page.appendChild(title);
  page.appendChild(sub);
  const list = el("div", "st-blocks");
  list.id = "stBlocks";
  docBlocks().forEach((b) => list.appendChild(blockRow(b)));
  page.appendChild(list);
  const addbar = el("div", "st-addbar");
  [["heading", "Heading"], ["paragraph", "Paragraph"], ["bullet", "Bullet"]].forEach(([type, lbl]) => {
    const b = el("button", "st-add", "");
    b.innerHTML = `${ic("plus", 13)}<span>${lbl}</span>`;
    b.addEventListener("click", () => {
      const row = blockRow({ type, text: "" });
      list.appendChild(row);
      const ed = row.querySelector(".st-block-text"); if (ed) ed.focus();
      markDirty();
    });
    addbar.appendChild(b);
  });
  page.appendChild(addbar);
  body.appendChild(page);
}
function blockRow(b) {
  const type = b.type || "paragraph";
  const row = el("div", "st-block st-block-" + type);
  row.dataset.type = type;
  const tag = type === "heading" ? "h3" : "div";
  const ed = editable(tag, "st-block-text", b.text || "",
    type === "heading" ? "Heading" : type === "bullet" ? "Bullet point" : "Write…");
  if (type === "bullet") row.appendChild(el("span", "st-bullet-dot"));
  row.appendChild(ed);
  const del = el("button", "st-bullet-x");
  del.innerHTML = ic("x", 12); del.title = "Remove";
  del.addEventListener("click", () => { row.remove(); markDirty(); });
  row.appendChild(del);
  return row;
}
function syncDocFromDom() {
  const page = $("#studioPane .st-page");
  if (!page) return;
  const t = page.querySelector(".st-doc-title");
  const sub = page.querySelector(".st-doc-sub");
  studio.spec.title = t ? t.textContent.trim() : "";
  studio.spec.subtitle = sub ? sub.textContent.trim() : "";
  studio.spec.blocks = Array.from(page.querySelectorAll(".st-block")).map((r) => ({
    type: r.dataset.type || "paragraph",
    text: (r.querySelector(".st-block-text") || {}).textContent ? r.querySelector(".st-block-text").textContent.trim() : "",
  })).filter((b) => b.text);
}

// --- sheet editor ---------------------------------------------------------
function sheetRows() {
  if (!Array.isArray(studio.spec.rows)) studio.spec.rows = [["Column A", "Column B"], ["", ""]];
  return studio.spec.rows;
}
function renderSheet(body) {
  body.classList.add("st-sheet");
  const wrap = el("div", "st-grid-wrap");
  wrap.id = "stGridWrap";
  drawGrid(wrap);
  const bar = el("div", "st-addbar");
  const addRow = el("button", "st-add"); addRow.innerHTML = `${ic("plus", 13)}<span>Row</span>`;
  addRow.addEventListener("click", () => { syncSheetFromDom(); const w = sheetRows()[0] ? sheetRows()[0].length : 2; sheetRows().push(new Array(w).fill("")); drawGrid(wrap); markDirty(); });
  const addCol = el("button", "st-add"); addCol.innerHTML = `${ic("plus", 13)}<span>Column</span>`;
  addCol.addEventListener("click", () => { syncSheetFromDom(); sheetRows().forEach((r) => r.push("")); drawGrid(wrap); markDirty(); });
  bar.appendChild(addRow); bar.appendChild(addCol);
  body.appendChild(wrap);
  body.appendChild(bar);
}
function drawGrid(wrap) {
  wrap.innerHTML = "";
  const table = el("table", "st-grid");
  sheetRows().forEach((row, ri) => {
    const tr = el("tr");
    row.forEach((cell) => {
      const td = el(ri === 0 ? "th" : "td");
      const ed = editable("div", "st-cell", cell == null ? "" : String(cell), "");
      td.appendChild(ed);
      tr.appendChild(td);
    });
    table.appendChild(tr);
  });
  wrap.appendChild(table);
}
function syncSheetFromDom() {
  const table = $("#stGridWrap .st-grid");
  if (!table) return;
  studio.spec.rows = Array.from(table.querySelectorAll("tr")).map((tr) =>
    Array.from(tr.children).map((td) => {
      const c = td.querySelector(".st-cell");
      return c ? c.textContent.trim() : "";
    }));
}

// --- persistence ----------------------------------------------------------
function syncFromDom() {
  if (isDeck()) syncDeckFromDom();
  else if (isSheet()) syncSheetFromDom();
  else syncDocFromDom();
}

async function saveStudio(silent) {
  syncFromDom();
  const btn = $("#stSaveBtn");
  if (btn) btn.disabled = true;
  try {
    const { status, body } = await postJSON(
      `/studio/${studio.cid}/${encodeURIComponent(studio.filename)}`, { spec: studio.spec });
    if (status !== 200) throw new Error(body.error || "save failed");
    markSaved();
    if (!silent) stToast("Saved. The downloadable file is updated.", "ok");
    return true;
  } catch (e) {
    stToast(e.message || "Could not save.", "warn");
    return false;
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function exportAs(fmt) {
  const ok = await saveStudio(true);
  if (!ok) return;
  const base = studio.filename.replace(/\.[^.]+$/, "");
  const url = withToken(`/studio/${studio.cid}/${encodeURIComponent(studio.filename)}/export?format=${encodeURIComponent(fmt)}`);
  // Trigger a real download without navigating the app away.
  const a = document.createElement("a");
  a.href = url;
  a.download = `${base}.${fmt}`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  stToast(`Exporting ${fmt.toUpperCase()}…`, "");
}

// --- present mode ---------------------------------------------------------
let presentIdx = 0;
function startPresent() {
  if (!isDeck()) return;
  syncDeckFromDom();
  saveStudio(true);              // persist edits to the file before presenting
  presentIdx = studio.active || 0;
  const overlay = $("#present");
  overlay.classList.add("show");
  overlay.setAttribute("aria-hidden", "false");
  drawPresent();
  document.addEventListener("keydown", presentKeys);
  if (overlay.requestFullscreen) overlay.requestFullscreen().catch(() => {});
}

function presentBullets(arr, ink, accent) {
  if (!arr || !arr.length) return "";
  return `<ul class="pz-bul">${arr.map((b) =>
    `<li style="color:#${ink}"><span class="pz-dot" style="background:#${accent}"></span>${esc(b)}</li>`).join("")}</ul>`;
}

function presentDiagram(shapes, accent, ink) {
  let boxes = "", lines = "";
  (shapes || []).forEach((sh) => {
    if (!sh || typeof sh !== "object") return;
    const kind = String(sh.type || "rect").toLowerCase();
    const col = sh.color ? normHex(sh.color) : accent;
    if (kind === "rect" || kind === "roundrect" || kind === "ellipse") {
      const radius = kind === "ellipse" ? "50%" : (kind === "roundrect" ? "12px" : "3px");
      const tc = sh.text_color ? normHex(sh.text_color) : "FFFFFF";
      boxes += `<div class="pz-shape" style="left:${+sh.x || 0}%;top:${+sh.y || 0}%;` +
        `width:${+sh.w || 20}%;height:${+sh.h || 20}%;background:#${col};border-radius:${radius};` +
        `color:#${tc}">${sh.text ? esc(sh.text) : ""}</div>`;
    } else if (kind === "line" || kind === "arrow") {
      const x1 = +sh.x || 0, y1 = +sh.y || 0;
      const x2 = (sh.x2 != null ? +sh.x2 : x1), y2 = (sh.y2 != null ? +sh.y2 : y1);
      const marker = kind === "arrow" ? ' marker-end="url(#pvarrow)"' : "";
      lines += `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="#${col}" stroke-width="0.7"${marker}/>`;
    } else if (kind === "text") {
      const tc = sh.color ? normHex(sh.color) : ink;
      boxes += `<div class="pz-shape pz-shape-text" style="left:${+sh.x || 0}%;top:${+sh.y || 0}%;` +
        `width:${+sh.w || 30}%;color:#${tc}">${sh.text ? esc(sh.text) : ""}</div>`;
    }
  });
  const svg = `<svg class="pz-diagram-svg" viewBox="0 0 100 100" preserveAspectRatio="none">` +
    `<defs><marker id="pvarrow" markerWidth="5" markerHeight="5" refX="4" refY="2.5" orient="auto">` +
    `<path d="M0,0 L5,2.5 L0,5 z" fill="#${accent}"/></marker></defs>${lines}</svg>`;
  return `<div class="pz-diagram">${svg}${boxes}</div>`;
}

function svgDataUri(svg) {
  return "data:image/svg+xml;charset=utf-8," + encodeURIComponent(String(svg || ""));
}
// A visual tag for a slide: inline SVG (chart/art) or an embedded image path.
function presentVisual(s) {
  if (s.svg) return `<img class="pz-img" src="${svgDataUri(s.svg)}" alt="">`;
  if (s.image) return `<img class="pz-img" src="${withToken(`/preview/${studio.cid}/${s.image}`)}" alt="">`;
  return "";
}
function presentCards(cards, pal) {
  const list = (cards || []).slice(0, 8);
  return `<div class="pz-cards">` + list.map((c) => {
    c = c || {};
    const tag = (c.num != null && c.num !== "") ? esc(String(c.num)) : (c.label ? esc(c.label) : "");
    return `<div class="pz-card" style="background:#${pal.surface}">` +
      (tag ? `<div class="pz-card-tag" style="color:#${pal.accent}">${tag}</div>` : "") +
      (c.title ? `<div class="pz-card-title" style="color:#${pal.ink}">${esc(c.title)}</div>` : "") +
      (c.text ? `<div class="pz-card-text" style="color:#${pal.muted}">${esc(c.text)}</div>` : "") +
      `</div>`;
  }).join("") + `</div>`;
}
function presentFlow(steps, pal) {
  const list = (steps || []).map((st) => (typeof st === "string" ? { label: st } : (st || {})));
  return `<div class="pz-flow">` + list.map((n, i) => {
    const label = n.label || n.title || n.value || n.name || n.text || "";
    const arrow = i < list.length - 1
      ? `<div class="pz-flow-arrow" style="color:#${pal.accent}">&#8594;</div>` : "";
    return `<div class="pz-flow-box" style="background:#${pal.surface};color:#${pal.ink};` +
      `border:1px solid #${pal.accent}55">${esc(label)}</div>${arrow}`;
  }).join("") + `</div>`;
}

function presentSlideHTML(s, pal) {
  const layout = slideLayout(s);
  const isSection = layout === "section";
  const bg = s.bg ? normHex(s.bg) : (isSection ? pal.accent : pal.bg);
  const ink = isSection ? pal.on_accent : pal.ink;
  const muted = isSection ? pal.on_accent : pal.muted;
  const accent = s.accent ? normHex(s.accent) : pal.accent;
  const sub = s.subtitle ? `<div class="pz-sub" style="color:#${muted}">${esc(s.subtitle)}</div>` : "";
  const head = (tag) => `<div class="pz-head"><div class="pz-rule" style="background:#${accent}"></div>` +
    `<${tag} style="color:#${ink}">${esc(s.title || "")}</${tag}></div>`;
  const imgTag = presentVisual(s);
  let inner;
  if (layout === "cover") {
    inner = `<div class="pz-center"><div class="pz-bar" style="background:#${accent}"></div>` +
      `<h1 style="color:#${ink}">${esc(s.title || "")}</h1>${sub}</div>`;
  } else if (layout === "section") {
    inner = `<div class="pz-center pz-center-mid"><h1 style="color:#${ink}">${esc(s.title || "")}</h1>${sub}</div>`;
  } else if (layout === "statement") {
    inner = `<div class="pz-center"><div class="pz-bar" style="background:#${accent}"></div>` +
      `<h1 class="pz-stmt" style="color:#${ink}">${esc(s.title || s.subtitle || "")}</h1></div>`;
  } else if (layout === "quote") {
    inner = `<div class="pz-quote"><div class="pz-mark" style="color:#${accent}">“</div>` +
      `<div class="pz-qtext" style="color:#${ink}">${esc(s.quote || s.title || "")}</div>` +
      (s.attribution ? `<div class="pz-attr" style="color:#${muted}">— ${esc(s.attribution)}</div>` : "") + `</div>`;
  } else if (layout === "two-column") {
    const cols = (s.columns || []).slice(0, 2);
    inner = head("h2") + `<div class="pz-cols">${cols.map((c) =>
      `<div class="pz-col">${presentBullets(c, ink, accent)}</div>`).join("")}</div>`;
  } else if (layout === "cards") {
    inner = head("h2") + sub + presentCards(s.cards, pal);
  } else if (layout === "image") {
    inner = (s.title ? head("h2") : "") + `<div class="pz-imgwrap">${imgTag}</div>`;
  } else if (layout === "diagram") {
    let fig;
    if (s.svg) fig = `<div class="pz-imgwrap">${imgTag}</div>`;
    else if (s.steps && s.steps.length) fig = presentFlow(s.steps, pal);
    else fig = presentDiagram(s.shapes || [], accent, ink);
    inner = head("h2") + fig;
  } else {
    const body = `<div class="pz-body">${head("h2")}${sub}${presentBullets(s.bullets, ink, accent)}</div>`;
    inner = (s.image || s.svg)
      ? `<div class="pz-split">${body}<div class="pz-imgwrap half">${imgTag}</div></div>`
      : body;
  }
  return { bg, html: `<div class="pz-slide pz-layout-${layout}" style="background:#${bg}">${inner}</div>` };
}

function drawPresent() {
  const slides = deckSlides();
  presentIdx = Math.max(0, Math.min(presentIdx, slides.length - 1));
  const s = slides[presentIdx];
  const { bg, html } = presentSlideHTML(s, deckTheme());
  const overlay = $("#present");
  overlay.style.background = "#" + bg;
  $("#presentStage").innerHTML = html;
  $("#presentCount").textContent = `${presentIdx + 1} / ${slides.length}`;
}
function presentKeys(e) {
  if (e.key === "ArrowRight" || e.key === " " || e.key === "PageDown") { e.preventDefault(); presentIdx++; drawPresent(); }
  else if (e.key === "ArrowLeft" || e.key === "PageUp") { e.preventDefault(); presentIdx--; drawPresent(); }
  else if (e.key === "Escape") endPresent();
}
function endPresent() {
  const overlay = $("#present");
  overlay.classList.remove("show");
  overlay.setAttribute("aria-hidden", "true");
  document.removeEventListener("keydown", presentKeys);
  if (document.fullscreenElement && document.exitFullscreen) document.exitFullscreen().catch(() => {});
}

// wire present overlay controls (markup is above this script, so it exists now)
(function wirePresent() {
  const n = $("#presentNext"), p = $("#presentPrev"), c = $("#presentClose");
  if (n) n.addEventListener("click", () => { presentIdx++; drawPresent(); });
  if (p) p.addEventListener("click", () => { presentIdx--; drawPresent(); });
  if (c) c.addEventListener("click", endPresent);
})();

window.openStudio = openStudio;
