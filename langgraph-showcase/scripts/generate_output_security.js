#!/usr/bin/env node
'use strict';

/**
 * generate_output_security.js
 *
 * Reads trivy_output_report.json and review_report.json from the run directory
 * and writes a self-contained HTML output security report (post-Gate 5 Trivy scan).
 *
 * Usage:
 *   node scripts/generate_output_security.js <run_dir>
 *   node scripts/generate_output_security.js <run_dir> <out_path>
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

const meta   = tryRead('run_meta.json') || {};
const trivy  = tryRead('trivy_output_report.json');
const review = tryRead('review_report.json');

const projectName = path.basename(meta.source_path || runDir);
const targetLang  = meta.target_lang || 'unknown';
const now         = new Date().toISOString().replace('T', ' ').slice(0, 19) + ' UTC';

const SEV_ORDER = { CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3, INFO: 4 };
const SEV_COLOURS = {
  CRITICAL: '#7b1a1a',
  HIGH:     '#ED3A12',
  MEDIUM:   '#8a5a00',
  LOW:      '#2d7d46',
  INFO:     '#91969C',
};

function esc(s) {
  if (s == null) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function sevBadge(sev) {
  const col = SEV_COLOURS[sev] || '#91969C';
  return `<span style="font-family:var(--mono);font-size:0.68rem;font-weight:700;text-transform:uppercase;
    letter-spacing:0.05em;padding:2px 8px;border:1px solid ${col};color:${col};border-radius:2px;">${esc(sev)}</span>`;
}

function renderTrivySection(t) {
  if (!t || t.error) {
    const msg = (t && t.error)
      ? `Trivy scan unavailable: ${esc(t.error)}`
      : 'trivy_output_report.json not found — Trivy output scan has not run yet.';
    return `<div style="padding:32px;text-align:center;border:1px dashed var(--rule);">
      <p style="font-family:var(--mono);color:var(--muted);">${msg}</p>
    </div>`;
  }

  const vulns = [...(t.vulnerabilities || [])].sort(
    (a, b) => (SEV_ORDER[a.severity] ?? 9) - (SEV_ORDER[b.severity] ?? 9)
  );
  const sum = t.summary || {};

  if (vulns.length === 0) {
    return `<div style="padding:24px 28px;background:#e8f5e9;border-left:4px solid #2d7d46;margin-bottom:24px;">
      <p style="margin:0;font-size:0.9rem;color:#1b5e20;"><strong>No CVEs detected</strong> in the generated output code.</p>
    </div>`;
  }

  const badges = ['CRITICAL','HIGH','MEDIUM','LOW']
    .filter(s => sum[s])
    .map(s => `<span style="font-family:var(--mono);font-size:0.68rem;font-weight:700;padding:2px 8px;
        border:1px solid ${SEV_COLOURS[s]};color:${SEV_COLOURS[s]};margin-right:6px;">${sum[s]} ${s}</span>`)
    .join('');

  const rows = vulns.map(v => `
    <details style="border:1px solid var(--rule);border-left:3px solid ${SEV_COLOURS[v.severity] || '#ccc'};margin-bottom:4px;">
      <summary style="padding:8px 12px;cursor:pointer;list-style:none;display:flex;align-items:center;gap:10px;user-select:none;">
        ${sevBadge(v.severity)}
        <span style="font-family:var(--mono);font-size:0.7rem;color:var(--muted);min-width:90px;">${esc(v.cve_id || v.id)}</span>
        <span style="font-family:var(--body);font-size:0.85rem;font-weight:500;flex:1;">${esc(v.pkg_name)} ${esc(v.installed_version || '')}</span>
        ${v.fixed_version ? `<span style="font-family:var(--mono);font-size:0.68rem;color:#2d7d46;">→ ${esc(v.fixed_version)}</span>` : ''}
      </summary>
      <div style="padding:10px 14px 12px;border-top:1px solid var(--rule);background:var(--sage);">
        <div style="font-family:var(--mono);font-size:0.72rem;color:var(--muted);margin-bottom:6px;">${esc(v.location || '')}</div>
        ${v.description ? `<p style="font-size:0.82rem;line-height:1.5;margin:0 0 6px;">${esc(v.description)}</p>` : ''}
        <p style="font-size:0.82rem;color:#2d7d46;margin:0;border-left:3px solid #2d7d46;padding-left:8px;">
          <strong>Fix:</strong> ${esc(v.remediation || 'Upgrade to the latest stable version.')}
        </p>
        ${v.primary_url ? `<p style="margin:4px 0 0;font-family:var(--mono);font-size:0.7rem;">
          <a href="${esc(v.primary_url)}" style="color:var(--muted);">${esc(v.primary_url)}</a></p>` : ''}
      </div>
    </details>`).join('\n');

  return `
    <p style="margin-bottom:12px;">${vulns.length} CVE(s) detected in generated output dependencies${badges ? ' — ' + badges : ''}.</p>
    ${rows}`;
}

function renderReviewSection(r) {
  if (!r) return '';

  const passed   = r.review_passed;
  const overall  = (r.overall || (passed ? 'PASS' : 'FAIL')).toUpperCase();
  const sevCounts = r.severity_counts || {};
  const metrics  = r.metrics || {};
  const findings = (r.findings || []).filter(f => f.severity === 'BLOCKER' || f.severity === 'MAJOR');

  const verdictCol = overall === 'PASS' ? '#2d7d46' : overall === 'WARN' ? '#8a5a00' : '#c0392b';

  const sevRows = ['BLOCKER','MAJOR','MINOR']
    .filter(s => sevCounts[s])
    .map(s => {
      const col = s === 'BLOCKER' ? '#c0392b' : s === 'MAJOR' ? '#8a5a00' : '#2d7d46';
      return `<tr><td style="font-family:var(--mono);font-size:0.72rem;color:${col};padding:4px 8px;">${s}</td>
        <td style="font-family:var(--mono);font-size:0.72rem;padding:4px 8px;">${sevCounts[s]}</td></tr>`;
    }).join('');

  const metricsHtml = `
    <table style="font-size:0.82rem;border-collapse:collapse;margin-bottom:20px;">
      <tr><td style="padding:3px 16px 3px 0;color:var(--muted);">Verdict</td>
          <td style="font-family:var(--mono);font-weight:700;color:${verdictCol};">${overall}</td></tr>
      <tr><td style="padding:3px 16px 3px 0;color:var(--muted);">Files reviewed</td>
          <td style="font-family:var(--mono);">${metrics.total_files ?? '–'}</td></tr>
      ${metrics.total_lines != null ? `<tr><td style="padding:3px 16px 3px 0;color:var(--muted);">Lines of code</td>
          <td style="font-family:var(--mono);">${metrics.total_lines}</td></tr>` : ''}
      ${metrics.todo_ratio != null ? `<tr><td style="padding:3px 16px 3px 0;color:var(--muted);">TODO density</td>
          <td style="font-family:var(--mono);">${(metrics.todo_ratio * 100).toFixed(0)}%</td></tr>` : ''}
      ${metrics.has_ports != null ? `<tr><td style="padding:3px 16px 3px 0;color:var(--muted);">Port interfaces</td>
          <td style="font-family:var(--mono);color:${metrics.has_ports ? '#2d7d46' : '#8a5a00'};">${metrics.has_ports ? 'present' : 'missing'}</td></tr>` : ''}
    </table>`;

  const findingCards = findings.length ? `
    <h3 style="margin-top:20px;">BLOCKER &amp; MAJOR findings</h3>
    ${findings.slice(0, 20).map(f => {
      const col = f.severity === 'BLOCKER' ? '#c0392b' : '#8a5a00';
      return `<div style="border:1px solid var(--rule);border-left:3px solid ${col};padding:10px 14px;margin-bottom:6px;">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:4px;">
          ${sevBadge(f.severity)}
          <span style="font-family:var(--mono);font-size:0.72rem;color:var(--muted);">${esc(f.check || '')}</span>
          <span style="font-family:var(--mono);font-size:0.72rem;">${esc(f.path || '')}</span>
        </div>
        <p style="margin:0;font-size:0.83rem;line-height:1.45;">${esc(f.message || '')}</p>
      </div>`;
    }).join('\n')}` : '';

  return `
    <h2 style="margin-top:40px;">PR Review <span style="font-family:var(--mono);font-size:0.8rem;font-weight:400;color:var(--muted);">automated code review</span></h2>
    ${r.summary ? `<div style="background:var(--sage);border-left:3px solid var(--ink);padding:14px 18px;margin-bottom:20px;font-size:0.88rem;line-height:1.5;">${esc(r.summary)}</div>` : ''}
    ${metricsHtml}
    ${sevRows ? `<table style="border-collapse:collapse;margin-bottom:16px;"><tbody>${sevRows}</tbody></table>` : ''}
    ${findingCards}`;
}

const trivyHtml   = renderTrivySection(trivy);
const reviewHtml  = renderReviewSection(review);

const html = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Output Security Report — ${esc(projectName)}</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Inter+Tight:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap');
:root{--ink:#171D1D;--sage:#E6EAE6;--muted:#91969C;--accent:#ED3A12;--rule:#D5D5D5;--bg:#FFFFFF;
  --serif:"Instrument Serif","Iowan Old Style",Georgia,serif;
  --body:"Inter Tight",-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  --mono:"IBM Plex Mono",ui-monospace,"SFMono-Regular",Menlo,Consolas,monospace;}
*{box-sizing:border-box;}
html,body{margin:0;padding:0;}
body{background:var(--bg);color:var(--ink);font-family:var(--body);font-size:14px;line-height:1.55;-webkit-font-smoothing:antialiased;}
h1,h2,h3{font-family:var(--serif);font-weight:400;color:var(--ink);letter-spacing:-0.005em;margin:0 0 0.45em;line-height:1.15;}
h1{font-size:2.2rem;}h2{font-size:1.4rem;margin-top:24px;}h3{font-size:1.05rem;}
p{margin:0 0 1em;}
.topbar{display:flex;align-items:center;justify-content:space-between;padding:9px 28px;border-bottom:1px solid var(--rule);}
.brand{font-family:var(--mono);font-size:0.78rem;letter-spacing:0.04em;color:var(--muted);text-transform:uppercase;display:flex;align-items:baseline;gap:12px;}
.brand .name{font-family:var(--serif);font-size:1.05rem;color:var(--ink);text-transform:none;letter-spacing:0;}
.mark{width:9px;height:9px;border-radius:50%;background:var(--accent);display:inline-block;transform:translateY(1px);}
main{max-width:980px;margin:0 auto;padding:40px 32px;}
details>summary::-webkit-details-marker{display:none;}
details[open]>summary{background:var(--bg);}
ol,ul{padding-left:1.4em;line-height:1.7;}
@media print{.topbar{display:none;}.print-btn{display:none;}}
</style>
</head>
<body>
<div class="topbar">
  <div class="brand">
    <span class="mark"></span>
    <span class="name">Micro-Cosmos</span>
    <span>Output Security Report</span>
  </div>
  <button class="print-btn" onclick="window.print()" style="font-family:var(--mono);font-size:0.75rem;padding:5px 12px;border:1px solid var(--rule);cursor:pointer;background:var(--bg);">Print / PDF</button>
</div>
<main>
  <h1>Output Security Report</h1>
  <p style="color:var(--muted);font-family:var(--mono);font-size:0.78rem;">
    ${esc(projectName)} · target: ${esc(targetLang)} · generated ${esc(now)}
  </p>

  <h2>Dependency CVEs <span style="font-family:var(--mono);font-size:0.75rem;font-weight:400;color:var(--muted);">via Trivy — generated output code</span></h2>
  ${trivyHtml}

  ${reviewHtml}
</main>
</body>
</html>`;

const reportsDir = path.join(runDir, 'reports');
if (!fs.existsSync(reportsDir)) fs.mkdirSync(reportsDir, { recursive: true });
const outPath = outArg || path.join(reportsDir, 'output-security-report.html');
fs.writeFileSync(outPath, html, 'utf8');
console.log(`output-security-report written → ${outPath}`);
