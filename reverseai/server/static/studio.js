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
  light:    { bg: "FFFFFF", surface: "F3F5F9", ink: "16181D", muted: "5C6672", accent: "2D6CDF", on_accent: "FFFFFF" },
  slate:    { bg: "F7F8FA", surface: "FFFFFF", ink: "1B2230", muted: "5A6676", accent: "4457F2", on_accent: "FFFFFF" },
  midnight: { bg: "0E1526", surface: "18233E", ink: "EEF3FF", muted: "9DB2D6", accent: "4F8CFF", on_accent: "FFFFFF" },
  aurora:   { bg: "07121A", surface: "0E2230", ink: "EAFBFF", muted: "8FC7D6", accent: "2AD6B5", on_accent: "04221C" },
  sunset:   { bg: "1C1020", surface: "2C1630", ink: "FFF0EC", muted: "E3A6B8", accent: "FF6B4A", on_accent: "2A0C08" },
  forest:   { bg: "0C1A12", surface: "12271B", ink: "ECFBEF", muted: "97C4A6", accent: "35C06A", on_accent: "05240F" },
  mono:     { bg: "121316", surface: "1D1F24", ink: "F4F5F7", muted: "A2A7B0", accent: "E8EAED", on_accent: "121316" },
};
const STUDIO_THEMES = ["light", "slate", "midnight", "aurora", "sunset", "forest", "mono"];
const STUDIO_LAYOUTS = ["cover", "content", "two-column", "section", "quote", "statement", "image", "diagram"];

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
  if (s.shapes && s.shapes.length) return "diagram";
  if (s.quote) return "quote";
  if ((s.image || s.image_data) && !(s.bullets && s.bullets.length)) return "image";
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
    card.appendChild(el("div", "st-diagram-note",
      "This slide is a diagram. Edit its shapes with the Ask bar below (e.g. \"make the middle box green\")."));
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
  presentIdx = studio.active || 0;
  const overlay = $("#present");
  overlay.classList.add("show");
  overlay.setAttribute("aria-hidden", "false");
  drawPresent();
  document.addEventListener("keydown", presentKeys);
  if (overlay.requestFullscreen) overlay.requestFullscreen().catch(() => {});
}
function drawPresent() {
  const slides = deckSlides();
  presentIdx = Math.max(0, Math.min(presentIdx, slides.length - 1));
  const s = slides[presentIdx];
  const stage = $("#presentStage");
  stage.innerHTML = `
    <div class="present-slide">
      <h1>${esc(s.title || "")}</h1>
      ${s.subtitle ? `<div class="present-sub">${esc(s.subtitle)}</div>` : ""}
      ${(s.bullets && s.bullets.length) ? `<ul>${s.bullets.map((b) => `<li>${esc(b)}</li>`).join("")}</ul>` : ""}
    </div>`;
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
