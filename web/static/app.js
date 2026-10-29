/* Poly web interface. Vanilla JS: dropdowns, window drag/resize, pane split,
   and the two API calls (transpile, self-check). No dependencies. */
"use strict";

const $ = (id) => document.getElementById(id);
const tile = $("tile"), head = $("tilehead"), grip = $("grip");
const panes = $("panes"), paneSrc = $("pane-src"), divider = $("divider");
const src = $("src"), out = $("out"), statusEl = $("status"), timingEl = $("timing");
const runBtn = $("run"), checkBtn = $("check"), copyBtn = $("copy"), keyEl = $("apikey");

const TARGET_NAMES = { py: "Python", js: "JavaScript", c: "C", cpp: "C++", java: "Java", cs: "C#", go: "Go", rust: "Rust", ruby: "Ruby", php: "PHP" };
const EXTENSIONS = { py: ".py", js: ".js", c: ".c", cpp: ".cpp", java: ".java", cs: ".cs", go: ".go", rust: ".rs", ruby: ".rb", php: ".php" };
let target = "js";
let sourceLang = "py";
let examples = {};
let demos = [];
let activeDemo = "";
let lastTranslation = null;
let busy = false;
const STORE_KEY = "poly.win.v2";
for (const [id, selected] of [["dd-source", "py"], ["dd-target", "js"]]) {
  const menu = $(id).querySelector(".dd-menu");
  menu.replaceChildren(...Object.entries(TARGET_NAMES).map(([value, name]) => {
    const li = document.createElement("li");
    li.setAttribute("role", "option");
    li.dataset.value = value;
    li.textContent = name;
    li.classList.toggle("on", value === selected);
    return li;
  }));
}

const DEFAULT_SOURCE = `def gcd(a: int, b: int) -> int:
    while b != 0:
        t = b
        b = a % b
        a = t
    return a

nums = [12, 18, 24, 30, 36]
halves = [n // 2 for n in nums if n % 3 == 0]
print(gcd(48, 36))
print(halves)
print(nums[1:4])
`;

/* ---------------- window state (position, size, split) ---------------- */

const state = load() || {};


function load() {
  try { return JSON.parse(localStorage.getItem(STORE_KEY)); } catch { return null; }
}
function save() {
  // While the visualizer split is active, persist the remembered full-span
  // geometry, never the temporary half-screen one.
  const b = tile.getBoundingClientRect();
  const r = (vizOpen && savedRect) ? savedRect : { x: b.left, y: b.top, w: b.width, h: b.height };
  localStorage.setItem(STORE_KEY, JSON.stringify({
    x: r.x, y: r.y, w: r.w, h: r.h,
    split: parseFloat(paneSrc.style.flexBasis) || 50, target,
  }));
}

function applyLayout() {
  const vw = innerWidth, vh = innerHeight;
  // default: near-fullscreen with a slim margin of artwork around the glass
  let w = state.w || (vw - 144);
  let h = state.h || (vh - 80);
  w = Math.max(660, Math.min(w, vw - 16));
  h = Math.max(380, Math.min(h, vh - 16));
  let x = state.x ?? (vw - w) / 2;
  let y = state.y ?? (vh - h) / 2 + 8;
  x = Math.max(8, Math.min(x, vw - w - 8));
  y = Math.max(8, Math.min(y, vh - h - 8));
  Object.assign(tile.style, { left: x + "px", top: y + "px", width: w + "px", height: h + "px" });
  paneSrc.style.flexBasis = (state.split || 50) + "%";
  if (state.target && TARGET_NAMES[state.target]) setTarget(state.target, false);
}

/* ---------------- dragging and resizing ---------------- */

function trackPointer(el, onStart, onMove, opts = {}) {
  el.addEventListener("pointerdown", (e) => {
    if (opts.exclude && e.target.closest(opts.exclude)) return;
    if (matchMedia("(max-width: 700px)").matches) return;
    e.preventDefault();
    const ctx = onStart(e);
    const move = (ev) => onMove(ev, ctx);
    const up = () => {
      removeEventListener("pointermove", move);
      removeEventListener("pointerup", up);
      opts.onEnd && opts.onEnd();
      save();
    };
    addEventListener("pointermove", move);
    addEventListener("pointerup", up);
  });
}

// move the tile by its header
trackPointer(head, (e) => {
  const r = tile.getBoundingClientRect();
  return { dx: e.clientX - r.left, dy: e.clientY - r.top, w: r.width, h: r.height };
}, (e, c) => {
  const x = Math.max(8, Math.min(e.clientX - c.dx, innerWidth - c.w - 8));
  const y = Math.max(8, Math.min(e.clientY - c.dy, innerHeight - c.h - 8));
  tile.style.left = x + "px";
  tile.style.top = y + "px";
}, { exclude: "button, input, .dd, textarea" });

// resize from the corner grip
trackPointer(grip, () => {
  const r = tile.getBoundingClientRect();
  return { x: r.left, y: r.top };
}, (e, c) => {
  const w = Math.max(660, Math.min(e.clientX - c.x + 8, innerWidth - c.x - 8));
  const h = Math.max(380, Math.min(e.clientY - c.y + 8, innerHeight - c.y - 8));
  tile.style.width = w + "px";
  tile.style.height = h + "px";
});

// drag the pane divider
trackPointer(divider, () => {
  divider.classList.add("active");
  return panes.getBoundingClientRect();
}, (e, r) => {
  const pct = Math.max(22, Math.min(78, ((e.clientX - r.left) / r.width) * 100));
  paneSrc.style.flexBasis = pct + "%";
}, { onEnd: () => divider.classList.remove("active") });

addEventListener("resize", () => {
  if (vizOpen) { applySplit(); return; }
  Object.assign(state, load() || {});
  applyLayout();
});

/* ---------------- pipeline visualizer ---------------- */

const viz = $("viz"), vizBody = $("vizbody"), vizBtn = $("vizbtn");
let vizOpen = false;
let savedRect = null;

function setRect(el, r) {
  Object.assign(el.style, { left: r.x + "px", top: r.y + "px", width: r.w + "px", height: r.h + "px" });
}

function splitRects() {
  const vw = innerWidth, vh = innerHeight, m = 36, gap = 14;
  const inner = vw - m * 2 - gap;
  const tw = Math.max(540, Math.round(inner * 0.46));
  return {
    tile: { x: m, y: m, w: tw, h: vh - m * 2 },
    viz: { x: m + tw + gap, y: m, w: inner - tw, h: vh - m * 2 },
  };
}

function applySplit() {
  const r = splitRects();
  setRect(tile, r.tile);
  setRect(viz, r.viz);
}

function openViz() {
  if (innerWidth < 1100) {
    statusEl.textContent = "screen too narrow for the visualizer";
    return;
  }
  const r = tile.getBoundingClientRect();
  savedRect = { x: r.left, y: r.top, w: r.width, h: r.height };
  vizOpen = true;
  vizBtn.classList.add("on");
  tile.classList.add("animating", "split");
  applySplit();
  viz.hidden = false;
  void viz.offsetWidth;          // force reflow so the fade-in transition always runs
  viz.classList.add("in");
  runPipeline();
}

function closeViz() {
  vizOpen = false;
  vizBtn.classList.remove("on");
  viz.classList.remove("in");
  setTimeout(() => { viz.hidden = true; }, 250);
  if (savedRect) setRect(tile, savedRect);
  setTimeout(() => tile.classList.remove("animating", "split"), 500);
}

async function runPipeline() {
  vizBody.innerHTML = '<div class="viz-msg">running the translation pipeline on your code&hellip;</div>';
  let r;
  try {
    r = await call("/api/pipeline", payload());
  } catch {
    vizBody.innerHTML = '<div class="viz-msg">server unreachable, is web/server.py running?</div>';
    return;
  }
  renderPipeline(r);
}

function renderPipeline(r) {
  vizBody.innerHTML = "";
  if (!r.ok || !r.stages) {
    vizBody.innerHTML = '<div class="viz-msg">pipeline failed to run</div>';
    return;
  }
  const badge = { ok: "", error: "failed", blocked: "blocked" };
  r.stages.forEach((s, i) => {
    const card = document.createElement("div");
    card.className = "stage" + (s.status === "error" ? " err" : s.status === "blocked" ? " blocked" : "");
    card.style.animationDelay = (i * 130) + "ms";

    const top = document.createElement("div");
    top.className = "stage-top";
    top.appendChild(line2("stage-num", "0" + (i + 1)));
    top.appendChild(line2("stage-name", s.name));
    if (badge[s.status]) top.appendChild(line2("stage-badge", badge[s.status]));
    top.appendChild(line2("stage-ms", s.status === "ok" ? s.ms + " ms" : ""));
    card.appendChild(top);

    const pre = document.createElement("pre");
    pre.textContent = s.detail;
    card.appendChild(pre);

    if (s.note) {
      const note = document.createElement("div");
      note.className = "stage-note";
      note.textContent = s.note;
      card.appendChild(note);
    }
    vizBody.appendChild(card);
    if (i < r.stages.length - 1) {
      const arrow = document.createElement("div");
      arrow.className = "stage-arrow";
      arrow.textContent = "↓";
      arrow.style.animationDelay = (i * 130 + 65) + "ms";
      vizBody.appendChild(arrow);
    }
  });
  if (!r.narrated) {
    const hint = document.createElement("div");
    hint.className = "viz-hint";
    hint.textContent = keyEl.value.trim()
      ? "AI narration unavailable for this run"
      : "Compiler stages are shown for supported Python programs; other pairs use AI translation and local compiler checks.";
    vizBody.appendChild(hint);
  }
}

function line2(cls, text) {
  const el = document.createElement("span");
  el.className = cls;
  el.textContent = text;
  return el;
}

vizBtn.addEventListener("click", () => (vizOpen ? closeViz() : openViz()));
$("vizclose").addEventListener("click", closeViz);
$("vizrefresh").addEventListener("click", runPipeline);
addEventListener("keydown", (e) => { if (e.key === "Escape" && vizOpen) closeViz(); });

/* ---------------- dropdowns ---------------- */

function initDropdown(root, onPick) {
  const trigger = root.querySelector(".dd-trigger");
  const value = root.querySelector(".dd-value");
  trigger.addEventListener("click", (e) => {
    if (busy) return;
    e.stopPropagation();
    const wasOpen = root.classList.contains("open");
    closeMenus();
    if (!wasOpen) root.classList.add("open");
  });
  root.querySelectorAll(".dd-menu li").forEach((li) => {
    li.addEventListener("click", () => {
      root.querySelectorAll("li").forEach((x) => x.classList.remove("on"));
      li.classList.add("on");
      value.textContent = li.textContent;
      root.classList.remove("open");
      onPick && onPick(li.dataset.value);
    });
  });
}
function closeMenus() { document.querySelectorAll(".dd.open").forEach((d) => d.classList.remove("open")); }
addEventListener("click", closeMenus);
addEventListener("keydown", (e) => { if (e.key === "Escape") closeMenus(); });

initDropdown($("dd-source"), (v) => setSource(v));
initDropdown($("dd-target"), (v) => setTarget(v, true));

function setSource(v, restore = true) {
  localStorage.setItem("poly.src." + sourceLang, src.value);
  sourceLang = v;
  localStorage.setItem("poly.sourceLang", v);
  $("label-src").textContent = "source · " + TARGET_NAMES[v].toLowerCase();
  const root = $("dd-source");
  root.querySelectorAll("li").forEach((li) => li.classList.toggle("on", li.dataset.value === v));
  root.querySelector(".dd-value").textContent = TARGET_NAMES[v];
  if (restore) {
    const demo = demos.find((d) => d.id === activeDemo);
    src.value = demo?.code[v] ?? localStorage.getItem("poly.src." + v) ?? examples[v] ?? "";
    if (demo) src.dispatchEvent(new Event("input"));
  }
  lastTranslation = null;
  showText("output appears here", "placeholder");
  statusEl.textContent = "ready · " + TARGET_NAMES[v] + " → " + TARGET_NAMES[target];
  timingEl.textContent = "";
}

function setTarget(v, fromUser) {
  target = v;
  $("label-out").textContent = "output · " + TARGET_NAMES[v].toLowerCase();
  const root = $("dd-target");
  root.querySelectorAll("li").forEach((li) => li.classList.toggle("on", li.dataset.value === v));
  root.querySelector(".dd-value").textContent = TARGET_NAMES[v];
  if (fromUser) {
    lastTranslation = null;
    showText("output appears here", "placeholder");
    timingEl.textContent = "";
    statusEl.textContent = "ready · " + TARGET_NAMES[sourceLang] + " → " + TARGET_NAMES[target];
    save();
  }
}

/* ---------------- editor niceties ---------------- */

src.value = localStorage.getItem("poly.src") || DEFAULT_SOURCE;
src.addEventListener("input", () => {
  const demo = demos.find((d) => d.id === activeDemo);
  if (demo && src.value.replace(/\r\n/g, "\n").trim() !== demo.code[sourceLang].trim()) {
    activeDemo = "";
    $("demo").value = "";
  }
  localStorage.setItem("poly.src." + sourceLang, src.value);
  if (sourceLang === "py") localStorage.setItem("poly.src", src.value);
});

src.addEventListener("keydown", (e) => {
  if (e.key === "Tab") {
    e.preventDefault();
    insert("    ");
  } else if (e.key === "Enter") {
    e.preventDefault();
    const before = src.value.slice(0, src.selectionStart);
    const line = before.slice(before.lastIndexOf("\n") + 1);
    const indent = (line.match(/^ */) || [""])[0] + ((sourceLang === "py" ? line.trimEnd().endsWith(":") : line.trimEnd().endsWith("{")) ? "    " : "");
    insert("\n" + indent);
  }
});
function insert(text) {
  const s = src.selectionStart, e = src.selectionEnd;
  src.value = src.value.slice(0, s) + text + src.value.slice(e);
  src.selectionStart = src.selectionEnd = s + text.length;
  src.dispatchEvent(new Event("input"));
}

addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); run(); }
});

/* ---------------- API calls ---------------- */

async function call(path, body) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), 360000);
  try {
    const res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: ctl.signal,
    });
    if (!res.ok) throw new Error("Server returned HTTP " + res.status);
    return await res.json();
  } finally { clearTimeout(timer); }
}

function payload() {
  return { source: src.value, source_lang: sourceLang, target, api_key: keyEl.value.trim(), provider: $("provider").value, model: $("model").value.trim() };
}

function setBusy(busy, msg) {
  setControlsBusy(busy);
  statusEl.textContent = msg;
  statusEl.className = "";
  timingEl.textContent = "";
}

function setControlsBusy(value) {
  busy = value;
  for (const id of ["run", "check", "swap", "example", "demo", "provider", "model", "apikey", "vizrefresh", "vizbtn"]) $(id).disabled = value;
  src.readOnly = value;
}

function showText(text, cls) {
  out.innerHTML = "";
  const code = document.createElement("code");
  if (cls) code.className = cls;
  code.textContent = text;
  out.appendChild(code);
}

function elapsed(ms) {
  return ms >= 1000 ? (ms / 1000).toFixed(1) + " s" : ms + " ms";
}

async function run() {
  if (runBtn.disabled) return;
  setBusy(true, "transpiling…");
  try {
    const r = await call("/api/transpile", payload());
    if (r.ok) {
      showText(r.code);
      lastTranslation = { source: src.value, sourceLang, target, code: r.code };
      statusEl.textContent = "Done";
      statusEl.className = "ok";
    } else {
      lastTranslation = null;
      showText(r.error.rendered, "err");
      statusEl.textContent = r.error.message;
      statusEl.className = "err";
    }
    timingEl.textContent = elapsed(r.ms || 0);
  } catch (err) {
    setBusy(false, err.name === "AbortError" ? "translation timed out, please retry" : "server unreachable, is web/server.py running?");
    statusEl.className = "err";
    return;
  }
  setControlsBusy(false);
}

async function check() {
  if (checkBtn.disabled) return;
  setBusy(true, "running source and translation locally…");
  try {
    const body = payload();
    if (lastTranslation && lastTranslation.source === src.value && lastTranslation.sourceLang === sourceLang && lastTranslation.target === target) body.translated_code = lastTranslation.code;
    const r = await call("/api/selfcheck", body);
    if (r.ok) {
      out.innerHTML = "";
      const code = document.createElement("code");
      code.appendChild(line("Source ↔ translation check\n", ""));
      code.appendChild(line(TARGET_NAMES[sourceLang] + " → " + TARGET_NAMES[target] + "\n\n", ""));
      const tag = { pass: ["PASS", "ok"], FAIL: ["FAIL", "err"], skipped: ["SKIP", "skip"], ERROR: ["ERR ", "err"] };
      for (const row of r.rows) {
        const [label, cls] = tag[row.status] || [row.status, ""];
        code.appendChild(line("  [", ""));
        code.appendChild(line(label, cls));
        code.appendChild(line("] " + row.name + "\n", ""));
        if (row.output)
          code.appendChild(line("        " + row.output + "\n", "err"));
      }
      code.appendChild(line("\nRESULT: ", ""));
      code.appendChild(line(r.all_ok ? "outputs match on this run" : r.verified === false ? "could not verify this translation" : "DIVERGENCE DETECTED", r.all_ok ? "ok" : "err"));
      out.appendChild(code);
      statusEl.textContent = r.all_ok ? "source and translation outputs match" : r.verified === false ? "check incomplete: see output" : "output mismatch";
      if (r.code) lastTranslation = { source: src.value, sourceLang, target, code: r.code };
      statusEl.className = r.all_ok ? "ok" : "err";
    } else {
      showText(r.error.rendered, "err");
      statusEl.textContent = r.error.message;
      statusEl.className = "err";
    }
    timingEl.textContent = elapsed(r.ms || 0);
  } catch {
    setBusy(false, "server unreachable, is web/server.py running?");
    statusEl.className = "err";
    return;
  }
  setControlsBusy(false);
}
function line(text, cls) {
  const span = document.createElement("span");
  if (cls) span.className = cls;
  span.textContent = text;
  return span;
}

copyBtn.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(out.textContent);
    copyBtn.textContent = "copied";
    setTimeout(() => (copyBtn.textContent = "copy"), 1200);
  } catch { /* clipboard unavailable */ }
});

runBtn.addEventListener("click", run);
checkBtn.addEventListener("click", check);

applyLayout();

$("settingsbtn").addEventListener("click", () => {
  $("settings").hidden = !$("settings").hidden;
  $("settingsbtn").setAttribute("aria-expanded", String(!$("settings").hidden));
});
$("example").addEventListener("click", () => {
  if (examples[sourceLang]) {
    activeDemo = "";
    $("demo").value = "";
    src.value = examples[sourceLang];
    src.dispatchEvent(new Event("input"));
    lastTranslation = null;
    statusEl.textContent = TARGET_NAMES[sourceLang] + " example loaded";
  }
});
$("swap").addEventListener("click", () => {
  const translated = lastTranslation && lastTranslation.source === src.value && lastTranslation.sourceLang === sourceLang && lastTranslation.target === target ? lastTranslation.code : null;
  const previous = sourceLang;
  setSource(target);
  setTarget(previous, true);
  if (translated) {
    src.value = translated;
    src.dispatchEvent(new Event("input"));
  }
});
$("download").addEventListener("click", () => {
  if (!lastTranslation) { statusEl.textContent = "translate a program first"; return; }
  const url = URL.createObjectURL(new Blob([lastTranslation.code], { type: "text/plain;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = (lastTranslation.target === "java" ? "Main" : "translated") + EXTENSIONS[lastTranslation.target];
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
fetch("/api/languages").then((r) => r.json()).then((data) => {
  examples = Object.fromEntries(Object.entries(data.languages).map(([k, v]) => [k, v.example]));
  $("service-info").textContent = data.api_configured ? "Server API access configured." : data.claude_cli ? "Claude CLI available. Uses your existing Claude login; no API key needed." : "Install Claude Code and sign in, or enter an Anthropic API key in the header.";
  const previous = localStorage.getItem("poly.sourceLang");
  if (previous && TARGET_NAMES[previous] && previous !== sourceLang) setSource(previous);
}).catch(() => { $("service-info").textContent = "Cannot reach server. Start python web/server.py."; });

fetch("/api/demos").then((r) => r.json()).then((data) => {
  demos = data.demos;
  for (const demo of demos) {
    const option = document.createElement("option");
    option.value = demo.id;
    option.textContent = demo.title;
    $("demo").appendChild(option);
  }
}).catch(() => { $("demo").disabled = true; });
$("demo").addEventListener("change", () => {
  const demo = demos.find((d) => d.id === $("demo").value);
  activeDemo = demo?.id ?? "";
  if (!demo) return;
  src.value = demo.code[sourceLang];
  src.dispatchEvent(new Event("input"));
  lastTranslation = null;
  showText("output appears here", "placeholder");
  timingEl.textContent = "";
  statusEl.textContent = demo.title + " loaded";
});
