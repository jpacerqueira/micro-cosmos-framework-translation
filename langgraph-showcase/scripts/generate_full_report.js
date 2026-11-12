#!/usr/bin/env node
'use strict';

/**
 * generate_full_report.js
 *
 * Combined status + content report — sits last in the Reports menu. A status
 * table at the top lists every other HTML report, every *.json artifact, and
 * the Kiro Powers / OpenSpec / Claude Code Skills output, in the same
 * top-to-bottom order the Reports menu lists them. Below that: the full
 * content of everything the table lists.
 *
 * Design choices (see transferable-skills/memory for the full rationale):
 *   - The 13 other HTML reports are embedded via <iframe src="{filename}">,
 *     not merged by extracting their inner markup — 4 of the 13 report
 *     scripts predate report_common.js's shared htmlShell and inline their
 *     own HTML, so a merge-by-extraction approach would need per-script
 *     special-casing and could silently break for a future report script.
 *     An iframe just points at the sibling file (relative path — resolves
 *     correctly both when served live via /runs/{id}/files/{filename} AND
 *     when full-app-migration-report.html is opened directly from an extracted full.zip,
 *     since every report lands as a flat sibling file under reports/).
 *   - Kiro/Skills/OpenSpec markdown files render as raw text in a <pre>
 *     block, not rendered Markdown->HTML — no Markdown-rendering dependency
 *     exists anywhere in this codebase's report scripts today.
 *   - Every embedded report/file sits inside a collapsed <details> so the
 *     page is scannable rather than one huge wall of content by default.
 *   - Always regenerated on every view (see run_file()'s special-case in
 *     app.py) — its only value is being an accurate live snapshot.
 *
 * Usage:
 *   node scripts/generate_full_report.js <run_dir> [<out>]
 */

const fs   = require('fs');
const path = require('path');
const { esc, htmlShell, writeReport } = require('./report_common');

const args   = process.argv.slice(2);
const runDir = args[0] ? path.resolve(args[0]) : process.cwd();
const outArg = args[1] ? path.resolve(args[1]) : null;
const reportsDir = path.join(runDir, 'reports');

function readOpt(name) {
  const p = path.join(runDir, name);
  return fs.existsSync(p) ? JSON.parse(fs.readFileSync(p, 'utf8')) : null;
}

const meta = readOpt('run_meta.json') || {};
const projectName = path.basename(meta.source_path || 'unknown');

// ── 1. HTML reports, in Reports-menu order ──────────────────────────────────

const HTML_REPORTS = [
  ['executive-summary.html', 'Executive summary'],
  ['migration-briefing.html', 'Migration briefing'],
  ['project-synthesis.html', 'Project synthesis'],
  ['hotspots.html', 'Hotspots & coupling'],
  ['dead-code.html', 'Dead code & waste'],
  ['architecture-decisions.html', 'Architecture decisions'],
  ['fitness-stubs.html', 'Fitness test stubs'],
  ['monitoring.html', 'Telemetry gap analysis'],
  ['security-report.html', 'Source security analysis'],
  ['output-security-report.html', 'Output security scan'],
  ['ir-graph.html', 'IR graph'],
  ['sprint-plan.html', 'Migration sprint plan'],
  ['feature-specs.html', 'Build output features'],
];

// ── 2. Data artifacts (*.json), run_dir root ─────────────────────────────────

const JSON_ARTIFACTS = [
  ['run_meta.json', 'Run metadata'],
  ['ir_graph.json', 'IR property graph'],
  ['bounded_context_map.json', 'Bounded context map'],
  ['seam.json', 'Seam report'],
  ['work_streams.json', 'Work streams'],
  ['tnas.json', 'Target-native architecture spec (TNAS)'],
  ['trivy_report.json', 'Source Trivy scan'],
  ['security_report.json', 'Security findings'],
  ['feature_specs.json', 'Feature specs'],
  ['feature_specs_result.json', 'Feature specs (raw agent output)'],
  ['seam_result.json', 'Seam translation result — most recent seam only'],
  ['skeptical_review.json', 'Skeptical review — most recent seam only'],
  ['test_review.json', 'Test review — most recent seam only'],
  ['functional_review.json', 'Functional review — most recent seam only'],
  ['write_manifest.json', 'Write manifest'],
  ['review_report.json', 'PR review report'],
  ['trivy_output_report.json', 'Output Trivy scan'],
];

// ── 3. Generated exports (reports/) ──────────────────────────────────────────

const EXPORTS = [
  ['openapi.yaml', 'OpenAPI 3.1 spec'],
  ['jira_bulk_import.json', 'Jira bulk import'],
];

function existsInReports(relPath) {
  return fs.existsSync(path.join(reportsDir, relPath));
}
function existsInRoot(relPath) {
  return fs.existsSync(path.join(runDir, relPath));
}

// ── Kiro.dev Powers ───────────────────────────────────────────────────────────

const KIRO_DIR = path.join(reportsDir, 'kiro-dev-powers-app-modernization');
let kiroPowers = [];
if (fs.existsSync(KIRO_DIR)) {
  kiroPowers = fs.readdirSync(KIRO_DIR, { withFileTypes: true })
    .filter((e) => e.isDirectory())
    .map((e) => e.name)
    .sort()
    .map((name) => ({
      name,
      powerMd: path.join(KIRO_DIR, name, 'POWER.md'),
    }));
}

// ── Claude Code skills ────────────────────────────────────────────────────────

let skillsDirName = null;
let skillFiles = [];
if (fs.existsSync(reportsDir)) {
  const skillsEntry = fs.readdirSync(reportsDir, { withFileTypes: true })
    .find((e) => e.isDirectory() && e.name.endsWith('_skills'));
  if (skillsEntry) {
    skillsDirName = skillsEntry.name;
    const cmdDir = path.join(reportsDir, skillsDirName, '.claude', 'commands');
    if (fs.existsSync(cmdDir)) {
      skillFiles = fs.readdirSync(cmdDir)
        .filter((f) => f.endsWith('.md'))
        .sort()
        .map((f) => path.join(cmdDir, f));
    }
    const claudeMd = path.join(reportsDir, skillsDirName, 'CLAUDE.md');
    if (fs.existsSync(claudeMd)) skillFiles.push(claudeMd);
  }
}

// ── OpenSpec ──────────────────────────────────────────────────────────────────

const OPENSPEC_DIR = path.join(reportsDir, 'openspec');
function walkMarkdown(dir) {
  if (!fs.existsSync(dir)) return [];
  let out = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out = out.concat(walkMarkdown(full));
    else if (entry.name.endsWith('.md')) out.push(full);
  }
  return out;
}
const openspecFiles = walkMarkdown(OPENSPEC_DIR).sort();

// ── Status table ──────────────────────────────────────────────────────────────

function statusRow(label, present, link) {
  const badge = present
    ? '<span style="color:#2E7D32;font-weight:600;">Generated</span>'
    : '<span style="color:#91969C;">Not yet generated</span>';
  const cell = present && link ? `<a href="${esc(link)}">${esc(label)}</a>` : esc(label);
  return `<tr><td>${cell}</td><td>${badge}</td></tr>`;
}
function sectionRow(label) {
  return `<tr><td colspan="2"><strong>${esc(label)}</strong></td></tr>`;
}

let tableRows = '';
tableRows += sectionRow('HTML reports');
for (const [file, label] of HTML_REPORTS) tableRows += statusRow(label, existsInReports(file), file);
tableRows += sectionRow('Data artifacts (*.json)');
for (const [file, label] of JSON_ARTIFACTS) tableRows += statusRow(label, existsInRoot(file), null);
tableRows += sectionRow('Generated exports');
for (const [file, label] of EXPORTS) tableRows += statusRow(label, existsInReports(file), file);
tableRows += sectionRow('Kiro.dev Powers');
if (kiroPowers.length) {
  for (const p of kiroPowers) tableRows += statusRow(p.name, true, null);
} else {
  tableRows += statusRow('Kiro.dev Powers', false, null);
}
tableRows += sectionRow('OpenSpec');
tableRows += statusRow('openspec/', openspecFiles.length > 0, null);
tableRows += sectionRow('Claude Code skills');
tableRows += statusRow(skillsDirName || 'Claude Code skills', skillFiles.length > 0, null);

const migrationHtml = `
<h2 class="section">Migration</h2>
<div class="metric-row">
  <div class="metric-card">
    <div class="metric-value">${esc(meta.source_lang || '?')}</div>
    <div class="metric-label">Source language</div>
  </div>
  <div class="metric-card">
    <div class="metric-value">${esc(meta.target_lang || '?')}</div>
    <div class="metric-label">Target language</div>
  </div>
  <div class="metric-card">
    <div class="metric-value">${meta.skip_llm === false ? 'LLM' : 'Deterministic'}</div>
    <div class="metric-label">Run mode</div>
  </div>
</div>
<p class="stat-line">Source path: <code>${esc(meta.source_path || 'unknown')}</code></p>
`;

const tableHtml = `
${migrationHtml}
<h2 class="section">Status</h2>
<p class="stat-line">Seam-scoped artifacts (seam_result.json, skeptical_review.json, test_review.json,
functional_review.json) reflect only the most recently processed seam, not the full TDD-loop history.</p>
<table><tbody>${tableRows}</tbody></table>
`;

// ── Embedded content ────────────────────────────────────────────────────────

function detailsBlock(summary, innerHtml) {
  return `<details style="margin:12px 0;border:1px solid #E6EAE6;padding:0 16px;">`
    + `<summary style="cursor:pointer;font-family:'Inter Tight',sans-serif;font-weight:600;padding:12px 0;">`
    + `${esc(summary)}</summary><div style="padding-bottom:16px;">${innerHtml}</div></details>`;
}
function preBlockFromFile(filePath) {
  let content;
  try {
    content = fs.readFileSync(filePath, 'utf8');
  } catch (e) {
    content = `(could not read ${filePath}: ${e.message})`;
  }
  return `<pre>${esc(content)}</pre>`;
}

let reportsHtml = '<h2 class="section">Reports</h2>';
for (const [file, label] of HTML_REPORTS) {
  if (existsInReports(file)) {
    reportsHtml += detailsBlock(
      label,
      `<iframe src="${esc(file)}" style="width:100%;height:1200px;border:1px solid #E6EAE6;"></iframe>`,
    );
  } else {
    reportsHtml += detailsBlock(label, `<p><a href="${esc(file)}">Not yet generated — click to generate</a></p>`);
  }
}

let kiroHtml = '<h2 class="section">Kiro.dev Powers</h2>';
if (kiroPowers.length) {
  for (const p of kiroPowers) {
    const inner = fs.existsSync(p.powerMd) ? preBlockFromFile(p.powerMd) : '<p>POWER.md not found.</p>';
    kiroHtml += detailsBlock(p.name, inner);
  }
} else {
  kiroHtml += '<p>Not yet generated.</p>';
}

let skillsHtml = '<h2 class="section">Claude Code skills</h2>';
if (skillFiles.length) {
  for (const f of skillFiles) {
    skillsHtml += detailsBlock(path.relative(reportsDir, f), preBlockFromFile(f));
  }
} else {
  skillsHtml += '<p>Not yet generated.</p>';
}

let openspecHtml = '<h2 class="section">OpenSpec</h2>';
if (openspecFiles.length) {
  for (const f of openspecFiles) {
    openspecHtml += detailsBlock(path.relative(OPENSPEC_DIR, f), preBlockFromFile(f));
  }
} else {
  openspecHtml += '<p>Not yet generated.</p>';
}

const bodyHtml = tableHtml + reportsHtml + kiroHtml + skillsHtml + openspecHtml;

const html = htmlShell({
  title: `Full report — ${projectName}`,
  projectName,
  reportType: 'Full Report',
  navLinks: [],
  bodyHtml,
});

writeReport(html, 'full-app-migration-report.html', runDir, outArg);
