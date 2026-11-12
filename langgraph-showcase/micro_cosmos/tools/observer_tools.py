"""Observer Agent tools — symbolic analysis of the source estate."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Optional

from micro_cosmos.langgraph_runtime import ToolContext

# Tree-sitter hybrid parsers (optional — fall back to regex if not installed)
try:
    from tree_sitter import Language as _TSLanguage, Parser as _TSParser
    _TS_BASE_OK = True
except Exception:
    _TS_BASE_OK = False

if _TS_BASE_OK:
    try:
        import tree_sitter_java as _tsjava
        _JAVA_TS = _TSLanguage(_tsjava.language())
        _TS_AVAILABLE = True
    except Exception:
        _TS_AVAILABLE = False
    try:
        import tree_sitter_c_sharp as _tscs
        _CS_TS = _TSLanguage(_tscs.language())
        _CS_TS_AVAILABLE = True
    except Exception:
        _CS_TS_AVAILABLE = False
    try:
        import tree_sitter_c as _tsc
        _C_TS = _TSLanguage(_tsc.language())
        _C_TS_AVAILABLE = True
    except Exception:
        _C_TS_AVAILABLE = False
else:
    _TS_AVAILABLE = False
    _CS_TS_AVAILABLE = False
    _C_TS_AVAILABLE = False

from micro_cosmos.schema.ir import (
    Confidence,
    DeadCodeFinding,
    IREdge,
    IREdgeType,
    IRGraph,
    IRNode,
    IRNodeType,
    PerformanceFinding,
)


_LANG_EXTENSIONS: dict[str, list[str]] = {
    "cobol": [".cbl", ".cob", ".cobol"],
    "python": [".py"],
    "pyspark": [".py", ".ipynb"],
    "python2": [".py"],
    "python3": [".py"],
    # .sql alongside .java so Flyway/Liquibase-style migration files travelling
    # with a Java estate are actually discovered and handed to _parse_java_file's
    # own .sql branch — restoring this (it was dropped by the same regression
    # that removed the parsing branch itself) is what makes that branch reachable
    # at all. NB: only correct while java*'s deep parser is _parse_java_file
    # (true today — tree_sitter isn't an installed dependency); if tree-sitter
    # is ever added, _parse_java_ts_file has no .sql handling and would need one.
    "java": [".java", ".sql"],
    "java8": [".java", ".sql"],
    "java11": [".java", ".sql"],
    "java21": [".java", ".sql"],
    "go": [".go"],
    "rust": [".rs"],
    "javascript": [".js", ".mjs", ".cjs"],
    "typescript": [".ts", ".tsx"],
    "csharp": [".cs"],
    "cpp": [".cpp", ".cc", ".cxx"],
    # .h is included alongside .c — struct/type definitions and function
    # prototypes commonly live in the header, not the implementation file;
    # skipping headers would miss most of a real C estate's data model.
    "c": [".c", ".h"],
    "php": [".php", ".phtml"],
    "ruby": [".rb"],
    "kotlin": [".kt"],
    "scala": [".scala"],
    "swift": [".swift"],
    # Dataform models. Registered after java so it does not compete for .sql,
    # which Java estates use for Flyway/Liquibase migrations.
    "sqlx": [".sqlx"],
}

_DOC_EXTENSIONS: set[str] = {".md", ".rst", ".txt", ".adoc"}

_PERF_PATTERNS: list[tuple[str, str, re.Pattern, re.Pattern, str]] = [
    (
        "SQL_IN_LOOP",
        "CRITICAL",
        re.compile(r"(?i)\b(PERFORM\s+VARYING|for\s|while\s|DO\s+WHILE\b|foreach\s)"),
        re.compile(r"(?i)(EXEC\s+SQL|\.execute\s*\(|executeQuery|executeUpdate|cursor\.execute)"),
        "Replace per-row queries with a single batched join or bulk operation.",
    ),
    (
        "FILE_OPEN_IN_LOOP",
        "HIGH",
        re.compile(r"(?i)\b(PERFORM\s+VARYING|for\s|while\s|DO\s+WHILE\b|foreach\s)"),
        re.compile(r"(?i)(OPEN\s+INPUT|OPEN\s+OUTPUT|open\s*\(|fopen\s*\(|new\s+FileReader|new\s+File\b)"),
        "Move file open/close outside the loop; read all data in a single pass.",
    ),
]


def _synth_source_sha(source_path: str) -> str:
    return hashlib.sha256(source_path.encode("utf-8")).hexdigest()[:16]


def _extensions_for(source_lang: str) -> list[str]:
    lang = source_lang.lower().strip()
    if not lang:
        return []
    # Exact match first — a fuzzy-only lookup here is a real, confirmed bug:
    # "cobol".startswith("c") is True, and with "cobol" registered earlier
    # in this dict than "c", source_lang="c" resolved to COBOL's extensions
    # instead of its own [".c"] entry. Invisible until now because nothing
    # previously used "c" as a source language. _call_extractor_for and
    # _deep_parser_for already check an exact dict key before falling back
    # to prefix matching — this brings _extensions_for in line with them.
    if lang in _LANG_EXTENSIONS:
        return _LANG_EXTENSIONS[lang]
    for key, exts in _LANG_EXTENSIONS.items():
        if lang.startswith(key) or key.startswith(lang):
            return exts
    return [f".{lang}"]


def _stem_to_name(stem: str) -> str:
    return "".join(word.capitalize() for word in re.split(r"[_\-\s]+", stem) if word)


_source_files_cache: dict[str, list[Path]] = {}
_source_content_cache: dict[str, str] = {}


def _source_files(root: Path, source_lang: str) -> list[Path]:
    key = f"{root}:{source_lang}"
    cached = _source_files_cache.get(key)
    if cached is not None:
        return cached
    exts = set(_extensions_for(source_lang))
    if not root.exists() or not root.is_dir():
        _source_files_cache[key] = []
        return []
    result = sorted(f for f in root.rglob("*") if f.is_file() and f.suffix in exts)
    _source_files_cache[key] = result
    return result


def _tree_has_file(root: Path, filename: str) -> bool:
    """True when ``filename`` sits on ``root`` or a parent, stopping at ``examples``."""
    current = root if root.is_dir() else root.parent
    for _ in range(6):
        if (current / filename).is_file():
            return True
        if current.name == "examples" or current.parent == current:
            return False
        current = current.parent
    return False


def _lang_for_suffix(suffix: str, ext_to_lang: dict[str, str], root: Path) -> str | None:
    if suffix == ".sqlx":
        return "sqlx"
    # A dbt project is SQL, not Java, even though Java claims .sql first so
    # Flyway files inside application estates stay classified as Java.
    if suffix == ".sql" and _tree_has_file(root, "dbt_project.yml"):
        return "sql"
    return ext_to_lang.get(suffix)


def detect_source_lang(source_path: str) -> str:
    """Walk source_path and return the dominant language by file-extension count."""
    root = Path(source_path)
    if not root.exists() or not root.is_dir():
        return ""

    ext_to_lang: dict[str, str] = {}
    for lang, exts in _LANG_EXTENSIONS.items():
        for ext in exts:
            ext_to_lang.setdefault(ext, lang)

    counts: dict[str, int] = {}
    for f in root.rglob("*"):
        if not f.is_file():
            continue
        lang = _lang_for_suffix(f.suffix, ext_to_lang, root)
        if lang:
            counts[lang] = counts.get(lang, 0) + 1

    if not counts:
        return ""
    return max(counts, key=lambda k: counts[k])


def detect_all_langs(source_path: str) -> list[dict]:
    """Walk source_path and return all detected languages sorted by file count descending."""
    root = Path(source_path)
    if not root.exists() or not root.is_dir():
        return []

    ext_to_lang: dict[str, str] = {}
    for lang, exts in _LANG_EXTENSIONS.items():
        for ext in exts:
            ext_to_lang.setdefault(ext, lang)

    counts: dict[str, int] = {}
    for f in root.rglob("*"):
        if not f.is_file():
            continue
        lang = _lang_for_suffix(f.suffix, ext_to_lang, root)
        if lang:
            counts[lang] = counts.get(lang, 0) + 1

    return [{"lang": k, "count": v} for k, v in sorted(counts.items(), key=lambda x: -x[1])]


def _extract_calls_cobol(content: str, source_id: str) -> list[tuple[str, str]]:
    # Strip COBOL comment lines (column 7, i.e. index 6, = '*' or '/') before matching
    clean = "\n".join(
        ln for ln in content.splitlines()
        if not (len(ln) > 6 and ln[6] in ("*", "/"))
    )

    edges = []
    seen: set[str] = set()

    def _add(name: str) -> None:
        if name and name not in seen:
            seen.add(name)
            edges.append((source_id, f"prog.{_stem_to_name(name)}"))

    # Standard COBOL: CALL 'PROGRAMNAME'
    for m in re.finditer(r"\bCALL\s+['\"]([A-Za-z0-9_\-]+)['\"]", clean, re.IGNORECASE):
        _add(m.group(1))

    # CICS: EXEC CICS LINK/XCTL PROGRAM('PROGRAMNAME')
    for m in re.finditer(
        r"\bEXEC\s+CICS\s+(?:LINK|XCTL)\s+PROGRAM\s*\(\s*['\"]([A-Za-z0-9_\-]+)['\"]",
        clean, re.IGNORECASE,
    ):
        _add(m.group(1))

    return edges


def _extract_calls_python(content: str, source_id: str) -> list[tuple[str, str]]:
    """Import edges use the last module segment.

    ``from src.etl_jobs.etl_pipeline import ETLPipeline`` points at
    ``prog.EtlPipeline``, the file ``etl_pipeline.py``. A first-segment match
    would point at ``prog.Src`` and then be dropped.
    """
    edges: list[tuple[str, str]] = []
    seen: set[str] = set()

    def _add(module_path: str) -> None:
        name = module_path.split(".")[-1].strip()
        if not name:
            return
        target = f"prog.{_stem_to_name(name)}"
        if target == source_id or target in seen:
            return
        seen.add(target)
        edges.append((source_id, target))

    for match in re.finditer(r"^from\s+([\w.]+)\s+import\s+", content, re.MULTILINE):
        _add(match.group(1))
    for match in re.finditer(r"^import\s+([\w.]+)", content, re.MULTILINE):
        _add(match.group(1))
    return edges


def _extract_calls_php(content: str, source_id: str) -> list[tuple[str, str]]:
    from pathlib import Path as _Path
    edges = []
    for m in re.finditer(
        r"^(?:require|include)(?:_once)?\s*['\"]([^'\"]+)['\"]",
        content, re.MULTILINE | re.IGNORECASE,
    ):
        stem = _Path(m.group(1)).stem
        if stem:
            edges.append((source_id, f"prog.{_stem_to_name(stem)}"))
    for m in re.finditer(r"^use\s+([\w\\]+)", content, re.MULTILINE):
        name = m.group(1).split("\\")[-1]
        if name:
            edges.append((source_id, f"prog.{name}"))
    return edges


def _extract_calls_javascript(content: str, source_id: str) -> list[tuple[str, str]]:
    from pathlib import Path as _Path
    edges = []
    for m in re.finditer(
        r"""(?:import\s+.*?from\s+|require\s*\(\s*)['\"]([^'"]+)['\"]""",
        content, re.MULTILINE,
    ):
        stem = _Path(m.group(1)).stem.lstrip("./")
        if stem and not stem.startswith("@"):
            edges.append((source_id, f"prog.{_stem_to_name(stem)}"))
    return edges


def _extract_calls_java(content: str, source_id: str) -> list[tuple[str, str]]:
    edges = []
    for m in re.finditer(
        r"^import\s+(?:static\s+)?([\w.]+?)(?:\.\*)?;",
        content, re.MULTILINE,
    ):
        class_name = m.group(1).split(".")[-1]
        if class_name and class_name[0].isupper():
            # Use class_name directly — _stem_to_name corrupts PascalCase
            edges.append((source_id, f"prog.{class_name}"))
    return edges


def _extract_calls_csharp(content: str, source_id: str) -> list[tuple[str, str]]:
    edges = []
    seen: set[str] = set()

    def _add(name: str) -> None:
        if name and name not in seen:
            seen.add(name)
            # Use name directly — _stem_to_name corrupts PascalCase/interface names
            edges.append((source_id, f"prog.{name}"))

    # Constructor parameters — primary DI wiring e.g. public Foo(IBar bar, IBaz baz)
    for ctor in re.finditer(r"public\s+\w+\s*\([^)]+\)", content, re.MULTILINE):
        for pm in re.finditer(
            r"(I[A-Z]\w+|[A-Z]\w+(?:Service|Repository|Context|Controller"
            r"|Scheduler|Settings|Job|Manager|Handler))\s+\w+",
            ctor.group(0),
        ):
            _add(pm.group(1))

    # Private readonly fields — injected dependencies
    for m in re.finditer(
        r"private\s+(?:readonly\s+)?"
        r"(I[A-Z]\w+|[A-Z]\w+(?:Service|Repository|Context|Controller"
        r"|Scheduler|Settings|Job|Manager|Handler))\s+\w+",
        content, re.MULTILINE,
    ):
        _add(m.group(1))

    return edges


def _extract_calls_c(content: str, source_id: str) -> list[tuple[str, str]]:
    """Cross-file dependency edges from local (quoted) #include directives.

    System includes (#include <stdio.h>) are stdlib/external, not part of
    this source estate, and deliberately excluded — matching every other
    _extract_calls_* function's "estate-internal dependencies only" scope.
    """
    edges = []
    seen: set[str] = set()
    for m in re.finditer(r'^\s*#\s*include\s*"([^"]+)"', content, re.MULTILINE):
        included = Path(m.group(1))
        stem = included.stem
        if not stem or stem in seen:
            continue
        seen.add(stem)
        # Headers get a distinct "_h" suffix (see parse_source_estate's own
        # file-node id logic) so an include of "account.h" doesn't collide
        # with account.c's own node — both share the same stem by the
        # near-universal C convention of pairing a header with its
        # implementation file of the same name.
        suffix = "_h" if included.suffix.lower() == ".h" else ""
        edges.append((source_id, f"prog.{_stem_to_name(stem)}{suffix}"))
    return edges


def _sqlx_config_string(config: str, key: str) -> str:
    match = re.search(rf'{key}\s*:\s*"([^"]*)"', config)
    if match:
        return match.group(1).strip()
    match = re.search(rf"{key}\s*:\s*'([^']*)'", config)
    return match.group(1).strip() if match else ""


def _sqlx_config_list(config: str, key: str) -> list[str]:
    match = re.search(rf"{key}\s*:\s*\[(.*?)\]", config, flags=re.DOTALL)
    if not match:
        return []
    return re.findall(r"""["']([^"']+)["']""", match.group(1))


def _split_select_items(select_list: str) -> list[str]:
    items: list[str] = []
    buf: list[str] = []
    depth = 0
    for ch in select_list:
        if ch == "(":
            depth += 1
        elif ch == ")" and depth:
            depth -= 1
        if ch == "," and depth == 0:
            items.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    if buf:
        items.append("".join(buf))
    return items


def _sqlx_columns(body: str) -> list[dict[str, str]]:
    match = re.search(r"\bSELECT\b(.*?)\bFROM\b", body, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return []
    columns: list[dict[str, str]] = []
    for raw in _split_select_items(match.group(1)):
        item = " ".join(raw.split())
        if not item:
            continue
        if item == "*":
            columns.append({"name": "*", "type": ""})
            continue
        alias = re.search(r"\bAS\s+(`?[A-Za-z_][\w]*`?)\s*$", item, flags=re.IGNORECASE)
        if alias:
            name = alias.group(1).strip("`")
            expr = item[: alias.start()].strip()
        else:
            expr = item
            name = item.split(".")[-1].strip("`")
        cast = re.search(
            r"\bAS\s+(NUMERIC|BIGNUMERIC|INT64|FLOAT64|STRING|DATE|TIMESTAMP|BOOL|BOOLEAN)\b",
            expr,
            flags=re.IGNORECASE,
        )
        columns.append({"name": name, "type": cast.group(1).upper() if cast else ""})
    return columns


def _parse_sqlx_document(content: str) -> dict:
    """Read a Dataform .sqlx file: config block, refs, columns, physical tables."""
    config_match = re.search(r"config\s*\{(.*?)\}", content, flags=re.DOTALL)
    config = config_match.group(1) if config_match else ""
    body = content[config_match.end():].strip() if config_match else content.strip()
    deps: list[str] = []
    for name in _sqlx_config_list(config, "dependencies") + re.findall(
        r"""\$\{\s*ref\(\s*["']([^"']+)["']\s*\)\s*\}""",
        body,
    ):
        if name not in deps:
            deps.append(name)
    stripped = re.sub(r"\$\{.*?\}", "", body, flags=re.DOTALL)
    sources: list[str] = []
    for name in re.findall(r"`([^`]+)`", stripped):
        if "." in name and name not in sources:
            sources.append(name)
    materialization = (_sqlx_config_string(config, "type") or "table").lower()
    name = _sqlx_config_string(config, "name")
    schema = _sqlx_config_string(config, "schema")
    description = _sqlx_config_string(config, "description")
    return {
        "name": name,
        "materialization": materialization,
        "schema": schema,
        "description": description or (f"BigQuery Dataform {materialization} {name}" if name else ""),
        "deps": deps,
        "columns": _sqlx_columns(body),
        "sources": sources,
        "has_aggregation": bool(
            re.search(r"\b(GROUP\s+BY|SUM|COUNT|AVG|MIN|MAX)\s*\(", body, flags=re.IGNORECASE)
        ),
    }


def _extract_calls_sqlx(content: str, source_id: str) -> list[tuple[str, str]]:
    """${ref()} and config dependencies are the model's upstream tables."""
    edges: list[tuple[str, str]] = []
    seen: set[str] = set()
    for dep in _parse_sqlx_document(content)["deps"]:
        target = f"prog.{_stem_to_name(dep)}"
        if not dep or target == source_id or target in seen:
            continue
        seen.add(target)
        edges.append((source_id, target))
    return edges


def _parse_sqlx_file(path: str, content: str, file_id: str) -> tuple[list[IRNode], list[IREdge]]:
    """Columns of a Dataform model, plus the physical BigQuery tables it reads."""
    parsed = _parse_sqlx_document(content)
    nodes: list[IRNode] = []
    edges: list[IREdge] = []
    for col in parsed["columns"]:
        col_id = f"col.{file_id}.{col['name']}"
        nodes.append(IRNode(
            id=col_id,
            type=IRNodeType.DATA_ITEM,
            name=col["name"],
            source_location=f"{path}:1",
            attributes={"type": col["type"], "owner": file_id, "dialect": "bigquery"},
        ))
        edges.append(IREdge(source_id=file_id, target_id=col_id, type=IREdgeType.DEFINES))
    for source in parsed["sources"]:
        table_id = "table." + re.sub(r"[^A-Za-z0-9_.]", "_", source)
        nodes.append(IRNode(
            id=table_id,
            type=IRNodeType.DATA_STRUCTURE,
            name=source,
            source_location="",
            attributes={"kind": "bigquery_table", "dialect": "bigquery"},
            summary=f"Physical BigQuery table {source}",
        ))
        edges.append(IREdge(source_id=file_id, target_id=table_id, type=IREdgeType.READS))
    return nodes, edges


_CALL_EXTRACTORS: dict[str, object] = {
    "cobol": _extract_calls_cobol,
    "python": _extract_calls_python,
    "python2": _extract_calls_python,
    "python3": _extract_calls_python,
    "pyspark": _extract_calls_python,
    "php": _extract_calls_php,
    "javascript": _extract_calls_javascript,
    "typescript": _extract_calls_javascript,
    "java": _extract_calls_java,
    "java8": _extract_calls_java,
    "java11": _extract_calls_java,
    "java21": _extract_calls_java,
    "csharp": _extract_calls_csharp,
    "c": _extract_calls_c,
    "sqlx": _extract_calls_sqlx,
}


def _call_extractor_for(source_lang: str):
    lang = source_lang.lower()
    if lang in _CALL_EXTRACTORS:
        return _CALL_EXTRACTORS[lang]
    for key, fn in _CALL_EXTRACTORS.items():
        if lang.startswith(key) or key.startswith(lang):
            return fn
    return None


# ─── helpers for rich signature extraction ───────────────────────────────────

def _ann_str(ann: object) -> str:
    """Convert an AST annotation node to a readable string."""
    import ast as _ast
    if ann is None:
        return ""
    try:
        return _ast.unparse(ann)
    except Exception:
        return ""


def _fn_inputs(func_node: object) -> list[dict[str, str]]:
    """Extract parameter names, types, and defaults from a Python AST function node."""
    args = func_node.args  # type: ignore[attr-defined]
    all_args = getattr(args, "posonlyargs", []) + args.args
    defaults = args.defaults or []
    offset = len(all_args) - len(defaults)
    inputs: list[dict[str, str]] = []
    for i, arg in enumerate(all_args):
        if arg.arg == "self":
            continue
        entry: dict[str, str] = {"name": arg.arg, "type": _ann_str(arg.annotation)}
        if i >= offset:
            entry["default"] = _ann_str(defaults[i - offset])
        inputs.append(entry)
    if args.vararg:
        inputs.append({"name": f"*{args.vararg.arg}", "type": _ann_str(args.vararg.annotation)})
    if args.kwarg:
        inputs.append({"name": f"**{args.kwarg.arg}", "type": _ann_str(args.kwarg.annotation)})
    return inputs


def _docblock_summary(content: str, pos: int) -> str:
    """Return the summary line from the nearest DocBlock before pos."""
    snippet = content[:pos]
    m = re.search(r"/\*\*([\s\S]*?)\*/\s*$", snippet)
    if not m:
        return ""
    lines = [re.sub(r"^\s*\*\s?", "", ln).strip() for ln in m.group(1).splitlines()]
    summary_lines = []
    for ln in lines:
        if not ln or ln.startswith("@"):
            break
        summary_lines.append(ln)
    return " ".join(summary_lines).strip()


def _php_param_list(raw: str) -> list[dict[str, str]]:
    """Parse a PHP parameter string into [{name, type, default}]."""
    params = []
    for part in raw.split(","):
        part = re.sub(r"^\?", "", part.strip()).strip()
        if not part:
            continue
        m = re.match(r"^([\w\\|]+)?\s*(\.\.\.)?\ *\$(\w+)(?:\s*=\s*(.+))?$", part)
        if m:
            entry: dict[str, str] = {
                "name": ("..." if m.group(2) else "") + m.group(3),
                "type": (m.group(1) or "").split("\\")[-1],
            }
            if m.group(4):
                entry["default"] = m.group(4).strip()
            params.append(entry)
    return params


def _php_return_type(content: str, method_end: int) -> str:
    """Extract ': ReturnType' following the closing paren of a PHP method."""
    tail = content[method_end: method_end + 80]
    m = re.match(r"\s*:\s*\??([\w\\|]+)", tail)
    return m.group(1).split("\\")[-1] if m else ""


# ─── language-specific deep node parsers ─────────────────────────────────────

def _parse_php_file(
    file_path: str, content: str, file_id: str
) -> "tuple[list[IRNode], list[IREdge]]":
    nodes: list[IRNode] = []
    edges: list[IREdge] = []

    ns_m = re.search(r"^\s*namespace\s+([\w\\]+)\s*;", content, re.MULTILINE)
    namespace = ns_m.group(1) if ns_m else ""

    cls_re = re.compile(
        r"^\s*(?:abstract\s+|final\s+)?(class|interface|trait)\s+(\w+)"
        r"(?:\s+extends\s+([\w\\]+))?"
        r"(?:\s+implements\s+([\w\\,\s]+?))?\s*\{",
        re.MULTILINE,
    )
    cls_positions: list[tuple[int, str]] = []

    for m in cls_re.finditer(content):
        kind, cls_name = m.group(1).lower(), m.group(2)
        cls_id = f"class.{cls_name}"
        line_no = content[: m.start()].count("\n") + 1
        attrs: dict[str, str] = {"kind": kind, "namespace": namespace}
        if m.group(3):
            attrs["extends"] = m.group(3).split("\\")[-1]
        if m.group(4):
            attrs["implements"] = ", ".join(
                p.strip().split("\\")[-1] for p in m.group(4).split(",") if p.strip()
            )
        summary = _docblock_summary(content, m.start())
        nodes.append(IRNode(
            id=cls_id, type=IRNodeType.DATA_STRUCTURE, name=cls_name,
            source_location=f"{file_path}:{line_no}", attributes=attrs,
            summary=summary,
        ))
        edges.append(IREdge(source_id=file_id, target_id=cls_id, type=IREdgeType.DEFINES))
        cls_positions.append((m.start(), cls_name))
        if m.group(3):
            edges.append(IREdge(
                source_id=cls_id, target_id=f"class.{m.group(3).split(chr(92))[-1]}",
                type=IREdgeType.CALLS,
            ))
        if m.group(4):
            for iface_raw in m.group(4).split(","):
                iface = iface_raw.strip().split("\\")[-1]
                if iface:
                    edges.append(IREdge(
                        source_id=cls_id, target_id=f"class.{iface}",
                        type=IREdgeType.REFERENCES,
                    ))

    def _owner(pos: int) -> "str | None":
        owner = None
        for start, name in cls_positions:
            if start <= pos:
                owner = name
        return owner

    for m in re.finditer(
        r"^\s*(public|protected|private)[\s\w]*function\s+(\w+)\s*\(([^)]*)\)",
        content, re.MULTILINE,
    ):
        owner = _owner(m.start())
        owner_id = f"class.{owner}" if owner else file_id
        method_id = f"method.{owner}.{m.group(2)}" if owner else f"method.{m.group(2)}"
        line_no = content[: m.start()].count("\n") + 1
        inputs = _php_param_list(m.group(3))
        output = _php_return_type(content, m.end())
        summary = _docblock_summary(content, m.start())
        nodes.append(IRNode(
            id=method_id, type=IRNodeType.PROCEDURE, name=m.group(2),
            source_location=f"{file_path}:{line_no}",
            attributes={"visibility": m.group(1)},
            summary=summary,
            inputs=inputs,
            output=output,
        ))
        edges.append(IREdge(source_id=owner_id, target_id=method_id, type=IREdgeType.DEFINES))

    for m in re.finditer(
        r"^\s*(public|protected|private|static)\s+(?:readonly\s+)?(?:\??([\w\\|]+)\s+)?\$(\w+)",
        content, re.MULTILINE,
    ):
        owner = _owner(m.start())
        owner_id = f"class.{owner}" if owner else file_id
        prop_id = f"field.{owner}.{m.group(3)}" if owner else f"field.{m.group(3)}"
        line_no = content[: m.start()].count("\n") + 1
        nodes.append(IRNode(
            id=prop_id, type=IRNodeType.DATA_ITEM, name=m.group(3),
            source_location=f"{file_path}:{line_no}",
            attributes={"visibility": m.group(1), "type": m.group(2) or ""},
        ))
        edges.append(IREdge(source_id=owner_id, target_id=prop_id, type=IREdgeType.DEFINES))

    return nodes, edges


def _parse_python_file(
    file_path: str, content: str, file_id: str
) -> "tuple[list[IRNode], list[IREdge]]":
    """Extract classes and functions; captures types, return types, and docstrings."""
    import ast as _ast
    nodes: list[IRNode] = []
    edges: list[IREdge] = []
    try:
        tree = _ast.parse(content, filename=file_path)
    except SyntaxError:
        return _parse_python_file_regex(file_path, content, file_id)

    for stmt in _ast.iter_child_nodes(tree):
        if isinstance(stmt, _ast.ClassDef):
            cls_id = f"class.{stmt.name}"
            doc = _ast.get_docstring(stmt) or ""
            nodes.append(IRNode(
                id=cls_id,
                type=IRNodeType.DATA_STRUCTURE,
                name=stmt.name,
                source_location=f"{file_path}:{stmt.lineno}",
                attributes={"kind": "class"},
                summary=doc.splitlines()[0] if doc else "",
            ))
            edges.append(IREdge(source_id=file_id, target_id=cls_id, type=IREdgeType.DEFINES))
            for child in _ast.iter_child_nodes(stmt):
                if isinstance(child, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                    method_id = f"method.{stmt.name}.{child.name}"
                    cdoc = _ast.get_docstring(child) or ""
                    nodes.append(IRNode(
                        id=method_id,
                        type=IRNodeType.PROCEDURE,
                        name=child.name,
                        source_location=f"{file_path}:{child.lineno}",
                        attributes={"class": stmt.name},
                        summary=cdoc.splitlines()[0] if cdoc else "",
                        inputs=_fn_inputs(child),
                        output=_ann_str(child.returns),
                    ))
                    edges.append(IREdge(
                        source_id=cls_id, target_id=method_id, type=IREdgeType.DEFINES,
                    ))
        elif isinstance(stmt, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
            fn_id = f"fn.{stmt.name}"
            doc = _ast.get_docstring(stmt) or ""
            nodes.append(IRNode(
                id=fn_id,
                type=IRNodeType.PROCEDURE,
                name=stmt.name,
                source_location=f"{file_path}:{stmt.lineno}",
                attributes={},
                summary=doc.splitlines()[0] if doc else "",
                inputs=_fn_inputs(stmt),
                output=_ann_str(stmt.returns),
            ))
            edges.append(IREdge(source_id=file_id, target_id=fn_id, type=IREdgeType.DEFINES))

    return nodes, edges


def _parse_python_file_regex(
    file_path: str, content: str, file_id: str
) -> "tuple[list[IRNode], list[IREdge]]":
    """Regex fallback for Python 2 files. Extracts param names and inline docstrings."""
    nodes: list[IRNode] = []
    edges: list[IREdge] = []
    current_class: "str | None" = None
    lines = content.splitlines()

    def _peek_docstring(idx: int) -> str:
        for i in range(idx + 1, min(idx + 4, len(lines))):
            s = lines[i].strip()
            if s.startswith('"""') or s.startswith("'''"):
                return s.strip('"\'').strip()
        return ""

    def _py2_params(sig: str) -> list[dict[str, str]]:
        params = []
        for p in sig.split(","):
            p = p.strip()
            if not p or p == "self":
                continue
            name = p.split("=")[0].strip()
            entry: dict[str, str] = {"name": name, "type": ""}
            if "=" in p:
                entry["default"] = p.split("=", 1)[1].strip()
            params.append(entry)
        return params

    for lineno, line in enumerate(lines, 1):
        cls_m = re.match(r"^class\s+(\w+)", line)
        if cls_m:
            current_class = cls_m.group(1)
            cls_id = f"class.{current_class}"
            nodes.append(IRNode(
                id=cls_id, type=IRNodeType.DATA_STRUCTURE, name=current_class,
                source_location=f"{file_path}:{lineno}", attributes={"kind": "class"},
                summary=_peek_docstring(lineno - 1),
            ))
            edges.append(IREdge(source_id=file_id, target_id=cls_id, type=IREdgeType.DEFINES))
            continue

        mod_fn = re.match(r"^def\s+(\w+)\s*\(([^)]*)\)", line)
        if mod_fn:
            current_class = None
            fn_id = f"fn.{mod_fn.group(1)}"
            nodes.append(IRNode(
                id=fn_id, type=IRNodeType.PROCEDURE, name=mod_fn.group(1),
                source_location=f"{file_path}:{lineno}", attributes={},
                summary=_peek_docstring(lineno - 1),
                inputs=_py2_params(mod_fn.group(2)),
            ))
            edges.append(IREdge(source_id=file_id, target_id=fn_id, type=IREdgeType.DEFINES))
            continue

        if current_class:
            meth_m = re.match(r"^    def\s+(\w+)\s*\(([^)]*)\)", line)
            if meth_m:
                method_id = f"method.{current_class}.{meth_m.group(1)}"
                nodes.append(IRNode(
                    id=method_id, type=IRNodeType.PROCEDURE, name=meth_m.group(1),
                    source_location=f"{file_path}:{lineno}",
                    attributes={"class": current_class},
                    summary=_peek_docstring(lineno - 1),
                    inputs=_py2_params(meth_m.group(2)),
                ))
                edges.append(IREdge(
                    source_id=f"class.{current_class}", target_id=method_id,
                    type=IREdgeType.DEFINES,
                ))

    return nodes, edges

def _extract_ts_struct_fields(lines: list[str], start_line: int) -> list[dict[str, str]]:
    """Scan from a class/interface declaration and extract field/property definitions.

    Stops at the matching closing brace. Skips method signatures (detected by
    the presence of `(` before the `:` type annotation).
    """
    fields: list[dict[str, str]] = []
    depth = 0
    in_body = False
    _skip = {"constructor", "return", "if", "for", "while", "switch", "case",
              "const", "let", "var", "type", "interface", "class", "enum",
              "function", "import", "export", "get", "set", "new", "delete",
              "typeof", "instanceof", "void", "throw", "try", "catch", "finally"}

    field_re = re.compile(
        r"^(?:(?:public|private|protected|readonly|static|declare|override|abstract|#)\s+)*"
        r"([\w$#]+)"        # field name
        r"(\?)?"            # optional marker
        r"(?:\s*!)?"        # non-null assertion
        r"\s*:"             # type annotation separator
    )

    for i in range(start_line, min(start_line + 300, len(lines))):
        line = lines[i]
        stripped = line.strip()

        opens  = line.count("{")
        closes = line.count("}")

        if not in_body:
            if "{" in line:
                in_body = True
                depth = opens - closes
            continue

        depth += opens - closes
        if depth <= 0:
            break  # end of class/interface body

        # Only examine direct body level
        if depth != 1:
            continue

        if not stripped or stripped.startswith(("//", "*", "/*", "@")):
            continue
        if stripped.startswith(("[",)):   # index signatures
            continue

        # Reject method signatures: if there is a `(` before the first `:`
        colon_idx = stripped.find(":")
        if colon_idx == -1:
            continue
        before_colon = stripped[:colon_idx]
        if "(" in before_colon or "=>" in before_colon:
            continue

        m = field_re.match(stripped)
        if not m:
            continue

        name = m.group(1)
        if name in _skip:
            continue

        optional = bool(m.group(2))
        after = stripped[m.end():].strip()
        # Stop type string at ; or = or // or {
        for stop_ch in (";", " =", "//", " {"):
            idx = after.find(stop_ch)
            if idx != -1:
                after = after[:idx]
        type_str = after.strip().rstrip(";").strip()
        if not type_str:
            continue

        entry: dict[str, str] = {"name": name, "type": type_str}
        if optional:
            entry["optional"] = "true"
        fields.append(entry)

    return fields


def _infer_ds_summary(name: str, fields: list[dict], file_path: str) -> str:
    """Derive a one-sentence domain summary for a class/interface from its name and fields."""
    # Split PascalCase into words
    words = re.sub(r"([A-Z][a-z])", r" \1",
                   re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", name)).split()
    lname = name.lower()
    field_names = ", ".join(f["name"] for f in fields[:4])

    def _entity(skip: set) -> str:
        return " ".join(w for w in words if w.lower() not in skip) or name

    if any(lname.endswith(s) for s in ("dto", "request", "input", "command")):
        action_w = next((w for w in words if w.lower() in
                         ("create", "update", "patch", "delete", "upsert", "add", "remove")), "")
        action = f"{action_w.lower()}ing" if action_w else "managing"
        ent = _entity({"dto", "request", "input", "command", action_w.lower()})
        return f"Request payload for {action} a {ent}." + (f" Fields: {field_names}." if field_names else "")

    if any(lname.endswith(s) for s in ("response", "result", "output", "view")):
        ent = _entity({"response", "result", "output", "view"})
        return f"Response shape for {ent} operations." + (f" Fields: {field_names}." if field_names else "")

    if any(lname.endswith(s) for s in ("entity", "model", "record", "row")):
        ent = _entity({"entity", "model", "record", "row"})
        return f"Database entity representing {ent}." + (f" Fields: {field_names}." if field_names else "")

    if lname.endswith("service"):
        return f"Service providing {_entity({'service'})} operations."

    if lname.endswith("controller"):
        return f"HTTP controller handling {_entity({'controller'})} endpoints."

    if any(lname.endswith(s) for s in ("repository", "repo", "dao")):
        return f"Data access layer for {_entity({'repository', 'repo', 'dao'})} records."

    if any(lname.endswith(s) for s in ("config", "options", "settings", "configuration")):
        return f"Configuration for {_entity({'config', 'options', 'settings', 'configuration'})}."

    if any(lname.endswith(s) for s in ("props", "component")):
        return f"Props interface for the {_entity({'props', 'component'})} UI component."

    if fields:
        return f"{name} with {len(fields)} field{'s' if len(fields) != 1 else ''}: {field_names}."

    return f"{' '.join(words)} structure."


def _proc_summary_from_sig(name: str, inputs: list[dict], output: str) -> str:
    """Generate a fallback one-sentence summary for a PROCEDURE from its signature."""
    params = [
        p["name"] + (": " + p["type"] if p.get("type") else "")
        for p in inputs
        if p.get("name") and p["name"] not in ("self", "this")
    ]
    param_str = ", ".join(params[:3]) + ("…" if len(params) > 3 else "")

    if params and output:
        return f"Takes {param_str} and returns {output}."
    if params:
        return f"Accepts {param_str}."
    if output:
        return f"Returns {output}."
    # Humanise the function name
    human = re.sub(r"([A-Z])", r" \1", name).strip().lower()
    return f"Performs {human}."


_PATH_DOMAIN_MAP = {
    "e2e": "E2E test", "spec": "test", "test": "test", "__tests__": "test",
    "auth": "authentication", "billing": "billing", "allocation": "resource allocation",
    "timesheet": "timesheets", "admin": "admin", "user": "user management",
    "client": "client management", "project": "project management",
    "proposal": "proposals", "crm": "CRM", "api": "API", "service": "service",
    "component": "UI component", "hook": "React hook", "dto": "data transfer",
    "entity": "data entity", "migration": "database migration", "config": "configuration",
    "feature": "feature", "module": "module", "shared": "shared utilities",
    "utils": "utilities", "helper": "helpers", "middleware": "middleware",
    "guard": "route guard", "interceptor": "interceptor", "filter": "filter",
    "decorator": "decorator", "pipe": "validation pipe",
}


def _path_domain(file_path: str, source_path: str = "") -> str:
    """Extract a human-readable domain label from a file's directory path segments."""
    try:
        from pathlib import Path as _P
        rel = str(_P(file_path).relative_to(source_path)) if source_path else file_path
    except ValueError:
        rel = file_path

    from pathlib import Path as _P
    parts = [p.lower().replace("-", " ").replace("_", " ")
             for p in _P(rel).parts]
    stem = _P(rel).stem.lower().replace("-", " ").replace("_", " ").replace(".spec", "").replace(".test", "")

    seen: set[str] = set()
    labels: list[str] = []
    for part in list(parts) + [stem]:
        for keyword, label in _PATH_DOMAIN_MAP.items():
            if keyword in part and label not in seen:
                seen.add(label)
                labels.append(label)
    return " / ".join(labels[:3])


def _parse_ts_params(raw: str) -> list[dict[str, str]]:
    """Parse TypeScript/JavaScript parameter string into [{name, type, default}]."""
    params = []
    depth = 0
    current = ""
    for ch in raw:
        if ch in "<({[":
            depth += 1
        elif ch in ">)}]":
            depth -= 1
        if ch == "," and depth == 0:
            params.append(current.strip())
            current = ""
        else:
            current += ch
    if current.strip():
        params.append(current.strip())

    result = []
    for p in params:
        p = p.strip()
        if not p or p in ("this",):
            continue
        # Strip leading access modifiers (constructor param injection: private x: T)
        p = re.sub(r"^(public|private|protected|readonly)\s+", "", p)
        # Optional marker
        p = re.sub(r"\?", "", p)
        # Destructuring — represent as-is
        if p.startswith("{") or p.startswith("["):
            result.append({"name": p.split(":")[0].strip(), "type": ""})
            continue
        # name: type = default  or  ...rest: type
        m = re.match(r"^(\.\.\.)?(\w+)\s*(?::\s*(.+?))?(?:\s*=\s*(.+))?$", p)
        if m:
            entry: dict[str, str] = {
                "name": ("..." if m.group(1) else "") + m.group(2),
                "type": (m.group(3) or "").strip(),
            }
            if m.group(4):
                entry["default"] = m.group(4).strip()
            result.append(entry)
    return result


def _parse_typescript_file(
    file_path: str, content: str, file_id: str
) -> "tuple[list[IRNode], list[IREdge]]":
    """Extract classes, interfaces, functions, and arrow-function exports from TS/JS."""
    nodes: list[IRNode] = []
    edges: list[IREdge] = []
    lines = content.splitlines()

    # Track class context using brace depth
    current_class: str | None = None
    class_open_depth = 0   # brace depth when the class { was opened
    brace_depth = 0

    # Regex patterns
    cls_re = re.compile(
        r"^\s*(export\s+)?(export\s+default\s+)?(abstract\s+)?class\s+(\w+)"
        r"(?:\s+extends\s+[\w<>, .]+)?(?:\s+implements\s+[\w<>, .]+)?"
    )
    iface_re = re.compile(r"^\s*(export\s+)?interface\s+(\w+)")
    fn_re = re.compile(
        r"^\s*(export\s+)?(default\s+)?(async\s+)?function\s+(\w+)\s*(?:<[^>]*>)?\s*\(([^)]*)\)"
        r"(?:\s*:\s*([\w<>\[\]|,\s.{}?]+))?"
    )
    arrow_re = re.compile(
        r"^\s*(export\s+)(const|let)\s+(\w+)\s*(?::<[^>]+>)?\s*=\s*(async\s+)?"
        r"\(([^)]*)\)\s*(?::\s*([\w<>\[\]|,\s.{}?]+))?\s*=>"
    )
    # Method inside a class (2+ spaces indent, not a keyword line)
    method_re = re.compile(
        r"^\s{2,}(public\s+|private\s+|protected\s+|static\s+|async\s+|override\s+|abstract\s+)*"
        r"(get\s+|set\s+)?(\w+)\s*(?:<[^>]*>)?\s*\(([^)]*)\)"
        r"(?:\s*:\s*([\w<>\[\]|,\s.{}?]+))?"
        r"\s*[{;]"
    )
    # Multi-line method start: name( with no ) on the same line
    method_open_re = re.compile(
        r"^\s{2,}((?:public|private|protected|static|async|override|abstract)\s+)*"
        r"((?:get|set)\s+)?(\w+)\s*(?:<[^>]*>)?\s*\((?:[^)]*)?$"
    )
    # Pending multi-line method state
    _pending_method_groups: tuple | None = None
    _pending_method_lineno: int = 0
    _pending_method_buf: str = ""

    def _docblock(idx: int) -> str:
        """Return the JSDoc summary line immediately above line idx."""
        for i in range(idx - 1, max(-1, idx - 6), -1):
            s = lines[i].strip()
            if s.startswith("*") and not s.startswith("*/"):
                text = re.sub(r"^\*\s?", "", s).strip()
                if text and not text.startswith("@"):
                    return text
            elif s.startswith("/**"):
                return ""
            elif s and not s.startswith("//") and not s.startswith("*"):
                break
        return ""

    for lineno, line in enumerate(lines, 1):
        opens = line.count("{")
        closes = line.count("}")

        # --- Class ---
        cm = cls_re.match(line)
        if cm:
            cls_name = cm.group(4)
            cls_id = f"class.{cls_name}"
            is_exported = bool(cm.group(1) or cm.group(2))
            is_abstract = bool(cm.group(3))
            nodes.append(IRNode(
                id=cls_id, type=IRNodeType.DATA_STRUCTURE, name=cls_name,
                source_location=f"{file_path}:{lineno}",
                attributes={
                    "kind": "class",
                    "export": "true" if is_exported else "false",
                    "abstract": "true" if is_abstract else "false",
                },
                summary=_docblock(lineno - 1),
            ))
            edges.append(IREdge(source_id=file_id, target_id=cls_id, type=IREdgeType.DEFINES))
            if opens > closes:
                current_class = cls_name
                class_open_depth = brace_depth
            brace_depth += opens - closes
            continue

        # --- Interface ---
        im = iface_re.match(line)
        if im:
            iname = im.group(2)
            iface_id = f"class.{iname}"
            nodes.append(IRNode(
                id=iface_id, type=IRNodeType.DATA_STRUCTURE, name=iname,
                source_location=f"{file_path}:{lineno}",
                attributes={
                    "kind": "interface",
                    "export": "true" if im.group(1) else "false",
                },
                summary=_docblock(lineno - 1),
            ))
            edges.append(IREdge(source_id=file_id, target_id=iface_id, type=IREdgeType.DEFINES))
            brace_depth += opens - closes
            continue

        brace_depth += opens - closes

        # Exit class context when we return to its opening depth
        if current_class is not None and brace_depth <= class_open_depth:
            current_class = None

        # --- Standalone function ---
        fm = fn_re.match(line)
        if fm and not current_class:
            fn_name = fm.group(4)
            fn_id = f"fn.{fn_name}"
            nodes.append(IRNode(
                id=fn_id, type=IRNodeType.PROCEDURE, name=fn_name,
                source_location=f"{file_path}:{lineno}",
                attributes={
                    "kind": "function",
                    "export": "true" if fm.group(1) else "false",
                    "async": "true" if fm.group(3) else "false",
                },
                summary=_docblock(lineno - 1),
                inputs=_parse_ts_params(fm.group(5) or ""),
                output=re.sub(r"\s*[{;]\s*$", "", (fm.group(6) or "").strip()).strip(),
            ))
            edges.append(IREdge(source_id=file_id, target_id=fn_id, type=IREdgeType.DEFINES))
            continue

        # --- Arrow function export ---
        am = arrow_re.match(line)
        if am and not current_class:
            fn_name = am.group(3)
            fn_id = f"fn.{fn_name}"
            nodes.append(IRNode(
                id=fn_id, type=IRNodeType.PROCEDURE, name=fn_name,
                source_location=f"{file_path}:{lineno}",
                attributes={
                    "kind": "arrow",
                    "export": "true",
                    "async": "true" if am.group(4) else "false",
                },
                summary=_docblock(lineno - 1),
                inputs=_parse_ts_params(am.group(5) or ""),
                output=re.sub(r"\s*[{;]\s*$", "", (am.group(6) or "").strip()).strip(),
            ))
            edges.append(IREdge(source_id=file_id, target_id=fn_id, type=IREdgeType.DEFINES))
            continue

        # --- Method inside class ---
        if current_class:
            # Flush a pending multi-line method when we see ): ReturnType { or ); or ) {
            if _pending_method_groups is not None:
                stripped = line.strip()
                _pending_method_buf += " " + stripped
                # Check if we've hit the closing ) now
                if ")" in stripped:
                    full_sig = _pending_method_buf
                    # Extract params: text between first ( and last matching )
                    p_start = full_sig.find("(")
                    p_end   = full_sig.rfind(")")
                    param_str = full_sig[p_start + 1: p_end] if p_start != -1 and p_end != -1 else ""
                    # Extract return type: after ): up to { or ;
                    ret_m = re.search(r"\)\s*:\s*([^{;\n]+)", full_sig)
                    raw_out = re.sub(r"\s*[{;]\s*$", "", (ret_m.group(1) if ret_m else "").strip()).strip()
                    inputs = _parse_ts_params(param_str)
                    pg = _pending_method_groups
                    method_name = pg[2]
                    modifiers = "".join(filter(None, [pg[0], pg[1]])).strip()
                    doc = _docblock(_pending_method_lineno - 1)
                    method_id = f"method.{current_class}.{method_name}"
                    nodes.append(IRNode(
                        id=method_id, type=IRNodeType.PROCEDURE, name=method_name,
                        source_location=f"{file_path}:{_pending_method_lineno}",
                        attributes={"class": current_class, "modifiers": modifiers,
                                    "kind": "getter" if "get " in modifiers else
                                            "setter" if "set " in modifiers else "method"},
                        summary=doc or _proc_summary_from_sig(method_name, inputs, raw_out),
                        inputs=inputs,
                        output=raw_out,
                    ))
                    edges.append(IREdge(
                        source_id=f"class.{current_class}", target_id=method_id,
                        type=IREdgeType.DEFINES,
                    ))
                    _pending_method_groups = None
                    _pending_method_buf = ""
                continue

            mm = method_re.match(line)
            if mm:
                method_name = mm.group(3)
                # Skip reserved words and decorators
                if method_name in ("if", "for", "while", "switch", "return", "const",
                                   "let", "var", "try", "catch", "import", "export"):
                    continue
                method_id = f"method.{current_class}.{method_name}"
                modifiers = "".join(filter(None, [mm.group(1), mm.group(2)])).strip()
                raw_out = re.sub(r"\s*[{;]\s*$", "", (mm.group(5) or "").strip()).strip()
                inputs = _parse_ts_params(mm.group(4) or "")
                doc = _docblock(lineno - 1)
                nodes.append(IRNode(
                    id=method_id, type=IRNodeType.PROCEDURE, name=method_name,
                    source_location=f"{file_path}:{lineno}",
                    attributes={"class": current_class, "modifiers": modifiers,
                                "kind": "getter" if "get " in modifiers else
                                        "setter" if "set " in modifiers else "method"},
                    summary=doc or _proc_summary_from_sig(method_name, inputs, raw_out),
                    inputs=inputs,
                    output=raw_out,
                ))
                edges.append(IREdge(
                    source_id=f"class.{current_class}", target_id=method_id,
                    type=IREdgeType.DEFINES,
                ))
            else:
                # Detect the start of a multi-line method signature
                mom = method_open_re.match(line)
                if mom and mom.group(3) not in (
                    "if", "for", "while", "switch", "return", "const",
                    "let", "var", "try", "catch", "import", "export", "constructor",
                ):
                    _pending_method_groups = (mom.group(1) or "", mom.group(2) or "", mom.group(3))
                    _pending_method_lineno = lineno
                    _pending_method_buf = line.strip()

    # ── Post-loop enrichment ──────────────────────────────────────────────────

    def _multiline_params(start_line: int) -> list[dict[str, str]]:
        """Extract params from a multi-line function signature starting at start_line."""
        text = ""
        depth = 0
        opened = False
        for i in range(start_line, min(start_line + 30, len(lines))):
            for ch in lines[i]:
                if ch == "(" and not opened:
                    opened = True
                    depth = 1
                elif ch == "(" and opened:
                    depth += 1
                    text += ch
                elif ch == ")":
                    if not opened:
                        continue
                    depth -= 1
                    if depth == 0:
                        return _parse_ts_params(text)
                    text += ch
                elif opened and depth > 0:
                    text += ch
            if opened:
                text += " "
        return []

    # 1. Extract struct fields for each DATA_STRUCTURE node and generate summary
    # 2. Fill inputs from multi-line signatures for PROCEDURE nodes
    # 3. Fill fallback summaries for PROCEDURE nodes that had no JSDoc
    for n in nodes:
        if n.type == IRNodeType.DATA_STRUCTURE:
            loc = n.source_location
            if loc and ":" in loc:
                fpath_loc, ln_str = loc.rsplit(":", 1)
                try:
                    start = int(ln_str) - 1
                    fields = _extract_ts_struct_fields(lines, start)
                    if fields:
                        n.inputs = fields
                    n.attributes["field_count"] = str(len(fields))
                    # Always regenerate summary from fields + name (not adjacent JSDoc)
                    n.summary = _infer_ds_summary(n.name, fields, file_path)
                except (ValueError, IndexError):
                    pass

        elif n.type == IRNodeType.PROCEDURE:
            # Clean trailing { from output
            if n.output:
                n.output = re.sub(r"\s*[{;]\s*$", "", n.output).strip()
            # Extract multi-line params for nodes the single-line regex missed
            if not n.inputs and n.source_location and ":" in n.source_location:
                _, ln_str = n.source_location.rsplit(":", 1)
                try:
                    params = _multiline_params(int(ln_str) - 1)
                    if params:
                        n.inputs = params
                except (ValueError, IndexError):
                    pass
            # Fill summary if missing
            if not n.summary:
                n.summary = _proc_summary_from_sig(n.name, n.inputs or [], n.output or "")

    return nodes, edges


_JAVA_MOD = r"(?:public|private|protected|static|final|abstract|synchronized|native|default|transient|volatile|sealed|non-sealed)\s+"
_JAVA_TYPE = r"[\w\[\]<>.,?]+"
# Annotation prefix: only matches lines that end after the annotation (no code on same line).
# @\w+(?:\([^)]*\))? matches @Name or @Name(args); \s*\n ensures newline follows.
# [ \t]* (not \s*) immediately before the required \n: \s overlaps with the literal \n
# it precedes, so a run of many blank lines gives the regex engine O(n) ways to split
# "how much does the leading \s* eat vs. the trailing \s*" for every one of those lines
# — measured ~1.4-1.8s to fail a single match attempt against 8,000 blank lines
# following a stray annotation. Restricting the leading whitespace to non-newline
# characters removes that ambiguity (there's exactly one way to match "rest of this
# line, then the newline"), fixing the blowup without changing what matches.
_JAVA_ANN = r"(?:@\w+(?:\([^)]*\))?[ \t]*\n\s*)*"
_JAVA_CLASS_RE = re.compile(
    r"^\s*" + _JAVA_ANN
    + r"(?:" + _JAVA_MOD + r")*"
    r"(class|interface|enum|record)\s+(\w+)"
    r"(?:\s+extends\s+(" + _JAVA_TYPE + r"(?:,\s*" + _JAVA_TYPE + r")*))?"
    r"(?:\s+implements\s+(" + _JAVA_TYPE + r"(?:,\s*" + _JAVA_TYPE + r")*))?"
    r"\s*[{<]",
    re.MULTILINE,
)
_JAVA_METHOD_RE = re.compile(
    r"^\s*" + _JAVA_ANN
    + r"(?:" + _JAVA_MOD + r")+"
    r"(?:<[^>]+>\s+)?"
    r"(" + _JAVA_TYPE + r"(?:[ \t]+" + _JAVA_TYPE + r")*)\s+"
    r"(\w+)\s*\(([^)]*)\)\s*(?:throws\s+[\w, ]+\s*)?\{",
    re.MULTILINE,
)
# Package-private methods (no access modifier — legal in Java, and the conventional
# style for Axon's @EventSourcingHandler methods) require at least one annotation line
# — _JAVA_METHOD_RE above already covers the modifier case, and this regex's negative
# lookahead for a modifier keyword keeps the two mutually exclusive rather than
# double-matching. Requiring an annotation (not making it optional the way _JAVA_ANN
# normally is) is deliberate: without it this would also match a bare
# "TYPE name(...) {" line with no modifier and no annotation, e.g. the opening brace of
# an anonymous inner class ("new Runnable() {") mis-parsed as a method named "Runnable"
# with return type "new".
_JAVA_ANN_REQUIRED = r"(?:@\w+(?:\([^)]*\))?[ \t]*\n\s*)+"  # same fix as _JAVA_ANN above
_JAVA_PKG_METHOD_RE = re.compile(
    r"^\s*" + _JAVA_ANN_REQUIRED
    + r"(?!" + _JAVA_MOD + r")"
    r"(?:<[^>]+>\s+)?"
    r"(" + _JAVA_TYPE + r"(?:[ \t]+" + _JAVA_TYPE + r")*)\s+"
    r"(\w+)\s*\(([^)]*)\)\s*(?:throws\s+[\w, ]+\s*)?\{",
    re.MULTILINE,
)
_JAVA_FIELD_RE = re.compile(
    r"^\s*" + _JAVA_ANN
    + r"(?:" + _JAVA_MOD + r")+"
    r"(" + _JAVA_TYPE + r"(?:[ \t]+" + _JAVA_TYPE + r")*)\s+"
    r"(\w+)\s*[=;]",
    re.MULTILINE,
)


def _java_param_list(raw: str) -> list[dict[str, str]]:
    params = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        part = re.sub(r"@\w+\s*", "", part).strip()
        m = re.match(r"([\w\[\]<>.,? ]+?)\s+(\w+)$", part)
        if m:
            params.append({"name": m.group(2), "type": m.group(1).strip()})
    return params


_JAVA_CTOR_RE = re.compile(
    r"^\s*" + _JAVA_ANN
    + r"(?:" + _JAVA_MOD + r")*"
    r"(\w+)\s*\(([^)]*)\)\s*(?:throws\s+[\w, ]+\s*)?\{",
    re.MULTILINE,
)

# Axon-specific handler annotations -> the handler_type they denote. Detection is
# gated on the annotation actually being imported from org.axonframework.* (see
# _axon_annotations below) so an unrelated same-named annotation (e.g. a hand-rolled
# @CommandHandler) isn't mistaken for Axon.
_AXON_PACKAGE_PREFIX = "org.axonframework."
_AXON_HANDLER_ANNOTATIONS: dict[str, str] = {
    "CommandHandler": "command",
    "EventHandler": "event",
    "QueryHandler": "query",
    "EventSourcingHandler": "event-sourcing",
    # A saga (process manager) reacts to events to orchestrate a long-running
    # workflow across aggregates. Its handlers live in org.axonframework.modelling.saga,
    # so they resolve through the same import gate as every other name here.
    "SagaEventHandler": "saga-event",
}

# Class-level saga marker (org.axonframework.spring.stereotype.Saga), the process-manager
# equivalent of @Aggregate. Kept separate from the handler map because it annotates a
# class, not a method, and so is checked alongside "Aggregate" rather than in the
# per-method handler loop.
_AXON_SAGA_CLASS_ANNOTATION = "Saga"

# @ProcessingGroup names the event processor a handler class belongs to. Two classes
# in different processing groups are independently deployable and independently
# replayable event processors, so a message flow spanning two groups is a firmer
# migration boundary than one contained inside a single group.
_AXON_PROCESSING_GROUP_ANNOTATION = "ProcessingGroup"
_PROCESSING_GROUP_RE = re.compile(r'@ProcessingGroup\s*\(\s*"([^"]+)"')


_AXON_ANNOTATION_NAMES = frozenset({
    "Aggregate", "AggregateIdentifier", _AXON_SAGA_CLASS_ANNOTATION,
    _AXON_PROCESSING_GROUP_ANNOTATION,
    # Lifecycle markers — not handlers themselves, but they must resolve so that a
    # method carrying only @StartSaga/@EndSaga alongside @SagaEventHandler is still
    # recognised, and so _JAVA_PKG_METHOD_RE's "annotated, no access modifier" path
    # sees them.
    "StartSaga", "EndSaga",
    *_AXON_HANDLER_ANNOTATIONS,
})


def _java_import_map(content: str) -> tuple[dict[str, str], frozenset[str]]:
    """Map bare imported type name -> fully-qualified name, e.g.
    {"CommandHandler": "org.axonframework.commandhandling.CommandHandler"}, plus the set
    of packages imported via wildcard (e.g. "org.axonframework.commandhandling" from
    `import org.axonframework.commandhandling.*;`) — the exact-name regex below can't
    capture a wildcard import's individual names, so those are resolved separately in
    _axon_annotations() against the known, fixed set of Axon annotation names."""
    imports: dict[str, str] = {}
    for m in re.finditer(r"^import\s+(?:static\s+)?([\w.]+);", content, re.MULTILINE):
        fqn = m.group(1)
        imports[fqn.rsplit(".", 1)[-1]] = fqn
    wildcard_packages = frozenset(
        m.group(1) for m in re.finditer(r"^import\s+(?:static\s+)?([\w.]+)\.\*;", content, re.MULTILINE)
    )
    return imports, wildcard_packages


def _axon_annotations(
    match_text: str, import_map: dict[str, str], wildcard_packages: frozenset[str] = frozenset(),
) -> list[str]:
    """Bare annotation names attached to a regex match's full span (which includes any
    directly-preceding annotation lines via _JAVA_ANN) that resolve to an
    org.axonframework.* import — either an exact import_map entry, or a wildcard import
    (`org.axonframework.x.*`) combined with the name being one of the fixed, known Axon
    annotation names (wildcard imports don't tell us which names they bring in, so this
    is deliberately restricted to names we already know to look for, not any name)."""
    names = re.findall(r"@(\w+)", match_text)
    resolved = []
    for n in names:
        if import_map.get(n, "").startswith(_AXON_PACKAGE_PREFIX):
            resolved.append(n)
        elif n in _AXON_ANNOTATION_NAMES and any(
            pkg.startswith(_AXON_PACKAGE_PREFIX.rstrip(".")) for pkg in wildcard_packages
        ):
            resolved.append(n)
    return resolved


def _parse_java_file(
    file_path: str, content: str, file_id: str
) -> "tuple[list[IRNode], list[IREdge]]":
    nodes: list[IRNode] = []
    edges: list[IREdge] = []

    if file_path.endswith(".sql"):
        for i, line in enumerate(content.splitlines(), 1):
            # Optional IF NOT EXISTS, optional schema-qualified name (dbo.Orders),
            # optional backtick/quote/bracket delimiters on either segment. Group 2 is
            # the table name proper (group 1, the schema, is discarded — recorded
            # nowhere downstream today, and keeping just the table name preserves the
            # existing single-name node identity). Does not handle quoted identifiers
            # containing spaces (e.g. "Order Items") or multi-line declarations
            # (table name on its own line) — accepted limitations of this lightweight
            # line-by-line scanner, consistent with the rest of the file.
            table_m = re.match(
                r'(?i)^\s*CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?'
                r'(?:[`"\[]?(\w+)[`"\]]?\.)?[`"\[]?(\w+)[`"\]]?',
                line,
            )
            if table_m:
                tbl_name = table_m.group(2)
                # "table." rather than "class." — a Java class and its JPA-backing
                # table commonly share a literal name (e.g. class Order / table
                # Order); the old class.<name> id let a table node silently collide
                # with a same-named Java class node in the same run's IR graph.
                tbl_id = f"table.{tbl_name}"
                nodes.append(IRNode(
                    id=tbl_id, type=IRNodeType.DATA_STRUCTURE, name=tbl_name,
                    source_location=f"{file_path}:{i}", attributes={"kind": "table"},
                ))
                edges.append(IREdge(source_id=file_id, target_id=tbl_id, type=IREdgeType.DEFINES))
        return nodes, edges

    import_map, wildcard_packages = _java_import_map(content)
    cls_positions: list[tuple[int, str]] = []

    for m in _JAVA_CLASS_RE.finditer(content):
        kind, cls_name = m.group(1).lower(), m.group(2)
        cls_id = f"class.{cls_name}"
        line_no = content[: m.start()].count("\n") + 1
        attrs: dict[str, str] = {"kind": kind}
        if m.group(3):
            attrs["extends"] = m.group(3).strip().split("<")[0].strip()
        if m.group(4):
            attrs["implements"] = ", ".join(
                i.strip().split("<")[0].strip() for i in m.group(4).split(",") if i.strip()
            )
        _cls_axon = _axon_annotations(m.group(0), import_map, wildcard_packages)
        if "Aggregate" in _cls_axon:
            attrs["is_axon_aggregate"] = "true"
        if _AXON_SAGA_CLASS_ANNOTATION in _cls_axon:
            attrs["is_axon_saga"] = "true"
        if _AXON_PROCESSING_GROUP_ANNOTATION in _cls_axon:
            _pg = _PROCESSING_GROUP_RE.search(m.group(0))
            if _pg:
                attrs["processing_group"] = _pg.group(1)
        summary = _docblock_summary(content, m.start())
        nodes.append(IRNode(
            id=cls_id, type=IRNodeType.DATA_STRUCTURE, name=cls_name,
            source_location=f"{file_path}:{line_no}", attributes=attrs,
            summary=summary,
        ))
        edges.append(IREdge(source_id=file_id, target_id=cls_id, type=IREdgeType.DEFINES))
        cls_positions.append((m.end(), cls_name))
        if m.group(3):
            parent = m.group(3).strip().split("<")[0].strip()
            edges.append(IREdge(source_id=cls_id, target_id=f"class.{parent}", type=IREdgeType.REFERENCES))
        if m.group(4):
            for iface_raw in m.group(4).split(","):
                iface = iface_raw.strip().split("<")[0].strip()
                if iface:
                    edges.append(IREdge(source_id=cls_id, target_id=f"class.{iface}", type=IREdgeType.REFERENCES))

    # Body ranges (not just "declared before this position") so ownership resolution
    # is nesting-aware: a field/method textually after a nested enum/inner class's
    # closing brace must resolve to the OUTER class, not the nested one, which a plain
    # "last class declared before this position" check gets wrong (Samuel Mbah / PR #27
    # follow-up review). _JAVA_CLASS_RE's match ends at the first '{' or '<' it finds
    # (stored above as m.end()) — searching for the body's own '{' from there, rather
    # than from the match start, also correctly skips past any '{' embedded in a
    # preceding annotation's array-literal argument (e.g. @SuppressWarnings({"x"})),
    # since annotations are consumed earlier in the same regex match. Does not account
    # for '{'/'}' inside string/char literals or comments — an accepted limitation of
    # this lightweight regex-based parser, consistent with the rest of the file.
    cls_body_ranges: list[tuple[int, int, str]] = []
    for end_pos, cls_name in cls_positions:
        brace_pos = content.find("{", end_pos - 1)
        if brace_pos == -1:
            continue
        depth = 1
        i = brace_pos + 1
        n = len(content)
        while i < n and depth > 0:
            if content[i] == "{":
                depth += 1
            elif content[i] == "}":
                depth -= 1
            i += 1
        cls_body_ranges.append((brace_pos, i, cls_name))

    def _owner_class(pos: int) -> "str | None":
        best_name = None
        best_size = None
        for body_start, body_end, name in cls_body_ranges:
            if body_start <= pos < body_end and (best_size is None or (body_end - body_start) < best_size):
                best_name = name
                best_size = body_end - body_start
        return best_name

    def _handler_node(
        m: "re.Match[str]", method_name: str, owner: "str | None", inputs: list[dict[str, str]],
        return_type: "str | None", seen_methods: set[str],
    ) -> "tuple[IRNode, IREdge, IREdge | None] | None":
        owner_id = f"class.{owner}" if owner else file_id
        method_id = f"method.{owner}.{method_name}" if owner else f"method.{method_name}"
        if method_id in seen_methods:
            method_id = f"{method_id}_{content[:m.start()].count(chr(10)) + 1}"
        seen_methods.add(method_id)
        line_no = content[: m.start()].count("\n") + 1
        summary = _docblock_summary(content, m.start())

        attrs: dict[str, str] = {}
        if return_type is not None:
            attrs["return_type"] = return_type
        handler_type = ""
        for annot, htype in _AXON_HANDLER_ANNOTATIONS.items():
            if annot in _axon_annotations(m.group(0), import_map, wildcard_packages):
                handler_type = htype
                break
        handles_payload = ""
        if handler_type:
            attrs["handler_type"] = handler_type
            if inputs:
                handles_payload = inputs[0]["type"]
                attrs["handles_payload"] = handles_payload

        node = IRNode(
            id=method_id, type=IRNodeType.PROCEDURE, name=method_name,
            source_location=f"{file_path}:{line_no}",
            attributes=attrs, summary=summary, inputs=inputs,
        )
        defines_edge = IREdge(source_id=owner_id, target_id=method_id, type=IREdgeType.DEFINES)
        ref_edge = (
            IREdge(source_id=method_id, target_id=f"class.{handles_payload}", type=IREdgeType.REFERENCES)
            if handles_payload else None
        )
        return node, defines_edge, ref_edge

    seen_methods: set[str] = set()
    # _JAVA_METHOD_RE and _JAVA_PKG_METHOD_RE must be merged and re-sorted by
    # source position, not iterated as two fully-sequential passes — two
    # same-named overloads (e.g. Axon's @EventSourcingHandler convention of
    # naming every handler "on") can be split across the two patterns if one
    # overload has an access modifier and another doesn't (a real, plausible
    # inconsistency in customer code). Processing all of one pattern's matches
    # before any of the other's would let a later-in-file, modifier-bearing
    # overload claim the unsuffixed method_id ahead of an earlier-in-file
    # package-private one, pushing the real handler onto an unpredictable
    # suffixed id (Samuel Mbah, PR #27).
    _method_matches = sorted(
        (*_JAVA_METHOD_RE.finditer(content), *_JAVA_PKG_METHOD_RE.finditer(content)),
        key=lambda m: m.start(),
    )
    for m in _method_matches:
        method_name = m.group(2)
        if method_name in {"if", "while", "for", "switch", "catch", "return", "new"}:
            continue
        owner = _owner_class(m.start())
        inputs = _java_param_list(m.group(3))
        result = _handler_node(m, method_name, owner, inputs, m.group(1).strip(), seen_methods)
        if result is None:
            continue
        node, defines_edge, ref_edge = result
        nodes.append(node)
        edges.append(defines_edge)
        if ref_edge:
            edges.append(ref_edge)

    # Constructors — same declaration shape as a method but with no return type, so
    # _JAVA_METHOD_RE (which requires one) never matches them. Matched separately and
    # filtered to only fire when the declared name equals the enclosing class name.
    for m in _JAVA_CTOR_RE.finditer(content):
        ctor_name = m.group(1)
        if ctor_name in {"if", "while", "for", "switch", "catch", "return", "new"}:
            continue
        owner = _owner_class(m.start())
        if ctor_name != owner:
            continue
        inputs = _java_param_list(m.group(2))
        result = _handler_node(m, ctor_name, owner, inputs, None, seen_methods)
        if result is None:
            continue
        node, defines_edge, ref_edge = result
        nodes.append(node)
        edges.append(defines_edge)
        if ref_edge:
            edges.append(ref_edge)

    seen_fields: set[str] = set()
    for m in _JAVA_FIELD_RE.finditer(content):
        field_name = m.group(2)
        if field_name in {"return", "new", "throw", "if", "else", "true", "false", "null"}:
            continue
        owner = _owner_class(m.start())
        owner_id = f"class.{owner}" if owner else file_id
        field_id = f"field.{owner}.{field_name}" if owner else f"field.{field_name}"
        if field_id in seen_fields:
            continue
        seen_fields.add(field_id)
        line_no = content[: m.start()].count("\n") + 1
        field_attrs: dict[str, str] = {"type": m.group(1).strip(), "class": owner or ""}
        if "AggregateIdentifier" in _axon_annotations(m.group(0), import_map, wildcard_packages):
            field_attrs["is_aggregate_identifier"] = "true"
        nodes.append(IRNode(
            id=field_id, type=IRNodeType.DATA_ITEM, name=field_name,
            source_location=f"{file_path}:{line_no}",
            attributes=field_attrs,
        ))
        edges.append(IREdge(source_id=owner_id, target_id=field_id, type=IREdgeType.DEFINES))

    return nodes, edges


def _parse_csharp_file(
    file_path: str, content: str, file_id: str
) -> "tuple[list[IRNode], list[IREdge]]":
    """Extract namespace, classes, interfaces, structs, methods, and properties from C#."""
    nodes: list[IRNode] = []
    edges: list[IREdge] = []

    ns_m = re.search(r"^\s*namespace\s+([\w.]+)", content, re.MULTILINE)
    namespace = ns_m.group(1) if ns_m else ""

    cls_re = re.compile(
        r"^\s*(?:(?:public|internal|protected|private|static|abstract|sealed|partial)\s+)+"
        r"(class|interface|struct|enum|record)\s+(\w+)"
        r"(?:\s*:\s*([\w,\s<>]+))?",
        re.MULTILINE,
    )
    # Allman-style braces: closing ) may be followed by newline then {
    # so we require only visibility + return-type + name + ( — brace is optional
    method_re = re.compile(
        r"^\s*(?:(?:public|private|protected|internal|static|virtual|override|abstract"
        r"|async|sealed|new)\s+)+"
        r"(?:[\w<>\[\]?.]+\s+)(\w+)\s*\([^)]*\)\s*(?:\{|;|=>|$)",
        re.MULTILINE,
    )
    prop_re = re.compile(
        r"^\s*(?:(?:public|private|protected|internal|static|virtual|override|abstract)\s+)+"
        r"([\w<>\[\]?]+)\s+(\w+)\s*\{[^}]*(?:get|set)",
        re.MULTILINE,
    )
    attr_re = re.compile(r"^\s*\[(\w+)(?:\([^)]*\))?\]")

    _SKIP_KW = frozenset({"if", "while", "for", "foreach", "switch", "catch", "using", "lock",
                          "return", "new", "throw", "typeof", "nameof", "sizeof"})

    lines = content.splitlines()
    current_annotations: list[str] = []
    current_class_name: "str | None" = None
    current_class_id: "str | None" = None

    # Build a map from line number → class name so method finditer can resolve ownership
    class_at_line: list[tuple[int, str, str]] = []  # (lineno, class_name, class_id)

    for lineno, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped:
            continue

        attr_m = attr_re.match(stripped)
        if attr_m:
            current_annotations.append(attr_m.group(1))
            continue

        cls_m = cls_re.match(line)
        if cls_m:
            kind, cls_name = cls_m.group(1), cls_m.group(2)
            current_class_name = cls_name
            current_class_id = f"class.{cls_name}"
            attrs: dict[str, str] = {
                "kind": kind,
                "namespace": namespace,
                "annotations": ",".join(current_annotations),
            }
            if cls_m.group(3):
                bases = [b.strip() for b in cls_m.group(3).split(",") if b.strip()]
                attrs["extends"] = bases[0]
                if len(bases) > 1:
                    attrs["implements"] = ", ".join(bases[1:])
            nodes.append(IRNode(
                id=current_class_id, type=IRNodeType.DATA_STRUCTURE, name=cls_name,
                source_location=f"{file_path}:{lineno}", attributes=attrs,
            ))
            edges.append(IREdge(source_id=file_id, target_id=current_class_id, type=IREdgeType.DEFINES))
            class_at_line.append((lineno, cls_name, current_class_id))
            current_annotations = []
            continue

        prop_m = prop_re.match(line)
        if prop_m:
            prop_type, prop_name = prop_m.group(1), prop_m.group(2)
            owner_id = current_class_id or file_id
            prop_id = (
                f"field.{current_class_name}.{prop_name}"
                if current_class_name else f"field.{prop_name}"
            )
            nodes.append(IRNode(
                id=prop_id, type=IRNodeType.DATA_ITEM, name=prop_name,
                source_location=f"{file_path}:{lineno}",
                attributes={"class": current_class_name or "", "type": prop_type},
            ))
            edges.append(IREdge(source_id=owner_id, target_id=prop_id, type=IREdgeType.DEFINES))
            current_annotations = []
            continue

        if not stripped.startswith("["):
            current_annotations = []

    # Second pass: find all methods across full content using finditer (handles Allman braces)
    for m in method_re.finditer(content):
        meth_name = m.group(1)
        if meth_name in _SKIP_KW:
            continue
        lineno = content[: m.start()].count("\n") + 1
        line_txt = lines[lineno - 1] if lineno <= len(lines) else ""
        # Resolve owning class by most recent class declaration before this line
        owner_cls_name: "str | None" = None
        owner_cls_id: "str | None" = None
        for cls_lineno, cls_name, cls_id in reversed(class_at_line):
            if cls_lineno <= lineno:
                owner_cls_name = cls_name
                owner_cls_id = cls_id
                break
        owner_id = owner_cls_id or file_id
        method_id = (
            f"method.{owner_cls_name}.{meth_name}"
            if owner_cls_name else f"method.{meth_name}"
        )
        visibility = "private"
        for v in ("public", "protected", "internal"):
            if v in line_txt:
                visibility = v
                break
        is_static = "static" in line_txt.split(meth_name)[0] if meth_name in line_txt else False
        nodes.append(IRNode(
            id=method_id, type=IRNodeType.PROCEDURE, name=meth_name,
            source_location=f"{file_path}:{lineno}",
            attributes={
                "class": owner_cls_name or "",
                "visibility": visibility,
                "is_static": str(is_static).lower(),
                "namespace": namespace,
            },
        ))
        edges.append(IREdge(source_id=owner_id, target_id=method_id, type=IREdgeType.DEFINES))

    seen: set[tuple] = set()
    unique: list[IREdge] = []
    for e in edges:
        key = (e.source_id, e.target_id, e.type)
        if key not in seen:
            seen.add(key)
            unique.append(e)
    return nodes, unique


def _parse_cobol_file(file_path: str, content: str, file_id: str):
    """Extract paragraphs (PROCEDURE), 01-level records (DATA_STRUCTURE),
    and PIC-bearing elementary items (DATA_ITEM) from a COBOL/copybook file.

    COBOL fixed-format layout:
      Col 7  (index 6): indicator — '*' or '/' = comment line
      Col 8+ (index 7): Area A — divisions, sections, 01-level, paragraphs
      Col 12+ (index 11): Area B — statements, subordinate data items

    COPY statements are expanded inline: the copybook's data definitions are
    parsed as if they belong to the including program, giving each program its
    full working-storage picture without creating a false hub node.
    """
    nodes: list = []
    edges: list = []

    file_stem = file_id.replace("prog.", "")  # e.g. "Fdrules"

    # Inline-expand COPY statements so copybook data items appear on each program
    copy_re = re.compile(r"^\s{6,8}COPY\s+([A-Za-z][A-Za-z0-9_\-]+)", re.IGNORECASE)
    expanded_lines: list[str] = []
    for raw in content.splitlines():
        cm = copy_re.match(raw)
        if cm:
            copybook_name = cm.group(1).upper()
            copybook_path = Path(file_path).parent / f"{copybook_name}.cpy"
            if copybook_path.exists():
                try:
                    expanded_lines.extend(copybook_path.read_text(encoding="utf-8", errors="replace").splitlines())
                except OSError:
                    pass
        else:
            expanded_lines.append(raw)
    content = "\n".join(expanded_lines)

    def is_comment(line: str) -> bool:
        return len(line) > 6 and line[6] in ("*", "/")

    # Patterns anchored to COBOL Area A (columns 8-11, i.e. 7+ leading chars)
    level01_re = re.compile(r"^\s{6,8}01\s+([\w][\w-]*)", re.IGNORECASE)
    # Subordinate items: levels 02-49 that carry a PIC clause
    level_item_re = re.compile(
        r"^\s{9,}(0[2-9]|[1-9][0-9])\s+([\w][\w-]*)\s+PIC\s", re.IGNORECASE
    )
    # Paragraph names: Area A, ALL-CAPS identifier ending with dot, nothing else on line
    para_re = re.compile(r"^\s{6,8}([A-Z][A-Z0-9-]{2,})\.\s*$")

    # Keyword tokens that look like paragraphs but are division/section headers
    _DIVISION_KEYWORDS = {
        "IDENTIFICATION", "ENVIRONMENT", "DATA", "PROCEDURE",
        "WORKING-STORAGE", "FILE", "LINKAGE", "INPUT-OUTPUT",
        "CONFIGURATION", "SPECIAL-NAMES",
    }
    # COBOL reserved words that follow PERFORM but are not paragraph names
    _PERFORM_KEYWORDS = {
        "UNTIL", "VARYING", "WITH", "TEST", "BEFORE", "AFTER",
        "TIMES", "THRU", "THROUGH", "INLINE", "END-PERFORM",
    }

    # Patterns for inter-program calls
    call_re = re.compile(r"\bCALL\s+['\"]([A-Za-z][A-Za-z0-9_-]+)['\"]", re.IGNORECASE)
    # Single-line form: EXEC CICS LINK PROGRAM('PROG') ...
    cics_link_re = re.compile(
        r"EXEC\s+CICS\s+(?:LINK|XCTL)\s+PROGRAM\s*\(\s*['\"]?([A-Za-z][A-Za-z0-9_-]+)['\"]?\s*\)",
        re.IGNORECASE,
    )
    # Multi-line form: EXEC CICS LINK on one line, PROGRAM(...) on a subsequent line
    cics_start_re = re.compile(r"EXEC\s+CICS\s+(?:LINK|XCTL)\b", re.IGNORECASE)
    cics_prog_re = re.compile(r"\bPROGRAM\s*\(\s*['\"]?([A-Za-z][A-Za-z0-9_-]+)['\"]?\s*\)", re.IGNORECASE)
    # Intra-program PERFORM: PERFORM paragraph-name [THRU para2] [...]
    perform_re = re.compile(r"\bPERFORM\s+([A-Z][A-Z0-9-]+)", re.IGNORECASE)

    in_data = False      # inside WORKING-STORAGE / FILE / LINKAGE section
    in_proc = False      # inside PROCEDURE DIVISION
    current_ds_id: str | None = None
    current_para_id: str | None = None
    _in_cics_link = False  # multi-line CICS LINK/XCTL continuation

    # ── Pass 1: collect paragraph names so PERFORM edges only target real paras ─
    known_paras: set[str] = set()
    _in_proc_scan = False
    for line in content.splitlines():
        if is_comment(line):
            continue
        upper = line.upper().strip()
        if "PROCEDURE DIVISION" in upper:
            _in_proc_scan = True
            continue
        if _in_proc_scan:
            mp = para_re.match(line)
            if mp and mp.group(1) not in _DIVISION_KEYWORDS:
                known_paras.add(mp.group(1).upper())

    for line in content.splitlines():
        if is_comment(line):
            continue
        upper = line.upper().strip()

        # --- Division / section transitions ---
        if "PROCEDURE DIVISION" in upper:
            in_data = False
            in_proc = True
            current_ds_id = None
            # Many real COBOL programs run mainline logic (including PERFORMs)
            # directly under PROCEDURE DIVISION, before any named paragraph
            # header — a standalone "mainline" body is not itself a paragraph,
            # so `current_para_id` would otherwise stay None until the first
            # real paragraph header, silently dropping every PERFORM issued
            # before it (no source node to attribute the CALLS edge to).
            # Synthesize a PROCEDURE node for this mainline so those calls are
            # captured too. Overwritten below the moment a real paragraph
            # header is seen, same as any other paragraph transition.
            mainline_id = f"proc.{file_stem}.mainline"
            nodes.append(IRNode(
                id=mainline_id, type=IRNodeType.PROCEDURE,
                name="MAINLINE", source_location=file_path,
            ))
            edges.append(IREdge(
                source_id=file_id, target_id=mainline_id,
                type=IREdgeType.DEFINES,
            ))
            current_para_id = mainline_id
            continue
        if re.search(
            r"WORKING-STORAGE\s+SECTION|FILE\s+SECTION|LINKAGE\s+SECTION",
            upper,
        ):
            in_data = True
            in_proc = False
            continue
        if re.search(
            r"\bIDENTIFICATION\s+DIVISION|\bENVIRONMENT\s+DIVISION|\bDATA\s+DIVISION",
            upper,
        ):
            continue

        # --- Data section ---
        if in_data:
            m01 = level01_re.match(line)
            if m01:
                name = m01.group(1).upper()
                if name not in ("DFHCOMMAREA", "FILLER"):
                    ds_id = f"ds.{file_stem}.{name.lower()}"
                    nodes.append(IRNode(
                        id=ds_id, type=IRNodeType.DATA_STRUCTURE,
                        name=name, source_location=file_path,
                    ))
                    edges.append(IREdge(
                        source_id=file_id, target_id=ds_id,
                        type=IREdgeType.DEFINES,
                    ))
                    current_ds_id = ds_id
                else:
                    current_ds_id = None
                continue

            mi = level_item_re.match(line)
            if mi and current_ds_id:
                name = mi.group(2).upper()
                if name != "FILLER":
                    item_id = f"di.{file_stem}.{name.lower()}"
                    nodes.append(IRNode(
                        id=item_id, type=IRNodeType.DATA_ITEM,
                        name=name, source_location=file_path,
                    ))
                    edges.append(IREdge(
                        source_id=current_ds_id, target_id=item_id,
                        type=IREdgeType.DEFINES,
                    ))

        # --- Procedure section ---
        if in_proc:
            mp = para_re.match(line)
            if mp:
                name = mp.group(1)
                if name not in _DIVISION_KEYWORDS:
                    proc_id = f"proc.{file_stem}.{name.lower()}"
                    nodes.append(IRNode(
                        id=proc_id, type=IRNodeType.PROCEDURE,
                        name=name, source_location=file_path,
                    ))
                    edges.append(IREdge(
                        source_id=file_id, target_id=proc_id,
                        type=IREdgeType.DEFINES,
                    ))
                    current_para_id = proc_id

            # PERFORM para-name → intra-program CALLS edge (only to known paragraphs)
            if current_para_id:
                for pm in perform_re.finditer(upper):
                    called = pm.group(1).upper()
                    if called in known_paras and called not in _PERFORM_KEYWORDS:
                        edges.append(IREdge(
                            source_id=current_para_id,
                            target_id=f"proc.{file_stem}.{called.lower()}",
                            type=IREdgeType.CALLS,
                        ))

            # CALL 'PROGNAME' → inter-program CALLS edge
            for cm in call_re.finditer(upper):
                called_prog = cm.group(1).upper()
                edges.append(IREdge(
                    source_id=file_id,
                    target_id=f"prog.{called_prog}",
                    type=IREdgeType.CALLS,
                ))

            # EXEC CICS LINK/XCTL → inter-program CALLS edge (single-line form)
            for clm in cics_link_re.finditer(upper):
                called_prog = clm.group(1).upper()
                edges.append(IREdge(
                    source_id=file_id,
                    target_id=f"prog.{called_prog}",
                    type=IREdgeType.CALLS,
                ))

            # Multi-line form: track state across lines
            if cics_start_re.search(upper):
                # Check if PROGRAM(...) is also on this same line (handled above); if not, arm state
                if not cics_link_re.search(upper):
                    _in_cics_link = True
            if _in_cics_link:
                pm2 = cics_prog_re.search(upper)
                if pm2:
                    _in_cics_link = False
                    called_prog = pm2.group(1).upper()
                    edges.append(IREdge(
                        source_id=file_id,
                        target_id=f"prog.{called_prog}",
                        type=IREdgeType.CALLS,
                    ))
                elif "END-EXEC" in upper:
                    _in_cics_link = False

    # Deduplicate edges
    seen: set[tuple] = set()
    unique: list = []
    for e in edges:
        key = (e.source_id, e.target_id, e.type)
        if key not in seen:
            seen.add(key)
            unique.append(e)
    return nodes, unique


def _parse_java_ts_file(
    file_path: str, content: str, file_id: str
) -> "tuple[list[IRNode], list[IREdge]]":
    """Tree-sitter deep parser for Java — same IR schema as _parse_java_file
    but AST-accurate with enriched attributes (fqcn, stereotype, annotations,
    HTTP endpoints, full method signatures)."""
    nodes: list[IRNode] = []
    edges: list[IREdge] = []

    src = content.encode("utf-8", errors="replace")
    parser = _TSParser(_JAVA_TS)
    root = parser.parse(src).root_node

    def _t(node) -> str:
        return src[node.start_byte:node.end_byte].decode("utf-8", errors="replace")

    def _walk(node, ntype: str):
        if node.type == ntype:
            yield node
        for child in node.children:
            yield from _walk(child, ntype)

    def _anns(node) -> list[str]:
        result = []
        for child in node.children:
            if child.type == "modifiers":
                for mod in child.children:
                    if mod.type in ("annotation", "marker_annotation"):
                        nn = mod.child_by_field_name("name")
                        if nn:
                            result.append(_t(nn))
        return result

    def _ann_arg(ann_node) -> str:
        args = ann_node.child_by_field_name("arguments")
        if not args:
            return ""
        for child in args.children:
            if child.type == "string_literal":
                return _t(child).strip('"\'')
            if child.type == "element_value_pair":
                for sub in child.children:
                    if sub.type == "string_literal":
                        return _t(sub).strip('"\'')
        return ""

    _HTTP = {
        "GetMapping": "GET", "PostMapping": "POST", "PutMapping": "PUT",
        "DeleteMapping": "DELETE", "PatchMapping": "PATCH", "RequestMapping": "ANY",
    }
    _STEREOS = {"Service", "Repository", "RestController", "Controller",
                "Component", "Configuration", "Entity"}

    # Package
    pkg = ""
    for pn in _walk(root, "package_declaration"):
        pkg = _t(pn).removeprefix("package ").rstrip(";").strip()

    # Class-level @RequestMapping paths
    cls_base_path: dict[str, str] = {}
    for node_type in ("class_declaration", "interface_declaration", "enum_declaration"):
        for cls in _walk(root, node_type):
            nn = cls.child_by_field_name("name")
            if not nn:
                continue
            cls_name = _t(nn)
            for child in cls.children:
                if child.type == "modifiers":
                    for mod in child.children:
                        if mod.type == "annotation":
                            an = mod.child_by_field_name("name")
                            if an and _t(an) == "RequestMapping":
                                cls_base_path[cls_name] = _ann_arg(mod)

    for node_type in ("class_declaration", "interface_declaration", "enum_declaration"):
        for cls in _walk(root, node_type):
            nn = cls.child_by_field_name("name")
            if not nn:
                continue
            cls_name = _t(nn)
            cls_id   = f"class.{cls_name}"
            line     = cls.start_point[0] + 1
            anns     = _anns(cls)
            stereo   = next((a for a in anns if a in _STEREOS), "—")
            kind     = node_type.replace("_declaration", "")
            fqcn     = f"{pkg}.{cls_name}" if pkg else cls_name

            ext_n = cls.child_by_field_name("superclass")
            impl_n = cls.child_by_field_name("interfaces")

            attrs: dict[str, str] = {
                "kind":        kind,
                "package":     pkg,
                "fqcn":        fqcn,
                "stereotype":  stereo,
                "annotations": ", ".join(anns),
                "line":        str(line),
            }
            if ext_n:
                attrs["extends"] = _t(ext_n).removeprefix("extends").strip()
            if impl_n:
                attrs["implements"] = _t(impl_n).removeprefix("implements").strip()

            nodes.append(IRNode(
                id=cls_id, type=IRNodeType.DATA_STRUCTURE, name=cls_name,
                source_location=f"{file_path}:{line}", attributes=attrs,
            ))
            edges.append(IREdge(source_id=file_id, target_id=cls_id, type=IREdgeType.DEFINES))

            # Methods
            seen_methods: set[str] = set()
            for method in _walk(cls, "method_declaration"):
                mn = method.child_by_field_name("name")
                if not mn:
                    continue
                mname       = _t(mn)
                mtype_n     = method.child_by_field_name("type")
                return_type = _t(mtype_n).strip() if mtype_n else "void"
                m_line      = method.start_point[0] + 1
                m_anns      = _anns(method)

                params: list[dict[str, str]] = []
                mparams = method.child_by_field_name("parameters")
                if mparams:
                    for param in mparams.children:
                        if param.type == "formal_parameter":
                            pt = param.child_by_field_name("type")
                            pn2 = param.child_by_field_name("name")
                            if pt and pn2:
                                params.append({"name": _t(pn2), "type": _t(pt).strip()})

                method_id = f"method.{cls_name}.{mname}"
                if method_id in seen_methods:
                    method_id = f"{method_id}@L{m_line}"
                seen_methods.add(method_id)

                m_attrs: dict[str, str] = {
                    "return_type": return_type,
                    "annotations": ", ".join(m_anns),
                    "line":        str(m_line),
                }
                # HTTP endpoint enrichment
                for ann in m_anns:
                    if ann in _HTTP:
                        verb = _HTTP[ann]
                        path = ""
                        for child in method.children:
                            if child.type == "modifiers":
                                for mod in child.children:
                                    if mod.type == "annotation":
                                        an2 = mod.child_by_field_name("name")
                                        if an2 and _t(an2) == ann:
                                            path = _ann_arg(mod)
                        base = cls_base_path.get(cls_name, "")
                        if base and path:
                            path = base.rstrip("/") + "/" + path.lstrip("/")
                        elif base:
                            path = base
                        m_attrs["http_verb"] = verb
                        m_attrs["http_path"] = path
                        break

                nodes.append(IRNode(
                    id=method_id, type=IRNodeType.PROCEDURE, name=mname,
                    source_location=f"{file_path}:{m_line}",
                    attributes=m_attrs, inputs=params, output=return_type,
                ))
                edges.append(IREdge(source_id=cls_id, target_id=method_id, type=IREdgeType.DEFINES))

            # Fields
            seen_fields: set[str] = set()
            body = cls.child_by_field_name("body")
            if body:
                for field in body.children:
                    if field.type != "field_declaration":
                        continue
                    ftype_n = field.child_by_field_name("type")
                    ftype = _t(ftype_n).strip() if ftype_n else ""
                    f_anns = _anns(field)
                    f_line = field.start_point[0] + 1
                    for decl in _walk(field, "variable_declarator"):
                        fname_n = decl.child_by_field_name("name")
                        if not fname_n:
                            continue
                        fname = _t(fname_n)
                        if fname in seen_fields:
                            continue
                        seen_fields.add(fname)
                        field_id = f"field.{cls_name}.{fname}"
                        nodes.append(IRNode(
                            id=field_id, type=IRNodeType.DATA_ITEM, name=fname,
                            source_location=f"{file_path}:{f_line}",
                            attributes={
                                "type":        ftype,
                                "annotations": ", ".join(f_anns),
                                "line":        str(f_line),
                            },
                        ))
                        edges.append(IREdge(source_id=cls_id, target_id=field_id, type=IREdgeType.DEFINES))

    return nodes, edges


def _parse_c_ts_file(
    file_path: str, content: str, file_id: str
) -> "tuple[list[IRNode], list[IREdge]]":
    """Tree-sitter deep parser for C.

    C has no classes, so unlike the Java/C# parsers this maps flatly onto
    the same DATA_STRUCTURE/PROCEDURE vocabulary COBOL's own procedural
    parser uses: each real struct definition (a struct_specifier that
    actually has a field_declaration_list — a bare "struct Foo *x" type
    reference does not) becomes a DATA_STRUCTURE node, and every top-level
    function definition becomes a PROCEDURE node, both hung directly off
    the file rather than off a containing class.

    Also extracts real intra-file CALLS edges between functions (Java's own
    tree-sitter parser above does not do this — it only builds DEFINES
    structure, leaving cross-method call graph entirely to the separate,
    file-level _extract_calls_* mechanism). C's flat, non-overloaded
    function namespace makes resolving "which function does this call
    target" trivial by name — no `this.field.method()` receiver resolution
    or overload disambiguation needed — so there is no good reason to skip
    it here, and seam/hotspot detection depends on a real call graph to be
    meaningful at all.
    """
    nodes: list[IRNode] = []
    edges: list[IREdge] = []

    src = content.encode("utf-8", errors="replace")
    parser = _TSParser(_C_TS)
    root = parser.parse(src).root_node

    def _t(node) -> str:
        return src[node.start_byte:node.end_byte].decode("utf-8", errors="replace")

    def _walk(node, ntype: str):
        if node.type == ntype:
            yield node
        for child in node.children:
            yield from _walk(child, ntype)

    def _declarator_name(node) -> str:
        """Unwrap pointer_declarator/array_declarator wrappers to the
        innermost identifier/field_identifier — e.g. "*acct" or "id[10]"
        both need to resolve to just "acct"/"id"."""
        while node is not None and node.type not in ("identifier", "field_identifier"):
            inner = node.child_by_field_name("declarator")
            if inner is None:
                return ""
            node = inner
        return _t(node) if node is not None else ""

    # ── structs (only real definitions — a struct_specifier used purely as
    #    a type reference, e.g. a parameter's "struct Account *acct", has
    #    no field_declaration_list and must not be treated as a definition) ──
    for st in _walk(root, "struct_specifier"):
        body = st.child_by_field_name("body")
        if body is None:
            continue
        name_n = st.child_by_field_name("name")
        struct_name = _t(name_n) if name_n else ""
        if not struct_name:
            continue
        struct_id = f"struct.{struct_name}"
        line = st.start_point[0] + 1
        nodes.append(IRNode(
            id=struct_id, type=IRNodeType.DATA_STRUCTURE, name=struct_name,
            source_location=f"{file_path}:{line}",
            attributes={"kind": "struct", "line": str(line)},
        ))
        edges.append(IREdge(source_id=file_id, target_id=struct_id, type=IREdgeType.DEFINES))

        for field in body.children:
            if field.type != "field_declaration":
                continue
            type_n = field.child_by_field_name("type")
            ftype = _t(type_n).strip() if type_n else ""
            decl_n = field.child_by_field_name("declarator")
            fname = _declarator_name(decl_n) if decl_n else ""
            if not fname:
                continue
            f_line = field.start_point[0] + 1
            field_id = f"field.{struct_name}.{fname}"
            nodes.append(IRNode(
                id=field_id, type=IRNodeType.DATA_ITEM, name=fname,
                source_location=f"{file_path}:{f_line}",
                attributes={"type": ftype, "line": str(f_line)},
            ))
            edges.append(IREdge(source_id=struct_id, target_id=field_id, type=IREdgeType.DEFINES))

    # ── top-level functions ──────────────────────────────────────────────
    seen_fns: set[str] = set()
    for fn in _walk(root, "function_definition"):
        declarator = fn.child_by_field_name("declarator")
        # A pointer-returning function ("char *get_name(...)") wraps the
        # real function_declarator inside a pointer_declarator — find it
        # rather than assuming it's the direct child.
        fdecl = declarator
        while fdecl is not None and fdecl.type != "function_declarator":
            fdecl = fdecl.child_by_field_name("declarator")
        if fdecl is None:
            continue
        name_n = fdecl.child_by_field_name("declarator")
        fn_name = _declarator_name(name_n) if name_n else ""
        if not fn_name:
            continue

        fn_id = f"fn.{fn_name}"
        if fn_id in seen_fns:
            fn_id = f"{fn_id}@L{fn.start_point[0] + 1}"
        seen_fns.add(fn_id)

        type_n = fn.child_by_field_name("type")
        return_type = _t(type_n).strip() if type_n else "int"
        storage = ""
        for child in fn.children:
            if child.type == "storage_class_specifier":
                storage = _t(child).strip()
                break
        line = fn.start_point[0] + 1

        params: list[dict[str, str]] = []
        plist = fdecl.child_by_field_name("parameters")
        if plist is not None:
            for pd in plist.children:
                if pd.type != "parameter_declaration":
                    continue
                pt_n = pd.child_by_field_name("type")
                ptype = _t(pt_n).strip() if pt_n else ""
                pd_n = pd.child_by_field_name("declarator")
                pname = _declarator_name(pd_n) if pd_n else ""
                if ptype == "void" and not pname:
                    continue  # the "(void)" no-args idiom, not a real parameter
                params.append({"name": pname, "type": ptype})

        nodes.append(IRNode(
            id=fn_id, type=IRNodeType.PROCEDURE, name=fn_name,
            source_location=f"{file_path}:{line}",
            attributes={"storage": storage, "line": str(line)},
            inputs=params, output=return_type,
        ))
        edges.append(IREdge(source_id=file_id, target_id=fn_id, type=IREdgeType.DEFINES))

        # Real intra-file call graph — only simple "identifier(...)" calls
        # are resolved (a function pointer or macro-expanded call target
        # isn't a plain identifier and is skipped rather than guessed at).
        body = fn.child_by_field_name("body")
        if body is None:
            continue
        seen_callees: set[str] = set()
        for call in _walk(body, "call_expression"):
            callee_n = call.child_by_field_name("function")
            if callee_n is None or callee_n.type != "identifier":
                continue
            callee = _t(callee_n)
            if callee and callee not in seen_callees:
                seen_callees.add(callee)
                edges.append(IREdge(source_id=fn_id, target_id=f"fn.{callee}", type=IREdgeType.CALLS))

    return nodes, edges


def _parse_csharp_ts_file(
    file_path: str, content: str, file_id: str
) -> "tuple[list[IRNode], list[IREdge]]":
    """Parse a C# file with Tree-sitter, producing enriched .NET IR nodes and edges.

    Extracts namespace, classes/interfaces/structs/records with ASP.NET stereotypes,
    methods with HTTP endpoint metadata, and fields/properties with type annotations.
    """
    nodes: list[IRNode] = []
    edges: list[IREdge] = []
    src = content.encode("utf-8", errors="replace")
    parser = _TSParser(_CS_TS)
    root = parser.parse(src).root_node

    def _txt(node) -> str:
        return src[node.start_byte:node.end_byte].decode("utf-8", errors="replace")

    def _walk(node, *types):
        if node.type in types:
            yield node
        for child in node.children:
            yield from _walk(child, *types)

    # Namespace — supports both block (C# ≤9) and file-scoped (C# 10+)
    namespace = ""
    for ns in _walk(root, "namespace_declaration", "file_scoped_namespace_declaration"):
        name_node = ns.child_by_field_name("name")
        if name_node:
            namespace = _txt(name_node)
            break

    # Extract attribute names from a node's attribute_list children
    def _anns_from(node) -> list[str]:
        anns: list[str] = []
        for child in node.children:
            if child.type == "attribute_list":
                for att in child.children:
                    if att.type == "attribute":
                        n = att.child_by_field_name("name") or next(
                            (c for c in att.children if c.type == "identifier"), None
                        )
                        if n:
                            anns.append(_txt(n))
        return anns

    # First string-literal argument from an attribute node
    def _ann_arg(att_node) -> str:
        for child in att_node.children:
            if child.type == "attribute_argument_list":
                for arg in child.children:
                    if arg.type == "attribute_argument":
                        for v in arg.children:
                            if v.type == "string_literal":
                                for part in v.children:
                                    if part.type == "string_literal_content":
                                        return _txt(part)
        return ""

    _NET_HTTP = {
        "HttpGet": "GET", "HttpPost": "POST", "HttpPut": "PUT",
        "HttpDelete": "DELETE", "HttpPatch": "PATCH", "Route": "ANY",
    }
    _NET_STEREOTYPES = {"ApiController", "Controller", "ServiceFilter", "ApiControllerBase"}

    def _stereotype(anns: list[str]) -> str:
        for a in anns:
            if a in _NET_STEREOTYPES:
                return a
        return "—"

    _TYPE_DECLS = (
        "class_declaration", "interface_declaration", "struct_declaration",
        "enum_declaration", "record_declaration", "record_struct_declaration",
    )

    cls_route_map: dict[str, str] = {}

    for type_node in _walk(root, *_TYPE_DECLS):
        name_node = type_node.child_by_field_name("name")
        if not name_node:
            continue

        cls_name = _txt(name_node)
        cls_id = f"class.{cls_name}"
        line = type_node.start_point[0] + 1
        anns = _anns_from(type_node)
        ann_str = ", ".join(anns)
        stereo = _stereotype(anns)
        kind = type_node.type.replace("_declaration", "")
        fqcn = f"{namespace}.{cls_name}" if namespace else cls_name

        # Base class / interfaces — fall back to searching for base_list child
        base_list = type_node.child_by_field_name("bases") or next(
            (c for c in type_node.children if c.type == "base_list"), None
        )
        extends, implements = "", ""
        if base_list:
            parts = [b.strip() for b in _txt(base_list).lstrip(":").strip().split(",") if b.strip()]
            if parts:
                extends = parts[0]
                implements = ", ".join(parts[1:])

        attrs: dict[str, str] = {
            "kind": kind, "namespace": namespace, "fqcn": fqcn,
            "stereotype": stereo, "annotations": ann_str, "line": str(line),
        }
        if extends:
            attrs["extends"] = extends
        if implements:
            attrs["implements"] = implements

        nodes.append(IRNode(
            id=cls_id, type=IRNodeType.DATA_STRUCTURE, name=cls_name,
            source_location=f"{file_path}:{line}", attributes=attrs,
        ))
        edges.append(IREdge(source_id=file_id, target_id=cls_id, type=IREdgeType.DEFINES))

        # Store class-level [Route("...")] for method path prefix
        for child in type_node.children:
            if child.type == "attribute_list":
                for att in child.children:
                    if att.type == "attribute":
                        n = next((c for c in att.children if c.type == "identifier"), None)
                        if n and _txt(n) == "Route":
                            cls_route_map[cls_name] = _ann_arg(att)

        body = type_node.child_by_field_name("body")
        if not body:
            continue

        # Methods
        seen_methods: set[str] = set()
        for method in _walk(body, "method_declaration"):
            mname_node = method.child_by_field_name("name")
            mtype_node = method.child_by_field_name("type")
            if not mname_node:
                continue
            mname = _txt(mname_node)
            m_line = method.start_point[0] + 1
            return_type = _txt(mtype_node).strip() if mtype_node else "void"
            m_anns = _anns_from(method)
            m_ann_str = ", ".join(m_anns)

            params: list[dict] = []
            params_node = method.child_by_field_name("parameters")
            if params_node:
                for param in params_node.children:
                    if param.type == "parameter":
                        pt = param.child_by_field_name("type")
                        pn = param.child_by_field_name("name")
                        if pt and pn:
                            params.append({"name": _txt(pn), "type": _txt(pt).strip()})

            method_id = f"method.{cls_name}.{mname}"
            if method_id in seen_methods:
                method_id = f"{method_id}@L{m_line}"
            seen_methods.add(method_id)

            # HTTP endpoint detection via [HttpGet/Post/...("path")]
            http_verb = http_path = ""
            for ann in m_anns:
                if ann in _NET_HTTP:
                    http_verb = _NET_HTTP[ann]
                    for child in method.children:
                        if child.type == "attribute_list":
                            for att in child.children:
                                if att.type == "attribute":
                                    an = next((c for c in att.children if c.type == "identifier"), None)
                                    if an and _txt(an) == ann:
                                        http_path = _ann_arg(att)
                    base = cls_route_map.get(cls_name, "")
                    if base and http_path:
                        http_path = base.rstrip("/") + "/" + http_path.lstrip("/")
                    elif base:
                        http_path = base
                    break

            m_attrs: dict[str, str] = {
                "return_type": return_type, "annotations": m_ann_str, "line": str(m_line),
            }
            if http_verb:
                m_attrs["http_verb"] = http_verb
                m_attrs["http_path"] = http_path

            nodes.append(IRNode(
                id=method_id, type=IRNodeType.PROCEDURE, name=mname,
                source_location=f"{file_path}:{m_line}",
                attributes=m_attrs, inputs=params, output=return_type,
            ))
            edges.append(IREdge(source_id=cls_id, target_id=method_id, type=IREdgeType.DEFINES))

        # Fields and properties
        seen_fields: set[str] = set()
        for child in body.children:
            if child.type == "field_declaration":
                f_anns = _anns_from(child)
                f_line = child.start_point[0] + 1
                var_decl = child.child_by_field_name("declaration")
                if not var_decl:
                    continue
                ft_node = var_decl.child_by_field_name("type")
                f_type = _txt(ft_node).strip() if ft_node else ""
                for decl in var_decl.children:
                    if decl.type == "variable_declarator":
                        fn_node = decl.child_by_field_name("name")
                        if not fn_node:
                            continue
                        fname = _txt(fn_node)
                        if fname in seen_fields:
                            continue
                        seen_fields.add(fname)
                        nodes.append(IRNode(
                            id=f"field.{cls_name}.{fname}", type=IRNodeType.DATA_ITEM, name=fname,
                            source_location=f"{file_path}:{f_line}",
                            attributes={"type": f_type, "annotations": ", ".join(f_anns), "line": str(f_line)},
                        ))
                        edges.append(IREdge(
                            source_id=cls_id, target_id=f"field.{cls_name}.{fname}", type=IREdgeType.DEFINES
                        ))

            elif child.type == "property_declaration":
                p_anns = _anns_from(child)
                p_line = child.start_point[0] + 1
                pn_node = child.child_by_field_name("name")
                pt_node = child.child_by_field_name("type")
                if not pn_node:
                    continue
                pname = _txt(pn_node)
                if pname in seen_fields:
                    continue
                seen_fields.add(pname)
                p_type = _txt(pt_node).strip() if pt_node else ""
                nodes.append(IRNode(
                    id=f"prop.{cls_name}.{pname}", type=IRNodeType.DATA_ITEM, name=pname,
                    source_location=f"{file_path}:{p_line}",
                    attributes={"type": p_type, "annotations": ", ".join(p_anns), "line": str(p_line)},
                ))
                edges.append(IREdge(
                    source_id=cls_id, target_id=f"prop.{cls_name}.{pname}", type=IREdgeType.DEFINES
                ))

    # Deduplicate edges
    seen_e: set[tuple] = set()
    unique: list[IREdge] = []
    for e in edges:
        k = (e.source_id, e.target_id, e.type)
        if k not in seen_e:
            seen_e.add(k)
            unique.append(e)
    return nodes, unique


_DEEP_PARSERS: dict[str, object] = {
    "cobol": _parse_cobol_file,
    "php": _parse_php_file,
    "python": _parse_python_file,
    "python2": _parse_python_file,
    "python3": _parse_python_file,
    "pyspark": _parse_python_file,
    "javascript": _parse_typescript_file,
    "typescript": _parse_typescript_file,
    "java": _parse_java_ts_file if _TS_AVAILABLE else _parse_java_file,
    "java8": _parse_java_ts_file if _TS_AVAILABLE else _parse_java_file,
    "java11": _parse_java_ts_file if _TS_AVAILABLE else _parse_java_file,
    "java21": _parse_java_ts_file if _TS_AVAILABLE else _parse_java_file,
    "csharp": _parse_csharp_ts_file if _CS_TS_AVAILABLE else _parse_csharp_file,
}
if _C_TS_AVAILABLE:
    # No regex-based fallback parser exists for C (unlike Java/C#) — when
    # tree_sitter_c isn't installed, "c" is simply absent here and files
    # degrade to the same shallow per-file PROGRAM-node-only treatment any
    # other language without a registered deep parser already gets.
    _DEEP_PARSERS["c"] = _parse_c_ts_file
_DEEP_PARSERS["sqlx"] = _parse_sqlx_file


def _deep_parser_for(source_lang: str):
    lang = source_lang.lower()
    if lang in _DEEP_PARSERS:
        return _DEEP_PARSERS[lang]
    for key, fn in _DEEP_PARSERS.items():
        if lang.startswith(key) or key.startswith(lang):
            return fn
    return None


def _module_docstring(content: str, source_lang: str) -> str:
    """Extract the leading module-level doc comment from a source file."""
    if not content:
        return ""
    lang = source_lang.lower()
    lines = content.splitlines()

    # Python: module-level triple-quoted string
    if any(lang.startswith(l) for l in ("python",)):
        for i, line in enumerate(lines[:8]):
            s = line.strip()
            if s.startswith("#") or s.startswith("__") or not s:
                continue
            if s.startswith('"""') or s.startswith("'''"):
                delim = '"""' if '"""' in line else "'''"
                inner = s[len(delim):]
                if delim in inner:
                    return inner[:inner.index(delim)].strip()
                collected = [inner.strip()]
                for j in range(i + 1, min(i + 8, len(lines))):
                    if delim in lines[j]:
                        collected.append(lines[j][:lines[j].index(delim)].strip())
                        break
                    collected.append(lines[j].strip())
                return " ".join(t for t in collected if t)
            break

    # TypeScript / JavaScript / PHP: leading /** ... */ JSDoc
    if any(lang.startswith(l) for l in ("typescript", "javascript", "php")):
        m = re.search(r"/\*\*([\s\S]+?)\*/", content[:3000])
        if m:
            for ln in m.group(1).splitlines():
                text = re.sub(r"^\s*\*\s?", "", ln).strip()
                if text and not text.startswith("@"):
                    return text

    # Generic: leading single-line comments (// or #)
    comment_lines = []
    for line in lines[:12]:
        s = line.strip()
        if s.startswith("//"):
            t = s.lstrip("/").strip()
            if t:
                comment_lines.append(t)
        elif s.startswith("#") and not s.startswith("#!"):
            t = s.lstrip("#").strip()
            if t:
                comment_lines.append(t)
        elif comment_lines:
            break
    return " ".join(comment_lines[:3]) if comment_lines else ""


def _attach_scheduler_activities(source_path: str, nodes: list[IRNode], edges: list[IREdge]) -> None:
    """One node per ADF or job activity, linked to the notebook it runs.

    Activities that share a notebook stay distinct. ``dependsOn`` is an edge
    from the upstream activity to the downstream one, matching the pipeline
    order. A notebook's own imports are separate CALLS edges.
    """
    from micro_cosmos.tools.databricks_bundle_tools import task_context_label
    from micro_cosmos.tools.scheduler_tools import discover_task_graph

    tasks = discover_task_graph(source_path)["tasks"]
    if not tasks:
        return
    by_path: dict[str, str] = {}
    for node in nodes:
        if node.type != IRNodeType.PROGRAM:
            continue
        loc = node.source_location or ""
        file_part = loc.rsplit(":", 1)[0] if ":" in loc else loc
        if file_part:
            by_path[str(Path(file_part).resolve())] = node.id
    labels = {tk: task_context_label(tk) for tk in tasks}
    for tk, tdef in tasks.items():
        label = labels[tk]
        act_id = f"act.{label}"
        notebook_names = [Path(path).name for path in tdef["owns_files"]]
        nodes.append(IRNode(
            id=act_id,
            type=IRNodeType.PROGRAM,
            name=label,
            source_location="",
            attributes={
                "etl_activity": tk,
                "etl_job": str(tdef.get("job") or ""),
                "etl_kind": str(tdef.get("kind") or ""),
                "notebook": notebook_names[0] if notebook_names else "",
                "dependency_count": str(len(tdef.get("depends_on") or [])),
            },
            summary=f"Scheduler activity {tk} in {tdef.get('job') or 'pipeline'}",
        ))
        for path in tdef["owns_files"]:
            target = by_path.get(str(Path(path).resolve()))
            if target:
                edges.append(IREdge(source_id=act_id, target_id=target, type=IREdgeType.CALLS))
        for dep_tk in tdef.get("depends_on") or []:
            if dep_tk not in labels:
                continue
            edges.append(IREdge(
                source_id=f"act.{labels[dep_tk]}",
                target_id=act_id,
                type=IREdgeType.CALLS,
            ))


def parse_source_estate(source_path: str, source_lang: str) -> dict:
    """Symbolically parse the source estate and produce an IR."""
    root = Path(source_path)
    files = _source_files(root, source_lang)
    extractor = _call_extractor_for(source_lang)

    if not files:
        name = _stem_to_name(root.name) or "EntryPoint"
        nodes: list[IRNode] = [
            IRNode(
                id=f"prog.{name}",
                type=IRNodeType.PROGRAM,
                name=name,
                source_location="",
            )
        ]
        edges: list[IREdge] = []
    else:
        deep_parser = _deep_parser_for(source_lang)
        nodes: list[IRNode] = []
        edges: list[IREdge] = []

        # Single pass: read content, create PROGRAM nodes with docstrings
        for f in files:
            try:
                content = f.read_text(encoding="utf-8", errors="replace")
                _source_content_cache[str(f)] = content
            except OSError:
                content = ""
            line_count = content.count("\n") + 1 if content else 0
            # For languages that use PascalCase filenames (e.g. Java), preserve
            # the original stem as the display name rather than re-casing it.
            _lang_lower = source_lang.lower()
            display_name = (
                f.stem if any(_lang_lower.startswith(p) for p in ("java", "kotlin", "scala", "swift", "csharp", "cobol"))
                else _stem_to_name(f.stem)
            )
            sqlx_meta = _parse_sqlx_document(content) if f.suffix.lower() == ".sqlx" and content else None
            if sqlx_meta and sqlx_meta.get("name"):
                display_name = _stem_to_name(sqlx_meta["name"])
            # C headers commonly share a base name with their implementation
            # file (account.h / account.c) — without disambiguating them,
            # both resolve to the identical "prog.Account" id, silently
            # colliding into two separate PROGRAM nodes with the same id
            # (confirmed live: real DEFINES/CALLS edges then become
            # ambiguous about which file they actually belong to).
            _file_suffix = "_h" if f.suffix.lower() == ".h" else ""
            sqlx_attributes: dict[str, str] = {}
            sqlx_inputs: list[dict[str, str]] = []
            sqlx_summary = ""
            sqlx_output = ""
            if sqlx_meta:
                relation = ".".join(
                    part for part in (sqlx_meta["schema"], sqlx_meta["name"] or f.stem) if part
                )
                sqlx_attributes = {
                    "etl_platform": "bigquery_dataform",
                    "dialect": "bigquery",
                    "materialization": sqlx_meta["materialization"],
                    "schema": sqlx_meta["schema"],
                    "model_name": sqlx_meta["name"] or f.stem,
                    "column_count": str(len(sqlx_meta["columns"])),
                    "has_aggregation": "true" if sqlx_meta["has_aggregation"] else "false",
                    "dependency_count": str(len(sqlx_meta["deps"])),
                }
                sqlx_inputs = list(sqlx_meta["columns"])
                sqlx_summary = sqlx_meta["description"]
                sqlx_output = relation
            nodes.append(IRNode(
                id=f"prog.{display_name}{_file_suffix}",
                type=IRNodeType.PROGRAM,
                name=display_name,
                source_location=f"{f}:1",
                attributes=sqlx_attributes,
                summary=sqlx_summary,
                inputs=sqlx_inputs,
                output=sqlx_output,
            ))

        node_ids = {n.id for n in nodes}
        model_index = {
            n.attributes["model_name"]: n.id
            for n in nodes
            if n.attributes.get("model_name")
        }
        for f in files:
            _lang_lower = source_lang.lower()
            _display = (
                f.stem if any(_lang_lower.startswith(p) for p in ("java", "kotlin", "scala", "swift", "csharp", "cobol"))
                else _stem_to_name(f.stem)
            )
            _suffix = "_h" if f.suffix.lower() == ".h" else ""
            try:
                content = f.read_text(encoding="utf-8", errors="replace")
                _source_content_cache[str(f)] = content
            except OSError:
                continue
            if f.suffix.lower() == ".sqlx" and content:
                meta = _parse_sqlx_document(content)
                if meta.get("name"):
                    _display = _stem_to_name(meta["name"])
            file_id = f"prog.{_display}{_suffix}"
            if extractor:
                for src, tgt in extractor(content, file_id):
                    resolved = tgt if tgt in node_ids else model_index.get(tgt.split(".")[-1], tgt)
                    if resolved not in node_ids:
                        snake = re.sub(r"(?<!^)(?=[A-Z])", "_", tgt.split(".")[-1]).lower()
                        resolved = model_index.get(snake, resolved)
                    if resolved in node_ids and resolved != src:
                        edges.append(IREdge(source_id=src, target_id=resolved, type=IREdgeType.CALLS))
            if deep_parser:
                extra_nodes, extra_edges = deep_parser(str(f), content, file_id)
                known_ids = {n.id for n in nodes}
                for extra in extra_nodes:
                    if extra.id in known_ids and extra.type == IRNodeType.DATA_STRUCTURE:
                        continue
                    nodes.append(extra)
                    known_ids.add(extra.id)
                edges.extend(extra_edges)
        _attach_scheduler_activities(source_path, nodes, edges)

    ir = IRGraph(
        nodes=nodes,
        edges=edges,
        source_lang=source_lang,
        source_snapshot_sha=_synth_source_sha(source_path),
    )
    ir.stamp(produced_by="observer.parser")
    return ir.model_dump(mode="json")


def catalogue_dead_code(ir_json: dict) -> dict:
    """Identify unreachable programs / procedures."""
    nodes = ir_json.get("nodes", [])
    edges = ir_json.get("edges", [])

    if not edges:
        return {"dead_code": []}

    called_ids = {e["target_id"] for e in edges if e.get("type") == IREdgeType.CALLS.value}
    sourced_ids = {e["source_id"] for e in edges}
    analysable = {IRNodeType.PROGRAM.value, IRNodeType.PROCEDURE.value}

    findings: list[DeadCodeFinding] = []
    for n in nodes:
        if n.get("type") not in analysable:
            continue
        nid = n["id"]
        if nid in called_ids:
            continue
        if nid not in sourced_ids:
            findings.append(DeadCodeFinding(
                node_id=nid,
                reason="No inbound CALLS edge and no outbound edges — isolated node.",
                confidence=Confidence.LOW,
                confirmed_by_telemetry=False,
            ))

    return {"dead_code": [f.model_dump(mode="json") for f in findings]}


def scan_performance_anti_patterns(ir_json: dict) -> dict:
    """Scan source files for structural performance anti-patterns."""
    seen_files: set[str] = set()
    for n in ir_json.get("nodes", []):
        loc = n.get("source_location", "")
        fpath = loc.rsplit(":", 1)[0] if ":" in loc else loc
        if fpath:
            seen_files.add(fpath)

    findings: list[PerformanceFinding] = []
    for fpath in sorted(seen_files):
        p = Path(fpath)
        if not p.exists():
            continue
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines):
            for pattern_id, severity, loop_re, inner_re, remediation in _PERF_PATTERNS:
                if not re.search(loop_re, line):
                    continue
                window = "\n".join(lines[i: i + 20])
                if re.search(inner_re, window):
                    findings.append(PerformanceFinding(
                        node_id=f"prog.{_stem_to_name(p.stem)}",
                        pattern=pattern_id,
                        severity=severity,
                        remediation=remediation,
                    ))
                    break

    # ─── Axon aggregate correctness scans ──────────────────────────────────────
    # Gated on is_axon_aggregate (set by _parse_java_file only when @Aggregate was
    # confirmed to resolve to an org.axonframework.* import) — never fires for a
    # generic aggregate-shaped class from an unrelated framework.
    # `n.get("attributes") or {}`, not `.get("attributes", {})` — the default only
    # applies when the key is missing, not when it's explicitly null.
    nodes_list = ir_json.get("nodes", [])
    agg_nodes = {
        n["id"]: n for n in nodes_list
        if (n.get("attributes") or {}).get("is_axon_aggregate") == "true"
    }
    if agg_nodes:
        agg_fields: dict[str, list[dict]] = {}
        for n in nodes_list:
            if n.get("type") == IRNodeType.DATA_ITEM.value:
                owner = (n.get("attributes") or {}).get("class", "")
                parent_id = f"class.{owner}"
                if parent_id in agg_nodes:
                    agg_fields.setdefault(parent_id, []).append(n)
        for agg_id in agg_nodes:
            fields = agg_fields.get(agg_id, [])
            has_id = any(
                (f.get("attributes") or {}).get("is_aggregate_identifier") == "true"
                for f in fields
            )
            if not has_id:
                findings.append(PerformanceFinding(
                    node_id=agg_id,
                    pattern="MISSING_AGGREGATE_IDENTIFIER",
                    severity="CRITICAL",
                    remediation=(
                        "Every @Aggregate class must have exactly one field annotated "
                        "@AggregateIdentifier to enable routing by Axon CommandGateway."
                    ),
                ))
            for f in fields:
                ftype = (f.get("attributes") or {}).get("type", "")
                if any(t in ftype for t in ("Repository", "EntityManager", "JdbcTemplate")):
                    findings.append(PerformanceFinding(
                        node_id=agg_id,
                        pattern="BYPASS_COMMAND_GATEWAY",
                        severity="HIGH",
                        remediation=(
                            "Avoid directly injecting or using database repositories inside "
                            "event-sourced aggregates. All mutations must go through command "
                            "routing and event application."
                        ),
                    ))
                    break

    return {"performance_findings": [f.model_dump(mode="json") for f in findings]}


def retrieve_documentation(source_path: str) -> dict:
    """Walk source_path for documentation files and return their contents."""
    root = Path(source_path)
    bundle: dict[str, str] = {}

    if root.exists() and root.is_dir():
        for f in sorted(root.rglob("*")):
            if not f.is_file() or f.suffix not in _DOC_EXTENSIONS:
                continue
            try:
                content = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            bundle[str(f.relative_to(root))] = content[:2000]

    return {"documentation_bundle": bundle}


def observe_source_estate(source_path: str, source_lang: str) -> dict:
    """Run all Observer analyses and return the complete IR."""
    ir = parse_source_estate(source_path, source_lang)
    dead = catalogue_dead_code(ir)
    perf = scan_performance_anti_patterns(ir)
    docs = retrieve_documentation(source_path)

    nodes = ir.get("nodes", [])
    edges = ir.get("edges", [])
    warnings: list[str] = []
    if not edges and len(nodes) == 1 and not nodes[0].get("source_location"):
        exts = _extensions_for(source_lang)
        warnings.append(
            f"No source files matching {exts} found under '{source_path}'. "
            f"Verify --source-lang is correct for this repository."
        )

    source_excerpts: dict[str, str] = {}
    _EXCERPT_CHARS = 800
    for n in nodes:
        if n.get("type") != "PROGRAM":
            continue
        loc = n.get("source_location", "")
        fpath = loc.rsplit(":", 1)[0] if ":" in loc else loc
        if not fpath:
            continue
        p = Path(fpath)
        if p.is_file():
            try:
                content = _source_content_cache.get(str(p)) or p.read_text(encoding="utf-8", errors="replace")
                source_excerpts[str(p.relative_to(Path(source_path)))] = content[:_EXCERPT_CHARS]
            except (OSError, ValueError):
                pass

    return {
        "nodes": nodes,
        "edges": edges,
        "source_lang": ir.get("source_lang", source_lang),
        "source_snapshot_sha": ir.get("source_snapshot_sha", ""),
        "dead_code": dead.get("dead_code", []),
        "performance_findings": perf.get("performance_findings", []),
        "documentation_bundle": docs.get("documentation_bundle", {}),
        "source_excerpts": source_excerpts,
        "warnings": warnings,
    }


_ir_cache: dict[str, dict] = {}


def submit_observer_output(
    llm_observations: list,
    function_summaries: list | None = None,
    source_path: str = "",
    source_lang: str = "",
    tool_context: Optional[ToolContext] = None,
) -> dict:
    """Build the IR property graph, attach observations, and merge LLM annotations into nodes.

    Works for any source language. The LLM provides the semantic layer;
    the deterministic parser provides structure. Both are merged per node.

    Args:
        llm_observations: Up to 15 plain-English estate-level insights.
        function_summaries: Per-node annotations (optional).
        source_path: Root directory of the source estate (resolved from session
            state automatically — the LLM does not need to pass this).
        source_lang: Language of the source files (resolved from session state
            automatically — the LLM does not need to pass this).
        llm_observations: Up to 15 plain-English estate-level insights.
        function_summaries: Per-node annotations — one entry per function, method,
            or class, for any language. Each entry:
            {
              "name": "<exact function/method/class name>",
              "summary": "<one sentence: what it does>",
              "inputs": [
                {"name": "<param>", "type": "<type>", "description": "<what it is>"}
              ],
              "output": "<return type and what it produces>"
            }
            Matched case-insensitively against IR node names.
            For languages where the parser cannot extract signatures (COBOL, Go,
            Java, Rust, etc.), the LLM inputs list is used directly.
            For languages where the parser already extracted param names (Python,
            PHP), the LLM enriches existing entries with type and description.
    """
    # Resolve source_path / source_lang from session state when the LLM omits them.
    if not source_path or not source_lang:
        if tool_context is not None:
            state = tool_context.state
            if not source_path:
                source_path = state.get("source_path", "")
            if not source_lang:
                source_lang = state.get("source_lang", "")

    ir = observe_source_estate(source_path, source_lang)
    observations = [str(o).strip() for o in (llm_observations or []) if o]
    ir["llm_observations"] = observations

    if function_summaries:
        summary_map: dict[str, dict] = {}
        for entry in function_summaries:
            if isinstance(entry, dict) and entry.get("name"):
                summary_map[entry["name"].lower()] = entry

        for node in ir.get("nodes", []):
            match = summary_map.get((node.get("name") or "").lower())
            if not match:
                continue

            # Summary: take LLM value if the parser didn't find one
            if match.get("summary") and not node.get("summary"):
                node["summary"] = match["summary"]

            # Output: take LLM value if the parser didn't find one
            if match.get("output") and not node.get("output"):
                node["output"] = match["output"]

            # Inputs: three cases
            llm_inputs = match.get("inputs") or []
            existing = node.get("inputs") or []

            if not existing and llm_inputs:
                # Language has no deterministic parser (COBOL, Go, Java, etc.)
                # Use LLM inputs directly
                node["inputs"] = [
                    {k: str(v) for k, v in p.items() if k in ("name", "type", "description", "default")}
                    for p in llm_inputs if isinstance(p, dict) and p.get("name")
                ]
            elif existing and llm_inputs:
                # Parser gave param names; LLM enriches with type and description
                llm_by_name = {p["name"].lower(): p for p in llm_inputs if isinstance(p, dict) and p.get("name")}
                for param in existing:
                    lp = llm_by_name.get((param.get("name") or "").lower())
                    if not lp:
                        continue
                    if lp.get("type") and not param.get("type"):
                        param["type"] = lp["type"]
                    if lp.get("description") and not param.get("description"):
                        param["description"] = lp["description"]

    # Enrich cache with dead_code so the Cartographer can isolate dead nodes
    if "dead_code" not in ir:
        ir["dead_code"] = catalogue_dead_code(ir).get("dead_code", [])

    key = f"{source_path}:{source_lang}"
    _ir_cache[key] = ir

    node_counts: dict[str, int] = {}
    for n in ir.get("nodes", []):
        node_counts[n.get("type", "UNKNOWN")] = node_counts.get(n.get("type", "UNKNOWN"), 0) + 1

    return {
        "status": "complete",
        "source_path": source_path,
        "source_lang": source_lang,
        "nodes": len(ir.get("nodes", [])),
        "edges": len(ir.get("edges", [])),
        "node_types": node_counts,
        "llm_observations_merged": len(observations),
        "function_summaries_merged": len(function_summaries or []),
    }
