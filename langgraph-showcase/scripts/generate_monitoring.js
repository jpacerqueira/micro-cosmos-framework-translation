#!/usr/bin/env node
'use strict';

/**
 * generate_monitoring.js
 *
 * Reads pipeline output files and writes a self-contained HTML monitoring
 * gap analysis report. Scores the legacy source for observability maturity
 * across five dimensions and identifies OpenTelemetry adoption gaps.
 *
 * Usage:
 *   node scripts/generate_monitoring.js <run_dir>          (write to run_dir)
 *   node scripts/generate_monitoring.js <run_dir> <out>    (write to <out>)
 */

const fs   = require('fs');
const path = require('path');

// ── Resolve paths ─────────────────────────────────────────────────────────────

const args   = process.argv.slice(2);
const runDir = args[0] ? path.resolve(args[0]) : process.cwd();
const outArg = args[1] ? path.resolve(args[1]) : null;

function tryRead(name) {
  const p = path.join(runDir, name);
  if (!fs.existsSync(p)) return null;
  try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch { return null; }
}

const meta     = tryRead('run_meta.json') || {};
const ir       = tryRead('ir_graph.json') || { nodes: [], edges: [] };
const tnas     = tryRead('tnas.json') || { services: [] };
const bcm      = tryRead('bounded_context_map.json') || { contexts: [] };
const security = tryRead('security_report.json') || {};

// ── Project metadata ──────────────────────────────────────────────────────────

const projectName = path.basename(meta.source_path || 'unknown');
const sourceLang  = meta.source_lang || 'unknown';
const targetLang  = meta.target_lang || 'unknown';

// ── Monitoring signal detection ───────────────────────────────────────────────

const nodes    = ir.nodes || [];
const contexts = bcm.contexts || [];
const services = (tnas.services || []).map(s => ({ ...s, service_id: s.service_id || s.name }));

// Patterns that indicate monitoring activity in node IDs, names, or summaries
// JVM: slf4j, log4j, logback, kotlin-logging, scala-logging; .NET: Serilog, NLog, log4net, ILogger; Node.js: pino, winston, bunyan
const LOGGING_PATTERNS   = ['log', 'logger', 'logging', 'slf4j', 'logback', 'log4j', 'serilog', 'nlog', 'log4net', 'ilogger', 'pino', 'winston', 'bunyan', 'zap', 'zerolog', 'structlog', 'logrus', 'scala-logging', 'kotlin-logging'];
// JVM: micrometer; .NET: app.metrics, opentelemetry.instrumentation; Node.js: prom-client, hot-shots
const METRICS_PATTERNS   = ['metric', 'micrometer', 'prometheus', 'counter', 'gauge', 'histogram', 'meter', 'prom', 'statsd', 'influx', 'datadog', 'app.metrics', 'hot-shots', 'telegraf'];
// JVM: opentelemetry, sleuth, zipkin, jaeger; .NET: activitysource, diagnostics.activity; Node.js: @opentelemetry/api
const TRACING_PATTERNS   = ['trace', 'span', 'tracer', 'opentelemetry', 'otel', 'zipkin', 'jaeger', 'sleuth', 'xray', 'dynatrace', 'newrelic', 'appdynamics', 'activitysource', 'diagnostics.activity'];
const HEALTH_PATTERNS    = ['health', 'healthz', 'readiness', 'liveness', 'probe', 'actuator', 'ping', 'status'];
const ALERTING_PATTERNS  = ['alert', 'alarm', 'pagerduty', 'opsgenie', 'notification', 'oncall', 'alertmanager', 'victorops', 'xmatters'];

function matchPatterns(patterns, text) {
  const lower = (text || '').toLowerCase();
  return patterns.some(p => lower.includes(p));
}

function scoreNode(node) {
  const text = [node.id, node.name, node.summary, ...(node.inputs || []).map(i => i.name)].join(' ');
  return {
    logging:  matchPatterns(LOGGING_PATTERNS,  text),
    metrics:  matchPatterns(METRICS_PATTERNS,  text),
    tracing:  matchPatterns(TRACING_PATTERNS,  text),
    health:   matchPatterns(HEALTH_PATTERNS,   text),
    alerting: matchPatterns(ALERTING_PATTERNS, text),
  };
}

// Aggregate signals across all IR nodes
let sig = { logging: 0, metrics: 0, tracing: 0, health: 0, alerting: 0 };
let totalNodes = nodes.length;
nodes.forEach(n => {
  const s = scoreNode(n);
  if (s.logging)  sig.logging++;
  if (s.metrics)  sig.metrics++;
  if (s.tracing)  sig.tracing++;
  if (s.health)   sig.health++;
  if (s.alerting) sig.alerting++;
});

// ── Per-dimension scoring ─────────────────────────────────────────────────────

function dimScore(count, total) {
  if (count === 0) return { score: 0, status: 'absent' };
  const ratio = count / Math.max(total, 1);
  if (ratio >= 0.1) return { score: 20, status: 'covered' };
  return { score: 10, status: 'partial' };
}

const dims = {
  logging:  { ...dimScore(sig.logging,  totalNodes), count: sig.logging  },
  metrics:  { ...dimScore(sig.metrics,  totalNodes), count: sig.metrics  },
  tracing:  { ...dimScore(sig.tracing,  totalNodes), count: sig.tracing  },
  health:   { ...dimScore(sig.health,   totalNodes), count: sig.health   },
  alerting: { ...dimScore(sig.alerting, totalNodes), count: sig.alerting },
};

const totalScore = Object.values(dims).reduce((sum, d) => sum + d.score, 0);

function interpretation(score) {
  if (score >= 80) return { label: 'Production-ready', color: '#2E7D32', bg: '#EAF4EA' };
  if (score >= 60) return { label: 'Adequate',         color: '#A0522D', bg: '#FEF3E2' };
  if (score >= 40) return { label: 'Basic',             color: '#A0522D', bg: '#FEF3E2' };
  if (score >= 20) return { label: 'Insufficient',      color: '#C0392B', bg: '#FDECEA' };
  return                   { label: 'None',              color: '#C0392B', bg: '#FDECEA' };
}

const interp = interpretation(totalScore);

// ── Gap findings ──────────────────────────────────────────────────────────────

const gaps = [];

if (dims.logging.status === 'absent') {
  gaps.push({ severity: 'MAJOR', dimension: 'Logging', description: 'No logging framework detected in the source codebase. Add structured logging (SLF4J+Logback / Serilog / pino) before migrating to microservices.' });
} else if (dims.logging.status === 'partial') {
  gaps.push({ severity: 'MINOR', dimension: 'Logging', description: 'Logging present but limited coverage. Ensure structured logs with trace-context injection (MDC trace_id / correlation-id field).' });
}

if (dims.metrics.status === 'absent') {
  gaps.push({ severity: 'MAJOR', dimension: 'Metrics', description: 'No metrics framework detected. Add Micrometer / prom-client / OpenTelemetry Metrics with a Prometheus or OTLP exporter.' });
} else if (dims.metrics.status === 'partial') {
  gaps.push({ severity: 'MINOR', dimension: 'Metrics', description: 'Partial metrics coverage. Standardise on Micrometer (Java/Kotlin) or prom-client (Node.js) and export to a central metrics store.' });
}

if (dims.tracing.status === 'absent') {
  gaps.push({ severity: totalScore <= 19 ? 'BLOCKER' : 'MAJOR', dimension: 'Tracing', description: 'No distributed tracing detected. Add OpenTelemetry SDK with OTLP exporter and wrap every public service method with a span.' });
} else if (dims.tracing.status === 'partial') {
  gaps.push({ severity: 'MAJOR', dimension: 'Tracing', description: 'Tracing present but incomplete. Ensure W3C TraceContext propagation on all outbound HTTP calls and trace-id injection into log statements.' });
}

if (dims.health.status === 'absent') {
  gaps.push({ severity: 'MAJOR', dimension: 'Health', description: 'No health endpoint detected. Add /health (readiness + liveness) before container/Kubernetes deployment.' });
}

if (dims.alerting.status === 'absent') {
  gaps.push({ severity: 'MINOR', dimension: 'Alerting', description: 'No alert rules detected. Define AlertManager / CloudWatch / PagerDuty rules for error rate, latency p99, and service availability SLOs.' });
}

if (totalScore <= 19) {
  gaps.unshift({ severity: 'BLOCKER', dimension: 'Overall', description: `Monitoring score ${totalScore}/100 is critically low. Microservice deployment is HIGH RISK without basic observability. Do not proceed to Gate 5 until score ≥ 40.` });
}

// ── Per-service gap table ─────────────────────────────────────────────────────

function scoreContext(ctx) {
  const ctxNodes = nodes.filter(n => (ctx.node_ids || []).includes(n.id));
  let s = { logging: 0, metrics: 0, tracing: 0, health: 0, alerting: 0 };
  ctxNodes.forEach(n => {
    const sig = scoreNode(n);
    if (sig.logging)  s.logging++;
    if (sig.metrics)  s.metrics++;
    if (sig.tracing)  s.tracing++;
    if (sig.health)   s.health++;
    if (sig.alerting) s.alerting++;
  });
  const total = ctxNodes.length || 1;
  return {
    name:     ctx.name,
    logging:  dimScore(s.logging,  total).score,
    metrics:  dimScore(s.metrics,  total).score,
    tracing:  dimScore(s.tracing,  total).score,
    health:   dimScore(s.health,   total).score,
    alerting: dimScore(s.alerting, total).score,
  };
}

const perService = contexts.map(scoreContext);

// ── OTel recommendations by target language ───────────────────────────────────

const OTEL_LANG = {
  // JVM stack
  java:       { dep: 'io.opentelemetry:opentelemetry-api:1.37.0',          api: 'GlobalOpenTelemetry.getTracer()',        test: 'InMemorySpanExporter'               },
  java8:      { dep: 'io.opentelemetry:opentelemetry-api:1.37.0',          api: 'GlobalOpenTelemetry.getTracer()',        test: 'InMemorySpanExporter'               },
  java11:     { dep: 'io.opentelemetry:opentelemetry-api:1.37.0',          api: 'GlobalOpenTelemetry.getTracer()',        test: 'InMemorySpanExporter'               },
  java21:     { dep: 'io.opentelemetry:opentelemetry-api:1.37.0',          api: 'GlobalOpenTelemetry.getTracer()',        test: 'InMemorySpanExporter'               },
  kotlin:     { dep: 'io.opentelemetry:opentelemetry-api:1.37.0',          api: 'GlobalOpenTelemetry.getTracer()',        test: 'InMemorySpanExporter'               },
  scala:      { dep: 'io.opentelemetry:opentelemetry-api:1.37.0',          api: 'GlobalOpenTelemetry.getTracer()',        test: 'InMemorySpanExporter'               },
  // .NET stack
  csharp:     { dep: 'OpenTelemetry.Api 1.8.* (NuGet)',                    api: 'ActivitySource.StartActivity()',         test: 'ActivityListener'                   },
  cs:         { dep: 'OpenTelemetry.Api 1.8.* (NuGet)',                    api: 'ActivitySource.StartActivity()',         test: 'ActivityListener'                   },
  fsharp:     { dep: 'OpenTelemetry.Api 1.8.* (NuGet)',                    api: 'ActivitySource.StartActivity()',         test: 'ActivityListener'                   },
  vbnet:      { dep: 'OpenTelemetry.Api 1.8.* (NuGet)',                    api: 'ActivitySource.StartActivity()',         test: 'ActivityListener'                   },
  // Node.js / JavaScript / TypeScript
  typescript: { dep: '@opentelemetry/api ^1.8',                            api: 'trace.getTracer().startActiveSpan()',    test: 'InMemorySpanExporter'               },
  javascript: { dep: '@opentelemetry/api ^1.8',                            api: 'trace.getTracer().startActiveSpan()',    test: 'InMemorySpanExporter'               },
  nodejs:     { dep: '@opentelemetry/api ^1.8',                            api: 'trace.getTracer().startActiveSpan()',    test: 'InMemorySpanExporter'               },
  // Go
  go:         { dep: 'go.opentelemetry.io/otel v1.24.0',                   api: 'otel.Tracer().Start(ctx, name)',         test: 'sdktrace + tracetest'               },
  // Python
  python:     { dep: 'opentelemetry-api==1.24.0 opentelemetry-sdk==1.24.0', api: 'trace.get_tracer()',                   test: 'InMemorySpanExporter'               },
  python3:    { dep: 'opentelemetry-api==1.24.0 opentelemetry-sdk==1.24.0', api: 'trace.get_tracer()',                   test: 'InMemorySpanExporter'               },
};
const otelRec = OTEL_LANG[targetLang.toLowerCase()] || null;

// ── HTML helpers ──────────────────────────────────────────────────────────────

function esc(s) {
  if (s === null || s === undefined) return '';
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function severityBadge(sev) {
  const styles = {
    BLOCKER: 'background:#FDECEA;color:#C0392B;border:1px solid #F5C6C2',
    MAJOR:   'background:#FEF3E2;color:#A0522D;border:1px solid #F5DFB8',
    MINOR:   'background:#EAF4EA;color:#2E7D32;border:1px solid #B8DDB8',
  };
  const style = styles[sev] || styles.MINOR;
  return `<span style="display:inline-block;padding:2px 7px;border-radius:2px;font-family:'IBM Plex Mono',monospace;font-size:11px;text-transform:uppercase;letter-spacing:0.04em;${style}">${esc(sev)}</span>`;
}

function dimStatusBadge(status) {
  const styles = {
    covered: 'background:#EAF4EA;color:#2E7D32',
    partial: 'background:#FEF3E2;color:#A0522D',
    absent:  'background:#FDECEA;color:#C0392B',
  };
  return `<span style="${styles[status] || ''};padding:2px 8px;border-radius:2px;font-family:'IBM Plex Mono',monospace;font-size:11px;">${esc(status)}</span>`;
}

function tableCaption(text) {
  return `<p style="font-family:'IBM Plex Mono',monospace;font-size:11px;color:#91969C;text-transform:uppercase;letter-spacing:0.08em;margin:32px 0 6px;">${esc(text)}</p>`;
}

function scoreCircle(score) {
  const { color, bg } = interpretation(score);
  return `<span style="display:inline-flex;align-items:center;justify-content:center;width:48px;height:48px;border-radius:50%;background:${bg};color:${color};font-family:'Instrument Serif',serif;font-size:20px;font-weight:400;">${esc(score)}</span>`;
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
  --color-panel:  #F2F4F2;
}
*, *::before, *::after { box-sizing: border-box; }
body {
  background: var(--color-bg); color: var(--color-dark);
  font-family: 'Inter Tight', sans-serif; font-size: 15px;
  line-height: 1.65; margin: 0; padding-top: 52px;
}
.nav {
  position: fixed; top: 0; left: 0; right: 0; z-index: 100;
  background: var(--color-white); border-bottom: 1px solid var(--color-sage);
  display: flex; align-items: center; height: 52px; padding: 0 32px; gap: 24px;
}
.nav-brand { display: flex; align-items: baseline; gap: 8px; flex-shrink: 0; }
.nav-brand-name { font-family: 'Instrument Serif', serif; font-size: 18px; color: var(--color-dark); text-decoration: none; }
.nav-brand-project { font-family: 'IBM Plex Mono', monospace; font-size: 12px; color: var(--color-muted); }
.nav-links { display: flex; gap: 20px; list-style: none; margin: 0; padding: 0; }
.nav-links a { font-family: 'Inter Tight', sans-serif; font-size: 12px; color: var(--color-muted); text-decoration: none; text-transform: uppercase; letter-spacing: 0.06em; white-space: nowrap; }
.nav-links a:hover { color: var(--color-dark); }
.download-btn {
  position: absolute; right: 32px; top: 50%; transform: translateY(-50%);
  font-family: 'IBM Plex Mono', monospace; font-size: 11px; text-transform: uppercase;
  letter-spacing: 0.07em; background: var(--color-dark); color: var(--color-white);
  border: none; padding: 8px 16px; cursor: pointer; flex-shrink: 0;
}
.download-btn:hover { background: #2D3535; }
.document { max-width: 900px; margin: 0 auto; padding: 48px 40px 120px; }
.cover { padding-bottom: 64px; border-bottom: 1px solid var(--color-sage); margin-bottom: 56px; }
.cover-eyebrow { font-family: 'IBM Plex Mono', monospace; font-size: 12px; color: var(--color-muted); text-transform: uppercase; letter-spacing: 0.10em; margin: 0 0 20px; }
.cover-title { font-family: 'Instrument Serif', serif; font-size: 56px; font-weight: 400; color: var(--color-dark); line-height: 1.08; margin: 0 0 16px; }
.cover-rule { width: 48px; height: 2px; background: var(--color-accent); margin: 0 0 20px; }
.cover-meta { font-family: 'IBM Plex Mono', monospace; font-size: 13px; color: var(--color-dark); margin: 0 0 48px; }
.cover-confidential { font-family: 'IBM Plex Mono', monospace; font-size: 11px; color: var(--color-muted); text-transform: uppercase; letter-spacing: 0.08em; margin: 0; }
h1.chapter { font-family: 'Instrument Serif', serif; font-size: 38px; font-weight: 400; color: var(--color-dark); padding-top: 56px; margin: 0 0 10px; line-height: 1.15; }
.chapter-rule { height: 2px; background: var(--color-accent); border: none; margin: 0 0 32px; }
h2.section { font-family: 'Instrument Serif', serif; font-size: 24px; font-weight: 400; color: var(--color-dark); margin: 40px 0 8px; }
h3.subsection { font-family: 'Inter Tight', sans-serif; font-size: 15px; font-weight: 600; color: var(--color-dark); margin: 28px 0 6px; }
p { margin: 0 0 14px; }
.metric-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin: 32px 0; }
.metric-card { background: var(--color-white); border: 1px solid var(--color-sage); padding: 20px 24px; }
.metric-value { font-family: 'Instrument Serif', serif; font-size: 36px; color: var(--color-dark); line-height: 1; }
.metric-label { font-family: 'IBM Plex Mono', monospace; font-size: 11px; color: var(--color-muted); text-transform: uppercase; letter-spacing: 0.07em; margin-top: 6px; }
.callout { background: #FEF3E2; border-left: 3px solid var(--color-accent); padding: 14px 18px; margin: 20px 0; font-family: 'Inter Tight', sans-serif; font-size: 14px; }
.callout-blocker { background: #FDECEA; border-left: 3px solid #C0392B; }
.callout strong { color: var(--color-dark); }
table { width: 100%; border-collapse: collapse; font-family: 'IBM Plex Mono', monospace; font-size: 12px; margin: 6px 0 32px; }
thead tr { background: var(--color-dark); color: var(--color-white); }
thead th { padding: 10px 12px; text-align: left; font-weight: 500; text-transform: uppercase; letter-spacing: 0.04em; }
tbody tr { border-bottom: 1px solid var(--color-sage); }
tbody td { padding: 9px 12px; vertical-align: top; }
tbody tr:last-child { border-bottom: none; }
tbody tr:hover { background: var(--color-panel); }
.score-bar-wrap { width: 100%; background: var(--color-sage); height: 8px; border-radius: 2px; }
.score-bar { height: 8px; border-radius: 2px; }
@media print {
  .nav { display: none !important; }
  body { padding-top: 0; }
  .document { max-width: 100%; }
  h1.chapter { break-before: page; }
  .cover { break-after: page; }
}
`.trim();

// ── Section builders ──────────────────────────────────────────────────────────

function buildNav() {
  const today = new Date().toLocaleDateString('en-GB', { year: 'numeric', month: 'long', day: 'numeric' });
  return `
<nav class="nav">
  <div class="nav-brand">
    <span class="nav-brand-name">Micro-Cosmos</span>
    <span class="nav-brand-project">· ${esc(projectName)}</span>
  </div>
  <ul class="nav-links">
    <li><a href="#score">Score</a></li>
    <li><a href="#gaps">Gaps</a></li>
    <li><a href="#services">Services</a></li>
    <li><a href="#otel">OTel Guide</a></li>
    <li><a href="#inventory">Inventory</a></li>
  </ul>
  <button onclick="window.print()" class="download-btn">↓ Download PDF</button>
</nav>`.trim();
}

function buildCover() {
  const today = new Date().toLocaleDateString('en-GB', { year: 'numeric', month: 'long', day: 'numeric' });
  return `
<div class="cover">
  <p class="cover-eyebrow">Monitoring gap analysis</p>
  <h1 class="cover-title">${esc(projectName)}</h1>
  <div class="cover-rule"></div>
  <p class="cover-meta">${esc(sourceLang)} → ${esc(targetLang)} · ${esc(today)}</p>
  <p class="cover-confidential">Micro-Cosmos · CONFIDENTIAL</p>
</div>`.trim();
}

function buildScore() {
  const { label, color, bg } = interp;
  const barColor = color;

  const dimRows = [
    ['Logging',  dims.logging],
    ['Metrics',  dims.metrics],
    ['Tracing',  dims.tracing],
    ['Health',   dims.health],
    ['Alerting', dims.alerting],
  ].map(([name, d]) => `
  <tr>
    <td>${esc(name)}</td>
    <td>${dimStatusBadge(d.status)}</td>
    <td style="text-align:center">${esc(d.score)}/20</td>
    <td>
      <div class="score-bar-wrap">
        <div class="score-bar" style="width:${esc(d.score * 5)}%;background:${d.score >= 20 ? '#2E7D32' : d.score >= 10 ? '#A0522D' : '#C0392B'}"></div>
      </div>
    </td>
    <td>${esc(d.count)} node${d.count !== 1 ? 's' : ''}</td>
  </tr>`).join('');

  const blockerAlert = totalScore <= 19
    ? `<div class="callout callout-blocker"><strong>⚠ BLOCKER:</strong> Monitoring score ${totalScore}/100 — microservice deployment is HIGH RISK without basic observability. Score must reach ≥ 40 before Gate 5 approval.</div>`
    : '';

  return `
<section id="score">
  <h1 class="chapter">Monitoring Maturity Score</h1>
  <hr class="chapter-rule">

  ${blockerAlert}

  <div class="metric-row">
    <div class="metric-card" style="background:${bg};border-color:${color}20">
      <div class="metric-value" style="color:${color}">${esc(totalScore)}</div>
      <div class="metric-label">Total score / 100</div>
    </div>
    <div class="metric-card">
      <div class="metric-value" style="color:${color}">${esc(label)}</div>
      <div class="metric-label">Status</div>
    </div>
    <div class="metric-card">
      <div class="metric-value">${esc(gaps.filter(g => g.severity === 'BLOCKER').length)}</div>
      <div class="metric-label">Blockers</div>
    </div>
    <div class="metric-card">
      <div class="metric-value">${esc(gaps.filter(g => g.severity === 'MAJOR').length)}</div>
      <div class="metric-label">Majors</div>
    </div>
  </div>

  <p>
    Monitoring maturity for <strong>${esc(projectName)}</strong> was scored across five
    observability dimensions by analysing ${esc(nodes.length)} IR nodes for known logging,
    metrics, tracing, health, and alerting framework patterns.
  </p>

  ${tableCaption('TABLE 1 — MONITORING DIMENSION SCORES')}
  <table>
    <thead><tr><th>Dimension</th><th>Status</th><th>Score</th><th>Coverage</th><th>Signals Found</th></tr></thead>
    <tbody>${dimRows}</tbody>
  </table>
</section>`.trim();
}

function buildGaps() {
  if (gaps.length === 0) {
    return `
<section id="gaps">
  <h1 class="chapter">Gap Analysis</h1>
  <hr class="chapter-rule">
  <p>No monitoring gaps detected. The source application has coverage across all five observability dimensions.</p>
</section>`.trim();
  }

  const rows = gaps.map(g => `
  <tr>
    <td>${severityBadge(g.severity)}</td>
    <td>${esc(g.dimension)}</td>
    <td>${esc(g.description)}</td>
  </tr>`).join('');

  return `
<section id="gaps">
  <h1 class="chapter">Gap Analysis</h1>
  <hr class="chapter-rule">
  <p>
    ${esc(gaps.length)} monitoring gap${gaps.length !== 1 ? 's' : ''} identified.
    ${esc(gaps.filter(g => g.severity === 'BLOCKER').length)} BLOCKER,
    ${esc(gaps.filter(g => g.severity === 'MAJOR').length)} MAJOR,
    ${esc(gaps.filter(g => g.severity === 'MINOR').length)} MINOR.
  </p>
  ${tableCaption('TABLE 2 — MONITORING GAPS')}
  <table>
    <thead><tr><th>Severity</th><th>Dimension</th><th>Description</th></tr></thead>
    <tbody>${rows}</tbody>
  </table>
</section>`.trim();
}

function buildSecuritySignal() {
  const findings = security.findings || [];
  const risk     = security.source_architecture_risk || security.risk_ranking?.[0] || null;
  const hints    = (ir.security_hints) || null;
  const hintCount = hints ? hints.finding_count || 0 : findings.length;
  if (hintCount === 0 && findings.length === 0 && !risk) return '';

  const riskColour = { HIGH: '#C0392B', CRITICAL: '#8B0000', MEDIUM: '#A0522D', LOW: '#2E7D32', UNKNOWN: '#91969C' };
  const riskLabel  = risk || (hints && hints.source_architecture_risk) || 'UNKNOWN';
  const col        = riskColour[riskLabel] || riskColour.UNKNOWN;

  const topFindings = (hints ? hints.top_findings || [] : findings.slice(0, 5))
    .map(f => `<tr>
      <td>${severityBadge(f.severity || 'INFO')}</td>
      <td style="font-family:'IBM Plex Mono',monospace;font-size:12px">${esc(f.id || '')}</td>
      <td>${esc(f.title || f.category || '')}</td>
      <td style="font-family:'IBM Plex Mono',monospace;font-size:11px;color:#91969C">${esc((f.location || '').split('/').pop() || '')}</td>
    </tr>`).join('');

  return `
<section id="security-signal">
  <h1 class="chapter">Security Signal</h1>
  <hr class="chapter-rule">
  <p>
    Security findings surfaced during source analysis.
    Architecture risk classification: <strong style="color:${col}">${esc(riskLabel)}</strong>.
    ${esc(hintCount)} finding${hintCount !== 1 ? 's' : ''} identified — review
    <a href="security-report.html">Security Report</a> for full details.
  </p>
  <div class="metric-row">
    <div class="metric-card" style="border-color:${col}40">
      <div class="metric-value" style="color:${col}">${esc(riskLabel)}</div>
      <div class="metric-label">Architecture Risk</div>
    </div>
    <div class="metric-card">
      <div class="metric-value">${esc(hintCount)}</div>
      <div class="metric-label">Security Findings</div>
    </div>
    <div class="metric-card">
      <div class="metric-value">${esc(findings.filter(f => f.affects_migration).length)}</div>
      <div class="metric-label">Migration-Affecting</div>
    </div>
    <div class="metric-card">
      <div class="metric-value">${esc(findings.filter(f => f.severity === 'HIGH' || f.severity === 'CRITICAL').length)}</div>
      <div class="metric-label">High / Critical</div>
    </div>
  </div>
  ${topFindings ? `${tableCaption('TOP SECURITY FINDINGS')}
  <table>
    <thead><tr><th>Severity</th><th>ID</th><th>Title</th><th>File</th></tr></thead>
    <tbody>${topFindings}</tbody>
  </table>` : ''}
</section>`.trim();
}

function buildServices() {
  if (perService.length === 0) {
    return `
<section id="services">
  <h1 class="chapter">Per-Service Gap Table</h1>
  <hr class="chapter-rule">
  <p>No bounded contexts available. Run the Cartographer phase to generate context decomposition.</p>
</section>`.trim();
  }

  const rows = perService.map(s => {
    const total = s.logging + s.metrics + s.tracing + s.health + s.alerting;
    const { label, color } = interpretation(total);
    return `<tr>
      <td>${esc(s.name)}</td>
      <td style="text-align:center">${esc(s.logging)}</td>
      <td style="text-align:center">${esc(s.metrics)}</td>
      <td style="text-align:center">${esc(s.tracing)}</td>
      <td style="text-align:center">${esc(s.health)}</td>
      <td style="text-align:center">${esc(s.alerting)}</td>
      <td style="text-align:center;color:${color}"><strong>${esc(total)}</strong></td>
      <td style="color:${color}">${esc(label)}</td>
    </tr>`;
  }).join('');

  return `
<section id="services">
  <h1 class="chapter">Per-Service Gap Table</h1>
  <hr class="chapter-rule">
  <p>
    Monitoring score breakdown across ${esc(perService.length)} bounded context${perService.length !== 1 ? 's' : ''}.
    Each dimension is scored 0–20 per context based on the IR nodes assigned to that context.
  </p>
  ${tableCaption('TABLE 3 — PER-SERVICE MONITORING SCORES')}
  <table>
    <thead>
      <tr>
        <th>Context</th>
        <th>Logging</th><th>Metrics</th><th>Tracing</th><th>Health</th><th>Alerting</th>
        <th>Total</th><th>Status</th>
      </tr>
    </thead>
    <tbody>${rows}</tbody>
  </table>
</section>`.trim();
}

function buildOtelGuide() {
  let langSection = '';
  if (otelRec) {
    langSection = `
  <div class="callout">
    <strong>Target language: ${esc(targetLang)}</strong><br>
    Dependency: <code>${esc(otelRec.dep)}</code><br>
    Primary API: <code>${esc(otelRec.api)}</code><br>
    Test pattern: <code>${esc(otelRec.test)}</code>
  </div>`;
  }

  const recRows = [
    ['Java · Kotlin · Scala', 'io.opentelemetry:opentelemetry-api:1.37.0',     'GlobalOpenTelemetry.getTracer()',          'InMemorySpanExporter'],
    ['C# · F# · VB.NET',      'OpenTelemetry.Api 1.8.* (NuGet)',               'ActivitySource.StartActivity()',           'ActivityListener'],
    ['TypeScript / JavaScript / Node.js', '@opentelemetry/api ^1.8',           'trace.getTracer().startActiveSpan()',      'InMemorySpanExporter'],
    ['Python',                'opentelemetry-api==1.24.0',                      'trace.get_tracer()',                       'InMemorySpanExporter'],
    ['Go',                    'go.opentelemetry.io/otel v1.24.0',               'otel.Tracer().Start(ctx, name)',           'sdktrace + tracetest'],
  ].map(([lang, dep, api, test]) => `<tr>
    <td>${esc(lang)}</td><td>${esc(dep)}</td><td>${esc(dep)}</td><td>${esc(api)}</td><td>${esc(test)}</td>
  </tr>`).join('');

  return `
<section id="otel">
  <h1 class="chapter">OpenTelemetry Adoption Guide</h1>
  <hr class="chapter-rule">
  <p>
    OpenTelemetry is the CNCF standard for distributed tracing, metrics, and logging.
    Adopt the OTel SDK in every translated microservice before production deployment.
  </p>

  ${langSection}

  ${tableCaption('TABLE 4 — OTel SDK QUICK REFERENCE BY LANGUAGE')}
  <table>
    <thead><tr><th>Language Stack</th><th>Package / NuGet</th><th>Primary API</th><th>Test Pattern</th></tr></thead>
    <tbody>${recRows}</tbody>
  </table>

  <h2 class="section">Instrumentation Checklist</h2>
  <p>Apply to every public service method in the translated codebase:</p>
  <table>
    <thead><tr><th>#</th><th>Item</th><th>Why</th></tr></thead>
    <tbody>
      <tr><td>1</td><td>Create a span per public service method</td><td>Enables distributed trace reconstruction</td></tr>
      <tr><td>2</td><td>Set span attributes (entity ID, operation type)</td><td>Queryable context for debugging</td></tr>
      <tr><td>3</td><td>Inject trace-id into structured log fields</td><td>Correlates logs with traces in dashboards</td></tr>
      <tr><td>4</td><td>Record exception on catch and set ERROR status</td><td>Marks failing spans for alerting</td></tr>
      <tr><td>5</td><td>Propagate W3C traceparent on outbound HTTP calls</td><td>Enables cross-service trace correlation</td></tr>
      <tr><td>6</td><td>Assert span emission in unit tests (InMemorySpanExporter)</td><td>Prevents OTel regression without a live collector</td></tr>
    </tbody>
  </table>
</section>`.trim();
}

function buildInventory() {
  const loggingNodes  = nodes.filter(n => matchPatterns(LOGGING_PATTERNS,  [n.id, n.name, n.summary].join(' ')));
  const metricsNodes  = nodes.filter(n => matchPatterns(METRICS_PATTERNS,  [n.id, n.name, n.summary].join(' ')));
  const tracingNodes  = nodes.filter(n => matchPatterns(TRACING_PATTERNS,  [n.id, n.name, n.summary].join(' ')));
  const healthNodes   = nodes.filter(n => matchPatterns(HEALTH_PATTERNS,   [n.id, n.name, n.summary].join(' ')));

  function nodeRows(arr) {
    if (arr.length === 0) return '<tr><td colspan="3">None detected</td></tr>';
    return arr.slice(0, 20).map(n => `<tr>
      <td>${esc(n.name || n.id)}</td>
      <td>${esc(n.type)}</td>
      <td style="color:#91969C">${esc(n.source_location || '')}</td>
    </tr>`).join('') + (arr.length > 20 ? `<tr><td colspan="3" style="color:#91969C">… and ${arr.length - 20} more</td></tr>` : '');
  }

  return `
<section id="inventory">
  <h1 class="chapter">Legacy Monitoring Inventory</h1>
  <hr class="chapter-rule">
  <p>
    Nodes in the IR graph that contain monitoring-related patterns, detected by name and summary analysis.
    These represent the existing observability surface area of <strong>${esc(projectName)}</strong>.
  </p>

  <h2 class="section">Logging (${esc(loggingNodes.length)} nodes)</h2>
  ${tableCaption('TABLE 5 — LOGGING NODES')}
  <table>
    <thead><tr><th>Name</th><th>Type</th><th>Source</th></tr></thead>
    <tbody>${nodeRows(loggingNodes)}</tbody>
  </table>

  <h2 class="section">Metrics (${esc(metricsNodes.length)} nodes)</h2>
  ${tableCaption('TABLE 6 — METRICS NODES')}
  <table>
    <thead><tr><th>Name</th><th>Type</th><th>Source</th></tr></thead>
    <tbody>${nodeRows(metricsNodes)}</tbody>
  </table>

  <h2 class="section">Tracing (${esc(tracingNodes.length)} nodes)</h2>
  ${tableCaption('TABLE 7 — TRACING NODES')}
  <table>
    <thead><tr><th>Name</th><th>Type</th><th>Source</th></tr></thead>
    <tbody>${nodeRows(tracingNodes)}</tbody>
  </table>

  <h2 class="section">Health (${esc(healthNodes.length)} nodes)</h2>
  ${tableCaption('TABLE 8 — HEALTH NODES')}
  <table>
    <thead><tr><th>Name</th><th>Type</th><th>Source</th></tr></thead>
    <tbody>${nodeRows(healthNodes)}</tbody>
  </table>
</section>`.trim();
}

// ── Assemble ──────────────────────────────────────────────────────────────────

function buildHTML() {
  const title = `${projectName} — Monitoring gap analysis`;
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>${esc(title)}</title>
  <link href="https://fonts.googleapis.com/css2?family=Instrument+Serif&family=Inter+Tight:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
  <style>${CSS}</style>
</head>
<body>
${buildNav()}
<div class="document">
${buildCover()}
${buildScore()}
${buildGaps()}
${buildSecuritySignal()}
${buildServices()}
${buildOtelGuide()}
${buildInventory()}
</div>
</body>
</html>`;
}

// ── Validate and write ────────────────────────────────────────────────────────

const html = buildHTML();

// Validate required sections
['score', 'gaps', 'services', 'otel', 'inventory'].forEach(id => {
  if (!html.includes(`id="${id}"`)) {
    console.error(`ERROR: anchor #${id} missing`);
    process.exit(1);
  }
});

// TABLE 1 (score) and TABLE 4 (OTel) are always present; others depend on data availability
[1, 4].forEach(i => {
  if (!html.includes(`TABLE ${i}`)) {
    console.error(`ERROR: TABLE ${i} missing`);
    process.exit(1);
  }
});

const outPath = outArg || path.join(runDir, 'reports', 'monitoring.html');
const outDir  = path.dirname(outPath);
if (!fs.existsSync(outDir)) fs.mkdirSync(outDir, { recursive: true });
fs.writeFileSync(outPath, html, 'utf8');
console.log(`Written: ${outPath} (${html.length} bytes)`);
console.log(`Score: ${totalScore}/100 — ${interp.label}`);
console.log(`Gaps: ${gaps.length} (${gaps.filter(g => g.severity === 'BLOCKER').length} blockers)`);

const outputsDir = '/mnt/user-data/outputs';
if (fs.existsSync(outputsDir)) {
  fs.writeFileSync(path.join(outputsDir, 'monitoring.html'), html, 'utf8');
  console.log(`Copied to ${outputsDir}/monitoring.html`);
}
