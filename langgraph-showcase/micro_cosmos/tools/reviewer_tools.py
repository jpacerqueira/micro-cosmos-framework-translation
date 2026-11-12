"""PR Reviewer Agent tools — rigorous automated code review of the output.

Performs a sequential series of checks across every translated file in the
output directory. Each check targets a specific quality dimension:

  1. File coverage    — translated source files exist (not just port stubs)
  2. Decimal hygiene  — no float/double used for monetary/COMP-3 fields
  3. Import integrity — language-specific imports match field types used
  4. TODO density     — translated code has < 40 % comment-only lines
  5. Method coverage  — each class has at least one substantive method
  6. Port presence    — hexagonal port interfaces accompany every program
  7. Structural parse — files are syntactically plausible (bracket balance, etc.)

Each finding has a severity: BLOCKER, MAJOR, MINOR, or INFO.
The review passes only when there are no BLOCKER or MAJOR findings.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


# ─── per-language check helpers ───────────────────────────────────────────────

_MONETARY_WORDS = re.compile(
    r"(?i)\b(amount|balance|price|rate|cost|fee|charge|total|salary|wage|revenue|profit|loss)\b"
)

_FLOAT_TYPES: dict[str, list[str]] = {
    "java":       [r"\bfloat\b", r"\bdouble\b", r"\bFloat\b", r"\bDouble\b"],
    "java8":      [r"\bfloat\b", r"\bdouble\b", r"\bFloat\b", r"\bDouble\b"],
    "java11":     [r"\bfloat\b", r"\bdouble\b", r"\bFloat\b", r"\bDouble\b"],
    "java21":     [r"\bfloat\b", r"\bdouble\b", r"\bFloat\b", r"\bDouble\b"],
    "python":     [r"\bfloat\b"],
    "python3":    [r"\bfloat\b"],
    "go":         [r"\bfloat32\b", r"\bfloat64\b"],
    "typescript": [r"\bnumber\b"],  # only flag when paired with monetary name
    "csharp":     [r"\bfloat\b", r"\bdouble\b", r"\bFloat\b", r"\bDouble\b"],
    "cs":         [r"\bfloat\b", r"\bdouble\b", r"\bFloat\b", r"\bDouble\b"],
    "kotlin":     [r"\bFloat\b", r"\bDouble\b", r"\bfloat\b", r"\bdouble\b"],
    "rust":       [r"\bf32\b", r"\bf64\b"],
    "scala":      [r"\bFloat\b", r"\bDouble\b", r"\bfloat\b", r"\bdouble\b"],
    "swift":      [r"\bFloat\b", r"\bDouble\b"],
}

_DECIMAL_IMPORTS: dict[str, str] = {
    "java":       r"import\s+java\.math\.BigDecimal",
    "java8":      r"import\s+java\.math\.BigDecimal",
    "java11":     r"import\s+java\.math\.BigDecimal",
    "java21":     r"import\s+java\.math\.BigDecimal",
    "python":     r"from\s+decimal\s+import\s+Decimal",
    "python3":    r"from\s+decimal\s+import\s+Decimal",
    "go":         r'"github\.com/shopspring/decimal"',
    "typescript": r"import\s+Decimal\s+from\s+['\"]decimal\.js['\"]",
    "kotlin":     r"import\s+java\.math\.BigDecimal",
    "rust":       r"use\s+rust_decimal|use\s+bigdecimal",
    "csharp":     r"\bdecimal\b",
    "cs":         r"\bdecimal\b",
}

_CLASS_RE: dict[str, re.Pattern] = {
    "java":       re.compile(r"public\s+class\s+\w+"),
    "java8":      re.compile(r"public\s+class\s+\w+"),
    "java11":     re.compile(r"public\s+class\s+\w+"),
    "java21":     re.compile(r"public\s+class\s+\w+"),
    "python":     re.compile(r"^class\s+\w+", re.MULTILINE),
    "python3":    re.compile(r"^class\s+\w+", re.MULTILINE),
    "go":         re.compile(r"type\s+\w+\s+struct"),
    "typescript": re.compile(r"export\s+class\s+\w+"),
    "csharp":     re.compile(r"public\s+class\s+\w+"),
    "cs":         re.compile(r"public\s+class\s+\w+"),
    "kotlin":     re.compile(r"(?:data\s+)?class\s+\w+|object\s+\w+"),
    "rust":       re.compile(r"struct\s+\w+|impl\s+\w+"),
    "scala":      re.compile(r"class\s+\w+|case\s+class\s+\w+|object\s+\w+"),
    "swift":      re.compile(r"class\s+\w+|struct\s+\w+"),
}

_METHOD_RE: dict[str, re.Pattern] = {
    "java":       re.compile(r"(public|private|protected)\s+\w[\w<>[\]]+\s+\w+\s*\("),
    "java8":      re.compile(r"(public|private|protected)\s+\w[\w<>[\]]+\s+\w+\s*\("),
    "java11":     re.compile(r"(public|private|protected)\s+\w[\w<>[\]]+\s+\w+\s*\("),
    "java21":     re.compile(r"(public|private|protected)\s+\w[\w<>[\]]+\s+\w+\s*\("),
    "python":     re.compile(r"^\s+def\s+\w+\s*\(", re.MULTILINE),
    "python3":    re.compile(r"^\s+def\s+\w+\s*\(", re.MULTILINE),
    "go":         re.compile(r"func\s+\(\w+\s+\*?\w+\)\s+\w+\s*\("),
    "typescript": re.compile(r"(public|private)?\s+\w+\s*\([^)]*\)\s*(?::\s*\w+)?\s*\{"),
    "csharp":     re.compile(r"(public|private|protected)\s+\w[\w<>[\]]+\s+\w+\s*\("),
    "cs":         re.compile(r"(public|private|protected)\s+\w[\w<>[\]]+\s+\w+\s*\("),
    "kotlin":     re.compile(r"fun\s+\w+\s*\("),
    "rust":       re.compile(r"fn\s+\w+\s*\("),
    "scala":      re.compile(r"def\s+\w+\s*[\(\[]"),
    "swift":      re.compile(r"func\s+\w+\s*\("),
}

_PORT_PATTERNS: dict[str, re.Pattern] = {
    "java":       re.compile(r"public\s+interface\s+I\w+(UseCase|Repository)"),
    "java8":      re.compile(r"public\s+interface\s+I\w+(UseCase|Repository)"),
    "java11":     re.compile(r"public\s+interface\s+I\w+(UseCase|Repository)"),
    "java21":     re.compile(r"public\s+interface\s+I\w+(UseCase|Repository)"),
    "python":     re.compile(r"class\s+I\w+(UseCase|Repository)\s*\(Protocol\)"),
    "python3":    re.compile(r"class\s+I\w+(UseCase|Repository)\s*\(Protocol\)"),
    "go":         re.compile(r"type\s+\w+(UseCase|Repository)\s+interface"),
    "typescript": re.compile(r"export\s+interface\s+I\w+(UseCase|Repository)"),
    "csharp":     re.compile(r"public\s+interface\s+I\w+(UseCase|Repository)"),
    "cs":         re.compile(r"public\s+interface\s+I\w+(UseCase|Repository)"),
    "kotlin":     re.compile(r"interface\s+I?\w+(UseCase|Repository)"),
    "rust":       re.compile(r"trait\s+\w+(UseCase|Repository)"),
    "scala":      re.compile(r"trait\s+\w+(UseCase|Repository)"),
    "swift":      re.compile(r"protocol\s+\w+(UseCase|Repository)"),
}


def _severity_label(blocker: int, major: int, minor: int) -> str:
    if blocker:
        return "FAIL"
    if major:
        return "WARN"
    return "PASS"


def _check_decimal_hygiene(content: str, path: str, target_lang: str) -> list[dict]:
    """Flag float/double used on monetary fields."""
    findings: list[dict] = []
    tl = target_lang.lower()
    float_patterns = _FLOAT_TYPES.get(tl, [])
    for i, line in enumerate(content.splitlines(), 1):
        if not _MONETARY_WORDS.search(line):
            continue
        for pat in float_patterns:
            if re.search(pat, line):
                # TypeScript: 'number' is flagged only with a monetary word
                findings.append({
                    "path": path,
                    "line": i,
                    "severity": "BLOCKER",
                    "check": "DECIMAL_HYGIENE",
                    "message": (
                        f"Monetary field uses imprecise type on line {i}: {line.strip()!r}. "
                        f"Use BigDecimal / Decimal / decimal instead."
                    ),
                })
                break
    return findings


def _check_decimal_imports(content: str, path: str, target_lang: str) -> list[dict]:
    """Verify that the required decimal import is present when decimal types are used."""
    tl = target_lang.lower()
    import_re = _DECIMAL_IMPORTS.get(tl)
    if not import_re:
        return []
    decimal_keywords = {"BigDecimal", "Decimal", "decimal.Decimal", "decimal.NewFromInt"}
    uses_decimal = any(kw in content for kw in decimal_keywords)
    if uses_decimal and not re.search(import_re, content):
        return [{
            "path": path,
            "line": 1,
            "severity": "MAJOR",
            "check": "MISSING_IMPORT",
            "message": f"Decimal type used but required import not found in {path}.",
        }]
    return []


def _check_todo_density(content: str, path: str) -> list[dict]:
    """Flag files where > 40 % of lines are TODO comments."""
    lines = content.splitlines()
    if not lines:
        return []
    todo_lines = sum(1 for l in lines if re.search(r"//\s*TODO|#\s*TODO", l))
    ratio = todo_lines / len(lines)
    if ratio > 0.40:
        return [{
            "path": path,
            "line": 0,
            "severity": "MAJOR",
            "check": "TODO_DENSITY",
            "message": (
                f"{todo_lines}/{len(lines)} lines ({ratio:.0%}) are TODO comments in {path}. "
                "Translation may be incomplete."
            ),
        }]
    if ratio > 0.20:
        return [{
            "path": path,
            "line": 0,
            "severity": "MINOR",
            "check": "TODO_DENSITY",
            "message": (
                f"{todo_lines}/{len(lines)} lines ({ratio:.0%}) are TODO comments in {path}. "
                "Review for completeness."
            ),
        }]
    return []


def _check_method_coverage(content: str, path: str, target_lang: str) -> list[dict]:
    """Each class-bearing file should have at least one substantive method."""
    tl = target_lang.lower()
    class_re = _CLASS_RE.get(tl)
    method_re = _METHOD_RE.get(tl)
    if not class_re or not method_re:
        return []
    has_class = bool(class_re.search(content))
    method_count = len(method_re.findall(content))
    if has_class and method_count == 0:
        return [{
            "path": path,
            "line": 0,
            "severity": "MAJOR",
            "check": "METHOD_COVERAGE",
            "message": f"{path} defines a class but has no methods — translation may be empty.",
        }]
    return []


def _check_bracket_balance(content: str, path: str, target_lang: str) -> list[dict]:
    """Ensure curly braces are balanced for brace-delimited languages."""
    from micro_cosmos.tools.observer_tools import _extensions_for
    if _extensions_for(target_lang.lower())[:1] == [".py"]:
        return []  # Python uses indentation, not braces
    open_count = content.count("{")
    close_count = content.count("}")
    if open_count != close_count:
        return [{
            "path": path,
            "line": 0,
            "severity": "BLOCKER",
            "check": "BRACKET_BALANCE",
            "message": (
                f"{path} has unbalanced braces: {open_count} open, {close_count} close. "
                "File will not compile."
            ),
        }]
    return []


def _check_python_indentation(content: str, path: str) -> list[dict]:
    """Detect mixed tabs/spaces in Python files."""
    findings: list[dict] = []
    for i, line in enumerate(content.splitlines(), 1):
        if line.startswith("\t") and "    " in line[:8]:
            findings.append({
                "path": path,
                "line": i,
                "severity": "MINOR",
                "check": "INDENTATION",
                "message": f"Mixed tab/space indentation on line {i} in {path}.",
            })
            break
    return findings


# ─── public API ───────────────────────────────────────────────────────────────

def _resolve_output_dir(run_dir: Path) -> Path:
    """Find the output directory for a run.

    Reads output_dir from write_manifest.json (written by the Writer tool).
    Falls back to the first subdirectory that looks like a generated project,
    then to the legacy 'output/' path.
    """
    manifest = run_dir / "write_manifest.json"
    if manifest.exists():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            out = Path(data.get("output_dir", ""))
            if out.is_dir():
                return out
        except Exception:
            pass
    # Scan for any non-system subdirectory
    for d in sorted(run_dir.iterdir()):
        if d.is_dir() and d.name not in ("__pycache__",) and not d.name.endswith(".json"):
            return d
    return run_dir / "output"


def review_output_files(run_dir: str, target_lang: str, source_lang: str) -> dict:
    """Perform a rigorous sequential code review of all files in the output directory.

    Runs eight checks in order:
      1. File coverage  — translated source files exist (not just ports)
      2. Decimal hygiene — no float/double on monetary fields
      3. Import integrity — decimal imports present where needed
      4. TODO density  — < 40 % TODO lines per file
      5. Method coverage — classes have at least one method
      6. Port presence — port interfaces exist alongside programs
      7. Structural parse — brace balance (compiled languages)
      8. README present — README.md exists with correct build instructions

    Args:
        run_dir: Path to the current run directory.
        target_lang: Target language (java, python, go, typescript, csharp).
        source_lang: Source language (for metadata).

    Returns:
        Dict with ``review_passed`` (bool), ``findings`` (list), ``summary`` (str),
        ``metrics`` (dict), and ``severity_counts`` (dict).
    """
    output_dir = _resolve_output_dir(Path(run_dir))
    tl = target_lang.lower()

    # ── 1. collect files ──────────────────────────────────────────────────────
    from micro_cosmos.tools.observer_tools import _extensions_for
    exts = _extensions_for(tl)
    ext = exts[0] if exts else f".{tl}"
    all_files: list[Path] = []
    if output_dir.exists():
        all_files = sorted(p for p in output_dir.rglob("*") if p.is_file())

    target_files = [p for p in all_files if p.suffix in exts]
    port_pattern = _PORT_PATTERNS.get(tl)

    findings: list[dict] = []

    # ── CHECK 1: file coverage ─────────────────────────────────────────────────
    if not target_files:
        findings.append({
            "path": str(output_dir),
            "line": 0,
            "severity": "BLOCKER",
            "check": "FILE_COVERAGE",
            "message": (
                f"No {ext or target_lang} files found in output directory. "
                "The Writer agent may not have run, or the source estate has no translatable files."
            ),
        })
    else:
        # Check for at least one file with real content (not empty scaffolding placeholder)
        impl_files = [p for p in target_files if p.stat().st_size > 50]
        if not impl_files:
            findings.append({
                "path": str(output_dir),
                "line": 0,
                "severity": "MAJOR",
                "check": "FILE_COVERAGE",
                "message": (
                    "Output contains only empty placeholder files — no translated implementation. "
                    "The Coder agent submitted no content; re-run to trigger another attempt."
                ),
            })

    # ── CHECK 6: port presence (done early so we can report against file list) ──
    has_ports = False
    if port_pattern:
        for p in target_files:
            try:
                content = p.read_text(encoding="utf-8", errors="replace")
                if port_pattern.search(content):
                    has_ports = True
                    break
            except OSError:
                pass
    if target_files and not has_ports:
        findings.append({
            "path": str(output_dir),
            "line": 0,
            "severity": "MAJOR",
            "check": "PORT_PRESENCE",
            "message": (
                "No hexagonal port interfaces (UseCase / Repository) found in output. "
                "The migration target must follow hexagonal architecture — "
                "every seam needs explicit port interfaces separating domain from infrastructure."
            ),
        })

    # ── PER-FILE CHECKS 2–5, 7 ────────────────────────────────────────────────
    total_lines = 0
    total_todo = 0
    file_reports: list[dict] = []

    for fpath in target_files:
        try:
            content = fpath.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            findings.append({
                "path": str(fpath.relative_to(output_dir)),
                "line": 0,
                "severity": "MAJOR",
                "check": "FILE_READ",
                "message": f"Could not read file: {exc}",
            })
            continue

        rel = str(fpath.relative_to(output_dir))
        lines = content.splitlines()
        total_lines += len(lines)
        total_todo += sum(1 for l in lines if re.search(r"//\s*TODO|#\s*TODO", l))

        file_findings: list[dict] = []
        file_findings.extend(_check_decimal_hygiene(content, rel, tl))
        file_findings.extend(_check_decimal_imports(content, rel, tl))
        file_findings.extend(_check_todo_density(content, rel))
        file_findings.extend(_check_method_coverage(content, rel, tl))
        file_findings.extend(_check_bracket_balance(content, rel, tl))
        if ext == ".py":
            file_findings.extend(_check_python_indentation(content, rel))

        findings.extend(file_findings)
        file_reports.append({
            "path": rel,
            "lines": len(lines),
            "finding_count": len(file_findings),
        })

    # ── CHECK 8: README.md ────────────────────────────────────────────────────
    readme_path = output_dir / "README.md"
    if not readme_path.exists():
        findings.append({
            "path": "README.md",
            "line": 0,
            "severity": "MAJOR",
            "check": "README_MISSING",
            "message": (
                "README.md not found in output directory. "
                "The Writer agent should generate one automatically."
            ),
        })
    else:
        try:
            readme_content = readme_path.read_text(encoding="utf-8", errors="replace")
            # Verify the README contains language-appropriate build keywords
            _build_keywords: dict[str, list[str]] = {
                "java": ["mvn", "gradle", "javac"],
                "java8": ["mvn", "gradle"],
                "java11": ["mvn", "gradle"],
                "java21": ["mvn", "gradle"],
                "python": ["pytest", "pip", "python"],
                "python2": ["pytest", "pip", "python"],
                "python3": ["pytest", "pip", "python"],
                "go": ["go build", "go test", "go mod"],
                "typescript": ["npm", "tsc", "npx"],
                "javascript": ["npm", "node"],
                "csharp": ["dotnet"],
                "cs": ["dotnet"],
                "kotlin": ["gradlew", "gradle"],
                "rust": ["cargo"],
                "scala": ["sbt"],
                "swift": ["swift build", "swift test"],
            }
            keywords = _build_keywords.get(tl, [])
            if keywords and not any(kw in readme_content for kw in keywords):
                findings.append({
                    "path": "README.md",
                    "line": 0,
                    "severity": "MINOR",
                    "check": "README_BUILD_INSTRUCTIONS",
                    "message": (
                        f"README.md does not contain {tl} build instructions "
                        f"(expected one of: {', '.join(keywords)})."
                    ),
                })
            # Verify at least one actual output file is mentioned
            mentioned = any(
                f.get("path", "") in readme_content
                for f in file_reports
                if f.get("path") != "README.md"
            )
            if file_reports and not mentioned:
                findings.append({
                    "path": "README.md",
                    "line": 0,
                    "severity": "MINOR",
                    "check": "README_FILE_REFERENCES",
                    "message": "README.md does not reference any of the generated output files.",
                })
        except OSError as exc:
            findings.append({
                "path": "README.md",
                "line": 0,
                "severity": "MAJOR",
                "check": "README_READ_ERROR",
                "message": f"Could not read README.md: {exc}",
            })

    # ── severity counts ───────────────────────────────────────────────────────
    severity_counts = {"BLOCKER": 0, "MAJOR": 0, "MINOR": 0, "INFO": 0}
    for f in findings:
        sev = f.get("severity", "INFO")
        severity_counts[sev] = severity_counts.get(sev, 0) + 1

    review_passed = severity_counts["BLOCKER"] == 0 and severity_counts["MAJOR"] == 0
    overall = _severity_label(severity_counts["BLOCKER"], severity_counts["MAJOR"], severity_counts["MINOR"])

    todo_ratio = (total_todo / total_lines) if total_lines else 0.0
    summary_parts = [
        f"{'PASSED' if review_passed else 'FAILED'}: {len(target_files)} {tl} file(s) reviewed.",
        f"Findings: {severity_counts['BLOCKER']} BLOCKER, {severity_counts['MAJOR']} MAJOR, "
        f"{severity_counts['MINOR']} MINOR.",
        f"TODO density: {todo_ratio:.0%} ({total_todo}/{total_lines} lines).",
    ]
    if not review_passed:
        blockers = [f["message"] for f in findings if f.get("severity") == "BLOCKER"]
        majors   = [f["message"] for f in findings if f.get("severity") == "MAJOR"]
        if blockers:
            summary_parts.append("BLOCKERS: " + "; ".join(blockers[:3]))
        if majors:
            summary_parts.append("MAJORS: " + "; ".join(majors[:3]))

    # Persist the review report next to the manifest
    report = {
        "review_passed": review_passed,
        "overall": overall,
        "findings": findings,
        "summary": " ".join(summary_parts),
        "severity_counts": severity_counts,
        "metrics": {
            "total_files": len(target_files),
            "total_lines": total_lines,
            "total_todo_lines": total_todo,
            "todo_ratio": round(todo_ratio, 3),
            "has_ports": has_ports,
        },
        "file_reports": file_reports,
    }
    try:
        (Path(run_dir) / "review_report.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
    except OSError:
        pass

    return report
