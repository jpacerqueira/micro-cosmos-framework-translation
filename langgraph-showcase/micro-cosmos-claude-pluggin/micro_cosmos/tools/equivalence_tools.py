"""Semantic Equivalence Agent ("Verifier") — differential testing.

Phase 1 scope, deliberately: target-side only. Given test vectors
(``{"description", "input", "expected_output"}``, normally authored by the
Code Writer alongside its implementation and tests — see
``submit_seam_translation``'s optional ``test_vectors`` parameter in
coder_tools.py), this module invokes the seam's own generated code through a
small, per-language CLI/JSON harness convention and compares the real output
against the expected one with a numeric-tolerant diff.

True source-vs-target differential execution — running the ORIGINAL legacy
code on the same input and comparing live outputs — is NOT built here. It
needs a runnable toolchain per source language (e.g. GnuCOBOL for COBOL
sources, not present anywhere in this codebase or its Dockerfile), which is
a separate, materially larger workstream. What this module proves is
narrower but still genuinely hard to fake: "does the generated code actually
produce what the Code Writer itself said it should for these inputs" — an
LLM reviewer's own optimistic self-report can no longer paper over that.

Harness convention (additive and optional — a seam with no harness file just
has nothing to differentially check, it is never treated as a failure):
    Python -> equivalence_harness.py                  (run directly)
    Java   -> src/main/java/EquivalenceHarness.java    (default package —
              may still `import` the seam's own named-package classes;
              compiled then invoked as a plain class, no build-plugin needed)
    Kotlin -> src/main/kotlin/EquivalenceHarness.kt    (top-level `fun main()`
              — Kotlin's compiler names the facade class EquivalenceHarnessKt;
              compiled+run via a Gradle init script, see _invoke_kotlin)
    C#     -> EquivalenceHarness.cs                    (a class with a
              `static void Main` — may reference other seams' generated
              classes directly, compiled into a throwaway Exe project built
              alongside them; see _invoke_csharp)
Every harness reads exactly one JSON value from stdin (the vector's "input")
and writes exactly one JSON value to stdout (the actual result) — nothing
else on stdout.

Other target languages remain a deliberate, honest no-op (see _INVOKERS) —
invoking a single class/method generically needs either a build-plugin
change to the scaffold or reliable stdin-forwarding through that language's
build tool. This degrades the same way fitness_runner._run_tests degrades
for a missing toolchain: "nothing to execute" is reported honestly, never
silently claimed as a pass or forced to a fail.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from micro_cosmos.tools.fitness_runner import (
    _gradle_cmd,
    _make_world_writable,
    _sandbox_env,
    _sandbox_preexec,
    assemble_accumulated_pr_files,
)

_HARNESS_TIMEOUT = 60  # seconds — a single vector invocation, not a full test suite


# ─── tolerant comparison ────────────────────────────────────────────────────

def _values_match(actual, expected, epsilon: float = 1e-6) -> bool:
    """Structural equality with numeric tolerance.

    Deliberately NOT order-insensitive for lists — most real JSON shapes
    (line items, ordered results) do care about order, and an order-
    insensitive multiset match over lists of dicts is ambiguous (which
    element corresponds to which?) and risks masking a real ordering bug.
    Only numeric values get tolerance; everything else is exact.
    """
    if isinstance(expected, bool) or isinstance(actual, bool):
        return actual is expected
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return abs(float(actual) - float(expected)) <= epsilon
    if isinstance(expected, dict) and isinstance(actual, dict):
        if set(actual.keys()) != set(expected.keys()):
            return False
        return all(_values_match(actual[k], expected[k], epsilon) for k in expected)
    if isinstance(expected, list) and isinstance(actual, list):
        if len(actual) != len(expected):
            return False
        return all(_values_match(a, e, epsilon) for a, e in zip(actual, expected))
    return actual == expected


# ─── per-language harness invocation ────────────────────────────────────────

def _invoke_python(project_root: Path, stdin_data: str) -> tuple[bool, str, str]:
    harness = project_root / "equivalence_harness.py"
    if not harness.exists():
        return False, "", "no equivalence_harness.py present"
    try:
        proc = subprocess.run(
            ["python", "equivalence_harness.py"],
            cwd=str(project_root),
            input=stdin_data,
            capture_output=True,
            text=True,
            timeout=_HARNESS_TIMEOUT,
            env=_sandbox_env(project_root),
            preexec_fn=_sandbox_preexec if os.name == "posix" else None,
        )
    except subprocess.TimeoutExpired:
        return False, "", f"harness timed out after {_HARNESS_TIMEOUT}s"
    if proc.returncode != 0:
        return False, proc.stdout, proc.stderr[:1000] or "harness exited non-zero with no stderr"
    return True, proc.stdout, ""


def _invoke_java(project_root: Path, stdin_data: str) -> tuple[bool, str, str]:
    harness = project_root / "src" / "main" / "java" / "EquivalenceHarness.java"
    if not harness.exists():
        return False, "", "no src/main/java/EquivalenceHarness.java present"

    if (project_root / "pom.xml").exists():
        build_cmd = ["mvn", "-q", "compile"]
        classes_dir = project_root / "target" / "classes"
    elif (project_root / "build.gradle.kts").exists() or (project_root / "build.gradle").exists():
        build_cmd = [_gradle_cmd(project_root)[0], "compileJava", "-q"]
        classes_dir = project_root / "build" / "classes" / "java" / "main"
    else:
        return False, "", "no pom.xml or build.gradle(.kts) found — cannot compile the harness"

    try:
        build = subprocess.run(
            build_cmd, cwd=str(project_root), capture_output=True, text=True,
            timeout=_HARNESS_TIMEOUT, env=_sandbox_env(project_root),
            preexec_fn=_sandbox_preexec if os.name == "posix" else None,
        )
    except subprocess.TimeoutExpired:
        return False, "", f"harness compile timed out after {_HARNESS_TIMEOUT}s"
    except FileNotFoundError:
        return False, "", "Java toolchain (mvn/gradle) not available in this environment"
    if build.returncode != 0:
        return False, "", ("compile failed: " + (build.stdout + build.stderr))[:1000]

    try:
        proc = subprocess.run(
            ["java", "-cp", str(classes_dir), "EquivalenceHarness"],
            cwd=str(project_root),
            input=stdin_data,
            capture_output=True,
            text=True,
            timeout=_HARNESS_TIMEOUT,
            env=_sandbox_env(project_root),
            preexec_fn=_sandbox_preexec if os.name == "posix" else None,
        )
    except subprocess.TimeoutExpired:
        return False, "", f"harness run timed out after {_HARNESS_TIMEOUT}s"
    if proc.returncode != 0:
        return False, proc.stdout, proc.stderr[:1000] or "harness exited non-zero with no stderr"
    return True, proc.stdout, ""


# Gradle init script (see security_tools.py's _maybe_restore_jvm_lockfile for
# the same "inject behavior without touching the project's own build file"
# idiom) that registers a throwaway JavaExec task reusing Gradle's own
# dependency resolution — sourceSets.main.runtimeClasspath correctly includes
# kotlin-stdlib and any other declared dependency without this code needing
# to locate those jars itself. standardOutput is redirected to a file instead
# of left on Gradle's own stdout: Gradle's console output (warnings,
# deprecation notices, first-run banners) cannot be trusted to stay off
# stdout even with -q, which would silently corrupt the "exactly one JSON
# value on stdout" harness contract.
_KOTLIN_INIT_SCRIPT = """\
allprojects { proj ->
    proj.afterEvaluate {
        if (proj.hasProperty('sourceSets')) {
            proj.tasks.register('runEquivalenceHarness', JavaExec) {
                classpath = proj.sourceSets.main.runtimeClasspath
                mainClass = 'EquivalenceHarnessKt'
                standardInput = System.in
                standardOutput = new FileOutputStream(new File(proj.projectDir, '_equivalence_harness_stdout.txt'))
            }
        }
    }
}
"""


def _invoke_kotlin(project_root: Path, stdin_data: str) -> tuple[bool, str, str]:
    """Kotlin's build.gradle.kts already applies the kotlin("jvm") plugin (see
    _project_scaffold_files in coder_tools.py) but has no `application`
    plugin/mainClass configured — there is no `gradle run` entrypoint to
    invoke directly. Confirmed via a real local run (Gradle 9.7.1, JDK 21,
    matching the container's openjdk-21-jdk-headless): Gradle's *daemon* mode
    happened to still forward stdin correctly to a JavaExec task's
    `standardInput = System.in`, but this is exactly the kind of undocumented
    daemon-protocol behavior that has differed across Gradle versions
    historically — --no-daemon is used unconditionally below so this doesn't
    depend on it, at the cost of one throwaway JVM startup per invocation
    (irrelevant next to _HARNESS_TIMEOUT's 60s budget for a single vector).
    """
    harness = project_root / "src" / "main" / "kotlin" / "EquivalenceHarness.kt"
    if not harness.exists():
        return False, "", "no src/main/kotlin/EquivalenceHarness.kt present"
    if not ((project_root / "build.gradle.kts").exists() or (project_root / "build.gradle").exists()):
        return False, "", "no build.gradle(.kts) found — cannot compile the harness"

    init_script = project_root / "_equivalence_init.gradle"
    stdout_file = project_root / "_equivalence_harness_stdout.txt"
    try:
        init_script.write_text(_KOTLIN_INIT_SCRIPT, encoding="utf-8")
    except OSError as exc:
        return False, "", f"failed to write Gradle init script: {exc}"

    gradle_bin = _gradle_cmd(project_root)[0]  # "./gradlew" or "gradle"
    try:
        proc = subprocess.run(
            [gradle_bin, "--no-daemon", "--init-script", str(init_script), "-q", "runEquivalenceHarness"],
            cwd=str(project_root),
            input=stdin_data,
            capture_output=True,
            text=True,
            timeout=_HARNESS_TIMEOUT,
            env=_sandbox_env(project_root),
            preexec_fn=_sandbox_preexec if os.name == "posix" else None,
        )
    except subprocess.TimeoutExpired:
        return False, "", f"harness run timed out after {_HARNESS_TIMEOUT}s"
    except FileNotFoundError:
        return False, "", "Kotlin/Gradle toolchain not available in this environment"
    if proc.returncode != 0:
        detail = (proc.stdout + proc.stderr)[:1000]
        return False, "", detail or "harness exited non-zero with no output"

    try:
        stdout = stdout_file.read_text(encoding="utf-8")
    except OSError as exc:
        return False, "", f"harness ran but its redirected output file could not be read: {exc}"
    return True, stdout, ""


def _invoke_csharp(project_root: Path, stdin_data: str) -> tuple[bool, str, str]:
    """C#'s scaffold (see _project_scaffold_files in coder_tools.py) names
    each seam's .csproj after the Pascal-cased seam name, with no merge logic
    across seams (unlike Kotlin's single, always-merged build.gradle.kts) —
    an accumulated multi-seam project directory routinely contains several
    .csproj files side by side, which makes a bare `dotnet build`/`dotnet
    run` in that directory ambiguous ("this folder contains more than one
    project or solution file"). None of those .csproj files are Exe-typed
    either (the scaffold emits plain libraries).

    Sidestep both problems without touching any of the accumulated project's
    own .csproj files: copy every *.cs file (the harness plus every seam's
    domain code, which the harness may reference directly since they all
    compile into the same throwaway assembly) into an isolated subdirectory,
    alongside one freshly generated Exe-typed .csproj that picks them all up
    via the SDK's own default globbing.
    """
    harness = project_root / "EquivalenceHarness.cs"
    if not harness.exists():
        return False, "", "no EquivalenceHarness.cs present"

    build_root = project_root / "_equivalence_harness_build"
    try:
        for src in project_root.rglob("*.cs"):
            if build_root in src.parents:
                continue
            rel = src.relative_to(project_root)
            dest = build_root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(src.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
    except OSError as exc:
        return False, "", f"failed to assemble harness build directory: {exc}"

    try:
        (build_root / "EquivalenceHarness.csproj").write_text(
            '<Project Sdk="Microsoft.NET.Sdk">'
            "<PropertyGroup>"
            "<OutputType>Exe</OutputType>"
            "<TargetFramework>net8.0</TargetFramework>"
            "<Nullable>enable</Nullable>"
            "<ImplicitUsings>enable</ImplicitUsings>"
            "<InvariantGlobalization>true</InvariantGlobalization>"
            "</PropertyGroup>"
            "</Project>\n",
            encoding="utf-8",
        )
    except OSError as exc:
        return False, "", f"failed to write harness .csproj: {exc}"
    _make_world_writable(build_root)

    try:
        build = subprocess.run(
            ["dotnet", "build", "--nologo", "-v", "minimal"],
            cwd=str(build_root), capture_output=True, text=True,
            timeout=_HARNESS_TIMEOUT, env=_sandbox_env(build_root),
            preexec_fn=_sandbox_preexec if os.name == "posix" else None,
        )
    except subprocess.TimeoutExpired:
        return False, "", f"harness compile timed out after {_HARNESS_TIMEOUT}s"
    except FileNotFoundError:
        return False, "", ".NET toolchain (dotnet) not available in this environment"
    if build.returncode != 0:
        return False, "", ("compile failed: " + (build.stdout + build.stderr))[:1000]

    dll = build_root / "bin" / "Debug" / "net8.0" / "EquivalenceHarness.dll"
    if not dll.exists():
        return False, "", f"build succeeded but expected output was not found at {dll}"

    try:
        proc = subprocess.run(
            ["dotnet", str(dll)],
            cwd=str(build_root),
            input=stdin_data,
            capture_output=True,
            text=True,
            timeout=_HARNESS_TIMEOUT,
            env=_sandbox_env(build_root),
            preexec_fn=_sandbox_preexec if os.name == "posix" else None,
        )
    except subprocess.TimeoutExpired:
        return False, "", f"harness run timed out after {_HARNESS_TIMEOUT}s"
    if proc.returncode != 0:
        return False, proc.stdout, proc.stderr[:1000] or "harness exited non-zero with no stderr"
    return True, proc.stdout, ""


# Lang -> invoker. Absence of an entry means "not wired up yet" — a soft,
# honest no-op (see run_accumulated_equivalence_check), never a failure.
_INVOKERS = {
    "python": _invoke_python,
    "java": _invoke_java,
    "kotlin": _invoke_kotlin,
    "csharp": _invoke_csharp,
}


def _write_equivalence_result(run_path: Path, result: dict) -> None:
    try:
        (run_path / "equivalence_result.json").write_text(
            json.dumps(result, indent=2), encoding="utf-8"
        )
    except OSError:
        pass


def run_accumulated_equivalence_check(run_dir: str, target_lang: str = "") -> dict:
    """Run real differential testing against the full accumulated project and
    persist the result as run_dir/equivalence_result.json.

    This is the Semantic Equivalence Agent's deterministic signal:
    submit_functional_review() (coding_loop_tools.py) reads this file
    directly off disk — never as an LLM-supplied parameter — and
    force-corrects its own `passed` field if a real vector comparison
    failed, mirroring exactly how submit_test_review() consumes
    test_execution.json (fitness_runner.py).

    Returns:
        Dict with ``ran`` (bool — False means nothing to check yet, not a
        failure), ``passed`` (bool), ``vectors_run`` (int), ``failures``
        (list[str]), and ``message`` (str).
    """
    run_path = Path(run_dir)
    seam_result_path = run_path / "seam_result.json"
    result: dict = {
        "ran": False,
        "passed": True,
        "vectors_run": 0,
        "failures": [],
        "message": "No seam_result.json yet — nothing to check.",
    }

    if not seam_result_path.exists():
        _write_equivalence_result(run_path, result)
        return result

    try:
        raw = json.loads(seam_result_path.read_text(encoding="utf-8"))
        if isinstance(raw, str):
            raw = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        result["message"] = f"Could not read seam_result.json: {exc}"
        _write_equivalence_result(run_path, result)
        return result

    if isinstance(raw, dict) and tuple(raw.keys()) == ("seam_result",):
        raw = raw["seam_result"]

    test_vectors = raw.get("test_vectors", []) if isinstance(raw, dict) else []
    if not isinstance(test_vectors, list) or not test_vectors:
        result["message"] = "No test vectors supplied for this seam — nothing to differentially check."
        _write_equivalence_result(run_path, result)
        return result

    pr = raw.get("pr", {}) if isinstance(raw, dict) else {}
    current_files: list[dict] = pr.get("files", []) if isinstance(pr, dict) else []
    accumulated = assemble_accumulated_pr_files(run_dir, current_files)

    lang = (target_lang or raw.get("target_lang", "")).lower()
    invoker = _INVOKERS.get(lang)
    if invoker is None:
        result["message"] = (
            f"Equivalence harness invocation is not yet wired up for '{lang}' — "
            f"{len(test_vectors)} test vector(s) present but not evaluated."
        )
        _write_equivalence_result(run_path, result)
        return result

    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        for f in accumulated:
            rel_path = (f.get("path") or "").lstrip("/")
            if not rel_path or f.get("content") is None:
                continue
            dest = tmp / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(f["content"], encoding="utf-8")

        # The harness subprocess drops privileges to the sandbox UID (see
        # _sandbox_preexec) but this directory was just created by the
        # caller's own (typically root) identity — without this, every
        # invoker below fails outright with a permission error before a
        # single vector runs. Same fix fitness_runner._run_tests already
        # applies for the Test Agent's own execution path.
        _make_world_writable(tmp)

        failures: list[str] = []
        vectors_run = 0
        harness_unavailable_reason = ""
        for vector in test_vectors:
            if not isinstance(vector, dict) or "input" not in vector or "expected_output" not in vector:
                continue
            stdin_data = json.dumps(vector["input"])
            ok, stdout, error = invoker(tmp, stdin_data)
            if not ok:
                harness_unavailable_reason = error
                break  # a broken/missing harness affects every vector identically
            vectors_run += 1
            desc = vector.get("description", f"vector {vectors_run}")
            try:
                actual = json.loads(stdout.strip())
            except (json.JSONDecodeError, ValueError):
                failures.append(f"{desc}: harness stdout was not valid JSON: {stdout[:200]!r}")
                continue
            if not _values_match(actual, vector["expected_output"]):
                failures.append(
                    f"{desc}: expected {vector['expected_output']!r}, got {actual!r}"
                )

    if vectors_run == 0 and harness_unavailable_reason:
        result["message"] = f"Could not run the equivalence harness: {harness_unavailable_reason}"
        _write_equivalence_result(run_path, result)
        return result

    result = {
        "ran": True,
        "passed": not failures,
        "vectors_run": vectors_run,
        "failures": failures,
        "message": (
            f"{vectors_run - len(failures)}/{vectors_run} vector(s) matched."
            if not failures else
            f"{len(failures)}/{vectors_run} vector(s) mismatched."
        ),
    }
    _write_equivalence_result(run_path, result)
    return result
