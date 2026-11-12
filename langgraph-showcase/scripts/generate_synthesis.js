#!/usr/bin/env node
'use strict';

/**
 * generate_synthesis.js
 *
 * Reads six pipeline output files and writes a single self-contained HTML
 * project synthesis document. No LLM calls.
 *
 * Usage:
 *   node scripts/generate_synthesis.js <run_dir>          (write to run_dir)
 *   node scripts/generate_synthesis.js <run_dir> <out>    (write to <out>)
 */

const fs   = require('fs');
const path = require('path');

// ── Resolve paths ─────────────────────────────────────────────────────────────

const args   = process.argv.slice(2);
const runDir = args[0] ? path.resolve(args[0]) : process.cwd();
const outArg = args[1] ? path.resolve(args[1]) : null;

function read(name) {
  const p = path.join(runDir, name);
  if (!fs.existsSync(p)) throw new Error(`Required file not found: ${p}`);
  return JSON.parse(fs.readFileSync(p, 'utf8'));
}

const meta     = read('run_meta.json');
const ir       = read('ir_graph.json');
const bcm      = read('bounded_context_map.json');
const tnas     = read('tnas.json');
const wsData   = read('work_streams.json');
const seamData = read('seam.json');

// ── Helper ────────────────────────────────────────────────────────────────────

function countBy(arr, fn) {
  return arr.reduce((acc, x) => {
    const k = fn(x); acc[k] = (acc[k] || 0) + 1; return acc;
  }, {});
}

// ── Data extraction ───────────────────────────────────────────────────────────

const projectName = path.basename(meta.source_path);
const sourceLang  = meta.source_lang;
const targetLang  = meta.target_lang;
const streams     = wsData.work_streams || wsData.streams || [];
const seams       = seamData.seams || [];
const nodes       = ir.nodes || [];
const edges       = ir.edges || [];
const contexts    = bcm.contexts || [];

// Normalise tnas: support both old (name) and new (service_id) format
const services          = (tnas.services || []).map(s => ({ ...s, service_id: s.service_id || s.name }));
const fitnessObj        = tnas.fitness_suite || {};
// Support both old array format (functions[]) and new object format ({ dimName: "text" })
const fitnessFns        = Array.isArray(fitnessObj.functions) ? fitnessObj.functions : [];
const _FITNESS_META = new Set(['sha','created_at','produced_by','functions','target_language','intended_commit_path']);
const fitnessDims       = (typeof fitnessObj === 'object' && !Array.isArray(fitnessObj))
  ? Object.entries(fitnessObj).filter(([k, v]) => typeof v === 'string' && !_FITNESS_META.has(k))
  : [];
const archNotes         = tnas.architectural_notes || [];
const migrationRationale = tnas.migration_sequence_rationale || '';

// ── Node/edge counts ──────────────────────────────────────────────────────────

const nodeTypes = countBy(nodes, n => n.type);
const edgeTypes = countBy(edges, e => e.type);

// ── Fan-in hotspots (top 10 by incoming CALLS) ────────────────────────────────

const nodeMap = Object.fromEntries(nodes.map(n => [n.id, n]));
const fanIn   = {};
edges.filter(e => e.type === 'CALLS').forEach(e => {
  fanIn[e.target_id] = (fanIn[e.target_id] || 0) + 1;
});
const hotspots = Object.entries(fanIn)
  .sort((a, b) => b[1] - a[1])
  .slice(0, 10)
  .map(([id, count]) => ({ id, count, node: nodeMap[id] || {} }));

// ── God class candidates (top 10 by DEFINES children) ────────────────────────

const defineCount = {};
edges.filter(e => e.type === 'DEFINES').forEach(e => {
  defineCount[e.source_id] = (defineCount[e.source_id] || 0) + 1;
});
const godCandidates = Object.entries(defineCount)
  .sort((a, b) => b[1] - a[1])
  .slice(0, 10)
  .map(([id, count]) => ({ id, count, node: nodeMap[id] || {} }));

// ── Circular dependency detection ─────────────────────────────────────────────

const callsGraph = {};
edges.filter(e => e.type === 'CALLS').forEach(e => {
  if (!callsGraph[e.source_id]) callsGraph[e.source_id] = new Set();
  callsGraph[e.source_id].add(e.target_id);
});
const mutualPairs = [];
const seenKeys    = new Set();
Object.entries(callsGraph).forEach(([src, targets]) => {
  targets.forEach(tgt => {
    if (src !== tgt && callsGraph[tgt] && callsGraph[tgt].has(src)) {
      const key = [src, tgt].sort().join('||');
      if (!seenKeys.has(key)) {
        seenKeys.add(key);
        mutualPairs.push({ key, a: src, b: tgt });
      }
    }
  });
});

// ── Test coverage proxy ────────────────────────────────────────────────────────

const progNodes = nodes.filter(n => n.id && n.id.startsWith('prog.'));
const testNodes = progNodes.filter(n => n.id.includes('.spec') || n.id.includes('.test'));
const implNodes = progNodes.filter(n => !n.id.includes('.spec') && !n.id.includes('.test'));
const testRatio = progNodes.length > 0 ? Math.round(testNodes.length / progNodes.length * 100) : 0;

// ── Seam stats ────────────────────────────────────────────────────────────────

const seamTypes  = countBy(seams, s => s.type);
const effortDist = countBy(seams, s => s.work && s.work.effort);
const phaseDist  = countBy(seams, s => s.work && s.work.migration_phase);
const totalPts   = seams.reduce((sum, s) => sum + ((s.work && s.work.story_points) || 0), 0);

// Per-effort actual story points (derived from data, not hardcoded)
const effortPts = seams.reduce((acc, s) => {
  const e = s.work && s.work.effort;
  if (e) acc[e] = (acc[e] || 0) + ((s.work && s.work.story_points) || 0);
  return acc;
}, {});

// ── Risk distribution ─────────────────────────────────────────────────────────

const riskCounts = { HIGH: 0, MEDIUM: 0, LOW: 0 };
services.forEach(s => {
  const r = (s.migration_risk || '').toUpperCase();
  if (r in riskCounts) riskCounts[r]++;
});

// ── Lookups ───────────────────────────────────────────────────────────────────

const serviceByCtx  = Object.fromEntries(services.map(s => [s.service_id, s]));
const decisionByCtx = Object.fromEntries((tnas.context_decisions || []).map(d => [d.context, d]));
const streamById    = Object.fromEntries(streams.map(s => [s.id, s]));

// ── Path stripping ────────────────────────────────────────────────────────────
// Strip everything up to and including the project directory name in source_location.

function stripPrefix(loc) {
  if (!loc) return '';
  // Remove line number suffix (:N)
  const withoutLine = loc.replace(/:\d+$/, '');
  // Find the project root segment
  const marker = `/${projectName}/`;
  const idx = withoutLine.indexOf(marker);
  if (idx !== -1) return withoutLine.slice(idx + marker.length);
  // Fallback: just the basename
  return path.basename(withoutLine);
}

// ── HTML helpers ──────────────────────────────────────────────────────────────

function esc(s) {
  if (s === null || s === undefined) return '';
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function riskBadge(risk) {
  const r = (risk || '').toUpperCase();
  const styles = {
    HIGH:   'background:#FDECEA;color:#C0392B;border:1px solid #F5C6C2',
    MEDIUM: 'background:#FEF3E2;color:#A0522D;border:1px solid #F5DFB8',
    LOW:    'background:#EAF4EA;color:#2E7D32;border:1px solid #B8DDB8',
  };
  const style = styles[r] || styles.LOW;
  return `<span style="display:inline-block;padding:2px 7px;border-radius:2px;font-family:'IBM Plex Mono',monospace;font-size:11px;text-transform:uppercase;letter-spacing:0.04em;${style}">${esc(r || 'LOW')}</span>`;
}

function pct(n, total) {
  if (!total) return '0';
  return Math.round(n / total * 100).toString();
}

function cap(text, maxSentences) {
  if (!text) return '';
  const sentences = text.match(/[^.!?]+[.!?]+/g) || [text];
  return sentences.slice(0, maxSentences).join(' ').trim();
}

function tableCaption(text) {
  return `<p style="font-family:'IBM Plex Mono',monospace;font-size:11px;color:#91969C;text-transform:uppercase;letter-spacing:0.08em;margin:32px 0 6px;">${esc(text)}</p>`;
}

function callout(html) {
  return `<div class="callout">${html}</div>`;
}

// ── CSS ───────────────────────────────────────────────────────────────────────

const CSS = `
:root {
  --color-dark:   #171D1D;
  --color-muted:  #91969C;
  --color-sage:   #E6EAE6;
  --color-accent: #ED3A12;
  --color-white:  #FFFFFF;
  --color-bg:     #F9FAF9;
  --color-panel:  #F2F4F2;
}

*, *::before, *::after { box-sizing: border-box; }

body {
  background: var(--color-bg);
  color: var(--color-dark);
  font-family: 'Inter Tight', sans-serif;
  font-size: 15px;
  line-height: 1.65;
  margin: 0;
  padding-top: 52px;
}

/* ── Navigation ── */
.nav {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 100;
  background: var(--color-white);
  border-bottom: 1px solid var(--color-sage);
  display: flex;
  align-items: center;
  height: 52px;
  padding: 0 32px;
  gap: 24px;
}
.nav-brand {
  display: flex;
  align-items: baseline;
  gap: 8px;
  flex-shrink: 0;
}
.nav-brand-name {
  font-family: 'Instrument Serif', serif;
  font-size: 18px;
  color: var(--color-dark);
  text-decoration: none;
}
.nav-brand-project {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 12px;
  color: var(--color-muted);
}
.nav-links {
  display: flex;
  gap: 20px;
  list-style: none;
  margin: 0;
  padding: 0;
}
.nav-links a {
  font-family: 'Inter Tight', sans-serif;
  font-size: 12px;
  color: var(--color-muted);
  text-decoration: none;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  white-space: nowrap;
}
.nav-links a:hover { color: var(--color-dark); }
.download-btn {
  position: absolute;
  right: 32px;
  top: 50%;
  transform: translateY(-50%);
  font-family: 'IBM Plex Mono', monospace;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  background: var(--color-dark);
  color: var(--color-white);
  border: none;
  padding: 8px 16px;
  cursor: pointer;
  flex-shrink: 0;
}
.download-btn:hover { background: #2D3535; }

/* ── Document ── */
.document {
  max-width: 900px;
  margin: 0 auto;
  padding: 48px 40px 120px;
}

/* ── Cover ── */
.cover {
  padding-bottom: 64px;
  border-bottom: 1px solid var(--color-sage);
  margin-bottom: 56px;
}
.cover-eyebrow {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 12px;
  color: var(--color-muted);
  text-transform: uppercase;
  letter-spacing: 0.10em;
  margin: 0 0 20px;
}
.cover-title {
  font-family: 'Instrument Serif', serif;
  font-size: 56px;
  font-weight: 400;
  color: var(--color-dark);
  line-height: 1.08;
  margin: 0 0 16px;
}
.cover-rule {
  width: 48px;
  height: 2px;
  background: var(--color-accent);
  margin: 0 0 20px;
}
.cover-meta {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 13px;
  color: var(--color-dark);
  margin: 0 0 48px;
}
.cover-confidential {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 11px;
  color: var(--color-muted);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  margin: 0;
}

/* ── Chapter (H1) ── */
h1.chapter {
  font-family: 'Instrument Serif', serif;
  font-size: 38px;
  font-weight: 400;
  color: var(--color-dark);
  padding-top: 56px;
  margin: 0 0 10px;
  line-height: 1.15;
}
.chapter-rule {
  height: 2px;
  background: var(--color-accent);
  border: none;
  margin: 0 0 32px;
}

/* ── Section (H2) ── */
h2.section {
  font-family: 'Instrument Serif', serif;
  font-size: 24px;
  font-weight: 400;
  color: var(--color-dark);
  margin: 40px 0 8px;
}

/* ── Subsection (H3) ── */
h3.subsection {
  font-family: 'Inter Tight', sans-serif;
  font-size: 15px;
  font-weight: 600;
  color: var(--color-dark);
  margin: 28px 0 6px;
}

/* ── Body ── */
p { margin: 0 0 14px; }

/* ── Stat line ── */
.stat-line {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 11px;
  color: var(--color-muted);
  text-transform: uppercase;
  letter-spacing: 0.07em;
  margin: 4px 0 10px;
}

/* ── Metric cards ── */
.metric-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin: 32px 0;
}
.metric-card {
  background: var(--color-white);
  border: 1px solid var(--color-sage);
  padding: 20px 24px;
}
.metric-value {
  font-family: 'Instrument Serif', serif;
  font-size: 36px;
  color: var(--color-dark);
  line-height: 1;
}
.metric-label {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 11px;
  color: var(--color-muted);
  text-transform: uppercase;
  letter-spacing: 0.07em;
  margin-top: 6px;
}

/* ── Callout ── */
.callout {
  background: #FEF3E2;
  border-left: 3px solid var(--color-accent);
  padding: 14px 18px;
  margin: 20px 0;
  font-family: 'Inter Tight', sans-serif;
  font-size: 14px;
}
.callout strong { color: var(--color-dark); }

/* ── Tables ── */
table {
  width: 100%;
  border-collapse: collapse;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 12px;
  margin: 6px 0 32px;
}
thead tr { background: var(--color-dark); color: var(--color-white); }
thead th {
  padding: 10px 12px;
  text-align: left;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
tbody tr { border-bottom: 1px solid var(--color-sage); }
tbody td { padding: 9px 12px; vertical-align: top; }
tbody tr:last-child { border-bottom: none; }
tbody tr:hover { background: var(--color-panel); }

/* ── Steps list inside table ── */
.steps-list {
  margin: 0;
  padding: 0 0 0 16px;
  font-size: 11px;
  line-height: 1.5;
}
.steps-list li { margin: 2px 0; }

/* ── Sage panel ── */
.panel {
  background: var(--color-sage);
  border-left: 3px solid #C5CBC5;
  padding: 16px 20px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 12px;
  color: var(--color-dark);
  margin: 16px 0 24px;
  white-space: pre-wrap;
  word-break: break-all;
}
`.trim();

const PRINT_CSS = `
@media print {
  .nav { display: none !important; }
  body { padding-top: 0; }
  .document { max-width: 100%; }
  h1.chapter { break-before: page; }
  .cover { break-after: page; }
  a::after { content: " (" attr(href) ")"; font-size: 10px; color: #666; }
}
`.trim();

// ── Section builders ──────────────────────────────────────────────────────────

function buildNav() {
  const today = new Date().toLocaleDateString('en-GB', { year: 'numeric', month: 'long', day: 'numeric' });
  return `
<nav class="nav">
  <div class="nav-brand">
    <span class="nav-brand-name">Micro-Cosmos</span>
    <span class="nav-brand-project">· ${esc(projectName)}</span>
  </div>
  <ul class="nav-links">
    <li><a href="#overview">Overview</a></li>
    <li><a href="#codebase">Codebase</a></li>
    <li><a href="#domains">Domains</a></li>
    <li><a href="#constraints">Constraints</a></li>
    <li><a href="#plan">Plan</a></li>
    <li><a href="#appendix">App. A</a></li>
    <li><a href="#appendix-b">App. B</a></li>
    <li><a href="#appendix-c">App. C</a></li>
    <li><a href="#appendix-d">App. D</a></li>
  </ul>
  <button onclick="window.print()" class="download-btn">↓ Download PDF</button>
</nav>`.trim();
}

function buildCover() {
  const today = new Date().toLocaleDateString('en-GB', { year: 'numeric', month: 'long', day: 'numeric' });
  return `
<div class="cover">
  <p class="cover-eyebrow">Project synthesis report</p>
  <h1 class="cover-title">${esc(projectName)}</h1>
  <div class="cover-rule"></div>
  <p class="cover-meta">${esc(sourceLang)} → ${esc(targetLang)} · ${esc(today)}</p>
  <p class="cover-confidential">Micro-Cosmos · CONFIDENTIAL</p>
</div>`.trim();
}

function buildOverview() {
  const compRows = [
    ['PROGRAM',        nodeTypes.PROGRAM || 0,        'Source files and modules'],
    ['DATA_STRUCTURE', nodeTypes.DATA_STRUCTURE || 0,  'Classes, interfaces, type definitions'],
    ['PROCEDURE',      nodeTypes.PROCEDURE || 0,       'Functions and methods'],
  ];
  const compTableRows = compRows.map(([t, c, d]) =>
    `<tr><td>${esc(t)}</td><td>${esc(c)}</td><td>${esc(d)}</td></tr>`
  ).join('') +
    `<tr><td><strong>Total</strong></td><td><strong>${esc(nodes.length)}</strong></td><td></td></tr>`;

  const scopeRows = [
    ['Total seams',           seams.length],
    ['Total story points',    totalPts],
    ['Object seams',          seamTypes.object || 0],
    ['Link seams',            seamTypes.link || 0],
    ['Preprocessing seams',   seamTypes.preprocessing || 0],
    ['Message seams',         seamTypes.message || 0],
    ['Extraction phase',      `${phaseDist.extraction || 0} seams`],
    ['Isolation phase',       `${phaseDist.isolation || 0} seams`],
    ['High-risk contexts',    riskCounts.HIGH],
    ['Medium-risk contexts',  riskCounts.MEDIUM],
    ['Low-risk contexts',     riskCounts.LOW],
  ].map(([m, v]) => `<tr><td>${esc(m)}</td><td>${esc(v)}</td></tr>`).join('');

  return `
<section id="overview">
  <h1 class="chapter">Project Overview</h1>
  <hr class="chapter-rule">

  <div class="metric-row">
    <div class="metric-card">
      <div class="metric-value">${esc(nodes.length)}</div>
      <div class="metric-label">IR Nodes</div>
    </div>
    <div class="metric-card">
      <div class="metric-value">${esc(edges.length)}</div>
      <div class="metric-label">Edges</div>
    </div>
    <div class="metric-card">
      <div class="metric-value">${esc(contexts.length)}</div>
      <div class="metric-label">Contexts</div>
    </div>
    <div class="metric-card">
      <div class="metric-value">${esc(totalPts)} pts</div>
      <div class="metric-label">Story Points</div>
    </div>
  </div>

  <p>
    This document is a complete technical assessment of <strong>${esc(projectName)}</strong>,
    a ${esc(sourceLang)} codebase, covering structure, domain decomposition, migration
    readiness, and the full refactoring plan for migration to ${esc(targetLang)}.
    The assessment was produced by static analysis of the intermediate representation (IR)
    graph and requires no manual annotation.
  </p>

  ${tableCaption('TABLE 1 — CODEBASE COMPOSITION')}
  <table>
    <thead><tr><th>Node Type</th><th>Count</th><th>Description</th></tr></thead>
    <tbody>${compTableRows}</tbody>
  </table>

  ${tableCaption('TABLE 2 — MIGRATION SCOPE')}
  <table>
    <thead><tr><th>Metric</th><th>Value</th></tr></thead>
    <tbody>${scopeRows}</tbody>
  </table>
</section>`.trim();
}

function buildCodebase() {
  // Hotspots table
  const hotspotRows = hotspots.map(h =>
    `<tr>
      <td>${esc(h.id)}</td>
      <td>${esc(h.count)}</td>
      <td>${esc(stripPrefix(h.node.source_location))}</td>
    </tr>`
  ).join('');

  const topHotspot = hotspots[0] || {};

  // God class table
  const godRows = godCandidates.map(g =>
    `<tr>
      <td>${esc(g.id)}</td>
      <td>${esc(g.count)}</td>
      <td>${esc(stripPrefix(g.node.source_location))}</td>
    </tr>`
  ).join('');

  const topGod = godCandidates[0] || {};

  // Circular deps table (always emit TABLE 5 caption for integrity check)
  const circRows = mutualPairs.map(p =>
    `<tr><td>${esc(p.a)}</td><td>${esc(p.b)}</td></tr>`
  ).join('');
  const circularContent = `
    ${tableCaption('TABLE 5 — MUTUAL CALL PAIRS')}
    ${mutualPairs.length === 0
      ? '<p>No circular dependencies detected.</p>'
      : `<table><thead><tr><th>Node A</th><th>Node B</th></tr></thead><tbody>${circRows}</tbody></table>`
    }`;

  return `
<section id="codebase">
  <h1 class="chapter">Codebase Analysis</h1>
  <hr class="chapter-rule">
  <p>
    Structural analysis of <strong>${esc(projectName)}</strong> derived from the IR graph.
    The following findings cover coupling hotspots, oversized components, circular
    dependencies, and test coverage — each representing a category of migration risk
    that must be addressed during the refactoring phase.
  </p>

  <h2 class="section">Coupling Hotspots</h2>
  <p>
    The following nodes have the highest fan-in (incoming CALLS edges) in the codebase.
    High fan-in indicates tight coupling and signals where interface extraction is most
    critical before migration can proceed safely.
  </p>
  ${topHotspot.id ? callout(`<strong>${esc(topHotspot.id)}</strong> has ${esc(topHotspot.count)} callers — the highest fan-in in the codebase. Any change to this node affects a significant fraction of all program nodes.`) : ''}
  ${tableCaption('TABLE 3 — TOP 10 FAN-IN HOTSPOTS')}
  <table>
    <thead><tr><th>Node ID</th><th>Callers</th><th>Source Path</th></tr></thead>
    <tbody>${hotspotRows}</tbody>
  </table>

  <h2 class="section">Oversized Components</h2>
  <p>
    The following nodes define the most children via DEFINES edges.
    Nodes with 15 or more children are candidates for decomposition before migration,
    as their size increases the risk of incomplete interface extraction.
  </p>
  ${topGod.id ? callout(`<strong>${esc(topGod.id)}</strong> defines ${esc(topGod.count)} children — significantly above the recommended threshold of 15. This is the highest-complexity component in the codebase.`) : ''}
  ${tableCaption('TABLE 4 — TOP 10 COMPONENTS BY COMPLEXITY')}
  <table>
    <thead><tr><th>Node ID</th><th>Children</th><th>Source Path</th></tr></thead>
    <tbody>${godRows}</tbody>
  </table>

  <h2 class="section">Circular Dependencies</h2>
  <p>
    ${esc(mutualPairs.length)} mutual call pair${mutualPairs.length !== 1 ? 's' : ''} ${mutualPairs.length !== 1 ? 'were' : 'was'} detected.
    These represent potential circular dependencies that must be resolved before
    extraction can produce well-bounded services.
  </p>
  ${circularContent}

  <h2 class="section">Test Coverage</h2>
  <p>
    <strong>${esc(testNodes.length)}</strong> test/spec files out of
    <strong>${esc(progNodes.length)}</strong> total program nodes
    (<strong>${esc(testRatio)}%</strong> coverage proxy).
    ${esc(implNodes.length)} implementation files have no corresponding test or spec file.
  </p>
  ${callout(`<strong>At ${esc(testRatio)}% test file coverage</strong>, a significant portion of the implementation has no corresponding test file. Migration of untested components carries higher risk of undetected regressions.`)}
</section>`.trim();
}

function buildDomains() {
  const contextSections = contexts.map(ctx => {
    const svc      = serviceByCtx[ctx.name] || {};
    const decision = decisionByCtx[ctx.name] || {};
    const risk     = svc.migration_risk || 'LOW';
    const comm     = decision.communication_style || 'sync-http';
    const nodeCount = (ctx.node_ids || []).length;

    return `
  <h3 class="subsection">${esc(ctx.name)}</h3>
  <p>${esc(cap(ctx.rationale || '', 3))}</p>
  <p class="stat-line">
    ${esc(nodeCount)} nodes · ${riskBadge(risk)} · ${esc(comm)}
  </p>`;
  }).join('');

  const callRows = [...(bcm.cross_context_calls || [])]
    .sort((a, b) => String(a[0]).localeCompare(String(b[0])))
    .map(([src, tgt]) => `<tr><td>${esc(src)}</td><td>${esc(tgt)}</td></tr>`)
    .join('');

  return `
<section id="domains">
  <h1 class="chapter">Bounded Context Map</h1>
  <hr class="chapter-rule">
  <p>
    The codebase was decomposed into <strong>${esc(contexts.length)}</strong> bounded contexts
    using file-path classification applied to the IR graph, propagated through DEFINES edges
    to all child nodes. <strong>${esc((bcm.cross_context_calls || []).length)}</strong>
    cross-context call relationships were identified, defining the seam boundaries between
    future services.
  </p>
  ${contextSections}

  ${tableCaption('TABLE 6 — CROSS-CONTEXT CALL RELATIONSHIPS')}
  <table>
    <thead><tr><th>Source Context</th><th>Target Context</th></tr></thead>
    <tbody>${callRows}</tbody>
  </table>
</section>`.trim();
}

function buildConstraints() {
  const fnSections = fitnessFns.map((fn, i) => `
  <h3 class="subsection">${esc(fn.name)}</h3>
  <p>${esc(fn.description)}</p>
  <p>The rationale for this constraint is: ${esc(fn.rationale)}</p>
  <p style="font-family:'IBM Plex Mono',monospace;font-size:11px;color:#91969C;text-transform:uppercase;letter-spacing:0.08em;margin:16px 0 6px;">CONSTRAINT ${i + 1} — ${esc(fn.id)}</p>
  <div class="panel">${esc(fn.spec)}</div>`).join('');

  const dimSections = fitnessDims.map(([dimKey, dimVal]) => {
    const title = dimKey.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
    const first = (dimVal || '').trim().split(/[\s.]/)[0];
    const statusStyle = first === 'High'
      ? 'background:#EAF4EA;color:#2E7D32;border:1px solid #B8DDB8'
      : first === 'Medium'
      ? 'background:#FEF3E2;color:#A0522D;border:1px solid #F5DFB8'
      : 'background:#FDECEA;color:#C0392B;border:1px solid #F5C6C2';
    const badge = `<span style="display:inline-block;padding:2px 7px;border-radius:2px;font-family:'IBM Plex Mono',monospace;font-size:11px;text-transform:uppercase;letter-spacing:0.04em;${statusStyle}">${esc(first === 'High' ? 'SATISFIED' : first === 'Medium' ? 'PARTIAL' : 'AT RISK')}</span>`;
    return `
  <h3 class="subsection">${esc(title)}</h3>
  <p>${badge} ${esc(dimVal)}</p>`;
  }).join('');

  const allFnSections = (fnSections + dimSections) || '<p>No fitness functions defined in this run.</p>';

  // Architectural notes — collapsible section
  const archNotesHtml = archNotes.length ? `
  <h2 class="section">Architectural Notes</h2>
  <details style="margin:16px 0">
    <summary style="cursor:pointer;font-family:'IBM Plex Mono',monospace;font-size:12px;text-transform:uppercase;letter-spacing:0.06em">Expand (${archNotes.length} notes)</summary>
    ${archNotes.map(n => `
      <h3 class="subsection">${esc(n.concern || '')}</h3>
      ${n.placement ? `<div class="panel">${esc(n.placement)}</div>` : ''}
      ${n.seam_location ? `<p style="font-size:12px;color:#91969C">Seam location: <code>${esc(n.seam_location)}</code></p>` : ''}`).join('')}
  </details>` : '';

  // Migration sequence rationale callout
  const rationaleHtml = migrationRationale ? callout(`<strong>Migration sequence rationale:</strong> ${esc(migrationRationale)}`) : '';

  return `
<section id="constraints">
  <h1 class="chapter">Architectural Constraints</h1>
  <hr class="chapter-rule">
  <p>
    The following fitness functions are <strong>BLOCKING</strong>. Each must pass before
    the migrated service is accepted into the target codebase. These rules are committed
    to the client CI pipeline on day one and gate every pull request for the duration of
    the engagement. Derived from <code>tnas.fitness_suite</code>.
  </p>
  ${allFnSections}
  ${archNotesHtml}
  ${rationaleHtml}
</section>`.trim();
}

function buildPlan() {
  const sorted = [...streams].sort((a, b) => (a.seq || 0) - (b.seq || 0));

  // Stream sequencing table
  const seqRows = sorted.map(s => {
    const depNames = (s.depends_on || [])
      .map(id => streamById[id] ? streamById[id].name : id)
      .join(', ') || '—';
    return `<tr>
      <td>${esc(s.seq)}</td>
      <td>${esc(s.name)}</td>
      <td>${esc(s.seam_count)}</td>
      <td>${esc(s.story_points)}</td>
      <td>${riskBadge(s.risk)}</td>
      <td>${esc(depNames)}</td>
    </tr>`;
  }).join('');

  // Effort distribution table
  const effortTiers = ['XS', 'S', 'M', 'L'];
  const effortRows = effortTiers.map(tier => {
    const count = effortDist[tier] || 0;
    const pts   = effortPts[tier] || 0;
    return `<tr>
      <td>${esc(tier)}</td>
      <td>${esc(count)}</td>
      <td>${esc(pts)}</td>
      <td>${pct(pts, totalPts)}%</td>
    </tr>`;
  }).join('');
  const effortTotal = `<tr>
    <td><strong>Total</strong></td>
    <td><strong>${esc(seams.length)}</strong></td>
    <td><strong>${esc(totalPts)}</strong></td>
    <td><strong>100%</strong></td>
  </tr>`;

  // Per-stream detail sections
  const streamDetails = sorted.map(s => {
    const depNames = (s.depends_on || []).map(id => streamById[id] ? streamById[id].name : id);
    const depLine = depNames.length > 0
      ? `<p>Depends on: ${esc(depNames.join(', '))}.</p>` : '';
    const typeParts = Object.entries(s.seam_types_present || {})
      .map(([t, n]) => `${n} ${t}`).join(', ');
    const typeBreakdown = typeParts
      ? `<p>Seam breakdown: ${esc(typeParts)}.</p>` : '';

    return `
  <h3 class="subsection">${esc(s.name)}</h3>
  <p>${esc(s.rationale)}</p>
  <p class="stat-line">
    ${esc(s.seam_count)} seams · ${esc(s.story_points)} pts · ${esc(s.dominant_effort)} effort · ${riskBadge(s.risk)}
  </p>
  ${depLine}
  ${typeBreakdown}`;
  }).join('');

  return `
<section id="plan">
  <h1 class="chapter">Migration Plan</h1>
  <hr class="chapter-rule">
  <p>
    Streams must be executed in sequence order. Streams with no dependencies may run
    in parallel with other zero-dependency streams. Each stream boundary maps to a
    bounded context, ensuring that refactoring seams are resolved before their
    downstream consumers are migrated.
  </p>

  ${tableCaption('TABLE 7 — WORK STREAM EXECUTION ORDER')}
  <table>
    <thead>
      <tr>
        <th>Seq</th><th>Stream</th><th>Seams</th><th>Points</th><th>Risk</th><th>Depends On</th>
      </tr>
    </thead>
    <tbody>${seqRows}</tbody>
  </table>

  ${tableCaption('TABLE 8 — EFFORT DISTRIBUTION')}
  <table>
    <thead>
      <tr><th>Effort</th><th>Seams</th><th>Story Points</th><th>% of Total</th></tr>
    </thead>
    <tbody>${effortRows}${effortTotal}</tbody>
  </table>

  <h2 class="section">Stream Details</h2>
  ${streamDetails}
</section>`.trim();
}

function buildAppendixA() {
  const sorted = [...seams].sort((a, b) =>
    ((b.work && b.work.story_points) || 0) - ((a.work && a.work.story_points) || 0)
  );

  const rows = sorted.map(s => {
    const w = s.work || {};
    const steps = (w.steps || []);
    const stepsHtml = steps.length > 0
      ? `<ol class="steps-list">${steps.map(st => `<li>${esc(st)}</li>`).join('')}</ol>`
      : '';
    return `<tr>
      <td>${esc(s.id)}</td>
      <td>${esc(s.type)}</td>
      <td>${esc(s.location)}</td>
      <td>${esc(w.effort)}</td>
      <td>${esc(w.story_points)}</td>
      <td>${riskBadge(w.risk)}</td>
      <td>${esc(w.migration_phase)}</td>
      <td>${stepsHtml}</td>
    </tr>`;
  }).join('');

  return `
<section id="appendix">
  <h1 class="chapter">Appendix A — Seam Inventory</h1>
  <hr class="chapter-rule">
  ${tableCaption(`TABLE 9 — SEAM INVENTORY (${seams.length} seams)`)}
  <table>
    <thead>
      <tr>
        <th>ID</th><th>Type</th><th>Location</th>
        <th>Effort</th><th>Points</th><th>Risk</th><th>Phase</th><th>Steps</th>
      </tr>
    </thead>
    <tbody>${rows}</tbody>
  </table>
</section>`.trim();
}

function buildAppendixB() {
  const rows = contexts.map(ctx => {
    const svc   = serviceByCtx[ctx.name] || {};
    const risk  = svc.migration_risk || 'LOW';
    const nids  = ctx.node_ids || [];
    const shown = nids.slice(0, 5);
    const rest  = nids.length - shown.length;
    const nodeCell = shown.map(esc).join(', ') + (rest > 0 ? ` … and ${rest} more` : '');
    return `<tr>
      <td>${esc(ctx.name)}</td>
      <td>${riskBadge(risk)}</td>
      <td>${esc(nids.length)}</td>
      <td>${nodeCell}</td>
    </tr>`;
  }).join('');

  return `
<section id="appendix-b">
  <h1 class="chapter">Appendix B — Context Node Inventory</h1>
  <hr class="chapter-rule">
  ${tableCaption('TABLE 10 — CONTEXT NODE ASSIGNMENTS')}
  <table>
    <thead>
      <tr><th>Context</th><th>Risk</th><th>Nodes</th><th>Node IDs (truncated)</th></tr>
    </thead>
    <tbody>${rows}</tbody>
  </table>
</section>`.trim();
}

function buildAppendixC() {
  // All PROCEDURE nodes (methods + fns + arrows), sorted by id
  const procs = nodes
    .filter(n => n.type === 'PROCEDURE')
    .sort((a, b) => (a.id || '').localeCompare(b.id || ''));

  const rows = procs.map(n => {
    const attrs   = n.attributes || {};
    const kind    = attrs.kind || n.type;
    const parent  = attrs.class || '';
    const inputs  = (n.inputs || []).map(i => `${esc(i.name)}: ${esc(i.type)}`).join('<br>') || '—';
    const output  = n.output ? esc(n.output) : '—';
    const summary = n.summary ? esc(n.summary) : '—';
    const mods    = [attrs.modifiers, attrs.async === 'true' ? 'async' : ''].filter(Boolean).join(' ');
    return `<tr>
      <td>${esc(n.name)}${mods ? `<br><span style="color:#91969C">${esc(mods)}</span>` : ''}</td>
      <td>${esc(kind)}</td>
      <td>${esc(parent) || '—'}</td>
      <td>${inputs}</td>
      <td>${output}</td>
      <td>${summary}</td>
      <td style="color:#91969C">${esc(stripPrefix(n.source_location))}</td>
    </tr>`;
  }).join('');

  return `
<section id="appendix-c">
  <h1 class="chapter">Appendix C — Procedure Signatures</h1>
  <hr class="chapter-rule">
  <p>
    All ${esc(procs.length)} procedure nodes (methods, functions, arrow functions) extracted
    from the IR graph. Inputs list parameter names and types; output shows the return type.
    Summary is derived from the source code analysis.
  </p>
  ${tableCaption(`TABLE 11 — PROCEDURE SIGNATURES (${procs.length} procedures)`)}
  <table>
    <thead>
      <tr>
        <th>Name</th><th>Kind</th><th>Class</th>
        <th>Inputs</th><th>Output</th><th>Summary</th><th>Source</th>
      </tr>
    </thead>
    <tbody>${rows}</tbody>
  </table>
</section>`.trim();
}

function buildAppendixD() {
  // All DATA_STRUCTURE nodes (interfaces, classes, types), sorted by id
  const types = nodes
    .filter(n => n.type === 'DATA_STRUCTURE')
    .sort((a, b) => (a.id || '').localeCompare(b.id || ''));

  const rows = types.map(n => {
    const attrs      = n.attributes || {};
    const kind       = attrs.kind || 'type';
    const fieldCount = attrs.field_count || (n.inputs || []).length || '—';
    const fields     = (n.inputs || []).map(i =>
      `${esc(i.name)}: ${esc(i.type)}`
    ).join('<br>') || '—';
    const summary = n.summary ? esc(n.summary) : '—';
    const exported = attrs.export === 'true' ? 'yes' : 'no';
    return `<tr>
      <td>${esc(n.name)}</td>
      <td>${esc(kind)}</td>
      <td>${esc(fieldCount)}</td>
      <td>${fields}</td>
      <td>${summary}</td>
      <td>${esc(exported)}</td>
      <td style="color:#91969C">${esc(stripPrefix(n.source_location))}</td>
    </tr>`;
  }).join('');

  return `
<section id="appendix-d">
  <h1 class="chapter">Appendix D — Data Type Definitions</h1>
  <hr class="chapter-rule">
  <p>
    All ${esc(types.length)} data structure nodes (interfaces, classes, type definitions)
    extracted from the IR graph. Fields lists each property name and its declared type.
    Summary is derived from source code analysis.
  </p>
  ${tableCaption(`TABLE 12 — DATA TYPE DEFINITIONS (${types.length} types)`)}
  <table>
    <thead>
      <tr>
        <th>Name</th><th>Kind</th><th>Fields</th>
        <th>Field Definitions</th><th>Summary</th><th>Exported</th><th>Source</th>
      </tr>
    </thead>
    <tbody>${rows}</tbody>
  </table>
</section>`.trim();
}

// ── Assemble ──────────────────────────────────────────────────────────────────

function buildHTML() {
  const title = `${projectName} — Project synthesis report`;
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>${esc(title)}</title>
  <link href="https://fonts.googleapis.com/css2?family=Instrument+Serif&family=Inter+Tight:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
  <style>
${CSS}
  </style>
  <style media="print">
${PRINT_CSS}
  </style>
</head>
<body>
${buildNav()}
<div class="document">
${buildCover()}
${buildOverview()}
${buildCodebase()}
${buildDomains()}
${buildConstraints()}
${buildPlan()}
${buildAppendixA()}
${buildAppendixB()}
${buildAppendixC()}
${buildAppendixD()}
</div>
</body>
</html>`;
}

// ── Validate and write ────────────────────────────────────────────────────────

const html = buildHTML();

// Check for bad interpolation: bare >undefined< or >[object Object]< as cell/tag content,
// not the word "undefined" inside type strings like "number | null | undefined".
if (html.includes('>[object Object]<') || html.includes('>[object Object]')
    || />\s*undefined\s*</.test(html)) {
  console.error('ERROR: bad interpolation in output');
  process.exit(1);
}

for (let i = 1; i <= 12; i++) {
  if (!html.includes(`TABLE ${i}`)) {
    console.error(`ERROR: TABLE ${i} missing`);
    process.exit(1);
  }
}

['overview', 'codebase', 'domains', 'constraints', 'plan', 'appendix', 'appendix-b', 'appendix-c', 'appendix-d']
  .forEach(id => {
    if (!html.includes(`id="${id}"`)) {
      console.error(`ERROR: anchor #${id} missing`);
      process.exit(1);
    }
  });

const tableRowCount = (html.match(/<tr/g) || []).length;
console.log('Total <tr> tags:', tableRowCount);

const outPath = outArg || path.join(runDir, 'project-synthesis.html');
fs.writeFileSync(outPath, html, 'utf8');
console.log(`Written: ${outPath} (${html.length} bytes)`);

const outputsDir = '/mnt/user-data/outputs';
if (fs.existsSync(outputsDir)) {
  fs.writeFileSync(path.join(outputsDir, 'project-synthesis.html'), html, 'utf8');
  console.log(`Copied to ${outputsDir}/project-synthesis.html`);
}
