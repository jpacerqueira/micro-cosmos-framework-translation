#!/usr/bin/env node
'use strict';

/**
 * report_common.js
 *
 * Shared design system and helpers for all Micro-Cosmos report generators.
 * Extracted from generate_synthesis.js — the canonical template.
 */

// ── HTML helpers ──────────────────────────────────────────────────────────────

function esc(s) {
  if (s === null || s === undefined) return '';
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function countBy(arr, fn) {
  return arr.reduce((acc, x) => {
    const k = fn(x); acc[k] = (acc[k] || 0) + 1; return acc;
  }, {});
}

function riskBadge(risk) {
  const r = (risk || '').toUpperCase();
  const styles = {
    HIGH:   'background:#FDECEA;color:#C0392B;border:1px solid #F5C6C2',
    MEDIUM: 'background:#FEF3E2;color:#A0522D;border:1px solid #F5DFB8',
    LOW:    'background:#EAF4EA;color:#2E7D32;border:1px solid #B8DDB8',
  };
  const style = styles[r] || styles.LOW;
  return `<span style="display:inline-block;padding:2px 7px;border-radius:2px;font-family:'IBM Plex Mono',monospace;font-size:11px;text-transform:uppercase;letter-spacing:0.04em;${style}">${esc(r || 'LOW')}</span>`;
}

function severityBadge(sev) {
  const s = (sev || '').toUpperCase();
  const styles = {
    BLOCKING: 'background:#FDECEA;color:#C0392B;border:1px solid #F5C6C2',
    WARNING:  'background:#FEF3E2;color:#A0522D;border:1px solid #F5DFB8',
    INFO:     'background:#EAF4EA;color:#2E7D32;border:1px solid #B8DDB8',
  };
  const style = styles[s] || styles.INFO;
  return `<span style="display:inline-block;padding:2px 7px;border-radius:2px;font-family:'IBM Plex Mono',monospace;font-size:11px;text-transform:uppercase;letter-spacing:0.04em;${style}">${esc(sev || 'INFO')}</span>`;
}

function confidenceBadge(conf) {
  const c = String(conf || '').toUpperCase();
  const styles = {
    HIGH:   'background:#EAF4EA;color:#2E7D32;border:1px solid #B8DDB8',
    MEDIUM: 'background:#FEF3E2;color:#A0522D;border:1px solid #F5DFB8',
    LOW:    'background:#F5F5F5;color:#666;border:1px solid #DDD',
  };
  const style = styles[c] || styles.LOW;
  return `<span style="display:inline-block;padding:2px 7px;border-radius:2px;font-family:'IBM Plex Mono',monospace;font-size:11px;text-transform:uppercase;letter-spacing:0.04em;${style}">${esc(conf || 'LOW')}</span>`;
}

function cap(text, maxSentences) {
  if (!text) return '';
  const sentences = text.match(/[^.!?]+[.!?]+/g) || [text];
  return sentences.slice(0, maxSentences).join(' ').trim();
}

function tableCaption(text) {
  return `<p style="font-family:'IBM Plex Mono',monospace;font-size:11px;color:#91969C;text-transform:uppercase;letter-spacing:0.08em;margin:32px 0 6px;">${esc(text)}</p>`;
}

function callout(html, type) {
  const borderColor = type === 'warn' ? '#ED3A12' : '#C5CBC5';
  const bg          = type === 'warn' ? '#FEF3E2' : '#EAF4EA';
  return `<div style="background:${bg};border-left:3px solid ${borderColor};padding:14px 18px;margin:20px 0;font-family:'Inter Tight',sans-serif;font-size:14px;">${html}</div>`;
}

function stripPrefix(loc, projectName) {
  if (!loc) return '';
  const withoutLine = loc.replace(/:\d+$/, '');
  const marker = `/${projectName}/`;
  const idx = withoutLine.indexOf(marker);
  if (idx !== -1) return withoutLine.slice(idx + marker.length);
  return require('path').basename(withoutLine);
}

// ── Shared CSS ────────────────────────────────────────────────────────────────

const CSS = `
:root {
  --color-dark:   #171D1D;
  --color-muted:  #91969C;
  --color-sage:   #E6EAE6;
  --color-accent: #ED3A12;
  --color-white:  #FFFFFF;
  --color-bg:     #F9FAF9;
  --color-panel:  #F2F4F2;
}

*, *::before, *::after { box-sizing: border-box; }

body {
  background: var(--color-bg);
  color: var(--color-dark);
  font-family: 'Inter Tight', sans-serif;
  font-size: 15px;
  line-height: 1.65;
  margin: 0;
  padding-top: 52px;
}

/* ── Navigation ── */
.nav {
  position: fixed; top: 0; left: 0; right: 0; z-index: 100;
  background: var(--color-white); border-bottom: 1px solid var(--color-sage);
  display: flex; align-items: center; height: 52px; padding: 0 32px; gap: 24px;
}
.nav-brand { display: flex; align-items: baseline; gap: 8px; flex-shrink: 0; }
.nav-brand-name { font-family: 'Instrument Serif', serif; font-size: 18px;
                  color: var(--color-dark); text-decoration: none; }
.nav-brand-project { font-family: 'IBM Plex Mono', monospace; font-size: 12px;
                     color: var(--color-muted); }
.nav-links { display: flex; gap: 20px; list-style: none; margin: 0; padding: 0; }
.nav-links a { font-family: 'Inter Tight', sans-serif; font-size: 12px;
               color: var(--color-muted); text-decoration: none;
               text-transform: uppercase; letter-spacing: 0.06em; white-space: nowrap; }
.nav-links a:hover { color: var(--color-dark); }
.download-btn {
  position: absolute; right: 32px; top: 50%; transform: translateY(-50%);
  font-family: 'IBM Plex Mono', monospace; font-size: 11px;
  text-transform: uppercase; letter-spacing: 0.07em;
  background: var(--color-dark); color: var(--color-white);
  border: none; padding: 8px 16px; cursor: pointer; flex-shrink: 0;
}
.download-btn:hover { background: #2D3535; }

/* ── Document ── */
.document { max-width: 900px; margin: 0 auto; padding: 48px 40px 120px; }

/* ── Cover ── */
.cover { padding-bottom: 64px; border-bottom: 1px solid var(--color-sage); margin-bottom: 56px; }
.cover-eyebrow { font-family: 'IBM Plex Mono', monospace; font-size: 12px;
                 color: var(--color-muted); text-transform: uppercase;
                 letter-spacing: 0.10em; margin: 0 0 20px; }
.cover-title { font-family: 'Instrument Serif', serif; font-size: 56px;
               font-weight: 400; color: var(--color-dark); line-height: 1.08;
               margin: 0 0 16px; }
.cover-rule { width: 48px; height: 2px; background: var(--color-accent); margin: 0 0 20px; }
.cover-meta { font-family: 'IBM Plex Mono', monospace; font-size: 13px;
              color: var(--color-dark); margin: 0 0 48px; }
.cover-confidential { font-family: 'IBM Plex Mono', monospace; font-size: 11px;
                      color: var(--color-muted); text-transform: uppercase;
                      letter-spacing: 0.08em; margin: 0; }

/* ── Headings ── */
h1.chapter { font-family: 'Instrument Serif', serif; font-size: 38px; font-weight: 400;
             color: var(--color-dark); padding-top: 56px; margin: 0 0 10px; line-height: 1.15; }
.chapter-rule { height: 2px; background: var(--color-accent); border: none; margin: 0 0 32px; }
h2.section { font-family: 'Instrument Serif', serif; font-size: 24px; font-weight: 400;
             color: var(--color-dark); margin: 40px 0 8px; }
h3.subsection { font-family: 'Inter Tight', sans-serif; font-size: 15px; font-weight: 600;
                color: var(--color-dark); margin: 28px 0 6px; }

/* ── Body ── */
p { margin: 0 0 14px; }
.stat-line { font-family: 'IBM Plex Mono', monospace; font-size: 11px;
             color: var(--color-muted); text-transform: uppercase;
             letter-spacing: 0.07em; margin: 4px 0 10px; }

/* ── Metric cards ── */
.metric-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin: 32px 0; }
.metric-card { background: var(--color-white); border: 1px solid var(--color-sage); padding: 20px 24px; }
.metric-value { font-family: 'Instrument Serif', serif; font-size: 36px;
                color: var(--color-dark); line-height: 1; }
.metric-label { font-family: 'IBM Plex Mono', monospace; font-size: 11px;
                color: var(--color-muted); text-transform: uppercase;
                letter-spacing: 0.07em; margin-top: 6px; }

/* ── Tables ── */
table { width: 100%; border-collapse: collapse; font-family: 'IBM Plex Mono', monospace;
        font-size: 12px; margin: 6px 0 32px; }
thead tr { background: var(--color-dark); color: var(--color-white); }
thead th { padding: 10px 12px; text-align: left; font-weight: 500;
           text-transform: uppercase; letter-spacing: 0.04em; }
tbody tr { border-bottom: 1px solid var(--color-sage); }
tbody td { padding: 9px 12px; vertical-align: top; }
tbody tr:last-child { border-bottom: none; }
tbody tr:hover { background: var(--color-panel); }

/* ── Code blocks ── */
pre { background: var(--color-dark); color: #E8EDEC; border-radius: 4px;
      padding: 20px 24px; font-family: 'IBM Plex Mono', monospace; font-size: 12px;
      line-height: 1.6; overflow-x: auto; margin: 12px 0 28px;
      white-space: pre; tab-size: 4; }
code { font-family: 'IBM Plex Mono', monospace; font-size: 12px;
       background: var(--color-panel); padding: 1px 5px; border-radius: 2px; }

/* ── Sage panel ── */
.panel { background: var(--color-sage); border-left: 3px solid #C5CBC5;
         padding: 16px 20px; font-family: 'IBM Plex Mono', monospace;
         font-size: 12px; color: var(--color-dark); margin: 16px 0 24px;
         white-space: pre-wrap; word-break: break-all; }

/* ── Bar chart ── */
.bar-wrap { display: flex; align-items: center; gap: 8px; }
.bar { height: 8px; border-radius: 2px; background: var(--color-accent); min-width: 2px; }

/* ── Steps list ── */
.steps-list { margin: 0; padding: 0 0 0 16px; font-size: 11px; line-height: 1.5; }
.steps-list li { margin: 2px 0; }
`.trim();

const PRINT_CSS = `
@media print {
  .nav { display: none !important; }
  body { padding-top: 0; }
  .document { max-width: 100%; }
  h1.chapter { break-before: page; }
  .cover { break-after: page; }
  a::after { content: " (" attr(href) ")"; font-size: 10px; color: #666; }
}
`.trim();

// ── Shell builder ──────────────────────────────────────────────────────────────

function htmlShell({ title, projectName, reportType, navLinks, bodyHtml }) {
  const today = new Date().toLocaleDateString('en-GB', { year: 'numeric', month: 'long', day: 'numeric' });
  const navItems = (navLinks || [])
    .map(([href, label]) => `<li><a href="${esc(href)}">${esc(label)}</a></li>`)
    .join('');
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>${esc(title)}</title>
  <link href="https://fonts.googleapis.com/css2?family=Instrument+Serif&family=Inter+Tight:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
  <style>${CSS}</style>
  <style media="print">${PRINT_CSS}</style>
</head>
<body>
<nav class="nav">
  <div class="nav-brand">
    <span class="nav-brand-name">Micro-Cosmos</span>
    <span class="nav-brand-project">· ${esc(projectName)}</span>
  </div>
  ${navItems ? `<ul class="nav-links">${navItems}</ul>` : ''}
  <button onclick="window.print()" class="download-btn">↓ Download PDF</button>
</nav>
<div class="document">
<div class="cover">
  <p class="cover-eyebrow">${esc(reportType)}</p>
  <h1 class="cover-title">${esc(projectName)}</h1>
  <div class="cover-rule"></div>
  <p class="cover-meta">${esc(today)}</p>
  <p class="cover-confidential">Micro-Cosmos · CONFIDENTIAL</p>
</div>
${bodyHtml}
</div>
</body>
</html>`;
}

// ── BCM helpers ───────────────────────────────────────────────────────────────

/**
 * Normalise bounded_context_map.json to a flat array of
 * { name, node_ids[], confidence, cross_context_calls } and a deduplicated
 * cross_context_calls list [[src, tgt], ...].
 *
 * Handles both:
 *   - New format: { contexts: [{name, node_ids, confidence, ...}], cross_context_calls: [[a,b]] }
 *   - Old format: { bounded_contexts: [{contexts:[name], node_ids:[], cross_context_calls:[{src_ctx,tgt_ctx}]}] }
 */
function normaliseBCM(bcm) {
  if (!bcm) return { contexts: [], crossContextCalls: [] };

  // New top-level format
  if (Array.isArray(bcm.contexts) && bcm.contexts.length > 0 && bcm.contexts[0].name) {
    const calls = (bcm.cross_context_calls || []).map(c =>
      Array.isArray(c) ? c : [c.src_ctx || c[0], c.tgt_ctx || c[1]]
    );
    return { contexts: bcm.contexts, crossContextCalls: calls };
  }

  // Old nested format
  if (Array.isArray(bcm.bounded_contexts)) {
    const contexts = [];
    const callsSet = new Set();
    const calls    = [];
    for (const bc of bcm.bounded_contexts) {
      const names = Array.isArray(bc.contexts) ? bc.contexts : [bc.contexts];
      for (const name of names) {
        contexts.push({
          name,
          node_ids:   bc.node_ids || [],
          confidence: bc.confidence || 0,
          rationale:  bc.rationale || '',
        });
      }
      for (const cc of (bc.cross_context_calls || [])) {
        const src = cc.src_ctx || cc[0];
        const tgt = cc.tgt_ctx || cc[1];
        const key = `${src}→${tgt}`;
        if (!callsSet.has(key)) { callsSet.add(key); calls.push([src, tgt]); }
      }
    }
    return { contexts, crossContextCalls: calls };
  }

  return { contexts: [], crossContextCalls: [] };
}

// ── Output writer ─────────────────────────────────────────────────────────────

function writeReport(html, defaultName, runDir, outArg) {
  const fs   = require('fs');
  const path = require('path');

  // Basic sanity checks
  if (html.includes('>[object Object]<') || />\s*undefined\s*</.test(html)) {
    console.error('ERROR: bad interpolation detected in output');
    process.exit(1);
  }

  const outPath = outArg || path.join(runDir, defaultName);
  fs.writeFileSync(outPath, html, 'utf8');
  console.log(`Written: ${outPath} (${html.length} bytes)`);

  const outputsDir = '/mnt/user-data/outputs';
  if (fs.existsSync(outputsDir)) {
    fs.writeFileSync(path.join(outputsDir, defaultName), html, 'utf8');
    console.log(`Copied to ${outputsDir}/${defaultName}`);
  }
}

// ── Exports ───────────────────────────────────────────────────────────────────

module.exports = {
  esc,
  countBy,
  riskBadge,
  severityBadge,
  confidenceBadge,
  cap,
  tableCaption,
  callout,
  stripPrefix,
  normaliseBCM,
  htmlShell,
  writeReport,
  CSS,
  PRINT_CSS,
};
