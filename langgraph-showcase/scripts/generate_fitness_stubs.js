#!/usr/bin/env node
'use strict';

/**
 * generate_fitness_stubs.js
 *
 * Renders architectural fitness functions as pytest stub code blocks.
 * One section per rule with metadata, spec explanation, and a runnable pytest file.
 *
 * Usage:
 *   node scripts/generate_fitness_stubs.js <run_dir>
 *   node scripts/generate_fitness_stubs.js <run_dir> <out>
 */

const fs   = require('fs');
const path = require('path');
const {
  esc, severityBadge, tableCaption, htmlShell, writeReport,
} = require('./report_common');

const args   = process.argv.slice(2);
const runDir = args[0] ? path.resolve(args[0]) : process.cwd();
const outArg = args[1] ? path.resolve(args[1]) : null;

function read(name) {
  const p = path.join(runDir, name);
  if (!fs.existsSync(p)) throw new Error(`Required file not found: ${p}`);
  return JSON.parse(fs.readFileSync(p, 'utf8'));
}

const meta        = read('run_meta.json');
const tnas        = read('tnas.json');
const projectName = path.basename(meta.source_path || 'unknown');
const targetLang  = meta.target_lang || 'python3';
const fitnessObj  = tnas.fitness_suite || {};
// Support old array format (functions[]) and new object format ({ dimName: "text" })
const fitnessFns  = Array.isArray(fitnessObj.functions) ? fitnessObj.functions : [];
// New object-format dimensions: each entry is [dimKey, assessmentText]
const _FITNESS_META = new Set(['sha','created_at','produced_by','functions','target_language','intended_commit_path']);
const fitnessDims = (typeof fitnessObj === 'object' && !Array.isArray(fitnessObj))
  ? Object.entries(fitnessObj).filter(([k, v]) => typeof v === 'string' && !_FITNESS_META.has(k))
  : [];

// Convert a dimension key to PascalCase class name suffix
function dimToPascal(key) {
  return key.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join('');
}

// Extract first sentence from an assessment string
function firstSentence(text) {
  const m = text.match(/[^.!?]+[.!?]+/);
  return m ? m[0].trim() : text.slice(0, 120);
}

// ── Spec → pytest code generator ─────────────────────────────────────────────

function stubFor(fn, targetLang) {
  const [rule, ...rest] = (fn.spec || '').split(':');
  const filename = `test_${fn.id.toLowerCase()}.py`;

  // Common pytest header
  const header = `"""
${fn.name}
${fn.description}

Spec:    ${fn.spec}
Derived: ${fn.derived_from}
"""
import ast
from pathlib import Path
import pytest

# ── Configure this path for your project ─────────────────────────────────────
PROJECT_SRC = "src"
`;

  switch (rule) {
    case 'no_primitive_type_on_field_role': {
      const [role, typesStr] = rest;
      const keywords = role === 'monetary'
        ? ['amount', 'balance', 'price', 'rate', 'cost', 'fee', 'total', 'salary', 'threshold', 'limit', 'weight', 'score']
        : [role];
      const badTypes = (typesStr || 'float,double').split(',');
      return { filename, code: `${header}
MONETARY_KEYWORDS = ${JSON.stringify(keywords)}
FORBIDDEN_TYPES   = ${JSON.stringify(badTypes)}


def _monetary_field(name: str) -> bool:
    lower = name.lower()
    return any(kw in lower for kw in MONETARY_KEYWORDS)


def _collect_fields(root: Path):
    for p in root.rglob("*.py"):
        try:
            tree = ast.parse(p.read_text())
        except SyntaxError:
            continue
        for cls in ast.walk(tree):
            if not isinstance(cls, ast.ClassDef):
                continue
            for item in ast.walk(cls):
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    yield str(p), item.target.id, ast.unparse(item.annotation)


def test_no_${role}_as_primitive_type() -> None:
    """${fn.name}"""
    violations = []
    for file_path, field_name, annotation in _collect_fields(Path(PROJECT_SRC)):
        if not _monetary_field(field_name):
            continue
        if any(t in annotation.lower() for t in FORBIDDEN_TYPES):
            violations.append(f"{file_path}::{field_name}: {annotation!r}")
    assert not violations, (
        f"FF VIOLATION — {len(violations)} ${role} field(s) use forbidden type(s):\\n"
        + "\\n".join(f"  {v}" for v in violations)
    )
` };
    }

    case 'no_direct_dependency': {
      const [source, forbidden] = rest;
      const INFRA = [
        'sqlalchemy', 'asyncpg', 'psycopg', 'pymongo',
        'aio_pika', 'pika', 'redis', 'aioredis',
        'httpx', 'aiohttp', 'requests',
        'boto3', 'google.cloud',
        'fastapi', 'starlette', 'flask',
        'celery',
      ];
      return { filename, code: `${header}
DOMAIN_PACKAGE       = f"{PROJECT_SRC}/${source.replace(/_/g, '/')}"
INFRASTRUCTURE_LIBS  = ${JSON.stringify(INFRA)}


def _collect_imports(root: Path):
    for p in root.rglob("*.py"):
        try:
            tree = ast.parse(p.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    yield str(p), alias.name
            elif isinstance(node, ast.ImportFrom) and node.module:
                yield str(p), node.module


def test_no_infrastructure_in_domain() -> None:
    """${fn.name}"""
    root = Path(DOMAIN_PACKAGE)
    if not root.exists():
        pytest.skip(f"Domain package not found: {DOMAIN_PACKAGE}")
    violations = [
        f"{p}: imports {imp!r}"
        for p, imp in _collect_imports(root)
        if any(imp.startswith(lib) for lib in INFRASTRUCTURE_LIBS)
    ]
    assert not violations, (
        f"FF VIOLATION — {len(violations)} infrastructure import(s) in ${source}:\\n"
        + "\\n".join(f"  {v}" for v in violations)
    )
` };
    }

    case 'command_return_type_in': {
      const allowed = rest.join(':').split(',');
      return { filename, code: `${header}
COMMAND_PREFIXES  = (
    "score_", "process_", "apply_", "submit_", "execute_",
    "create_", "update_", "delete_", "approve_", "decline_",
    "transition_", "handle_", "send_", "publish_", "emit_",
)
ALLOWED_RETURNS = ${JSON.stringify(allowed)}


def test_cqrs_command_return() -> None:
    """${fn.name}"""
    violations = []
    for p in Path(PROJECT_SRC).rglob("*.py"):
        try:
            tree = ast.parse(p.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not any(node.name.startswith(pfx) for pfx in COMMAND_PREFIXES):
                continue
            if node.returns is None:
                continue
            ret = ast.unparse(node.returns)
            if ret not in ALLOWED_RETURNS:
                violations.append(f"{p}::{node.name}() -> {ret!r}")
    assert not violations, (
        f"FF VIOLATION — {len(violations)} command(s) return disallowed type(s):\\n"
        + "\\n".join(f"  {v}" for v in violations)
    )
` };
    }

    case 'state_transition_via': {
      const via = rest.join(':');
      return { filename, code: `${header}
STATUS_FIELD_NAMES  = {"status", "alert_status", "acct_status", "txn_status",
                        "auth_decision", "account_status", "state"}
PERMITTED_CLASSES   = {
    # Add the names of your state machine classes here, e.g.:
    # "AccountStateMachine", "FraudAlertStateMachine",
}


def test_state_transitions_via_state_machine() -> None:
    """${fn.name}"""
    violations = []
    for p in Path(PROJECT_SRC).rglob("*.py"):
        try:
            tree = ast.parse(p.read_text())
        except SyntaxError:
            continue
        for cls in ast.walk(tree):
            if not isinstance(cls, ast.ClassDef):
                continue
            if cls.name in PERMITTED_CLASSES:
                continue
            for node in ast.walk(cls):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if (
                            isinstance(target, ast.Attribute)
                            and isinstance(target.value, ast.Name)
                            and target.value.id == "self"
                            and target.attr in STATUS_FIELD_NAMES
                        ):
                            violations.append(
                                f"{p}::{cls.name}: direct assignment to self.{target.attr}"
                            )
    assert not violations, (
        f"FF VIOLATION — {len(violations)} direct status mutation(s):\\n"
        + "\\n".join(f"  {v}" for v in violations)
    )
` };
    }

    case 'no_database_access_outside': {
      const boundary = rest.join(':');
      const DB_LIBS = ['sqlalchemy', 'asyncpg', 'psycopg', 'psycopg2', 'pymongo', 'motor', 'aiosqlite', 'databases'];
      return { filename, code: `${header}
REPOSITORY_PATH_MARKERS = ("${boundary}", "repository", "repo", "adapters/persistence")
DB_LIBRARIES = ${JSON.stringify(DB_LIBS)}


def _is_repo_adapter(p: Path) -> bool:
    return any(m in str(p).lower() for m in REPOSITORY_PATH_MARKERS)


def test_no_db_outside_repository() -> None:
    """${fn.name}"""
    violations = []
    for p in Path(PROJECT_SRC).rglob("*.py"):
        if _is_repo_adapter(p):
            continue
        try:
            tree = ast.parse(p.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            imp = None
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imp = alias.name
            elif isinstance(node, ast.ImportFrom) and node.module:
                imp = node.module
            if imp and any(imp.startswith(lib) for lib in DB_LIBRARIES):
                violations.append(f"{p}: imports {imp!r}")
    assert not violations, (
        f"FF VIOLATION — {len(violations)} DB import(s) outside repository adapters:\\n"
        + "\\n".join(f"  {v}" for v in violations)
    )
` };
    }

    default:
      return { filename, code: `${header}
# TODO: Implement assertion for spec: ${fn.spec}
def test_${fn.id.toLowerCase()}() -> None:
    """${fn.name}"""
    pytest.fail("Fitness function not yet implemented for spec: ${fn.spec}")
` };
  }
}

// ── Render ─────────────────────────────────────────────────────────────────────

function copyBtn(id) {
  return `<button onclick="
    const pre = document.getElementById('code-${id}');
    navigator.clipboard.writeText(pre.textContent).then(() => {
      this.textContent = '✓ Copied'; setTimeout(() => this.textContent = 'Copy', 1500);
    });
  " style="font-family:'IBM Plex Mono',monospace;font-size:11px;background:#2D3535;color:#E8EDEC;border:none;padding:4px 10px;cursor:pointer;border-radius:2px;float:right;margin-top:-48px;position:relative">Copy</button>`;
}

const fnSections = fitnessFns.map((fn, i) => {
  const num  = String(i + 1).padStart(3, '0');
  const stub = stubFor(fn, targetLang);
  return `
  <section id="ff-${num}">
    <div style="display:flex;align-items:baseline;gap:12px;margin-bottom:4px">
      <span style="font-family:'IBM Plex Mono',monospace;font-size:12px;color:#91969C">FF-${esc(num)}</span>
      ${severityBadge(fn.severity)}
    </div>
    <h2 class="section" style="margin-top:0">${esc(fn.name)}</h2>
    <p class="stat-line">Derived from: ${esc(fn.derived_from || '—')} · File: <code>${esc(stub.filename)}</code></p>
    <p>${esc(fn.description)}</p>
    <p><strong>Rationale:</strong> ${esc(fn.rationale)}</p>
    <p><strong>Spec:</strong> <code>${esc(fn.spec)}</code></p>
    ${copyBtn(num)}
    <pre id="code-${num}">${esc(stub.code)}</pre>
  </section>`;
}).join('');

// Dimension-based stubs from new fitness_suite object format
const dimSections = fitnessDims.map(([dimKey, dimVal], i) => {
  const offset   = fitnessFns.length + i + 1;
  const num      = String(offset).padStart(3, '0');
  const pascal   = dimToPascal(dimKey);
  const title    = dimKey.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
  const reason   = firstSentence(dimVal);
  const filename = `test_${dimKey.toLowerCase()}.py`;
  const code = `"""
${title}
${dimVal}
"""
import pytest


class Test${esc(pascal)}:
    """${esc(dimVal)}"""

    @pytest.mark.skip(reason="${esc(reason)}")
    def test_dimension_satisfied(self) -> None:
        """Verify that ${esc(title.toLowerCase())} meets the required threshold."""
        raise NotImplementedError("Implement assertion for: ${esc(dimKey)}")
`;
  return `
  <section id="ff-${num}">
    <div style="display:flex;align-items:baseline;gap:12px;margin-bottom:4px">
      <span style="font-family:'IBM Plex Mono',monospace;font-size:12px;color:#91969C">FF-${esc(num)}</span>
    </div>
    <h2 class="section" style="margin-top:0">${esc(title)}</h2>
    <p class="stat-line">File: <code>${esc(filename)}</code></p>
    <p>${esc(dimVal)}</p>
    ${copyBtn(num)}
    <pre id="code-${num}">${esc(code)}</pre>
  </section>`;
}).join('');

const allFnSections = (fnSections + dimSections) || '<p style="color:#91969C">No fitness functions recorded in this run.</p>';

const totalFns = fitnessFns.length + fitnessDims.length;
const bodyHtml = `
<div class="metric-row" style="grid-template-columns:repeat(3,1fr)">
  <div class="metric-card"><div class="metric-value">${esc(totalFns)}</div><div class="metric-label">Fitness functions</div></div>
  <div class="metric-card"><div class="metric-value">${esc(fitnessFns.filter(f => f.severity === 'BLOCKING').length)}</div><div class="metric-label">Blocking</div></div>
  <div class="metric-card"><div class="metric-value">${esc(targetLang)}</div><div class="metric-label">Target language</div></div>
</div>

<section id="intro">
  <h1 class="chapter">Usage</h1>
  <hr class="chapter-rule">
  <p>Copy each code block into <code>architecture/fitness/</code> in the target repository.
  Run with pytest on every pull request. A BLOCKING rule failure must prevent the PR from merging.</p>
  <div class="panel">pytest architecture/fitness/ -v
pytest architecture/fitness/ --tb=short -q  # CI-friendly</div>
  <p>Adapt the <code>PROJECT_SRC</code> constant at the top of each file to match your package layout.</p>
</section>

<section id="rules">
  <h1 class="chapter">Fitness functions</h1>
  <hr class="chapter-rule">
  ${allFnSections}
</section>
`;

const navLinks = [['#intro','Usage'],['#rules','Rules']];
fitnessFns.forEach((fn, i) => {
  const num = String(i + 1).padStart(3, '0');
  navLinks.push([`#ff-${num}`, `FF-${num}`]);
});
fitnessDims.forEach(([, ], i) => {
  const num = String(fitnessFns.length + i + 1).padStart(3, '0');
  navLinks.push([`#ff-${num}`, `FF-${num}`]);
});

const html = htmlShell({
  title:      `${projectName} — Fitness test stubs`,
  projectName,
  reportType: 'Fitness test stubs',
  navLinks,
  bodyHtml,
});

writeReport(html, 'fitness-stubs.html', runDir, outArg);
