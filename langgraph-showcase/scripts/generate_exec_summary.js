#!/usr/bin/env node
'use strict';

/**
 * generate_exec_summary.js
 *
 * Generates a one-page executive summary for non-technical stakeholders.
 *
 * Usage:
 *   node scripts/generate_exec_summary.js <run_dir>
 *   node scripts/generate_exec_summary.js <run_dir> <out>
 */

const fs   = require('fs');
const path = require('path');
const {
  esc, countBy, riskBadge, severityBadge, callout,
  normaliseBCM, htmlShell, writeReport,
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

const meta     = read('run_meta.json');
const ir       = readOpt('ir_graph.json');
const seam     = readOpt('seam.json');
const wsData   = readOpt('work_streams.json');
const tnas     = readOpt('tnas.json');
const bcmRaw   = readOpt('bounded_context_map.json');

// Maps internal lang codes → display names. Keys are lowercase, digits kept.
const LANG_DISPLAY = {
  java: 'Java', java8: 'Java 8', java11: 'Java 11', java17: 'Java 17', java21: 'Java 21',
  kotlin: 'Kotlin', kotlin19: 'Kotlin 1.9',
  python: 'Python', python3: 'Python 3', python39: 'Python 3.9', python311: 'Python 3.11',
  typescript: 'TypeScript', javascript: 'JavaScript',
  csharp: 'C#', 'c#': 'C#', dotnet: '.NET', dotnet8: '.NET 8',
  go: 'Go', golang: 'Go',
  rust: 'Rust', scala: 'Scala', clojure: 'Clojure',
  cobol: 'COBOL', cobol85: 'COBOL 85', rpg: 'RPG', fortran: 'Fortran',
  ruby: 'Ruby', php: 'PHP', swift: 'Swift', dart: 'Dart',
};
function formatLang(code) {
  if (!code || code === '?') return code || '?';
  return LANG_DISPLAY[code.toLowerCase()] || code;
}

// Derive a human-readable project name by stripping standard build-tool path
// suffixes (src/main/java etc.) before taking the basename, then removing any
// leading language prefix (e.g. "java-natwest..." → "Natwest Fraud Detection").
function deriveProjectName(sourcePath, sourceLang) {
  const genericSuffixes = [
    '/src/main/java', '/src/main/kotlin', '/src/main/python',
    '/src/main', '/src/test/java', '/src/test/kotlin', '/src',
  ];
  let p = (sourcePath || '').replace(/\\/g, '/');
  for (const suffix of genericSuffixes) {
    if (p.endsWith(suffix)) { p = p.slice(0, -suffix.length); break; }
  }
  let name = p.split('/').filter(Boolean).pop() || 'unknown';
  const lang = (sourceLang || '').replace(/\d+$/, '').toLowerCase();
  if (lang && (name.toLowerCase().startsWith(lang + '-') || name.toLowerCase().startsWith(lang + '_'))) {
    name = name.slice(lang.length + 1);
  }
  return name.split(/[-_]/).filter(Boolean).map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
}
const projectName = deriveProjectName(meta.source_path, meta.source_lang);
const sourceLang  = meta.source_lang || '?';
const targetLang  = meta.target_lang || '?';
// Full report title: "NatWest Fraud Detection — Java 21 to Python 3"
const reportTitle = targetLang && targetLang !== '?'
  ? `${projectName} — ${formatLang(sourceLang)} to ${formatLang(targetLang)}`
  : projectName;

const { contexts, crossContextCalls } = normaliseBCM(bcmRaw);
const nodes  = ir ? (ir.nodes || []) : [];
const seams  = seam ? (seam.seams || []) : [];
const streams = wsData ? (wsData.work_streams || []) : [];

const nodeTypes  = countBy(nodes, n => n.type);
const classCount = nodeTypes.DATA_STRUCTURE || 0;
const fileCount  = nodeTypes.PROGRAM || 0;
const procCount  = nodeTypes.PROCEDURE || 0;
const fieldCount = nodeTypes.DATA_ITEM || 0;

const totalSeamPts = wsData ? (wsData.total_story_points || 0) : (seam ? (seam.total_story_points || 0) : 0);

const fitnessObj    = tnas ? (tnas.fitness_suite || {}) : {};
const fitnessFns    = Array.isArray(fitnessObj.functions) ? fitnessObj.functions : [];
const _FITNESS_META = new Set(['sha','created_at','produced_by','functions','target_language','intended_commit_path']);
const fitnessDims   = (typeof fitnessObj === 'object' && !Array.isArray(fitnessObj))
  ? Object.entries(fitnessObj).filter(([k, v]) => typeof v === 'string' && !_FITNESS_META.has(k))
  : [];
const blockingCount = fitnessFns.filter(f => f.severity === 'BLOCKING').length;

const deadCodeCount = ir ? (ir.dead_code || []).length : 0;
const perfFindCount = ir ? (ir.performance_findings || []).length : 0;

// TNAS / BCM discrepancy check
const tnasSummary = tnas ? (tnas.summary || '') : '';
const tnasMentionsZero = tnasSummary.includes('0 bounded context');
const hasContexts = contexts.length > 0;
const discrepancy = tnasMentionsZero && hasContexts;

// Waves breakdown — only count streams that carry actual work
const wavesBySeq = {};
for (const s of streams) {
  if (!((s.story_points || 0) > 0 || (s.seam_count || 0) > 0)) continue;
  const q = s.seq || 1;
  wavesBySeq[q] = wavesBySeq[q] || { count: 0, points: 0 };
  wavesBySeq[q].count++;
  wavesBySeq[q].points += s.story_points || 0;
}
const waveCount = Object.keys(wavesBySeq).length;
const wavesRows = Object.entries(wavesBySeq)
  .sort(([a], [b]) => Number(a) - Number(b))
  .map(([seq, { count, points }]) =>
    `<tr><td>Wave ${esc(seq)}</td><td>${esc(count)} parallel stream${count !== 1 ? 's' : ''}</td><td>${esc(points)} pts</td></tr>`
  ).join('');

// Fitness rules table — support both old array format and new object format
const fitnessRowsLegacy = fitnessFns.map(fn =>
  `<tr>
    <td style="font-weight:600">${esc(fn.name)}</td>
    <td>${severityBadge(fn.severity)}</td>
    <td style="color:#666">${esc(fn.rationale)}</td>
  </tr>`
).join('');

function dimSeverityBadge(val) {
  const first = (val || '').trim().split(/[\s.]/)[0];
  const s = first === 'High' ? 'SATISFIED' : first === 'Medium' ? 'PARTIAL' : first === 'Low' ? 'AT RISK' : 'UNKNOWN';
  return severityBadge(s);
}

const fitnessRowsDims = fitnessDims.map(([dimKey, dimVal]) => {
  const title = dimKey.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
  return `<tr>
    <td style="font-weight:600">${esc(title)}</td>
    <td>${dimSeverityBadge(dimVal)}</td>
    <td style="color:#666">${esc(dimVal)}</td>
  </tr>`;
}).join('');

const fitnessRows = (fitnessRowsLegacy + fitnessRowsDims) || '<tr><td colspan="3" style="color:#91969C">No fitness functions in this run.</td></tr>';

// Pre-Phase Security Signal from ir_graph.security_hints
const securityHints = ir ? (ir.security_hints || null) : null;
const securitySignalHtml = securityHints ? (() => {
  const riskStyle = securityHints.source_architecture_risk === 'HIGH'
    ? 'background:#FDECEA;color:#C0392B;border:1px solid #F5C6C2'
    : securityHints.source_architecture_risk === 'MEDIUM'
    ? 'background:#FEF3E2;color:#A0522D;border:1px solid #F5DFB8'
    : 'background:#EAF4EA;color:#2E7D32;border:1px solid #B8DDB8';
  const riskBadgeHtml = `<span style="display:inline-block;padding:2px 7px;border-radius:2px;font-family:'IBM Plex Mono',monospace;font-size:11px;text-transform:uppercase;letter-spacing:0.04em;${riskStyle}">${esc(securityHints.source_architecture_risk || 'UNKNOWN')}</span>`;
  const topFindings = securityHints.top_findings || [];
  const findingsList = topFindings.length
    ? `<details style="margin-top:8px"><summary style="cursor:pointer;font-size:12px;font-family:'IBM Plex Mono',monospace">Top findings (${topFindings.length})</summary>
        <ul style="font-size:12px;margin:6px 0 0;padding-left:18px">
          ${topFindings.map(f => `<li><strong>${esc(f.id || '')}</strong>${f.title ? ` — ${esc(f.title)}` : ''}${f.severity ? ` [${esc(f.severity)}]` : ''}${f.location ? ` <code>${esc(f.location)}</code>` : ''}</li>`).join('')}
        </ul>
       </details>`
    : '';
  return `
<section id="security-signal">
  <h1 class="chapter">Pre-Phase Security Signal</h1>
  <hr class="chapter-rule">
  <p>Static analysis of the source architecture before LLM phases ran identified
  <strong>${esc(securityHints.finding_count || topFindings.length)}</strong> security finding${(securityHints.finding_count || topFindings.length) !== 1 ? 's' : ''}
  with a source architecture risk of ${riskBadgeHtml}.</p>
  ${findingsList}
</section>`;
})() : '';

// Context confidence table
const ctxRows = contexts.map(ctx => {
  const conf = typeof ctx.confidence === 'number'
    ? `${Math.round(ctx.confidence * 100)}%`
    : String(ctx.confidence || '?');
  return `<tr>
    <td style="font-weight:600">${esc(ctx.name)}</td>
    <td>${esc(conf)}</td>
    <td>${esc((ctx.node_ids || []).length)} nodes</td>
  </tr>`;
}).join('') || '<tr><td colspan="3" style="color:#91969C">No bounded contexts identified.</td></tr>';

const seamsRows = [
  ['Object seams',        seam ? (seam.seam_counts && seam.seam_counts.object)        || 0 : 0],
  ['Preprocessing seams', seam ? (seam.seam_counts && seam.seam_counts.preprocessing) || 0 : 0],
  ['Message seams', seam ? (seam.seam_counts && seam.seam_counts.message) || 0 : 0],
  ['Boundary seams',      seam ? (seam.seam_counts && seam.seam_counts.boundary)      || 0 : 0],
  ['Link seams',          seam ? (seam.seam_counts && seam.seam_counts.link)          || 0 : 0],
].filter(([, n]) => n > 0)
 .map(([t, n]) => `<tr><td>${esc(t)}</td><td>${esc(n)}</td></tr>`).join('');

const bodyHtml = `
<div class="metric-row" style="grid-template-columns:repeat(4,1fr)">
  <div class="metric-card"><div class="metric-value">${esc(fileCount)}</div><div class="metric-label">${esc(formatLang(sourceLang))} files</div></div>
  <div class="metric-card"><div class="metric-value">${esc(classCount)}</div><div class="metric-label">Classes</div></div>
  <div class="metric-card"><div class="metric-value">${esc(contexts.length)}</div><div class="metric-label">Domains</div></div>
  <div class="metric-card"><div class="metric-value">${esc(totalSeamPts)} <span style="font-size:22px">pts</span></div><div class="metric-label">Story points</div></div>
</div>
<div class="metric-row" style="grid-template-columns:repeat(4,1fr);margin-top:0">
  <div class="metric-card"><div class="metric-value">${esc(procCount)}</div><div class="metric-label">Methods</div></div>
  <div class="metric-card"><div class="metric-value">${esc(fieldCount)}</div><div class="metric-label">Fields</div></div>
  <div class="metric-card"><div class="metric-value">${esc(waveCount)}</div><div class="metric-label">Migration waves</div></div>
  <div class="metric-card"><div class="metric-value">${esc(blockingCount)}</div><div class="metric-label">Blocking rules</div></div>
</div>

<section id="overview">
  <h1 class="chapter">What is this system?</h1>
  <hr class="chapter-rule">
  <p>
    <strong>${esc(projectName)}</strong> is a <strong>${esc(sourceLang)}</strong> codebase
    being analysed for migration to <strong>${esc(targetLang)}</strong>. It contains
    <strong>${esc(fileCount)}</strong> source files, <strong>${esc(classCount)}</strong> classes,
    <strong>${esc(procCount)}</strong> methods, and <strong>${esc(fieldCount)}</strong> fields
    (${esc(nodes.length)} nodes total in the intermediate representation graph).
  </p>
  <p>
    The codebase has been partitioned into <strong>${esc(contexts.length)}</strong> bounded context${contexts.length !== 1 ? 's' : ''}
    by the Cartographer agent. ${crossContextCalls.length > 0 ? `There are <strong>${esc(crossContextCalls.length)}</strong> cross-context call relationships that define the seam boundaries.` : ''}
  </p>
  ${tnasSummary && !discrepancy ? `<p style="color:#666;font-style:italic">${esc(tnasSummary)}</p>` : ''}
  ${discrepancy ? callout(`<strong>Data quality note:</strong> The TNAS architect summary states "0 bounded contexts migrated" but the Cartographer identified ${contexts.length}. The fitness functions, seam catalogue, and work streams are valid; the TNAS service list and context decisions were not populated in this run. Regenerate TNAS after reviewing and approving the bounded context map.`, 'warn') : ''}
</section>

<section id="domains">
  <h1 class="chapter">Domain structure</h1>
  <hr class="chapter-rule">
  <p>The following bounded contexts were identified. Confidence reflects agreement across the
  three Cartographer analysis passes (file-path, semantic, LLM-voted).</p>
  <table>
    <thead><tr><th>Context</th><th>Confidence</th><th>Size</th></tr></thead>
    <tbody>${ctxRows}</tbody>
  </table>
  ${crossContextCalls.length > 0 ? `
  <p>Cross-context dependencies (caller → callee): ${crossContextCalls.map(([s, t]) => `<strong>${esc(s)}</strong> → <strong>${esc(t)}</strong>`).join(' &nbsp;·&nbsp; ')}.</p>
  ` : ''}
</section>

<section id="migration">
  <h1 class="chapter">Migration scope</h1>
  <hr class="chapter-rule">
  <p>The analysis identified <strong>${esc(seams.length)}</strong> migration seam${seams.length !== 1 ? 's' : ''} totalling
  <strong>${esc(totalSeamPts)} story points</strong>. Seams are the structural joints that must be
  cut and interfaced before the target ${esc(targetLang)} service can be assembled safely.</p>
  ${seamsRows ? `<table><thead><tr><th>Seam type</th><th>Count</th></tr></thead><tbody>${seamsRows}</tbody></table>` : ''}
  ${waveCount > 0 ? `
  <p>Work is organised into <strong>${esc(waveCount)} sequential wave${waveCount !== 1 ? 's' : ''}</strong> of parallel streams:</p>
  <table><thead><tr><th>Wave</th><th>Parallelism</th><th>Effort</th></tr></thead>
  <tbody>${wavesRows}</tbody></table>
  ` : ''}
</section>

<section id="rules">
  <h1 class="chapter">Architectural rules</h1>
  <hr class="chapter-rule">
  <p>The following <strong>${esc(blockingCount)} BLOCKING</strong> fitness function${blockingCount !== 1 ? 's' : ''} must pass
  on every pull request to the ${esc(targetLang)} target before it is accepted. They are
  enforced in CI from day one and gate every PR for the duration of the engagement.</p>
  <table>
    <thead><tr><th>Rule</th><th>Severity</th><th>Rationale</th></tr></thead>
    <tbody>${fitnessRows}</tbody>
  </table>
</section>

${deadCodeCount + perfFindCount > 0 ? `
<section id="findings">
  <h1 class="chapter">Static analysis findings</h1>
  <hr class="chapter-rule">
  <p><strong>${esc(deadCodeCount)}</strong> dead-code flag${deadCodeCount !== 1 ? 's' : ''} and
  <strong>${esc(perfFindCount)}</strong> performance finding${perfFindCount !== 1 ? 's' : ''} were produced.
  See the <em>Dead Code &amp; Waste</em> report for detail and caveats — most dead-code flags
  are conservative (getter/setter methods invisible to static CALLS analysis).</p>
</section>
` : ''}

${securitySignalHtml}
`;

const html = htmlShell({
  title:       `${reportTitle} — Executive summary`,
  projectName: reportTitle,
  reportType:  'Executive summary',
  navLinks:    [['#overview','Overview'],['#domains','Domains'],['#migration','Migration'],['#rules','Rules'],['#security-signal','Security']],
  bodyHtml,
});

writeReport(html, 'executive-summary.html', runDir, outArg);
