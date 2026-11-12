// Micro-Cosmos dashboard — live event consumer + IR graph renderer.

const RUN_ID = window.SOURCE_RUN_ID;
const trace = document.getElementById("trace");
const gatesEl = document.getElementById("gates");
const phaseStrip = document.getElementById("phase-strip");
const artifactView = document.getElementById("artifact-view");
const liveStatusEl = document.getElementById("live-status");
const liveTextEl = document.getElementById("live-text");
const livedot = liveStatusEl ? liveStatusEl.querySelector(".live-dot") : null;

// ─── Cytoscape Layout Configuration ──────────────────────────────────────────
// Summary (repo-map): fcose — compound-aware force-directed layout. Keeps
//   bounded-context children inside their parent hull and produces compact,
//   well-separated clusters. Falls back to cose if fcose is not loaded.
// Full (module-level): dagre TB — shows only PROGRAM + DATA_STRUCTURE nodes
//   ranked top→bottom by call direction. Skips methods/fields so the graph
//   stays readable for stakeholder demos.

const _hasCytoscape = typeof cytoscape !== "undefined";
const _hasDagre    = typeof dagre           !== "undefined";
const _hasFcose    = typeof cytoscapeFcose  !== "undefined";
if (_hasCytoscape && _hasFcose) cytoscape.use(cytoscapeFcose);

// Colour palette for bounded contexts.
// bg/border: used in Repo Map standalone boxes.
// node: used in Full Detail node backgrounds (slightly deeper, keeps white text readable).
const CONTEXT_PALETTE = [
  { bg: "#dce8f5", border: "#5b8ec4", node: "#4a7eb4" },  // blue
  { bg: "#e8ddf5", border: "#8b5bc4", node: "#7a4ab4" },  // purple
  { bg: "#ddf5e8", border: "#3da46a", node: "#2a9459" },  // green
  { bg: "#f5e8dd", border: "#c47a3d", node: "#b46a2a" },  // orange
  { bg: "#f5dddd", border: "#c44040", node: "#b43030" },  // red
  { bg: "#ddf5f5", border: "#3da4a4", node: "#2a9494" },  // teal
  { bg: "#f5f0dd", border: "#b8a03a", node: "#a89028" },  // gold
];

// Summary view: dagre LR — context boxes as a left-to-right dependency diagram.
// This gives a clean bounded-context map: Web → Service → Repository → Entity etc.
const LAYOUT_SUMMARY = _hasDagre
  ? {
      name: "dagre",
      animate: false,
      rankDir: "LR",
      rankSep: 160,
      nodeSep: 60,
      edgeSep: 20,
      padding: 60,
      nodeDimensionsIncludeLabels: true,
      ranker: "network-simplex",
    }
  : {
      name: "grid",
      animate: false,
      padding: 60,
    };

// Full view: dagre TB — PROGRAM + DATA_STRUCTURE only (module-level architecture).
// Skipping PROCEDURE/DATA_ITEM keeps the graph to ~100 nodes, readable in a demo.
const LAYOUT_FULL = _hasDagre
  ? {
      name: "dagre",
      animate: false,
      nodeDimensionsIncludeLabels: true,
      rankDir: "LR",
      rankSep: 100,
      nodeSep: 30,
      edgeSep: 10,
      padding: 48,
      ranker: "network-simplex",
    }
  : {
      name: "breadthfirst",
      animate: false,
      directed: true,
      padding: 40,
      spacingFactor: 1.5,
      nodeDimensionsIncludeLabels: true,
    };

let currentLevel = "summary";

// ─── Cytoscape ───────────────────────────────────────────────────────────────
// ── Touchpad scroll → pan (Google-Maps style) ────────────────────────────────
// On macOS, two-finger swipe fires wheel events with ctrlKey=false.
// Pinch-to-zoom fires wheel events with ctrlKey=true (browser normalisation).
// We intercept in capture phase (before Cytoscape sees it) and route accordingly.
const _cyEl = document.getElementById("cy");

// No-op stub used when Cytoscape fails to load — keeps the rest of the UI alive.
const _CY_STUB = {
  on: () => {}, off: () => {}, fit: () => {}, resize: () => {},
  panBy: () => {}, animate: () => {}, nodes: () => ({ length: 0 }),
  elements: () => ({ select: () => {}, length: 0 }),
  json: () => ({}),
};

if (_cyEl && _hasCytoscape) {
  _cyEl.addEventListener("wheel", (e) => {
    if (e.ctrlKey || e.metaKey) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    cy.panBy({ x: -e.deltaX * 1.2, y: -e.deltaY * 1.2 });
  }, { passive: false, capture: true });
}

let cy = _hasCytoscape ? cytoscape({
  container: _cyEl,
  elements: [],
  // Disable node grabbing so every click-drag pans the canvas, even over nodes.
  autoungrabify: true,
  userPanningEnabled: true,
  userZoomingEnabled: true,   // pinch-to-zoom still works via the handler above
  boxSelectionEnabled: false,
  style: [
    {
      selector: "node[kind='ir_node']",
      style: {
        "background-color": "#5c8a5c",
        "label": "data(label)",
        "color": "#171D1D",
        "font-family": "Inter Tight, sans-serif",
        "font-size": "9px",
        "font-weight": "500",
        "text-valign": "bottom",
        "text-margin-y": 4,
        "width": 24,
        "height": 24,
        "border-width": 1.5,
        "border-color": "#ffffff",
        "border-opacity": 0.9,
        "text-wrap": "wrap",
        "text-max-width": 100,
      },
    },
    {
      selector: "node[type='PROGRAM']",
      style: {
        "background-color": "#3d6b8a",
        "shape": "round-rectangle",
        "width": "label",
        "height": "label",
        "padding": "6px 12px",
        "font-size": "10px",
        "font-weight": "700",
        "text-valign": "center",
        "text-halign": "center",
        "text-wrap": "wrap",
        "text-max-width": 160,
        "color": "#e8f0f8",
      },
    },
    {
      selector: "node[type='DATA_STRUCTURE']",
      style: {
        "background-color": "#5c7a6a",
        "shape": "round-rectangle",
        "width": 38,
        "height": 24,
        "font-size": "8.5px",
        "font-weight": "600",
        "text-valign": "center",
        "text-max-width": 120,
        "color": "#fff",
      },
    },
    // PROCEDURE: pill showing name + signature
    {
      selector: "node[type='PROCEDURE']",
      style: {
        "background-color": "#5c8a5c",
        "shape": "round-rectangle",
        "width": "label",
        "height": "label",
        "padding": "5px 10px",
        "font-size": "8px",
        "text-valign": "center",
        "text-halign": "center",
        "text-wrap": "wrap",
        "text-max-width": 160,
        "color": "#fff",
        "font-family": "IBM Plex Mono, monospace",
      },
    },
    { selector: "node[type='DATA_ITEM']",     style: { "background-color": "#c98b3b", "shape": "ellipse", "width": 14, "height": 14, "font-size": "7px", "color": "#fff" }},
    { selector: "node[type='STATE_FIELD']",   style: { "background-color": "#b85a5a", "shape": "diamond", "width": 16, "height": 16, "font-size": "7px", "color": "#fff" }},
    { selector: "node[type='EXTERNAL_CALL']", style: { "background-color": "#7a4f8a", "shape": "hexagon", "width": 20, "height": 20, "color": "#fff" }},
    // Bounded-context node (summary / repo-map view) — standalone labelled box
    {
      selector: "node[kind='context']",
      style: {
        "background-color": "#dce8f5",
        "background-opacity": 0.9,
        "border-width": 3,
        "border-color": "#5b8ec4",
        "border-style": "solid",
        "label": "data(label)",
        "font-family": "Inter Tight, sans-serif",
        "font-size": "13px",
        "font-weight": "700",
        "color": "#1a3a5c",
        "text-valign": "center",
        "text-halign": "center",
        "text-wrap": "wrap",
        "text-max-width": "150px",
        "shape": "round-rectangle",
        "width": "label",
        "height": "label",
        "padding": "18px 24px",
      },
    },
    // Dead code context — greyed out, dashed border, muted label
    {
      selector: "node[kind='context'][name='DeadCode']",
      style: {
        "background-color": "#f0f0f0",
        "background-opacity": 0.7,
        "border-width": 2,
        "border-color": "#aaaaaa",
        "border-style": "dashed",
        "color": "#888888",
        "font-style": "italic",
      },
    },
    // Edges — labels hidden by default, shown on highlight
    {
      selector: "edge",
      style: {
        "width": 1.5,
        "line-color": "#b5b5b5",
        "target-arrow-color": "#b5b5b5",
        "target-arrow-shape": "triangle",
        "curve-style": "bezier",
        "label": "data(label)",
        "font-family": "IBM Plex Mono, monospace",
        "font-size": "7px",
        "color": "#666",
        "text-rotation": "autorotate",
        "text-background-color": "#ffffff",
        "text-background-opacity": 0.85,
        "text-background-padding": 2,
        "text-opacity": 0,
      },
    },
    { selector: "edge[label='DEFINES']",        style: { "line-color": "#c8d8e8", "target-arrow-color": "#c8d8e8", "line-style": "dotted", "width": 1, "target-arrow-shape": "none", "opacity": 0.7 }},
    { selector: "edge[label='CALLS']",          style: { "line-color": "#3d6b8a", "target-arrow-color": "#3d6b8a", "width": 2 }},
    { selector: "edge[label='REFERENCES']",     style: { "line-color": "#7a4f8a", "target-arrow-color": "#7a4f8a", "line-style": "dashed", "width": 1.5 }},
    { selector: "edge[label='REDEFINES']",      style: { "line-color": "#b85a5a", "target-arrow-color": "#b85a5a" }},
    { selector: "edge[label='CO_MUTATES_WITH']",style: { "line-color": "#c98b3b", "target-arrow-color": "#c98b3b", "line-style": "dotted", "width": 1.5, "target-arrow-shape": "none" }},
    { selector: "node.faded",       style: { "opacity": 0.15 }},
    { selector: "edge.faded",       style: { "opacity": 0.06 }},
    { selector: "node.highlighted", style: { "border-width": 3, "border-color": "#ED3A12" }},
    { selector: "edge.highlighted", style: { "width": 2.5, "line-color": "#ED3A12", "target-arrow-color": "#ED3A12", "color": "#ED3A12", "text-opacity": 1 }},
    // Seam annotations — applied via explicit addClass() after cy.add(), not data selectors
    { selector: "node.seam-boundary",     style: { "border-width": 3.5, "border-color": "#e09c3c", "border-opacity": 1 }},
    { selector: "node.seam-object",       style: { "border-width": 3.5, "border-color": "#3cb8b0", "border-opacity": 1 }},
    { selector: "node.seam-preprocessing",style: { "border-width": 3.5, "border-color": "#9b59b6", "border-opacity": 1 }},
    { selector: "edge.seam-link",         style: { "line-color": "#e09c3c", "target-arrow-color": "#e09c3c", "width": 2.5, "opacity": 0.85 }},
  ],
  layout: LAYOUT_SUMMARY,
}) : _CY_STUB;

// ─── Tooltip ─────────────────────────────────────────────────────────────────
const tooltip = document.getElementById("graph-tooltip");
const cyContainer = _cyEl;

function buildSignatureLabel(data) {
  const params = (data.inputs || [])
    .filter(p => p.name && p.name !== "self" && !p.name.startsWith("**"));

  // Keep params compact: show type only when it adds information
  const paramStr = params
    .map(p => p.type ? `${p.name}: ${p.type}` : p.name)
    .join(", ");

  // Truncate very long param lists so labels don't blow out the container
  const sig = paramStr.length > 60
    ? `${data.label || data.id}(${paramStr.slice(0, 57)}…)`
    : `${data.label || data.id}(${paramStr})`;

  const ret = data.output
    ? `\n→ ${data.output.length > 40 ? data.output.slice(0, 37) + "…" : data.output}`
    : "";

  const summary = data.summary
    ? `\n${data.summary.length > 55 ? data.summary.slice(0, 52) + "…" : data.summary}`
    : "";

  return `${sig}${ret}${summary}`;
}

function showTooltip(node, renderedPos) {
  const d = node.data();
  if (!d.summary && !(d.inputs && d.inputs.length) && !d.output && !d.seam_type) { hideTooltip(); return; }

  const gtName = tooltip.querySelector(".gt-name");
  const gtSummary = tooltip.querySelector(".gt-summary");
  const gtParams = tooltip.querySelector(".gt-params");
  const gtOutput = tooltip.querySelector(".gt-output");
  const gtSeam = tooltip.querySelector(".gt-seam");

  gtName.textContent = d.label || d.id;

  gtSummary.textContent = d.summary || "";
  gtSummary.hidden = !d.summary;

  if (d.inputs && d.inputs.length) {
    const rows = d.inputs
      .filter(p => p.name && !p.name.startsWith("self"))
      .map(p => {
        const name = `<span class="gt-param-name">${escapeHtml(p.name)}</span>`;
        const type = p.type ? ` <span class="gt-param-type">${escapeHtml(p.type)}</span>` : "";
        const def  = p.default ? ` = ${escapeHtml(p.default)}` : "";
        const desc = p.description ? `<br><span class="gt-param-desc">  ${escapeHtml(p.description)}</span>` : "";
        return `${name}${type}${def}${desc}`;
      }).join("<br>");
    gtParams.innerHTML = rows;
    gtParams.hidden = false;
  } else {
    gtParams.hidden = true;
  }

  if (d.output) {
    gtOutput.innerHTML = `→ <span class="gt-output-val">${escapeHtml(d.output)}</span>`;
    gtOutput.hidden = false;
  } else {
    gtOutput.hidden = true;
  }

  if (gtSeam) {
    if (d.seam_type) {
      const labels = { boundary: "boundary seam", object: "object seam", preprocessing: "preprocessing seam", message: "message seam" };
      const label = labels[d.seam_type] || d.seam_type;
      const evidenceHtml = d.seam_evidence ? `<div class="gt-seam-evidence">${escapeHtml(d.seam_evidence)}</div>` : "";
      const noteHtml = d.seam_note ? `<div class="gt-seam-note">${escapeHtml(d.seam_note)}</div>` : "";
      gtSeam.innerHTML = `<span class="gt-seam-badge gt-seam-${escapeHtml(d.seam_type)}">${escapeHtml(label)}</span>${evidenceHtml}${noteHtml}`;
      gtSeam.hidden = false;
    } else {
      gtSeam.hidden = true;
    }
  }

  tooltip.removeAttribute("hidden");

  // Position near the node, keeping within the graph panel
  const panelRect = cyContainer.getBoundingClientRect();
  const zoom = cy.zoom();
  const pan = cy.pan();
  const np = node.renderedPosition();
  let x = np.x + 16;
  let y = np.y - 8;
  // Clamp right edge
  if (x + 320 > panelRect.width) x = np.x - 320 - 8;
  if (y + tooltip.offsetHeight > panelRect.height) y = panelRect.height - tooltip.offsetHeight - 8;
  tooltip.style.left = `${Math.max(4, x)}px`;
  tooltip.style.top  = `${Math.max(4, y)}px`;
}

function hideTooltip() {
  tooltip.setAttribute("hidden", "");
}

cy.on("mouseover", "node[kind='ir_node']", (evt) => {
  const node = evt.target;
  cy.elements().addClass("faded");
  node.removeClass("faded").addClass("highlighted");
  node.neighborhood().removeClass("faded");
  cy.nodes("[kind='context']").removeClass("faded");
  showTooltip(node, evt.renderedPosition);
});

cy.on("mousemove", "node[kind='ir_node']", (evt) => {
  showTooltip(evt.target, evt.renderedPosition);
});

cy.on("mouseout", "node[kind='ir_node']", () => {
  cy.elements().removeClass("highlighted faded");
  hideTooltip();
});

cy.on("tap", () => hideTooltip());

// Context node hover — show rationale in tooltip
cy.on("mouseover", "node[kind='context']", (evt) => {
  const d = evt.target.data();
  const tooltip = document.getElementById("graph-tooltip");
  if (!tooltip) return;
  tooltip.querySelector(".gt-name").textContent = d.name || d.label;
  const gtSummary = tooltip.querySelector(".gt-summary");
  gtSummary.textContent = d.rationale || "";
  gtSummary.hidden = !d.rationale;
  tooltip.querySelector(".gt-params").hidden = true;
  tooltip.querySelector(".gt-output").hidden = true;
  const gtSeam = tooltip.querySelector(".gt-seam");
  if (gtSeam) gtSeam.hidden = true;
  tooltip.removeAttribute("hidden");
  const np = evt.target.renderedPosition();
  const panelRect = _cyEl.getBoundingClientRect();
  let x = np.x + 16;
  let y = np.y - 8;
  if (x + 320 > panelRect.width) x = np.x - 320 - 8;
  if (y + tooltip.offsetHeight > panelRect.height) y = panelRect.height - tooltip.offsetHeight - 8;
  tooltip.style.left = `${Math.max(4, x)}px`;
  tooltip.style.top  = `${Math.max(4, y)}px`;
});
cy.on("mouseout", "node[kind='context']", () => hideTooltip());

// Double-click a bounded context node to zoom into it
cy.on("dblclick", "node[kind='context']", (evt) => {
  cy.fit(evt.target, 48);
});
// Double-click background to zoom back to full graph
cy.on("dblclick", (evt) => {
  if (evt.target === cy) cy.fit(cy.nodes(":visible"), 32);
});

// ── Pan navigation controls ───────────────────────────────────────────────────
const PAN_STEP = 120;

// Arrow-key panning (when graph panel is focused / no input is active)
document.addEventListener("keydown", (e) => {
  if (document.activeElement && document.activeElement.tagName === "INPUT") return;
  if (document.activeElement && document.activeElement.tagName === "TEXTAREA") return;
  if (e.key === "ArrowUp")    { e.preventDefault(); cy.panBy({ x: 0,         y:  PAN_STEP }); }
  if (e.key === "ArrowDown")  { e.preventDefault(); cy.panBy({ x: 0,         y: -PAN_STEP }); }
  if (e.key === "ArrowLeft")  { e.preventDefault(); cy.panBy({ x:  PAN_STEP, y: 0 }); }
  if (e.key === "ArrowRight") { e.preventDefault(); cy.panBy({ x: -PAN_STEP, y: 0 }); }
  if (e.key === "f" || e.key === "F") cy.fit(cy.nodes(":visible"), 32);
});

window.addEventListener("resize", () => { cy.resize(); cy.fit(); });

// ── Drag-to-resize the graph panel ────────────────────────────────────────────
(function () {
  const resizer = document.querySelector(".dashboard-resizer");
  const graphPanel = document.querySelector(".graph-panel");
  const dashboard = document.querySelector(".dashboard");
  if (!resizer || !graphPanel || !dashboard) return;

  const WIDTH_KEY = "source:graph-panel-width";
  const MIN_WIDTH = 320;

  function clamp(px) {
    const max = dashboard.getBoundingClientRect().width - MIN_WIDTH - 13;
    return Math.max(MIN_WIDTH, Math.min(px, max));
  }
  function setWidth(px) {
    graphPanel.style.flex = `0 0 ${clamp(px)}px`;
    cy.resize();
  }

  const savedWidth = parseInt(localStorage.getItem(WIDTH_KEY), 10);
  if (!Number.isNaN(savedWidth)) setWidth(savedWidth);

  let dragging = false;
  resizer.addEventListener("mousedown", (e) => {
    dragging = true;
    resizer.classList.add("dragging");
    document.body.style.userSelect = "none";
    e.preventDefault();
  });
  window.addEventListener("mousemove", (e) => {
    if (!dragging) return;
    // graph-panel is the right-hand column now — its width is the distance
    // from the cursor to the dashboard's right edge, not the left edge.
    const right = dashboard.getBoundingClientRect().right;
    setWidth(right - e.clientX);
  });
  window.addEventListener("mouseup", () => {
    if (!dragging) return;
    dragging = false;
    resizer.classList.remove("dragging");
    document.body.style.userSelect = "";
    localStorage.setItem(WIDTH_KEY, Math.round(graphPanel.getBoundingClientRect().width));
  });

  // Keyboard resize for accessibility (arrow keys while the separator is focused)
  resizer.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    // graph-panel is on the right now — ArrowLeft moves the divider left,
    // which grows it; ArrowRight shrinks it. Opposite of a left-hand panel.
    const current = graphPanel.getBoundingClientRect().width;
    const next = current + (e.key === "ArrowLeft" ? 24 : -24);
    setWidth(next);
    localStorage.setItem(WIDTH_KEY, Math.round(graphPanel.getBoundingClientRect().width));
  });
})();

document.querySelectorAll(".graph-level-btn").forEach((btn) => {
  btn.addEventListener("click", () => refreshGraph(btn.dataset.level));
});

const fitBtn = document.querySelector(".graph-fit-btn");
if (fitBtn) fitBtn.addEventListener("click", () => cy.fit(undefined, 32));

async function refreshGraph(level) {
  level = level || currentLevel;
  currentLevel = level;
  document.querySelectorAll(".graph-level-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.level === level);
  });
  try {
    const res = await fetch(`/runs/${RUN_ID}/graph?level=${level}`);
    if (!res.ok) return;
    const data = await res.json();
    if (!data.elements || data.elements.length === 0) return;

    cy.startBatch();
    cy.elements().remove();
    cy.add(data.elements);

    // In full-detail mode, hide PROCEDURE and DATA_ITEM nodes so the graph
    // shows only the module-level architecture (PROGRAM + DATA_STRUCTURE).
    // This keeps the node count manageable for a stakeholder demo.
    if (level === "full") {
      cy.nodes("[type='PROCEDURE'],[type='DATA_ITEM']").remove();
      cy.edges().style("text-opacity", 0.85);

      // Colour-code nodes by bounded context — same palette as the Repo Map
      // so stakeholders can visually link the two views.
      cy.nodes("[kind='ir_node']").forEach((n) => {
        const ctxIdx = n.data("ctx_index");
        if (ctxIdx !== undefined) {
          const col = CONTEXT_PALETTE[ctxIdx % CONTEXT_PALETTE.length];
          n.style("background-color", col.node);
          n.style("border-color", col.border);
          n.style("color", "#ffffff");
        }
      });
    } else {
      cy.edges().style("text-opacity", 0);
    }

    // Apply seam classes
    cy.nodes().forEach((n) => {
      const st = n.data("seam_type");
      if (st) n.addClass(`seam-${st}`);
    });
    cy.edges().forEach((e) => {
      if (e.data("seam_link")) e.addClass("seam-link");
    });

    // Colour-code each bounded context node — skip DeadCode (styled separately)
    let paletteIdx = 0;
    cy.nodes("[kind='context']").forEach((n) => {
      if (n.data("name") === "DeadCode") return;
      const col = CONTEXT_PALETTE[paletteIdx % CONTEXT_PALETTE.length];
      paletteIdx++;
      n.style("background-color", col.bg);
      n.style("border-color", col.border);
      n.style("color", col.border);
    });

    cy.endBatch();

    // Ensure Cytoscape knows the current container dimensions before layout
    cy.resize();

    const layout = cy.layout(level === "summary" ? LAYOUT_SUMMARY : LAYOUT_FULL);
    layout.on("layoutstop", () => {
      // Small delay so compound hulls finish expanding before we fit
      setTimeout(() => cy.fit(cy.nodes(":visible"), 32), 60);
    });
    layout.run();
  } catch (e) {
    console.warn("graph fetch failed", e);
  }
}

refreshGraph("summary");

// ─── Gate summary ────────────────────────────────────────────────────────────
function gsKV(label, value) {
  return `<div class="gs-row"><span class="gs-label">${label}</span><span class="gs-value">${value}</span></div>`;
}

function gsList(items) {
  if (!items || !items.length) return "";
  return `<ul class="gs-list">${items.map((s) => `<li>${escapeHtml(String(s))}</li>`).join("")}</ul>`;
}

function buildGateSummary(gateId, artifact, extraData = {}) {
  if (!artifact || typeof artifact !== "object") return "";
  const titles = {
    gate_1: "Observer · IR property graph",
    gate_2: "Cartographer · bounded contexts",
    gate_3: "Architect · TNAS and fitness suite",
    gate_4:   "Security · vulnerability and migration-risk review",
    gate_4_5: "Planning · translation scope & feature specs review",
    gate_5:   "PR Approval · generated code review",
  };
  const title = titles[gateId] || gateId;
  let body = "";

  try {
    if (gateId === "gate_1") {
      const nodes = artifact.nodes || [];
      const edges = artifact.edges || [];
      const tc = {};
      for (const n of nodes) { const t = n.type || "UNKNOWN"; tc[t] = (tc[t] || 0) + 1; }
      const typeStr = Object.entries(tc).map(([t, c]) => `${c} ${escapeHtml(t.toLowerCase())}`).join(" · ");
      body += gsKV("Nodes", `${nodes.length}${typeStr ? ` <span class="gs-dim">— ${typeStr}</span>` : ""}`);
      body += gsKV("Edges", edges.length);
      const dead = (artifact.dead_code || []).length;
      const perf = (artifact.performance_findings || []).length;
      body += gsKV("Dead code", dead ? `<span class="gs-warn">${dead} finding${dead !== 1 ? "s" : ""}</span>` : "none");
      body += gsKV("Performance", perf ? `<span class="gs-warn">${perf} finding${perf !== 1 ? "s" : ""}</span>` : "none");

      // ── Per-node detail: classes, methods, functions ──────────────────
      const detailNodes = nodes.filter(n =>
        (n.type === "PROCEDURE" || n.type === "DATA_STRUCTURE") &&
        (n.summary || (n.inputs && n.inputs.length) || n.output)
      );
      if (detailNodes.length) {
        body += `<div class="gs-node-list">`;
        for (const n of detailNodes) {
          const isProcedure = n.type === "PROCEDURE";
          const inputs = (n.inputs || []).filter(p => p.name && !p.name.startsWith("self"));
          const sigParts = inputs.map(p => {
            let s = `<span class="gs-param-name">${escapeHtml(p.name)}</span>`;
            if (p.type) s += `: <span class="gs-param-type">${escapeHtml(p.type)}</span>`;
            return s;
          });
          const sig = isProcedure
            ? `<span class="gs-node-sig">${escapeHtml(n.name)}(${sigParts.join(", ")})${n.output ? ` → <span class="gs-return-type">${escapeHtml(n.output)}</span>` : ""}</span>`
            : `<span class="gs-node-sig">${escapeHtml(n.name)}</span>`;

          const paramDescs = inputs
            .filter(p => p.description)
            .map(p => `<div class="gs-param-row"><span class="gs-param-name">${escapeHtml(p.name)}</span> <span class="gs-param-desc">${escapeHtml(p.description)}</span></div>`)
            .join("");

          body += `
            <div class="gs-node-card">
              <div class="gs-node-header">
                <span class="gs-node-type">${escapeHtml(n.type.toLowerCase())}</span>
                ${sig}
              </div>
              ${n.summary ? `<div class="gs-node-summary">${escapeHtml(n.summary)}</div>` : ""}
              ${paramDescs ? `<div class="gs-param-list">${paramDescs}</div>` : ""}
            </div>`;
        }
        body += `</div>`;
      }

      const obs = artifact.llm_observations || [];
      if (obs.length) {
        body += gsKV("LLM observations", `${obs.length} noted`);
        body += gsList(obs);
      }
    }

    else if (gateId === "gate_2") {
      const contexts = artifact.contexts || [];
      body += gsKV("Contexts", contexts.length);
      for (const ctx of contexts) {
        const nids = ctx.node_ids || [];
        const progCount = nids.filter(id => id.startsWith("prog.")).length;
        const nc = nids.length;
        const conf = escapeHtml(String(ctx.confidence || "?"));
        const countLabel = progCount > 0
          ? `${progCount} file${progCount !== 1 ? "s" : ""} · ${nc} node${nc !== 1 ? "s" : ""}`
          : `${nc} node${nc !== 1 ? "s" : ""}`;
        body += gsKV(
          escapeHtml(ctx.name || "unnamed"),
          `${countLabel} · <span class="gs-dim">${conf} confidence</span>`
        );
        if (ctx.rationale) body += `<p class="gs-note">${escapeHtml(ctx.rationale)}</p>`;
      }
      const leaky = (artifact.leaky_abstractions || []).length;
      if (leaky) body += gsKV("Leaky abstractions", `<span class="gs-warn">${leaky} flagged</span>`);
    }

    else if (gateId === "gate_3") {
      if (artifact.summary) body += `<p class="gs-narrative">${escapeHtml(artifact.summary)}</p>`;
      const services = artifact.services || [];
      const tl = escapeHtml(String(artifact.target_lang || artifact.target_language || "?"));
      const ctxDecisions = artifact.context_decisions || [];
      const fitness = artifact.fitness_suite || {};
      const rules = fitness.rules || fitness.checks || fitness.functions || [];
      const blocking = rules.filter((r) => r.severity === "BLOCKING" || r.blocking === true).length;
      body += gsKV("Target language", tl);
      body += gsKV("Services", services.length);
      for (const svc of services) {
        const risk = String(svc.migration_risk || "").toUpperCase();
        const riskHtml = risk === "HIGH"   ? `<span class="gs-fail">${escapeHtml(risk)} risk</span>`
                       : risk === "MEDIUM" ? `<span class="gs-warn">${escapeHtml(risk)} risk</span>`
                       : risk === "LOW"    ? `<span class="gs-ok">${escapeHtml(risk)} risk</span>`
                       : "";
        const rationale = svc.rationale || "";
        body += gsKV(
          escapeHtml(svc.service_id || svc.name || svc.context || String(svc)),
          `${riskHtml}${riskHtml && rationale ? " · " : ""}${rationale ? `<span class="gs-dim">${escapeHtml(rationale)}</span>` : ""}`
        );
        if (svc.risk_reason) body += `<p class="gs-note">${escapeHtml(svc.risk_reason)}</p>`;
      }
      if (ctxDecisions.length) body += gsKV("Contexts", ctxDecisions.length);
      body += gsKV("Fitness checks", `${rules.length} total · ${blocking > 0 ? `<span class="gs-warn">${blocking} blocking</span>` : "0 blocking"} · ${rules.length - blocking} non-blocking`);
      const notes = artifact.architect_notes || [];
      if (notes.length) {
        body += gsKV("Architect notes", "");
        body += gsList(notes.map((n) => (typeof n === "string" ? n : (n.note || n.message || String(n)))));
      }
    }

    else if (gateId === "gate_4") {
      const findings = artifact.findings || [];
      const srcRisk  = String(artifact.source_architecture_risk || "UNKNOWN").toUpperCase();
      const dstRisk  = String(artifact.destination_architecture_risk || "UNKNOWN").toUpperCase();

      // ── Risk dashboard ──────────────────────────────────────────────────────
      const _riskHtml = (label, risk) => {
        const cls = risk === "CRITICAL" ? "gs-fail"
                  : risk === "HIGH"     ? "gs-fail"
                  : risk === "MEDIUM"   ? "gs-warn"
                  : risk === "LOW"      ? "gs-ok"
                  : "gs-dim";
        return gsKV(label, `<span class="${cls}">${escapeHtml(risk)}</span>`);
      };
      body += _riskHtml("Source architecture risk", srcRisk);
      body += _riskHtml("Destination architecture risk", dstRisk);

      // ── Finding counts by severity ──────────────────────────────────────────
      const SEV_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"];
      const sevCounts = {};
      for (const f of findings) {
        const s = (f.severity || "INFO").toUpperCase();
        sevCounts[s] = (sevCounts[s] || 0) + 1;
      }
      const sevParts = SEV_ORDER
        .filter(s => sevCounts[s])
        .map(s => {
          const cls = (s === "CRITICAL" || s === "HIGH") ? "gs-fail"
                    : s === "MEDIUM" ? "gs-warn"
                    : s === "LOW"    ? "gs-ok"
                    : "gs-dim";
          return `<span class="${cls}">${sevCounts[s]} ${escapeHtml(s.toLowerCase())}</span>`;
        }).join(" · ");
      body += gsKV("Findings", findings.length
        ? `${findings.length} total${sevParts ? " — " + sevParts : ""}`
        : `<span class="gs-ok">none</span>`);

      if (artifact.scope_summary) {
        body += `<p class="gs-note">${escapeHtml(artifact.scope_summary)}</p>`;
      }

      // ── Trivy CVE summary ───────────────────────────────────────────────────
      const trivy = extraData.trivy;
      if (trivy && !trivy.error && trivy.summary && trivy.summary.total > 0) {
        const ts = trivy.summary;
        const trivyParts = ["CRITICAL","HIGH","MEDIUM","LOW"]
          .filter(s => ts[s])
          .map(s => {
            const cls = (s === "CRITICAL" || s === "HIGH") ? "gs-fail"
                      : s === "MEDIUM" ? "gs-warn" : "gs-ok";
            return `<span class="${cls}">${ts[s]} ${escapeHtml(s.toLowerCase())}</span>`;
          }).join(" · ");
        body += gsKV(
          "Trivy CVEs",
          `${ts.total} dependency CVE(s)${trivyParts ? " — " + trivyParts : ""}` +
          ` <span class="gs-dim" style="font-size:0.7em;">(scan ran before LLM phase)</span>`
        );
        if (ts.CRITICAL || ts.HIGH) {
          const topCves = (trivy.vulnerabilities || [])
            .filter(v => v.severity === "CRITICAL" || v.severity === "HIGH")
            .slice(0, 5);
          if (topCves.length) {
            body += `<div class="gs-node-list" style="margin-top:4px;">`;
            for (const v of topCves) {
              const col = v.severity === "CRITICAL" ? "#c0392b" : "#c0392b";
              body += `<div class="gs-node-card" style="border-left-color:${col}">
                <div class="gs-node-header">
                  <span class="gs-node-type" style="color:${col};border-color:${col}">${escapeHtml(v.severity)}</span>
                  <span class="gs-node-sig"><strong>${escapeHtml(v.cve_id || v.id)}</strong> · ${escapeHtml(v.pkg_name)} ${escapeHtml(v.installed_version || "")}</span>
                </div>
                ${v.fixed_version ? `<div class="gs-node-summary gs-ok">Fix: upgrade to ${escapeHtml(v.fixed_version)}</div>` : ""}
              </div>`;
            }
            body += `</div>`;
          }
        }
      } else if (trivy && !trivy.error && trivy.summary && trivy.summary.total === 0) {
        body += gsKV("Trivy CVEs", `<span class="gs-ok">none detected</span>`);
      }

      // ── Finding cards ───────────────────────────────────────────────────────
      if (findings.length) {
        const SEV_COLOR = {
          CRITICAL: "#c0392b", HIGH: "#c0392b", MEDIUM: "#8a5a00", LOW: "#2d7d46", INFO: "#666",
        };
        body += `<div class="gs-node-list">`;
        for (const f of findings) {
          const sev     = (f.severity || "INFO").toUpperCase();
          const sevCol  = SEV_COLOR[sev] || "#666";
          const cat     = escapeHtml(f.category || "");
          const cwe     = f.cwe_id ? `<span class="gs-dim" style="margin-left:6px">${escapeHtml(f.cwe_id)}</span>` : "";
          const loc     = f.location ? `<span class="gs-param-desc" style="font-family:monospace">${escapeHtml(f.location)}</span>` : "";
          const confBadge = f.confirmed
            ? `<span class="gs-ok" style="font-size:0.7em;margin-left:6px">confirmed</span>`
            : `<span class="gs-dim" style="font-size:0.7em;margin-left:6px">hypothesis</span>`;
          const migBadge = f.affects_migration
            ? `<span class="gs-warn" style="font-size:0.7em;margin-left:4px">affects migration</span>` : "";

          const snippetHtml = f.code_snippet
            ? `<details class="gs-snippet-details">
                <summary class="gs-snippet-summary">&#x1F4C4; code snippet</summary>
                <pre class="gs-snippet-pre">${escapeHtml(f.code_snippet)}</pre>
               </details>`
            : "";
          const matchedHtml = f.matched_text
            ? `<div class="gs-matched-text">Matched: <code>${escapeHtml(f.matched_text)}</code></div>`
            : "";

          body += `
            <div class="gs-node-card">
              <div class="gs-node-header">
                <span class="gs-node-type" style="color:${sevCol};border-color:${sevCol}">${escapeHtml(sev)}</span>
                <span class="gs-node-sig">
                  <span style="font-weight:600">${escapeHtml(f.id || "")} · ${escapeHtml(f.title || "")}</span>
                  ${confBadge}${migBadge}
                </span>
              </div>
              <div class="gs-node-summary">
                ${cat ? `<span class="gs-dim">${cat}</span>${cwe} · ` : ""}${loc}
              </div>
              ${f.description ? `<div class="gs-node-summary" style="margin-top:4px">${escapeHtml(f.description)}</div>` : ""}
              ${matchedHtml}
              ${f.remediation ? `<div class="gs-note" style="margin-top:4px;border-left:2px solid ${sevCol};padding-left:8px">${escapeHtml(f.remediation)}</div>` : ""}
              ${snippetHtml}
            </div>`;
        }
        body += `</div>`;
      }

      // ── Recommended fixes ───────────────────────────────────────────────────
      const fixes = artifact.recommended_fixes || [];
      if (fixes.length) {
        body += gsKV("Recommended fixes", fixes.length);
        body += gsList(fixes);
      }

      // ── Follow-up checks ────────────────────────────────────────────────────
      const checks = artifact.follow_up_checks || [];
      if (checks.length) {
        body += gsKV("Follow-up checks", checks.length);
        body += gsList(checks);
      }

      // ── Migration security notes ─────────────────────────────────────────────
      const migNotes = artifact.migration_security_notes || [];
      if (migNotes.length) {
        body += gsKV("Migration security notes", migNotes.length);
        body += gsList(migNotes);
      }
    }

    else if (gateId === "gate_4_5") {
      // artifact is feature_specs.json — either a list or {specs:[...]}
      const specs = Array.isArray(artifact) ? artifact : (artifact.specs || []);

      // ── Totals ────────────────────────────────────────────────────────────────
      const totalPts = specs.reduce((s, x) => s + (x.story_points || 0), 0);
      body += gsKV("Seams to translate", specs.length);
      body += gsKV("Total story points", totalPts || "—");

      // ── Effort breakdown ──────────────────────────────────────────────────────
      const eff = {};
      for (const s of specs) { const e = (s.effort || "?").toUpperCase(); eff[e] = (eff[e] || 0) + 1; }
      const effParts = ["XS","S","M","L","XL"].filter(e => eff[e]).map(e => `${eff[e]} ${e}`).join(" · ");
      if (effParts) body += gsKV("Effort", effParts);

      // ── Risk breakdown ────────────────────────────────────────────────────────
      const riskCnt = {};
      for (const s of specs) { const r = (s.risk || "?").toLowerCase(); riskCnt[r] = (riskCnt[r] || 0) + 1; }
      const riskParts = ["low","medium","high","critical"].filter(r => riskCnt[r]).map(r => {
        const cls = r === "critical" || r === "high" ? "gs-fail" : r === "medium" ? "gs-warn" : "gs-ok";
        return `<span class="${cls}">${riskCnt[r]} ${escapeHtml(r)}</span>`;
      }).join(" · ");
      if (riskParts) body += gsKV("Risk profile", riskParts);

      // ── Export links ──────────────────────────────────────────────────────────
      body += `<div class="gs-section">
        <span class="gs-label">Exports</span>
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:4px;">
          <a class="gs-link" href="/runs/${RUN_ID}/export/openapi"
             download="openapi.yaml">&#8659; OpenAPI 3.1 spec</a>
          <a class="gs-link" href="/runs/${RUN_ID}/export/jira"
             download="jira_bulk_import.json">&#8659; Jira bulk import</a>
          <a class="gs-link" href="/runs/${RUN_ID}/files/feature-specs.html"
             target="_blank" rel="noopener">&#8599; Full feature specs</a>
        </div>
      </div>`;

      // ── Feature list preview (first 8) ────────────────────────────────────────
      if (specs.length) {
        const rows = specs.slice(0, 8).map(s =>
          `<li><strong>${escapeHtml(s.title || s.seam_id || "—")}</strong>` +
          ` <span class="gs-dim">${escapeHtml((s.effort || "?").toUpperCase())} &middot; ${s.story_points || 0} pts</span></li>`
        ).join("");
        const more = specs.length > 8
          ? `<li class="gs-dim">&hellip; ${specs.length - 8} more &mdash; <a class="gs-link" href="/runs/${RUN_ID}/files/feature-specs.html" target="_blank" rel="noopener">view all</a></li>`
          : "";
        body += `<div class="gs-section">
          <span class="gs-label">Features (${specs.length})</span>
          <ul class="gs-list">${rows}${more}</ul>
        </div>`;
      }
    }

    else if (gateId === "gate_5") {
      const passed   = artifact.review_passed;
      const overall  = String(artifact.overall || (passed ? "PASS" : "FAIL")).toUpperCase();
      const sevCounts = artifact.severity_counts || {};
      const metrics  = artifact.metrics || {};

      // ── Overall verdict ──────────────────────────────────────────────────────
      const verdictCls = overall === "PASS" ? "gs-ok" : overall === "WARN" ? "gs-warn" : "gs-fail";
      body += gsKV("PR review", `<span class="${verdictCls}">${escapeHtml(overall)}</span>`);
      body += gsKV("Files reviewed", metrics.total_files ?? "–");
      if (metrics.total_lines) {
        const todoRatio = metrics.todo_ratio != null ? ` · ${(metrics.todo_ratio * 100).toFixed(0)}% TODO` : "";
        body += gsKV("Code lines", `${metrics.total_lines}${escapeHtml(todoRatio)}`);
      }
      if (metrics.has_ports != null) {
        body += gsKV("Port interfaces", metrics.has_ports
          ? `<span class="gs-ok">present</span>`
          : `<span class="gs-warn">missing</span>`);
      }

      // ── Finding severity counts ──────────────────────────────────────────────
      const allFindings = artifact.findings || [];
      if (allFindings.length) {
        const sevParts = ["BLOCKER","MAJOR","MINOR"].filter(s => sevCounts[s]).map(s => {
          const cls = s === "BLOCKER" ? "gs-fail" : s === "MAJOR" ? "gs-warn" : "gs-ok";
          return `<span class="${cls}">${sevCounts[s]} ${escapeHtml(s.toLowerCase())}</span>`;
        }).join(" · ");
        body += gsKV("Findings", `${allFindings.length} total${sevParts ? " — " + sevParts : ""}`);
      } else {
        body += gsKV("Findings", `<span class="gs-ok">none</span>`);
      }
      if (artifact.summary) body += `<p class="gs-note">${escapeHtml(artifact.summary)}</p>`;

      // ── Trivy output CVE summary ─────────────────────────────────────────────
      const trivyOut = extraData.trivy;
      if (trivyOut && !trivyOut.error && trivyOut.summary && trivyOut.summary.total > 0) {
        const ts = trivyOut.summary;
        const trivyParts = ["CRITICAL","HIGH","MEDIUM","LOW"]
          .filter(s => ts[s])
          .map(s => {
            const cls = (s === "CRITICAL" || s === "HIGH") ? "gs-fail"
                      : s === "MEDIUM" ? "gs-warn" : "gs-ok";
            return `<span class="${cls}">${ts[s]} ${escapeHtml(s.toLowerCase())}</span>`;
          }).join(" · ");
        body += gsKV(
          "Trivy CVEs (output)",
          `${ts.total} CVE(s) in generated code${trivyParts ? " — " + trivyParts : ""}` +
          ` <span class="gs-dim" style="font-size:0.7em;">(post-Gate 5 scan)</span>`
        );
        if (ts.CRITICAL || ts.HIGH) {
          const topCves = (trivyOut.vulnerabilities || [])
            .filter(v => v.severity === "CRITICAL" || v.severity === "HIGH")
            .slice(0, 5);
          if (topCves.length) {
            body += `<div class="gs-node-list" style="margin-top:4px;">`;
            for (const v of topCves) {
              body += `<div class="gs-node-card" style="border-left-color:#c0392b">
                <div class="gs-node-header">
                  <span class="gs-node-type" style="color:#c0392b;border-color:#c0392b">${escapeHtml(v.severity)}</span>
                  <span class="gs-node-sig"><strong>${escapeHtml(v.cve_id || v.id)}</strong> · ${escapeHtml(v.pkg_name)} ${escapeHtml(v.installed_version || "")}</span>
                </div>
                ${v.fixed_version ? `<div class="gs-node-summary gs-ok">Fix: upgrade to ${escapeHtml(v.fixed_version)}</div>` : ""}
              </div>`;
            }
            body += `</div>`;
          }
        }
      } else if (trivyOut && !trivyOut.error && trivyOut.summary && trivyOut.summary.total === 0) {
        body += gsKV("Trivy CVEs (output)", `<span class="gs-ok">none detected in generated code</span>`);
      }

      // ── BLOCKER / MAJOR finding cards ────────────────────────────────────────
      const critical = allFindings.filter(f => f.severity === "BLOCKER" || f.severity === "MAJOR");
      if (critical.length) {
        body += `<div class="gs-node-list">`;
        for (const f of critical.slice(0, 10)) {
          const sev = f.severity || "MINOR";
          const col = sev === "BLOCKER" ? "#c0392b" : "#8a5a00";
          body += `<div class="gs-node-card" style="border-left-color:${col}">
            <div class="gs-node-header">
              <span class="gs-node-type" style="color:${col};border-color:${col}">${escapeHtml(sev)}</span>
              <span class="gs-node-sig">${escapeHtml(f.check || "")} · <span style="font-family:monospace">${escapeHtml(f.path || "")}</span></span>
            </div>
            <div class="gs-node-summary">${escapeHtml(f.message || "")}</div>
          </div>`;
        }
        body += `</div>`;
      }
    }

  } catch (e) {
    console.warn("buildGateSummary error", gateId, e);
    return "";
  }

  if (!body) return "";
  return `<details class="gate-summary">
    <summary class="gate-summary-title">${escapeHtml(title)}</summary>
    <div class="gate-summary-body">${body}</div>
  </details>`;
}

const GATE_ARTIFACT_KEY = {
  gate_1:   "ir_graph",
  gate_2:   "bounded_context_map",
  gate_3:   "tnas",
  gate_4:   "security_report",
  gate_4_5: "feature_specs",
  gate_5:   "review_report",
};

// ─── Gate panel ──────────────────────────────────────────────────────────────
function renderGatePanel(payload) {
  const gateId = payload.gate_id;
  const card = document.createElement("div");
  card.className = "gate-card open";
  card.id = `gate-${gateId}`;
  const invalidBanner = payload.artifact_valid === false
    ? `<div class="gate-invalid-banner">⚠ This artifact fails its own validity check — it may be leftover output from a crashed agent turn rather than a real result. Review carefully before approving.</div>`
    : "";
  card.innerHTML = `
    <header>
      <h3>${escapeHtml(payload.gate_name)}</h3>
      <span class="badge">${escapeHtml(gateId)}</span>
    </header>
    ${invalidBanner}
    <div class="gate-summary-slot"></div>
    <p class="reviewer">Reviewer role: <strong>${escapeHtml(payload.expected_reviewer_role)}</strong></p>
    <p class="sha">Artifact SHA: <code>${escapeHtml(payload.artifact_sha)}</code></p>
    <div class="gate-actions">
      <form hx-post="/runs/${RUN_ID}/gates/${gateId}/approve" hx-target="#gate-${gateId} .gate-result" hx-swap="innerHTML">
        <input type="text" name="reviewer_name" placeholder="Your name" required>
        <input type="text" name="notes" placeholder="Notes (optional)">
        <button type="submit" class="approve">Approve</button>
      </form>
      <form hx-post="/runs/${RUN_ID}/gates/${gateId}/reject" hx-target="#gate-${gateId} .gate-result" hx-swap="innerHTML">
        <input type="text" name="reviewer_name" placeholder="Your name" required>
        <input type="text" name="reason" placeholder="Reason (becomes a RejectionConstraint)" required>
        <button type="submit" class="reject">Reject</button>
      </form>
    </div>
    <div class="gate-result"></div>
  `;

  const existing = document.getElementById(`gate-${gateId}`);
  if (existing) existing.replaceWith(card);
  else gatesEl.appendChild(card);
  htmx.process(card);

  setTimeout(() => {
    const actions = card.querySelector(".gate-actions");
    if (actions) actions.scrollIntoView({ behavior: "smooth", block: "nearest" });
    else card.scrollIntoView({ behavior: "smooth", block: "start" });
  }, 120);

  const artKey = GATE_ARTIFACT_KEY[gateId];
  if (artKey) {
    const slot = card.querySelector(".gate-summary-slot");
    const artFetch = fetch(`/runs/${RUN_ID}/artifacts/${artKey}`)
      .then((r) => r.ok ? r.json() : null)
      .catch(() => null);
    const trivyFetch = gateId === "gate_4"
      ? fetch(`/runs/${RUN_ID}/artifacts/trivy_report`).then(r => r.ok ? r.json() : null).catch(() => null)
      : gateId === "gate_5"
      ? fetch(`/runs/${RUN_ID}/artifacts/trivy_output_report`).then(r => r.ok ? r.json() : null).catch(() => null)
      : Promise.resolve(null);
    Promise.all([artFetch, trivyFetch]).then(([artifact, trivyData]) => {
      if (slot && artifact) {
        const extraData = trivyData ? { trivy: trivyData } : {};
        const html = buildGateSummary(gateId, artifact, extraData);
        if (html) slot.innerHTML = html;
      }
    });
  }
}

function renderCompletionCard(artifacts, paused = false) {
  const existing = document.getElementById("completion-card");
  if (existing) existing.remove();

  const ARTIFACT_LABELS = {
    ir_graph:            "IR property graph",
    bounded_context_map: "Bounded context map",
    tnas:                "TNAS · fitness suite",
    security_report:     "Security report",
    review_report:       "PR review report",
  };

  const artItems = artifacts
    .map((k) => `<li><button class="completion-art-btn art-btn" data-key="${escapeHtml(k)}">${escapeHtml(ARTIFACT_LABELS[k] || k)}</button></li>`)
    .join("");

  const card = document.createElement("div");
  card.id = "completion-card";
  card.className = "completion-card";
  card.innerHTML = `
    <div class="completion-mark"></div>
    <h3 class="completion-heading">${paused ? "Stopped after planning" : "Pipeline complete"}</h3>
    <p class="completion-sub">${paused
      ? "Analysis and planning finished through Gate 4.5. Code translation was not started — every artifact produced so far is still downloadable."
      : "All phases and gates finished — analysis, code generation, PR approval, and Trivy output scan."}</p>
    ${artItems ? `<ul class="completion-artifacts">${artItems}</ul>` : ""}
  `;

  card.querySelectorAll(".completion-art-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      fetchAndShowArtifact(btn.dataset.key, false);
      switchTab("artifacts");
    });
  });

  const placeholder = gatesEl.querySelector("p.hint");
  if (placeholder) placeholder.remove();
  gatesEl.prepend(card);
  card.scrollIntoView({ behavior: "smooth", block: "start" });
}

function markGateResolved(payload) {
  const card = document.getElementById(`gate-${payload.gate_id}`);
  if (!card) return;
  card.classList.remove("open");
  card.classList.add("resolved");
  card.dataset.decision = payload.decision;

  const actions = card.querySelector(".gate-actions");
  if (actions) actions.hidden = true;

  // A manual approval's "Approved by X: notes" text comes from the htmx-swapped
  // response body of the approve form. An auto-approved gate never makes that
  // HTTP call, so fill it here instead — only if still empty, so a manual
  // same-tab approval's already-swapped text is never overwritten.
  const resultDivEarly = card.querySelector(".gate-result");
  if (resultDivEarly && !resultDivEarly.innerHTML.trim() && payload.decision === "APPROVED" && payload.reviewer_name) {
    resultDivEarly.innerHTML = `<div class="ok">Gate ${escapeHtml(payload.gate_id)} approved by `
      + `${escapeHtml(payload.reviewer_name)}${payload.notes ? ": " + escapeHtml(payload.notes) : ""}.</div>`;
  }

  if (payload.decision === "ESCALATED" || card.querySelector(".gate-restart")) return;

  const restartForm = document.createElement("form");
  restartForm.className = "gate-restart";
  restartForm.setAttribute("hx-post", `/runs/${RUN_ID}/restart`);
  restartForm.setAttribute("hx-target", `#gate-${payload.gate_id} .gate-result`);
  restartForm.setAttribute("hx-swap", "innerHTML");
  restartForm.innerHTML = `
    <input type="hidden" name="from_gate" value="${escapeHtml(payload.gate_id)}">
    <button type="submit" class="restart-btn" title="Re-run the pipeline from this gate">↩ Restart from here</button>
  `;
  const resultDiv = card.querySelector(".gate-result");
  if (resultDiv) card.insertBefore(restartForm, resultDiv);
  else card.appendChild(restartForm);
  htmx.process(restartForm);
}

// ─── Trace panel ─────────────────────────────────────────────────────────────
// Renders a JSON value as nested, collapsible <details> nodes (like a
// browser's native JSON viewer) instead of a single unbroken JSON.stringify
// blob — the latter has almost no whitespace and can't wrap, so it overflows
// the panel width instead of fitting it.
function jsonTreeHtml(value, depth) {
  if (value === null || value === undefined) {
    return `<span class="json-val json-null">null</span>`;
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return `<span class="json-val json-punct">[]</span>`;
    const open = depth <= 1 ? " open" : "";
    const rows = value
      .map((v, i) => `<div class="json-row">${jsonTreeHtml(v, depth + 1)}${i < value.length - 1 ? "," : ""}</div>`)
      .join("");
    return `<details class="json-node"${open}><summary>[ <span class="json-count">${value.length} item${value.length === 1 ? "" : "s"}</span> ]</summary><div class="json-children">${rows}</div></details>`;
  }
  if (typeof value === "object") {
    const keys = Object.keys(value);
    if (keys.length === 0) return `<span class="json-val json-punct">{}</span>`;
    const open = depth <= 1 ? " open" : "";
    const rows = keys
      .map((k, i) => `<div class="json-row"><span class="json-key">${escapeHtml(k)}</span>: ${jsonTreeHtml(value[k], depth + 1)}${i < keys.length - 1 ? "," : ""}</div>`)
      .join("");
    return `<details class="json-node"${open}><summary>{ <span class="json-count">${keys.length} key${keys.length === 1 ? "" : "s"}</span> }</summary><div class="json-children">${rows}</div></details>`;
  }
  if (typeof value === "string") return `<span class="json-val json-string">"${escapeHtml(value)}"</span>`;
  if (typeof value === "number") return `<span class="json-val json-number">${value}</span>`;
  if (typeof value === "boolean") return `<span class="json-val json-bool">${value}</span>`;
  return escapeHtml(String(value));
}

// Mirrors app.py's _extract_json(), extended for one more real shape seen in
// live traces: some agents emit prose *followed by* raw JSON with no fence
// at all (no ```json```), not just fenced JSON or pure JSON with no prose.
// Tries, in order: (1) the whole text is already JSON, (2) a fenced
// ```json ... ``` block with optional prose around it, (3) prose followed by
// unfenced JSON — found by trying every "{"/"[" position as a possible start
// and taking the first one that parses cleanly through to the end of the
// text. Returns null (render as plain text, unchanged) if nothing matches.
function extractJsonFromText(text) {
  const trimmed = text.trim();

  try {
    return { json: JSON.parse(trimmed), before: "", after: "" };
  } catch (e) { /* not pure JSON — keep looking */ }

  const fenced = trimmed.match(/```(?:json)?\s*([\s\S]+?)\s*```/);
  if (fenced) {
    try {
      return {
        json: JSON.parse(fenced[1].trim()),
        before: trimmed.slice(0, fenced.index).trim(),
        after: trimmed.slice(fenced.index + fenced[0].length).trim(),
      };
    } catch (e) { /* fenced block wasn't valid JSON either — keep looking */ }
  }

  for (let i = 0; i < trimmed.length; i++) {
    if (trimmed[i] !== "{" && trimmed[i] !== "[") continue;
    try {
      return { json: JSON.parse(trimmed.slice(i)), before: trimmed.slice(0, i).trim(), after: "" };
    } catch (e) { /* this position wasn't a valid JSON start — try the next */ }
  }

  return null;
}

function appendTrace(phase, payload) {
  const entry = document.createElement("div");
  entry.className = `trace-entry phase-${phase}`;
  let body = "";
  if (payload.parts) {
    for (const p of payload.parts) {
      if (p.type === "text" && p.text) {
        const extracted = extractJsonFromText(p.text);
        if (extracted) {
          if (extracted.before) body += `<div class="text">${escapeHtml(extracted.before)}</div>`;
          body += `<div class="json-tree">${jsonTreeHtml(extracted.json, 0)}</div>`;
          if (extracted.after) body += `<div class="text">${escapeHtml(extracted.after)}</div>`;
        } else {
          body += `<div class="text">${escapeHtml(p.text)}</div>`;
        }
      } else if (p.type === "function_call") {
        body += `<div class="fcall">→ <code>${escapeHtml(p.name)}</code></div><div class="json-tree">${jsonTreeHtml(p.args, 0)}</div>`;
      } else if (p.type === "function_response") {
        body += `<div class="fresp">← <code>${escapeHtml(p.name)}</code></div><div class="json-tree">${jsonTreeHtml(p.response, 1)}</div>`;
      }
    }
  }
  if (!body) body = `<div class="json-tree">${jsonTreeHtml(payload, 1)}</div>`;
  entry.innerHTML = `
    <header><span class="author">${escapeHtml(payload.author || "unknown")}</span><span class="phase">${escapeHtml(phase)}</span></header>
    ${body}
  `;
  trace.appendChild(entry);
  trace.scrollTop = trace.scrollHeight;
}

// ─── Diagnostics panel ───────────────────────────────────────────────────────
const diagFeed = document.getElementById("diagnostics-feed");
const diagCountError = document.getElementById("diag-count-error");
const diagCountWarning = document.getElementById("diag-count-warning");
const diagCountDebug = document.getElementById("diag-count-debug");
const diagClearBtn = document.getElementById("diag-clear");
const diagTabBadge = document.getElementById("diag-tab-badge");
let diagBadgeCount = 0;

const diagCounts = { ERROR: 0, WARNING: 0, DEBUG: 0 };

function updateDiagCounts() {
  diagCountError.textContent = `${diagCounts.ERROR} error${diagCounts.ERROR === 1 ? "" : "s"}`;
  diagCountWarning.textContent = `${diagCounts.WARNING} warning${diagCounts.WARNING === 1 ? "" : "s"}`;
  diagCountDebug.textContent = `${diagCounts.DEBUG} debug`;
}

function appendDiagnostic(severity, phase, payload) {
  const msg = payload && payload.message ? payload.message : JSON.stringify(payload);
  const source = (payload && payload.source) || "unknown";
  const ts = (payload && payload.timestamp) || new Date().toISOString();
  const tb = payload && payload.traceback ? payload.traceback : "";
  const ctx = payload && payload.context ? payload.context : null;

  const empty = diagFeed.querySelector(".diag-empty");
  if (empty) empty.remove();

  const entry = document.createElement("div");
  entry.className = `diag-entry diag-${severity.toLowerCase()}`;
  entry.dataset.severity = severity;
  entry.innerHTML = `
    <header>
      <span class="diag-sev">${escapeHtml(severity)}</span>
      <span class="diag-phase">${escapeHtml(phase || "—")}</span>
      <span class="diag-source">${escapeHtml(source)}</span>
      <span class="diag-time">${escapeHtml(ts.slice(11, 19))}</span>
    </header>
    <div class="diag-message">${escapeHtml(msg)}</div>
    ${ctx && Object.keys(ctx).length
      ? `<details class="diag-context"><summary>Context</summary><pre>${escapeHtml(JSON.stringify(ctx, null, 2))}</pre></details>`
      : ""}
    ${tb
      ? `<details class="diag-traceback"><summary>Traceback</summary><pre>${escapeHtml(tb)}</pre></details>`
      : ""}
  `;
  diagFeed.prepend(entry);

  diagCounts[severity] = (diagCounts[severity] || 0) + 1;
  updateDiagCounts();
}

diagClearBtn.addEventListener("click", () => {
  diagFeed.innerHTML = '<p class="diag-empty">No diagnostic events yet.</p>';
  diagCounts.ERROR = diagCounts.WARNING = diagCounts.DEBUG = 0;
  updateDiagCounts();
  diagBadgeCount = 0;
  if (diagTabBadge) { diagTabBadge.textContent = ""; diagTabBadge.classList.remove("visible"); }
});

// ─── Live status line ────────────────────────────────────────────────────────
const progressEl = document.getElementById("pipeline-progress");

// ─── Stop TDD loop control ───────────────────────────────────────────────────
const runControls = document.getElementById("run-controls");
const tddStopForm = document.getElementById("tdd-stop-form");
const _TDD_LOOP_PHASES = new Set(["code_writer", "skeptical_review", "test_review", "functional_review"]);
function setTddStopVisible(visible) {
  if (runControls) runControls.hidden = !visible;
}

function setLiveStatus(state, text) {
  if (!liveStatusEl) return;
  liveStatusEl.removeAttribute("hidden");
  if (livedot) livedot.className = `live-dot${state !== "running" ? ` ${state}` : ""}`;
  if (liveTextEl) liveTextEl.textContent = text;
  if (progressEl) {
    if (state === "running") progressEl.removeAttribute("hidden");
    else progressEl.setAttribute("hidden", "");
  }
}

// ─── Trace badge ─────────────────────────────────────────────────────────────
const traceTabBadge = document.getElementById("trace-tab-badge");
let traceBadgeCount = 0;
let traceTabActive = false;

function bumpTraceBadge() {
  if (traceTabActive) return;
  traceBadgeCount++;
  if (traceTabBadge) {
    traceTabBadge.textContent = traceBadgeCount > 99 ? "99+" : traceBadgeCount;
    traceTabBadge.classList.add("visible");
  }
}

// ─── Processing (seam status) badge ─────────────────────────────────────────
const processingTabBadge = document.getElementById("processing-tab-badge");
let processingBadgeCount = 0;
let processingTabActive = false;

function bumpProcessingBadge() {
  if (processingTabActive) return;
  processingBadgeCount++;
  if (processingTabBadge) {
    processingTabBadge.textContent = processingBadgeCount > 99 ? "99+" : processingBadgeCount;
    processingTabBadge.classList.add("visible");
  }
}

// ─── Seam tab ────────────────────────────────────────────────────────────────
const seamTabBadge = document.getElementById("seam-tab-badge");
let _seamDataLoaded = false;
let _seamData = null;

const SEAM_COLORS = {
  boundary:     { fg: "#e09c3c", bg: "rgba(224,156,60,0.10)",  label: "Boundary"     },
  object:       { fg: "#3cb8b0", bg: "rgba(60,184,176,0.10)",  label: "Object"       },
  preprocessing:{ fg: "#9b59b6", bg: "rgba(155,89,182,0.10)",  label: "Preprocessing"},
  link:         { fg: "#5c8a5c", bg: "rgba(92,138,92,0.10)",   label: "Link"         },
  message:      { fg: "#c0632f", bg: "rgba(192,99,47,0.10)",   label: "Message"      },
};

function _seamFanIn(seam) {
  // Parse "fan-in: 42" or "N CALLS edges…" from evidence for sort ordering.
  for (const ev of (seam.evidence || [])) {
    const m = ev.match(/(\d+)/);
    if (m) return parseInt(m[1], 10);
  }
  return 0;
}

// ── Seam type colours (shared by roadmap and graph) ──────────────────────────
const SEAM_TYPE_COLOR = {
  boundary:      "#e09c3c",
  object:        "#3cb8b0",
  preprocessing: "#9b59b6",
  link:          "#5c8a5c",
  message:       "#c0632f",
};

const SEQ_ACCENT = { 1: "#2d7d46", 2: "#1a5fa6", 3: "#8a5a00", 4: "#6b6b6b" };
const SEQ_LABEL  = {
  1: "Seq 1 · start now",
  2: "Seq 2 · after seq 1",
  3: "Seq 3 · parallel · after seq 2",
  4: "Seq 4 · after all seq 3 streams",
};

// ── Seam row builder (shared by roadmap + standalone report) ──────────────────
function _seamRow(s, compact = false) {
  const leaf = s.location.split(".").pop();
  const ev   = (s.evidence || [])[0] || "";
  const pts  = s.work?.story_points ?? "";
  const col  = SEAM_TYPE_COLOR[s.type] || "#888";
  if (compact) {
    return `<tr>
      <td class="sr-loc">${escapeHtml(leaf)}</td>
      <td class="sr-ev">${escapeHtml(ev)}</td>
      <td class="sr-pts" style="color:${col}">${pts}p</td>
    </tr>`;
  }
  const src = s.source_location
    ? escapeHtml(s.source_location.split("/").slice(-2).join("/")) : "";
  return `<div class="ws-seam-row">
    <div class="ws-seam-left">
      <span class="ws-seam-loc">${escapeHtml(leaf)}</span>
      ${src ? `<span class="ws-seam-src">${src}</span>` : ""}
      <span class="ws-seam-ev">${escapeHtml(ev)}</span>
    </div>
    <span class="ws-seam-pts" style="color:${col}">${pts}p</span>
  </div>`;
}

// ── Stream card HTML ──────────────────────────────────────────────────────────
function _streamCard(ws, seamById) {
  const seams  = (ws.seam_ids || []).map(id => seamById[id]).filter(Boolean);
  const byType = {};
  for (const s of seams) (byType[s.type] = byType[s.type] || []).push(s);

  const SHOW = 10;
  let bodyHtml = `<p class="ws-rationale">${escapeHtml(ws.rationale || "")}</p>`;
  if (ws.depends_on?.length) {
    const deps = ws.depends_on.map(d => escapeHtml(d.replace(/_/g, " "))).join(", ");
    bodyHtml += `<p class="ws-deps">Depends on: <span>${deps}</span></p>`;
  }
  for (const [type, list] of Object.entries(byType).sort()) {
    const col = SEAM_TYPE_COLOR[type] || "#888";
    bodyHtml += `<div class="ws-type-hdr" style="color:${col}">${type} · ${list.length}</div>`;
    const visible = list.slice(0, SHOW);
    const rest    = list.slice(SHOW);
    bodyHtml += visible.map(s => _seamRow(s)).join("");
    if (rest.length) {
      bodyHtml += `<button class="ws-show-more">+ ${rest.length} more</button>`
               + `<div hidden>${rest.map(s => _seamRow(s)).join("")}</div>`;
    }
  }

  const riskCls = `ws-risk-${(ws.risk || "").toLowerCase()}`;
  return `<details class="ws-card">
    <summary class="ws-card-summary">
      <div class="ws-card-main">
        <div class="ws-card-name">${escapeHtml(ws.name)}</div>
        <div class="ws-card-meta">
          <span>${ws.seam_count} seams · ${ws.story_points} pts</span>
          <span class="ws-risk ${riskCls}">${ws.risk}</span>
          <span class="ws-phase">${ws.migration_phase || ""}</span>
        </div>
      </div>
      <div class="ws-pts-chip">${ws.story_points}</div>
    </summary>
    <div class="ws-card-body">${bodyHtml}</div>
  </details>`;
}

// ── Roadmap renderer (primary Seams tab view) ─────────────────────────────────
function _buildRoadmap(seamData, wsData) {
  const seamById = Object.fromEntries((seamData.seams || []).map(s => [s.id, s]));
  const streams  = (wsData.work_streams || []).filter(w => w.seam_count > 0);
  const total    = wsData.total_seams || 0;
  const totalPts = wsData.total_story_points || 0;

  let html = `<div class="ws-header">
    <span class="ws-totals">${total} seams · ${totalPts} pts · ${streams.length} streams</span>
    <button class="ws-export-btn" id="ws-export-btn">↓ Seam report</button>
  </div>`;

  const bySeq = {};
  for (const ws of streams) (bySeq[ws.seq] = bySeq[ws.seq] || []).push(ws);

  for (const [seq, group] of Object.entries(bySeq).sort(([a], [b]) => a - b)) {
    const accent = SEQ_ACCENT[seq] || "#888";
    html += `<div class="ws-lane" style="--seq-accent:${accent}">
      <div class="ws-lane-hdr">${SEQ_LABEL[seq] || `seq ${seq}`}</div>
      <div class="ws-cards">${group.map(ws => _streamCard(ws, seamById)).join("")}</div>
    </div>`;
  }
  return html;
}

// ── Fallback: type-grouped view (no work-streams data) ────────────────────────
function _buildByType(data) {
  const seams  = data.seams || [];
  const counts = data.seam_counts || {};
  const byType = { boundary: [], object: [], preprocessing: [], link: [], message: [] };
  for (const s of seams) byType[s.type]?.push(s);
  for (const t of Object.keys(byType)) byType[t].sort((a, b) => _seamFanIn(b) - _seamFanIn(a));

  const pills = Object.entries(SEAM_TYPE_COLOR).map(([type, col]) => {
    const n = counts[type] || 0;
    return `<span class="seam-pill" style="color:${col};border-color:${col}">${n} ${type}</span>`;
  }).join("");

  const TRUNC = { object: 30 };
  const sections = Object.entries(SEAM_TYPE_COLOR).map(([type, col]) => {
    const list = byType[type] || [];
    if (!list.length) return "";
    const vis  = list.slice(0, TRUNC[type] || list.length);
    const rest = TRUNC[type] ? list.slice(TRUNC[type]) : [];
    const rows = vis.map(s => {
      const ev  = (s.evidence || []).map(e => `<span class="seam-ev">${escapeHtml(e)}</span>`).join(" · ");
      const src = s.source_location
        ? `<div class="seam-src">${escapeHtml(s.source_location.split("/").slice(-2).join("/"))}</div>` : "";
      return `<div class="seam-entry">
        <div class="seam-entry-head"><span class="seam-loc">${escapeHtml(s.location)}</span>${src}</div>
        ${ev ? `<div class="seam-entry-ev">${ev}</div>` : ""}
        ${s.substitution_note ? `<div class="seam-note">${escapeHtml(s.substitution_note)}</div>` : ""}
      </div>`;
    }).join("");
    const more = rest.length
      ? `<button class="seam-show-more">+ ${rest.length} more…</button><div hidden>${
          rest.map(s => `<div class="seam-entry"><span class="seam-loc">${escapeHtml(s.location)}</span></div>`).join("")
        }</div>` : "";
    const open = type === "boundary" || type === "link" ? "open" : "";
    return `<details class="seam-section" ${open}>
      <summary class="seam-section-title">
        <span class="seam-section-badge" style="color:${col};border-color:${col}">${type}</span>
        <span class="seam-section-count">${list.length}</span>
      </summary>
      <div class="seam-section-body">${rows}${more}</div>
    </details>`;
  }).join("");

  return `<div class="seam-summary-strip">${pills}</div>
    <p class="seam-narrative">${escapeHtml(data.summary || "")}</p>
    ${sections}`;
}

// ── Main entry point ──────────────────────────────────────────────────────────
function renderSeamPanel(data) {
  const feed = document.getElementById("seam-feed");
  if (!feed) return;
  _seamData = data;

  const total = data.total_seams || data.total || 0;
  if (seamTabBadge) {
    seamTabBadge.textContent = total > 999 ? "999+" : String(total);
    seamTabBadge.classList.add("visible");
  }

  if (window.WORK_STREAMS_DATA?.work_streams?.length) {
    feed.innerHTML = _buildRoadmap(data, window.WORK_STREAMS_DATA);
    // Seam report download (client-side blob)
    document.getElementById("ws-export-btn")
      ?.addEventListener("click", exportSeamReport);
  } else {
    feed.innerHTML = _buildByType(data);
  }

  feed.querySelectorAll(".seam-show-more, .ws-show-more").forEach(btn => {
    btn.addEventListener("click", () => {
      if (btn.nextElementSibling) btn.nextElementSibling.hidden = false;
      btn.remove();
    });
  });
}

// ── Generic dropdown helper ───────────────────────────────────────────────────
function _initDropdownMenu(btnId, listId) {
  const btn  = document.getElementById(btnId);
  const list = document.getElementById(listId);
  if (!btn || !list) return;

  btn.addEventListener("click", e => {
    e.stopPropagation();
    // Close any other open dropdown (class-based or details-based)
    document.querySelectorAll(".reports-menu-list.open").forEach(el => {
      if (el !== list) {
        el.classList.remove("open");
        el.previousElementSibling?.setAttribute("aria-expanded", "false");
      }
    });
    const open = list.classList.toggle("open");
    btn.setAttribute("aria-expanded", String(open));
  });

  document.addEventListener("click", () => {
    list.classList.remove("open");
    btn.setAttribute("aria-expanded", "false");
  });

  document.addEventListener("keydown", e => {
    if (e.key === "Escape") {
      list.classList.remove("open");
      btn.setAttribute("aria-expanded", "false");
    }
  });
}

// ── Reports dropdown ──────────────────────────────────────────────────────────
function _initReportsMenu() {
  _initDropdownMenu("reports-menu-btn", "reports-menu-list");
}

// ── Download generate-and-regenerate flow ──────────────────────────────────────
// "⚡ Generate/Regenerate …" buttons (class dl-regen-btn): POST to
// /runs/{id}/zip/{type}, which (re)builds the zip on the server, overwriting
// any previous one at the same path — a folder's zip can be rebuilt as many
// times as needed within the same page load, not just once. On success the
// button's paired <a download> link (data-link-id, created on first success)
// is pointed at the fresh file and the button relabels itself "Regenerate".
// Pre-built download links present on page load: no JS needed — browser
// handles them natively.
function _initDownloadLinks() {
  document.querySelectorAll(".dl-regen-btn").forEach(btn => {
    btn.addEventListener("click", async e => {
      e.preventDefault();
      e.stopPropagation();
      if (btn.dataset.generating) return;

      btn.dataset.generating = "1";
      const origText = btn.textContent.trim();
      btn.textContent = "⏳ Generating…";
      btn.disabled = true;

      try {
        const res = await fetch(`/runs/${RUN_ID}/zip/${btn.dataset.folderType}`, { method: "POST" });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          btn.textContent = `⚠ ${data.detail || "Failed"}`;
          setTimeout(() => { btn.textContent = origText; }, 3500);
          return;
        }

        const filename = data.filename || `${btn.dataset.folderName}.zip`;
        const linkId = btn.dataset.linkId;
        let link = document.getElementById(linkId);
        if (!link) {
          link = document.createElement("a");
          link.id = linkId;
          link.className = "reports-menu-item";
          btn.parentElement.insertBefore(link, btn);
        }
        // Query param is cosmetic cache-busting only — the server's own
        // Last-Modified/ETag (recomputed from the file's real mtime/size on
        // every request) already forces a fresh fetch after a rebuild.
        link.href = `/runs/${RUN_ID}/download/${btn.dataset.folderType}?v=${data.size || 0}`;
        link.setAttribute("download", filename);
        link.textContent = `⬇ ${filename}`;

        btn.textContent = `🔄 Regenerate ${filename}`;
      } catch {
        btn.textContent = "⚠ Failed";
        setTimeout(() => { btn.textContent = origText; }, 3500);
      } finally {
        btn.disabled = false;
        delete btn.dataset.generating;
      }
    });
  });
}

// ── Standalone HTML report (legacy helper, kept for external callers) ─────────
function _wireRunFileBtn(btnId, filename) {
  const el = document.getElementById(btnId);
  if (!el) return;
  el.href     = `/runs/${RUN_ID}/files/${filename}`;
  el.download = filename;
}

function exportSeamReport() {
  const seamData = _seamData;
  const wsData   = window.WORK_STREAMS_DATA;
  if (!seamData || !wsData) {
    console.warn("exportSeamReport: missing data", { seamData: !!seamData, wsData: !!wsData });
    return;
  }

  const seamById = Object.fromEntries((seamData.seams || []).map(s => [s.id, s]));
  const streams  = (wsData.work_streams || []).filter(w => w.seam_count > 0);
  const runId    = RUN_ID || "unknown";
  const now      = new Date().toISOString().slice(0, 10);

  // ── Summary table ──
  const summaryRows = streams.map(ws => {
    const risk = (ws.risk || "").toLowerCase();
    const riskStyle = risk === "high" ? "color:#c0392b" : risk === "medium" ? "color:#8a5a00" : "color:#2d7d46";
    const deps = (ws.depends_on || []).map(d => d.replace(/_/g," ")).join(", ") || "—";
    return `<tr>
      <td>${escapeHtml(ws.name)}</td>
      <td style="text-align:center">${ws.seq}</td>
      <td style="text-align:right">${ws.seam_count}</td>
      <td style="text-align:right">${ws.story_points}</td>
      <td style="${riskStyle}">${ws.risk}</td>
      <td>${ws.migration_phase || ""}</td>
      <td style="font-size:11px;color:#666">${escapeHtml(deps)}</td>
    </tr>`;
  }).join("");

  // ── Per-stream sections ──
  const streamSections = streams.map(ws => {
    const seams  = (ws.seam_ids || []).map(id => seamById[id]).filter(Boolean);
    const byType = {};
    for (const s of seams) (byType[s.type] = byType[s.type] || []).push(s);
    const typeRows = Object.entries(byType).sort().map(([type, list]) => {
      const col = SEAM_TYPE_COLOR[type] || "#888";
      const rows = list.map(s => {
        const loc  = s.location.split(".").pop();
        const ev   = (s.evidence || [])[0] || "";
        const note = s.work?.title || s.substitution_note || "";
        return `<tr>
          <td style="color:${col};font-size:11px;font-weight:600;padding:4px 8px">${type}</td>
          <td style="font-family:monospace;font-size:11px;padding:4px 8px">${escapeHtml(loc)}</td>
          <td style="font-size:11px;color:#666;padding:4px 8px">${escapeHtml(ev)}</td>
          <td style="font-size:11px;padding:4px 8px">${escapeHtml(note)}</td>
          <td style="text-align:right;font-size:11px;padding:4px 8px">${s.work?.story_points ?? ""}p</td>
        </tr>`;
      }).join("");
      return rows;
    }).join("");
    const deps = (ws.depends_on || []).map(d => d.replace(/_/g," ")).join(", ") || "none";
    return `<section style="margin:32px 0;page-break-inside:avoid">
      <h2 style="font-size:15px;font-weight:700;margin:0 0 4px;color:#171D1D">${escapeHtml(ws.name)}</h2>
      <p style="font-size:12px;color:#666;margin:0 0 8px">Seq ${ws.seq} · ${ws.seam_count} seams · ${ws.story_points} pts · ${ws.risk} risk · ${ws.migration_phase || ""} · depends on: ${escapeHtml(deps)}</p>
      <p style="font-size:12px;color:#444;margin:0 0 10px;line-height:1.5">${escapeHtml(ws.rationale || "")}</p>
      <table style="width:100%;border-collapse:collapse;font-family:system-ui,sans-serif">
        <thead><tr style="background:#f4f4f4">
          <th style="text-align:left;font-size:11px;padding:4px 8px;font-weight:600">type</th>
          <th style="text-align:left;font-size:11px;padding:4px 8px;font-weight:600">node</th>
          <th style="text-align:left;font-size:11px;padding:4px 8px;font-weight:600">evidence</th>
          <th style="text-align:left;font-size:11px;padding:4px 8px;font-weight:600">work</th>
          <th style="text-align:right;font-size:11px;padding:4px 8px;font-weight:600">pts</th>
        </tr></thead>
        <tbody>${typeRows}</tbody>
      </table>
    </section>`;
  }).join("");

  const html = `<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>Seam report · run ${escapeHtml(runId)} · ${now}</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 960px; margin: 40px auto; padding: 0 24px; color: #171D1D; }
  h1   { font-size: 22px; font-weight: 700; margin: 0 0 4px; }
  .meta { font-size: 13px; color: #666; margin: 0 0 32px; }
  table { border-collapse: collapse; width: 100%; }
  th,td { border: 1px solid #e5e5e5; padding: 6px 10px; }
  th { background: #f7f7f7; font-size: 12px; text-align: left; }
  td { font-size: 12px; }
  tr:nth-child(even) td { background: #fafafa; }
  @media print { section { page-break-inside: avoid; } }
</style>
</head><body>
<h1>Seam analysis report</h1>
<p class="meta">Run <code>${escapeHtml(runId)}</code> · generated ${now} · ${wsData.total_seams} seams · ${wsData.total_story_points} story points</p>
<h2 style="font-size:15px;font-weight:700;margin:0 0 10px">Work stream summary</h2>
<table>
  <thead><tr><th>Stream</th><th>Seq</th><th>Seams</th><th>Pts</th><th>Risk</th><th>Phase</th><th>Depends on</th></tr></thead>
  <tbody>${summaryRows}</tbody>
</table>
<hr style="margin:32px 0;border:none;border-top:1px solid #e5e5e5">
<h2 style="font-size:15px;font-weight:700;margin:0 0 24px">Stream details</h2>
${streamSections}
</body></html>`;

  const blob = new Blob([html], { type: "text/html" });
  const url  = URL.createObjectURL(blob);
  const a    = Object.assign(document.createElement("a"), {
    href: url, download: `seam-report-${runId}.html`,
  });
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

async function loadSeamPanel() {
  if (_seamDataLoaded) return;
  const feed = document.getElementById("seam-feed");
  if (!feed) return;

  // If SSR embedded both payloads at page-load time, use them directly.
  if (window.SEAM_DATA && window.WORK_STREAMS_DATA) {
    try {
      renderSeamPanel(window.SEAM_DATA);
      _seamDataLoaded = true;
    } catch (e) {
      console.error("renderSeamPanel (inline data) failed", e);
      feed.innerHTML = `<p class="seam-error">Seam render error: ${escapeHtml(String(e))}</p>`;
    }
    return;
  }

  feed.innerHTML = `<p class="seam-loading">Loading seam analysis…</p>`;
  try {
    const [seamRes, wsRes] = await Promise.all([
      fetch(`/runs/${RUN_ID}/seams`),
      fetch(`/runs/${RUN_ID}/artifacts/work_streams`),
    ]);
    if (!seamRes.ok) {
      const msg = seamRes.status === 404
        ? "IR not yet available — seams appear after the Observer phase completes."
        : `Failed to load seams (HTTP ${seamRes.status}).`;
      feed.innerHTML = `<p class="seam-error">${escapeHtml(msg)}</p>`;
      return;
    }
    const seamData = await seamRes.json();
    if (wsRes.ok) {
      try { window.WORK_STREAMS_DATA = await wsRes.json(); } catch (_) {}
    }
    renderSeamPanel(seamData);
    _seamDataLoaded = true;
  } catch (e) {
    console.warn("seam fetch failed", e);
    feed.innerHTML = `<p class="seam-error">Could not load seam analysis: ${escapeHtml(String(e))}</p>`;
  }
}

// ─── Target architecture & features (Seams tab, below source seams) ─────────
// Always re-fetches (no one-shot loaded guard like loadSeamPanel) — tnas.json
// and feature_specs.json land at different phases, so this is called again on
// each relevant phase_completed event to pick up whichever became available.
function _targetServiceCard(svc, decision) {
  const risk    = (svc.migration_risk || "").toLowerCase();
  const riskCls = risk ? `ws-risk-${risk}` : "";
  const tags    = [];
  if (decision?.communication_style) tags.push(escapeHtml(decision.communication_style.replace(/-/g, " ")));
  if (svc.pattern_recommendation) tags.push(escapeHtml(svc.pattern_recommendation));

  return `<details class="ws-card">
    <summary class="ws-card-summary">
      <div class="ws-card-main">
        <div class="ws-card-name">${escapeHtml(svc.service_id || svc.name || "service")}</div>
        <div class="ws-card-meta">
          ${svc.migration_risk ? `<span class="ws-risk ${riskCls}">${escapeHtml(svc.migration_risk)}</span>` : ""}
          ${tags.map(t => `<span class="ws-phase">${t}</span>`).join("")}
        </div>
      </div>
    </summary>
    <div class="ws-card-body">
      <p class="ws-rationale">${escapeHtml(svc.rationale || "")}</p>
    </div>
  </details>`;
}

function _targetFeatureRow(spec) {
  const pts = spec.story_points ?? "";
  const api = spec.api_surface ? `<span class="ws-phase">API</span>` : "";
  return `<div class="ws-seam-row">
    <div class="ws-seam-left">
      <span class="ws-seam-loc">${escapeHtml(spec.title || spec.seam_id || "")}</span>
      <span class="ws-seam-ev">${escapeHtml((spec.business_value || "").slice(0, 140))}</span>
    </div>
    ${api}
    <span class="ws-seam-pts">${pts}p</span>
  </div>`;
}

function renderTargetPanel(tnasData, featureSpecsData) {
  const feed = document.getElementById("target-feed");
  if (!feed) return;

  const services      = tnasData?.services || [];
  const decisionByCtx = Object.fromEntries((tnasData?.context_decisions || []).map(d => [d.context, d]));

  let servicesHtml;
  if (!tnasData) {
    servicesHtml = `<p class="hint">Target architecture appears after the Architect phase completes.</p>`;
  } else if (!services.length) {
    servicesHtml = `<p class="hint">No target services identified.</p>`;
  } else {
    servicesHtml = `<div class="ws-cards">${
      services.map(svc => _targetServiceCard(svc, decisionByCtx[svc.service_id || svc.name])).join("")
    }</div>`;
  }

  const specs = featureSpecsData?.specs || [];
  let featuresHtml;
  if (!featureSpecsData) {
    featuresHtml = `<p class="hint">Target features appear after the Feature Specifier phase completes.</p>`;
  } else if (!specs.length) {
    featuresHtml = `<p class="hint">No target features identified.</p>`;
  } else {
    featuresHtml = specs.map(spec => _targetFeatureRow(spec)).join("");
  }

  feed.innerHTML = `
    <div class="seam-target-subsection">
      <div class="seam-target-subheading">Target services</div>
      ${servicesHtml}
    </div>
    <div class="seam-target-subsection">
      <div class="seam-target-subheading">Target features</div>
      ${featuresHtml}
    </div>
  `;
}

async function loadTargetPanel() {
  const feed = document.getElementById("target-feed");
  if (!feed) return;
  try {
    const [tnasRes, fsRes] = await Promise.all([
      fetch(`/runs/${RUN_ID}/artifacts/tnas`),
      fetch(`/runs/${RUN_ID}/artifacts/feature_specs`),
    ]);
    const tnasData         = tnasRes.ok ? await tnasRes.json() : null;
    const featureSpecsData = fsRes.ok ? await fsRes.json() : null;
    renderTargetPanel(tnasData, featureSpecsData);
  } catch (e) {
    console.warn("target panel fetch failed", e);
    feed.innerHTML = `<p class="seam-error">Could not load target architecture: ${escapeHtml(String(e))}</p>`;
  }
}

// ─── Processing (seam status) panel ─────────────────────────────────────────
// Deliberately always re-fetches (no one-shot "already loaded" guard like
// loadSeamPanel) since it must reflect live status changes as the TDD loop
// progresses through the run, not just a snapshot at first tab activation.
async function loadProcessingPanel() {
  const wrap = document.getElementById("processing-table-wrap");
  if (!wrap) return;
  wrap.innerHTML = `<p class="seam-loading">Loading seam processing status…</p>`;
  try {
    const res = await fetch(`/runs/${RUN_ID}/seams`);
    if (!res.ok) {
      const msg = res.status === 404
        ? "Seams not yet available — status appears once seam translation begins."
        : `Failed to load seam status (HTTP ${res.status}).`;
      wrap.innerHTML = `<p class="seam-error">${escapeHtml(msg)}</p>`;
      return;
    }
    const seamData = await res.json();
    renderProcessingPanel(seamData);
  } catch (e) {
    console.warn("processing fetch failed", e);
    wrap.innerHTML = `<p class="seam-error">Could not load processing status: ${escapeHtml(String(e))}</p>`;
  }
}

function renderProcessingPanel(seamData) {
  const wrap = document.getElementById("processing-table-wrap");
  if (!wrap) return;
  const seams = (seamData && seamData.seams) || [];
  if (!seams.length) {
    wrap.innerHTML = `<p class="hint">No seams processed yet.</p>`;
    return;
  }

  const summary = seamData.processing_summary;
  if (!summary) {
    // seam.json exists (seams array is non-empty) but init_seam_processing()
    // hasn't run yet — the seam TDD loop hasn't started (still waiting on
    // Gate 4.5 approval). Distinct from "all seams pending after the loop
    // started" — that state always carries a processing_summary.
    wrap.innerHTML = `<p class="hint">Seam processing hasn't started yet — waiting for Gate 4.5 approval.</p>`;
    return;
  }

  const isDeterministic = document.querySelector(".run-mode-badge")?.classList.contains("mode-det");
  const detBanner = isDeterministic
    ? `<p class="processing-det-banner">⚠ Deterministic mode has no Code Writer/review LLM fallback — every seam predictably shows "failed" after exhausting its retries. This is expected, not a defect. Switch to LLM mode to see real pass/fail results.</p>`
    : "";

  const summaryHtml = `<p class="hint">${summary.success || 0} succeeded · ${summary.failed || 0} failed · ${summary.pending || 0} pending (of ${summary.total || seams.length})</p>`;

  const rows = seams.map((s) => {
    const p = s.processing || { status: "pending", attempts: 0, retry_attempts: 0, failure_reason: null };
    const statusClass = p.status === "success" ? "status-ok" : p.status === "failed" ? "status-fail" : "status-pending";
    const attemptsText = `${p.attempts || 0}${p.retry_attempts ? ` (+${p.retry_attempts} retry)` : ""}`;
    return `<tr>
      <td>${escapeHtml(s.id || s.location || "?")}</td>
      <td>${escapeHtml(s.type || "")}</td>
      <td class="${statusClass}">${escapeHtml(p.status)}</td>
      <td>${escapeHtml(attemptsText)}</td>
      <td>${p.failure_reason ? escapeHtml(p.failure_reason) : "—"}</td>
    </tr>`;
  }).join("");

  wrap.innerHTML = `${detBanner}${summaryHtml}
    <table class="demo-table">
      <thead><tr><th>Seam</th><th>Type</th><th>Status</th><th>Attempts</th><th>Failure reason</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

// ─── Tab switching ───────────────────────────────────────────────────────────
function switchTab(name) {
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === name);
  });
  document.querySelectorAll(".tab-panel").forEach((panel) => {
    panel.classList.toggle("active", panel.id === `tab-${name}`);
  });
  traceTabActive = name === "trace";
  if (name === "trace") {
    traceBadgeCount = 0;
    if (traceTabBadge) { traceTabBadge.textContent = ""; traceTabBadge.classList.remove("visible"); }
  }
  if (name === "diagnostics") {
    diagBadgeCount = 0;
    if (diagTabBadge) { diagTabBadge.textContent = ""; diagTabBadge.classList.remove("visible"); }
  }
  processingTabActive = name === "processing";
  if (name === "processing") {
    processingBadgeCount = 0;
    if (processingTabBadge) { processingTabBadge.textContent = ""; processingTabBadge.classList.remove("visible"); }
    loadProcessingPanel();
  }
  if (name === "seams") { loadSeamPanel(); loadTargetPanel(); }
}

function bumpDiagBadge() {
  diagBadgeCount++;
  if (diagTabBadge) {
    diagTabBadge.textContent = diagBadgeCount;
    diagTabBadge.classList.add("visible");
  }
}

document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => switchTab(btn.dataset.tab));
});

// ─── Phase strip ─────────────────────────────────────────────────────────────
function markPhase(phase, status) {
  const pill = phaseStrip.querySelector(`[data-phase='${phase}']`);
  if (!pill) return;
  pill.classList.remove("running", "done", "open", "rejected", "error", "skipped");
  pill.classList.add(status);
}

// ─── Artifact inspector ──────────────────────────────────────────────────────
const PHASE_ARTIFACT = {
  observer:          "ir_graph",
  cartographer:      "bounded_context_map",
  architect:         "tnas",
  security:          "security_report",
  pr_reviewer:       "review_report",
};

async function fetchAndShowArtifact(key, autoShow = false) {
  try {
    const res = await fetch(`/runs/${RUN_ID}/artifacts/${key}`);
    if (!res.ok) {
      if (!autoShow) artifactView.textContent = `Artifact ${key} not yet available.`;
      return;
    }
    const data = await res.json();
    const btn = document.querySelector(`.art-btn[data-key="${key}"]`);
    if (btn) btn.classList.add("ready");
    if (!autoShow) artifactView.innerHTML = `
      <div class="json-tree-controls">
        <button type="button" class="json-tree-btn" data-tree-action="expand">Expand all</button>
        <button type="button" class="json-tree-btn" data-tree-action="collapse">Collapse all</button>
      </div>
      <div class="json-tree">${jsonTreeHtml(data, 0)}</div>
    `;
  } catch (e) {
    if (!autoShow) artifactView.textContent = `Error: ${e}`;
  }
}

document.querySelectorAll(".art-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".art-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    fetchAndShowArtifact(btn.dataset.key, false);
  });
});

// Delegated (survives artifactView.innerHTML being replaced on every fetch) —
// expand/collapse every node at once; each node stays individually toggleable afterward.
artifactView.addEventListener("click", (e) => {
  const btn = e.target.closest("[data-tree-action]");
  if (!btn) return;
  const open = btn.dataset.treeAction === "expand";
  artifactView.querySelectorAll(".json-node").forEach((node) => { node.open = open; });
});

// ─── WebSocket ───────────────────────────────────────────────────────────────
const wsProto = location.protocol === "https:" ? "wss" : "ws";
const ws = new WebSocket(`${wsProto}://${location.host}/runs/${RUN_ID}/events`);

ws.onmessage = (msg) => {
  let event;
  try {
    event = JSON.parse(msg.data);
  } catch (e) {
    console.warn("malformed event", msg.data);
    appendDiagnostic("WARNING", "ws", { message: "Malformed event from server", source: "client" });
    return;
  }
  const { kind, phase, payload } = event;
  switch (kind) {
    case "phase_started":
      markPhase(phase, "running");
      setLiveStatus("running", `${payload.agent} · starting…`);
      appendTrace(phase, { author: payload.agent, parts: [{ type: "text", text: `▶ phase started` }] });
      bumpTraceBadge();
      setTddStopVisible(_TDD_LOOP_PHASES.has(phase));
      break;
    case "agent_event": {
      const parts = payload.parts || [];
      const fc = parts.find((p) => p.type === "function_call");
      const fr = parts.find((p) => p.type === "function_response");
      const txt = parts.find((p) => p.type === "text" && p.text);
      if (fc) setLiveStatus("running", `${payload.author || phase} · → ${fc.name}(…)`);
      else if (fr) setLiveStatus("running", `${payload.author || phase} · ← ${fr.name}`);
      else if (txt) setLiveStatus("running", `${payload.author || phase} · ${txt.text.slice(0, 100)}`);
      appendTrace(phase, payload);
      bumpTraceBadge();
      break;
    }
    case "phase_completed":
      // recovered_from_crash: the agent's own LLM turn crashed and this
      // phase proceeded on a deterministic fallback artifact instead — keep
      // the "error" pill and a visibly different status line rather than
      // overwriting it with a plain success checkmark, which would silently
      // erase the exact signal #60/#61/#62 exist to surface. The fallback
      // artifact is still real and worth inspecting, so the rest of this
      // handler (graph/seam-panel/artifact refresh) still runs unchanged.
      if (payload.recovered_from_crash) {
        markPhase(phase, "error");
        setLiveStatus("error", `⚠ ${payload.agent} crashed — recovered via deterministic fallback (degraded artifact, review before proceeding)`);
        appendTrace(phase, { author: payload.agent, parts: [{ type: "text", text: `⚠ phase recovered from a crash via deterministic fallback (output: ${payload.output_key})` }] });
      } else {
        markPhase(phase, "done");
        setLiveStatus("done", `✓ ${payload.agent} · ${payload.output_key} produced`);
        appendTrace(phase, { author: payload.agent, parts: [{ type: "text", text: `✓ phase completed (output: ${payload.output_key})` }] });
      }
      bumpTraceBadge();
      if (phase === "observer" || phase === "cartographer") {
        refreshGraph(currentLevel);
      }
      if (phase === "observer" || phase === "cartographer") {
        _seamDataLoaded = false;
        window.SEAM_DATA = undefined; _seamData = null;
        window.WORK_STREAMS_DATA = undefined;
        loadSeamPanel();
      }
      if (phase === "architect" || phase === "feature_specifier") {
        loadTargetPanel();
      }
      if (PHASE_ARTIFACT[phase]) {
        fetchAndShowArtifact(PHASE_ARTIFACT[phase], true);
      }
      break;
    case "gate_opened":
      markPhase(phase, "open");
      setLiveStatus("done", `Gate ${payload.gate_id} · awaiting review`);
      renderGatePanel(payload);
      switchTab("gates");
      setTddStopVisible(false);
      break;
    case "gate_resolved":
      markGateResolved(payload);
      markPhase(phase, payload.decision === "APPROVED" ? "done" : "rejected");
      if (payload.decision === "APPROVED") {
        setLiveStatus("done", `Gate ${payload.gate_id} approved · continuing…`);
      } else {
        setLiveStatus("error", `Gate ${payload.gate_id} rejected · re-running phase`);
      }
      break;
    case "seam_started":
      setLiveStatus("running", `Seam ${payload.seam} · code generation starting…`);
      appendTrace(phase, { author: "orchestrator", parts: [{ type: "text", text: `▶ seam ${escapeHtml(payload.seam)} — starting TDD loop (${payload.total_seams} total)` }] });
      bumpTraceBadge();
      setTddStopVisible(true);
      break;
    case "seam_completed": {
      const seamMark = payload.status === "failed" ? "✗" : "✓";
      const seamStatusText = payload.status ? `${payload.status} · ${payload.attempts || "?"} attempt(s)` : "code written";
      appendTrace(phase, { author: "orchestrator", parts: [{ type: "text", text: `${seamMark} seam ${escapeHtml(payload.seam)} — ${seamStatusText}` }] });
      bumpTraceBadge();
      bumpProcessingBadge();
      if (processingTabActive) loadProcessingPanel();
      break;
    }
    case "retry_pass_started":
      appendTrace(phase, { author: "orchestrator", parts: [{ type: "text", text: `↺ retry pass starting for ${payload.failed_seam_count} failed seam(s)` }] });
      bumpTraceBadge();
      bumpProcessingBadge();
      break;
    case "retry_pass_completed":
      appendTrace(phase, { author: "orchestrator", parts: [{ type: "text", text: `↺ retry ${escapeHtml(payload.seam)} — ${escapeHtml(payload.status)}` }] });
      bumpTraceBadge();
      bumpProcessingBadge();
      loadProcessingPanel();
      break;
    case "phase_skipped":
      markPhase(phase, "done");
      appendTrace(phase, { author: "orchestrator", parts: [{ type: "text", text: `⏭ phase skipped (${payload.reason || "restart"})` }] });
      bumpTraceBadge();
      break;
    case "pipeline_restarted":
      appendTrace(phase, { author: "orchestrator", parts: [{ type: "text", text: `↺ pipeline restarted from ${escapeHtml(payload.start_phase || phase)}` }] });
      bumpTraceBadge();
      break;
    case "pipeline_completed": {
      const pausedAfterPlanning = !!payload.paused_after_planning;
      (payload.skipped_phases || []).forEach((p) => markPhase(p, "skipped"));
      renderCompletionCard(payload.artifacts || [], pausedAfterPlanning);
      appendTrace("done", { author: "orchestrator", parts: [{ type: "text", text: pausedAfterPlanning
        ? "Stopped after planning — Gate 4.5 approved; code translation loop not started."
        : "Pipeline complete — all phases and gates finished." }] });
      setLiveStatus("done", pausedAfterPlanning ? "Stopped after planning." : "Pipeline complete.");
      bumpTraceBadge();
      switchTab("gates");
      setTddStopVisible(false);
      break;
    }
    case "error":
      appendTrace(phase, { author: "orchestrator", parts: [{ type: "text", text: `✕ ${payload.message || payload.text || "error"}` }] });
      appendDiagnostic("ERROR", phase, payload);
      markPhase(phase, "error");
      setLiveStatus("error", `✕ ${(payload.message || "error").slice(0, 120)}`);
      bumpDiagBadge();
      bumpTraceBadge();
      setTddStopVisible(false);
      break;
    case "warning":
      appendDiagnostic("WARNING", phase, payload);
      bumpDiagBadge();
      break;
    case "debug":
      appendDiagnostic("DEBUG", phase, payload);
      break;
    case "tdd_loop_stop_requested":
      if (tddStopForm) {
        const btn = tddStopForm.querySelector("button");
        if (btn) { btn.disabled = true; btn.textContent = "Stopping…"; }
      }
      appendDiagnostic("WARNING", phase, payload);
      bumpDiagBadge();
      break;
    case "tdd_loop_stopped":
      setTddStopVisible(false);
      setLiveStatus("done", payload.mid_seam
        ? `TDD loop stopped mid-seam (${escapeHtml(payload.seam || "?")}) · continuing to PR review…`
        : `TDD loop stopped · ${payload.remaining_seam_count || 0} seam(s) skipped · continuing to PR review…`);
      appendTrace(phase, { author: "orchestrator", parts: [{ type: "text", text: "⏹ TDD loop stopped by user request" }] });
      bumpTraceBadge();
      bumpProcessingBadge();
      if (processingTabActive) loadProcessingPanel();
      break;
  }
};

ws.onclose = () => {
  appendTrace("ws", { author: "client", parts: [{ type: "text", text: "WebSocket closed." }] });
  appendDiagnostic("WARNING", "ws", {
    message: "WebSocket disconnected. Refresh to reconnect.",
    source: "client",
  });
};

ws.onerror = (err) => {
  console.error("ws error", err);
  appendDiagnostic("ERROR", "ws", {
    message: "WebSocket error. Check the server is reachable.",
    source: "client",
  });
};

updateDiagCounts();

// Try loading seam data on page init — covers existing completed runs where
// the phase_completed event replay may have already fired before this handler
// was registered, or where the user navigates straight to the Seams tab.
setTimeout(loadSeamPanel, 400);

function escapeHtml(s) {
  if (s == null) return "";
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

// ─── Chat ("Ask this run") panel ─────────────────────────────────────────────

const chatForm    = document.getElementById("chat-form");
const chatInput   = document.getElementById("chat-input");
const chatHistoryEl = document.getElementById("chat-history");

// Multi-turn conversation history — persisted for the lifetime of this page
let convHistory = [];

function chatAppend(role, html) {
  const el = document.createElement("div");
  el.className = `chat-msg chat-msg-${role}`;
  el.innerHTML = html;
  chatHistoryEl.appendChild(el);
  chatHistoryEl.scrollTop = chatHistoryEl.scrollHeight;
  return el;
}

function chatCitation(c) {
  const kind  = escapeHtml(c.kind || "");
  const loc   = escapeHtml(c.source_location || "");
  const id    = escapeHtml(c.chunk_id || "");
  const label = id.replace(/^[^:]+:/, "");   // strip "node:" / "seam:" / "security:" prefix

  let link = "";
  if (c.kind === "node") {
    link = `<a class="chat-cite-link" href="#" data-node-id="${escapeHtml(id.replace(/^node:/, ""))}"
               title="Highlight in graph">${escapeHtml(label)}</a>`;
  } else if (loc.startsWith("report:")) {
    link = `<span class="chat-cite-link" title="${escapeHtml(loc)}">${escapeHtml(label)}</span>`;
  } else {
    link = `<span class="chat-cite-link">${escapeHtml(label)}</span>`;
  }
  return `<span class="chat-cite chat-cite-${kind}" title="${escapeHtml(c.excerpt || "")}">${link}</span>`;
}

function chatRenderSteps(steps) {
  if (!steps || steps.length === 0) return "";

  const parts = steps.map((s) => {
    if (s.type === "retrieval") {
      const kindBadges = (s.artifact_kinds || [])
        .map(k => `<span class="cot-kind-badge">${escapeHtml(k)}</span>`)
        .join(" ");
      const passes = (s.passes || []).map(p =>
        `<div class="cot-pass">
          <span class="cot-pass-query" title="${escapeHtml(p.query)}">${escapeHtml(p.query.length > 60 ? p.query.slice(0, 60) + "…" : p.query)}</span>
          <span class="cot-pass-stats">${p.returned} retrieved, ${p.new} new</span>
        </div>`
      ).join("");
      return `<div class="cot-step cot-step-retrieval">
        <span class="cot-step-icon">&#x1F50E;</span>
        <span class="cot-step-label">Retrieved ${s.total_chunks} chunks</span>
        <span class="cot-index-mode cot-mode-${escapeHtml(s.index_mode || "lexical")}">${escapeHtml(s.index_mode || "lexical")}</span>
        ${kindBadges}
        ${passes}
      </div>`;
    }
    if (s.type === "context") {
      return `<div class="cot-step cot-step-context">
        <span class="cot-step-icon">&#x1F4DC;</span>
        <span class="cot-step-label">${escapeHtml(s.description || "Building context…")}</span>
      </div>`;
    }
    return "";
  }).filter(Boolean).join("\n");

  return `<details class="cot-panel">
    <summary class="cot-summary">&#x1F9E0; Reasoning trace</summary>
    <div class="cot-steps">${parts}</div>
  </details>`;
}

function chatRenderAnswer(data) {
  const text     = escapeHtml(data.answer || "(no answer)");
  const modeBadge = data.mode !== "generative"
    ? ` <em class="chat-mode">[${escapeHtml(data.mode)}]</em>`
    : "";
  const cites    = (data.citations || []).map(chatCitation).join(" ");
  const citeBar  = cites ? `<div class="chat-citations">Sources: ${cites}</div>` : "";
  const cotPanel = chatRenderSteps(data.steps);
  return `${cotPanel}<div class="chat-answer">${text}${modeBadge}</div>${citeBar}`;
}

if (chatForm) {
  chatForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const q = chatInput.value.trim();
    if (!q) return;

    chatInput.value = "";
    chatAppend("user", escapeHtml(q));
    const loadingEl = chatAppend("assistant",
      "<span class='chat-loading'>&#x1F9E0; Thinking&hellip;</span>"
    );

    try {
      const resp = await fetch(`/runs/${RUN_ID}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: q,
          history: convHistory.slice(-(12)),   // last 6 turns (12 messages)
        }),
      });
      const data = await resp.json();

      if (resp.ok) {
        loadingEl.innerHTML = chatRenderAnswer(data);
        // Append to conversation history for next turn
        convHistory.push({ role: "user", content: q });
        convHistory.push({ role: "assistant", content: data.answer || "" });
        // Cap history to avoid unbounded growth
        if (convHistory.length > 24) convHistory = convHistory.slice(-24);
      } else {
        loadingEl.innerHTML = escapeHtml(data?.detail || data?.error?.message || resp.statusText);
      }
    } catch (err) {
      loadingEl.textContent = `Error: ${err.message}`;
    }
  });

  // Deep-link: click a node citation → highlight it in the Cytoscape graph
  chatHistoryEl.addEventListener("click", (e) => {
    const link = e.target.closest("[data-node-id]");
    if (!link || !cy) return;
    e.preventDefault();
    const nodeId = link.dataset.nodeId;
    const eles = cy.elements(`[id="${nodeId}"]`);
    if (eles.length) {
      cy.animate({ fit: { eles, padding: 60 }, duration: 400 });
      eles.select();
    }
    const graphPanel = document.querySelector(".graph-panel");
    if (graphPanel) graphPanel.scrollIntoView({ behavior: "smooth" });
  });
}

_initReportsMenu();
_initDownloadLinks();
