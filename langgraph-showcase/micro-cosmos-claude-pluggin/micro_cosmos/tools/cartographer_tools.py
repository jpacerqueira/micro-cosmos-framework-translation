"""Cartographer Agent tools — deterministic path-rule context classifier."""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

# Shared by Rule 14c and _classify_generic_layer: structural directories that
# never carry domain signal on their own.
_GENERIC_SKIP_DIRS = {"src", "main", "test", "java", "kotlin", "python", "lib", "pkg",
                       "app", "core", "common", "shared", "util", "utils", "notebooks"}


# ── Rule-based classifier ─────────────────────────────────────────────────────

def _classify_prog_node(source_location: str) -> str:
    """Apply 14 ordered path rules to classify a prog.* node into a context.

    Rules are checked in order; the first match wins. Case-insensitive.
    """
    path = source_location.lower()

    # Rule 1 — TestE2E
    if "/e2e/" in path or "/fixtures/auth.ts" in path:
        return "TestE2E"

    # Rule 2 — TestUnit
    if ("/__tests__/" in path or ".spec.ts" in path
            or ".test.ts" in path or ".test.tsx" in path):
        return "TestUnit"

    # Rule 3 — Configuration
    if ("vite.config" in path or "vitest.config" in path
            or "playwright.config" in path or "genkit.config" in path):
        return "Configuration"

    # Rule 4 — ExternalIntegrations (generic third-party SaaS integration folder
    # patterns — HR/payroll, ERP/CRM, and external comms/alerting systems — not
    # tied to any specific vendor)
    if any(p in path for p in (
        "/external-api/", "/third-party/",
        "/hris/", "/hr-integration/", "/payroll/",
        "/erp/", "/crm/",
        "/alerts-api/", "/chatops/", "/comms-api/",
    )):
        return "ExternalIntegrations"

    # Rule 5 — Authentication
    if ("/auth/" in path or "/guard" in path or "/guards/" in path
            or "firebase" in path or "/permission" in path):
        return "Authentication"

    # Rule 6 — Admin
    if "/admin/" in path:
        return "Admin"

    # Rule 7 — Messaging
    if ("/notification" in path or "/pubsub" in path
            or "/activity-events" in path or "/publisher" in path):
        return "Messaging"

    # Rule 8 — DataTransfer
    if "/timesheet" in path or "/phase-assignment" in path or "/allocation" in path:
        return "DataTransfer"

    # Rule 9 — ProjectManagement
    # "/project" requires a trailing slash — a bare prefix match incorrectly
    # classified unrelated directories like "project2_next_bis_domain" (a
    # Databricks data-mesh domain name, not a project-management feature) as
    # ProjectManagement, collapsing an entire multi-domain estate into one
    # context and tripping the >40% concentration check below. Confirmed via
    # a real run (2026-08-04) — not a hypothetical fix.
    if any(p in path for p in (
        "/project/", "/milestone", "/expense", "/project-role",
        "/rate-card", "/cpq", "/effort-estimate", "/margin", "/nuts-and-bolts",
    )):
        return "ProjectManagement"

    # Rule 10 — People
    if "/people" in path or "/person" in path:
        return "People"

    # Rule 11 — Frontend (compound: must contain both /app/src/ and a UI segment)
    if "/app/src/" in path and any(
        p in path for p in ("/features/", "/components/", "/hooks/", "/pages/", "/theme")
    ):
        return "Frontend"

    # Rule 12 — BackendCore
    if "/functions/src/" in path or "/nestjs/" in path or "/api/" in path:
        return "BackendCore"

    # Rule 13 — DataConnect
    if "/data-connect/" in path:
        return "DataConnect"

    # ── Generic structural classifier (non-TypeScript codebases) ─────────────
    # Rule 14a — Java/Kotlin test sources
    if "/src/test/" in path or "/test/java/" in path or "/test/kotlin/" in path:
        return "TestUnit"

    # Rule 14b — Java/Kotlin Maven module: extract module dir before /src/main/
    m = re.search(r"/([^/]+)/src/main/", path)
    if m:
        module = m.group(1)
        # Skip numeric/build-tool segments like "03-backend-springboot"
        if not re.match(r"^\d", module):
            return "".join(w.title() for w in re.split(r"[-_]", module))

    # Rule 14c — Generic: use first meaningful directory segment after the project root.
    # Split on "/" and skip empty or common non-domain segments. Purely numeric
    # segments are dropped, but an ordinal-prefixed segment (e.g. Databricks
    # pipeline-stage folders like "01_bis_hub") keeps its suffix as a candidate
    # instead of being discarded outright — the ordinal is a sort key, not the
    # domain signal, and dropping the whole segment was collapsing multi-stage
    # notebook estates into a single bucket. Confirmed via a real run (2026-08-04).
    parts: list[str] = []
    for p in path.split("/"):
        if not p or p in _GENERIC_SKIP_DIRS:
            continue
        m = re.match(r"^\d+[-_]+(.+)$", p)
        if m:
            parts.append(m.group(1))
        elif not re.match(r"^\d", p):
            parts.append(p)
    # Find the first segment that looks like a domain name (not a file extension segment)
    for part in parts[1:4]:  # skip index 0 (project root), check next 3
        if "." not in part and len(part) > 2:
            return "".join(w.title() for w in re.split(r"[-_]", part))

    # Rule 14d — Shared (catch-all)
    return "Shared"


def _classify_csharp_layer(source_location: str) -> str | None:
    """Extract a domain-layer context from a C# file path.

    Primary: immediate subdirectory within the .NET project directory
    (Controllers/, Services/, Repositories/, etc.).
    Fallback: class name suffix for files at the project root level.
    Returns None if no meaningful layer can be found.
    """
    path = source_location.lower()

    _DIR_LAYERS = (
        ("controllers", "Web"), ("views", "Web"),
        ("middleware", "Web"), ("filters", "Web"),
        ("services", "Service"), ("handlers", "Service"),
        ("helpers", "Service"), ("validators", "Service"),
        ("mappers", "Service"), ("converters", "Service"),
        ("repositories", "Repository"), ("data", "Repository"),
        ("infrastructure", "Repository"),
        ("entities", "Entity"),
        ("models", "Domain"), ("domain", "Domain"),
        ("dtos", "Domain"), ("dto", "Domain"),
        ("interfaces", "Domain"), ("exceptions", "Domain"),
        ("events", "Domain"), ("valueobjects", "Domain"),
        ("config", "Config"), ("app_start", "Config"),
        ("configuration", "Config"), ("settings", "Config"),
        ("properties", "Config"),
        ("batch", "Batch"), ("jobs", "Batch"), ("tasks", "Batch"),
    )
    for dir_name, layer in _DIR_LAYERS:
        if f"/{dir_name}/" in path:
            return layer

    # Fallback: derive from class name suffix (.cs and .asax.cs files)
    fn = re.search(r"/([^/]+?)(?:\.asax)?\.cs(?::[0-9]+)?$", path)
    if fn:
        name = fn.group(1)
        for suffix, layer in (
            ("controller", "Web"), ("middleware", "Web"), ("filter", "Web"),
            ("service", "Service"), ("serviceimpl", "Service"),
            ("handler", "Service"), ("validator", "Service"), ("mapper", "Service"),
            ("repository", "Repository"), ("repo", "Repository"),
            ("entity", "Entity"),
            ("config", "Config"), ("configuration", "Config"),
            ("startup", "Config"), ("settings", "Config"),
            ("dto", "Domain"), ("viewmodel", "Domain"), ("model", "Domain"),
            ("domain", "Domain"), ("event", "Domain"), ("exception", "Domain"),
            ("job", "Batch"), ("task", "Batch"), ("batch", "Batch"),
            ("application", "Application"), ("program", "Application"),
            ("global", "Application"),
        ):
            if name.endswith(suffix):
                return layer
    return None


def _classify_cobol_layer(source_location: str) -> str | None:
    """Extract a domain-layer context from a COBOL file name.

    COBOL programs typically use a short system prefix followed by a domain code.
    e.g. BKACCT → Account, BKTRXN → Transaction, BKTLRMN → Teller.
    Matches from most-specific suffix to least to avoid false positives.
    """
    fn = re.search(r"/([^/]+?)\.(?:cbl|cob|cobol|cpy)(?::[0-9]+)?$", source_location, re.IGNORECASE)
    if not fn:
        return None
    name = fn.group(1).upper()

    # Copybooks → Shared
    if name.endswith("COMMON") or name.endswith("COPY") or source_location.lower().endswith(".cpy"):
        return "Shared"

    # Ordered most-specific first to prevent shorter patterns shadowing longer ones
    for suffix, layer in (
        ("MQBRDG", "Messaging"), ("MQUEUE", "Messaging"), ("PUBSUB", "Messaging"),
        ("TLRMN", "Teller"), ("TELLERMGR", "Teller"),
        ("TRXN", "Transaction"), ("TRANS", "Transaction"),
        ("ACCT", "Account"), ("ACCOUNT", "Account"),
        ("AUDIT", "Audit"),
        ("CUST", "Customer"), ("CUSTOMER", "Customer"),
        ("LOAN", "Loan"),
        ("PAYMT", "Payment"), ("PAY", "Payment"),
        ("REPORT", "Reporting"), ("RPT", "Reporting"),
        ("BATCH", "Batch"), ("BAT", "Batch"),
        ("AUTH", "Authentication"),
        ("SCREEN", "Presentation"), ("MENU", "Presentation"),
        ("DB", "Repository"), ("DATA", "Repository"),
    ):
        if suffix in name:
            return layer

    # Strip 2-letter system prefix and title-case the remainder as a fallback
    if len(name) > 4 and re.match(r"^[A-Z]{2}", name):
        remainder = name[2:]
        if len(remainder) > 2:
            return remainder.title()

    return None


def _classify_java_layer(source_location: str) -> str | None:
    """Extract a domain-layer context from a Java/Kotlin file path.

    Primary: the file's immediate parent directory — depth-independent, so it
    doesn't assume a fixed tld/company/project prefix (a fixed "skip 3
    segments" offset captured the wrong, non-discriminating segment for
    deeper package structures, e.g. org/axonframework/samples/bank/command/
    always returned "bank" regardless of the real per-file sub-package).
    Fallback: class name suffix for files living directly in the root package.
    Returns None if no meaningful segment can be found.
    """
    path = source_location.lower()
    m = re.search(r"/([^/]+)/[^/]+\.(?:java|kt|groovy)(?::[0-9]+)?$", path)
    if m:
        seg = m.group(1)
        if len(seg) > 2 and seg not in _GENERIC_SKIP_DIRS:
            return "".join(w.title() for w in re.split(r"[-_]", seg))

    # Fallback: derive layer from class name suffix (handles root-package files)
    fn = re.search(r"/([^/]+?)\.(?:java|kt|groovy)(?::[0-9]+)?$", path)
    if fn:
        name = fn.group(1)
        for suffix, layer in (
            ("serviceimpl", "Service"), ("service", "Service"),
            ("repository", "Repository"), ("repo", "Repository"),
            ("controller", "Web"), ("restcontroller", "Web"),
            ("resource", "Web"), ("endpoint", "Web"),
            ("entity", "Entity"),
            ("config", "Config"), ("configuration", "Config"),
            ("properties", "Config"), ("settings", "Config"),
            ("dto", "Domain"), ("vo", "Domain"), ("model", "Domain"),
            ("domain", "Domain"), ("event", "Domain"),
            ("exception", "Domain"), ("error", "Domain"),
            ("batch", "Batch"), ("job", "Batch"), ("step", "Batch"),
            ("tasklet", "Batch"), ("processor", "Batch"),
            ("reader", "Batch"), ("writer", "Batch"), ("listener", "Batch"),
            ("application", "Application"), ("app", "Application"),
            ("mapper", "Service"), ("converter", "Service"),
            ("validator", "Service"), ("handler", "Service"),
        ):
            if name.endswith(suffix):
                return layer
    return None


def _classify_generic_layer(source_location: str) -> str | None:
    """Extract a domain-layer context from a generic (e.g. Python/notebook) file path.

    Mirrors _classify_java_layer/_classify_csharp_layer/_classify_cobol_layer but
    for languages with no dedicated classifier: Java/C#/COBOL projects never
    reach this (their own classifiers match first), so it only fires for the
    estates none of those cover — e.g. Databricks notebooks organised as
    numbered pipeline-stage folders, where the immediate parent directory
    (ordinal prefix stripped) is the real domain signal.
    Returns None if no meaningful segment can be found.
    """
    path = source_location.lower()
    parts = [p for p in path.split("/") if p]
    if len(parts) < 2:
        return None
    parent = parts[-2]
    m = re.match(r"^\d+[-_]+(.+)$", parent)
    if m:
        parent = m.group(1)
    if parent in _GENERIC_SKIP_DIRS or len(parent) <= 2:
        return None
    return "".join(w.title() for w in re.split(r"[-_]", parent))


# ── Context metadata ──────────────────────────────────────────────────────────

_CONFIDENCE = {
    "TestE2E":    0.95,
    "TestUnit":   0.95,
    "Configuration": 0.95,
    "DeadCode":   0.90,
    "Shared":     0.60,
}
_DEFAULT_CONFIDENCE = 0.85

_RATIONALE = {
    "DeadCode":           "Nodes with no inbound CALLS edges — not referenced by any active code path. Business decision required on whether to delete or migrate.",
    "TestE2E":            "End-to-end browser tests and shared e2e fixtures.",
    "TestUnit":           "Unit and integration spec files covering business logic.",
    "Configuration":      "Build, test, and runtime configuration files.",
    "ExternalIntegrations": "Adapters for third-party APIs (HR/payroll systems, ERP/CRM platforms, communications/alerting tools, external REST).",
    "Authentication":     "Auth guards, Firebase identity, JWT strategy, and permissions.",
    "Admin":              "Admin-facing features, back-office UI, and admin API controllers.",
    "Messaging":          "Event publishing, Pub/Sub handlers, notifications, and activity logs.",
    "DataTransfer":       "Timesheet capture, phase assignment, and allocation data flows.",
    "ProjectManagement":  "Project hierarchy, milestones, expenses, rate cards, CPQ, and margins.",
    "People":             "Person profiles, people management, and HR data.",
    "Frontend":           "React feature pages, shared UI components, hooks, and themes.",
    "BackendCore":        "NestJS API controllers, services, modules, and shared backend utilities.",
    "DataConnect":        "Firebase Data Connect operations and data-access layer.",
    "Raw":                "BigQuery Dataform raw views over physical source tables.",
    "Staging":            "BigQuery Dataform staging tables that cleanse the raw layer.",
    "Marts":              "BigQuery Dataform mart tables published to consumers.",
    "Shared":             "Utility modules and files that did not match a specific domain rule.",
    # Java/Kotlin domain layers
    "Service":            "Business logic and application services.",
    "Repository":         "Data-access layer — JPA/Spring repositories and DAOs.",
    "Entity":             "JPA entity classes and persistence model.",
    "Domain":             "Domain model: value objects, enums, events, and exceptions.",
    "Web":                "REST controllers, request/response DTOs, and HTTP endpoints.",
    "Config":             "Spring configuration classes, properties, and settings.",
    "Batch":              "Spring Batch jobs, steps, readers, processors, and writers.",
    "Application":        "Application entry point and top-level bootstrap configuration.",
}


# ── Legacy analysis helpers (kept for tests / other callers) ──────────────────

def analyse_co_mutation(ir_json: dict) -> dict:
    """Group nodes that share write access to the same data — co-mutation affinity."""
    nodes = [n["id"] for n in ir_json.get("nodes", []) if n.get("type") == "PROGRAM"]
    edges = [e for e in ir_json.get("edges", []) if e.get("type") == "CO_MUTATES_WITH"]

    if not nodes:
        return {"affinity_groups": []}

    adj: dict[str, set[str]] = {nid: set() for nid in nodes}
    for e in edges:
        src, tgt = e.get("source_id", ""), e.get("target_id", "")
        if src in adj and tgt in adj:
            adj[src].add(tgt)
            adj[tgt].add(src)

    visited: set[str] = set()
    groups: list[list[str]] = []
    for nid in nodes:
        if nid in visited or not adj[nid]:
            continue
        component: list[str] = []
        stack = [nid]
        while stack:
            n = stack.pop()
            if n in visited:
                continue
            visited.add(n)
            component.append(n)
            stack.extend(adj.get(n, set()) - visited)
        if len(component) > 1:
            groups.append(sorted(component))

    return {"affinity_groups": groups}


def analyse_call_graph(ir_json: dict) -> dict:
    """Apply community detection over the inter-program call graph."""
    nodes = [n["id"] for n in ir_json.get("nodes", []) if n.get("type") == "PROGRAM"]
    edges = [e for e in ir_json.get("edges", []) if e.get("type") == "CALLS"]

    if not nodes:
        return {"clusters": [], "cross_cluster_calls": []}

    adj: dict[str, set[str]] = {nid: set() for nid in nodes}
    for e in edges:
        src, tgt = e.get("source_id", ""), e.get("target_id", "")
        if src in adj and tgt in adj:
            adj[src].add(tgt)
            adj[tgt].add(src)

    visited: set[str] = set()
    clusters: list[list[str]] = []
    for nid in nodes:
        if nid in visited:
            continue
        cluster: list[str] = []
        stack = [nid]
        while stack:
            n = stack.pop()
            if n in visited:
                continue
            visited.add(n)
            cluster.append(n)
            stack.extend(adj.get(n, set()) - visited)
        clusters.append(sorted(cluster))

    node_to_cluster: dict[str, int] = {}
    for i, cl in enumerate(clusters):
        for n in cl:
            node_to_cluster[n] = i

    cross: list[list[str]] = []
    for e in edges:
        src, tgt = e.get("source_id", ""), e.get("target_id", "")
        if src in node_to_cluster and tgt in node_to_cluster:
            if node_to_cluster[src] != node_to_cluster[tgt]:
                cross.append([src, tgt])

    return {"clusters": clusters, "cross_cluster_calls": cross}


def analyse_table_ownership(ir_json: dict) -> dict:
    """Identify write authority over data stores."""
    nodes = [n["id"] for n in ir_json.get("nodes", []) if n.get("type") == "PROGRAM"]
    edges = [e for e in ir_json.get("edges", []) if e.get("type") == "CALLS"]

    sourced = {e.get("source_id") for e in edges}
    exclusive: dict[str, list[str]] = {}
    for nid in nodes:
        if nid not in sourced:
            table = f"ext.{nid.replace('prog.', '').upper()}_TABLE"
            exclusive[table] = [nid]

    return {"exclusive_writers": exclusive, "shared_writers": []}


# ── Main entry point ──────────────────────────────────────────────────────────

def analyse_bounded_contexts(source_path: str, source_lang: str) -> dict:
    """Return bounded contexts and cross-context calls for the source estate.

    Uses deterministic path-rule classification (14 ordered rules) rather than
    graph-based clustering, so the output is reproducible and not sensitive to
    graph connectivity issues.

    Steps:
    1. Classify every prog.* node by source_location using 14 path rules.
    2. Propagate context to class.*/fn.* via DEFINES edges, then to method.*
       nodes via attributes.class.
    3. Any remaining unassigned nodes fall into "Shared".
    4. Compute cross-context calls: unique (src_ctx, tgt_ctx) pairs from CALLS edges.
    5. Validate and return.
    """
    from micro_cosmos.tools.observer_tools import _ir_cache, parse_source_estate

    key = f"{source_path}:{source_lang}"
    ir = _ir_cache.get(key) or parse_source_estate(source_path, source_lang)

    all_nodes: list[dict] = ir.get("nodes", [])
    all_edges: list[dict] = ir.get("edges", [])

    # ── Step 0: pre-classify dead code nodes ─────────────────────────────────
    # Nodes flagged as dead code are separated into their own context so they
    # are not mixed with active code in the Repo Map. The business decides
    # whether to delete or migrate them — we just isolate them visually.
    dead_code_ids: set[str] = {
        d.get("node_id", "") for d in ir.get("dead_code", []) if d.get("node_id")
    }

    # ── Step 1: classify prog.* nodes ────────────────────────────────────────
    node_to_ctx: dict[str, str] = {}
    for n in all_nodes:
        nid = n.get("id", "")
        if not nid.startswith("prog."):
            continue
        loc = n.get("source_location", "") or ""
        if nid in dead_code_ids:
            node_to_ctx[nid] = "DeadCode"
        else:
            node_to_ctx[nid] = _classify_prog_node(loc)

    # ── Step 1a: ETL scheduler override ──────────────────────────────────────
    # An estate's own scheduler definition (Databricks Asset Bundle YAML,
    # Azure Data Factory pipeline JSON, or any other format registered in
    # scheduler_tools.py) declares the real ETL task boundaries and their
    # dependency order — a far more reliable seam signal than path structure
    # for these formats. Where present, it takes priority over Step 1's
    # path-rule classification for the files it covers (task_key becomes
    # the context label), and each task's depends_on becomes an explicit
    # cross-context call pair below.
    from micro_cosmos.tools.databricks_bundle_tools import task_context_label
    from micro_cosmos.tools.scheduler_tools import discover_task_graph

    _bundle_task_cross_calls: list[tuple[str, str]] = []
    _dab_rationale: dict[str, str] = {}
    _scheduler_tasks = discover_task_graph(source_path)["tasks"]
    if _scheduler_tasks:
        _task_ctx_of: dict[str, str] = {
            tk: task_context_label(tk) for tk in _scheduler_tasks
        }
        # A notebook owned by one activity takes that activity's context.
        # A notebook owned by several activities keeps its path context;
        # each activity is its own act.* node, so collapsing the file onto
        # the lexicographically smallest activity would hide the others.
        _owners: dict[Path, set[str]] = defaultdict(set)
        for tk, tdef in _scheduler_tasks.items():
            label = _task_ctx_of[tk]
            for f in tdef["owns_files"]:
                _owners[f].add(label)
        _file_to_ctx: dict[Path, str] = {
            path: next(iter(labels))
            for path, labels in _owners.items()
            if len(labels) == 1
        }
        for n in all_nodes:
            nid = n.get("id", "")
            if not nid.startswith("act.") or nid in dead_code_ids:
                continue
            attrs = n.get("attributes") or {}
            node_to_ctx[nid] = _task_ctx_of.get(attrs.get("etl_activity", ""), "") or n.get("name") or nid
        if _file_to_ctx:
            for n in all_nodes:
                nid = n.get("id", "")
                if not nid.startswith("prog.") or nid in dead_code_ids:
                    continue
                loc = n.get("source_location", "") or ""
                file_part = loc.rsplit(":", 1)[0] if ":" in loc else loc
                if not file_part:
                    continue
                resolved = Path(file_part).resolve()
                ctx = _file_to_ctx.get(resolved)
                if ctx:
                    node_to_ctx[nid] = ctx
        for tk, tdef in _scheduler_tasks.items():
            ctx_label = _task_ctx_of[tk]
            dep_note = (
                f" Depends on: {', '.join(_task_ctx_of[d] for d in tdef['depends_on'] if d in _task_ctx_of)}."
                if tdef["depends_on"] else ""
            )
            _dab_rationale[ctx_label] = (
                f"Task '{tk}' (kind: {tdef['kind']}) from job/pipeline '{tdef['job']}' — "
                f"classified per the estate's own scheduler definition, not path rules.{dep_note}"
            )
            for dep_tk in tdef["depends_on"]:
                if dep_tk in _task_ctx_of:
                    _bundle_task_cross_calls.append((_task_ctx_of[dep_tk], _task_ctx_of[tk]))

    # ── Step 1b: reclassify over-broad contexts via Java sub-package depth ──────
    # If a single context captures >40% of prog.* nodes in a large codebase it is
    # almost certainly a single-module Java/Kotlin project. Drill one level deeper
    # into the package path to produce meaningful domain-layer contexts.
    _prog_by_ctx: dict[str, int] = defaultdict(int)
    for nid, ctx in node_to_ctx.items():
        _prog_by_ctx[ctx] += 1
    _prog_total_tmp = sum(_prog_by_ctx.values())
    if _prog_total_tmp >= 3:
        _id_to_node = {n.get("id", ""): n for n in all_nodes}
        for _ctx, _count in list(_prog_by_ctx.items()):
            if _count / _prog_total_tmp > 0.4:
                for nid in list(node_to_ctx):
                    if node_to_ctx.get(nid) == _ctx and nid.startswith("prog."):
                        _loc = (_id_to_node.get(nid) or {}).get("source_location", "") or ""
                        _sub = (_classify_java_layer(_loc) or _classify_csharp_layer(_loc)
                                or _classify_cobol_layer(_loc) or _classify_generic_layer(_loc))
                        if _sub:
                            node_to_ctx[nid] = _sub

    # ── Step 1c: Dataform models are layered by config schema, not by path ──
    # Every .sqlx file lives under definitions/, so path rules collapse the
    # estate into one context. The config schema (raw, staging, marts) is the
    # warehouse layer.
    for n in all_nodes:
        nid = n.get("id", "")
        attrs = n.get("attributes") or {}
        if attrs.get("etl_platform") != "bigquery_dataform" or nid in dead_code_ids:
            continue
        schema = (attrs.get("schema") or "models").strip()
        node_to_ctx[nid] = "".join(
            part.title() for part in re.split(r"[-_\s]+", schema) if part
        ) or "Models"

    # ── Step 2: build full DEFINES hierarchy (prog → class → method/field) ──
    all_defines: dict[str, list[str]] = defaultdict(list)
    for e in all_edges:
        if e.get("type") == "DEFINES":
            all_defines[e.get("source_id", "")].append(e.get("target_id", ""))

    # ── Step 3: propagate context prog.* → class.* → method.* / field.* ─────
    for prog_id, ctx in list(node_to_ctx.items()):
        if not prog_id.startswith("prog."):
            continue
        for class_id in all_defines.get(prog_id, []):
            node_to_ctx[class_id] = ctx
            for child_id in all_defines.get(class_id, []):
                node_to_ctx[child_id] = ctx

    # ── Step 4: assign any remaining nodes; isolate individually dead nodes ──
    # Tool-path-derived names (e.g. "MicroCosmosSource") are renamed to Shared.
    # Nodes individually flagged as dead code (but whose prog parent is active)
    # are moved to DeadCode so they don't pollute active domain contexts.
    _TOOL_PATH_NAMES = {"MicroCosmosSource", "MicroCosmos", "MicroCosmosSrc"}
    for n in all_nodes:
        nid = n.get("id", "")
        if nid in dead_code_ids:
            node_to_ctx[nid] = "DeadCode"
        elif nid not in node_to_ctx:
            node_to_ctx[nid] = "Shared"
        elif node_to_ctx[nid] in _TOOL_PATH_NAMES:
            node_to_ctx[nid] = "Shared"

    # ── Step 5: group node_ids by context ────────────────────────────────────
    ctx_nodes: dict[str, list[str]] = defaultdict(list)
    for nid, ctx in node_to_ctx.items():
        ctx_nodes[ctx].append(nid)

    # ── Step 6: compute cross-context calls as (ctx_label, ctx_label) pairs ──
    seen_pairs: set[tuple[str, str]] = set()
    cross_calls: list[list[str]] = []
    for e in all_edges:
        if e.get("type") != "CALLS":
            continue
        src_ctx = node_to_ctx.get(e.get("source_id", ""))
        tgt_ctx = node_to_ctx.get(e.get("target_id", ""))
        if src_ctx and tgt_ctx and src_ctx != tgt_ctx:
            pair = (src_ctx, tgt_ctx)
            if pair not in seen_pairs:
                seen_pairs.add(pair)
                cross_calls.append(list(pair))
    # Task depends_on from Step 1a — the scheduler's own declared execution
    # order, not inferred from source-code CALLS edges at all.
    for pair in _bundle_task_cross_calls:
        if pair[0] != pair[1] and pair not in seen_pairs:
            seen_pairs.add(pair)
            cross_calls.append(list(pair))

    # ── Step 7: validate ──────────────────────────────────────────────────────
    prog_total = sum(1 for n in all_nodes if n.get("id", "").startswith("prog."))
    # Only enforce the 40% cap on codebases large enough to have meaningful domain splits.
    # A context that still exceeds the cap after Step 1b's refinement attempt is recorded
    # rather than raised — see issue #87: silently dropping bounded_context_map.json starves
    # every downstream consumer (context-boundary seams, work-stream grouping) entirely,
    # whereas a flagged-but-real artifact lets _is_valid_bounded_context_map() surface the
    # same reviewer warning at Gate 2 while still giving reject-and-restart something to act on.
    over_concentrated: list[dict] = []
    if prog_total >= 20:
        for ctx_label, nids in ctx_nodes.items():
            prog_count = sum(1 for nid in nids if nid.startswith("prog."))
            if prog_count / prog_total > 0.4:
                over_concentrated.append({
                    "name": ctx_label,
                    "prog_count": prog_count,
                    "prog_total": prog_total,
                    "pct": round(100 * prog_count / prog_total),
                })

    # The IR may contain duplicate node IDs (same ID, different content).
    # Validate against unique IDs only — duplicates cannot be separately assigned.
    ir_unique_ids = {n.get("id", "") for n in all_nodes if n.get("id")}
    assigned_total = len(node_to_ctx)
    ir_total = len(ir_unique_ids)
    if assigned_total != ir_total:
        missing = ir_unique_ids - set(node_to_ctx)
        raise ValueError(
            f"Node assignment incomplete: {assigned_total} assigned of {ir_total} unique IDs. "
            f"Missing {len(missing)}: {sorted(missing)[:5]}"
        )

    # Only enforce the cross-context-calls check on codebases large enough to
    # have meaningful domain splits (small repos legitimately map to one context).
    if prog_total >= 20 and not cross_calls:
        calls_exist = any(e.get("type") == "CALLS" for e in all_edges)
        if calls_exist:
            raise ValueError(
                "cross_context_calls is empty but CALLS edges exist. "
                "Context classification has produced degenerate boundaries."
            )

    # ── Step 8: build output ──────────────────────────────────────────────────
    contexts = []
    for ctx_label in sorted(ctx_nodes):
        nids = sorted(ctx_nodes[ctx_label])
        contexts.append({
            "name": ctx_label,
            "node_ids": nids,
            "confidence": _CONFIDENCE.get(ctx_label, _DEFAULT_CONFIDENCE),
            "rationale": _dab_rationale.get(
                ctx_label, _RATIONALE.get(ctx_label, f"Nodes classified to {ctx_label} by path rules."),
            ),
            "leaky_abstractions": [],
        })

    return {
        "contexts": contexts,
        "cross_context_calls": cross_calls,
        "over_concentrated_contexts": over_concentrated,
    }
