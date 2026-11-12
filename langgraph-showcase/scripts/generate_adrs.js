#!/usr/bin/env node
'use strict';

/**
 * generate_adrs.js
 *
 * Architecture Decision Records — one ADR per fitness function,
 * plus any context_decisions from tnas.json.
 *
 * Usage:
 *   node scripts/generate_adrs.js <run_dir>
 *   node scripts/generate_adrs.js <run_dir> <out>
 */

const fs   = require('fs');
const path = require('path');
const {
  esc, severityBadge, callout, htmlShell, writeReport,
} = require('./report_common');

const args   = process.argv.slice(2);
const runDir = args[0] ? path.resolve(args[0]) : process.cwd();
const outArg = args[1] ? path.resolve(args[1]) : null;

function read(name) {
  const p = path.join(runDir, name);
  if (!fs.existsSync(p)) throw new Error(`Required file not found: ${p}`);
  return JSON.parse(fs.readFileSync(p, 'utf8'));
}

const meta = read('run_meta.json');
const tnas = read('tnas.json');

const projectName   = path.basename(meta.source_path || 'unknown');
const targetLang    = meta.target_lang || '?';
const fitnessObj    = tnas.fitness_suite || {};
// Support both old array format (functions[]) and new object format ({ dimName: "text" })
const fitnessFns    = Array.isArray(fitnessObj.functions) ? fitnessObj.functions : [];
const _FITNESS_META = new Set(['sha','created_at','produced_by','functions','target_language','intended_commit_path']);
const fitnessDims   = typeof fitnessObj === 'object' && !Array.isArray(fitnessObj)
  ? Object.entries(fitnessObj).filter(([k, v]) => typeof v === 'string' && !_FITNESS_META.has(k))
  : [];
const ctxDecisions  = tnas.context_decisions || [];
const archNotes     = tnas.architectural_notes || [];

// Map dimension value prefix to ADR status
function dimStatus(val) {
  const first = (val || '').trim().split(/[\s.]/)[0];
  if (first === 'High')   return 'SATISFIED';
  if (first === 'Medium') return 'PARTIAL';
  if (first === 'Low')    return 'AT RISK';
  return 'UNKNOWN';
}

function statusStyle(status) {
  if (status === 'SATISFIED') return 'background:#EAF4EA;color:#2E7D32;border:1px solid #B8DDB8';
  if (status === 'PARTIAL')   return 'background:#FEF3E2;color:#A0522D;border:1px solid #F5DFB8';
  if (status === 'AT RISK')   return 'background:#FDECEA;color:#C0392B;border:1px solid #F5C6C2';
  return 'background:#F5F5F5;color:#666;border:1px solid #DDD';
}

function statusBadge(status) {
  return `<span style="display:inline-block;padding:2px 7px;border-radius:2px;font-family:'IBM Plex Mono',monospace;font-size:11px;text-transform:uppercase;letter-spacing:0.04em;${statusStyle(status)}">${esc(status)}</span>`;
}

// Find relevant arch notes for a dimension by keyword matching
function relatedNotes(dimKey) {
  const keywords = dimKey.toLowerCase().split('_');
  return archNotes.filter(n => {
    const concern = (n.concern || '').toLowerCase();
    return keywords.some(kw => kw.length > 3 && concern.includes(kw));
  });
}

function specExplain(spec) {
  if (!spec) return '';
  const [rule, ...rest] = spec.split(':');
  switch (rule) {
    case 'no_primitive_type_on_field_role':
      return `Fields with role <code>${esc(rest[0])}</code> must not use primitive types <code>${esc(rest[1])}</code>.`;
    case 'no_direct_dependency':
      return `Module <code>${esc(rest[0])}</code> must not import <code>${esc(rest[1])}</code> directly.`;
    case 'command_return_type_in':
      return `Command methods must return one of: <code>${esc(rest.join(':'))}</code>.`;
    case 'state_transition_via':
      return `All state transitions must pass through: <code>${esc(rest.join(':'))}</code>.`;
    case 'no_database_access_outside':
      return `Database access is only permitted inside: <code>${esc(rest.join(':'))}</code>.`;
    default:
      return `<code>${esc(spec)}</code>`;
  }
}

let adrIndex = 0;

// ADR cards from old-format fitnessFns array (if present)
const legacyAdrSections = fitnessFns.map(fn => {
  adrIndex++;
  const num = String(adrIndex).padStart(3, '0');
  return `
  <section id="adr-${num}" style="margin:0 0 48px;padding:0 0 48px;border-bottom:1px solid #E6EAE6">
    <div style="display:flex;align-items:baseline;gap:12px;margin-bottom:8px">
      <span style="font-family:'IBM Plex Mono',monospace;font-size:12px;color:#91969C">ADR-${esc(num)}</span>
      ${severityBadge(fn.severity)}
    </div>
    <h2 class="section" style="margin-top:0">${esc(fn.name)}</h2>

    <h3 class="subsection">Status</h3>
    <p>Accepted — BLOCKING. All pull requests to the ${esc(targetLang)} target must pass this rule.</p>
    <p class="stat-line">Derived from: ${esc(fn.derived_from || '—')}</p>

    <h3 class="subsection">Context</h3>
    <p>${esc(fn.description)}</p>
    <p>Constraint spec: ${specExplain(fn.spec)}</p>

    <h3 class="subsection">Decision</h3>
    <div class="panel">${esc(fn.spec)}</div>

    <h3 class="subsection">Consequences</h3>
    <p>${esc(fn.rationale)}</p>
  </section>`;
}).join('');

// ADR cards from new-format fitness_suite object entries
const dimAdrSections = fitnessDims.map(([dimKey, dimVal]) => {
  adrIndex++;
  const num    = String(adrIndex).padStart(3, '0');
  const title  = dimKey.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
  const status = dimStatus(dimVal);
  const notes  = relatedNotes(dimKey);
  const notesHtml = notes.length
    ? `<h3 class="subsection">Related architectural notes</h3>` +
      notes.map(n => `<p><strong>${esc(n.concern)}</strong>${n.placement ? ` — ${esc(n.placement)}` : ''}${n.seam_location ? ` (seam: ${esc(n.seam_location)})` : ''}</p>`).join('')
    : '';
  return `
  <section id="adr-${num}" style="margin:0 0 48px;padding:0 0 48px;border-bottom:1px solid #E6EAE6">
    <div style="display:flex;align-items:baseline;gap:12px;margin-bottom:8px">
      <span style="font-family:'IBM Plex Mono',monospace;font-size:12px;color:#91969C">ADR-${esc(num)}</span>
      ${statusBadge(status)}
    </div>
    <h2 class="section" style="margin-top:0">${esc(title)}</h2>

    <h3 class="subsection">Status</h3>
    <p>${statusBadge(status)}</p>

    <h3 class="subsection">Body</h3>
    <p>${esc(dimVal)}</p>

    ${notesHtml}
  </section>`;
}).join('');

const adrSections = legacyAdrSections + dimAdrSections;

// Architectural notes section (all notes, not just related ones)
const archNotesSections = archNotes.length
  ? archNotes.map((n, i) => {
      const body = n.placement || n.seam_location || '';
      return `
  <section style="margin:0 0 32px;padding:0 0 32px;border-bottom:1px solid #E6EAE6">
    <h2 class="section" style="margin-top:0">${esc(n.concern || `Note ${i + 1}`)}</h2>
    ${body ? `<div class="panel">${esc(body)}</div>` : ''}
  </section>`;
    }).join('')
  : `<p style="color:#91969C">No architectural notes recorded in this run.</p>`;

const ctxDecisionSections = ctxDecisions.length > 0
  ? ctxDecisions.map(d => {
      adrIndex++;
      const num = String(adrIndex).padStart(3, '0');
      return `
  <section id="adr-${num}" style="margin:0 0 48px;padding:0 0 48px;border-bottom:1px solid #E6EAE6">
    <div style="margin-bottom:8px">
      <span style="font-family:'IBM Plex Mono',monospace;font-size:12px;color:#91969C">ADR-${esc(num)} · Context decision</span>
    </div>
    <h2 class="section" style="margin-top:0">${esc(d.context || 'Context decision')}</h2>
    <h3 class="subsection">Status</h3>
    <p>Accepted.</p>
    <h3 class="subsection">Decision</h3>
    <p>${esc(d.rationale || d.decision || JSON.stringify(d))}</p>
  </section>`;
    }).join('')
  : `<div style="background:#F2F4F2;padding:24px;border-left:3px solid #C5CBC5;margin:16px 0">
      <p style="margin:0;color:#91969C;font-family:'IBM Plex Mono',monospace;font-size:12px">
        No context decisions were recorded in this run. Context-level architectural decisions
        (e.g. deployment targets, communication styles) should be added in a follow-up
        architect review once the bounded context map has been human-approved.
      </p>
    </div>`;

const totalAdrCount = fitnessFns.length + fitnessDims.length;
const bodyHtml = `
<div class="metric-row" style="grid-template-columns:repeat(3,1fr)">
  <div class="metric-card"><div class="metric-value">${esc(totalAdrCount)}</div><div class="metric-label">Fitness ADRs</div></div>
  <div class="metric-card"><div class="metric-value">${esc(ctxDecisions.length)}</div><div class="metric-label">Context decisions</div></div>
  <div class="metric-card"><div class="metric-value">${esc(archNotes.length)}</div><div class="metric-label">Architectural notes</div></div>
</div>

<section id="intro">
  <h1 class="chapter">About these ADRs</h1>
  <hr class="chapter-rule">
  <p>These Architecture Decision Records codify the non-negotiable rules for the
  <strong>${esc(targetLang)}</strong> target codebase. Each rule was derived from static analysis
  of the source ${esc(meta.source_lang || '?')} system and industry-standard DDD/hexagonal patterns.
  They are enforced in CI on every PR for the duration of the migration engagement.</p>
  <p>BLOCKING rules must pass before any pull request merges. WARNING rules generate CI warnings.
  INFO rules are advisory only.</p>
</section>

<section id="fitness-adrs">
  <h1 class="chapter">Fitness function ADRs</h1>
  <hr class="chapter-rule">
  ${adrSections || '<p style="color:#91969C">No fitness functions recorded in this run.</p>'}
</section>

<section id="context-decisions">
  <h1 class="chapter">Context decisions</h1>
  <hr class="chapter-rule">
  ${ctxDecisionSections}
</section>

<section id="architectural-notes">
  <h1 class="chapter">Architectural Notes</h1>
  <hr class="chapter-rule">
  ${archNotesSections}
</section>
`;

const adrNavLinks = [];
fitnessFns.forEach((fn, i) => {
  const num = String(i + 1).padStart(3, '0');
  adrNavLinks.push([`#adr-${num}`, `ADR-${num}`]);
});
fitnessDims.forEach(([dimKey], i) => {
  const num = String(fitnessFns.length + i + 1).padStart(3, '0');
  adrNavLinks.push([`#adr-${num}`, `ADR-${num}`]);
});

const html = htmlShell({
  title:      `${projectName} — Architecture decisions`,
  projectName,
  reportType: 'Architecture decision records',
  navLinks:   [['#intro','Intro'],['#fitness-adrs','Fitness ADRs'],['#context-decisions','Context decisions'],['#architectural-notes','Arch Notes'], ...adrNavLinks.slice(0,5)],
  bodyHtml,
});

writeReport(html, 'architecture-decisions.html', runDir, outArg);
