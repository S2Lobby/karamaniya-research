/* Directed relationship graph for one month (spec 102). Shared by the report and the control room.
   KaramaniyaRelGraph.draw(svg, frame, {mode, color, name})
   frame = {month, nodes: [{id, status, offices, influence}], edges: [{from, to, trust, rivalry, dependency}]}
   mode: "trust" (default), "rivalry" or "dependency". Colours come from CSS tokens. */
(function () {
  "use strict";
  const NS = "http://www.w3.org/2000/svg";
  function sv(tag, attrs, text) {
    const n = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, v);
    if (text !== undefined) n.textContent = text;
    return n;
  }
  function draw(svg, frame, opts) {
    opts = opts || {};
    const mode = opts.mode || "trust";
    const color = opts.color || (() => "var(--accent)");
    const name = opts.name || (id => id);
    const W = 560, H = 380, cx = W / 2, cy = H / 2 + 6, R = 138;
    svg.setAttribute("viewBox", "0 0 " + W + " " + H);
    svg.replaceChildren();
    if (!frame || !(frame.nodes || []).length) {
      svg.appendChild(sv("text", { x: cx, y: cy, "text-anchor": "middle", fill: "var(--muted)", "font-size": 14 },
        "No relationship data for this month"));
      return;
    }
    const defs = sv("defs");
    for (const key of ["pos", "neg", "riv", "dep"]) {
      const m = sv("marker", { id: "rg-" + key, viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse" });
      const fill = key === "pos" ? "var(--good)" : key === "neg" ? "var(--critical)" : key === "riv" ? "var(--s2)" : "var(--s7)";
      m.appendChild(sv("path", { d: "M 0 0 L 10 5 L 0 10 z", fill }));
      defs.appendChild(m);
    }
    svg.appendChild(defs);
    const nodes = frame.nodes.slice().sort((a, b) => a.id < b.id ? -1 : 1);
    const pos = {};
    nodes.forEach((n, i) => {
      const a = -Math.PI / 2 + i * 2 * Math.PI / nodes.length;
      pos[n.id] = { x: cx + R * Math.cos(a), y: cy + R * Math.sin(a), r: 18 + 16 * Math.max(0, Math.min(1, n.influence || 0.4)) };
    });
    const gEdges = sv("g"), gNodes = sv("g");
    for (const e of frame.edges || []) {
      const p = pos[e.from], q = pos[e.to];
      if (!p || !q) continue;
      let strength, stroke, marker, dash = "";
      if (mode === "trust") {
        const d = (e.trust ?? 50) - 50;
        if (Math.abs(d) < 6) continue;
        strength = Math.abs(d) / 50; stroke = d > 0 ? "var(--good)" : "var(--critical)"; marker = d > 0 ? "pos" : "neg";
      } else if (mode === "rivalry") {
        if ((e.rivalry || 0) < 20) continue;
        strength = (e.rivalry || 0) / 100; stroke = "var(--s2)"; marker = "riv"; dash = "6 4";
      } else {
        if ((e.dependency || 0) < 10) continue;
        strength = (e.dependency || 0) / 100; stroke = "var(--s7)"; marker = "dep";
      }
      const dx = q.x - p.x, dy = q.y - p.y, len = Math.hypot(dx, dy) || 1;
      const ux = dx / len, uy = dy / len, off = 22;
      const sx = p.x + ux * p.r, sy = p.y + uy * p.r, ex = q.x - ux * (q.r + 4), ey = q.y - uy * (q.r + 4);
      const mx = (sx + ex) / 2 - uy * off, my = (sy + ey) / 2 + ux * off;
      const path = sv("path", { d: `M ${sx} ${sy} Q ${mx} ${my} ${ex} ${ey}`, fill: "none", stroke,
        "stroke-width": (1 + 5 * strength).toFixed(2), "stroke-opacity": (0.35 + 0.6 * strength).toFixed(2),
        "marker-end": "url(#rg-" + marker + ")", "stroke-dasharray": dash });
      path.appendChild(sv("title", {}, `${name(e.from)} → ${name(e.to)}: trust ${e.trust}, rivalry ${e.rivalry}, dependency ${e.dependency}`));
      gEdges.appendChild(path);
    }
    for (const n of nodes) {
      const p = pos[n.id];
      const gone = n.status && n.status !== "active";
      const g = sv("g", { opacity: gone ? 0.35 : 1 });
      g.appendChild(sv("circle", { cx: p.x, cy: p.y, r: p.r, fill: color(n.id), stroke: "var(--surface)", "stroke-width": 2 }));
      g.appendChild(sv("text", { x: p.x, y: p.y + 5, "text-anchor": "middle", fill: "#fff", "font-weight": 700, "font-size": 15 }, n.id));
      const label = (n.offices || []).join(", ") || (gone ? n.status : "no office");
      g.appendChild(sv("text", { x: p.x, y: p.y + p.r + 15, "text-anchor": "middle", fill: "var(--ink-2)", "font-size": 12 }, label));
      g.appendChild(sv("title", {}, name(n.id) + (n.influence != null ? " · influence " + Math.round(100 * n.influence) + "%" : "")));
      gNodes.appendChild(g);
    }
    svg.appendChild(gEdges);
    svg.appendChild(gNodes);
  }
  window.KaramaniyaRelGraph = { draw };
})();
