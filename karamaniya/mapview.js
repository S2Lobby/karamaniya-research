/* The map of Solvara, month by month. Shared by the run report and the control room.
 *
 *   const map = KaramaniyaMap(hostElement, { geo, regions, names, onSelect });
 *   map.show(row, prevRow, { month, pins: true });   // one history row (see engine.snapshot)
 *   map.setLayer("unrest");
 *
 * Every piece of text that could come from a run (event texts, names) is set with textContent. */
(function () {
  "use strict";
  const NS = "http://www.w3.org/2000/svg";
  const CSS = `
.kmap { position: relative; user-select: none; -webkit-user-select: none; border-radius: 8px; overflow: hidden; background: var(--km-sea);
  --km-sea: #b7cfd8; --km-sea-2: #a2bfcb; --km-land: #ece6d8; --km-ink: #1b2a31; --km-ink-2: #4a5961; --km-halo: #f8f6f0;
  --km-coast: #4f6d78; --km-border: #58606b; --km-nation: #26303a; --km-river: #6a9aae; --km-road: #8a6a46; --km-rail: #5b4a3a;
  --km-mtn: #f2ede2; --km-mtn-line: #6d6353; --km-mtn-shade: #c4b79f; --km-tree: #8aab85; --km-tree-line: #5b7857; --km-field: #c4b286;
  --km-k: #cfe1d6; --km-veleria: #d6dae5; --km-dorsania: #e7ddc8; --km-foreign-data: #d9d9d4;
  --km-occ: #eb6834; --km-reb: #e87ba4; --km-front: #c73333; --km-ours: #0d6b67; --km-union: #a8421b; --km-league: #2a78d6;
  --km-seq-0: #f6e6d3; --km-seq-1: #f0c69d; --km-seq-2: #e59a63; --km-seq-3: #cf683c; --km-seq-4: #a23d22;
  --km-div-lo: #c75a33; --km-div-mid: #dedbd3; --km-div-hi: #2c7c86;
  --km-id-karamanian: #1baf7a; --km-id-imperial: #4a3aa7; --km-id-vell: #eda100;
  --km-panel: rgba(252, 252, 251, 0.94); --km-panel-line: rgba(16, 32, 42, 0.14); --km-shadow: 0 2px 10px rgba(16, 32, 42, 0.16); }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) .kmap {
  --km-sea: #0f1c22; --km-sea-2: #0b161b; --km-land: #2a2f2b; --km-ink: #eef3f1; --km-ink-2: #b3c0bb; --km-halo: #121816;
  --km-coast: #7fa3ad; --km-border: #8b949c; --km-nation: #d5dde2; --km-river: #4f8296; --km-road: #a88a62; --km-rail: #b39a7c;
  --km-mtn: #3b3f39; --km-mtn-line: #a39784; --km-mtn-shade: #2a2d28; --km-tree: #3f5d45; --km-tree-line: #6f9573; --km-field: #6b6346;
  --km-k: #2e4239; --km-veleria: #313745; --km-dorsania: #413a2b; --km-foreign-data: #33373a;
  --km-occ: #e0632e; --km-reb: #d55181; --km-front: #ff6b5b; --km-ours: #3fc1b5; --km-union: #ff8a57; --km-league: #5ea3f2;
  --km-seq-0: #3a302a; --km-seq-1: #6e4328; --km-seq-2: #a6562e; --km-seq-3: #da6d3c; --km-seq-4: #ff9d62;
  --km-div-lo: #e0703f; --km-div-mid: #4b4f51; --km-div-hi: #4fb7c0;
  --km-id-karamanian: #2fc28c; --km-id-imperial: #9a8ff0; --km-id-vell: #e0a526;
  --km-panel: rgba(22, 27, 26, 0.94); --km-panel-line: rgba(255, 255, 255, 0.14); --km-shadow: 0 2px 12px rgba(0, 0, 0, 0.5); } }
:root[data-theme="dark"] .kmap {
  --km-sea: #0f1c22; --km-sea-2: #0b161b; --km-land: #2a2f2b; --km-ink: #eef3f1; --km-ink-2: #b3c0bb; --km-halo: #121816;
  --km-coast: #7fa3ad; --km-border: #8b949c; --km-nation: #d5dde2; --km-river: #4f8296; --km-road: #a88a62; --km-rail: #b39a7c;
  --km-mtn: #3b3f39; --km-mtn-line: #a39784; --km-mtn-shade: #2a2d28; --km-tree: #3f5d45; --km-tree-line: #6f9573; --km-field: #6b6346;
  --km-k: #2e4239; --km-veleria: #313745; --km-dorsania: #413a2b; --km-foreign-data: #33373a;
  --km-occ: #e0632e; --km-reb: #d55181; --km-front: #ff6b5b; --km-ours: #3fc1b5; --km-union: #ff8a57; --km-league: #5ea3f2;
  --km-seq-0: #3a302a; --km-seq-1: #6e4328; --km-seq-2: #a6562e; --km-seq-3: #da6d3c; --km-seq-4: #ff9d62;
  --km-div-lo: #e0703f; --km-div-mid: #4b4f51; --km-div-hi: #4fb7c0;
  --km-id-karamanian: #2fc28c; --km-id-imperial: #9a8ff0; --km-id-vell: #e0a526;
  --km-panel: rgba(22, 27, 26, 0.94); --km-panel-line: rgba(255, 255, 255, 0.14); --km-shadow: 0 2px 12px rgba(0, 0, 0, 0.5); }
.kmap svg.km-svg { display: block; width: 100%; height: auto; touch-action: none; cursor: grab; }
.kmap svg.km-svg.dragging { cursor: grabbing; }
.kmap .km-region { cursor: pointer; transition: fill 0.35s; }
.kmap .km-region:hover { filter: brightness(1.06); }
.kmap .km-region.sel { stroke: var(--km-ink); stroke-width: 2.4; }
.kmap text { font-family: var(--font-body, "Public Sans", system-ui, sans-serif); paint-order: stroke; stroke: var(--km-halo); stroke-linejoin: round; fill: var(--km-ink); }
.kmap .km-bar { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; padding: 6px; background: var(--km-panel); border-bottom: 1px solid var(--km-panel-line); }
.kmap .km-layers { display: flex; flex-wrap: wrap; gap: 2px; }
.kmap .km-layers button, .kmap .km-zoom button { border: 0; background: transparent; color: var(--km-ink); font: 500 12.5px/1 var(--font-body, system-ui); padding: 6px 9px; border-radius: 6px; cursor: pointer; }
.kmap .km-layers button[aria-pressed="true"] { background: var(--km-ink); color: var(--km-halo); }
.kmap .km-zoom { margin-left: auto; display: flex; gap: 2px; }
.kmap .km-zoom button { font-size: 15px; min-width: 30px; }
.kmap .km-legend { background: var(--km-panel); border-top: 1px solid var(--km-panel-line);
  padding: 8px 12px; font: 12px/1.35 var(--font-body, system-ui); color: var(--km-ink); display: grid; gap: 5px; }
.kmap .km-legend .row { display: flex; flex-wrap: wrap; gap: 4px 12px; align-items: center; }
.kmap .km-legend .sw { width: 12px; height: 12px; border-radius: 3px; display: inline-block; vertical-align: -2px; margin-right: 5px; border: 1px solid var(--km-panel-line); }
.kmap .km-legend .ramp { display: inline-flex; vertical-align: -2px; margin: 0 5px; }
.kmap .km-legend .ramp span { width: 16px; height: 10px; display: inline-block; }
.kmap .km-legend .ttl { font-weight: 600; }
.kmap .km-tip { position: absolute; z-index: 5; pointer-events: none; background: var(--km-panel); color: var(--km-ink); border: 1px solid var(--km-panel-line);
  border-radius: 8px; padding: 9px 11px; font: 12.5px/1.4 var(--font-body, system-ui); box-shadow: var(--km-shadow); min-width: 210px; max-width: 290px; }
.kmap .km-tip h4 { margin: 0 0 2px; font-size: 14px; }
.kmap .km-tip .sub { color: var(--km-ink-2); font-size: 11.5px; margin-bottom: 6px; }
.kmap .km-tip dl { margin: 0; display: grid; grid-template-columns: auto auto; gap: 1px 12px; }
.kmap .km-tip dt { color: var(--km-ink-2); }
.kmap .km-tip dd { margin: 0; text-align: right; font-variant-numeric: tabular-nums; font-weight: 600; }
.kmap .km-tip .bar { display: flex; height: 7px; border-radius: 4px; overflow: hidden; margin: 5px 0 2px; }
.kmap .km-tip .note { margin-top: 5px; color: var(--km-ink-2); font-size: 11.5px; }
.km-card { display: grid; gap: 10px; font-size: 13.5px; }
.km-card h3 { margin: 0; font-size: 17px; }
.km-card .sub { color: var(--ink-2, #555); font-size: 12.5px; }
.km-card dl { margin: 0; display: grid; grid-template-columns: 1fr auto auto; gap: 3px 12px; align-items: baseline; }
.km-card dt { color: var(--ink-2, #555); }
.km-card dd { margin: 0; text-align: right; font-variant-numeric: tabular-nums; font-weight: 600; }
.km-card dd.d { font-weight: 500; font-size: 12px; min-width: 4.5em; }
.km-card .up { color: var(--good-ink, #0a7a0a); } .km-card .down { color: var(--critical-ink, #b42828); } .km-card .flat { color: var(--muted, #888); }
.km-card .stack { display: flex; height: 10px; border-radius: 5px; overflow: hidden; }
.km-card .keys { display: flex; flex-wrap: wrap; gap: 2px 12px; font-size: 12px; color: var(--ink-2, #555); }
.km-card .keys i { display: inline-block; width: 9px; height: 9px; border-radius: 2px; margin-right: 5px; vertical-align: -1px; }
.km-card .k { font-size: 11px; letter-spacing: 0.05em; text-transform: uppercase; color: var(--muted, #888); font-weight: 600; }
`;

  const LAYERS = [
    { id: "control", name: "Control" }, { id: "unrest", name: "Unrest" }, { id: "hunger", name: "Hunger" },
    { id: "approval", name: "Approval" }, { id: "indep", name: "Independence" }, { id: "identity", name: "Identity" },
    { id: "jobs", name: "Jobs" }, { id: "damage", name: "War damage" },
  ];
  const IDENT = ["karamanian", "imperial", "vell"];
  const IDENT_NAME = { karamanian: "Karamanian", imperial: "Imperial", vell: "Vell" };
  const CLASS_NAME = { farmers: "Farmers", workers: "Workers", middle: "Middle class", elite: "Elite" };

  function injectCss() {
    if (document.getElementById("kmap-css")) return;
    const st = document.createElement("style"); st.id = "kmap-css"; st.textContent = CSS;
    document.head.appendChild(st);
  }
  function sv(tag, attrs, parent) {
    const n = document.createElementNS(NS, tag);
    if (attrs) for (const k in attrs) if (attrs[k] !== undefined && attrs[k] !== null) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  }
  function h(tag, attrs, ...kids) {
    const n = document.createElement(tag);
    if (attrs) for (const k in attrs) {
      const v = attrs[k]; if (v === undefined || v === null || v === false) continue;
      if (k === "class") n.className = v; else if (k === "text") n.textContent = v; else if (k === "style") n.style.cssText = v;
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), v); else n.setAttribute(k, v);
    }
    for (const kid of kids.flat(Infinity)) if (kid !== null && kid !== undefined && kid !== false)
      n.appendChild(typeof kid === "string" || typeof kid === "number" ? document.createTextNode(String(kid)) : kid);
    return n;
  }
  const pct = (x, d = 0) => (x === undefined || x === null || isNaN(x)) ? "–" : (x * 100).toFixed(d) + "%";
  const num = x => Math.round(x || 0).toLocaleString("en-US");
  const compact = x => { x = x || 0; const a = Math.abs(x); return a >= 1e6 ? (x / 1e6).toFixed(a >= 1e7 ? 0 : 1) + "M" : a >= 1e4 ? Math.round(x / 1e3) + "K" : a >= 1000 ? (x / 1e3).toFixed(1) + "K" : String(Math.round(x)); };

  function hex2rgb(s) {
    s = (s || "").trim();
    const m = /^#([0-9a-f]{6})$/i.exec(s);
    if (!m) return [128, 128, 128];
    const n = parseInt(m[1], 16);
    return [n >> 16 & 255, n >> 8 & 255, n & 255];
  }
  function mix(a, b, t) { return a.map((v, i) => Math.round(v + (b[i] - v) * t)); }
  const rgb = c => "rgb(" + c.join(",") + ")";

  window.KaramaniyaMap = function (host, opts) {
    injectCss();
    const geo = opts.geo, names = opts.names || {};
    const REG = {}; (opts.regions || []).forEach(r => { REG[r.id] = r; });
    let layer = opts.layer || "control", row = null, prev = null, selected = null;
    let k = 1, tx = 0, ty = 0;

    host.classList.add("kmap");
    host.replaceChildren();
    const svg = sv("svg", { class: "km-svg", viewBox: "0 0 " + geo.w + " " + geo.h, role: "img", "aria-label": "Map of " + (names.island || "the island") }, host);
    const defs = sv("defs", null, svg);
    // Patterns and symbols.
    const hatch = (id, color) => {
      const p = sv("pattern", { id, width: 8, height: 8, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)" }, defs);
      sv("rect", { width: 8, height: 8, fill: color, "fill-opacity": 0.22 }, p);
      sv("line", { x1: 0, y1: 0, x2: 0, y2: 8, stroke: color, "stroke-width": 3.2, "stroke-opacity": 0.85 }, p);
    };
    const uid = "km" + Math.random().toString(36).slice(2, 8);
    hatch(uid + "-occ", "var(--km-occ)"); hatch(uid + "-reb", "var(--km-reb)");
    const glow = sv("radialGradient", { id: uid + "-sea", cx: "50%", cy: "48%", r: "70%" }, defs);
    sv("stop", { offset: "55%", "stop-color": "var(--km-sea)" }, glow); sv("stop", { offset: "100%", "stop-color": "var(--km-sea-2)" }, glow);
    const mtn = sv("symbol", { id: uid + "-mtn", viewBox: "-7 -7 14 9", overflow: "visible" }, defs);
    sv("path", { d: "M-7 2L0 -6L7 2Z", fill: "var(--km-mtn)", stroke: "var(--km-mtn-line)", "stroke-width": 0.8, "stroke-linejoin": "round" }, mtn);
    sv("path", { d: "M0 -6L2.2 -1.4L0.6 -0.6L1.6 2L7 2Z", fill: "var(--km-mtn-shade)" }, mtn);
    const tree = sv("symbol", { id: uid + "-tree", viewBox: "-3 -3 6 6", overflow: "visible" }, defs);
    sv("circle", { r: 2.3, fill: "var(--km-tree)", stroke: "var(--km-tree-line)", "stroke-width": 0.5 }, tree);
    const ship = sv("symbol", { id: uid + "-ship", viewBox: "-8 -5 16 10", overflow: "visible" }, defs);
    sv("path", { d: "M-7 0H7L4.5 3.6H-4.5Z", fill: "currentColor", stroke: "var(--km-halo)", "stroke-width": 0.8 }, ship);
    sv("path", { d: "M-1 0V-4.6L3 0Z", fill: "currentColor", stroke: "var(--km-halo)", "stroke-width": 0.6 }, ship);

    const world = sv("g", { class: "km-world" }, svg);
    sv("rect", { x: -2000, y: -2000, width: geo.w + 4000, height: geo.h + 4000, fill: "url(#" + uid + "-sea)" }, world);
    // Faint depth rings around the coast.
    const gHalo = sv("g", { fill: "none", "stroke-linejoin": "round", "pointer-events": "none" }, world);
    for (const [w, o] of [[34, 0.12], [18, 0.2], [8, 0.32]]) for (const d of geo.coast)
      sv("path", { d, stroke: "var(--km-sea)", "stroke-width": w, opacity: 1, "stroke-opacity": o + 0.5, style: "mix-blend-mode:normal" }, gHalo);
    for (const d of geo.coast) sv("path", { d, stroke: "var(--km-halo)", "stroke-width": 5, "stroke-opacity": 0.35 }, gHalo);
    const gRegions = sv("g", null, world);
    const regionNodes = {};
    for (const id in geo.regions) {
      const p = sv("path", { d: geo.regions[id].path, class: "km-region", "fill-rule": "evenodd", "data-r": id, fill: "var(--km-land)" }, gRegions);
      regionNodes[id] = p;
    }
    const gHatch = sv("g", { "pointer-events": "none" }, world);
    const hatchNodes = {};
    for (const id in geo.regions) hatchNodes[id] = sv("path", { d: geo.regions[id].path, "fill-rule": "evenodd", fill: "none" }, gHatch);
    // Land use and relief (drawn once; muted so the data colours show through).
    const gRelief = sv("g", { "pointer-events": "none", opacity: 0.85 }, world);
    for (const [x, y, a] of geo.fields) {
      const g = sv("g", { transform: "translate(" + x + " " + y + ") rotate(" + a + ")" }, gRelief);
      sv("path", { d: "M-4.5 -2.2h9M-4.5 0h9M-4.5 2.2h9", stroke: "var(--km-field)", "stroke-width": 0.75 }, g);
    }
    for (const [x, y] of geo.forest) sv("use", { href: "#" + uid + "-tree", x: x - 3, y: y - 3, width: 6, height: 6 }, gRelief);
    for (const [x, y] of geo.hills) sv("path", { d: "M" + (x - 4.5) + " " + (y + 1.5) + "q4.5 -5.5 9 0", fill: "none", stroke: "var(--km-mtn-line)", "stroke-width": 0.8, "stroke-linecap": "round" }, gRelief);
    for (const [x, y, s] of geo.mountains.slice().sort((a, b) => a[1] - b[1])) {
      const size = 13 * s;
      sv("use", { href: "#" + uid + "-mtn", x: x - size / 2, y: y - size * 0.55, width: size, height: size * 0.65 }, gRelief);
    }
    const gWater = sv("g", { "pointer-events": "none" }, world);
    for (const d of geo.lakes) sv("path", { d, fill: "var(--km-sea)", stroke: "var(--km-coast)", "stroke-width": 0.8 }, gWater);
    for (const d of geo.shores) sv("path", { d, fill: "none", stroke: "var(--km-coast)", "stroke-width": 0.8 }, gWater);
    for (const d of geo.rivers) sv("path", { d, fill: "none", stroke: "var(--km-river)", "stroke-width": 1.7, "stroke-linecap": "round", "stroke-linejoin": "round" }, gWater);
    const gRoads = sv("g", { fill: "none", "pointer-events": "none", opacity: 0.75 }, world);
    for (const r of geo.roads) sv("path", { d: r.path, stroke: r.rail ? "var(--km-rail)" : "var(--km-road)", "stroke-width": r.minor ? 0.7 : r.rail ? 1.3 : 1.1,
      "stroke-dasharray": r.rail ? "none" : r.minor ? "2 2" : "5 2.5", "stroke-linecap": "round" }, gRoads);
    const gBorders = sv("g", { fill: "none", "pointer-events": "none", "stroke-linecap": "round", "stroke-linejoin": "round" }, world);
    const borderNodes = [];
    for (const b of geo.borders) {
      const n = sv("path", { d: b.path, stroke: b.national ? "var(--km-nation)" : "var(--km-border)", "stroke-width": b.national ? 2.3 : 0.9,
        "stroke-dasharray": b.national ? "8 3.5" : "2.5 2.5", "stroke-opacity": b.national ? 0.85 : 0.7 }, gBorders);
      borderNodes.push({ b, n });
    }
    for (const d of geo.coast) sv("path", { d, stroke: "var(--km-coast)", "stroke-width": 1.2 }, gBorders);
    const gFront = sv("g", { fill: "none", "pointer-events": "none" }, world);
    const gSea = sv("g", { "pointer-events": "none" }, world);
    for (const l of geo.lanes) sv("path", { d: l.path, fill: "none", stroke: "var(--km-coast)", "stroke-width": 1, "stroke-dasharray": "3 4", opacity: 0.8 }, gSea);
    const gSeaDyn = sv("g", { "pointer-events": "none" }, world);
    const gCities = sv("g", { "pointer-events": "none" }, world);
    const cityText = [];
    for (const c of geo.cities) {
      const s = c.kind === "capital" ? 4.6 : c.kind === "city" ? 3.4 : 2.1;
      if (c.kind === "capital") sv("rect", { x: c.x - s, y: c.y - s, width: 2 * s, height: 2 * s, fill: "var(--km-ink)", stroke: "var(--km-halo)", "stroke-width": 1.2 }, gCities);
      else sv("circle", { cx: c.x, cy: c.y, r: s, fill: c.kind === "town" ? "var(--km-halo)" : "var(--km-ink)", stroke: c.kind === "town" ? "var(--km-ink)" : "var(--km-halo)", "stroke-width": c.kind === "town" ? 0.9 : 1.2 }, gCities);
      const t = sv("text", { x: c.x + s + 3, y: c.y + 3.5, "font-size": c.kind === "town" ? 9 : 12.5, "font-weight": c.kind === "town" ? 400 : 600, "stroke-width": 2.6, "data-base": c.kind === "town" ? 9 : 12.5 }, gCities);
      t.textContent = c.name; cityText.push(t);
    }
    const gLabels = sv("g", { "pointer-events": "none" }, world);
    const labelNodes = {};
    for (const id in geo.regions) {
      const g = geo.regions[id], r = REG[id] || { name: id };
      const t = sv("text", { x: g.lx, y: g.ly, "text-anchor": "middle", "font-size": 13, "font-weight": 700, "letter-spacing": 1.6, "stroke-width": 3, "data-base": 13, opacity: 0.8 }, gLabels);
      t.textContent = (r.name || id).toUpperCase();
      const sub = sv("text", { x: g.lx, y: g.ly + 14, "text-anchor": "middle", "font-size": 10.5, "font-weight": 600, "stroke-width": 2.6, "data-base": 10.5 }, gLabels);
      labelNodes[id] = { t, sub };
    }
    const gBadges = sv("g", { "pointer-events": "none" }, world);
    const gMil = sv("g", { "pointer-events": "none" }, world);
    const gPins = sv("g", { "pointer-events": "none" }, world);

    // Controls, legend, tooltip.
    const bar = h("div", { class: "km-bar" });
    const layerBox = h("div", { class: "km-layers", role: "group", "aria-label": "Map layer" });
    const zoomBox = h("div", { class: "km-zoom" },
      h("button", { type: "button", title: "Zoom in", "aria-label": "Zoom in", onclick: () => zoomBy(1.5) }, "+"),
      h("button", { type: "button", title: "Zoom out", "aria-label": "Zoom out", onclick: () => zoomBy(1 / 1.5) }, "−"),
      h("button", { type: "button", title: "Whole island", "aria-label": "Reset zoom", onclick: () => { k = 1; tx = 0; ty = 0; applyZoom(); } }, "⌂"));
    bar.append(layerBox, zoomBox);
    const legend = h("div", { class: "km-legend" });
    const tip = h("div", { class: "km-tip", hidden: true });
    host.insertBefore(bar, svg);
    host.append(legend, tip);

    function renderLayerButtons() {
      layerBox.replaceChildren(...LAYERS.map(L => h("button", { type: "button", "aria-pressed": String(L.id === layer),
        onclick: () => { layer = L.id; renderLayerButtons(); paint(); } }, L.name)));
    }

    // ---- zoom and pan ----
    function applyZoom() {
      k = Math.max(1, Math.min(7, k));
      const maxX = geo.w * (k - 1), maxY = geo.h * (k - 1);
      tx = Math.min(0, Math.max(-maxX, tx)); ty = Math.min(0, Math.max(-maxY, ty));
      world.setAttribute("transform", "translate(" + tx.toFixed(1) + " " + ty.toFixed(1) + ") scale(" + k.toFixed(3) + ")");
      const f = 1 / Math.pow(k, 0.72);
      for (const t of svg.querySelectorAll("text[data-base]")) t.setAttribute("font-size", (Number(t.getAttribute("data-base")) * f).toFixed(2));
      gCities.querySelectorAll("text").forEach(t => { if (Number(t.getAttribute("data-base")) < 10) t.style.display = k < 1.25 ? "none" : ""; });
      layoutMarkers(f);
    }
    // Put every marker (counters, badges, pins) near its anchor without covering names or each other.
    // Most important first; each tries a ring of nearby spots and keeps the first free one.
    const SPOTS = [[0, 0], [0, 1], [0, -1], [1, 0], [-1, 0], [1, 1], [-1, 1], [1, -1], [-1, -1], [0, 2], [0, -2], [2, 0], [-2, 0],
      [2, 1], [-2, 1], [2, -1], [-2, -1], [0, 3], [0, -3], [1, 2], [-1, 2], [1, -2], [-1, -2], [3, 0], [-3, 0],
      [2, 2], [-2, 2], [2, -2], [-2, -2], [0, 4], [0, -4], [3, 1], [-3, 1], [3, -1], [-3, -1]];
    const boxCache = new WeakMap();
    function layoutMarkers(f) {
      const hit = (a, b) => Math.min(a[0] + a[2], b[0] + b[2]) - Math.max(a[0], b[0]) > 1 && Math.min(a[1] + a[3], b[1] + b[3]) - Math.max(a[1], b[1]) > 1;
      const taken = [];
      for (const t of [...gLabels.querySelectorAll("text"), ...gCities.querySelectorAll("text")]) {
        if (!t.textContent || t.style.display === "none") continue;
        try { const b = t.getBBox(); if (b.width) taken.push([b.x, b.y, b.width, b.height]); } catch (e) { /* not laid out yet */ }
      }
      for (const c of geo.cities) taken.push([c.x - 5, c.y - 5, 10, 10]);
      const marks = [...svg.querySelectorAll("[data-anchor]")].sort((a, b) => Number(a.getAttribute("data-prio")) - Number(b.getAttribute("data-prio")));
      for (const m of marks) {
        const [ax, ay] = m.getAttribute("data-anchor").split(",").map(Number);
        let bb = boxCache.get(m);
        if (!bb) { try { const b = m.getBBox(); bb = [b.x, b.y, b.width, b.height]; } catch (e) { bb = [-10, -8, 20, 16]; } boxCache.set(m, bb); }
        const w = bb[2] * f, hgt = bb[3] * f;
        let spot = null;
        for (const [sx, sy] of SPOTS) {
          const x = ax + sx * (w / 2 + 5), y = ay + sy * (hgt + 4);
          const box = [x + bb[0] * f, y + bb[1] * f, w, hgt];
          if (!taken.some(o => hit(o, box))) { spot = [x, y, box]; break; }
        }
        if (!spot) spot = [ax, ay, [ax + bb[0] * f, ay + bb[1] * f, w, hgt]];
        m.setAttribute("transform", "translate(" + spot[0].toFixed(1) + " " + spot[1].toFixed(1) + ") scale(" + f.toFixed(3) + ")");
        taken.push(spot[2]);
      }
    }
    function toMap(ev) { const r = svg.getBoundingClientRect(); return [(ev.clientX - r.left) / r.width * geo.w, (ev.clientY - r.top) / r.height * geo.h]; }
    function zoomBy(f, at) {
      const [cx, cy] = at || [geo.w / 2, geo.h / 2];
      const nk = Math.max(1, Math.min(7, k * f)); const r = nk / k;
      tx = cx - (cx - tx) * r; ty = cy - (cy - ty) * r; k = nk; applyZoom();
    }
    svg.addEventListener("wheel", ev => { ev.preventDefault(); zoomBy(ev.deltaY < 0 ? 1.25 : 0.8, toMap(ev)); }, { passive: false });
    let drag = null, moved = false;
    svg.addEventListener("pointerdown", ev => { drag = { p: toMap(ev), tx, ty }; moved = false; });
    svg.addEventListener("pointermove", ev => {
      if (drag && (ev.buttons & 1)) {
        const p = toMap(ev), dx = p[0] - drag.p[0], dy = p[1] - drag.p[1];
        if (Math.abs(dx) + Math.abs(dy) > 3) { moved = true; svg.classList.add("dragging"); tip.hidden = true; }
        if (moved) { tx = drag.tx + dx; ty = drag.ty + dy; applyZoom(); return; }
      }
      hover(ev);
    });
    const endDrag = () => { drag = null; svg.classList.remove("dragging"); };
    svg.addEventListener("pointerup", ev => {
      if (!moved) { const t = ev.target.closest && ev.target.closest(".km-region"); if (t) select(t.getAttribute("data-r"), true); }
      endDrag();
    });
    svg.addEventListener("pointerleave", () => { endDrag(); tip.hidden = true; });

    // ---- colours ----
    const cssv = name => getComputedStyle(host).getPropertyValue(name).trim();
    function seqColor(t) {
      t = Math.max(0, Math.min(1, t)) * 4; const i = Math.min(3, Math.floor(t));
      return rgb(mix(hex2rgb(cssv("--km-seq-" + i)), hex2rgb(cssv("--km-seq-" + (i + 1))), t - i));
    }
    function divColor(t) {  // t in 0..1, 0.5 neutral
      t = Math.max(0, Math.min(1, t));
      return t < 0.5 ? rgb(mix(hex2rgb(cssv("--km-div-lo")), hex2rgb(cssv("--km-div-mid")), t / 0.5))
                     : rgb(mix(hex2rgb(cssv("--km-div-mid")), hex2rgb(cssv("--km-div-hi")), (t - 0.5) / 0.5));
    }
    const nationVar = n => n === "karamaniya" ? "var(--km-k)" : n === "veleria" ? "var(--km-veleria)" : n === "dorsania" ? "var(--km-dorsania)" : "var(--km-land)";

    function detail(id) { return row && row.region_detail ? row.region_detail[id] : null; }
    function regState(id) { return row && row.regions ? row.regions[id] : null; }
    function controllerOf(id) { const s = regState(id); return s ? s.controller : (REG[id] || {}).nation; }
    function frontFieldStrength(fr) { return Number(fr.ours_effective ?? fr.ours) || 0; }

    const LAYER_VALUE = {
      unrest: d => d.unrest, hunger: d => Math.min(1, d.hunger / 0.4), approval: d => d.approval, indep: d => d.indep,
      jobs: d => Math.min(1, d.unemployment / 0.35),
    };
    function fillFor(id) {
      const r = REG[id] || {}; const d = detail(id); const s = regState(id);
      const own = r.nation === "karamaniya";
      if (layer === "control" || !own) {
        if (!own) return layer === "control" ? nationVar(r.nation) : "var(--km-foreign-data)";
        if (s && s.controller === "union") return "var(--km-veleria)";
        return nationVar("karamaniya");
      }
      if (!d) return "var(--km-foreign-data)";
      if (layer === "damage") return seqColor(s ? s.damage : 0);
      if (layer === "identity") {
        const top = IDENT.reduce((a, b) => (d.ident[b] || 0) > (d.ident[a] || 0) ? b : a, IDENT[0]);
        const share = d.ident[top] || 0;
        return rgb(mix(hex2rgb(cssv("--km-land")), hex2rgb(cssv("--km-id-" + top)), 0.25 + 0.75 * Math.max(0, (share - 0.34) / 0.66)));
      }
      const f = LAYER_VALUE[layer];
      if (layer === "approval" || layer === "indep") return divColor(f(d));
      return seqColor(f(d));
    }
    function layerText(id) {
      const d = detail(id), s = regState(id), r = REG[id] || {};
      if (r.nation !== "karamaniya") return layer === "control" ? ({ veleria: names.veleria || "Veleria", dorsania: names.dorsania || "Dorsania" })[r.nation] || "" : "";
      if (s && s.controller === "union") return "occupied by the Union";
      if (s && s.controller === "rebels") return "held by rebels";
      if (!d) return "";
      switch (layer) {
        case "control": return "government · pop " + compact(d.pop);
        case "unrest": return "unrest " + pct(d.unrest);
        case "hunger": return "hunger " + pct(d.hunger);
        case "approval": return "approval " + pct(d.approval);
        case "indep": return "for independence " + pct(d.indep);
        case "identity": { const top = IDENT.reduce((a, b) => (d.ident[b] || 0) > (d.ident[a] || 0) ? b : a, IDENT[0]); return IDENT_NAME[top] + " " + pct(d.ident[top]); }
        case "jobs": return "jobless " + pct(d.unemployment);
        case "damage": return "war damage " + pct(s ? s.damage : 0);
      }
      return "";
    }

    function renderLegend() {
      const rows = [];
      const sw = (c, label) => h("span", null, h("span", { class: "sw", style: "background:" + c }), label);
      const ramp = (fn, lo, hi, label) => h("span", null, h("span", { class: "ttl", text: label + " " }), lo, h("span", { class: "ramp" }, [0, 0.25, 0.5, 0.75, 1].map(t => h("span", { style: "background:" + fn(t) }))), hi);
      const hatchCss = v => "repeating-linear-gradient(45deg, var(" + v + ") 0 3px, transparent 3px 6px)";
      const occupiedSw = [sw(hatchCss("--km-occ"), "occupied by the " + (names.union || "Union")), sw(hatchCss("--km-reb"), "held by rebels")];
      if (layer === "control") rows.push(h("div", { class: "row" }, sw("var(--km-k)", names.k || "Karamaniya"), sw("var(--km-veleria)", names.veleria || "Veleria"),
        sw("var(--km-dorsania)", names.dorsania || "Dorsania"), occupiedSw));
      else if (layer === "unrest") rows.push(h("div", { class: "row" }, ramp(seqColor, "calm", "uprising", "Unrest")));
      else if (layer === "hunger") rows.push(h("div", { class: "row" }, ramp(seqColor, "fed", "40%+ hungry", "Hunger")));
      else if (layer === "approval") rows.push(h("div", { class: "row" }, ramp(divColor, "0%", "100%", "Approval of the government")));
      else if (layer === "indep") rows.push(h("div", { class: "row" }, ramp(divColor, "for union", "for independence", "Support")));
      else if (layer === "identity") rows.push(h("div", { class: "row" }, h("span", { class: "ttl", text: "Largest group" }), IDENT.map(i => sw("var(--km-id-" + i + ")", IDENT_NAME[i]))));
      else if (layer === "jobs") rows.push(h("div", { class: "row" }, ramp(seqColor, "0%", "35%+", "Unemployment")));
      else if (layer === "damage") rows.push(h("div", { class: "row" }, ramp(seqColor, "none", "ruined", "War damage")));
      if (layer !== "control") rows.push(h("div", { class: "row" }, occupiedSw));
      rows.push(h("div", { class: "row" },
        h("span", null, h("span", { class: "sw", style: "background:var(--km-ours)" }), "our troops"),
        h("span", null, h("span", { class: "sw", style: "background:var(--km-union)" }), "Union"),
        h("span", null, h("span", { class: "sw", style: "background:var(--km-league)" }), names.league || "League"),
        h("span", null, h("span", { class: "sw", style: "background:var(--km-front)" }), "front line, fighting"),
        h("span", null, "▲ mountains · ■ capital · ● city · ○ town · numbered pins: this month's events")));
      legend.replaceChildren(...rows);
    }

    // ---- dynamic overlays ----
    const cityOf = {}; for (const c of geo.cities) if (c.kind !== "town") cityOf[c.region] = c;
    function borderBetween(test) { return geo.borders.filter(b => test(b.a, b.b) || test(b.b, b.a)); }

    function counter(parent, x, y, color, lines, title, prio) {
      const g = sv("g", { "data-anchor": x + "," + y, "data-prio": prio === undefined ? 1 : prio }, parent);
      const w = Math.max(...lines.map(l => l.length)) * 6.4 + 26, hgt = 13 + lines.length * 12;
      sv("rect", { x: -w / 2, y: -hgt / 2, width: w, height: hgt, rx: 3, fill: "var(--km-halo)", stroke: color, "stroke-width": 1.8 }, g);
      // NATO-style infantry mark
      sv("rect", { x: -w / 2 + 5, y: -6, width: 14, height: 12, fill: color, rx: 1 }, g);
      sv("path", { d: "M" + (-w / 2 + 5) + " -6l14 12M" + (-w / 2 + 19) + " -6l-14 12", stroke: "var(--km-halo)", "stroke-width": 1.2 }, g);
      lines.forEach((l, i) => {
        const t = sv("text", { x: -w / 2 + 23, y: -hgt / 2 + 16 + i * 12, "font-size": i ? 9.5 : 11, "font-weight": i ? 500 : 700, "stroke-width": 0, fill: i ? "var(--km-ink-2)" : "var(--km-ink)" }, g);
        t.textContent = l;
      });
      if (title) { const tt = sv("title", null, g); tt.textContent = title; }
      return g;
    }
    const BADGE = { red: ["#c0392b", "#fff"], orange: ["#c9612f", "#fff"], dark: ["#33414a", "#fff"], occ: ["#c4541f", "#fff"],
      reb: ["#b8487a", "#fff"], union: ["#a8421b", "#fff"] };
    function badge(parent, x, y, text, kind, prio) {
      const [bg, fg] = BADGE[kind] || BADGE.dark;
      const g = sv("g", { "data-anchor": x + "," + y, "data-prio": prio === undefined ? 5 : prio }, parent);
      const w = text.length * 5.5 + 12;
      sv("rect", { x: -w / 2, y: -7.5, width: w, height: 15, rx: 7.5, fill: bg, stroke: "var(--km-halo)", "stroke-width": 1.2 }, g);
      const t = sv("text", { x: 0, y: 3.4, "text-anchor": "middle", "font-size": 9.3, "font-weight": 700, "stroke-width": 0, fill: fg, "letter-spacing": 0.3 }, g);
      t.textContent = text;
      return g;
    }

    function paintMilitary() {
      gMil.replaceChildren(); gFront.replaceChildren(); gSeaDyn.replaceChildren();
      if (!row) return;
      const fronts = row.fronts || {};
      const enemyNations = new Set(["veleria", "dorsania"]);
      // Front lines: where land held by us meets land held by the Union or rebels (and the old borders once at war).
      for (const { b } of borderNodes) {
        const ca = controllerOf(b.a), cb = controllerOf(b.b);
        const hostile = x => x === "union" || x === "rebels" || enemyNations.has(x);
        const line = (ca === "karamaniya" && hostile(cb)) || (cb === "karamaniya" && hostile(ca));
        if (!line) continue;
        const active = row.war && !row.ceasefire;
        if (!active && !(ca === "union" || cb === "union" || ca === "rebels" || cb === "rebels")) continue;
        sv("path", { d: b.path, stroke: "var(--km-front)", "stroke-width": 7, "stroke-opacity": 0.22, "stroke-linecap": "round" }, gFront);
        sv("path", { d: b.path, stroke: "var(--km-front)", "stroke-width": 2.4, "stroke-dasharray": active ? "1 5" : "6 4", "stroke-linecap": "round" }, gFront);
      }
      // Army counters on each front, the Union across from them.
      for (const f of ["north", "east"]) {
        const fr = fronts[f]; if (!fr || !fr.region) continue;
        const city = cityOf[fr.region]; const g = geo.regions[fr.region]; if (!g) continue;
        const bs = borderBetween((a, b2) => a === fr.region && (controllerOf(b2) === "union" || enemyNations.has(controllerOf(b2))));
        let bx, by, ex, ey;
        if (bs.length) {
          const mid = bs.reduce((acc, b) => [acc[0] + b.mid[0], acc[1] + b.mid[1]], [0, 0]).map(v => v / bs.length);
          bx = mid[0]; by = mid[1];
          const other = bs[0].a === fr.region ? bs[0].b : bs[0].a; const og = geo.regions[other];
          const vx = (og ? og.lx : bx) - bx, vy = (og ? og.ly : by) - by, L = Math.hypot(vx, vy) || 1;
          ex = bx + vx / L * 58; ey = by + vy / L * 58;
          bx -= vx / L * 56; by -= vy / L * 56;
        } else { bx = (city || g).x || g.lx; by = ((city || g).y || g.ly) - 30; ex = bx; ey = by - 60; }
        const fortTxt = "fort " + pct(fr.fort) + (fr.progress > 0.005 ? " · pushed " + pct(fr.progress) : "");
        const ourStrength = frontFieldStrength(fr);
        counter(gMil, bx, by, "var(--km-ours)", [compact(ourStrength), fortTxt],
          "Our " + f + " front at " + ((REG[fr.region] || {}).name || fr.region) + ": " + num(ourStrength) + " effective field strength, fortifications " + pct(fr.fort), 0);
        if (fr.union > 0) {
          counter(gMil, ex, ey, "var(--km-union)", [compact(fr.union), fr.combat ? "attacking" : "massed"],
            (names.union || "Union") + " forces on the " + f + " front: " + num(fr.union), 1);
          if (fr.progress > 0.01) {
            const L = Math.hypot(bx - ex, by - ey) || 1, ux = (bx - ex) / L, uy = (by - ey) / L;
            const len = 18 + 60 * Math.min(1, fr.progress);
            const x2 = ex + ux * (26 + len), y2 = ey + uy * (26 + len);
            sv("path", { d: "M" + (ex + ux * 24) + " " + (ey + uy * 24) + "L" + x2 + " " + y2, stroke: "var(--km-union)", "stroke-width": 5, "stroke-linecap": "round", opacity: 0.85 }, gFront);
            sv("path", { d: "M" + (x2 + ux * 9) + " " + (y2 + uy * 9) + "L" + (x2 - uy * 7) + " " + (y2 + ux * 7) + "L" + (x2 + uy * 7) + " " + (y2 - ux * 7) + "Z", fill: "var(--km-union)" }, gFront);
          }
        }
        if (fr.combat) {
          const cx = (bx + ex) / 2, cy = (by + ey) / 2;
          const star = [];
          for (let i = 0; i < 16; i++) { const r = i % 2 ? 5 : 12, a = Math.PI * i / 8; star.push((cx + r * Math.cos(a)).toFixed(1) + " " + (cy + r * Math.sin(a)).toFixed(1)); }
          sv("path", { d: "M" + star.join("L") + "Z", fill: "var(--km-front)", stroke: "var(--km-halo)", "stroke-width": 1.2 }, gMil);
          const nx = -(ey - by), ny = ex - bx, NL = Math.hypot(nx, ny) || 1;
          badge(gMil, cx + nx / NL * 34, cy + ny / NL * 34, "lost " + compact(fr.combat.k_loss) + " · they " + compact(fr.combat.u_loss), "red", 2);
        }
      }
      // The capital's garrison.
      const cap = geo.cities.find(c => c.kind === "capital" && (REG[c.region] || {}).nation === "karamaniya");
      if (cap && row.garrison > 0) counter(gMil, cap.x - 58, cap.y - 4, "var(--km-ours)", [compact(row.garrison), "garrison"], "Held back to guard the capital", 3);
      // Union armies massing before the war, at their capitals.
      if (row.union_formed && row.union_army > 0) {
        const fr = fronts || {}; const onFront = (fr.north ? fr.north.union : 0) + (fr.east ? fr.east.union : 0);
        const rest = Math.max(0, row.union_army - onFront);
        const caps = geo.cities.filter(c => c.kind === "capital" && (REG[c.region] || {}).nation !== "karamaniya");
        if (rest > 500 && caps.length) caps.forEach(c => counter(gMil, c.x, c.y - 26, "var(--km-union)", [compact(rest / caps.length), "reserve"], "Union troops not on a front", 3));
      }
      // At sea: our navy, the blockade, League convoys.
      const lanes = geo.lanes;
      const shipAt = (x, y, color, n, label, dx, dy) => {
        for (let i = 0; i < n; i++) {
          const ox = x + (i % 3) * 13 - 13 + (dx || 0) * Math.floor(i / 3) * 12, oy = y + Math.floor(i / 3) * 9 + (dy || 0) * Math.floor(i / 3) * 12;
          sv("use", { href: "#" + uid + "-ship", x: ox - 8, y: oy - 5, width: 16, height: 10, style: "color:" + color }, gSeaDyn);
        }
        if (label) { const t = sv("text", { x: x, y: y + 18 + Math.floor((n - 1) / 3) * 9, "text-anchor": "middle", "font-size": 9.5, "font-weight": 700, "stroke-width": 2.4, fill: color, "data-base": 9.5 }, gSeaDyn); t.textContent = label; }
      };
      const navyN = Math.max(0, Math.min(9, Math.round(row.navy || 0)));
      const mission = (row.policy || {}).navy_mission || "patrol";
      lanes.forEach((l, i) => {
        const blk = row.blockade_eff || 0;
        if (i === 0 && navyN) shipAt(l.x - l.dx * 22, l.y - l.dy * 22, "var(--km-ours)", Math.min(navyN, 6), navyN + " warships · " + mission.replace("_", " "));
        if (blk > 0.02) shipAt(l.x + l.dx * 40, l.y + l.dy * 40, "var(--km-union)", Math.max(1, Math.round(blk * 6)), "blockade " + pct(blk));
        const lg = row.league || {};
        if (lg.escort || lg.alliance || (lg.aid || 0) > 0) shipAt(l.x + l.dx * 95, l.y + l.dy * 95, "var(--km-league)", lg.escort ? 3 : 2, i === 0 ? (lg.escort ? "League convoy + escort" : "League convoy") : "");
      });
      // Embargoes on the land borders.
      if ((row.grain_embargo || 0) > 0.02 || (row.coal_embargo || 0) > 0.02) {
        const nb = geo.borders.filter(b => b.national && ((REG[b.a] || {}).nation === "karamaniya" || (REG[b.b] || {}).nation === "karamaniya"));
        const frontRegions = Object.values(fronts).map(v => v && v.region).filter(Boolean);
        const far = b => Math.min(...frontRegions.map(id => { const g2 = geo.regions[id]; return g2 ? Math.hypot(b.mid[0] - g2.lx, b.mid[1] - g2.ly) : 999; }), 999);
        if (nb.length) {
          const b = nb.slice().sort((x, y) => far(y) - far(x))[0];
          const txt = [(row.grain_embargo || 0) > 0.02 ? "grain −" + pct(row.grain_embargo) : "", (row.coal_embargo || 0) > 0.02 ? "coal −" + pct(row.coal_embargo) : ""].filter(Boolean).join(" · ");
          badge(gMil, b.mid[0], b.mid[1] - 16, "EMBARGO " + txt, "union", 4);
        }
      }
    }

    function paintBadges() {
      gBadges.replaceChildren();
      if (!row) return;
      for (const id in geo.regions) {
        const r = REG[id]; if (!r || r.nation !== "karamaniya") continue;
        const d = detail(id), s = regState(id) || {}, g = geo.regions[id];
        const tags = [];
        if (s.controller === "union") tags.push(["OCCUPIED", "occ"]);
        if (s.controller === "rebels" || (d && d.rebels > 0)) tags.push(["REBELS", "reb"]);
        if (d && d.unrest > 0.45) tags.push(["UPRISING", "red"]); else if (d && d.unrest > 0.3) tags.push(["PROTESTS", "orange"]);
        if (d && d.hunger > 0.12) tags.push(["HUNGER " + pct(d.hunger), "orange"]);
        if (d && d.repression > 0.08) tags.push(["CRACKDOWN", "dark"]);
        if (r.capital && row.constitution && row.constitution.emergency) tags.push(["MARTIAL LAW", "dark"]);
        if ((s.strike || 0) > 0.05) tags.push(["STRIKE " + pct(s.strike), "orange"]);
        if (d && d.interned > 500) tags.push(["INTERNED " + compact(d.interned), "dark"]);
        tags.splice(3);
        let y = g.ly + 30;
        const perRow = 2;
        tags.forEach((t, i) => {
          const col = i % perRow, rowN = Math.floor(i / perRow);
          const count = Math.min(perRow, tags.length - rowN * perRow);
          const x = g.lx + (col - (count - 1) / 2) * 74;
          badge(gBadges, x, y + rowN * 18, t[0], t[1]);
        });
      }
    }

    function paintPins(pinsOn) {
      gPins.replaceChildren();
      const out = [];
      if (!row || !pinsOn) return out;
      const places = [];
      for (const c of geo.cities) places.push({ name: c.name, x: c.x, y: c.y });
      for (const id in geo.regions) { const r = REG[id]; if (r) places.push({ name: r.name, x: geo.regions[id].lx, y: geo.regions[id].ly }); }
      places.sort((a, b) => b.name.length - a.name.length);
      const used = {};
      (row.events || []).filter(e => e.public !== false).forEach(e => {
        const text = e.text || "";
        const p = places.find(pl => text.includes(pl.name));
        if (!p) return;
        const n = out.length + 1; const key = p.name; const stack = used[key] = (used[key] || 0) + 1;
        const x = p.x + 10 + (stack - 1) * 16, y = p.y - 16;
        const g = sv("g", { "data-anchor": x + "," + y, "data-prio": 6 }, gPins);
        sv("path", { d: "M0 9L-6 -1A7 7 0 1 1 6 -1Z", fill: (e.importance || 1) >= 3 ? "var(--km-front)" : "var(--km-ink)", stroke: "var(--km-halo)", "stroke-width": 1.2, transform: "translate(0 -4)" }, g);
        const t = sv("text", { x: 0, y: -2.5, "text-anchor": "middle", "font-size": 8.5, "font-weight": 700, "stroke-width": 0, fill: "var(--km-halo)" }, g);
        t.textContent = String(n);
        const tt = sv("title", null, g); tt.textContent = text;
        out.push({ n, text, place: p.name, importance: e.importance || 1, kind: e.kind });
      });
      return out;
    }

    function paint() {
      for (const id in regionNodes) {
        regionNodes[id].setAttribute("fill", fillFor(id));
        const c = controllerOf(id);
        hatchNodes[id].setAttribute("fill", c === "union" && (REG[id] || {}).nation === "karamaniya" ? "url(#" + uid + "-occ)" : c === "rebels" ? "url(#" + uid + "-reb)" : "none");
        const lab = labelNodes[id]; if (lab) lab.sub.textContent = layerText(id);
      }
      renderLegend();
    }

    // ---- hover and selection ----
    function nationStats(nation) {
      const n = ((row || {}).nations || {})[nation];
      if (!n) return null;
      const own = nation === "karamaniya";
      const fields = [["Population", num(n.population)], ["Annual output", num(n.output_annual) + " base crowns"],
        ["Output / person", num(n.output_per_person) + " base crowns"], [own ? "Standing army" : "Army", num(n.army)], ["Navy", num(n.navy)]];
      if (own && row && row.army_mobilized !== undefined && row.army_mobilized !== null) {
        fields.push(["Mobilized reserves", num(row.army_mobilized)]);
        fields.push(["Effective field strength", num(row.army_field_total ?? ((row.army || 0) + (row.army_mobilized_effective || 0)))]);
      }
      if (n.unemployment !== undefined) fields.push(["Unemployment", pct(n.unemployment)], ["Food / need", pct(n.food_ratio)],
        [nation === "karamaniya" && row && row.month < 12
          ? `Inflation, annualized (${row.month + 1} mo)` : "Inflation, year on year", pct(n.inflation_yoy)]);
      if (n.monthly_printing !== undefined) fields.push(["Money printed / month", pct(n.monthly_printing)]);
      if (nation !== "karamaniya") fields.push(["Readiness", pct(n.readiness || 0)], ["Morale", pct(n.morale || 0)],
        ["Supply", pct(n.supply || 0)], ["Fortification", pct(n.fortification || 0)],
        ["Last movement", n.last_movement || "no recent movement reported"], ["Visible mission", n.visible_mission || "border security"]);
      return h("div", null, h("div", { class: "k", text: "Country · modelled" }),
        h("dl", null, fields.map(([key, value]) => [h("dt", { text: key }), h("dd", { text: value }), h("dd", { class: "d" })])),
        h("p", { class: "sub", text: "Base crowns are a common starting-price unit, not real-world dollars." }));
    }
    function tipFor(id) {
      const r = REG[id] || { name: id }, d = detail(id), s = regState(id) || {};
      const parts = [h("h4", { text: r.name })];
      const nation = r.nation === "karamaniya" ? (names.k || "Karamaniya") : r.nation === "veleria" ? (names.veleria || "Veleria") : (names.dorsania || "Dorsania");
      const ctrl = s.controller === "union" ? "occupied by the " + (names.union || "Union") : s.controller === "rebels" ? "held by rebels" : "";
      parts.push(h("div", { class: "sub", text: nation + (ctrl ? " · " + ctrl : "") + (r.capital ? " · capital" : "") }));
      if (d) {
        const rows = [["Population", num(d.pop)], ["Approval", pct(d.approval)], ["Unrest", pct(d.unrest)], ["Hunger", pct(d.hunger)],
          ["For independence", pct(d.indep)], ["Fear", pct(d.fear)], ["Unemployment", pct(d.unemployment)], ["Real income", pct(d.income)],
          ["On strike", pct(s.strike || 0)], ["War damage", pct(s.damage || 0)]];
        if (d.conscripted) rows.push(["In the army", num(d.conscripted)]);
        if (d.interned) rows.push(["Interned", num(d.interned)]);
        if (d.rebels) rows.push(["Armed rebels", num(d.rebels)]);
        parts.push(h("dl", null, rows.map(([k2, v]) => [h("dt", { text: k2 }), h("dd", { text: v })])));
        parts.push(h("div", { class: "bar", title: "Identity" }, IDENT.map(i => h("span", { style: "width:" + (100 * (d.ident[i] || 0)).toFixed(1) + "%;background:var(--km-id-" + i + ")" }))));
        parts.push(h("div", { class: "note", text: IDENT.map(i => IDENT_NAME[i] + " " + pct(d.ident[i])).join(" · ") }));
        const fr = Object.entries(row.fronts || {}).find(([, v]) => v.region === id);
        if (fr) parts.push(h("div", { class: "note", text: "Front line (" + fr[0] + "): " + num(frontFieldStrength(fr[1])) + " effective field strength against " + num(fr[1].union) + " Union; fortified " + pct(fr[1].fort) + "." }));
      } else if (r.population) {
        const n = ((row || {}).nations || {})[r.nation];
        parts.push(h("dl", null, h("dt", { text: "Region population" }), h("dd", { text: num(r.population) }),
          n ? [h("dt", { text: "Country output / person" }), h("dd", { text: num(n.output_per_person) + " base crowns" })] : null));
      }
      parts.push(h("div", { class: "note", text: "Click for everything about this region." }));
      return parts;
    }
    function hover(ev) {
      const t = ev.target.closest && ev.target.closest(".km-region");
      if (!t || !row) { tip.hidden = true; return; }
      tip.replaceChildren(...tipFor(t.getAttribute("data-r"))); tip.hidden = false;
      const hr = host.getBoundingClientRect(), tw = tip.offsetWidth, th = tip.offsetHeight;
      let x = ev.clientX - hr.left + 16, y = ev.clientY - hr.top + 16;
      if (x + tw > hr.width - 6) x = ev.clientX - hr.left - tw - 16;
      if (y + th > hr.height - 6) y = Math.max(6, hr.height - th - 6);
      tip.style.left = Math.max(6, x) + "px"; tip.style.top = Math.max(6, y) + "px";
    }
    function select(id, fromUser) {
      selected = selected === id && fromUser ? null : id;
      for (const k2 in regionNodes) regionNodes[k2].classList.toggle("sel", k2 === selected);
      if (opts.onSelect) opts.onSelect(selected);
    }

    // A full card for one region, with the change since last month. Good news is green whichever way it moves.
    const CARD_ROWS = [
      ["pop", "Population", v => num(v), 1], ["approval", "Approval", v => pct(v), 1], ["unrest", "Unrest", v => pct(v), -1],
      ["hunger", "Hunger", v => pct(v, 1), -1], ["indep", "For independence", v => pct(v), 0], ["fear", "Fear", v => pct(v), -1],
      ["grievance", "Grievance (of 1.2)", v => v.toFixed(2), -1], ["unemployment", "Unemployment", v => pct(v, 1), -1],
      ["income", "Real income", v => pct(v), 1], ["savings", "Savings", v => pct(v), 1], ["conscripted", "In the army", v => num(v), 0],
      ["interned", "Interned", v => num(v), -1], ["rebels", "Armed rebels", v => num(v), -1]];
    function card(id) {
      const r = REG[id] || { name: id }, d = detail(id), s = regState(id) || {};
      const pd = prev && prev.region_detail ? prev.region_detail[id] : null, ps = prev && prev.regions ? prev.regions[id] || {} : {};
      const nation = r.nation === "karamaniya" ? (names.k || "Karamaniya") : r.nation === "veleria" ? (names.veleria || "Veleria") : (names.dorsania || "Dorsania");
      const ctrl = s.controller === "union" ? "occupied by the " + (names.union || "Union") : s.controller === "rebels" ? "held by rebels" : r.nation === "karamaniya" ? "held by the government" : "";
      const out = [h("div", null, h("div", { class: "k", text: nation + (r.capital ? " · capital" : "") }), h("h3", { text: r.name }), h("div", { class: "sub", text: ctrl }))];
      if (!d) {
        if (r.population) out.push(h("dl", null, h("dt", { text: "Region population" }), h("dd", { text: num(r.population) }), h("dd", { class: "d" })));
        const country = nationStats(r.nation); if (country) out.push(country);
        out.push(h("p", { class: "sub", text: "The simulation tracks people in detail only inside " + (names.k || "Karamaniya") + ". Rival totals are simplified." }));
        return h("div", { class: "km-card" }, out);
      }
      const change = (key, cur, before, good, isPct) => {
        if (before === undefined || before === null) return h("dd", { class: "d flat", text: "" });
        const diff = cur - before;
        const index = key === "grievance";
        if (Math.abs(diff) < (index ? 0.005 : isPct ? 0.0005 : 0.5)) return h("dd", { class: "d flat", text: "=" });
        const txt = (diff > 0 ? "+" : "−") + (index ? Math.abs(diff).toFixed(2) : isPct ? (Math.abs(diff) * 100).toFixed(1) + " pt" : num(Math.abs(diff)));
        const cls = good === 0 ? "flat" : (diff > 0) === (good > 0) ? "up" : "down";
        return h("dd", { class: "d " + cls, text: txt });
      };
      const rows = [];
      for (const [key, label, fmt, good] of CARD_ROWS) {
        const v = d[key]; if (v === undefined || ((key === "interned" || key === "rebels" || key === "conscripted") && !v)) continue;
        const isPct = key !== "pop" && key !== "conscripted" && key !== "interned" && key !== "rebels";
        rows.push(h("dt", { text: label }), h("dd", { text: fmt(v) }), change(key, v, pd ? pd[key] : undefined, good, isPct));
      }
      rows.push(h("dt", { text: "On strike" }), h("dd", { text: pct(s.strike || 0) }), change("strike", s.strike || 0, ps.strike, -1, true));
      rows.push(h("dt", { text: "War damage" }), h("dd", { text: pct(s.damage || 0) }), change("damage", s.damage || 0, ps.damage, -1, true));
      out.push(h("dl", null, rows));
      const founding = d.founding_problems || [];
      if (founding.length) out.push(h("div", { class: "map-issue" },
        h("div", { class: "k", text: "Inherited issues in this region" }),
        h("ul", { style: "margin:4px 0 0;padding-left:18px" }, founding.map(p => h("li", null,
          h("b", { text: p.title + " · " + p.severity + "/100" }), " — " + p.trend.replace(/_/g, " ") +
          (p.neglect_months ? "; " + p.neglect_months + " months without improvement" : ""))))));
      if (r.capital) { const country = nationStats(r.nation); if (country) out.push(country); }
      const idc = i => cssv("--km-id-" + i);
      out.push(h("div", null, h("div", { class: "k", text: "Who lives here" }),
        h("div", { class: "stack" }, IDENT.map(i => h("span", { style: "width:" + (100 * (d.ident[i] || 0)).toFixed(1) + "%;background:" + idc(i) }))),
        h("div", { class: "keys" }, IDENT.map(i => h("span", null, h("i", { style: "background:" + idc(i) }), IDENT_NAME[i] + " " + pct(d.ident[i]))))));
      const clsKeys = Object.keys(d.cls || {});
      const shade = t => rgb(mix(hex2rgb(cssv("--km-seq-1")), hex2rgb(cssv("--km-seq-4")), t));
      out.push(h("div", null, h("div", { class: "k", text: "By class" }),
        h("div", { class: "stack" }, clsKeys.map((c, i) => h("span", { style: "width:" + (100 * d.cls[c]).toFixed(1) + "%;background:" + shade(i / Math.max(1, clsKeys.length - 1)) }))),
        h("div", { class: "keys" }, clsKeys.map((c, i) => h("span", null, h("i", { style: "background:" + shade(i / Math.max(1, clsKeys.length - 1)) }), (CLASS_NAME[c] || c) + " " + pct(d.cls[c]))))));
      const fr = Object.entries(row.fronts || {}).find(([, v]) => v.region === id);
      if (fr) {
        const [f, v] = fr;
        out.push(h("div", null, h("div", { class: "k", text: "The " + f + " front runs here" }),
          h("p", { text: num(frontFieldStrength(v)) + " of our effective field strength against " + num(v.union) + " of the " + (names.union || "Union") + "'s. Fortified " + pct(v.fort) +
            (v.progress > 0.005 ? "; the enemy has taken " + pct(v.progress) + " of the way to the next line" : "") +
            (v.combat ? ". Fighting this month: we lost about " + num(v.combat.k_loss) + ", they lost about " + num(v.combat.u_loss) + "." : ".") })));
      }
      const here = (row.events || []).filter(e => e.public !== false && ((e.text || "").includes(r.name) || geo.cities.some(c => c.region === id && (e.text || "").includes(c.name))));
      if (here.length) out.push(h("div", null, h("div", { class: "k", text: "This month here" }), h("ul", { style: "margin:4px 0 0;padding-left:18px" }, here.map(e => h("li", { text: e.text })))));
      return h("div", { class: "km-card" }, out);
    }

    renderLayerButtons(); applyZoom(); paint();
    let lastPins = [];
    return {
      show(r, p, extra) { row = r; prev = p || null; paint(); paintMilitary(); paintBadges(); lastPins = paintPins(!extra || extra.pins !== false); applyZoom(); return lastPins; },
      setLayer(id) { layer = id; renderLayerButtons(); paint(); },
      select(id) { select(id, false); },
      pins() { return lastPins; },
      detail(id) { return { region: REG[id], detail: detail(id), state: regState(id), row }; },
      card(id) { return card(id); },
      selected() { return selected; },
    };
  };
})();
