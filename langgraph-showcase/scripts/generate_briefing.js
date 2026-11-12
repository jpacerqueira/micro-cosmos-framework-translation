#!/usr/bin/env node
'use strict';

/**
 * generate_briefing.js
 *
 * Reads five pipeline output files from a run directory and writes a single
 * self-contained HTML migration-briefing report.
 *
 * Usage:
 *   node scripts/generate_briefing.js <run_dir>          (write to run_dir)
 *   node scripts/generate_briefing.js <run_dir> <out>    (write to out path)
 */

const fs   = require('fs');
const path = require('path');

// ── Resolve directories ────────────────────────────────────────────────────────

const args   = process.argv.slice(2);
const runDir = args[0] ? path.resolve(args[0]) : process.cwd();
const outArg = args[1] ? path.resolve(args[1]) : null;

function read(name) {
  const p = path.join(runDir, name);
  if (!fs.existsSync(p)) throw new Error(`Required file not found: ${p}`);
  return JSON.parse(fs.readFileSync(p, 'utf8'));
}

const meta     = read('run_meta.json');
const bcm      = read('bounded_context_map.json');
const tnas     = read('tnas.json');
const wsData   = read('work_streams.json');
const seamData = read('seam.json');

function readOptional(name) {
  const p = path.join(runDir, name);
  if (!fs.existsSync(p)) return null;
  return JSON.parse(fs.readFileSync(p, 'utf8'));
}
const irGraph = readOptional('ir_graph.json');

// ── Data extraction ────────────────────────────────────────────────────────────

const projectName = path.basename(meta.source_path);
const sourceLang  = meta.source_lang;
const targetLang  = meta.target_lang;
const streams     = wsData.work_streams || wsData.streams || [];
const seams       = seamData.seams || [];
const contexts    = bcm.contexts || [];
// Support both old format (name) and new format (service_id)
const services    = (tnas.services || []).map(s => ({
  ...s,
  service_id: s.service_id || s.name,
}));
const fitnessObj  = tnas.fitness_suite || {};
// Support both old array format (functions[]) and new object format ({ dimName: "text" })
const fitnessFns  = Array.isArray(fitnessObj.functions) ? fitnessObj.functions : [];
const _FITNESS_META = new Set(['sha','created_at','produced_by','functions','target_language','intended_commit_path']);
const fitnessDims = (typeof fitnessObj === 'object' && !Array.isArray(fitnessObj))
  ? Object.entries(fitnessObj).filter(([k, v]) => typeof v === 'string' && !_FITNESS_META.has(k))
  : [];
const archNotes   = tnas.architectural_notes || [];
const migrationRationale = tnas.migration_sequence_rationale || '';

const totalSeams   = seams.length;
const streamCount  = streams.length;
const contextCount = contexts.length;
const totalPoints  = seams.reduce((sum, s) => sum + ((s.work && s.work.story_points) || 0), 0);
const riskCounts   = { HIGH: 0, MEDIUM: 0, LOW: 0 };
services.forEach(s => {
  const r = (s.migration_risk || '').toUpperCase();
  if (r in riskCounts) riskCounts[r]++;
});

// Lookup helpers
const serviceByContext  = Object.fromEntries(services.map(s => [s.service_id, s]));
const decisionByContext = Object.fromEntries(
  (tnas.context_decisions || []).map(d => [d.context, d])
);
const streamById = Object.fromEntries(streams.map(s => [s.id, s]));

// ── Validation assertions ─────────────────────────────────────────────────────

console.assert(streams.length > 0,    'No streams found in work_streams.json');
console.assert(seams.length > 0,      'No seams found in seam.json');
console.assert(contexts.length > 0,   'No contexts found in bounded_context_map.json');
console.assert(fitnessFns.length > 0 || fitnessDims.length > 0, 'No fitness functions found in tnas.json');
console.assert(totalPoints > 0,       'Zero story points across all seams');

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
  return `<span style="display:inline-block;padding:2px 7px;border-radius:3px;font-family:'IBM Plex Mono',monospace;font-size:11px;text-transform:uppercase;letter-spacing:0.04em;${style}">${esc(risk || 'LOW')}</span>`;
}

function statLine(...parts) {
  return `<p class="stat-line">${parts.map(esc).join(' · ')}</p>`;
}

function cap(text, maxSentences) {
  if (!text) return '';
  const sentences = text.match(/[^.!?]+[.!?]+/g) || [text];
  return sentences.slice(0, maxSentences).join(' ').trim();
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
}

*, *::before, *::after { box-sizing: border-box; }

body {
  background: var(--color-bg);
  color: var(--color-dark);
  font-family: 'Inter Tight', sans-serif;
  font-size: 16px;
  line-height: 1.6;
  margin: 0;
  padding: 0;
}

/* ── Navigation ── */
.nav {
  position: sticky;
  top: 0;
  z-index: 100;
  background: var(--color-white);
  border-bottom: 1px solid var(--color-sage);
  display: flex;
  align-items: center;
  padding: 0 32px;
  height: 52px;
  gap: 24px;
}
.nav-brand {
  font-family: 'Instrument Serif', serif;
  font-size: 18px;
  color: var(--color-dark);
  text-decoration: none;
  flex-shrink: 0;
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
  letter-spacing: 0.08em;
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
}
.download-btn:hover { background: #2D3535; }

/* ── Document ── */
.document {
  max-width: 860px;
  margin: 0 auto;
  padding: 48px 40px 96px;
}

/* ── Cover ── */
.cover {
  padding-bottom: 64px;
  border-bottom: 1px solid var(--color-sage);
  margin-bottom: 64px;
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
  font-size: 52px;
  font-weight: 400;
  color: var(--color-dark);
  line-height: 1.1;
  margin: 0 0 16px;
}
.cover-rule {
  width: 48px;
  height: 2px;
  background: var(--color-accent);
  margin: 0 0 20px;
}
.cover-subtitle {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 14px;
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

/* ── Chapter headings (H1) ── */
h1.chapter {
  font-family: 'Instrument Serif', serif;
  font-size: 36px;
  font-weight: 400;
  color: var(--color-dark);
  margin: 64px 0 8px;
  line-height: 1.2;
}
.chapter-rule {
  height: 2px;
  background: var(--color-accent);
  margin: 0 0 32px;
  border: none;
}

/* ── Section headings (H2) ── */
h2.section {
  font-family: 'Instrument Serif', serif;
  font-size: 24px;
  font-weight: 400;
  color: var(--color-dark);
  margin: 36px 0 4px;
  line-height: 1.3;
}

/* ── Body text ── */
p {
  margin: 0 0 16px;
  color: var(--color-dark);
}

/* ── Stat line ── */
.stat-line {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 12px;
  color: var(--color-muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  margin: 4px 0 12px;
}

/* ── Tables ── */
.table-caption {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 11px;
  color: var(--color-muted);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  margin: 32px 0 6px;
}
table {
  width: 100%;
  border-collapse: collapse;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 12px;
  margin: 0 0 32px;
}
thead tr {
  background: var(--color-dark);
  color: var(--color-white);
}
thead th {
  padding: 10px 12px;
  text-align: left;
  font-weight: 500;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
tbody tr {
  border-bottom: 1px solid var(--color-sage);
}
tbody td {
  padding: 9px 12px;
  vertical-align: top;
}
tbody tr:last-child {
  border-bottom: none;
}
tbody tr:hover {
  background: var(--color-sage);
}

/* ── Sage panels ── */
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

/* ── Module block (Appendix B) ── */
.module-block {
  border: 1px solid var(--color-sage);
  border-radius: 2px;
  margin: 20px 0 32px;
  padding: 0;
}
.module-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  background: var(--color-dark);
  color: var(--color-white);
  padding: 8px 14px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 13px;
  font-weight: 500;
}
.module-name { flex: 1; }
.module-counts {
  font-size: 11px;
  color: #9AA0A0;
  flex-shrink: 0;
  margin-left: 16px;
}
.module-deps {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 6px 14px;
  border-bottom: 1px solid var(--color-sage);
  font-family: 'IBM Plex Mono', monospace;
  font-size: 11px;
  flex-wrap: wrap;
}
.module-deps:last-of-type { border-bottom: none; }
.dep-label {
  color: var(--color-muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  flex-shrink: 0;
  min-width: 58px;
  padding-top: 2px;
}
.dep-pill {
  background: var(--color-sage);
  border: 1px solid #C5CBC5;
  border-radius: 2px;
  padding: 1px 6px;
  color: var(--color-dark);
  cursor: default;
}
.module-block h3.subsection,
.module-block .fields-grid,
.module-block table,
.module-block > p {
  margin-left: 14px;
  margin-right: 14px;
}

/* ── Sub-section headings (H3) ── */
h3.subsection {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 14px;
  font-weight: 500;
  color: var(--color-dark);
  margin: 28px 0 4px;
  display: flex;
  align-items: center;
  gap: 8px;
}

/* ── Kind / modifier badges ── */
.badge {
  display: inline-block;
  padding: 1px 6px;
  border-radius: 2px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 10px;
  font-weight: 500;
  text-transform: lowercase;
  letter-spacing: 0.03em;
  vertical-align: middle;
}
.badge-class     { background:#E8EAF6; color:#3949AB; border:1px solid #C5CAE9; }
.badge-interface { background:#E0F2F1; color:#00695C; border:1px solid #B2DFDB; }
.badge-enum      { background:#FFF3E0; color:#E65100; border:1px solid #FFCC80; }
.badge-async     { background:#F3E5F5; color:#6A1B9A; border:1px solid #E1BEE7; }
.badge-private   { background:#FAFAFA; color:#616161; border:1px solid #E0E0E0; }

/* ── Fields panel ── */
.fields-grid {
  display: grid;
  grid-template-columns: minmax(140px,auto) 1fr auto;
  gap: 0;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 11px;
  border: 1px solid var(--color-sage);
  margin: 8px 0 16px;
}
.fields-grid-header {
  background: var(--color-sage);
  color: var(--color-muted);
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  padding: 5px 10px;
  border-bottom: 1px solid #C5CBC5;
}
.fields-grid-cell {
  padding: 4px 10px;
  border-bottom: 1px solid var(--color-sage);
  color: var(--color-dark);
}
.fields-grid-cell:last-child, .fields-grid-header:last-child {
  color: var(--color-muted);
  text-align: center;
}
.fields-grid-row:last-child .fields-grid-cell {
  border-bottom: none;
}

/* ── Print ── */
@media print {
  .nav { display: none; }
  h1.chapter { page-break-before: always; }
  .cover { page-break-after: always; }
}
`.trim();

// ── Section builders ──────────────────────────────────────────────────────────

function buildCover() {
  return `
<div class="cover">
  <p class="cover-eyebrow">Migration readiness report</p>
  <h1 class="cover-title">${esc(projectName)}</h1>
  <div class="cover-rule"></div>
  <p class="cover-subtitle">${esc(sourceLang)} → ${esc(targetLang)}</p>
  <p class="cover-confidential">Micro-Cosmos · CONFIDENTIAL</p>
</div>`.trim();
}

function buildNav() {
  return `
<nav class="nav">
  <a class="nav-brand" href="#">Micro-Cosmos</a>
  <ul class="nav-links">
    <li><a href="#executive-summary">Executive Summary</a></li>
    <li><a href="#contexts">Contexts</a></li>
    <li><a href="#constraints">Constraints</a></li>
    <li><a href="#streams">Streams</a></li>
    <li><a href="#appendix">Appendix A</a></li>
    <li><a href="#appendix-functions">Appendix B</a></li>
  </ul>
  <button onclick="window.print()" class="download-btn">↓ Download PDF</button>
</nav>`.trim();
}

function buildExecutiveSummary() {
  const highRiskServices = services.filter(s => (s.migration_risk || '').toUpperCase() === 'HIGH');
  const riskParagraph = highRiskServices.length > 0
    ? highRiskServices.map(s => `<strong>${esc(s.service_id)}</strong>: ${esc(s.risk_reason)}`).join(' ')
    : 'No high-risk contexts were identified.';

  const rows = [
    ['Total seams', totalSeams],
    ['Total story points', totalPoints],
    ['Bounded contexts', contextCount],
    ['Work streams', streamCount],
    ['High-risk contexts', riskCounts.HIGH],
    ['Medium-risk contexts', riskCounts.MEDIUM],
    ['Low-risk contexts', riskCounts.LOW],
  ].map(([metric, value]) => `
      <tr><td>${esc(metric)}</td><td>${esc(value)}</td></tr>`).join('');

  return `
<section id="executive-summary">
  <h1 class="chapter">Executive Summary</h1>
  <hr class="chapter-rule">
  <p>
    This report covers the migration readiness assessment of <strong>${esc(projectName)}</strong>,
    a ${esc(sourceLang)} codebase targeted for migration to ${esc(targetLang)}.
    The assessment identified ${esc(totalSeams)} refactoring seams across ${esc(contextCount)}
    bounded contexts, representing ${esc(totalPoints)} story points distributed across
    ${esc(streamCount)} dependency-ordered work streams.
  </p>
  <p>${riskParagraph}</p>
  <p class="table-caption">Table 1 — Migration Scope Summary</p>
  <table>
    <thead><tr><th>Metric</th><th>Value</th></tr></thead>
    <tbody>${rows}
    </tbody>
  </table>
</section>`.trim();
}

function buildContexts() {
  const contextSections = contexts.map(ctx => {
    const svc      = serviceByContext[ctx.name] || {};
    const decision = decisionByContext[ctx.name] || {};
    const risk     = svc.migration_risk || 'LOW';
    const commStyle = decision.communication_style || 'sync-http';
    const nodeCount = (ctx.node_ids || []).length;
    const rationale = cap(ctx.rationale || '', 3);

    return `
  <h2 class="section">${esc(ctx.name)}</h2>
  <p>${esc(rationale)}</p>
  <p class="stat-line">
    ${esc(nodeCount)} nodes · ${riskBadge(risk)} · ${esc(commStyle)}
  </p>`;
  }).join('');

  const callRows = [...(bcm.cross_context_calls || [])]
    .sort((a, b) => String(a[0]).localeCompare(String(b[0])))
    .map(([src, tgt]) => `
      <tr><td>${esc(src)}</td><td>${esc(tgt)}</td></tr>`)
    .join('');

  return `
<section id="contexts">
  <h1 class="chapter">Bounded Context Map</h1>
  <hr class="chapter-rule">
  <p>
    Contexts were derived from the IR graph by file-path classification and CALLS-edge
    propagation — not by manual assignment. Each source file is assigned to exactly one
    context by a deterministic set of ordered path rules; child nodes (classes, methods,
    functions) inherit the context of their parent program node.
  </p>
  ${contextSections}
  <p class="table-caption">Table 2 — Cross-Context Call Relationships</p>
  <table>
    <thead><tr><th>Source</th><th>Target</th></tr></thead>
    <tbody>${callRows}
    </tbody>
  </table>
</section>`.trim();
}

function buildConstraints() {
  const fnSections = fitnessFns.map((fn, i) => {
    const label = `Constraint ${i + 1} — ${fn.id}`;
    return `
  <h2 class="section">${esc(fn.name)}</h2>
  <p>${esc(fn.description)}</p>
  <p>The rationale for this constraint is: ${esc(fn.rationale)}</p>
  <p class="table-caption">${esc(label)}</p>
  <div class="panel">${esc(fn.spec)}</div>`;
  }).join('');

  const dimSections = fitnessDims.map(([dimKey, dimVal], i) => {
    const title = dimKey.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
    const first = (dimVal || '').trim().split(/[\s.]/)[0];
    const statusStyle = first === 'High'
      ? 'background:#EAF4EA;color:#2E7D32;border:1px solid #B8DDB8'
      : first === 'Medium'
      ? 'background:#FEF3E2;color:#A0522D;border:1px solid #F5DFB8'
      : 'background:#FDECEA;color:#C0392B;border:1px solid #F5C6C2';
    const badge = `<span style="display:inline-block;padding:2px 7px;border-radius:2px;font-family:'IBM Plex Mono',monospace;font-size:11px;text-transform:uppercase;letter-spacing:0.04em;${statusStyle}">${esc(first === 'High' ? 'SATISFIED' : first === 'Medium' ? 'PARTIAL' : 'AT RISK')}</span>`;
    return `
  <h2 class="section">${esc(title)}</h2>
  <p>${badge} ${esc(dimVal)}</p>`;
  }).join('');

  const allFnSections = (fnSections + dimSections) || '<p>No fitness functions defined in this run.</p>';

  // Architectural notes collapsible section
  const archNotesHtml = archNotes.length
    ? `<details style="margin:24px 0">
        <summary style="cursor:pointer;font-family:'IBM Plex Mono',monospace;font-size:12px;text-transform:uppercase;letter-spacing:0.06em">Architectural Notes (${archNotes.length})</summary>
        ${archNotes.map(n => `
          <h3 style="font-size:14px;margin:16px 0 4px">${esc(n.concern || '')}</h3>
          ${n.placement ? `<div class="panel">${esc(n.placement)}</div>` : ''}
          ${n.seam_location ? `<p style="font-size:12px;color:#666">Seam: <code>${esc(n.seam_location)}</code></p>` : ''}`).join('')}
      </details>`
    : '';

  // Migration sequence rationale callout
  const rationale = migrationRationale
    ? `<div style="background:#EAF4EA;border-left:3px solid #2E7D32;padding:14px 18px;margin:20px 0;font-size:14px">
        <strong>Migration sequence rationale:</strong><br>${esc(migrationRationale)}
       </div>`
    : '';

  return `
<section id="constraints">
  <h1 class="chapter">Architectural Constraints</h1>
  <hr class="chapter-rule">
  <p>
    The following are BLOCKING fitness functions from the technology-neutral architecture
    specification. All constraints must pass before any migrated service is accepted into
    the target codebase. These rules are committed to the client CI pipeline on day one
    and gate every pull request for the duration of the engagement.
  </p>
  ${allFnSections}
  ${archNotesHtml}
  ${rationale}
</section>`.trim();
}

function buildStreams() {
  const sorted = [...streams].sort((a, b) => (a.seq || 0) - (b.seq || 0));

  const seqRows = sorted.map(s => {
    const depNames = (s.depends_on || [])
      .map(id => streamById[id] ? streamById[id].name : id)
      .join(', ') || '—';
    return `
      <tr>
        <td>${esc(s.seq)}</td>
        <td>${esc(s.name)}</td>
        <td>${esc(s.seam_count)}</td>
        <td>${esc(s.story_points)}</td>
        <td>${riskBadge(s.risk)}</td>
        <td>${esc(depNames)}</td>
      </tr>`;
  }).join('');

  const streamDetails = sorted.map(s => {
    const depNames = (s.depends_on || [])
      .map(id => streamById[id] ? streamById[id].name : id);
    const depLine = depNames.length > 0
      ? `<p>Depends on: ${esc(depNames.join(', '))}.</p>`
      : '';

    const typesPresent = s.seam_types_present || {};
    const typeParts = Object.entries(typesPresent)
      .map(([t, n]) => `${n} ${t}`)
      .join(', ');
    const typeBreakdown = typeParts
      ? `<p>Seam breakdown: ${esc(typeParts)}.</p>`
      : '';

    return `
  <h2 class="section">${esc(s.name)}</h2>
  <p>${esc(s.rationale)}</p>
  <p class="stat-line">
    ${esc(s.seam_count)} seams · ${esc(s.story_points)} pts · ${esc(s.dominant_effort)} effort · ${riskBadge(s.risk)}
  </p>
  ${depLine}
  ${typeBreakdown}`;
  }).join('');

  return `
<section id="streams">
  <h1 class="chapter">Migration Stream Plan</h1>
  <hr class="chapter-rule">
  <p>
    Streams must be executed in sequence order. Streams with no dependencies may run
    in parallel with other zero-dependency streams. Each stream boundary maps to a
    bounded context, ensuring that refactoring seams are resolved before their
    downstream consumers are migrated.
  </p>
  <p class="table-caption">Table 3 — Work Stream Execution Order</p>
  <table>
    <thead>
      <tr>
        <th>Seq</th>
        <th>Stream</th>
        <th>Seams</th>
        <th>Points</th>
        <th>Risk</th>
        <th>Depends on</th>
      </tr>
    </thead>
    <tbody>${seqRows}
    </tbody>
  </table>
  ${streamDetails}
</section>`.trim();
}

function buildAppendix() {
  const sorted = [...seams].sort((a, b) =>
    ((b.work && b.work.story_points) || 0) - ((a.work && a.work.story_points) || 0)
  );

  const rows = sorted.map(s => {
    const w = s.work || {};
    return `
      <tr>
        <td>${esc(s.id)}</td>
        <td>${esc(s.type)}</td>
        <td>${esc(s.location)}</td>
        <td>${esc(w.effort)}</td>
        <td>${esc(w.story_points)}</td>
        <td>${riskBadge(w.risk)}</td>
        <td>${esc(w.migration_phase)}</td>
      </tr>`;
  }).join('');

  return `
<section id="appendix">
  <h1 class="chapter">Appendix A — Seam Inventory</h1>
  <hr class="chapter-rule">
  <p class="table-caption">Table 4 — Seam Inventory (${esc(totalSeams)} seams)</p>
  <table>
    <thead>
      <tr>
        <th>ID</th>
        <th>Type</th>
        <th>Location</th>
        <th>Effort</th>
        <th>Points</th>
        <th>Risk</th>
        <th>Phase</th>
      </tr>
    </thead>
    <tbody>${rows}
    </tbody>
  </table>
</section>`.trim();
}

function buildFunctionAppendix() {
  if (!irGraph) return '';

  const irNodes = irGraph.nodes || [];
  const irEdges = irGraph.edges || [];
  const nodeById = Object.fromEntries(irNodes.map(n => [n.id, n]));

  // ── Index maps ────────────────────────────────────────────────────────────────
  const progToContext = {};
  for (const ctx of contexts) {
    for (const nid of (ctx.node_ids || [])) progToContext[nid] = ctx.name;
  }

  const progToClasses  = {};   // prog id → [class id]
  const progToFns      = {};   // prog id → [fn id]
  const classToMethods = {};   // class id → [method id]
  const progCallsOut   = {};   // prog id → [prog id] (modules it imports)
  const progCallsIn    = {};   // prog id → [prog id] (modules that import it)

  for (const e of irEdges) {
    const { source_id: src, target_id: tgt, type } = e;
    if (type === 'DEFINES') {
      if (src.startsWith('prog.') && tgt.startsWith('class.'))
        (progToClasses[src] = progToClasses[src] || []).push(tgt);
      else if (src.startsWith('prog.') && tgt.startsWith('fn.'))
        (progToFns[src] = progToFns[src] || []).push(tgt);
      else if (src.startsWith('class.') && tgt.startsWith('method.'))
        (classToMethods[src] = classToMethods[src] || []).push(tgt);
    } else if (type === 'CALLS' && src.startsWith('prog.') && tgt.startsWith('prog.')) {
      (progCallsOut[src] = progCallsOut[src] || []).push(tgt);
      (progCallsIn[tgt]  = progCallsIn[tgt]  || []).push(src);
    }
  }

  // ── Helpers ───────────────────────────────────────────────────────────────────
  function unique(arr) { return [...new Set(arr)]; }

  function kindBadge(kind) {
    const k = (kind || '').toLowerCase();
    const cls = k === 'class' ? 'badge-class' : k === 'interface' ? 'badge-interface' : 'badge-enum';
    return `<span class="badge ${cls}">${esc(k || 'type')}</span>`;
  }

  function modBadges(mods) {
    return (mods || '').split(',').map(m => m.trim()).filter(Boolean).map(m =>
      `<span class="badge badge-${m === 'async' ? 'async' : 'private'}">${esc(m)}</span>`
    ).join(' ');
  }

  function shortLoc(loc) {
    return (loc || '').replace(/^.*?\/([^/]+\/[^/]+)$/, '$1');
  }

  // Derive a readable module label from a prog id or its children's source locations
  function progLabel(progId, childIds) {
    // Try to get the file path from a child node
    for (const cid of (childIds || [])) {
      const n = nodeById[cid];
      if (n && n.source_location) {
        const loc = n.source_location.replace(/:\d+$/, '');
        const parts = loc.split('/');
        return parts.slice(-2).join('/');
      }
    }
    // Fall back to stripping the prog. prefix
    return progId.replace(/^prog\./, '').replace(/\./g, '/');
  }

  // Render a compact pill list of prog ids, converted to readable labels
  function renderProgList(progIds, allProgIds) {
    if (!progIds || progIds.length === 0) return '<span style="color:var(--color-muted)">—</span>';
    return progIds.map(pid => {
      const childIds = [...(progToClasses[pid] || []), ...(progToFns[pid] || [])];
      const label = progLabel(pid, childIds);
      const ctx = progToContext[pid];
      const title = ctx ? `${pid} (${ctx})` : pid;
      return `<span class="dep-pill" title="${esc(title)}">${esc(label)}</span>`;
    }).join(' ');
  }

  function renderInputs(inputs) {
    if (!inputs || inputs.length === 0) return '—';
    return inputs.map(i => {
      const opt = i.optional === 'true' ? '?' : '';
      const def = i.default ? ` = ${i.default}` : '';
      return `${esc(i.name)}${opt}: ${esc(i.type)}${esc(def)}`;
    }).join(', ');
  }

  function renderFieldsGrid(fields) {
    if (!fields || fields.length === 0) return '';
    const rows = fields.map(f => {
      const opt = f.optional === 'true' ? '?' : '';
      return `<div class="fields-grid-row" style="display:contents">
        <div class="fields-grid-cell">${esc(f.name)}${opt}</div>
        <div class="fields-grid-cell">${esc(f.type)}</div>
        <div class="fields-grid-cell">${f.optional === 'true' ? 'opt' : ''}</div>
      </div>`;
    }).join('');
    return `<div class="fields-grid">
      <div class="fields-grid-row" style="display:contents">
        <div class="fields-grid-header">Field</div>
        <div class="fields-grid-header">Type</div>
        <div class="fields-grid-header">Opt</div>
      </div>
      ${rows}
    </div>`;
  }

  function renderMethodsTable(methodIds) {
    if (!methodIds || methodIds.length === 0) return '';
    const meaningful = methodIds
      .map(id => nodeById[id])
      .filter(m => m && !(m.name === 'super' && !m.inputs?.length && !m.output));
    if (!meaningful.length) return '';

    const rows = meaningful.map(m => {
      const mods = modBadges(m.attributes?.modifiers);
      return `
          <tr>
            <td>${mods ? mods + ' ' : ''}${esc(m.name)}</td>
            <td>${renderInputs(m.inputs)}</td>
            <td>${esc(m.output || '—')}</td>
            <td>${esc(m.summary || '')}</td>
          </tr>`;
    }).join('');

    return `<table>
      <thead>
        <tr><th>Method</th><th>Inputs</th><th>Output</th><th>Summary</th></tr>
      </thead>
      <tbody>${rows}
      </tbody>
    </table>`;
  }

  function renderStandaloneFnsTable(fnIds) {
    if (!fnIds || fnIds.length === 0) return '';
    const rows = fnIds.map(id => {
      const fn = nodeById[id];
      if (!fn) return '';
      return `
          <tr>
            <td>${esc(fn.name)}</td>
            <td>${renderInputs(fn.inputs)}</td>
            <td>${esc(fn.output || '—')}</td>
            <td>${esc(fn.summary || '')}</td>
          </tr>`;
    }).join('');

    return `<table>
      <thead>
        <tr><th>Function</th><th>Inputs</th><th>Output</th><th>Summary</th></tr>
      </thead>
      <tbody>${rows}
      </tbody>
    </table>`;
  }

  // ── Group prog nodes by context ───────────────────────────────────────────────
  const contextToProgs = {};
  for (const [progId, ctxName] of Object.entries(progToContext)) {
    (contextToProgs[ctxName] = contextToProgs[ctxName] || []).push(progId);
  }

  let totalModules = 0, totalClasses = 0, totalMethods = 0, totalStandalone = 0;

  // ── Render ────────────────────────────────────────────────────────────────────
  const sections = Object.entries(contextToProgs)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([ctxName, progIds]) => {
      // Only render prog nodes that have at least one class or fn
      const activeProg = progIds.filter(p =>
        (progToClasses[p] || []).length > 0 || (progToFns[p] || []).length > 0
      );
      if (!activeProg.length) return '';

      totalModules += activeProg.length;

      const moduleSections = activeProg.map(progId => {
        const classIds      = unique(progToClasses[progId] || []);
        const standaloneFns = unique(progToFns[progId] || []);
        const allChildren   = [...classIds, ...standaloneFns];
        const label         = progLabel(progId, allChildren);
        const callsOut      = unique(progCallsOut[progId] || []);
        const callsIn       = unique(progCallsIn[progId]  || []);

        totalClasses    += classIds.length;
        totalStandalone += standaloneFns.length;

        const classSections = classIds.map(classId => {
          const cls       = nodeById[classId];
          if (!cls) return '';
          const kind      = cls.attributes?.kind || 'class';
          const fields    = cls.inputs || [];
          const methodIds = unique(classToMethods[classId] || []);
          totalMethods   += methodIds.length;
          const loc       = shortLoc(cls.source_location);

          return `
    <h3 class="subsection">${esc(cls.name)} ${kindBadge(kind)}</h3>
    <p class="stat-line" style="margin-top:2px">
      ${esc(fields.length)} field${fields.length !== 1 ? 's' : ''} ·
      ${esc(methodIds.length)} method${methodIds.length !== 1 ? 's' : ''} ·
      <span title="${esc(cls.source_location)}">${esc(loc)}</span>
    </p>
    ${cls.summary ? `<p style="font-size:13px;margin-bottom:8px">${esc(cls.summary)}</p>` : ''}
    ${renderFieldsGrid(fields)}
    ${renderMethodsTable(methodIds)}`;
        }).join('');

        const standaloneSection = standaloneFns.length > 0 ? `
    <h3 class="subsection" style="font-size:12px;color:var(--color-muted)">Module-level functions</h3>
    ${renderStandaloneFnsTable(standaloneFns)}` : '';

        return `
  <div class="module-block">
    <div class="module-header">
      <span class="module-name" title="${esc(progId)}">${esc(label)}</span>
      <span class="module-counts">${esc(classIds.length)} class${classIds.length !== 1 ? 'es' : ''} · ${esc(standaloneFns.length)} fn${standaloneFns.length !== 1 ? 's' : ''}</span>
    </div>
    <div class="module-deps">
      <span class="dep-label">Calls</span>
      ${renderProgList(callsOut)}
    </div>
    <div class="module-deps">
      <span class="dep-label">Called by</span>
      ${renderProgList(callsIn)}
    </div>
    ${classSections}
    ${standaloneSection}
  </div>`;
      }).join('');

      return `
  <h2 class="section">${esc(ctxName)}</h2>
  <p class="stat-line">${esc(activeProg.length)} module${activeProg.length !== 1 ? 's' : ''}</p>
  ${moduleSections}`;
    }).join('');

  return `
<section id="appendix-functions">
  <h1 class="chapter">Appendix B — Class &amp; Function Inventory</h1>
  <hr class="chapter-rule">
  <p>
    ${esc(totalModules)} modules, ${esc(totalClasses)} classes/interfaces,
    and ${esc(totalMethods + totalStandalone)} procedures extracted from the IR graph.
    Organised by bounded context → module. Each module shows its import dependencies
    (Calls) and consumers (Called by) at the module level, then its classes and functions.
  </p>
  ${sections}
</section>`.trim();
}

// ── Assemble full HTML ────────────────────────────────────────────────────────

function buildHTML() {
  const title = `${projectName} — Migration readiness report`;
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
</head>
<body>
${buildNav()}
<div class="document">
${buildCover()}
${buildExecutiveSummary()}
${buildContexts()}
${buildConstraints()}
${buildStreams()}
${buildAppendix()}
${buildFunctionAppendix()}
</div>
</body>
</html>`;
}

// ── Write output ──────────────────────────────────────────────────────────────

const html    = buildHTML();
const outPath = outArg || path.join(runDir, 'migration-briefing.html');

fs.writeFileSync(outPath, html, 'utf8');

// Also copy to /mnt/user-data/outputs/ if that path exists
const outputsDir = '/mnt/user-data/outputs';
if (fs.existsSync(outputsDir)) {
  fs.writeFileSync(path.join(outputsDir, 'migration-briefing.html'), html, 'utf8');
  console.log(`Copied to ${outputsDir}/migration-briefing.html`);
}

// ── Post-write validation ─────────────────────────────────────────────────────

const written = fs.readFileSync(outPath, 'utf8');

if (written.includes('[object Object]')) {
  console.error('ERROR: Bad interpolation ([object Object]) found in output');
  process.exit(1);
}

const tableCount    = (written.match(/<table/g) || []).length;
const allTbodies    = written.match(/<tbody[^>]*>[\s\S]*?<\/tbody>/g) || [];
// Seam inventory is table index 3 (0-based); stream table is index 2
const seamTableBody   = allTbodies[3] || '';
const seamRowCount    = (seamTableBody.match(/<tr/g) || []).length;
const streamTableBody = allTbodies[2] || '';
const streamRowCount  = (streamTableBody.match(/<tr/g) || []).length;
const fnRowCount      = allTbodies.slice(4).reduce((s, t) => s + (t.match(/<tr/g) || []).length, 0);

console.log(`File written: ${outPath}`);
console.log(`File size:    ${written.length} bytes`);
console.log(`Tables found: ${tableCount}`);
console.log(`Seam rows: ${seamRowCount} (expected ${totalSeams})`);
console.log(`Stream table rows: ${streamRowCount} (expected ${streamCount})`);
console.log(`Function rows: ${fnRowCount}`);

if (seamRowCount !== totalSeams) {
  console.warn(`WARNING: seam row count ${seamRowCount} !== seam count ${totalSeams}`);
}
if (streamRowCount !== streamCount) {
  console.warn(`WARNING: stream row count ${streamRowCount} !== stream count ${streamCount}`);
}
