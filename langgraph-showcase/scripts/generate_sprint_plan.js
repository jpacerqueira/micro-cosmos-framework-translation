#!/usr/bin/env node
'use strict';

/**
 * generate_sprint_plan.js
 *
 * Sprint / iteration migration plan from work_streams.json.
 * Groups streams by seq wave, shows parallelism, critical path, story-point rollup.
 *
 * Usage:
 *   node scripts/generate_sprint_plan.js <run_dir>
 *   node scripts/generate_sprint_plan.js <run_dir> <out>
 */

const fs   = require('fs');
const path = require('path');
const {
  esc, riskBadge, tableCaption, callout, htmlShell, writeReport,
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
const wsData   = read('work_streams.json');
const seamData = readOpt('seam.json');

const projectName = path.basename(meta.source_path || 'unknown');
const streams     = wsData.work_streams || wsData.streams || [];
const seams       = seamData ? (seamData.seams || []) : [];
const totalPts    = wsData.total_story_points || 0;
const totalSeams  = wsData.total_seams || seams.length;

const streamById = Object.fromEntries(streams.map(s => [s.id, s]));
const seamById   = Object.fromEntries(seams.map(s => [s.id, s]));

// Group streams by seq
const bySeq = {};
for (const s of streams) {
  const q = s.seq || 1;
  if (!bySeq[q]) bySeq[q] = [];
  bySeq[q].push(s);
}
const seqKeys = Object.keys(bySeq).map(Number).sort((a, b) => a - b);

// Wave summary
const waveSummary = seqKeys.map(q => {
  const group = bySeq[q];
  const pts   = group.reduce((sum, s) => sum + (s.story_points || 0), 0);
  return { seq: q, count: group.length, pts };
});

// Critical path: longest dep chain by stream count
function longestChain(id, memo = {}) {
  if (memo[id] !== undefined) return memo[id];
  const s = streamById[id];
  if (!s || !s.depends_on || s.depends_on.length === 0) return memo[id] = [id];
  const best = s.depends_on.reduce((best, dep) => {
    const chain = longestChain(dep, memo);
    return chain.length > best.length ? chain : best;
  }, []);
  return memo[id] = [...best, id];
}
const allChains = streams.map(s => longestChain(s.id));
const criticalPath = allChains.reduce((best, c) => c.length > best.length ? c : best, []);

// Cumulative points
let cumPts = 0;
const waveRows = seqKeys.map(q => {
  const group = bySeq[q];
  const pts   = group.reduce((sum, s) => sum + (s.story_points || 0), 0);
  cumPts += pts;
  const names = group.map(s => esc(s.name)).join(', ');
  return `<tr>
    <td>Wave ${esc(q)}</td>
    <td>${esc(group.length)}</td>
    <td>${esc(pts)}</td>
    <td>${esc(cumPts)}</td>
    <td style="color:#91969C;font-size:11px">${names}</td>
  </tr>`;
}).join('');

// Per-wave detailed sections
const waveSections = seqKeys.map(q => {
  const group = bySeq[q];
  const wavePts = group.reduce((sum, s) => sum + (s.story_points || 0), 0);
  const parallelNote = group.length > 1
    ? `<p>${esc(group.length)} streams run <strong>in parallel</strong> in this wave. They can be owned by separate teams simultaneously.</p>`
    : '<p>Single stream — no parallelism in this wave.</p>';

  const streamCards = group.map(s => {
    const deps = (s.depends_on || []).map(id => streamById[id] ? streamById[id].name : id);
    const depLine = deps.length > 0
      ? `<p class="stat-line">Depends on: ${deps.map(esc).join(', ')}</p>` : '';
    const seamsInStream = (s.seam_ids || []).map(id => seamById[id]).filter(Boolean);
    const seamsTable = seamsInStream.length > 0 ? `
      <table style="margin-top:8px">
        <thead><tr><th>Seam</th><th>Type</th><th>Effort</th><th>Points</th></tr></thead>
        <tbody>${seamsInStream.map(sm => `<tr>
          <td>${esc(sm.location)}</td>
          <td>${esc(sm.type)}</td>
          <td>${esc(sm.work && sm.work.effort)}</td>
          <td>${esc(sm.work && sm.work.story_points)}</td>
        </tr>`).join('')}</tbody>
      </table>` : '';
    const onCritPath = criticalPath.includes(s.id);
    const critLabel = onCritPath ? `<span style="font-family:'IBM Plex Mono',monospace;font-size:10px;color:#C0392B;background:#FDECEA;border:1px solid #F5C6C2;padding:1px 5px;border-radius:2px;margin-left:6px">critical path</span>` : '';
    return `
    <div style="background:#fff;border:1px solid #E6EAE6;padding:20px 24px;margin:12px 0">
      <h3 class="subsection" style="margin-top:0">${esc(s.name)}${critLabel}</h3>
      <p class="stat-line">${esc(s.seam_count)} seam${s.seam_count !== 1 ? 's' : ''} · ${esc(s.story_points)} pts · ${riskBadge(s.risk)} · ${esc(s.migration_phase)}</p>
      ${depLine}
      <p>${esc(s.rationale)}</p>
      ${seamsTable}
    </div>`;
  }).join('');

  return `
  <section id="wave-${q}">
    <h2 class="section">Wave ${esc(q)}</h2>
    ${parallelNote}
    <p class="stat-line">${esc(group.length)} stream${group.length !== 1 ? 's' : ''} · ${esc(wavePts)} story points</p>
    ${streamCards}
  </section>`;
}).join('');

// Critical path visualised
const cpNames = criticalPath.map(id => streamById[id] ? streamById[id].name : id);
const cpHtml = cpNames.length > 0
  ? `<div class="panel" style="white-space:normal;word-break:normal">${cpNames.map(esc).join(' → ')}</div>
     <p>The critical path has <strong>${esc(criticalPath.length)}</strong> steps. This is the minimum number of sequential handoffs regardless of team size.</p>`
  : '<p style="color:#91969C">No dependency chain long enough to compute.</p>';

const bodyHtml = `
<div class="metric-row" style="grid-template-columns:repeat(4,1fr)">
  <div class="metric-card"><div class="metric-value">${esc(totalSeams)}</div><div class="metric-label">Total seams</div></div>
  <div class="metric-card"><div class="metric-value">${esc(totalPts)} <span style="font-size:22px">pts</span></div><div class="metric-label">Story points</div></div>
  <div class="metric-card"><div class="metric-value">${esc(streams.length)}</div><div class="metric-label">Work streams</div></div>
  <div class="metric-card"><div class="metric-value">${esc(seqKeys.length)}</div><div class="metric-label">Waves</div></div>
</div>

<section id="summary">
  <h1 class="chapter">Wave summary</h1>
  <hr class="chapter-rule">
  <p>Streams within the same wave are fully independent and can run in parallel. A stream in
  wave N cannot start until all its <code>depends_on</code> streams are complete.</p>
  ${tableCaption('WAVE ROLLUP')}
  <table>
    <thead><tr><th>Wave</th><th>Parallel streams</th><th>Points</th><th>Cumulative pts</th><th>Streams</th></tr></thead>
    <tbody>${waveRows}</tbody>
  </table>
</section>

<section id="critical-path">
  <h1 class="chapter">Critical path</h1>
  <hr class="chapter-rule">
  <p>The longest chain of serial dependencies — the floor on total calendar duration.</p>
  ${cpHtml}
</section>

<section id="waves">
  <h1 class="chapter">Wave details</h1>
  <hr class="chapter-rule">
  ${waveSections}
</section>
`;

const navLinks = [['#summary','Summary'],['#critical-path','Critical path'],['#waves','Waves']];
for (const q of seqKeys) navLinks.push([`#wave-${q}`, `Wave ${q}`]);

const html = htmlShell({
  title:      `${projectName} — Sprint plan`,
  projectName,
  reportType: 'Sprint plan',
  navLinks,
  bodyHtml,
});

writeReport(html, 'sprint-plan.html', runDir, outArg);
