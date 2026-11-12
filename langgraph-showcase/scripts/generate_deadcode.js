#!/usr/bin/env node
'use strict';

/**
 * generate_deadcode.js
 *
 * Dead code & waste report: groups dead_code[] by class with confidence badges,
 * renders performance_findings[], explains the conservative-detection caveat.
 *
 * Usage:
 *   node scripts/generate_deadcode.js <run_dir>
 *   node scripts/generate_deadcode.js <run_dir> <out>
 */

const fs   = require('fs');
const path = require('path');
const {
  esc, countBy, riskBadge, confidenceBadge, callout, tableCaption,
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

const projectName = path.basename(meta.source_path || 'unknown');
const nodes  = ir.nodes || [];
const nodeMap = Object.fromEntries(nodes.map(n => [n.id, n]));
const deadCode  = ir.dead_code || [];
const perfFinds = ir.performance_findings || [];

const { contexts } = normaliseBCM(bcmRaw);

// Build node_id → context map
const nodeToCtx = {};
for (const ctx of contexts) {
  for (const nid of (ctx.node_ids || [])) nodeToCtx[nid] = ctx.name;
}

// Group dead-code findings by class name (node_id format: method.ClassName.methodName)
const byClass = {};
for (const d of deadCode) {
  const parts = d.node_id.split('.');
  const cls   = parts.length >= 2 ? parts[1] : d.node_id;
  if (!byClass[cls]) byClass[cls] = [];
  byClass[cls].push(d);
}
const classesSorted = Object.entries(byClass).sort((a, b) => b[1].length - a[1].length);

// Confidence breakdown
const confBreakdown = countBy(deadCode, d => (d.confidence || 'LOW').toUpperCase());

// Severity badge for perf findings
function severityStyle(s) {
  const styles = {
    CRITICAL: 'background:#FDECEA;color:#C0392B;border:1px solid #F5C6C2',
    HIGH:     'background:#FDECEA;color:#C0392B;border:1px solid #F5C6C2',
    MEDIUM:   'background:#FEF3E2;color:#A0522D;border:1px solid #F5DFB8',
    LOW:      'background:#EAF4EA;color:#2E7D32;border:1px solid #B8DDB8',
  };
  const style = styles[(s || '').toUpperCase()] || styles.LOW;
  return `<span style="display:inline-block;padding:2px 7px;border-radius:2px;font-family:'IBM Plex Mono',monospace;font-size:11px;text-transform:uppercase;${style}">${esc(s || 'LOW')}</span>`;
}

// ── Render dead code ──────────────────────────────────────────────────────────

const deadCodeContent = deadCode.length === 0
  ? `<div style="background:#EAF4EA;border-left:3px solid #B8DDB8;padding:16px 20px;font-family:'IBM Plex Mono',monospace;font-size:12px;color:#2E7D32">
      ✓ No dead code findings in this run.
    </div>`
  : `
  ${tableCaption(`DEAD CODE BY CLASS (${classesSorted.length} classes, ${deadCode.length} total findings)`)}
  <table>
    <thead>
      <tr><th>Class</th><th>Methods flagged</th><th>Confidence</th><th>Context</th></tr>
    </thead>
    <tbody>
      ${classesSorted.map(([cls, items]) => {
        const ctx = nodeToCtx[`prog.${cls.toLowerCase()}`] || '—';
        const conf = (items[0].confidence || 'LOW').toUpperCase();
        return `<tr>
          <td style="font-weight:600">${esc(cls)}</td>
          <td>${esc(items.length)}</td>
          <td>${confidenceBadge(conf)}</td>
          <td style="color:#91969C">${esc(ctx)}</td>
        </tr>`;
      }).join('')}
    </tbody>
  </table>
  <details style="margin-top:16px">
    <summary style="cursor:pointer;font-family:'IBM Plex Mono',monospace;font-size:12px;color:#91969C;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:8px">
      Expand full method list
    </summary>
    <table style="margin-top:8px">
      <thead><tr><th>Node ID</th><th>Reason</th><th>Confidence</th></tr></thead>
      <tbody>${deadCode.map(d =>
        `<tr>
          <td style="font-family:'IBM Plex Mono',monospace;font-size:11px">${esc(d.node_id)}</td>
          <td style="color:#91969C;font-size:11px">${esc(d.reason)}</td>
          <td>${confidenceBadge((d.confidence || 'LOW').toUpperCase())}</td>
        </tr>`
      ).join('')}</tbody>
    </table>
  </details>`;

// ── Render performance findings ───────────────────────────────────────────────

const perfContent = perfFinds.length === 0
  ? `<div style="background:#EAF4EA;border-left:3px solid #B8DDB8;padding:16px 20px;font-family:'IBM Plex Mono',monospace;font-size:12px;color:#2E7D32">
      ✓ No performance findings in this run.
    </div>`
  : `
  ${tableCaption(`PERFORMANCE FINDINGS (${perfFinds.length})`)}
  <table>
    <thead>
      <tr><th>Node</th><th>Pattern</th><th>Severity</th><th>Remediation</th></tr>
    </thead>
    <tbody>
      ${perfFinds.map(f => {
        const node = nodeMap[f.node_id] || {};
        const name = node.name || f.node_id;
        return `<tr>
          <td style="font-weight:600">${esc(name)}<br><span style="color:#91969C;font-size:11px">${esc(f.node_id)}</span></td>
          <td><code>${esc(f.pattern)}</code></td>
          <td>${severityStyle(f.severity)}</td>
          <td style="color:#666;font-size:12px">${esc(f.remediation)}</td>
        </tr>`;
      }).join('')}
    </tbody>
  </table>`;

const bodyHtml = `
<div class="metric-row" style="grid-template-columns:repeat(4,1fr)">
  <div class="metric-card"><div class="metric-value">${esc(deadCode.length)}</div><div class="metric-label">Dead code flags</div></div>
  <div class="metric-card"><div class="metric-value">${esc(classesSorted.length)}</div><div class="metric-label">Classes affected</div></div>
  <div class="metric-card"><div class="metric-value">${esc(perfFinds.length)}</div><div class="metric-label">Perf findings</div></div>
  <div class="metric-card">
    <div class="metric-value" style="font-size:20px;margin-top:8px">
      ${confBreakdown.HIGH ? `${confBreakdown.HIGH} HIGH` : confBreakdown.MEDIUM ? `${confBreakdown.MEDIUM} MED` : 'ALL LOW'}
    </div>
    <div class="metric-label">Confidence</div>
  </div>
</div>

<section id="caveat">
  <h1 class="chapter">⚠ How to interpret these results</h1>
  <hr class="chapter-rule">
  ${callout(`<strong>Detection is conservative.</strong> The dead code detector flags methods with
    no inbound CALLS edges AND no outbound edges in the IR graph. CALLS edges are tracked at the
    <em>file level</em> — not at the method level. This means every individual method appears
    "isolated" even when it is called from within the same file or by a framework via reflection
    (Spring, JPA, Jackson). The ${esc(deadCode.length)} findings below are almost certainly
    dominated by getter/setter accessor methods that Spring reads reflectively and methods called
    within-file that the static analysis cannot see. <strong>Do not prune based on these flags alone.</strong>`, 'warn')}
  <p>The actionable signals are: (1) <strong>zero-fan-in PROGRAM nodes</strong> (entire files
  never called from another file) — see the Hotspots report; (2) duplicated method names across
  classes (e.g. <code>buildCommArea</code> appearing in both the controller and the monitor
  service); (3) classes whose method counts are entirely getter/setter boilerplate — candidates
  for simplification to plain data models in the target language.</p>
</section>

<section id="deadcode">
  <h1 class="chapter">Dead code findings</h1>
  <hr class="chapter-rule">
  <p><strong>${esc(deadCode.length)}</strong> method-level dead code flag${deadCode.length !== 1 ? 's' : ''},
  all with <strong>LOW</strong> confidence. Grouped by class, sorted by flag count.</p>
  ${deadCodeContent}
</section>

<section id="perf">
  <h1 class="chapter">Performance findings</h1>
  <hr class="chapter-rule">
  <p>Anti-patterns detected by the Observer's performance scanner
  (e.g. SQL_IN_LOOP, FILE_OPEN_IN_LOOP). These carry higher confidence than dead-code flags
  as they are based on explicit structural patterns in the IR.</p>
  ${perfContent}
</section>
`;

const html = htmlShell({
  title:      `${projectName} — Dead code & waste`,
  projectName,
  reportType: 'Dead code & waste',
  navLinks:   [['#caveat','⚠ Read first'],['#deadcode','Dead code'],['#perf','Perf findings']],
  bodyHtml,
});

writeReport(html, 'dead-code.html', runDir, outArg);
