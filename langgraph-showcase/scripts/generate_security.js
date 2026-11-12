#!/usr/bin/env node
'use strict';

/**
 * generate_security.js
 *
 * Reads security_report.json and trivy_report.json from the run directory
 * and writes a self-contained HTML security analysis report.
 *
 * Usage:
 *   node scripts/generate_security.js <run_dir>          (write to run_dir)
 *   node scripts/generate_security.js <run_dir> <out>    (write to out path)
 */

const fs   = require('fs');
const path = require('path');

const { writeReport } = require('./report_common');

const args   = process.argv.slice(2);
const runDir = args[0] ? path.resolve(args[0]) : process.cwd();
const outArg = args[1] ? path.resolve(args[1]) : null;

function tryRead(name) {
  const p = path.join(runDir, name);
  if (!fs.existsSync(p)) return null;
  try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch { return null; }
}

function read(name) {
  const v = tryRead(name);
  if (!v) throw new Error(`Required file not found: ${path.join(runDir, name)}`);
  return v;
}

const meta   = read('run_meta.json');
const report = tryRead('security_report.json');
const trivy  = tryRead('trivy_report.json');

const projectName = path.basename(meta.source_path || runDir);
const now         = new Date().toISOString().replace('T', ' ').slice(0, 19) + ' UTC';

const SEV_ORDER   = { CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3, INFO: 4 };
const SEV_COLOURS = {
  CRITICAL: '#7b1a1a',
  HIGH:     '#ED3A12',
  MEDIUM:   '#8a5a00',
  LOW:      '#2d7d46',
  INFO:     '#91969C',
};
const SEV_BG = {
  CRITICAL: '#fff0f0',
  HIGH:     '#fff5f0',
  MEDIUM:   '#fffbf0',
  LOW:      '#f0fff4',
  INFO:     '#f5f5f5',
};

function escHtml(s) {
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function sevBadge(sev) {
  const col = SEV_COLOURS[sev] || '#91969C';
  return `<span class="sev-badge" style="border-color:${col};color:${col};">${sev}</span>`;
}

function confirmedBadge(confirmed) {
  return confirmed
    ? `<span class="status-badge confirmed">CONFIRMED</span>`
    : `<span class="status-badge hypothesis">HYPOTHESIS</span>`;
}

function migrationBadge() {
  return `<span class="status-badge migration">AFFECTS MIGRATION</span>`;
}

// ── Statistics dashboard ──────────────────────────────────────────────────────

function renderStatsDashboard(findings, trivyData) {
  const sevCounts = { CRITICAL: 0, HIGH: 0, MEDIUM: 0, LOW: 0, INFO: 0 };
  for (const f of findings) sevCounts[f.severity] = (sevCounts[f.severity] || 0) + 1;
  const confirmedCount    = findings.filter(f => f.confirmed).length;
  const migrationCount    = findings.filter(f => f.affects_migration).length;
  const trivyVulns        = trivyData && !trivyData.error ? (trivyData.vulnerabilities || []) : [];
  const trivyTotal        = trivyData && !trivyData.error ? (trivyData.summary?.total || 0) : 0;
  const trivyCrit         = trivyData?.summary?.CRITICAL || 0;
  const trivyHigh         = trivyData?.summary?.HIGH || 0;
  const trivyMigration    = trivyVulns.filter(v => v.affects_migration).length;
  const trivyConfirmed    = trivyVulns.filter(v => v.confirmed !== false).length; // Trivy CVEs are confirmed unless explicitly false

  const totalMigration = migrationCount + trivyMigration;
  const totalHighCrit  = (sevCounts.CRITICAL + sevCounts.HIGH) + (trivyCrit + trivyHigh);

  function statBox(value, label, sublabel, colorClass) {
    return `
      <div class="stat-box ${colorClass}">
        <div class="stat-value">${value}</div>
        <div class="stat-label">${label}</div>
        ${sublabel ? `<div class="stat-sub">${sublabel}</div>` : ''}
      </div>`;
  }

  const sevBreakdown = ['CRITICAL','HIGH','MEDIUM','LOW','INFO']
    .filter(s => sevCounts[s] > 0)
    .map(s => `<span style="color:${SEV_COLOURS[s]};font-weight:600;">${sevCounts[s]} ${s.toLowerCase()}</span>`)
    .join(' · ');

  const trivyBreakdown = trivyTotal > 0
    ? `${trivyCrit ? `<span style="color:${SEV_COLOURS.CRITICAL};font-weight:600;">${trivyCrit} critical</span> ` : ''}${trivyHigh ? `<span style="color:${SEV_COLOURS.HIGH};font-weight:600;">${trivyHigh} high</span>` : ''}`
    : '<span style="color:#2d7d46;">none</span>';

  const highCritClass = totalHighCrit > 0 ? 'stat-critical' : 'stat-ok';
  const migClass      = totalMigration > 0 ? 'stat-warn' : 'stat-ok';

  return `
    <div class="stats-grid">
      ${statBox(findings.length, 'Source findings', sevBreakdown || 'none', findings.length > 0 ? 'stat-warn' : 'stat-ok')}
      ${statBox(trivyTotal, 'Dependency CVEs', trivyBreakdown, trivyTotal > 0 ? (trivyCrit ? 'stat-critical' : 'stat-warn') : 'stat-ok')}
      ${statBox(totalMigration, 'Affect migration', `${migrationCount} code · ${trivyMigration} CVEs`, migClass)}
      ${statBox(confirmedCount + trivyConfirmed, 'Confirmed', `${confirmedCount} code · ${trivyConfirmed} CVEs`, confirmedCount + trivyConfirmed > 0 ? 'stat-warn' : 'stat-ok')}
    </div>`;
}

// ── Risk assessment cards ─────────────────────────────────────────────────────

function riskCard(label, value) {
  const col = SEV_COLOURS[value] || '#91969C';
  return `
    <div style="border:2px solid ${col};padding:20px 28px;min-width:200px;text-align:center;">
      <div style="font-family:var(--mono);font-size:0.68rem;text-transform:uppercase;letter-spacing:0.08em;color:var(--muted);margin-bottom:8px;">${label}</div>
      <div style="font-family:var(--serif);font-size:2rem;color:${col};">${value || 'UNKNOWN'}</div>
    </div>`;
}

// ── Trivy CVE section — always-visible cards ──────────────────────────────────

function renderTrivyCards(t) {
  if (!t || t.error) {
    const msg = t?.error ? escHtml(t.error) : 'Trivy scan not available.';
    return `<p class="muted">${msg}</p>`;
  }
  if (!Array.isArray(t.vulnerabilities) || t.vulnerabilities.length === 0) {
    return `<p class="ok-banner">No dependency CVEs found — clean bill of health for this project's dependencies.</p>`;
  }

  const vulns = [...t.vulnerabilities].sort(
    (a, b) => (SEV_ORDER[a.severity] ?? 9) - (SEV_ORDER[b.severity] ?? 9)
  );
  const sum = t.summary || {};
  const totalHtml = `${vulns.length} CVE(s) in project dependencies`;
  const sevHtml = ['CRITICAL','HIGH','MEDIUM','LOW']
    .filter(s => sum[s])
    .map(s => `<span class="sev-badge" style="border-color:${SEV_COLOURS[s]};color:${SEV_COLOURS[s]};">${sum[s]} ${s}</span>`)
    .join(' ');

  const cards = vulns.map(v => {
    const col = SEV_COLOURS[v.severity] || '#91969C';
    return `
      <div class="finding-card" style="border-left-color:${col};">
        <div class="finding-header">
          ${sevBadge(v.severity)}
          <span class="mono" style="color:var(--muted);min-width:110px;font-size:0.75rem;">${escHtml(v.cve_id || v.id)}</span>
          <span class="finding-title">${escHtml(v.pkg_name)} <span class="mono" style="font-weight:400;font-size:0.82rem;">${escHtml(v.installed_version || '')}</span></span>
          ${v.fixed_version ? `<span class="fix-arrow mono">→ ${escHtml(v.fixed_version)}</span>` : ''}
          ${confirmedBadge(true)}
          ${v.affects_migration ? migrationBadge() : ''}
        </div>
        <div class="finding-location mono">${escHtml(v.location || '')}</div>
        ${v.description ? `<p class="finding-desc">${escHtml(v.description)}</p>` : ''}
        <div class="remediation-bar" style="border-left-color:${col};">
          <strong>Fix:</strong> ${escHtml(v.remediation || 'Upgrade to the latest stable version.')}
        </div>
        ${v.primary_url ? `<p class="mono" style="margin:4px 0 0;font-size:0.7rem;"><a href="${escHtml(v.primary_url)}" class="muted">${escHtml(v.primary_url)}</a></p>` : ''}
      </div>`;
  }).join('\n');

  return `<p style="margin-bottom:14px;">${totalHtml} &nbsp;${sevHtml}</p>${cards}`;
}

// ── Category / severity matrix ────────────────────────────────────────────────

function renderCategoryMatrix(findings) {
  if (!findings.length) return '';
  const cats = {};
  for (const f of findings) {
    if (!cats[f.category]) cats[f.category] = { CRITICAL:0, HIGH:0, MEDIUM:0, LOW:0, INFO:0, total:0 };
    cats[f.category][f.severity] = (cats[f.category][f.severity] || 0) + 1;
    cats[f.category].total++;
  }
  const rows = Object.entries(cats)
    .sort((a, b) => b[1].total - a[1].total)
    .map(([cat, counts]) => {
      const cells = ['CRITICAL','HIGH','MEDIUM','LOW','INFO'].map(s => {
        const n = counts[s];
        return n
          ? `<td style="color:${SEV_COLOURS[s]};font-weight:600;text-align:center;">${n}</td>`
          : `<td style="color:var(--muted);text-align:center;">—</td>`;
      }).join('');
      return `<tr>
        <td style="font-family:var(--mono);font-size:0.8rem;padding:6px 12px 6px 0;white-space:nowrap;">${escHtml(cat)}</td>
        ${cells}
        <td style="text-align:center;font-weight:600;padding-left:12px;">${counts.total}</td>
      </tr>`;
    }).join('');
  return `
    <table class="matrix-table">
      <thead>
        <tr>
          <th style="text-align:left;padding-right:12px;">Category</th>
          ${['CRITICAL','HIGH','MEDIUM','LOW','INFO'].map(s => `<th style="color:${SEV_COLOURS[s]};text-align:center;">${s}</th>`).join('')}
          <th style="text-align:center;padding-left:12px;">Total</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>`;
}

// ── Migration impact section ──────────────────────────────────────────────────

function renderMigrationImpact(findings, trivyData) {
  const migFindings = findings.filter(f => f.affects_migration);
  const migCves     = trivyData ? (trivyData.vulnerabilities || []).filter(v => v.affects_migration) : [];

  if (!migFindings.length && !migCves.length) {
    return `<p class="ok-banner">No source-code findings flagged as migration-affecting. See Dependency CVEs below for supply-chain risks.</p>`;
  }

  let html = '';

  if (migCves.length) {
    html += `<h3 style="margin-top:16px;">Dependency CVEs affecting migration (${migCves.length})</h3>`;
    html += migCves.map(v => {
      const col = SEV_COLOURS[v.severity] || '#91969C';
      return `<div class="finding-card compact" style="border-left-color:${col};">
        <div class="finding-header">
          ${sevBadge(v.severity)}
          <span class="mono" style="color:var(--muted);font-size:0.75rem;">${escHtml(v.cve_id || v.id)}</span>
          <span class="finding-title">${escHtml(v.pkg_name)} ${escHtml(v.installed_version || '')}</span>
          ${v.fixed_version ? `<span class="fix-arrow mono">→ ${escHtml(v.fixed_version)}</span>` : ''}
        </div>
        <div class="remediation-bar" style="border-left-color:${col};">${escHtml(v.remediation || '')}</div>
      </div>`;
    }).join('\n');
  }

  if (migFindings.length) {
    html += `<h3 style="margin-top:20px;">Source code findings affecting migration (${migFindings.length})</h3>`;
    html += migFindings.map(f => {
      const col = SEV_COLOURS[f.severity] || '#91969C';
      return `<div class="finding-card compact" style="border-left-color:${col};">
        <div class="finding-header">
          <span class="mono muted" style="min-width:60px;">${escHtml(f.id)}</span>
          ${sevBadge(f.severity)}
          <span class="finding-title">${escHtml(f.title)}</span>
          ${confirmedBadge(f.confirmed)}
        </div>
        <div class="mono" style="font-size:0.75rem;color:var(--muted);margin-top:4px;">${escHtml(f.location)}</div>
        <div class="remediation-bar" style="border-left-color:${col};">${escHtml(f.remediation)}</div>
      </div>`;
    }).join('\n');
  }

  return html;
}

// ── Source findings by file ───────────────────────────────────────────────────

function renderFindingsByFile(findings) {
  if (!findings.length) return '';
  const files = {};
  for (const f of findings) {
    const fileKey = (f.location || 'unknown').split(':')[0];
    if (!files[fileKey]) files[fileKey] = [];
    files[fileKey].push(f);
  }
  const sorted = Object.entries(files).sort((a, b) => b[1].length - a[1].length);

  return sorted.map(([file, flist]) => {
    const sevCounts = {};
    for (const f of flist) sevCounts[f.severity] = (sevCounts[f.severity] || 0) + 1;
    const badges = ['CRITICAL','HIGH','MEDIUM','LOW','INFO']
      .filter(s => sevCounts[s])
      .map(s => `<span class="sev-badge" style="border-color:${SEV_COLOURS[s]};color:${SEV_COLOURS[s]};">${sevCounts[s]} ${s}</span>`)
      .join(' ');
    const topSev = ['CRITICAL','HIGH','MEDIUM','LOW','INFO'].find(s => sevCounts[s]) || 'INFO';
    const col = SEV_COLOURS[topSev];
    return `
      <details class="file-group" style="border-left:3px solid ${col};">
        <summary class="file-summary">
          <span class="mono file-name">${escHtml(file)}</span>
          <span class="file-badges">${badges} <span class="muted" style="font-size:0.75rem;">${flist.length} finding${flist.length>1?'s':''}</span></span>
        </summary>
        <div class="file-findings">
          ${flist.map(f => renderFindingCard(f, true)).join('')}
        </div>
      </details>`;
  }).join('\n');
}

// ── Individual finding card ───────────────────────────────────────────────────

function renderSnippet(snippet) {
  if (!snippet) return '';
  const lines = escHtml(snippet).split('\n').map(line => {
    const isHit = line.startsWith('→');
    return isHit
      ? `<span style="background:#fff3cd;display:block;white-space:pre;">${line}</span>`
      : `<span style="display:block;white-space:pre;">${line}</span>`;
  }).join('');
  return `
    <details class="snippet-details">
      <summary class="snippet-summary">&#x1F4C4; Show code snippet</summary>
      <pre class="snippet-pre">${lines}</pre>
    </details>`;
}

function renderFindingCard(f, compact = false) {
  const col = SEV_COLOURS[f.severity] || '#ccc';
  return `
    <div class="finding-card${compact?' compact':''}" style="border-left-color:${col};">
      <div class="finding-header">
        <span class="mono muted" style="min-width:60px;font-size:0.75rem;">${escHtml(f.id)}</span>
        ${sevBadge(f.severity)}
        <span class="finding-title">${escHtml(f.title)}</span>
        <span class="mono muted" style="font-size:0.68rem;text-transform:uppercase;">${escHtml(f.category)}</span>
        ${f.cwe_id ? `<span class="mono muted" style="font-size:0.65rem;">${escHtml(f.cwe_id)}</span>` : ''}
      </div>
      <div style="margin:6px 0;display:flex;gap:6px;flex-wrap:wrap;align-items:center;">
        ${confirmedBadge(f.confirmed)}
        ${f.affects_migration ? migrationBadge() : ''}
      </div>
      <p class="finding-desc">${escHtml(f.description)}</p>
      ${f.matched_text ? `<div class="matched-text">Matched: <code>${escHtml(f.matched_text)}</code></div>` : ''}
      <div class="finding-location mono">&#x1F4CC; ${escHtml(f.location)}</div>
      <div class="remediation-bar" style="border-left-color:${col};"><strong>Fix:</strong> ${escHtml(f.remediation)}</div>
      ${renderSnippet(f.code_snippet)}
    </div>`;
}

// ── Full report renderer ──────────────────────────────────────────────────────

function renderPlaceholder() {
  return `<div style="padding:48px;text-align:center;border:1px dashed var(--rule);">
    <p class="mono muted">security_report.json not yet generated.</p>
    <p class="muted" style="font-size:0.85rem;">The Security phase must complete before this report is available.</p>
  </div>`;
}

function renderReport(r) {
  const findings = [...(r.findings || [])].sort(
    (a, b) => (SEV_ORDER[a.severity] ?? 9) - (SEV_ORDER[b.severity] ?? 9)
  );

  // ── Stats dashboard ─────────────────────────────────────────────────────────
  const statsHtml = renderStatsDashboard(findings, trivy);

  // ── Risk cards ──────────────────────────────────────────────────────────────
  const riskHtml = `
    <div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:28px;">
      ${riskCard('Source Architecture Risk', r.source_architecture_risk)}
      ${riskCard('Target Architecture Risk', r.destination_architecture_risk)}
    </div>`;

  // ── Scope summary ────────────────────────────────────────────────────────────
  const scopeHtml = r.scope_summary
    ? `<div class="scope-banner">${escHtml(r.scope_summary)}</div>`
    : '';

  // ── Dependency CVEs (Trivy) — always-visible cards ──────────────────────────
  const trivyHtml = `
    <h2>Dependency CVEs <span class="mono" style="font-size:0.75rem;font-weight:400;color:var(--muted);">via Trivy</span></h2>
    ${renderTrivyCards(trivy)}`;

  // ── Migration impact ─────────────────────────────────────────────────────────
  const migHtml = `
    <h2 style="margin-top:32px;">Migration impact</h2>
    ${renderMigrationImpact(findings, trivy)}`;

  // ── Category/severity matrix ─────────────────────────────────────────────────
  const matrixHtml = findings.length ? `
    <h2 style="margin-top:32px;">Findings by category</h2>
    ${renderCategoryMatrix(findings)}` : '';

  // ── Source code findings grouped by file ─────────────────────────────────────
  const byFileHtml = findings.length ? `
    <h2 style="margin-top:32px;">Source code findings
      <span class="mono" style="font-size:0.9rem;font-weight:400;">
        ${findings.length} total ·
        ${findings.filter(f=>f.confirmed).length} confirmed ·
        ${findings.filter(f=>!f.confirmed).length} hypothesis
      </span>
    </h2>
    <p class="muted" style="font-size:0.85rem;margin-bottom:16px;">
      Grouped by source file. Expand a file to see individual findings and code snippets.
    </p>
    ${renderFindingsByFile(findings)}` : `<h2 style="margin-top:32px;">Source code findings</h2><p class="muted">No findings.</p>`;

  // ── Auxiliary sections ────────────────────────────────────────────────────────
  const migNotes   = r.migration_security_notes || [];
  const recFixes   = r.recommended_fixes || [];
  const followUp   = r.follow_up_checks || [];
  const ranking    = r.risk_ranking || [];

  const migNotesHtml = `
    <h2 style="margin-top:32px;">Migration security notes</h2>
    ${migNotes.length
      ? `<ul class="aux-list">${migNotes.map(n=>`<li>${escHtml(n)}</li>`).join('')}</ul>`
      : '<p class="muted">None identified by the LLM analysis. Review migration impact section above.</p>'}`;

  const recFixesHtml = `
    <h2 style="margin-top:32px;">Recommended fixes</h2>
    ${recFixes.length
      ? `<ol class="aux-list">${recFixes.map(n=>`<li>${escHtml(n)}</li>`).join('')}</ol>`
      : '<p class="muted">See individual finding remediations above.</p>'}`;

  const followUpHtml = followUp.length ? `
    <h2 style="margin-top:32px;">Follow-up checks</h2>
    <ul class="aux-list">${followUp.map(n=>`<li>${escHtml(n)}</li>`).join('')}</ul>` : '';

  const rankingHtml = ranking.length ? `
    <h2 style="margin-top:32px;">Risk ranking</h2>
    <ol class="ranking-list">
      ${ranking.map(id => {
        const f = findings.find(x => x.id === id);
        const col = f ? (SEV_COLOURS[f.severity] || 'var(--ink)') : 'var(--ink)';
        return `<li style="color:${col};">${escHtml(id)}${f ? ` — <span style="color:var(--ink);font-family:var(--body);">${escHtml(f.title)}</span>` : ''}</li>`;
      }).join('')}
    </ol>` : '';

  return [
    statsHtml,
    riskHtml,
    scopeHtml,
    trivyHtml,
    migHtml,
    matrixHtml,
    byFileHtml,
    migNotesHtml,
    recFixesHtml,
    followUpHtml,
    rankingHtml,
  ].join('\n');
}

// ── HTML shell ────────────────────────────────────────────────────────────────

const bodyContent = report ? renderReport(report) : renderPlaceholder();

const html = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Security Report — ${escHtml(projectName)}</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Inter+Tight:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap');
:root{
  --ink:#171D1D;--sage:#E6EAE6;--muted:#91969C;--accent:#ED3A12;--rule:#D5D5D5;--bg:#FFFFFF;
  --serif:"Instrument Serif","Iowan Old Style",Georgia,serif;
  --body:"Inter Tight",-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  --mono:"IBM Plex Mono",ui-monospace,"SFMono-Regular",Menlo,Consolas,monospace;
}
*{box-sizing:border-box;}
html,body{margin:0;padding:0;}
body{background:var(--bg);color:var(--ink);font-family:var(--body);font-size:14px;line-height:1.55;-webkit-font-smoothing:antialiased;}
h1,h2,h3{font-family:var(--serif);font-weight:400;color:var(--ink);letter-spacing:-0.005em;margin:0 0 0.45em;line-height:1.15;}
h1{font-size:2.2rem;}h2{font-size:1.4rem;margin-top:24px;}h3{font-size:1.05rem;margin-top:16px;}
p{margin:0 0 1em;}
a{color:inherit;}
.mono{font-family:var(--mono);}
.muted{color:var(--muted);}

/* ── Top bar ── */
.topbar{display:flex;align-items:center;justify-content:space-between;padding:9px 28px;border-bottom:1px solid var(--rule);}
.brand{font-family:var(--mono);font-size:0.78rem;letter-spacing:0.04em;color:var(--muted);text-transform:uppercase;display:flex;align-items:baseline;gap:12px;}
.brand .name{font-family:var(--serif);font-size:1.05rem;color:var(--ink);text-transform:none;letter-spacing:0;}
.mark{width:9px;height:9px;border-radius:50%;background:var(--accent);display:inline-block;transform:translateY(1px);}
main{max-width:1000px;margin:0 auto;padding:40px 32px;}

/* ── Stats dashboard ── */
.stats-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-bottom:32px;}
.stat-box{border:1px solid var(--rule);padding:16px 20px;background:var(--sage);}
.stat-box.stat-critical{border-color:${SEV_COLOURS.CRITICAL};background:#fff0f0;}
.stat-box.stat-warn{border-color:${SEV_COLOURS.MEDIUM};background:#fffbf0;}
.stat-box.stat-ok{border-color:#2d7d46;background:#f0fff4;}
.stat-value{font-family:var(--serif);font-size:2.4rem;line-height:1;margin-bottom:4px;}
.stat-label{font-family:var(--mono);font-size:0.72rem;text-transform:uppercase;letter-spacing:0.06em;color:var(--ink);margin-bottom:4px;}
.stat-sub{font-size:0.78rem;color:var(--muted);line-height:1.4;}

/* ── Scope / ok banners ── */
.scope-banner{background:var(--sage);border-left:3px solid var(--ink);padding:14px 18px;margin-bottom:28px;font-size:0.9rem;line-height:1.55;}
.ok-banner{background:#f0fff4;border-left:3px solid #2d7d46;padding:12px 16px;color:#2d7d46;font-size:0.88rem;}

/* ── Finding cards ── */
.finding-card{border:1px solid var(--rule);border-left:3px solid #ccc;margin-bottom:8px;background:var(--bg);}
.finding-card.compact{margin-bottom:6px;}
.finding-header{display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:10px 14px 6px;}
.finding-title{font-family:var(--body);font-size:0.88rem;font-weight:600;flex:1;}
.finding-desc{font-size:0.84rem;line-height:1.5;margin:0 14px 8px;color:var(--ink);}
.finding-location{font-size:0.75rem;color:var(--muted);padding:0 14px 6px;word-break:break-all;}
.remediation-bar{border-left:3px solid #ccc;margin:6px 14px 10px;padding-left:8px;font-size:0.82rem;color:#1a5c30;}
.matched-text{font-family:var(--mono);font-size:0.74rem;color:#8b2252;background:#fdf0f5;border:1px solid #e8c0d0;padding:4px 10px;margin:4px 14px 6px;overflow-x:auto;white-space:pre;}
.fix-arrow{font-size:0.72rem;color:#2d7d46;}

/* ── Severity badge ── */
.sev-badge{font-family:var(--mono);font-size:0.68rem;font-weight:700;text-transform:uppercase;letter-spacing:0.05em;padding:2px 8px;border:1px solid;border-radius:2px;}

/* ── Status badges ── */
.status-badge{font-size:0.65rem;font-family:var(--mono);padding:1px 6px;border-radius:2px;border:1px solid;}
.status-badge.confirmed{color:#2d7d46;border-color:#2d7d46;}
.status-badge.hypothesis{color:#8a5a00;border-color:#8a5a00;}
.status-badge.migration{color:#ED3A12;border-color:#ED3A12;}

/* ── Code snippet ── */
.snippet-details{margin:4px 14px 10px;}
.snippet-summary{font-family:var(--mono);font-size:0.7rem;color:var(--muted);cursor:pointer;user-select:none;list-style:none;}
.snippet-pre{margin:6px 0 0;font-family:var(--mono);font-size:0.72rem;line-height:1.5;background:#1e1e1e;color:#d4d4d4;padding:10px 14px;overflow-x:auto;border-radius:2px;}
details>summary::-webkit-details-marker{display:none;}
details[open]>summary{background:var(--bg);}

/* ── File group ── */
.file-group{border:1px solid var(--rule);margin-bottom:6px;}
.file-summary{padding:10px 14px;cursor:pointer;display:flex;align-items:center;gap:12px;user-select:none;background:var(--sage);}
.file-name{font-size:0.8rem;flex:1;word-break:break-all;}
.file-badges{display:flex;gap:6px;align-items:center;flex-wrap:wrap;}
.file-findings{padding:8px 12px 4px;}

/* ── Category matrix ── */
.matrix-table{border-collapse:collapse;font-size:0.82rem;margin-bottom:8px;width:100%;}
.matrix-table th{font-family:var(--mono);font-size:0.72rem;text-transform:uppercase;padding-bottom:6px;border-bottom:1px solid var(--rule);}
.matrix-table td{padding:5px 8px;border-bottom:1px solid var(--rule);}

/* ── Aux lists ── */
.aux-list{padding-left:1.4em;line-height:1.7;font-size:0.88rem;}
.ranking-list{font-family:var(--mono);font-size:0.8rem;padding-left:1.4em;line-height:1.9;}
ol,ul{margin-top:0;}
</style>
</head>
<body>
<div class="topbar">
  <div class="brand">
    <span class="mark"></span>
    <span class="name">Micro-Cosmos &amp; Security</span>
    <span>Security Analysis</span>
    <span>${escHtml(meta.source_lang || '')} → ${escHtml(meta.target_lang || '')}</span>
  </div>
  <div style="font-family:var(--mono);font-size:0.72rem;color:var(--muted);">${now}</div>
</div>
<main>
  <p style="font-family:var(--mono);font-size:0.72rem;color:var(--muted);text-transform:uppercase;letter-spacing:0.08em;margin-bottom:10px;">Micro-Cosmos · Security Analysis</p>
  <h1>${escHtml(projectName)}</h1>
  ${bodyContent}
</main>
</body>
</html>`;

writeReport(html, 'security-report.html', runDir, outArg);
