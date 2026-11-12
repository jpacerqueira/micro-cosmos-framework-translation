"""Code Reviewer tools — deterministic checks on in-memory seam_result files.

Runs before the Writer agent so defects can be caught and fed back to
the Coder+Judge for a retry, without touching the filesystem.

Checks performed (in order):
  1. Coverage       — every IR PROGRAM node has a translated file
  2. Procedure map  — every source procedure appears as a method/function
  3. Decimal hygiene — no float/double on monetary fields
  4. TODO density   — < 30 % TODO lines per file
  5. Bracket balance — curly braces balanced (compiled languages)
"""

from __future__ import annotations

import json
import re
from pathlib import Path


_MONETARY_WORDS = re.compile(
    r"(?i)\b(amount|balance|price|rate|cost|fee|charge|total|salary|wage)\b"
)
_FLOAT_TYPES: dict[str, list[str]] = {
    "java":       [r"\bfloat\b", r"\bdouble\b", r"\bFloat\b", r"\bDouble\b"],
    "java8":      [r"\bfloat\b", r"\bdouble\b", r"\bFloat\b", r"\bDouble\b"],
    "java11":     [r"\bfloat\b", r"\bdouble\b", r"\bFloat\b", r"\bDouble\b"],
    "java21":     [r"\bfloat\b", r"\bdouble\b", r"\bFloat\b", r"\bDouble\b"],
    "python":     [r"\bfloat\b"],
    "python3":    [r"\bfloat\b"],
    "go":         [r"\bfloat32\b", r"\bfloat64\b"],
    "typescript": [],  # 'number' is ambiguous; skip auto-flag
    "csharp":     [r"\bfloat\b", r"\bdouble\b"],
    "cs":         [r"\bfloat\b", r"\bdouble\b"],
    "kotlin":     [r"\bFloat\b", r"\bDouble\b", r"\bfloat\b", r"\bdouble\b"],
    "rust":       [r"\bf32\b", r"\bf64\b"],
    "scala":      [r"\bFloat\b", r"\bDouble\b"],
    "swift":      [r"\bFloat\b", r"\bDouble\b"],
}


def _check_float_usage(content: str, path: str, target_lang: str) -> list[dict]:
    findings = []
    tl = target_lang.lower()
    for pat in _FLOAT_TYPES.get(tl, []):
        for i, line in enumerate(content.splitlines(), 1):
            if _MONETARY_WORDS.search(line) and re.search(pat, line):
                findings.append({
                    "severity": "BLOCKER",
                    "check": "DECIMAL_HYGIENE",
                    "path": path,
                    "line": i,
                    "message": f"Monetary field uses imprecise float type on line {i}: {line.strip()!r}",
                })
                break
    return findings


def _check_todo_density(content: str, path: str) -> list[dict]:
    lines = content.splitlines()
    if not lines:
        return []
    todo_count = sum(1 for l in lines if re.search(r"//\s*TODO|#\s*TODO", l))
    ratio = todo_count / len(lines)
    if ratio > 0.30:
        return [{
            "severity": "MAJOR",
            "check": "TODO_DENSITY",
            "path": path,
            "line": 0,
            "message": (
                f"{todo_count}/{len(lines)} lines ({ratio:.0%}) are TODO stubs in {path}. "
                "Translation is likely incomplete — re-translate with full procedure bodies."
            ),
        }]
    return []


_TEST_SUFFIXES = (
    "_test.go", "Test.java", "Tests.java", "Spec.java",
    "test_.py", "_test.py", ".test.ts", ".spec.ts",
    "Test.kt", "Tests.kt", "Spec.scala", "Tests.cs", "Spec.cs",
)
_TEST_MARKERS = (
    "#[cfg(test)]", "@Test", "def test_", "func Test",
    "describe(", "it(", "[Fact]", "[Theory]",
)
_PORT_ONLY_DIRS = {"ports", "port", "Ports", "Port"}


def _check_test_presence(pr_files: list[dict]) -> list[dict]:
    """Verify at least one test file is present in the submission."""
    has_tests = any(
        any(f["path"].endswith(s) for s in _TEST_SUFFIXES)
        or any(m in f.get("content", "") for m in _TEST_MARKERS)
        for f in pr_files
    )
    if not has_tests:
        return [{
            "severity": "BLOCKER",
            "check": "TEST_PRESENCE",
            "path": "<submission>",
            "line": 0,
            "message": (
                "No test files found in the generated output. "
                "Re-architect and include unit tests covering the happy path, "
                "a rule violation, and an edge case."
            ),
        }]
    return []


def _check_impl_presence(pr_files: list[dict], target_lang: str) -> list[dict]:
    """Verify at least one non-port implementation file is present."""
    impl_files = [
        f for f in pr_files
        if not any(part in _PORT_ONLY_DIRS
                   for part in f["path"].replace("\\", "/").split("/"))
    ]
    from micro_cosmos.tools.observer_tools import _extensions_for
    exts = set(_extensions_for(target_lang))
    code_impls = [f for f in impl_files if any(f["path"].endswith(e) for e in exts)]
    if not code_impls:
        return [{
            "severity": "BLOCKER",
            "check": "IMPL_PRESENCE",
            "path": "<submission>",
            "line": 0,
            "message": (
                "No implementation files found — only port/interface stubs submitted. "
                "Re-submit with concrete domain types and method bodies."
            ),
        }]
    return []


def _check_bracket_balance(content: str, path: str, target_lang: str) -> list[dict]:
    tl = target_lang.lower()
    if tl in ("python", "python3"):
        return []
    if content.count("{") != content.count("}"):
        return [{
            "severity": "BLOCKER",
            "check": "BRACKET_BALANCE",
            "path": path,
            "line": 0,
            "message": (
                f"Unbalanced braces in {path}: "
                f"{content.count('{')} open vs {content.count('}')} close. File will not compile."
            ),
        }]
    return []


def _procedure_names_from_ir(source_path: str, source_lang: str, seam_name: str) -> list[str]:
    """Return procedure/function names from the IR that must appear in translated output."""
    try:
        from micro_cosmos.tools.observer_tools import parse_source_estate
        ir = parse_source_estate(source_path, source_lang)
        names = [
            node.get("name", "")
            for node in ir.get("nodes", [])
            if node.get("type") == "PROCEDURE"
        ]
        return [n for n in names if n]
    except Exception:
        return []


def review_generated_code(
    source_path: str,
    source_lang: str,
    target_lang: str,
    seam_name: str,
    run_dir: str,
) -> dict:
    """Review the seam_result PR files for correctness before they are written.

    Reads the seam_result.json from run_dir (written by CODER_JUDGE) and
    runs deterministic checks on the in-memory file contents.

    Args:
        source_path: Root directory of the source estate.
        source_lang: Source language (cobol, python, java, …).
        target_lang: Target language for the translation.
        seam_name:   Name of the seam being reviewed.
        run_dir:     Path to the current run directory.

    Returns:
        Dict with ``passed`` (bool), ``issues`` (list of finding dicts),
        ``summary`` (str), ``severity_counts`` (dict), and
        ``procedures_missing`` (list of paragraph names not found in the output).
    """
    tl = target_lang.lower()

    # Load seam_result produced by CODER_JUDGE
    seam_result_path = Path(run_dir) / "seam_result.json"
    if not seam_result_path.exists():
        return {
            "passed": False,
            "issues": [{
                "severity": "BLOCKER",
                "check": "SEAM_RESULT_MISSING",
                "path": str(seam_result_path),
                "line": 0,
                "message": "seam_result.json not found — CODER_JUDGE may not have completed.",
            }],
            "summary": "FAILED: seam_result.json missing.",
            "severity_counts": {"BLOCKER": 1, "MAJOR": 0, "MINOR": 0},
            "procedures_missing": [],
        }

    try:
        seam_result = json.loads(seam_result_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "passed": False,
            "issues": [{
                "severity": "BLOCKER",
                "check": "SEAM_RESULT_PARSE",
                "path": str(seam_result_path),
                "line": 0,
                "message": f"Could not parse seam_result.json: {exc}",
            }],
            "summary": f"FAILED: seam_result.json parse error: {exc}",
            "severity_counts": {"BLOCKER": 1, "MAJOR": 0, "MINOR": 0},
            "procedures_missing": [],
        }

    pr_files: list[dict] = seam_result.get("pr", {}).get("files", [])

    # CHECK 1: at least one translated file exists
    issues: list[dict] = []
    if not pr_files:
        issues.append({
            "severity": "BLOCKER",
            "check": "FILE_COVERAGE",
            "path": seam_name,
            "line": 0,
            "message": "No files in the generated PR — translation produced no output.",
        })

    # CHECK 2a: implementation files present (not just port stubs)
    issues.extend(_check_impl_presence(pr_files, tl))

    # CHECK 2b: test files present
    issues.extend(_check_test_presence(pr_files))

    # Checks per generated file
    expected_procs = _procedure_names_from_ir(source_path, source_lang, seam_name)
    missing_procs: list[str] = []
    all_content = "\n".join(f.get("content", "") for f in pr_files)

    for f in pr_files:
        path = f.get("path", "<unknown>")
        content = f.get("content", "")
        issues.extend(_check_float_usage(content, path, tl))
        issues.extend(_check_todo_density(content, path))
        issues.extend(_check_bracket_balance(content, path, tl))

    # CHECK: procedure coverage (source procedures mapped to output methods)
    if expected_procs:
        for proc in expected_procs:
            # Accept snake_case, camelCase, or PascalCase variants of the paragraph name
            clean = re.sub(r"[_\-]", "", proc).lower()
            if clean not in re.sub(r"[_\-]", "", all_content).lower():
                missing_procs.append(proc)
        if missing_procs:
            issues.append({
                "severity": "MAJOR",
                "check": "PROCEDURE_COVERAGE",
                "path": seam_name,
                "line": 0,
                "message": (
                    f"{len(missing_procs)} source procedure(s) not found in translated output: "
                    + ", ".join(missing_procs[:10])
                    + ("…" if len(missing_procs) > 10 else "")
                    + ". Re-translate and ensure all procedures are represented as methods."
                ),
            })

    severity_counts = {"BLOCKER": 0, "MAJOR": 0, "MINOR": 0}
    for issue in issues:
        sev = issue.get("severity", "MINOR")
        severity_counts[sev] = severity_counts.get(sev, 0) + 1

    passed = severity_counts["BLOCKER"] == 0 and severity_counts["MAJOR"] == 0

    blockers = [i["message"] for i in issues if i.get("severity") == "BLOCKER"]
    majors   = [i["message"] for i in issues if i.get("severity") == "MAJOR"]
    parts = [f"{'PASSED' if passed else 'FAILED'}: {len(pr_files)} file(s) reviewed."]
    parts.append(
        f"Findings: {severity_counts['BLOCKER']} BLOCKER, "
        f"{severity_counts['MAJOR']} MAJOR, {severity_counts['MINOR']} MINOR."
    )
    if blockers:
        parts.append("BLOCKERS: " + "; ".join(blockers[:3]))
    if majors:
        parts.append("MAJORS: " + "; ".join(majors[:3]))

    return {
        "passed": passed,
        "issues": issues,
        "summary": " ".join(parts),
        "severity_counts": severity_counts,
        "procedures_missing": missing_procs,
    }
