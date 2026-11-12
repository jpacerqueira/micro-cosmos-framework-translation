#!/usr/bin/env node
'use strict';

/**
 * generate_hotspots.js
 *
 * Hotspot & coupling report: fan-in ranking, god-class candidates,
 * circular dependencies, context×context coupling matrix, risk ranking.
 *
 * Usage:
 *   node scripts/generate_hotspots.js <run_dir>
 *   node scripts/generate_hotspots.js <run_dir> <out>
 */

const fs   = require('fs');
const path = require('path');
const {
  esc, countBy, riskBadge, callout, tableCaption,
  normaliseBCM, htmlShell, writeReport, stripPrefix,
} = require('./report_common');

const args   = process.argv.slice(2);
const runDir = args[0] ? path.resolve(args[0]) : process.cwd();
const outArg = args[1] ? path.resolve(args[1]) : null;

function read(name) {
  const p = path.join(runDir, name);
  if (!fs.existsSync(p)) throw new Error(`Required file not found: ${p}`);
  return JSON.parse(fs.readFileSync(p, 'utf8'));
}
function readOpt(name) {
  const p = path.join(runDir, name);
  return fs.existsSync(p) ? JSON.parse(fs.readFileSync(p, 'utf8')) : null;
}

const meta   = read('run_meta.json');
const ir     = read('ir_graph.json');
const bcmRaw = readOpt('bounded_context_map.json');
const seamData = readOpt('seam.json');

const projectName = path.basename(meta.source_path || 'unknown');

const nodes = ir.nodes || [];
const edges = ir.edges || [];
const nodeMap = Object.fromEntries(nodes.map(n => [n.id, n]));

const { contexts, crossContextCalls } = normaliseBCM(bcmRaw);

// ── Fan-in (inbound CALLS per target) ────────────────────────────────────────

const fanIn = {};
edges.filter(e => e.type === 'CALLS').forEach(e => {
  fanIn[e.target_id] = (fanIn[e.target_id] || 0) + 1;
});
const hotspots = Object.entries(fanIn)
  .sort((a, b) => b[1] - a[1])
  .slice(0, 25)
  .map(([id, count]) => ({ id, count, node: nodeMap[id] || {} }));

const maxFanIn = hotspots.length > 0 ? hotspots[0].count : 1;

// ── God-class candidates (DEFINES count) ─────────────────────────────────────

const defineCount = {};
edges.filter(e => e.type === 'DEFINES').forEach(e => {
  defineCount[e.source_id] = (defineCount[e.source_id] || 0) + 1;
});
const godCandidates = Object.entries(defineCount)
  .sort((a, b) => b[1] - a[1])
  .slice(0, 15)
  .map(([id, count]) => ({ id, count, node: nodeMap[id] || {} }));

const maxDefines = godCandidates.length > 0 ? godCandidates[0].count : 1;

// ── Circular dependencies ─────────────────────────────────────────────────────

const callsGraph = {};
edges.filter(e => e.type === 'CALLS').forEach(e => {
  if (!callsGraph[e.source_id]) callsGraph[e.source_id] = new Set();
  callsGraph[e.source_id].add(e.target_id);
});
const mutualPairs = [];
const seenKeys = new Set();
Object.entries(callsGraph).forEach(([src, targets]) => {
  targets.forEach(tgt => {
    if (src !== tgt && callsGraph[tgt] && callsGraph[tgt].has(src)) {
      const key = [src, tgt].sort().join('||');
      if (!seenKeys.has(key)) { seenKeys.add(key); mutualPairs.push({ a: src, b: tgt }); }
    }
  });
});

// ── Context×context coupling matrix ──────────────────────────────────────────

// Build node_id → context name map
const nodeToCtx = {};
for (const ctx of contexts) {
  for (const nid of (ctx.node_ids || [])) nodeToCtx[nid] = ctx.name;
}

// Count cross-context CALLS edges
const ctxMatrix = {};  // { 'src|tgt': count }
let matrixEdges = 0;
if (contexts.length > 0) {
  edges.filter(e => e.type === 'CALLS').forEach(e => {
    const src = nodeToCtx[e.source_id];
    const tgt = nodeToCtx[e.target_id];
    if (src && tgt && src !== tgt) {
      const key = `${src}|${tgt}`;
      ctxMatrix[key] = (ctxMatrix[key] || 0) + 1;
      matrixEdges++;
    }
  });
  // Fallback: seed from cross_context_calls (name-level data)
  if (matrixEdges === 0) {
    for (const [src, tgt] of crossContextCalls) {
      const key = `${src}|${tgt}`;
      ctxMatrix[key] = (ctxMatrix[key] || 0) + 1;
    }
  }
}

const ctxNames = contexts.map(c => c.name);
const maxCell  = Math.max(1, ...Object.values(ctxMatrix));

function cellStyle(val) {
  if (val === 0) return 'background:#F5F5F5;color:#CCC';
  const intensity = val / maxCell;
  if (intensity < 0.33) return 'background:#FFF3CD;color:#856404;border:1px solid #FFE69C';
  if (intensity < 0.66) return 'background:#FFD6A5;color:#7C3C00;border:1px solid #FFBB70';
  return 'background:#FDECEA;color:#C0392B;border:1px solid #F5C6C2';
}

// ── Seam memberships for risk ranking ────────────────────────────────────────

const seamIds = new Set((seamData ? (seamData.seams || []) : []).map(s => s.location));

// ── Consolidated risk ranking ─────────────────────────────────────────────────

const riskRanking = Object.entries(fanIn)
  .map(([id, fi]) => {
    const def  = defineCount[id] || defineCount[id.replace('prog.', 'class.')] || 0;
    const node = nodeMap[id] || {};
    const inSeam = seamIds.has(id);
    const score  = fi * 3 + (def > 30 ? 4 : def > 15 ? 2 : 0) + (inSeam ? 2 : 0);
    return { id, fi, def, score, node, inSeam };
  })
  .sort((a, b) => b.score - a.score)
  .slice(0, 10);

// ── Render ────────────────────────────────────────────────────────────────────

const hotspotRows = hotspots.map(h => {
  const barWidth = Math.round(h.count / maxFanIn * 100);
  const seam = seamIds.has(h.id) ? '<span style="font-family:\'IBM Plex Mono\',monospace;font-size:10px;color:#C0392B;border:1px solid #F5C6C2;background:#FDECEA;padding:1px 5px;border-radius:2px;margin-left:6px">seam</span>' : '';
  return `<tr>
    <td style="color:#91969C;width:24px">${esc(hotspots.indexOf(h) + 1)}</td>
    <td style="font-weight:600">${esc(h.id)}${seam}</td>
    <td>${esc(h.count)}</td>
    <td><div class="bar-wrap"><div class="bar" style="width:${barWidth}px;max-width:120px"></div></div></td>
    <td style="color:#91969C;font-size:11px">${esc(stripPrefix(h.node.source_location, projectName))}</td>
  </tr>`;
}).join('');

const godRows = godCandidates.map(g => {
  const barWidth = Math.round(g.count / maxDefines * 100);
  const verdict = g.count > 40 ? '<span style="color:#C0392B;font-weight:600">Decompose</span>'
                : g.count > 15 ? '<span style="color:#A0522D">Review</span>'
                : '<span style="color:#2E7D32">Acceptable</span>';
  return `<tr>
    <td style="font-weight:600">${esc(g.id)}</td>
    <td>${esc(g.count)}</td>
    <td><div class="bar-wrap"><div class="bar" style="width:${barWidth}px;max-width:120px"></div></div></td>
    <td>${verdict}</td>
    <td style="color:#91969C;font-size:11px">${esc(stripPrefix(g.node.source_location, projectName))}</td>
  </tr>`;
}).join('');

const circularContent = mutualPairs.length === 0
  ? '<p style="color:#2E7D32;font-family:\'IBM Plex Mono\',monospace">✓ No circular dependencies detected. (' + esc(edges.filter(e => e.type === 'CALLS').length) + ' CALLS edges analysed.)</p>'
  : tableCaption(`MUTUAL CALL PAIRS (${mutualPairs.length})`) + `<table>
      <thead><tr><th>Node A</th><th>Node B</th></tr></thead>
      <tbody>${mutualPairs.map(p => `<tr><td>${esc(p.a)}</td><td>${esc(p.b)}</td></tr>`).join('')}</tbody>
    </table>`;

// Matrix HTML
let matrixHtml = '<p style="color:#91969C">Not enough context data for coupling matrix.</p>';
if (ctxNames.length > 1) {
  const headerCols = ctxNames.map(n => `<th style="text-align:center;padding:8px 12px;font-family:'IBM Plex Mono',monospace;font-size:11px;color:#91969C;text-transform:uppercase;letter-spacing:0.05em">→ ${esc(n)}</th>`).join('');
  const matrixBodyRows = ctxNames.map(srcName => {
    const rowLabel = `<td style="text-align:right;padding:8px 12px;font-family:'IBM Plex Mono',monospace;font-size:12px;font-weight:600;white-space:nowrap">${esc(srcName)} →</td>`;
    const cells = ctxNames.map(tgtName => {
      if (srcName === tgtName) {
        return `<td style="background:#F5F5F5;padding:10px 24px;text-align:center;color:#CCC;font-size:11px">—</td>`;
      }
      const val  = ctxMatrix[`${srcName}|${tgtName}`] || 0;
      const style = cellStyle(val);
      return `<td style="${style};padding:12px 24px;text-align:center;font-family:'IBM Plex Mono',monospace;font-size:13px;font-weight:600;min-width:80px">
        ${val > 0 ? esc(val) : '0'}
        <div style="font-size:10px;font-weight:400;margin-top:2px;opacity:0.7">${val > 0 ? 'call' + (val !== 1 ? 's' : '') : ''}</div>
      </td>`;
    }).join('');
    return `<tr>${rowLabel}${cells}</tr>`;
  }).join('');
  matrixHtml = `
  <p>Cell values = number of cross-context CALLS edges from <em>row context</em> to <em>column context</em>.
  Yellow = low coupling &nbsp;·&nbsp; orange = medium &nbsp;·&nbsp; red = high.
  Bidirectional coupling (both cells non-zero) signals a boundary to clarify before migration.</p>
  <div style="overflow-x:auto">
  <table style="width:auto;border-collapse:separate;border-spacing:3px">
    <thead><tr><th style="background:transparent"></th>${headerCols}</tr></thead>
    <tbody>${matrixBodyRows}</tbody>
  </table>
  </div>`;
}

// Context confidence table
const ctxConfRows = contexts.map(ctx => {
  const conf = typeof ctx.confidence === 'number'
    ? `${Math.round(ctx.confidence * 100)}%` : String(ctx.confidence || '?');
  const quality = (typeof ctx.confidence === 'number' ? ctx.confidence : 0) >= 0.8
    ? riskBadge('low') : riskBadge('medium');
  return `<tr><td style="font-weight:600">${esc(ctx.name)}</td><td>${esc(conf)}</td><td>${quality}</td></tr>`;
}).join('') || '<tr><td colspan="3" style="color:#91969C">No context data.</td></tr>';

const riskRows = riskRanking.map((r, i) => {
  const tags = [];
  if (r.fi  > 0)  tags.push(`fan-in ${r.fi}`);
  if (r.def > 0)  tags.push(`${r.def} members`);
  if (r.inSeam)   tags.push('seam candidate');
  const tagHtml = tags.map(t => `<span style="background:#F0F4F0;border:1px solid #D0D8D0;border-radius:3px;padding:1px 6px;font-size:10px;color:#2E7D32;margin-right:4px">${esc(t)}</span>`).join('');
  return `<tr>
    <td style="color:#91969C;width:24px">${i + 1}</td>
    <td style="font-weight:600">${esc(r.id)}</td>
    <td>${tagHtml}</td>
  </tr>`;
}).join('');

const godTop = godCandidates[0];
const bodyHtml = `
<section id="fanin">
  <h1 class="chapter">Fan-in ranking</h1>
  <hr class="chapter-rule">
  <p>Files with the highest number of inbound CALLS edges — i.e. files the most other files depend on.
  High fan-in = wide blast radius. These are the nodes to extract interfaces from
  <strong>before</strong> migration begins. Nodes tagged <span style="color:#C0392B;font-family:'IBM Plex Mono',monospace;font-size:11px">seam</span> are already identified as migration seams.</p>
  ${hotspots.length > 0 ? callout(`<strong>${esc(hotspots[0].id)}</strong> has ${esc(hotspots[0].count)} caller${hotspots[0].count !== 1 ? 's' : ''} — the highest fan-in in the codebase.`) : ''}
  ${tableCaption(`TOP ${hotspots.length} FAN-IN HOTSPOTS`)}
  <table>
    <thead><tr><th>#</th><th>Node</th><th>Callers</th><th></th><th>Source path</th></tr></thead>
    <tbody>${hotspotRows}</tbody>
  </table>
</section>

<section id="godclass">
  <h1 class="chapter">God-class candidates</h1>
  <hr class="chapter-rule">
  <p>Classes with the highest number of members (DEFINES edges). Classes with &gt;15 members are
  candidates for decomposition before migration; classes with &gt;40 members should be decomposed
  first, regardless of seam status.</p>
  ${godTop ? callout(`<strong>${esc(godTop.id)}</strong> defines ${esc(godTop.count)} members — significantly above the recommended threshold of 15. This is the highest-complexity component and the highest-priority design task in the migration.`, godTop.count > 40 ? 'warn' : undefined) : ''}
  ${tableCaption(`TOP ${godCandidates.length} COMPONENTS BY SIZE`)}
  <table>
    <thead><tr><th>Node</th><th>Members</th><th></th><th>Verdict</th><th>Source path</th></tr></thead>
    <tbody>${godRows}</tbody>
  </table>
</section>

<section id="cycles">
  <h1 class="chapter">Circular dependencies</h1>
  <hr class="chapter-rule">
  <p>Mutual CALLS between files (A calls B <em>and</em> B calls A). These create brittle
  coupling that must be resolved before extraction can produce well-bounded services.</p>
  ${circularContent}
</section>

<section id="matrix">
  <h1 class="chapter">Context coupling matrix</h1>
  <hr class="chapter-rule">
  ${matrixHtml}

  ${tableCaption('CONTEXT CONFIDENCE')}
  <table style="width:auto">
    <thead><tr><th>Context</th><th>Confidence</th><th>Quality</th></tr></thead>
    <tbody>${ctxConfRows}</tbody>
  </table>
</section>

<section id="ranking">
  <h1 class="chapter">Consolidated risk ranking</h1>
  <hr class="chapter-rule">
  <p>Combined score: fan-in × 3 + god-class size factor + seam membership bonus.
  Higher = touch last / most carefully.</p>
  <table>
    <thead><tr><th>#</th><th>Node</th><th>Risk factors</th></tr></thead>
    <tbody>${riskRows || '<tr><td colspan="3" style="color:#91969C">No ranked nodes.</td></tr>'}</tbody>
  </table>
</section>
`;

const html = htmlShell({
  title:      `${projectName} — Hotspots & coupling`,
  projectName,
  reportType: 'Hotspots & coupling',
  navLinks:   [['#fanin','Fan-in'],['#godclass','God classes'],['#cycles','Cycles'],['#matrix','Matrix'],['#ranking','Risk ranking']],
  bodyHtml,
});

writeReport(html, 'hotspots.html', runDir, outArg);
