#!/usr/bin/env node
'use strict';

/**
 * generate_graph.js
 *
 * Reads ir_graph.json + bounded_context_map.json and writes a self-contained
 * interactive HTML visualisation of the module dependency graph.
 *
 * Usage:
 *   node scripts/generate_graph.js <run_dir>          (write to run_dir)
 *   node scripts/generate_graph.js <run_dir> <out>    (write to out path)
 */

const fs   = require('fs');
const path = require('path');

// ── Paths ─────────────────────────────────────────────────────────────────────

const args   = process.argv.slice(2);
const runDir = args[0] ? path.resolve(args[0]) : process.cwd();
const outArg = args[1] ? path.resolve(args[1]) : null;

function read(name) {
  const p = path.join(runDir, name);
  if (!fs.existsSync(p)) throw new Error(`Required file not found: ${p}`);
  return JSON.parse(fs.readFileSync(p, 'utf8'));
}

const meta = read('run_meta.json');
const ir   = read('ir_graph.json');
const bcm  = read('bounded_context_map.json');

// ── Extract & pre-process ─────────────────────────────────────────────────────

const projectName = path.basename(meta.source_path);
const sourceLang  = meta.source_lang;
const targetLang  = meta.target_lang;

const irNodes = ir.nodes  || [];
const irEdges = ir.edges  || [];
const ctxList = bcm.contexts || [];

// prog node id → context name
const progToCtx = {};
for (const ctx of ctxList) {
  for (const nid of (ctx.node_ids || [])) progToCtx[nid] = ctx.name;
}

// Build DEFINES indexes
const progToClasses  = {};  // prog → [class id]
const progToFns      = {};  // prog → [fn id]
const classToMethods = {};  // class → [method id]
const nodeById       = {};

for (const n of irNodes) nodeById[n.id] = n;

for (const e of irEdges) {
  const { source_id: src, target_id: tgt, type } = e;
  if (type !== 'DEFINES') continue;
  if (src.startsWith('prog.') && tgt.startsWith('class.'))
    (progToClasses[src] = progToClasses[src] || []).push(tgt);
  else if (src.startsWith('prog.') && tgt.startsWith('fn.'))
    (progToFns[src] = progToFns[src] || []).push(tgt);
  else if (src.startsWith('class.') && tgt.startsWith('method.'))
    (classToMethods[src] = classToMethods[src] || []).push(tgt);
}

// CALLS graph: prog → prog only
const callEdges = irEdges.filter(e =>
  e.type === 'CALLS' &&
  e.source_id.startsWith('prog.') &&
  e.target_id.startsWith('prog.')
);

// Prog nodes that appear in the calls graph + all prog nodes as fallback
const progNodes = irNodes.filter(n => n.type === 'PROGRAM');

// Assign a colour index to each context
const contextNames = [...new Set(ctxList.map(c => c.name))].sort();

// ── Build graph data ──────────────────────────────────────────────────────────

function shortPath(loc) {
  if (!loc) return '';
  const p = loc.replace(/:\d+$/, '');
  const parts = p.split('/');
  return parts.slice(-2).join('/');
}

function firstChildLoc(progId) {
  for (const cid of [...(progToClasses[progId] || []), ...(progToFns[progId] || [])]) {
    const n = nodeById[cid];
    if (n && n.source_location) return shortPath(n.source_location);
  }
  return progId.replace(/^prog\./, '').replace(/\./g, '/');
}

const graphNodes = progNodes.map(n => {
  const ctx     = progToCtx[n.id] || 'Unassigned';
  const classes = (progToClasses[n.id] || []);
  const fns     = (progToFns[n.id] || []);
  const defs    = classes.length + fns.length;
  const label   = firstChildLoc(n.id);
  return { id: n.id, label, ctx, defs };
});

const graphEdges = callEdges.map(e => ({ source: e.source_id, target: e.target_id }));

// ── Build node details (shown in right panel on click) ────────────────────────

const nodeDetails = {};
for (const n of progNodes) {
  const classes = (progToClasses[n.id] || []).map(cid => {
    const cls = nodeById[cid];
    if (!cls) return null;
    const methods = (classToMethods[cid] || [])
      .map(mid => nodeById[mid])
      .filter(m => m && !(m.name === 'super' && !m.inputs?.length && !m.output))
      .map(m => ({
        name: m.name,
        mods: m.attributes?.modifiers || '',
        inputs: (m.inputs || []).map(i => `${i.name}${i.optional === 'true' ? '?' : ''}: ${i.type}`).join(', ') || '—',
        output: m.output || '—',
        summary: m.summary || '',
      }));
    return {
      name: cls.name,
      kind: cls.attributes?.kind || 'class',
      fieldCount: (cls.inputs || []).length,
      summary: cls.summary || '',
      loc: shortPath(cls.source_location),
      methods,
    };
  }).filter(Boolean);

  const fns = (progToFns[n.id] || []).map(fid => {
    const fn = nodeById[fid];
    if (!fn) return null;
    return {
      name: fn.name,
      inputs: (fn.inputs || []).map(i => `${i.name}${i.optional === 'true' ? '?' : ''}: ${i.type}`).join(', ') || '—',
      output: fn.output || '—',
      summary: fn.summary || '',
    };
  }).filter(Boolean);

  const loc = (() => {
    for (const cid of [...(progToClasses[n.id] || []), ...(progToFns[n.id] || [])]) {
      const cn = nodeById[cid];
      if (cn && cn.source_location) return cn.source_location.replace(/:\d+$/, '');
    }
    return '';
  })();

  nodeDetails[n.id] = { ctx: progToCtx[n.id] || 'Unassigned', loc, classes, fns };
}

// ── Serialise payload ─────────────────────────────────────────────────────────

const payload = JSON.stringify({
  meta:     { project: projectName, sourceLang, targetLang },
  contexts: contextNames,
  nodes:    graphNodes,
  edges:    graphEdges,
  details:  nodeDetails,
});

// ── HTML ──────────────────────────────────────────────────────────────────────

const html = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>${projectName} — IR Graph</title>
<link href="https://fonts.googleapis.com/css2?family=Instrument+Serif&family=Inter+Tight:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js"></script>
<style>
:root {
  --color-dark:   #171D1D;
  --color-muted:  #91969C;
  --color-sage:   #E6EAE6;
  --color-accent: #ED3A12;
  --color-white:  #FFFFFF;
  --color-bg:     #F9FAF9;
  --sidebar-w:    240px;
  --detail-w:     340px;
  --nav-h:        52px;
}
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: 'Inter Tight', sans-serif;
  font-size: 13px;
  background: var(--color-bg);
  color: var(--color-dark);
  height: 100vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

/* ── Nav ── */
.nav {
  height: var(--nav-h);
  background: var(--color-white);
  border-bottom: 1px solid var(--color-sage);
  display: flex;
  align-items: center;
  padding: 0 20px;
  gap: 16px;
  flex-shrink: 0;
  z-index: 10;
}
.nav-brand {
  font-family: 'Instrument Serif', serif;
  font-size: 18px;
  color: var(--color-dark);
  text-decoration: none;
  flex-shrink: 0;
}
.nav-title {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 12px;
  color: var(--color-muted);
  text-transform: uppercase;
  letter-spacing: 0.07em;
}
.nav-sep { color: var(--color-sage); }
.nav-right {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 12px;
}
.nav-stat {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 11px;
  color: var(--color-muted);
  background: var(--color-sage);
  padding: 3px 8px;
  border-radius: 2px;
}

/* ── Layout ── */
.layout {
  display: flex;
  flex: 1;
  overflow: hidden;
}

/* ── Sidebar ── */
.sidebar {
  width: var(--sidebar-w);
  background: var(--color-white);
  border-right: 1px solid var(--color-sage);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  overflow: hidden;
}
.sidebar-section {
  padding: 12px 14px;
  border-bottom: 1px solid var(--color-sage);
}
.sidebar-label {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--color-muted);
  margin-bottom: 8px;
}
.search-box {
  width: 100%;
  padding: 6px 9px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 12px;
  border: 1px solid #D0D4D0;
  background: var(--color-bg);
  color: var(--color-dark);
  outline: none;
}
.search-box:focus { border-color: var(--color-dark); }
.ctx-list {
  flex: 1;
  overflow-y: auto;
  padding: 10px 14px;
}
.ctx-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 0;
  cursor: pointer;
  user-select: none;
}
.ctx-swatch {
  width: 10px;
  height: 10px;
  border-radius: 2px;
  flex-shrink: 0;
}
.ctx-name {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 11px;
  color: var(--color-dark);
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.ctx-count {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 10px;
  color: var(--color-muted);
}
.ctx-item.dimmed .ctx-name,
.ctx-item.dimmed .ctx-count { opacity: 0.4; }

.toggle-row {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.toggle-btn {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  padding: 4px 8px;
  border: 1px solid #D0D4D0;
  background: var(--color-bg);
  color: var(--color-muted);
  cursor: pointer;
}
.toggle-btn:hover { border-color: var(--color-dark); color: var(--color-dark); }

/* ── Canvas ── */
.canvas-wrap {
  flex: 1;
  position: relative;
  overflow: hidden;
  background: var(--color-bg);
}
#graph-svg {
  width: 100%;
  height: 100%;
  display: block;
}
.node circle {
  stroke: var(--color-white);
  stroke-width: 1.5;
  cursor: pointer;
  transition: opacity 0.15s;
}
.node.dimmed circle { opacity: 0.12; }
.node.highlighted circle { stroke: var(--color-dark); stroke-width: 2.5; }
.node text {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 9px;
  fill: var(--color-dark);
  pointer-events: none;
  opacity: 0;
}
.node.labeled text { opacity: 1; }
.link {
  stroke: #C5CBC5;
  stroke-width: 1;
  stroke-opacity: 0.5;
  fill: none;
  marker-end: url(#arrow);
  transition: opacity 0.15s;
}
.link.dimmed { opacity: 0.05; }
.link.highlighted { stroke: var(--color-dark); stroke-opacity: 1; stroke-width: 1.5; }

/* ── Detail panel ── */
.detail-panel {
  width: var(--detail-w);
  background: var(--color-white);
  border-left: 1px solid var(--color-sage);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  overflow: hidden;
  transition: width 0.2s;
}
.detail-panel.hidden { width: 0; border: none; }
.detail-header {
  padding: 14px 16px 10px;
  border-bottom: 1px solid var(--color-sage);
  flex-shrink: 0;
}
.detail-file {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 12px;
  font-weight: 500;
  color: var(--color-dark);
  word-break: break-all;
  margin-bottom: 4px;
}
.detail-ctx {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  color: var(--color-muted);
}
.detail-close {
  float: right;
  background: none;
  border: none;
  cursor: pointer;
  color: var(--color-muted);
  font-size: 16px;
  line-height: 1;
  margin-top: -2px;
}
.detail-close:hover { color: var(--color-dark); }
.detail-body {
  flex: 1;
  overflow-y: auto;
  padding: 0 16px 16px;
}
.detail-section-title {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--color-muted);
  margin: 16px 0 6px;
}
.class-block {
  border: 1px solid var(--color-sage);
  margin-bottom: 8px;
}
.class-header {
  background: var(--color-sage);
  padding: 5px 9px;
  display: flex;
  align-items: center;
  gap: 6px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 11px;
  font-weight: 500;
}
.kind-badge {
  font-size: 9px;
  padding: 1px 4px;
  border-radius: 2px;
  text-transform: lowercase;
}
.kind-class     { background:#E8EAF6; color:#3949AB; }
.kind-interface { background:#E0F2F1; color:#00695C; }
.kind-enum      { background:#FFF3E0; color:#E65100; }
.class-summary {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 10px;
  color: var(--color-muted);
  padding: 4px 9px;
  border-bottom: 1px solid var(--color-sage);
  font-style: italic;
}
.method-row {
  display: flex;
  align-items: baseline;
  gap: 6px;
  padding: 3px 9px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 10px;
  border-bottom: 1px solid var(--color-sage);
}
.method-row:last-child { border-bottom: none; }
.method-name { color: var(--color-dark); font-weight: 500; }
.method-sig  { color: var(--color-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; }
.mod-badge   { font-size: 9px; padding: 0px 4px; border-radius: 2px; flex-shrink: 0; }
.mod-async   { background:#F3E5F5; color:#6A1B9A; }
.mod-private { background:#F5F5F5; color:#757575; }
.fn-row {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 10px;
  padding: 3px 0;
  border-bottom: 1px solid var(--color-sage);
  color: var(--color-dark);
}
.fn-row:last-child { border-bottom: none; }
.fn-name   { font-weight: 500; }
.fn-sig    { color: var(--color-muted); }
.fn-summary { color: var(--color-muted); font-style: italic; font-size: 9px; }
.detail-deps {
  margin-top: 4px;
}
.dep-row {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 10px;
  color: var(--color-muted);
  margin-bottom: 4px;
  line-height: 1.6;
}
.dep-row strong { color: var(--color-dark); }
.dep-chip {
  display: inline-block;
  background: var(--color-sage);
  border: 1px solid #C5CBC5;
  border-radius: 2px;
  padding: 0 5px;
  margin: 1px 2px;
  cursor: pointer;
  color: var(--color-dark);
}
.dep-chip:hover { border-color: var(--color-dark); }

/* ── Tooltip ── */
.tooltip {
  position: fixed;
  background: var(--color-dark);
  color: var(--color-white);
  font-family: 'IBM Plex Mono', monospace;
  font-size: 11px;
  padding: 5px 9px;
  border-radius: 2px;
  pointer-events: none;
  opacity: 0;
  transition: opacity 0.1s;
  z-index: 100;
  max-width: 300px;
  word-break: break-all;
}
</style>
</head>
<body>
<nav class="nav">
  <a class="nav-brand" href="#">Micro-Cosmos</a>
  <span class="nav-sep">·</span>
  <span class="nav-title">IR Graph — <strong id="nav-project"></strong></span>
  <div class="nav-right">
    <span class="nav-stat" id="stat-nodes"></span>
    <span class="nav-stat" id="stat-edges"></span>
    <span class="nav-stat" id="stat-contexts"></span>
  </div>
</nav>
<div class="layout">
  <aside class="sidebar">
    <div class="sidebar-section">
      <div class="sidebar-label">Search modules</div>
      <input class="search-box" id="search" type="search" placeholder="filename or class…">
    </div>
    <div class="sidebar-section">
      <div class="sidebar-label">Controls</div>
      <div class="toggle-row">
        <button class="toggle-btn" id="btn-isolates">Hide isolates</button>
        <button class="toggle-btn" id="btn-labels">Show labels</button>
        <button class="toggle-btn" id="btn-reset">Reset view</button>
      </div>
    </div>
    <div class="sidebar-label" style="padding:10px 14px 4px">Contexts</div>
    <div class="ctx-list" id="ctx-list"></div>
  </aside>

  <div class="canvas-wrap">
    <svg id="graph-svg">
      <defs>
        <marker id="arrow" viewBox="0 -4 8 8" refX="16" refY="0"
                markerWidth="6" markerHeight="6" orient="auto">
          <path d="M0,-4L8,0L0,4" fill="#C5CBC5"/>
        </marker>
        <marker id="arrow-hi" viewBox="0 -4 8 8" refX="16" refY="0"
                markerWidth="6" markerHeight="6" orient="auto">
          <path d="M0,-4L8,0L0,4" fill="#171D1D"/>
        </marker>
      </defs>
    </svg>
  </div>

  <aside class="detail-panel hidden" id="detail-panel">
    <div class="detail-header">
      <button class="detail-close" id="detail-close">✕</button>
      <div class="detail-file" id="detail-file"></div>
      <div class="detail-ctx" id="detail-ctx"></div>
    </div>
    <div class="detail-body" id="detail-body"></div>
  </aside>
</div>
<div class="tooltip" id="tooltip"></div>

<script>
const RAW = ${payload};

// ── Palette (13 contexts max, repeats if more) ────────────────────────────────
const PALETTE = [
  '#3B82F6','#10B981','#F59E0B','#EF4444','#8B5CF6',
  '#EC4899','#06B6D4','#84CC16','#F97316','#6366F1',
  '#14B8A6','#E11D48','#A16207',
];
const ctxColor = Object.fromEntries(
  RAW.contexts.map((c, i) => [c, PALETTE[i % PALETTE.length]])
);
ctxColor['Unassigned'] = '#9CA3AF';

// ── State ─────────────────────────────────────────────────────────────────────
let hiddenContexts = new Set();
let showIsolates   = true;
let showLabels     = false;
let searchQuery    = '';
let selectedNodeId = null;

// Build adjacency for "isolate" detection
const connected = new Set();
for (const e of RAW.edges) { connected.add(e.source); connected.add(e.target); }

// Callers / callees maps
const callsOut = {};
const callsIn  = {};
for (const e of RAW.edges) {
  (callsOut[e.source] = callsOut[e.source] || []).push(e.target);
  (callsIn[e.target]  = callsIn[e.target]  || []).push(e.source);
}

// ── Nav stats ─────────────────────────────────────────────────────────────────
document.getElementById('nav-project').textContent = RAW.meta.project;
document.getElementById('stat-nodes').textContent    = RAW.nodes.length + ' modules';
document.getElementById('stat-edges').textContent    = RAW.edges.length + ' imports';
document.getElementById('stat-contexts').textContent = RAW.contexts.length + ' contexts';

// ── Context sidebar ───────────────────────────────────────────────────────────
const ctxNodeCount = {};
for (const n of RAW.nodes) ctxNodeCount[n.ctx] = (ctxNodeCount[n.ctx] || 0) + 1;

const ctxList = document.getElementById('ctx-list');
for (const ctx of [...RAW.contexts, 'Unassigned'].filter(c => ctxNodeCount[c])) {
  const item = document.createElement('div');
  item.className = 'ctx-item';
  item.dataset.ctx = ctx;
  item.innerHTML = \`
    <div class="ctx-swatch" style="background:\${ctxColor[ctx]}"></div>
    <span class="ctx-name">\${ctx}</span>
    <span class="ctx-count">\${ctxNodeCount[ctx] || 0}</span>
  \`;
  item.addEventListener('click', () => toggleContext(ctx, item));
  ctxList.appendChild(item);
}

function toggleContext(ctx, el) {
  if (hiddenContexts.has(ctx)) {
    hiddenContexts.delete(ctx);
    el.classList.remove('dimmed');
  } else {
    hiddenContexts.add(ctx);
    el.classList.add('dimmed');
  }
  applyFilters();
}

// ── D3 setup ──────────────────────────────────────────────────────────────────
const svg = d3.select('#graph-svg');
const g   = svg.append('g');

const width  = () => svg.node().clientWidth  || 800;
const height = () => svg.node().clientHeight || 600;

// Zoom
const zoom = d3.zoom()
  .scaleExtent([0.05, 8])
  .on('zoom', e => {
    g.attr('transform', e.transform);
    // Show labels when zoomed in enough
    const k = e.transform.k;
    svg.selectAll('.node text').style('opacity', (showLabels || k > 2) ? 1 : 0);
  });
svg.call(zoom);

// Prepare nodes + edges for simulation
const simNodes = RAW.nodes.map(n => ({ ...n }));
const nodeMap  = Object.fromEntries(simNodes.map(n => [n.id, n]));

const simEdges = RAW.edges
  .filter(e => nodeMap[e.source] && nodeMap[e.target])
  .map(e => ({ source: e.source, target: e.target }));

// Radius scale: 4–14 based on defs count
const rScale = d3.scaleSqrt()
  .domain([0, d3.max(simNodes, n => n.defs) || 1])
  .range([4, 14]);

// Force simulation
const simulation = d3.forceSimulation(simNodes)
  .force('link',    d3.forceLink(simEdges).id(d => d.id).distance(60).strength(0.3))
  .force('charge',  d3.forceManyBody().strength(-120).distanceMax(400))
  .force('center',  d3.forceCenter(0, 0))
  .force('collide', d3.forceCollide(d => rScale(d.defs) + 3))
  .alphaDecay(0.02);

// Draw edges
const linkSel = g.append('g').attr('class', 'links')
  .selectAll('.link')
  .data(simEdges)
  .join('path')
  .attr('class', 'link');

// Draw nodes
const nodeSel = g.append('g').attr('class', 'nodes')
  .selectAll('.node')
  .data(simNodes)
  .join('g')
  .attr('class', 'node')
  .call(d3.drag()
    .on('start', (e, d) => { if (!e.active) simulation.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
    .on('drag',  (e, d) => { d.fx = e.x; d.fy = e.y; })
    .on('end',   (e, d) => { if (!e.active) simulation.alphaTarget(0); d.fx = null; d.fy = null; })
  );

nodeSel.append('circle')
  .attr('r', d => rScale(d.defs))
  .attr('fill', d => ctxColor[d.ctx] || '#9CA3AF');

nodeSel.append('text')
  .attr('dy', d => rScale(d.defs) + 10)
  .attr('text-anchor', 'middle')
  .text(d => d.label.split('/').pop());

// Hover tooltip
const tooltip = document.getElementById('tooltip');
nodeSel
  .on('mouseover', (e, d) => {
    tooltip.textContent = d.label + ' · ' + d.ctx;
    tooltip.style.opacity = 1;
  })
  .on('mousemove', e => {
    tooltip.style.left = (e.clientX + 12) + 'px';
    tooltip.style.top  = (e.clientY - 8)  + 'px';
  })
  .on('mouseleave', () => { tooltip.style.opacity = 0; })
  .on('click', (e, d) => {
    e.stopPropagation();
    selectNode(d.id);
  });

svg.on('click', () => {
  selectedNodeId = null;
  clearHighlight();
  closeDetail();
});

// Tick
function arcPath(d) {
  const dx = d.target.x - d.source.x;
  const dy = d.target.y - d.source.y;
  const dr = Math.sqrt(dx * dx + dy * dy) * 1.4;
  return \`M\${d.source.x},\${d.source.y}A\${dr},\${dr} 0 0,1 \${d.target.x},\${d.target.y}\`;
}

simulation.on('tick', () => {
  linkSel.attr('d', arcPath);
  nodeSel.attr('transform', d => \`translate(\${d.x},\${d.y})\`);
});

// Initial zoom-to-fit after simulation settles
simulation.on('end', () => fitView());

function fitView() {
  const bounds = g.node().getBBox();
  if (!bounds.width || !bounds.height) return;
  const w = width(), h = height();
  const scale = Math.min(0.9, 0.9 * Math.min(w / bounds.width, h / bounds.height));
  const tx = w / 2 - scale * (bounds.x + bounds.width  / 2);
  const ty = h / 2 - scale * (bounds.y + bounds.height / 2);
  svg.transition().duration(600).call(
    zoom.transform, d3.zoomIdentity.translate(tx, ty).scale(scale)
  );
}

// ── Filter / highlight logic ──────────────────────────────────────────────────

function isVisible(d) {
  if (hiddenContexts.has(d.ctx)) return false;
  if (!showIsolates && !connected.has(d.id)) return false;
  if (searchQuery) {
    const q = searchQuery.toLowerCase();
    return d.label.toLowerCase().includes(q) || d.id.toLowerCase().includes(q) ||
           (RAW.details[d.id]?.classes || []).some(c => c.name.toLowerCase().includes(q));
  }
  return true;
}

function applyFilters() {
  const visSet = new Set(simNodes.filter(isVisible).map(n => n.id));

  nodeSel.classed('dimmed', d => !visSet.has(d.id));
  linkSel.classed('dimmed', d => !visSet.has(d.source.id) || !visSet.has(d.target.id));

  // Re-apply selection highlight on top
  if (selectedNodeId) applyHighlight(selectedNodeId);

  if (showLabels) nodeSel.classed('labeled', d => visSet.has(d.id));
}

function applyHighlight(nodeId) {
  const neighbors = new Set([nodeId,
    ...(callsOut[nodeId] || []),
    ...(callsIn[nodeId]  || []),
  ]);
  nodeSel
    .classed('highlighted', d => d.id === nodeId)
    .classed('dimmed',      d => !neighbors.has(d.id));
  linkSel
    .classed('highlighted', d => d.source.id === nodeId || d.target.id === nodeId)
    .classed('dimmed',      d => d.source.id !== nodeId && d.target.id !== nodeId)
    .attr('marker-end',     d =>
      (d.source.id === nodeId || d.target.id === nodeId) ? 'url(#arrow-hi)' : 'url(#arrow)'
    );
}

function clearHighlight() {
  nodeSel.classed('highlighted dimmed', false);
  linkSel.classed('highlighted dimmed', false).attr('marker-end', 'url(#arrow)');
  applyFilters();
}

// ── Node selection + detail panel ─────────────────────────────────────────────

function selectNode(nodeId) {
  selectedNodeId = nodeId;
  applyHighlight(nodeId);
  renderDetail(nodeId);
}

function renderDetail(nodeId) {
  const d   = RAW.details[nodeId];
  const n   = nodeMap[nodeId];
  if (!d || !n) return;

  document.getElementById('detail-file').textContent = d.loc || n.label;
  document.getElementById('detail-ctx').textContent  = d.ctx;

  const panel = document.getElementById('detail-panel');
  panel.classList.remove('hidden');

  const body = document.getElementById('detail-body');
  let html = '';

  // ── Calls / Called by ──
  const out = (callsOut[nodeId] || []).map(t => nodeMap[t]).filter(Boolean);
  const inp = (callsIn[nodeId]  || []).map(t => nodeMap[t]).filter(Boolean);

  html += '<div class="detail-section-title">Calls (imports)</div>';
  html += '<div class="detail-deps">';
  if (out.length) {
    html += '<div class="dep-row">' +
      out.map(t => \`<span class="dep-chip" data-nid="\${t.id}" title="\${t.label}">\${t.label.split('/').pop()}</span>\`).join('') +
      '</div>';
  } else {
    html += '<div class="dep-row" style="font-style:italic">none</div>';
  }
  html += '</div>';

  html += '<div class="detail-section-title">Called by (imported by)</div>';
  html += '<div class="detail-deps">';
  if (inp.length) {
    html += '<div class="dep-row">' +
      inp.map(t => \`<span class="dep-chip" data-nid="\${t.id}" title="\${t.label}">\${t.label.split('/').pop()}</span>\`).join('') +
      '</div>';
  } else {
    html += '<div class="dep-row" style="font-style:italic">none</div>';
  }
  html += '</div>';

  // ── Classes ──
  if (d.classes.length) {
    html += \`<div class="detail-section-title">Classes (\${d.classes.length})</div>\`;
    for (const cls of d.classes) {
      const klass = cls.kind === 'class' ? 'kind-class' : cls.kind === 'interface' ? 'kind-interface' : 'kind-enum';
      html += \`<div class="class-block">
        <div class="class-header">
          <span class="kind-badge \${klass}">\${cls.kind}</span>
          \${esc(cls.name)}
          <span style="margin-left:auto;font-size:9px;color:var(--color-muted)">\${cls.fieldCount}f · \${cls.methods.length}m</span>
        </div>\`;
      if (cls.summary) html += \`<div class="class-summary">\${esc(cls.summary)}</div>\`;
      for (const m of cls.methods) {
        const mods = m.mods.split(',').map(x => x.trim()).filter(Boolean)
          .map(x => \`<span class="mod-badge mod-\${x}">\${x}</span>\`).join('');
        html += \`<div class="method-row">
          \${mods}
          <span class="method-name">\${esc(m.name)}</span>
          <span class="method-sig">(\${esc(m.inputs)}) → \${esc(m.output)}</span>
        </div>\`;
      }
      html += '</div>';
    }
  }

  // ── Functions ──
  if (d.fns.length) {
    html += \`<div class="detail-section-title">Functions (\${d.fns.length})</div>\`;
    for (const fn of d.fns) {
      html += \`<div class="fn-row">
        <span class="fn-name">\${esc(fn.name)}</span>
        <span class="fn-sig"> (\${esc(fn.inputs)}) → \${esc(fn.output)}</span>
        \${fn.summary ? \`<div class="fn-summary">\${esc(fn.summary)}</div>\` : ''}
      </div>\`;
    }
  }

  body.innerHTML = html;

  // Chip click → navigate to that node
  body.querySelectorAll('.dep-chip[data-nid]').forEach(chip => {
    chip.addEventListener('click', () => selectNode(chip.dataset.nid));
  });
}

function closeDetail() {
  document.getElementById('detail-panel').classList.add('hidden');
}
document.getElementById('detail-close').addEventListener('click', () => {
  selectedNodeId = null;
  clearHighlight();
  closeDetail();
});

// ── Controls ──────────────────────────────────────────────────────────────────

document.getElementById('btn-isolates').addEventListener('click', function() {
  showIsolates = !showIsolates;
  this.textContent = showIsolates ? 'Hide isolates' : 'Show isolates';
  applyFilters();
});

document.getElementById('btn-labels').addEventListener('click', function() {
  showLabels = !showLabels;
  this.textContent = showLabels ? 'Hide labels' : 'Show labels';
  nodeSel.classed('labeled', d => showLabels && isVisible(d));
});

document.getElementById('btn-reset').addEventListener('click', () => {
  hiddenContexts.clear();
  document.querySelectorAll('.ctx-item').forEach(el => el.classList.remove('dimmed'));
  searchQuery = '';
  document.getElementById('search').value = '';
  showIsolates = true;
  document.getElementById('btn-isolates').textContent = 'Hide isolates';
  selectedNodeId = null;
  clearHighlight();
  closeDetail();
  fitView();
});

document.getElementById('search').addEventListener('input', function() {
  searchQuery = this.value.trim();
  applyFilters();
});

// ── HTML escape ───────────────────────────────────────────────────────────────
function esc(s) {
  if (s === null || s === undefined) return '';
  return String(s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// Initial filter pass
applyFilters();

// Resize handler
new ResizeObserver(fitView).observe(document.querySelector('.canvas-wrap'));
</script>
</body>
</html>`;

// ── Write output ──────────────────────────────────────────────────────────────

const outPath = outArg || path.join(runDir, 'ir-graph.html');
fs.writeFileSync(outPath, html, 'utf8');

const outputsDir = '/mnt/user-data/outputs';
if (fs.existsSync(outputsDir)) {
  fs.writeFileSync(path.join(outputsDir, 'ir-graph.html'), html, 'utf8');
  console.log(`Copied to ${outputsDir}/ir-graph.html`);
}

const written = fs.readFileSync(outPath, 'utf8');
console.log(`File written: ${outPath}`);
console.log(`File size:    ${written.length} bytes`);
console.log(`Nodes: ${graphNodes.length}  Edges: ${graphEdges.length}  Contexts: ${contextNames.length}`);
