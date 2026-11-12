#!/usr/bin/env node
'use strict';

/**
 * generate_feature_specs.js
 *
 * Generates "Build Output Features" — the seam-by-seam development feature
 * specification report. Reads feature_specs.json and produces a self-contained
 * HTML dashboard with overview metrics, work stream groupings, seam spec cards,
 * and export buttons for OpenAPI 3.1 YAML and Jira bulk-import JSON.
 *
 * Usage: node generate_feature_specs.js <run_dir> [out_path]
 */

const fs   = require('fs');
const path = require('path');
const {
  esc, riskBadge, tableCaption, htmlShell, writeReport,
} = require('./report_common.js');

// ── CLI args ──────────────────────────────────────────────────────────────────
const [,, runDir, outArg] = process.argv;
if (!runDir) { console.error('Usage: generate_feature_specs.js <run_dir> [out_path]'); process.exit(1); }

function read(name) {
  const p = path.join(runDir, name);
  if (!fs.existsSync(p)) return null;
  try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch { return null; }
}

// ── Load data ─────────────────────────────────────────────────────────────────
const data = read('feature_specs.json');
if (!data) {
  console.error('feature_specs.json not found — run the FEATURE_SPECIFIER pipeline phase first');
  process.exit(1);
}

const specs      = data.specs      || [];
const workStreams = data.work_streams || [];
const summary    = data.summary    || {};
const runId      = data.run_id     || path.basename(runDir);
const sourcePath = data.source_path || '';
const targetLang = data.target_lang || '';
const projectName = path.basename(sourcePath) || runId;

// ── Badge helpers ─────────────────────────────────────────────────────────────

function effortBadge(effort) {
  const e = (effort || '').toUpperCase();
  const styles = {
    XS: 'background:#EAF4EA;color:#2E7D32;border:1px solid #B8DDB8',
    S:  'background:#EAF4EA;color:#2E7D32;border:1px solid #B8DDB8',
    M:  'background:#E8F0FE;color:#1A56AC;border:1px solid #B3C9F5',
    L:  'background:#FEF3E2;color:#A0522D;border:1px solid #F5DFB8',
    XL: 'background:#FDECEA;color:#C0392B;border:1px solid #F5C6C2',
  };
  const style = styles[e] || styles.M;
  return `<span style="display:inline-block;padding:2px 7px;border-radius:2px;font-family:'IBM Plex Mono',monospace;font-size:11px;text-transform:uppercase;letter-spacing:0.04em;${style}">${esc(e || 'M')}</span>`;
}

function phaseBadge(phase) {
  const p = (phase || '').toUpperCase();
  const style = p.includes('1')
    ? 'background:#E8F0FE;color:#1A56AC;border:1px solid #B3C9F5'
    : 'background:#F3E8FE;color:#6B21A8;border:1px solid #D8B4FE';
  return `<span style="display:inline-block;padding:2px 7px;border-radius:2px;font-family:'IBM Plex Mono',monospace;font-size:11px;text-transform:uppercase;letter-spacing:0.04em;${style}">${esc(phase || '')}</span>`;
}

function spBadge(sp) {
  return `<span style="display:inline-block;padding:2px 7px;border-radius:2px;font-family:'IBM Plex Mono',monospace;font-size:11px;background:#F2F4F2;color:#171D1D;border:1px solid #C5CBC5;">${esc(String(sp))} pts</span>`;
}

function apiTag() {
  return `<span style="display:inline-block;padding:2px 7px;border-radius:2px;font-family:'IBM Plex Mono',monospace;font-size:11px;background:#171D1D;color:#fff;border:1px solid #171D1D;letter-spacing:0.04em;">API</span>`;
}

// ── Section helpers ───────────────────────────────────────────────────────────

function metricsSection() {
  const totalSeams  = summary.total_seams  || specs.length;
  const totalSP     = summary.total_story_points || specs.reduce((a, s) => a + (s.story_points || 0), 0);
  const apiSeams    = summary.api_seams    || specs.filter(s => s.api_surface).length;
  const streamCount = workStreams.length;

  // Phase breakdown bar
  const byPhase = summary.by_phase || {};
  const phaseEntries = Object.entries(byPhase).sort(([a], [b]) => a.localeCompare(b));
  const phaseBar = phaseEntries.map(([ph, sp]) => {
    const pct = totalSP > 0 ? Math.round((sp / totalSP) * 100) : 0;
    return `
      <div style="margin-bottom:10px;">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:3px;">
          ${phaseBadge(ph)}
          <span style="font-family:'IBM Plex Mono',monospace;font-size:11px;color:#91969C;">${sp} pts · ${pct}%</span>
        </div>
        <div style="height:6px;background:#E6EAE6;border-radius:2px;">
          <div style="height:6px;width:${pct}%;background:#ED3A12;border-radius:2px;min-width:2px;"></div>
        </div>
      </div>`;
  }).join('');

  return `
<h1 class="chapter">Overview</h1>
<hr class="chapter-rule">

<div class="metric-row">
  <div class="metric-card">
    <div class="metric-value">${totalSeams}</div>
    <div class="metric-label">Seams</div>
  </div>
  <div class="metric-card">
    <div class="metric-value">${totalSP}</div>
    <div class="metric-label">Story Points</div>
  </div>
  <div class="metric-card">
    <div class="metric-value">${streamCount}</div>
    <div class="metric-label">Work Streams</div>
  </div>
  <div class="metric-card">
    <div class="metric-value">${apiSeams}</div>
    <div class="metric-label">API Seams</div>
  </div>
</div>

${phaseBar ? `
<h2 class="section">Story Points by Phase</h2>
<div style="max-width:480px;">${phaseBar}</div>
` : ''}`;
}

function workStreamsSection() {
  if (!workStreams.length) return '';

  const rows = workStreams.map(ws => {
    const wsSpecs = specs.filter(s => s.work_stream_id === ws.id);
    const sp      = wsSpecs.reduce((a, s) => a + (s.story_points || 0), 0);
    return `
    <tr>
      <td><strong>${esc(ws.name)}</strong><br>
        <span style="font-size:11px;color:#91969C;">${esc(ws.rationale || '')}</span>
      </td>
      <td>${phaseBadge(ws.migration_phase)}</td>
      <td style="text-align:center;">${wsSpecs.length}</td>
      <td style="text-align:center;">${spBadge(sp)}</td>
    </tr>`;
  }).join('');

  return `
<h1 class="chapter" id="work-streams">Work Streams</h1>
<hr class="chapter-rule">
${tableCaption('Work stream overview — each stream maps to a Jira Epic')}
<table>
  <thead><tr>
    <th>Stream</th>
    <th>Phase</th>
    <th style="text-align:center;">Seams</th>
    <th style="text-align:center;">Story Points</th>
  </tr></thead>
  <tbody>${rows}</tbody>
</table>`;
}

function seamSpecCards() {
  if (!specs.length) return '<p>No seam specifications generated yet.</p>';

  // Group specs by work stream for section headers
  const wsMap = {};
  for (const ws of workStreams) wsMap[ws.id] = ws.name;

  // Sort specs by work stream seq, then story_points desc
  const wsSeq = {};
  workStreams.forEach((ws, i) => { wsSeq[ws.id] = i; });
  const sorted = [...specs].sort((a, b) => {
    const sa = wsSeq[a.work_stream_id] ?? 99;
    const sb = wsSeq[b.work_stream_id] ?? 99;
    if (sa !== sb) return sa - sb;
    return (b.story_points || 0) - (a.story_points || 0);
  });

  let currentWs = null;
  const cards = sorted.map(spec => {
    let wsHeader = '';
    if (spec.work_stream_id !== currentWs) {
      currentWs = spec.work_stream_id;
      const wsName = wsMap[currentWs] || currentWs;
      wsHeader = `<h2 class="section" style="margin-top:48px;">${esc(wsName)}</h2>`;
    }

    const criteria = (spec.acceptance_criteria || [])
      .map(c => `<li style="margin:4px 0;">${esc(c)}</li>`)
      .join('');

    const apiBlock = spec.api_surface ? (() => {
      const eps = (spec.api_surface.endpoints || [])
        .map(ep => `<li style="margin:3px 0;"><strong>${esc(ep.method)}</strong> <code>${esc(ep.path)}</code> — ${esc(ep.summary)}</li>`)
        .join('');
      return `
        <div style="margin-top:14px;">
          <p class="stat-line">API Surface (${esc(spec.api_surface.type || 'REST')})</p>
          <ul style="margin:0;padding-left:16px;font-size:13px;">${eps}</ul>
        </div>`;
    })() : '';

    const deps = (spec.dependencies || []).length > 0
      ? `<p class="stat-line" style="margin-top:12px;">Depends on: ${spec.dependencies.map(d => `<code>${esc(d)}</code>`).join(', ')}</p>`
      : '';

    const labels = (spec.jira_labels || [])
      .map(l => `<span style="font-family:'IBM Plex Mono',monospace;font-size:10px;padding:1px 6px;background:#F2F4F2;border:1px solid #C5CBC5;border-radius:2px;">${esc(l)}</span>`)
      .join(' ');

    return `
${wsHeader}
<div style="background:#fff;border:1px solid #E6EAE6;padding:24px 28px;margin-bottom:16px;">
  <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:12px;">
    <div>
      <h3 class="subsection" style="margin:0 0 4px;">${esc(spec.title)}</h3>
      <p class="stat-line" style="margin:0;">${esc(spec.seam_id)}</p>
    </div>
    <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;">
      ${spec.api_surface ? apiTag() : ''}
      ${phaseBadge(spec.migration_phase)}
      ${effortBadge(spec.effort)}
      ${riskBadge(spec.risk)}
      ${spBadge(spec.story_points)}
    </div>
  </div>

  <p style="margin:0 0 10px;">${esc(spec.description)}</p>

  <div style="background:#F9FAF9;border-left:3px solid #C5CBC5;padding:10px 14px;margin:12px 0;">
    <p style="font-family:'IBM Plex Mono',monospace;font-size:11px;color:#91969C;text-transform:uppercase;letter-spacing:0.07em;margin:0 0 4px;">Business Value</p>
    <p style="margin:0;font-size:13px;">${esc(spec.business_value)}</p>
  </div>

  ${criteria ? `
  <p class="stat-line" style="margin-top:14px;">Acceptance Criteria</p>
  <ul style="margin:0;padding-left:16px;font-size:13px;">${criteria}</ul>` : ''}

  ${spec.technical_notes ? `
  <p class="stat-line" style="margin-top:14px;">Technical Notes</p>
  <p style="font-size:13px;margin:0;">${esc(spec.technical_notes)}</p>` : ''}

  ${apiBlock}
  ${deps}

  <div style="margin-top:16px;display:flex;gap:6px;flex-wrap:wrap;">${labels}</div>
</div>`;
  }).join('');

  return `
<h1 class="chapter" id="specs">Seam Specifications</h1>
<hr class="chapter-rule">
${cards}`;
}

function exportSection() {
  const runIdEnc = encodeURIComponent(runId);
  return `
<h1 class="chapter" id="export">Export</h1>
<hr class="chapter-rule">
<p>Download feature specifications in standard formats for integration with external tools.</p>

<div style="display:grid;grid-template-columns:1fr 1fr;gap:24px;margin:32px 0;">

  <div style="background:#fff;border:1px solid #E6EAE6;padding:28px 28px;">
    <h2 class="section" style="margin:0 0 8px;">OpenAPI 3.1 YAML</h2>
    <p style="font-size:13px;color:#91969C;margin:0 0 16px;">
      OpenAPI 3.1 specification. API-bearing seams generate <code>paths</code>;
      all seams contribute <code>components/schemas</code>.
    </p>
    <a href="/runs/${runIdEnc}/export/openapi"
       download="openapi.yaml"
       style="display:inline-block;font-family:'IBM Plex Mono',monospace;font-size:11px;
              text-transform:uppercase;letter-spacing:0.07em;background:#171D1D;color:#fff;
              text-decoration:none;padding:10px 20px;">
      ↓ Download openapi.yaml
    </a>
  </div>

  <div style="background:#fff;border:1px solid #E6EAE6;padding:28px 28px;">
    <h2 class="section" style="margin:0 0 8px;">Jira Import</h2>
    <p style="font-size:13px;color:#91969C;margin:0 0 4px;">
      Bulk-import JSON compatible with <code>POST /rest/api/3/issue/bulk</code>.
      Work streams → Epics, seams → Stories.
    </p>
    <div style="display:flex;align-items:center;gap:8px;margin:8px 0 16px;">
      <label style="font-family:'IBM Plex Mono',monospace;font-size:11px;text-transform:uppercase;letter-spacing:0.07em;">Project key:</label>
      <input id="jira-project-key" type="text" value="ALX"
             style="font-family:'IBM Plex Mono',monospace;font-size:12px;padding:4px 8px;
                    border:1px solid #C5CBC5;background:#F9FAF9;width:80px;">
    </div>
    <button onclick="downloadJira()"
            style="font-family:'IBM Plex Mono',monospace;font-size:11px;text-transform:uppercase;
                   letter-spacing:0.07em;background:#171D1D;color:#fff;border:none;
                   padding:10px 20px;cursor:pointer;">
      ↓ Download jira_bulk_import.json
    </button>
  </div>

</div>

<script>
function downloadJira() {
  const key = (document.getElementById('jira-project-key').value || 'ALX').trim().toUpperCase();
  const url  = '/runs/${runIdEnc}/export/jira?project_key=' + encodeURIComponent(key);
  const a    = document.createElement('a');
  a.href     = url;
  a.download = 'jira_bulk_import.json';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}
</script>`;
}

// ── Assemble report ───────────────────────────────────────────────────────────

const navLinks = [
  ['#overview',     'Overview'],
  ['#work-streams', 'Work Streams'],
  ['#specs',        'Specifications'],
  ['#export',       'Export'],
];

const bodyHtml = [
  `<div id="overview">` + metricsSection() + `</div>`,
  workStreamsSection(),
  seamSpecCards(),
  exportSection(),
].join('\n');

const html = htmlShell({
  title:       `Build Output Features — ${projectName}`,
  projectName,
  reportType:  `Build Output Features · ${targetLang ? targetLang.charAt(0).toUpperCase() + targetLang.slice(1) : 'Feature Specifications'}`,
  navLinks,
  bodyHtml,
});

writeReport(html, 'feature-specs.html', path.join(runDir, 'reports'), outArg);
