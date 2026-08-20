/* Poly web interface. Vanilla JS: dropdowns, window drag/resize, pane split,
   and the two API calls (transpile, self-check). No dependencies. */
"use strict";

const $ = (id) => document.getElementById(id);
const tile = $("tile"), head = $("tilehead"), grip = $("grip");
const panes = $("panes"), paneSrc = $("pane-src"), divider = $("divider");
const src = $("src"), out = $("out"), statusEl = $("status"), timingEl = $("timing");
const runBtn = $("run"), checkBtn = $("check"), copyBtn = $("copy"), keyEl = $("apikey");

const TARGET_NAMES = { js: "JavaScript", py: "Python", c: "C" };
let target = "js";

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

const STORE_KEY = "poly.win.v2";   // v2: discard layouts saved while the visualizer split was active

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
  vizBody.innerHTML = '<div class="viz-msg">running the 6-stage pipeline on your code&hellip;</div>';
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
      : "paste an API key in the header for an AI narration of each stage";
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

initDropdown($("dd-source"), null);
initDropdown($("dd-target"), (v) => setTarget(v, true));

function setTarget(v, fromUser) {
  target = v;
  $("label-out").textContent = "output · " + TARGET_NAMES[v].toLowerCase();
  const root = $("dd-target");
  root.querySelectorAll("li").forEach((li) => li.classList.toggle("on", li.dataset.value === v));
  root.querySelector(".dd-value").textContent = TARGET_NAMES[v];
  if (fromUser) save();
}

/* ---------------- editor niceties ---------------- */

src.value = localStorage.getItem("poly.src") || DEFAULT_SOURCE;
src.addEventListener("input", () => localStorage.setItem("poly.src", src.value));

src.addEventListener("keydown", (e) => {
  if (e.key === "Tab") {
    e.preventDefault();
    insert("    ");
  } else if (e.key === "Enter") {
    e.preventDefault();
    const before = src.value.slice(0, src.selectionStart);
    const line = before.slice(before.lastIndexOf("\n") + 1);
    const indent = (line.match(/^ */) || [""])[0] + (line.trimEnd().endsWith(":") ? "    " : "");
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
  const timer = setTimeout(() => ctl.abort(), 60000);
  try {
    const res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: ctl.signal,
    });
    return await res.json();
  } finally { clearTimeout(timer); }
}

function payload() {
  return { source: src.value, target, api_key: keyEl.value.trim() };
}

function setBusy(busy, msg) {
  runBtn.disabled = checkBtn.disabled = busy;
  statusEl.textContent = msg;
  statusEl.className = "";
  timingEl.textContent = "";
}

function showText(text, cls) {
  out.innerHTML = "";
  const code = document.createElement("code");
  if (cls) code.className = cls;
  code.textContent = text;
  out.appendChild(code);
}

function holeSummary(records) {
  if (!records || !records.length) return "no holes";
  const via = records.some((r) => r.via === "live") ? "live LLM"
            : records.some((r) => r.via === "mock") ? "offline mock" : "cache";
  const n = records.length;
  return n + " hole" + (n > 1 ? "s" : "") + " via " + via + ", gates A/B/C passed";
}

async function run() {
  if (runBtn.disabled) return;
  setBusy(true, "transpiling…");
  try {
    const r = await call("/api/transpile", payload());
    if (r.ok) {
      showText(r.code);
      statusEl.textContent = TARGET_NAMES[target].toLowerCase() + " · " + holeSummary(r.records);
      statusEl.className = "ok";
    } else {
      showText(r.error.rendered, "err");
      statusEl.textContent = r.error.message;
      statusEl.className = "err";
    }
    timingEl.textContent = (r.ms || 0) + " ms";
  } catch {
    setBusy(false, "server unreachable, is web/server.py running?");
    statusEl.className = "err";
    return;
  }
  runBtn.disabled = checkBtn.disabled = false;
}

async function check() {
  if (checkBtn.disabled) return;
  setBusy(true, "running 3-way self-check…");
  try {
    const r = await call("/api/selfcheck", payload());
    if (r.ok) {
      out.innerHTML = "";
      const code = document.createElement("code");
      code.appendChild(line("3-way differential self-check\n", ""));
      code.appendChild(line("CPython source vs IR interpreter vs targets\n\n", ""));
      const tag = { pass: ["PASS", "ok"], FAIL: ["FAIL", "err"], skipped: ["SKIP", "skip"], ERROR: ["ERR ", "err"] };
      for (const row of r.rows) {
        const [label, cls] = tag[row.status] || [row.status, ""];
        code.appendChild(line("  [", ""));
        code.appendChild(line(label, cls));
        code.appendChild(line("] " + row.name + "\n", ""));
        if (row.status === "FAIL" || row.status === "ERROR")
          code.appendChild(line("        " + row.output + "\n", "err"));
      }
      code.appendChild(line("\nRESULT: ", ""));
      code.appendChild(line(r.all_ok ? "all consistent" : "DIVERGENCE DETECTED", r.all_ok ? "ok" : "err"));
      out.appendChild(code);
      statusEl.textContent = r.all_ok ? "self-check consistent across all targets" : "divergence detected";
      statusEl.className = r.all_ok ? "ok" : "err";
    } else {
      showText(r.error.rendered, "err");
      statusEl.textContent = r.error.message;
      statusEl.className = "err";
    }
    timingEl.textContent = (r.ms || 0) + " ms";
  } catch {
    setBusy(false, "server unreachable, is web/server.py running?");
    statusEl.className = "err";
    return;
  }
  runBtn.disabled = checkBtn.disabled = false;
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
