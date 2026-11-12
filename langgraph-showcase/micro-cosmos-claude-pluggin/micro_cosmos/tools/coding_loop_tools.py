"""Tools for the TDD coding-loop agents.

read_generated_files   — read all PR files from the current seam_result
read_review_feedback   — read consolidated review findings for the Code Writer
submit_code_review     — skeptical reviewer submits findings
submit_test_review     — TDD test reviewer submits findings
submit_functional_review — functional reviewer submits findings
"""

from __future__ import annotations

import json
from pathlib import Path

from micro_cosmos.tools.run_context import get_run_dir, set_run_dir  # noqa: F401 — re-exported


# ─── helpers ──────────────────────────────────────────────────────────────────

def _severity_counts(findings: list[dict]) -> dict:
    counts: dict[str, int] = {"BLOCKER": 0, "MAJOR": 0, "MINOR": 0}
    for f in findings:
        sev = f.get("severity", "MINOR").upper()
        counts[sev] = counts.get(sev, 0) + 1
    return counts


def _has_blocker(findings: list[dict]) -> bool:
    return any(f.get("severity", "").upper() == "BLOCKER" for f in findings)


def _has_blocker_or_major(findings: list[dict]) -> bool:
    return any(f.get("severity", "").upper() in ("BLOCKER", "MAJOR") for f in findings)


# ─── read tools ───────────────────────────────────────────────────────────────

def read_generated_files(run_dir: str) -> dict:
    """Read all PR files from the current seam_result.

    Reads ``seam_result.json`` from run_dir and returns each file's path,
    content, and line count.

    Args:
        run_dir: Path to the current run directory.

    Returns:
        Dict with ``files`` (list of {path, content, lines}), ``count`` (int),
        ``seam_name`` (str), ``target_lang`` (str).  On error returns
        ``{files: [], error: str}``.
    """
    seam_result_path = Path(run_dir) / "seam_result.json"
    if not seam_result_path.exists():
        return {
            "files": [],
            "count": 0,
            "seam_name": "",
            "target_lang": "",
            "error": f"seam_result.json not found at {seam_result_path}",
        }

    try:
        raw = seam_result_path.read_text(encoding="utf-8")
        seam_result = json.loads(raw)
        # ADK sometimes double-encodes: the saved value is a JSON string
        # whose decoded value is the actual dict.
        if isinstance(seam_result, str):
            seam_result = json.loads(seam_result)
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "files": [],
            "count": 0,
            "seam_name": "",
            "target_lang": "",
            "error": f"Could not parse seam_result.json: {exc}",
        }

    # Unwrap one level if the model echoed {seam_result: {...}}
    if isinstance(seam_result, dict) and list(seam_result.keys()) == ["seam_result"]:
        seam_result = seam_result["seam_result"]

    pr_files: list[dict] = []
    if isinstance(seam_result, dict):
        pr_files = seam_result.get("pr", {}).get("files", [])

    # Context compaction for fix iterations: when review files are present we
    # already know which files have BLOCKER/MAJOR findings.  Files with no
    # findings are truncated to their first few lines so the LLM context stays
    # well below the model's window even for large seams (35+ files).
    _STUB_HEAD = 10   # lines of header to keep for unchanged files
    files_needing_full_content: set[str] = set()
    all_impl_flagged = False
    has_any_review = False

    for review_file in ("skeptical_review.json", "test_review.json", "functional_review.json"):
        rp = Path(run_dir) / review_file
        if not rp.exists():
            continue
        has_any_review = True
        try:
            rv = json.loads(rp.read_text(encoding="utf-8"))
            if isinstance(rv, str):
                rv = json.loads(rv)
            if not isinstance(rv, dict):
                continue
            for finding in rv.get("findings", []):
                sev = finding.get("severity", "").upper()
                if sev not in ("BLOCKER", "MAJOR"):
                    continue
                for key in ("file", "test_file"):
                    p = finding.get(key, "")
                    if p and p not in ("<unknown>", ""):
                        files_needing_full_content.add(p)
                # Functional BLOCKER/MAJOR flags every impl file
                if "source_behavior" in finding:
                    all_impl_flagged = True
        except (OSError, json.JSONDecodeError):
            pass

    files_out: list[dict] = []
    for f in pr_files:
        path = f.get("path", "")
        content = f.get("content", "")
        if not path:
            continue
        # Skip DDD scaffolding stubs (InMemoryRepository etc.) — reviewers should
        # only see LLM-generated code, not generic structural placeholders.
        if f.get("_scaffold"):
            continue

        lines = content.splitlines()
        line_count = len(lines)

        # On fix iterations, truncate files that have no findings so the LLM
        # context stays compact.  Only omit the body — the signature lines let
        # the LLM reason about what the file contains without re-reading it.
        is_test_path = any(
            path.startswith(d) for d in ("src/test/", "tests/", "test/")
        ) or any(path.endswith(s) for s in ("Test.kt", "Tests.kt", "Spec.kt",
                                              "Test.java", "Tests.java", "_test.go",
                                              "_test.py", "test_.py", ".spec.ts", ".test.ts"))
        needs_full = (
            not has_any_review
            or all_impl_flagged
            or path in files_needing_full_content
        )
        if not needs_full and line_count > _STUB_HEAD:
            stub = "\n".join(lines[:_STUB_HEAD])
            stub += f"\n// … ({line_count - _STUB_HEAD} more lines — no findings, omitted to save context)"
            files_out.append({"path": path, "content": stub, "lines": line_count, "truncated": True})
            continue

        files_out.append({
            "path": path,
            "content": content,
            "lines": line_count,
        })

    return {
        "files": files_out,
        "count": len(files_out),
        "seam_name": seam_result.get("seam_name", "") if isinstance(seam_result, dict) else "",
        "target_lang": seam_result.get("target_lang", "") if isinstance(seam_result, dict) else "",
    }


def read_review_feedback(run_dir: str) -> dict:
    """Read consolidated review findings for the Code Writer.

    Reads ``skeptical_review.json``, ``test_review.json``, and
    ``functional_review.json`` from run_dir.  Each file is optional.

    Args:
        run_dir: Path to the current run directory.

    Returns:
        Dict with ``has_feedback`` (bool), ``skeptical_review`` (dict),
        ``test_review`` (dict), ``functional_review`` (dict), and
        ``combined_findings`` (list[str]) — flat human-readable strings such as
        ``"[SKEPTICAL/BLOCKER] file.go:doThing — function body is empty"``.
    """
    run_path = Path(run_dir)
    result: dict = {
        "has_feedback": False,
        "skeptical_review": {},
        "test_review": {},
        "functional_review": {},
        "combined_findings": [],
        "files_with_findings": [],
        "submission_warnings": [],
    }

    def _load_optional(filename: str) -> dict:
        p = run_path / filename
        if not p.exists():
            return {}
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            # Guard against double-serialized strings: the LLM may have echoed
            # the artifact as a JSON string rather than a JSON object, causing
            # _save_artifact to write json.dumps(string) to disk.
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    pass
            return raw if isinstance(raw, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    skeptical = _load_optional("skeptical_review.json")
    test_rev = _load_optional("test_review.json")
    functional = _load_optional("functional_review.json")

    result["skeptical_review"] = skeptical
    result["test_review"] = test_rev
    result["functional_review"] = functional

    combined: list[str] = []

    # Skeptical reviewer findings: {file, symbol, issue, severity}
    for finding in skeptical.get("findings", []):
        sev = finding.get("severity", "MINOR").upper()
        file_part = finding.get("file", "<unknown>")
        sym = finding.get("symbol", "")
        issue = finding.get("issue", "")
        loc = f"{file_part}:{sym}" if sym else file_part
        combined.append(f"[SKEPTICAL/{sev}] {loc} — {issue}")

    # Test reviewer findings: {test_file, test_name, issue, severity}
    for finding in test_rev.get("findings", []):
        sev = finding.get("severity", "MINOR").upper()
        test_file = finding.get("test_file", "<unknown>")
        test_name = finding.get("test_name", "")
        issue = finding.get("issue", "")
        loc = f"{test_file}:{test_name}" if test_name else test_file
        combined.append(f"[TEST/{sev}] {loc} — {issue}")

    # Functional reviewer findings: {source_behavior, issue, severity}
    for finding in functional.get("findings", []):
        sev = finding.get("severity", "MINOR").upper()
        source_behavior = finding.get("source_behavior", "<unknown>")
        issue = finding.get("issue", "")
        combined.append(f"[FUNCTIONAL/{sev}] {source_behavior} — {issue}")

    # Surface submission warnings from seam_result so the Code Writer can see
    # "no test files found" / "no impl files found" without a full review cycle.
    seam_result = _load_optional("seam_result.json")
    submission_warnings: list[str] = []
    if isinstance(seam_result, dict):
        for w in seam_result.get("warnings", []):
            combined.append(f"[SUBMISSION/WARNING] {w}")
            submission_warnings.append(w)

    # When the test review didn't pass because test categories are absent, synthesise
    # explicit BLOCKER entries so the Code Writer receives actionable feedback.
    # Without this, an empty findings list leaves has_feedback=False and the writer
    # regenerates the same code on every iteration without knowing what is missing.
    if test_rev and not test_rev.get("passed", True):
        if not test_rev.get("has_happy_path"):
            combined.append(
                "[TEST/BLOCKER] test suite — no happy-path test present; "
                "add a test for a valid, successful operation with a meaningful assertion"
            )
        if not test_rev.get("has_rule_violation"):
            combined.append(
                "[TEST/BLOCKER] test suite — no rule-violation test present; "
                "add a test that passes invalid input and asserts the expected error or exception"
            )
        if not test_rev.get("has_edge_case"):
            combined.append(
                "[TEST/BLOCKER] test suite — no edge-case test present; "
                "add a test for a boundary value such as zero, empty collection, or maximum value"
            )

    # Collect unique file paths that have BLOCKER/MAJOR findings so the Code
    # Writer knows exactly which files need changes vs. which to preserve intact.
    files_with_findings: set[str] = set()
    for finding in skeptical.get("findings", []):
        if finding.get("severity", "").upper() in ("BLOCKER", "MAJOR"):
            p = finding.get("file", "")
            if p and p != "<unknown>":
                files_with_findings.add(p)
    for finding in test_rev.get("findings", []):
        if finding.get("severity", "").upper() in ("BLOCKER", "MAJOR"):
            p = finding.get("test_file", "")
            if p and p != "<unknown>":
                files_with_findings.add(p)
    for finding in functional.get("findings", []):
        if finding.get("severity", "").upper() in ("BLOCKER", "MAJOR"):
            # Functional findings don't name a generated file; flag all impl files.
            files_with_findings.add("*impl*")
            break

    result["combined_findings"] = combined
    result["files_with_findings"] = sorted(files_with_findings)
    result["submission_warnings"] = submission_warnings
    result["has_feedback"] = bool(combined)

    return result


# ─── submit tools ─────────────────────────────────────────────────────────────

def submit_code_review(
    findings: list,
    passed: bool,
    run_dir: str = "",
) -> dict:
    """Skeptical reviewer submits findings.

    Writes ``skeptical_review.json`` to run_dir.

    Args:
        findings: List of dicts with keys: file (str), symbol (str),
                  issue (str), severity (BLOCKER/MAJOR/MINOR).
        passed:   Whether the review passed.  Forced to False if any BLOCKER
                  or MAJOR finding is present.
        run_dir:  Path to the current run directory.

    Returns:
        Dict with ``findings``, ``passed``, ``severity_counts``, and
        ``review_type`` fields, plus the path of the written file.
    """
    run_dir = run_dir or get_run_dir()
    if not isinstance(findings, list):
        findings = []

    # Normalise finding dicts
    normalised: list[dict] = []
    for f in findings:
        if not isinstance(f, dict):
            continue
        normalised.append({
            "file":     f.get("file", "<unknown>"),
            "symbol":   f.get("symbol", ""),
            "issue":    f.get("issue", ""),
            "severity": f.get("severity", "MINOR").upper(),
        })

    severity_counts = _severity_counts(normalised)

    # Enforce: passed must be False if any BLOCKER or MAJOR
    if _has_blocker_or_major(normalised):
        passed = False

    result: dict = {
        "review_type": "skeptical",
        "findings": normalised,
        "passed": passed,
        "severity_counts": severity_counts,
    }

    try:
        out_path = Path(run_dir) / "skeptical_review.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        result["written_to"] = str(out_path)
    except OSError as exc:
        result["write_error"] = str(exc)

    return result


def submit_test_review(
    findings: list,
    passed: bool,
    has_happy_path: bool = False,
    has_rule_violation: bool = False,
    has_edge_case: bool = False,
    run_dir: str = "",
) -> dict:
    """TDD test reviewer submits findings.

    Writes ``test_review.json`` to run_dir.

    Args:
        findings:          List of dicts with keys: test_file (str),
                           test_name (str), issue (str), severity.
        passed:            Whether the review passed.  Forced to False if any
                           BLOCKER finding is present, or if any required test
                           category is absent.
        has_happy_path:    True if at least one happy-path test exists.
        has_rule_violation: True if at least one rule-violation test exists.
        has_edge_case:     True if at least one edge-case test exists.
        run_dir:           Path to the current run directory.

    Returns:
        Dict with all parameters plus ``severity_counts`` and the path of the
        written file.
    """
    run_dir = run_dir or get_run_dir()
    if not isinstance(findings, list):
        findings = []

    normalised: list[dict] = []
    for f in findings:
        if not isinstance(f, dict):
            continue
        normalised.append({
            "test_file":  f.get("test_file", "<unknown>"),
            "test_name":  f.get("test_name", ""),
            "issue":      f.get("issue", ""),
            "severity":   f.get("severity", "MINOR").upper(),
        })

    # Enforce: passed must be False if any BLOCKER or if a test category is missing
    if _has_blocker(normalised):
        passed = False
    if not (has_happy_path and has_rule_violation and has_edge_case):
        passed = False

    # Fold in the real execution signal (see
    # fitness_runner.run_accumulated_test_execution) — read directly off disk,
    # never as an LLM-supplied parameter. This both avoids an ADK tool-schema
    # footgun (a new required parameter the model omits silently drops the
    # whole tool call) and stops the reviewer's own self-report from being
    # trusted over what the tests actually did when they ran. A seam can no
    # longer pass on static judgment alone while its real tests are failing.
    exec_path = Path(run_dir) / "test_execution.json"
    if exec_path.exists():
        try:
            exec_result = json.loads(exec_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            exec_result = None
        if isinstance(exec_result, dict) and exec_result.get("ran") and not exec_result.get("passed", True):
            passed = False
            detail = (
                (exec_result.get("exec_result") or {}).get("message")
                or exec_result.get("message", "")
            )
            normalised.append({
                "test_file": "<real execution>",
                "test_name": "",
                "issue": f"Real test execution failed: {detail[:500]}",
                "severity": "BLOCKER",
            })

    severity_counts = _severity_counts(normalised)

    result: dict = {
        "review_type":       "test",
        "findings":          normalised,
        "passed":            passed,
        "has_happy_path":    has_happy_path,
        "has_rule_violation": has_rule_violation,
        "has_edge_case":     has_edge_case,
        "severity_counts":   severity_counts,
    }

    try:
        out_path = Path(run_dir) / "test_review.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        result["written_to"] = str(out_path)
    except OSError as exc:
        result["write_error"] = str(exc)

    return result


def submit_functional_review(
    findings: list,
    passed: bool,
    run_dir: str = "",
) -> dict:
    """Functional reviewer submits findings.

    Writes ``functional_review.json`` to run_dir.

    Args:
        findings: List of dicts with keys: source_behavior (str), issue (str),
                  severity (BLOCKER/MAJOR/MINOR).
        passed:   Whether the review passed.  Forced to False if any BLOCKER
                  finding is present.
        run_dir:  Path to the current run directory.

    Returns:
        Dict with ``findings``, ``passed``, ``severity_counts``, and the path
        of the written file.
    """
    run_dir = run_dir or get_run_dir()
    if not isinstance(findings, list):
        findings = []

    normalised: list[dict] = []
    for f in findings:
        if not isinstance(f, dict):
            continue
        normalised.append({
            "source_behavior": f.get("source_behavior", "<unknown>"),
            "issue":           f.get("issue", ""),
            "severity":        f.get("severity", "MINOR").upper(),
        })

    # Enforce: passed must be False if any BLOCKER
    if _has_blocker(normalised):
        passed = False

    # "Does this behave like the source" is unanswerable for code that
    # doesn't even compile — fold in the real test-execution signal too,
    # not just equivalence. Without this, a seam with a real compile/build
    # failure but no test vectors supplied (equivalence_result.json then
    # reads ran:false, passed:true — an honest "nothing to check", not a
    # failure) had nothing forcing Functional Review's own passed=True
    # verdict to be corrected, even though the code cannot run at all.
    exec_path = Path(run_dir) / "test_execution.json"
    if exec_path.exists():
        try:
            exec_result = json.loads(exec_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            exec_result = None
        if isinstance(exec_result, dict) and exec_result.get("ran") and not exec_result.get("passed", True):
            passed = False
            detail = (
                (exec_result.get("exec_result") or {}).get("message")
                or exec_result.get("message", "")
            )
            normalised.append({
                "source_behavior": "<real execution>",
                "issue": f"Cannot assess behaviour — real test execution failed: {detail[:500]}",
                "severity": "BLOCKER",
            })

    # Fold in the real differential-testing signal (see
    # equivalence_tools.run_accumulated_equivalence_check) — read directly
    # off disk, never as an LLM-supplied parameter, for the same reasons
    # submit_test_review folds in test_execution.json: avoids an ADK
    # tool-schema footgun, and stops the reviewer's own self-report from
    # being trusted over what a real vector comparison actually found.
    # "does this behave like it's supposed to" is this reviewer's own stated
    # remit, so this is the natural gate for that signal.
    equiv_path = Path(run_dir) / "equivalence_result.json"
    if equiv_path.exists():
        try:
            equiv_result = json.loads(equiv_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            equiv_result = None
        if isinstance(equiv_result, dict) and equiv_result.get("ran") and not equiv_result.get("passed", True):
            passed = False
            failures = equiv_result.get("failures") or [equiv_result.get("message", "")]
            normalised.append({
                "source_behavior": "<real equivalence check>",
                "issue": "Differential test vector mismatch: " + "; ".join(failures)[:500],
                "severity": "BLOCKER",
            })

    severity_counts = _severity_counts(normalised)

    result: dict = {
        "review_type":     "functional",
        "findings":        normalised,
        "passed":          passed,
        "severity_counts": severity_counts,
    }

    try:
        out_path = Path(run_dir) / "functional_review.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        result["written_to"] = str(out_path)
    except OSError as exc:
        result["write_error"] = str(exc)

    return result
