"""Fitness-function runner — the executable architecture layer.

Runs two classes of checks:

1. Spec-based rules from the TNAS fitness_suite (e.g. no float on monetary fields).
2. Real compilation and test execution: files are written to a temp directory and the
   language toolchain is invoked. If the toolchain is not available the check is skipped
   with a warning rather than a hard failure, so the pipeline is still usable in
   environments that lack a full SDK.
"""

from __future__ import annotations

import json
import os
import re
import resource
import subprocess
import tempfile
from pathlib import Path


# ─── language detection ───────────────────────────────────────────────────────

_EXT_TO_LANG: dict[str, str] = {
    ".go":   "go",
    ".java": "java",
    ".py":   "python",
    ".ts":   "typescript",
    ".cs":   "csharp",
    ".kt":   "kotlin",
    ".rs":   "rust",
    ".scala":"scala",
    ".swift":"swift",
}

# Commands to run when the toolchain is present. Evaluated after files are
# written to a temp directory; cwd is set to that directory.
# "kotlin" here is a placeholder — no scaffold generator ever emits a gradlew
# wrapper script, so this entry is never used verbatim. See _run_tests, which
# resolves the real Gradle command (./gradlew if present, else the `gradle`
# CLI installed in the image) the same way security_tools.py's Trivy
# dependency-lock restore already does for Java/Kotlin.
_TEST_COMMANDS: dict[str, list[str]] = {
    "go":         ["go", "test", "./..."],
    "python":     ["python", "-m", "pytest", "--tb=short", "-q"],
    # "-q" is not a recognised dotnet-CLI verbosity flag (confirmed via
    # `dotnet test --help`) — silently broke every fresh build under this
    # SDK, failing with an opaque "Building target
    # 'GenerateTargetFrameworkMonikerAttribute' completely" MSBuild error
    # before a single test ever ran. "-v minimal" is the correct flag and
    # still preserves per-test assertion failure detail (unlike "-v quiet",
    # which drops it) — verified against a real xUnit failure.
    "csharp":     ["dotnet", "test", "--nologo", "-v", "minimal"],
    # "kotlin" is deliberately absent — _run_tests always overwrites this via
    # _gradle_cmd(tmp) before use (a bare "gradle test -q" isn't reliable,
    # see _gradle_cmd's own docstring), so any value here would be dead code.
    # A key still needs to exist so _TEST_COMMANDS.get("kotlin") doesn't
    # short-circuit into the "no test command configured" skip path.
    "kotlin":     [],
    "rust":       ["cargo", "test", "--quiet"],
    "scala":      ["sbt", "test"],
    "swift":      ["swift", "test"],
    # Java and TypeScript need a build file to be present; handled specially below.
    "java":       ["mvn", "test", "-q"],
    "typescript": ["npx", "--yes", "jest", "--passWithNoTests"],
}

_JAVA_MVN_CMD = ["mvn", "test", "-q"]


def _gradle_cmd(tmp: Path) -> list[str]:
    """Resolve the real Gradle invocation for a temp project directory.

    Mirrors security_tools.py's _maybe_restore_jvm_lockfile: prefer the
    project's own wrapper script if present, else the `gradle` CLI installed
    in the image. No scaffold generator emits a gradlew wrapper today, so
    this almost always resolves to the `gradle` CLI branch — but honouring
    an existing wrapper is still correct if one is ever generated.
    """
    return ["./gradlew", "test", "-q"] if (tmp / "gradlew").exists() else ["gradle", "test", "-q"]

_TEST_TIMEOUT = 120  # seconds

# ─── Tier-1 sandboxing (defense-in-depth, NOT a real security boundary) ───────
#
# This subprocess runs arbitrary LLM-generated code inside the same shared
# container as the orchestrator itself — no Docker-in-Docker, no
# gVisor/Firecracker/nsjail, no network egress restriction. The hardening
# below (minimal env, resource limits, privilege drop) narrows the blast
# radius of a broken or malicious generated test but does not eliminate it.
# A genuinely isolated boundary needs a separate, dedicated execution
# service (tracked as a follow-up, not built here).

_SANDBOX_UID = 10001  # must match the "sandboxrunner" user created in the Dockerfile
# The Dockerfile creates sandboxrunner with --create-home specifically so a
# build tool's own dependency cache (Maven's ~/.m2/repository above all) can
# accumulate across seams/TDD iterations instead of re-downloading from
# Maven Central on every single call. That only actually happens if HOME
# points here — pointing it at the per-call ephemeral tmp dir instead (as an
# earlier version of this code did) silently defeated the whole point of
# --create-home, since that directory is deleted the moment the call ends.
_SANDBOX_HOME = Path("/home/sandboxrunner")

# Generous multiplier over the wall-clock timeout — bounds runaway/fork-bomb
# CPU consumption without false-failing a legitimate multi-threaded
# Gradle/Maven/dotnet build.
_SANDBOX_MAX_CPU_SECONDS = _TEST_TIMEOUT * 4
# Per-UID, system-wide (Linux RLIMIT_NPROC semantics) — well above what any
# single legitimate test run spawns, but shared across concurrent seams/runs
# on the same container instance, so this can rarely false-fail under heavy
# concurrent load. Tier 2 (a dedicated, single-concurrency execution service)
# is the real fix for that; this is best-effort only.
_SANDBOX_MAX_PROCESSES = 512
_SANDBOX_MAX_OPEN_FILES = 1024
# RLIMIT_AS (virtual address space) is deliberately NOT used here — confirmed
# via a real container run that a 4 GiB cap reliably crashes the JVM with
# "insufficient memory for the Java Runtime Environment... Native memory
# allocation (malloc) failed" before a single test executes. JVMs (and to a
# lesser extent .NET) reserve virtual address space far in excess of what
# they actually resident-use (heap regions, metaspace, code cache, per-thread
# stacks), so any RLIMIT_AS cap tight enough to matter as a memory-bomb
# defense is also tight enough to break ordinary JVM startup. This also
# silently no-ops on macOS (setrlimit raises ValueError there), which is
# exactly why this was only caught by testing inside the real Linux
# container, not on a macOS dev machine. A real memory-bomb defense belongs
# at the Tier-2 container/cgroup level (a resident-memory limit, not a
# virtual-address-space one) — see the module docstring above.

# Env vars a test/build toolchain legitimately needs. Deliberately NOT
# inherited wholesale from the parent process — the orchestrator's own
# environment carries secrets (LLM API keys, session secret, demo password,
# GCP credentials) that generated test code has no legitimate reason to see.
_SANDBOX_ENV_ALLOWLIST = (
    "PATH", "HOME", "LANG", "LC_ALL", "TMPDIR",
    "JAVA_HOME", "GRADLE_HOME", "MAVEN_HOME", "DOTNET_ROOT",
    "GOPATH", "GOCACHE", "GOROOT", "GOFLAGS",
    "CARGO_HOME", "RUSTUP_HOME",
    "NODE_OPTIONS", "NPM_CONFIG_CACHE",
)


def _sandbox_env(tmp: Path) -> dict[str, str]:
    """Minimal environment for a test-execution subprocess — see _SANDBOX_ENV_ALLOWLIST.

    HOME is force-set, not defaulted — the parent process (running as root)
    always already has HOME set (e.g. /root), so `setdefault` would never
    actually redirect it.

    Only inside the real container (root, about to drop to sandboxrunner —
    same condition _sandbox_preexec itself gates on) does HOME point at
    _SANDBOX_HOME, sandboxrunner's own real, persistent home directory
    (Dockerfile: `useradd --create-home`) — deliberately NOT the same as
    tmp (the per-call project working directory): tmp is deleted the moment
    this call ends, so a build tool that trusts $HOME for its own
    cache/repository location (e.g. Maven's ~/.m2/repository) would silently
    lose that cache every single call if HOME pointed there instead,
    defeating the Dockerfile's own --create-home, which exists specifically
    so this cache can persist across seams/TDD iterations. Outside the
    container (local dev/CI, already unprivileged — no real sandboxrunner
    UID/home exists there at all) HOME falls back to tmp, the pre-existing
    behaviour, rather than creating an unrelated real path on whoever's
    machine this happens to run on.
    TMPDIR always uses the per-call tmp — genuine scratch space is
    correctly ephemeral, unlike a dependency cache.
    """
    env = {k: v for k, v in os.environ.items() if k in _SANDBOX_ENV_ALLOWLIST}
    if os.name == "posix" and hasattr(os, "getuid") and os.getuid() == 0:
        _SANDBOX_HOME.mkdir(parents=True, exist_ok=True)
        env["HOME"] = str(_SANDBOX_HOME)
    else:
        env["HOME"] = str(tmp)
    env["TMPDIR"] = str(tmp)
    return env


def _sandbox_preexec() -> None:
    """Best-effort resource limits + privilege drop, run in the forked child
    before exec(). Each limit is applied independently so a constant missing
    on a given platform (e.g. RLIMIT_NPROC is not always present) doesn't
    skip the rest."""
    for _name, _value in (
        ("RLIMIT_CPU", _SANDBOX_MAX_CPU_SECONDS),
        ("RLIMIT_NPROC", _SANDBOX_MAX_PROCESSES),
        ("RLIMIT_NOFILE", _SANDBOX_MAX_OPEN_FILES),
    ):
        _limit = getattr(resource, _name, None)
        if _limit is None:
            continue
        try:
            resource.setrlimit(_limit, (_value, _value))
        except (ValueError, OSError):
            pass

    # Drop root privileges for this subprocess specifically (not the whole
    # container, which would break Gradle/dotnet's own writable-HOME
    # assumptions elsewhere). Only meaningful inside the shipped container,
    # which runs as root — a no-op in local dev/CI, which already runs
    # unprivileged.
    if hasattr(os, "getuid") and os.getuid() == 0:
        try:
            os.setgroups([])
            os.setgid(_SANDBOX_UID)
            os.setuid(_SANDBOX_UID)
        except OSError:
            pass


def _make_world_writable(root: Path) -> None:
    """Grant the sandbox UID ownership of everything under root.

    The temp directory is created by the (root) caller before the sandboxed
    subprocess UID (see _sandbox_preexec) takes over, so without this the
    dropped-privilege process cannot read the source files or write build
    artifacts (target/, build/, node_modules/, etc.) into it.

    chown to _SANDBOX_UID specifically, not a blanket chmod 0o777 — this is
    an ephemeral, container-local temp directory deleted immediately after
    the run, so the practical exposure either way is small, but 0o777 grants
    every user/process in the container write access, not just the one that
    actually needs it. If anything else ever shares this container, chown
    doesn't hand it a write path into another run's working tree for free.
    """
    try:
        os.chown(root, _SANDBOX_UID, _SANDBOX_UID)
        for p in root.rglob("*"):
            try:
                os.chown(p, _SANDBOX_UID, _SANDBOX_UID)
            except OSError:
                pass
    except OSError:
        pass

# Pre-compiled spec-check patterns (used inside _check_spec per TDD iteration).
_RE_INFRA = re.compile(
    r"(?:import|require|use)\s+.*?(?:database|jdbc|\.sql|orm|mongo|redis|kafka|HttpClient|RestTemplate|DataSource)",
    re.IGNORECASE,
)
_RE_DOMAIN_PATH = re.compile(r"[/\\]domain[/\\]|[/\\]core[/\\]", re.IGNORECASE)
_RE_CMD = re.compile(
    r"(?:fun|public\s+\w+|def)\s+(?:handle|execute|dispatch|process)\w*\s*\([^)]*\)\s*(?::\s*(\w+))?",
    re.IGNORECASE,
)
_RE_DIRECT_STATE = re.compile(r"\.\s*(?:status|state)\s*=[^=>]", re.IGNORECASE)
_RE_SM_PATH = re.compile(r"(?:state.?machine|statemachine|fsm)", re.IGNORECASE)
_RE_DB = re.compile(
    r"(?:SELECT\s|INSERT\s|UPDATE\s|DELETE\s|executeQuery|executeUpdate|\.execute\(|\.query\(|cursor\.execute)",
    re.IGNORECASE,
)
_RE_REPO_PATH = re.compile(r"(?:repository|adapter|repo|dao|store)", re.IGNORECASE)


def _detect_lang(pr_files: list[dict]) -> str | None:
    exts = {Path(f["path"]).suffix for f in pr_files if f.get("path")}
    for ext, lang in _EXT_TO_LANG.items():
        if ext in exts:
            return lang
    return None


def _run_tests(lang: str, tmp: Path) -> dict:
    """Write no files (caller does that); run the test command; return a result dict."""
    cmd = _TEST_COMMANDS.get(lang)
    if cmd is None:
        return {"function_id": f"test_suite_{lang}", "passed": True,
                "message": f"No test command configured for {lang}; skipping."}

    # Kotlin always builds via Gradle — resolve the real invocation now that a
    # bare hardcoded "./gradlew" is not reliable (see _gradle_cmd's docstring).
    if lang == "kotlin":
        cmd = _gradle_cmd(tmp)

    # Java: prefer Gradle if build.gradle.kts / build.gradle present
    if lang == "java":
        if (tmp / "build.gradle.kts").exists() or (tmp / "build.gradle").exists():
            cmd = _gradle_cmd(tmp)
        elif not (tmp / "pom.xml").exists():
            return {"function_id": "test_suite_java", "passed": True,
                    "message": "No pom.xml or build.gradle found; skipping Java test run."}

    _make_world_writable(tmp)
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(tmp),
            capture_output=True,
            text=True,
            timeout=_TEST_TIMEOUT,
            env=_sandbox_env(tmp),
            preexec_fn=_sandbox_preexec if os.name == "posix" else None,
        )
        output = (proc.stdout + proc.stderr).strip()
        # pytest's exit code 5 means "no tests collected" — unlike `go test`/
        # `cargo test`/`mvn test` (which exit 0 with zero tests), pytest
        # treats an empty collection as an error. A PR fragment with no test
        # files of its own (e.g. this fitness suite checking non-test source
        # only) has nothing to vacuously fail — treat it the same as the
        # "toolchain not available" skip path below, not a real failure.
        if lang == "python" and proc.returncode == 5:
            return {
                "function_id": f"test_suite_{lang}",
                "passed": True,
                "message": "No tests collected; nothing to execute.",
            }
        test_passed = proc.returncode == 0
        return {
            "function_id": f"test_suite_{lang}",
            "passed": test_passed,
            "message": output[:3000] if output else ("Tests passed." if test_passed else "Tests failed with no output."),
        }
    except subprocess.TimeoutExpired:
        return {
            "function_id": f"test_suite_{lang}",
            "passed": False,
            "message": f"Test execution timed out after {_TEST_TIMEOUT}s.",
        }
    except FileNotFoundError:
        # Toolchain not installed — skip rather than hard-fail.
        return {
            "function_id": f"test_suite_{lang}",
            "passed": True,
            "message": f"{lang} toolchain not available in this environment; skipping test execution.",
        }


# ─── spec-based checks ────────────────────────────────────────────────────────

def _check_spec(fn: dict, pr_files: list[dict]) -> dict:
    """Evaluate a single TNAS fitness function spec against pr_files."""
    passed = True
    message = "OK"
    spec = fn.get("spec", "")

    if "no_primitive_type_on_field_role:monetary" in spec:
        _BAD = ["double amount", "float amount", "float money", "double money",
                "float64 Amount", "float32 Amount", "float64 amount", "float32 amount"]
        for f in pr_files:
            if any(bad in f.get("content", "") for bad in _BAD):
                passed = False
                message = f"Monetary field uses a primitive float type in {f['path']}"
                break

    elif "no_direct_dependency:domain_core,infrastructure" in spec:
        for f in pr_files:
            if _RE_DOMAIN_PATH.search(f.get("path", "")) and _RE_INFRA.search(f.get("content", "")):
                passed = False
                message = f"Domain file {f['path']} imports infrastructure directly"
                break

    elif "command_return_type_in:void,DomainEvent" in spec:
        _OK_RETURNS = {"void", "None", "Unit", "()", ""}
        for f in pr_files:
            for m in _RE_CMD.finditer(f.get("content", "")):
                ret = (m.group(1) or "").strip()
                if ret and ret not in _OK_RETURNS and not ret.endswith("Event"):
                    passed = False
                    message = (
                        f"Command method returns {ret!r} in {f['path']} — "
                        "expected void or DomainEvent"
                    )
                    break
            if not passed:
                break

    elif "state_transition_via:state_machine" in spec:
        for f in pr_files:
            if _RE_SM_PATH.search(f.get("path", "")):
                continue
            if _RE_DIRECT_STATE.search(f.get("content", "")):
                passed = False
                message = (
                    f"Direct state field assignment in {f['path']} — "
                    "transitions should go via the state machine"
                )
                break

    elif "no_database_access_outside:repository_adapter" in spec:
        for f in pr_files:
            if not _RE_REPO_PATH.search(f.get("path", "")) and _RE_DB.search(f.get("content", "")):
                passed = False
                message = f"Database access outside repository/adapter in {f['path']}"
                break

    return {"function_id": fn["id"], "passed": passed, "message": message}


# ─── public API ───────────────────────────────────────────────────────────────

def run_fitness_suite(
    suite_json: dict,
    pr_files: list[dict],
) -> dict:
    """Run the fitness suite against a candidate PR.

    Args:
        suite_json: Serialised FitnessSuite from the TNAS.
        pr_files: List of {path, content} dicts produced by the Coder Agent.

    Returns:
        Dict with keys ``passed`` (bool), ``results`` (list of per-check dicts),
        and ``exec_result`` (the test execution result, or None if skipped).
    """
    # ── 1. spec-based checks ──────────────────────────────────────────────────
    spec_results: list[dict] = []
    functions = suite_json.get("functions", [])
    for fn in functions:
        spec_results.append(_check_spec(fn, pr_files))

    blocking_specs_pass = all(
        r["passed"]
        for r, fn in zip(spec_results, suite_json.get("functions", []))
        if fn.get("severity") == "BLOCKING"
    )

    # ── 2. real test execution ────────────────────────────────────────────────
    exec_result: dict | None = None
    lang = _detect_lang(pr_files)
    if lang and pr_files:
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            for f in pr_files:
                if not f.get("path") or f.get("content") is None:
                    continue
                dest = tmp / f["path"].lstrip("/")
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(f["content"], encoding="utf-8")
            exec_result = _run_tests(lang, tmp)

    exec_passed = exec_result["passed"] if exec_result else True
    all_passed = blocking_specs_pass and exec_passed

    return {
        "passed": all_passed,
        "results": spec_results,
        "exec_result": exec_result,
    }


# ─── accumulated-project test execution (the Test Agent) ──────────────────────
#
# run_fitness_suite() above only ever sees the current seam's own files — fine
# for spec-based checks, which are about this seam's own hygiene, but not
# enough to actually build/run tests, since a seam's files routinely reference
# types/build-file dependencies introduced by an earlier seam. The functions
# below assemble the FULL accumulated project (every prior seam already
# materialized to disk, overlaid with the current seam's in-flight files) so
# real test execution sees what will actually ship.

def assemble_accumulated_pr_files(run_dir: str, current_pr_files: list[dict]) -> list[dict]:
    """Merge the current seam's files on top of every prior seam's already-
    materialized output (runs/{run_id}/reports/{proj_dir}/), so real test
    execution sees the whole accumulated project rather than just this seam's
    diff. Build-file collisions (pom.xml, package.json, etc.) are merged via
    the same logic write_output_files() uses, rather than one seam's build
    file silently overwriting another's.

    Deliberately NOT used for the static spec checks in run_fitness_suite()
    above — those stay scoped to the current seam's own files, since they're
    about this seam's own code hygiene and re-running them against the whole
    accumulated project would re-flag already-reviewed prior seams on every
    iteration. Only real execution needs this full accumulated view.
    """
    from micro_cosmos.tools.coder_tools import _dedup_declarations
    from micro_cosmos.tools.writer_tools import _BUILD_FILE_NAMES, _merge_build_file

    run_path = Path(run_dir)
    canonical_file = run_path / "reports" / "project_dir.txt"

    accumulated: dict[str, str] = {}
    if canonical_file.exists():
        proj_dir = canonical_file.read_text(encoding="utf-8").strip()
        project_root = run_path / "reports" / proj_dir
        if proj_dir and project_root.is_dir():
            for p in project_root.rglob("*"):
                if not p.is_file():
                    continue
                try:
                    accumulated[str(p.relative_to(project_root))] = p.read_text(
                        encoding="utf-8", errors="replace"
                    )
                except OSError:
                    continue
    # If project_dir.txt doesn't exist yet, there is nothing to accumulate —
    # driver.py writes it once, before any seam's TDD loop runs, so its
    # absence here only happens on the (defensive) best-effort write failure
    # path, not in normal operation.

    for f in current_pr_files:
        rel_path = (f.get("path") or "").lstrip("/")
        if not rel_path or f.get("content") is None:
            continue
        content = _dedup_declarations(f["content"], rel_path)
        existing = accumulated.get(rel_path)
        if existing is not None and Path(rel_path).name in _BUILD_FILE_NAMES:
            try:
                content = _merge_build_file(existing, content, Path(rel_path).name)
            except Exception:
                pass  # merge failed — fall through to plain overwrite, same as write_output_files
        accumulated[rel_path] = content

    return [{"path": path, "content": content} for path, content in accumulated.items()]


def _write_test_execution_result(run_path: Path, result: dict) -> None:
    try:
        (run_path / "test_execution.json").write_text(
            json.dumps(result, indent=2), encoding="utf-8"
        )
    except OSError:
        pass


def run_accumulated_test_execution(run_dir: str, target_lang: str = "") -> dict:
    """Run real per-language tests against the full accumulated project and
    persist the result as run_dir/test_execution.json.

    This is the deterministic Test Agent signal: submit_test_review() (see
    coding_loop_tools.py) reads this file directly off disk — never as an
    LLM-supplied parameter — and force-corrects its own `passed` field if
    real execution failed, so a seam can no longer pass the TDD loop on
    static judgment alone while its real tests are actually failing.

    Args:
        run_dir: Path to the current run directory (contains seam_result.json).
        target_lang: Target language identifier — used only for the result's
            own metadata/logging; language detection itself is driven by the
            actual file extensions present, same as run_fitness_suite().

    Returns:
        Dict with ``ran`` (bool — False means nothing to execute yet, not a
        failure), ``passed`` (bool), ``message`` (str), and ``exec_result``
        (the raw per-test-command result, or None).
    """
    run_path = Path(run_dir)
    seam_result_path = run_path / "seam_result.json"
    result: dict = {
        "ran": False,
        "passed": True,
        "message": "No seam_result.json yet — nothing to execute.",
        "target_lang": target_lang,
        "exec_result": None,
    }

    if not seam_result_path.exists():
        _write_test_execution_result(run_path, result)
        return result

    try:
        raw = json.loads(seam_result_path.read_text(encoding="utf-8"))
        if isinstance(raw, str):
            # ADK sometimes double-encodes: the saved value is a JSON string
            # whose decoded value is the actual dict (same as writer_tools.py).
            raw = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        result["message"] = f"Could not read seam_result.json: {exc}"
        _write_test_execution_result(run_path, result)
        return result

    if isinstance(raw, dict) and tuple(raw.keys()) == ("seam_result",):
        raw = raw["seam_result"]

    pr = raw.get("pr", {}) if isinstance(raw, dict) else {}
    current_files: list[dict] = pr.get("files", []) if isinstance(pr, dict) else []
    if not current_files:
        result["message"] = "seam_result.json has no pr.files — nothing to execute."
        _write_test_execution_result(run_path, result)
        return result

    accumulated = assemble_accumulated_pr_files(run_dir, current_files)
    lang = _detect_lang(accumulated) or _detect_lang(current_files)
    if not lang:
        result["message"] = (
            f"Could not detect a supported language from generated files "
            f"(target_lang={target_lang!r})."
        )
        _write_test_execution_result(run_path, result)
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
        exec_result = _run_tests(lang, tmp)

    result = {
        "ran": True,
        "passed": bool(exec_result.get("passed", True)),
        "message": exec_result.get("message", ""),
        "target_lang": target_lang,
        "exec_result": exec_result,
    }
    _write_test_execution_result(run_path, result)
    return result
