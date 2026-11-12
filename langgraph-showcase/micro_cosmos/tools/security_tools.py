"""Security tools for the Security Agent.

Six tools are available to the LLM:

  scan_source_for_security  — deterministic regex scan; each finding includes a code
                               snippet so the LLM can confirm/dismiss without reading
                               every file.
  read_file_snippet         — read N lines of context around a specific line number;
                               used to investigate a finding in its surrounding code.
  search_in_source          — case-insensitive full-text search across source files;
                               used to discover patterns the LLM suspects but that the
                               regex scanner did not catch.
  read_manifest_files       — read dependency manifests (requirements.txt, pom.xml,
                               package.json, Dockerfile, .env*, …); used for
                               supply-chain and hardcoded-secret auditing.
  read_trivy_report         — read the Trivy filesystem scan results (CVEs in
                               dependencies) saved by the pipeline before the LLM runs.
  submit_security_findings  — validate and store the agent's completed analysis as the
                               security_report artifact.

Pipeline-only (not given to LLM):
  run_trivy_scan            — run Trivy as a subprocess, save trivy_report.json.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Optional

from micro_cosmos import diagnostics

_VALID_SEVERITIES = {"CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"}
_VALID_CATEGORIES = {
    "INJECTION", "AUTH", "CRYPTO", "SECRETS", "VALIDATION",
    "EXPOSURE", "DESERIALIZATION", "PATH", "SSRF", "SUPPLY_CHAIN", "OTHER",
}

# (pattern_id, severity, category, cwe_id, regex, remediation)
_SECURITY_PATTERNS: list[tuple[str, str, str, str, re.Pattern, str]] = [
    (
        "HARDCODED_SECRET",
        "HIGH",
        "SECRETS",
        "CWE-798",
        re.compile(
            r'(?i)(password|passwd|secret|api[_-]?key|auth[_-]?token|access[_-]?key)'
            r'\s*[=:]\s*["\'][^"\']{4,}["\']',
        ),
        "Move credentials to environment variables or a secrets manager. "
        "Never commit secrets to source control.",
    ),
    (
        "SQL_CONCAT",
        "HIGH",
        "INJECTION",
        "CWE-89",
        re.compile(
            r'(?i)(executeQuery|execute|prepareStatement|createQuery|createNativeQuery'
            r'|ExecuteReader|ExecuteNonQuery|ExecuteScalar|FromSqlRaw|ExecuteSqlRaw)'
            r'\s*\(\s*["\'].*["\']?\s*\+'
            # ADO.NET commonly builds SQL by assigning .CommandText rather than
            # passing it straight into a call — a separate alternative since the
            # method-call shape above doesn't match a property assignment.
            r'|CommandText\s*=\s*["\'][^"\']*["\']\s*\+',
        ),
        "Use parameterised queries or an ORM. Never concatenate user input into SQL strings.",
    ),
    (
        "EVAL_EXEC",
        "HIGH",
        "INJECTION",
        "CWE-78",
        re.compile(
            r'(?i)\b(eval|exec)\s*\(|Runtime\.getRuntime\(\)\.exec'
            r'|subprocess\.(call|run|Popen)\s*\(.*shell\s*=\s*True',
        ),
        "Avoid eval/exec with user-controlled input. Use allow-listed commands "
        "or subprocess with argument lists instead of shell=True.",
    ),
    (
        "WEAK_HASH_CRYPTO",
        "MEDIUM",
        "CRYPTO",
        "CWE-916",
        re.compile(
            r'(?i)(MessageDigest\.getInstance\s*\(\s*["\']MD5|MessageDigest\.getInstance\s*\(\s*["\']SHA-?1'
            r'|hashlib\.(md5|sha1)\s*\(|new\s+MD5Digest\(\)|CryptoJS\.MD5'
            r'|MD5\.Create\s*\(\)|SHA1\.Create\s*\(\)|MD5CryptoServiceProvider|SHA1CryptoServiceProvider)',
        ),
        "Replace MD5/SHA-1 with SHA-256 or Argon2 for password hashing and SHA-256+ for data integrity.",
    ),
    (
        "INSECURE_RANDOM",
        "MEDIUM",
        "CRYPTO",
        "CWE-330",
        re.compile(
            r'(?i)(Math\.random\s*\(\)|random\.random\s*\(\)|new\s+Random\s*\(\)'
            r'|System\.currentTimeMillis\s*\(\))\s*(?=[^;]{0,60}(token|secret|key|session|nonce|csrf))',
        ),
        "Use a cryptographically secure random generator (SecureRandom, secrets.token_bytes, "
        "crypto.randomBytes) for security-sensitive values.",
    ),
    (
        "PATH_TRAVERSAL",
        "MEDIUM",
        "PATH",
        "CWE-22",
        re.compile(
            r'(?i)(new\s+File\s*\(.*getParam|new\s+File\s*\(.*getHeader'
            r'|\.\./|\.\.\\'
            r'|Paths\.get\s*\(.*request\.|path\.join\s*\(.*req\.)',
        ),
        "Validate and canonicalise all user-supplied file paths. Use Path.resolve() "
        "and check the result is within the expected base directory.",
    ),
    (
        "UNSAFE_DESERIALIZATION",
        "HIGH",
        "DESERIALIZATION",
        "CWE-502",
        re.compile(
            r'(?i)(ObjectInputStream\s*\(|pickle\.loads\s*\(|yaml\.load\s*\((?!.*Loader=)'
            r'|BinaryFormatter|NetDataContractSerializer|JsonConvert\.DeserializeObject.*Type\.GetType)',
        ),
        "Avoid deserialising untrusted data. Use safe alternatives: Jackson with type restrictions, "
        "json.loads (Python), or YAML SafeLoader. Never deserialise arbitrary types.",
    ),
    (
        "DEBUG_EXPOSURE",
        "LOW",
        "EXPOSURE",
        "CWE-215",
        re.compile(
            # ["\']?...["\']? around true: the bare debug=true form (Django-style)
            # doesn't have quotes, but ASP.NET's Web.config attribute syntax
            # (debug="true") does — \s* alone never consumed the quote character,
            # so this previously missed that form entirely, not just for C#.
            r'(?i)(debug\s*=\s*["\']?true["\']?'
            r'|management\.endpoints\.web\.exposure\.include\s*=\s*\*'
            r'|server\.error\.include-stacktrace\s*=\s*always'
            r'|UseDeveloperExceptionPage\s*\(\s*\))',
        ),
        "Disable debug mode and restrict actuator/diagnostic endpoints in production.",
    ),
    (
        "MISSING_AUTH_ANNOTATION",
        "MEDIUM",
        "AUTH",
        "CWE-862",
        # CAVEAT (documented, not hidden — same discipline as INSECURE_RANDOM's
        # heuristic note above): ASP.NET Core commonly puts [Authorize] on the
        # CONTROLLER CLASS (covering every action), not per-action like Spring's
        # @PreAuthorize. A nearby-only lookahead can't see a class-level
        # attribute declared 50+ lines above an action method, so this pattern
        # is more prone to false positives for C# than for the Java/Spring case
        # it was originally written for. Treat any C# finding here as a
        # heads-up to verify, not a confirmed gap.
        re.compile(
            r'(?i)(@(Get|Post|Put|Delete|Patch)Mapping|@RequestMapping|\[Http(Get|Post|Put|Delete|Patch)\])'
            r'(?![\s\S]{0,200}(@(PreAuthorize|Secured|RolesAllowed|Authorize)|\[Authorize))',
        ),
        "Ensure all controller endpoints are protected with explicit authorisation annotations "
        "(@PreAuthorize, @Secured, [Authorize], or equivalent).",
    ),
    (
        "SSRF_CANDIDATE",
        "HIGH",
        "SSRF",
        "CWE-918",
        re.compile(
            r'(?i)(new\s+URL\s*\(.*getParam|HttpClient.*execute\s*\(.*getParam'
            r'|requests\.(get|post)\s*\(.*request\.'
            r'|fetch\s*\(.*req\.|axios\.(get|post)\s*\(.*req\.'
            r'|HttpClient[\s\S]{0,40}(GetAsync|PostAsync|PutAsync|DeleteAsync|SendAsync)\s*\(.*Request\.)',
        ),
        "Validate and allowlist URLs before making outbound HTTP requests. "
        "Never forward user-supplied URLs directly to internal services.",
    ),
    # ── Python web frameworks ────────────────────────────────────────────────
    (
        "FLASK_SSTI",
        "HIGH",
        "INJECTION",
        "CWE-94",
        re.compile(r'\brender_template_string\s*\('),
        "render_template_string() with user-controlled content causes SSTI. "
        "Use render_template() with static template files instead.",
    ),
    (
        "DJANGO_MARK_SAFE",
        "MEDIUM",
        "INJECTION",
        "CWE-79",
        re.compile(r'\bmark_safe\s*\('),
        "mark_safe() bypasses Django auto-escaping. Never call it on user-supplied input.",
    ),
    (
        "DJANGO_CSRF_EXEMPT",
        "MEDIUM",
        "AUTH",
        "CWE-352",
        re.compile(r'@\s*csrf_exempt'),
        "@csrf_exempt removes CSRF protection. Only use with an alternative scheme; document why.",
    ),
    (
        "DJANGO_ALLOWED_HOSTS_WILDCARD",
        "MEDIUM",
        "VALIDATION",
        "CWE-184",
        re.compile(r'ALLOWED_HOSTS\s*=\s*\[\s*["\'][*]["\']'),
        "ALLOWED_HOSTS = ['*'] enables DNS rebinding. Set an explicit allowlist in production.",
    ),
    (
        "DJANGO_RAW_SQL",
        "HIGH",
        "INJECTION",
        "CWE-89",
        re.compile(
            r'(?:cursor\.execute|connection\.execute|\.raw)\s*\('
            r'\s*(?:f["\']|["\'][^"\']*%s|["\'][^"\']*\{|[^,)]*\s*\+)',
        ),
        "String-formatted SQL in cursor.execute() or .raw() is injectable. "
        "Use parameterised queries: cursor.execute(sql, [param]).",
    ),
    (
        "PYTHON_ASSERT_AUTH",
        "HIGH",
        "AUTH",
        "CWE-617",
        re.compile(
            r'\bassert\b.{0,80}(?:is_authenticated|has_perm|is_admin|is_staff|role|auth|token)',
            re.IGNORECASE,
        ),
        "assert is stripped by Python -O. Never use it for auth checks. Use explicit if/raise.",
    ),
    (
        "CORS_WILDCARD_WITH_CREDENTIALS",
        "MEDIUM",
        "AUTH",
        "CWE-942",
        re.compile(
            r'(?:allow_origins\s*=\s*\[\s*["\'][*]["\']|origins\s*=\s*["\'][*]["\'])',
        ),
        "CORS allow_origins='*' with credentials enabled exposes session cookies. "
        "Enumerate trusted origins explicitly.",
    ),
    (
        "PYTHON_XML_XXE",
        "MEDIUM",
        "INJECTION",
        "CWE-611",
        re.compile(
            r'(?:xml\.etree\.ElementTree|xml\.dom\.minidom|xml\.sax|xml\.parsers\.expat)'
            r'\.(?:parse|parseString|fromstring|fromstringlist)\s*\(',
        ),
        "Built-in Python XML parsers are vulnerable to XXE. Use defusedxml as a drop-in replacement.",
    ),
    (
        "INSECURE_TEMPFILE",
        "LOW",
        "PATH",
        "CWE-377",
        re.compile(r'\btempfile\.mktemp\s*\('),
        "tempfile.mktemp() has a TOCTOU race. Use tempfile.mkstemp() or NamedTemporaryFile().",
    ),
    # ── Data pipeline patterns ───────────────────────────────────────────────
    (
        "PANDAS_EVAL_INJECTION",
        "HIGH",
        "INJECTION",
        "CWE-94",
        re.compile(r'(?:df|pd|DataFrame)\s*\.eval\s*\(|(?<!\w)pd\.eval\s*\('),
        "DataFrame.eval() executes Python expressions. User input flowing in is code execution. "
        "Use vectorised operations instead.",
    ),
    (
        "PANDAS_QUERY_INJECTION",
        "MEDIUM",
        "INJECTION",
        "CWE-89",
        re.compile(r'\.query\s*\(\s*(?:f["\']|[^)]{0,60}\.format\s*\(|[^)]{0,60}%\s*[({])'),
        "DataFrame.query() with f-string or .format() is injectable. Use boolean mask indexing.",
    ),
    (
        "SPARK_SQL_INJECTION",
        "HIGH",
        "INJECTION",
        "CWE-89",
        re.compile(
            r'spark\.sql\s*\(\s*(?:f["\']|[^)]{0,60}\.format\s*\(|[^)]{0,60}%\s*[({]'
            r'|["\'][^"\']*["\'\)]\s*\+)',
        ),
        "spark.sql() with string formatting is injectable. Use the DataFrame API or parameterised SQL.",
    ),
    (
        "NUMPY_PICKLE_LOAD",
        "HIGH",
        "DESERIALIZATION",
        "CWE-502",
        re.compile(r'(?:numpy|np)\.load\s*\([^)]*allow_pickle\s*=\s*True'),
        "numpy.load(..., allow_pickle=True) executes arbitrary code in .npy/.npz files. "
        "Use Parquet/CSV and keep allow_pickle=False.",
    ),
    (
        "ARROW_UNTRUSTED_IPC",
        "MEDIUM",
        "DESERIALIZATION",
        "CWE-502",
        re.compile(
            r'(?:pa|pyarrow)\.(?:ipc\.open_file|ipc\.open_stream|ipc\.read_message|'
            r'RecordBatchFileReader|RecordBatchStreamReader|read_feather|read_parquet)\s*\(',
        ),
        "Arrow IPC/Parquet/Feather readers on untrusted binary sources. "
        "Read only from integrity-verified sources and validate schema immediately.",
    ),
    (
        "SENSITIVE_DATA_LOGGED",
        "MEDIUM",
        "EXPOSURE",
        "CWE-532",
        re.compile(
            r'(?:log(?:ger)?\.(?:info|debug|warning|error|critical)|print)\s*\('
            r'[^)]{0,200}(?:password|passwd|secret|token|api_key|credit_card|ssn|dob|salary)',
            re.IGNORECASE,
        ),
        "Sensitive values must not appear in logs. Mask or redact before logging.",
    ),
    (
        "DASK_DELAYED_EXEC",
        "MEDIUM",
        "INJECTION",
        "CWE-94",
        re.compile(r'dask\.delayed\s*\(\s*(?:eval|exec|compile)\s*\)'),
        "dask.delayed wrapping eval/exec schedules arbitrary code as a Dask task. Avoid this pattern.",
    ),
    (
        "SPARK_CONF_SECRET",
        "HIGH",
        "SECRETS",
        "CWE-798",
        re.compile(
            r'spark(?:Context)?\.(?:conf\.set|setConf)\s*\([^)]*'
            r'(?:password|secret|key|token|credential)',
            re.IGNORECASE,
        ),
        "Secrets in spark.conf.set() appear in Spark UI and event logs. "
        "Use an external secrets provider (Vault, AWS Secrets Manager).",
    ),
    (
        "PIPELINE_UNVALIDATED_PATH",
        "MEDIUM",
        "PATH",
        "CWE-22",
        re.compile(
            r'(?:pd\.read_csv|pd\.read_parquet|pd\.read_excel|spark\.read\.|dask\.dataframe\.'
            r'read_csv|pa\.parquet\.read_table|pq\.read_table)\s*\([^)]*(?:request\.|args\.|'
            r'params\.|getenv|environ)',
            re.IGNORECASE,
        ),
        "Pipeline read path from request/env params risks path traversal. "
        "Validate and canonicalise all externally-supplied paths.",
    ),
]

_SOURCE_EXTENSIONS = {
    ".py", ".java", ".cs", ".ts", ".tsx", ".js", ".jsx",
    ".go", ".php", ".rb", ".kt", ".scala", ".swift", ".rs",
}

_MANIFEST_NAMES = frozenset({
    "requirements.txt", "requirements-dev.txt", "requirements-test.txt",
    "pyproject.toml", "setup.py", "setup.cfg", "Pipfile",
    "pom.xml", "build.gradle", "build.gradle.kts",
    "package.json", "cargo.toml", "go.mod", "go.sum",
    "gemfile", "composer.json",
    "dockerfile", "docker-compose.yml", "docker-compose.yaml",
})

_SEV_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}

_SNIPPET_CONTEXT = 3   # lines before/after a match in findings
_MAX_FINDINGS = 80     # cap to keep prompt size manageable


def _extract_snippet(lines: list[str], match_line_0: int, context: int = _SNIPPET_CONTEXT) -> str:
    """Return a numbered code snippet centred on match_line_0 (0-indexed)."""
    start = max(0, match_line_0 - context)
    end = min(len(lines), match_line_0 + context + 1)
    parts = []
    for i in range(start, end):
        marker = "→ " if i == match_line_0 else "  "
        parts.append(f"{marker}{i + 1:4d} | {lines[i]}")
    return "\n".join(parts)


# ── Tool 1: deterministic scanner ─────────────────────────────────────────────

def scan_source_for_security(source_path: str, source_lang: str) -> dict:
    """Deterministic regex scanner. Returns a SecurityReport-shaped dict with code snippets.

    Each finding includes:
      - code_snippet: the matched line plus context lines so the LLM can confirm or
        dismiss the finding without opening the file.
      - matched_text: the exact text that triggered the pattern.

    Use this as the starting point; investigate HIGH/CRITICAL findings further with
    read_file_snippet and search_in_source before calling submit_security_findings.
    """
    root = Path(source_path)
    findings: list[dict] = []
    seen: set[tuple[str, str]] = set()
    counter = 1
    files_with_findings: set[str] = set()

    if root.is_dir():
        for fpath in sorted(root.rglob("*")):
            if not fpath.is_file() or fpath.suffix not in _SOURCE_EXTENSIONS:
                continue
            try:
                content = fpath.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            lines = content.splitlines()
            rel = str(fpath.relative_to(root))

            for pattern_id, severity, category, cwe_id, regex, remediation in _SECURITY_PATTERNS:
                for match in regex.finditer(content):
                    line_no_0 = content[: match.start()].count("\n")
                    line_no = line_no_0 + 1
                    loc = f"{rel}:{line_no}"
                    key = (pattern_id, loc)
                    if key in seen:
                        continue
                    seen.add(key)
                    files_with_findings.add(rel)

                    snippet = _extract_snippet(lines, line_no_0)
                    matched_text = match.group(0)[:120]

                    findings.append({
                        "id": f"SEC-{counter:03d}",
                        "title": pattern_id.replace("_", " ").title(),
                        "description": (
                            f"Pattern '{pattern_id}' detected at {loc}. "
                            f"Matched: `{matched_text.strip()}`"
                        ),
                        "severity": severity,
                        "category": category,
                        "location": loc,
                        "confirmed": False,
                        "remediation": remediation,
                        "cwe_id": cwe_id,
                        "affects_migration": False,
                        "code_snippet": snippet,
                        "matched_text": matched_text.strip(),
                    })
                    counter += 1
                    if counter > _MAX_FINDINGS:
                        break
                if counter > _MAX_FINDINGS:
                    break
            if counter > _MAX_FINDINGS:
                break

    findings.sort(key=lambda f: (_SEV_ORDER.get(f["severity"], 9), f["id"]))

    sevs = {f["severity"] for f in findings}
    src_risk = (
        "CRITICAL" if "CRITICAL" in sevs else
        "HIGH"     if "HIGH"     in sevs else
        "MEDIUM"   if "MEDIUM"   in sevs else
        "LOW"
    )

    return {
        "source_lang": source_lang,
        "scope_summary": (
            f"Deterministic scan of '{source_path}' ({source_lang}). "
            f"Found {len(findings)} candidate findings across {len(files_with_findings)} file(s). "
            "Each finding includes a code_snippet — inspect HIGH/CRITICAL findings with "
            "read_file_snippet and use search_in_source to discover unlisted patterns."
        ),
        "findings": findings,
        "files_with_findings": sorted(files_with_findings),
        "source_architecture_risk": src_risk,
        "destination_architecture_risk": "REQUIRES_ANALYSIS",
        "risk_ranking": [f["id"] for f in findings],
        "recommended_fixes": [],
        "follow_up_checks": [
            "Confirm each hypothesis finding by reading the code_snippet in context.",
            "Use read_file_snippet(file, line) to inspect the surrounding logic.",
            "Use search_in_source(source_path, query) to find related patterns.",
            "Review auth/config files: settings.py, application.properties, web.config.",
            "Inspect dependency manifests with read_manifest_files for vulnerable versions.",
        ],
        "migration_security_notes": [],
    }


# ── Tool 2: focused file reader ───────────────────────────────────────────────

def read_file_snippet(file_path: str, line_number: int, context_lines: int = 8) -> dict:
    """Read N lines of context around a specific line number in a source file.

    Use this to investigate a finding from scan_source_for_security in its surrounding
    code — e.g. to check whether a suspicious call is reachable from user input, whether
    there is a guard above it, or what arguments are passed.

    Returns up to (2 * context_lines + 1) lines centred on line_number, with line numbers
    displayed and the target line marked with '→'.
    """
    p = Path(file_path)
    if not p.exists():
        return {"error": f"File not found: {file_path}", "file_path": file_path}
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        total = len(lines)
        target_0 = max(0, line_number - 1)
        start = max(0, target_0 - context_lines)
        end = min(total, target_0 + context_lines + 1)
        snippet = "\n".join(
            f"{'→ ' if i == target_0 else '  '}{i + 1:4d} | {lines[i]}"
            for i in range(start, end)
        )
        return {
            "file_path": file_path,
            "line_number": line_number,
            "total_lines": total,
            "lines_shown": f"{start + 1}–{end}",
            "snippet": snippet,
        }
    except OSError as exc:
        return {"error": str(exc), "file_path": file_path}


# ── Tool 3: lateral search ────────────────────────────────────────────────────

def _as_int(value: object, default: int) -> int:
    """Models often send numeric tool arguments as strings. Compare and
    slice with the number they asked for; an unparseable value keeps the
    parameter's own default.
    """
    if isinstance(value, bool) or value is None:
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        try:
            return int(text)
        except ValueError:
            try:
                return int(float(text))
            except ValueError:
                return default
    return default


def search_in_source(
    source_path: str,
    query: str,
    file_extensions: Optional[list[str]] = None,
    max_results: int = 20,
    context_lines: int = 2,
) -> dict:
    """Case-insensitive text search across source files.

    Use this to investigate patterns the LLM suspects but that the regex scanner did
    not catch — e.g. all usages of a specific function, all places a particular
    variable flows, or all imports of a dangerous library.

    Returns up to max_results matches, each with file path, line number, and
    context_lines lines of surrounding code.
    """
    max_results = _as_int(max_results, 20)
    context_lines = _as_int(context_lines, 2)
    if isinstance(file_extensions, str):
        text = file_extensions.strip()
        parsed = None
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
        if isinstance(parsed, list):
            file_extensions = [str(item) for item in parsed]
        elif text:
            file_extensions = [part.strip() for part in text.split(",") if part.strip()]
        else:
            file_extensions = None
    root = Path(source_path)
    if not root.is_dir():
        return {"error": f"Not a directory: {source_path}", "query": query, "results": []}

    extensions = (
        {f".{e.lstrip('.')}" for e in file_extensions}
        if file_extensions else _SOURCE_EXTENSIONS
    )
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    results: list[dict] = []

    for fpath in sorted(root.rglob("*")):
        if not fpath.is_file() or fpath.suffix not in extensions:
            continue
        try:
            lines = fpath.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        rel = str(fpath.relative_to(root))
        for i, line in enumerate(lines):
            if not pattern.search(line):
                continue
            start = max(0, i - context_lines)
            end = min(len(lines), i + context_lines + 1)
            snippet = "\n".join(
                f"{'→ ' if j == i else '  '}{j + 1:4d} | {lines[j]}"
                for j in range(start, end)
            )
            results.append({
                "file": rel,
                "line_number": i + 1,
                "matched_line": line.strip()[:200],
                "snippet": snippet,
            })
            if len(results) >= max_results:
                break
        if len(results) >= max_results:
            break

    return {
        "query": query,
        "total_matches": len(results),
        "truncated": len(results) >= max_results,
        "results": results,
    }


# ── Tool 4: manifest / dependency reader ──────────────────────────────────────

def read_manifest_files(source_path: str) -> dict:
    """Read dependency manifests and configuration files for supply-chain and secrets auditing.

    Finds and returns the contents of: requirements.txt, pyproject.toml, pom.xml,
    package.json, Cargo.toml, go.mod, Dockerfile, docker-compose.yml, .env*, *.csproj.

    Use this early in the analysis to:
    - Check for pinned versions of known-problematic packages.
    - Find secrets or credentials in .env files.
    - Identify security-relevant build/deploy configuration.
    """
    root = Path(source_path)
    if not root.is_dir():
        return {"error": f"Not a directory: {source_path}", "files": []}

    _MAX_FILE_CHARS = 8_000
    _TOTAL_BUDGET = 50_000
    total_chars = 0
    found: list[dict] = []

    for fpath in sorted(root.rglob("*")):
        if not fpath.is_file():
            continue
        name_lower = fpath.name.lower()
        suffix_lower = fpath.suffix.lower()
        is_manifest = (
            name_lower in _MANIFEST_NAMES
            or suffix_lower in (".csproj", ".fsproj", ".nuspec")
            or (name_lower.startswith(".env") and suffix_lower in ("", ".example", ".sample", ".local"))
        )
        if not is_manifest:
            continue

        try:
            rel = str(fpath.relative_to(root))
        except ValueError:
            rel = str(fpath)

        if total_chars >= _TOTAL_BUDGET:
            found.append({"path": rel, "content": "[budget exhausted]", "size": 0})
            continue

        try:
            content = fpath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        size = len(content)
        truncated = size > _MAX_FILE_CHARS
        excerpt = content[:_MAX_FILE_CHARS]
        total_chars += len(excerpt)
        found.append({
            "path": rel,
            "content": excerpt + ("\n... [truncated — use read_source_file for full content]" if truncated else ""),
            "size": size,
            "truncated": truncated,
        })

    return {
        "source_path": source_path,
        "count": len(found),
        "files": found,
    }


# ── Tool 5: final submission ───────────────────────────────────────────────────

def submit_security_findings(
    scope_summary: str = "",
    findings: list | None = None,
    source_architecture_risk: str = "",
    destination_architecture_risk: str = "",
    source_lang: str = "",
    target_lang: str = "",
    risk_ranking: list | None = None,
    recommended_fixes: list | None = None,
    follow_up_checks: list | None = None,
    migration_security_notes: list | None = None,
) -> dict:
    """Accept the Security Agent's completed analysis and return the security_report artifact.

    This is the final call the LLM makes after completing the full ReACT analysis loop.
    The orchestrator stores the return value as the 'security_report' artifact, which is
    then rendered to security-report.html and indexed in the FAISS vector store.

    findings must be a list of dicts, each with:
      id, title, description, severity, category, location, confirmed, remediation,
      cwe_id (optional), affects_migration (bool), code_snippet (optional).

    source_architecture_risk / destination_architecture_risk: CRITICAL | HIGH | MEDIUM | LOW
    """
    clean: list[dict] = []
    for i, f in enumerate(findings or []):
        if not isinstance(f, dict):
            continue
        sev = str(f.get("severity", "MEDIUM")).upper()
        if sev not in _VALID_SEVERITIES:
            sev = "MEDIUM"
        cat = str(f.get("category", "OTHER")).upper()
        if cat not in _VALID_CATEGORIES:
            cat = "OTHER"
        clean.append({
            "id": f.get("id") or f"SEC-{i + 1:03d}",
            "title": str(f.get("title", "Unnamed finding")),
            "description": str(f.get("description", "")),
            "severity": sev,
            "category": cat,
            "location": str(f.get("location", "")),
            "confirmed": bool(f.get("confirmed", False)),
            "remediation": str(f.get("remediation", "")),
            "cwe_id": str(f.get("cwe_id", "")),
            "affects_migration": bool(f.get("affects_migration", False)),
            "code_snippet": str(f.get("code_snippet", "")),
        })

    clean.sort(key=lambda f: (_SEV_ORDER.get(f["severity"], 9), f["id"]))

    src_risk = str(source_architecture_risk).upper()
    if src_risk not in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}:
        src_risk = "MEDIUM"
    dst_risk = str(destination_architecture_risk).upper()
    if dst_risk not in {"CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"}:
        dst_risk = "UNKNOWN"

    return {
        "source_lang": source_lang,
        "target_lang": target_lang,
        "scope_summary": str(scope_summary),
        "findings": clean,
        "source_architecture_risk": src_risk,
        "destination_architecture_risk": dst_risk,
        "risk_ranking": list(risk_ranking or [f["id"] for f in clean]),
        "recommended_fixes": list(recommended_fixes or []),
        "follow_up_checks": list(follow_up_checks or []),
        "migration_security_notes": list(migration_security_notes or []),
    }


# ── Trivy integration ─────────────────────────────────────────────────────────

_TRIVY_SEV_MAP = {"CRITICAL": "CRITICAL", "HIGH": "HIGH", "MEDIUM": "MEDIUM", "LOW": "LOW"}


def _maybe_restore_dotnet_lockfile(target_dir: Path, lang: str) -> None:
    """Best-effort: generate packages.lock.json for C#/.NET targets so Trivy's
    NuGet scanner gets full transitive-dependency data instead of just direct
    <PackageReference> names (Trivy can read Java's pom.xml directly with no
    build step, but .NET dependency resolution needs a lock file or .deps.json
    to work well — see "GPU type"-style caveat notes in deployment docs for
    the same "verify don't guess" treatment). Never raises — a failed/skipped
    restore just means Trivy scans with whatever it can already see, same as
    before this function existed."""
    if lang != "csharp":
        return
    try:
        result = subprocess.run(
            ["dotnet", "restore", "--use-lock-file", str(target_dir)],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            diagnostics.log.warning(
                "dotnet restore --use-lock-file failed for %s — Trivy will "
                "scan with only direct PackageReference data: %s",
                target_dir, (result.stderr or result.stdout or "")[:300],
            )
    except FileNotFoundError:
        diagnostics.log.warning(
            ".NET SDK not found — Trivy will scan %s with only direct "
            "PackageReference data, not a full transitive dependency graph",
            target_dir,
        )
    except subprocess.TimeoutExpired:
        diagnostics.log.warning("dotnet restore timed out for %s after 120s", target_dir)


_JVM_LANGS = {"java", "java8", "java11", "java21", "kotlin"}


def _maybe_restore_jvm_lockfile(target_dir: Path, lang: str) -> None:
    """Best-effort: generate a gradle.lockfile for Gradle-based Java/Kotlin
    targets so Trivy's Gradle scanner has something to read at all — unlike
    Maven's pom.xml (which Trivy parses directly with no build step), Trivy
    does NOT read build.gradle/build.gradle.kts, only gradle.lockfile, so a
    Gradle project without one gets zero Trivy detection. Maven projects are
    deliberately NOT touched here: Trivy already reads pom.xml directly, and
    its narrower gap (unresolved version properties/variables) has no clean
    fix without invasively rewriting the project's pom.xml — left as a
    documented limitation instead of a half-working workaround.

    Uses a Gradle init script to force-enable dependency locking
    (`dependencyLocking { lockAllConfigurations() }`) without ever touching
    the project's own build.gradle. Never raises — a failed/skipped restore
    just means Trivy scans with whatever it can already see, same as before
    this function existed."""
    if lang not in _JVM_LANGS:
        return
    has_gradle = (target_dir / "build.gradle").exists() or (target_dir / "build.gradle.kts").exists()
    if not has_gradle:
        return  # Maven (pom.xml) or nothing generated yet — nothing to do

    init_script = target_dir / ".trivy-dependency-locking-init.gradle"
    gradle_cmd = "./gradlew" if (target_dir / "gradlew").exists() else "gradle"
    try:
        init_script.write_text(
            "allprojects {\n"
            "    dependencyLocking {\n"
            "        lockAllConfigurations()\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )
        result = subprocess.run(
            [gradle_cmd, f"--init-script={init_script.name}", "dependencies", "--write-locks"],
            capture_output=True, text=True, timeout=180, cwd=str(target_dir),
        )
        if result.returncode != 0:
            diagnostics.log.warning(
                "gradle dependency-locking failed for %s — Trivy will scan "
                "with no Gradle dependency data at all (Trivy requires a "
                "gradle.lockfile; it does not read build.gradle directly): %s",
                target_dir, (result.stderr or result.stdout or "")[:300],
            )
    except FileNotFoundError:
        diagnostics.log.warning(
            "gradle not found — Trivy will scan %s with no Gradle dependency "
            "data at all (Trivy requires a gradle.lockfile; it does not read "
            "build.gradle directly)", target_dir,
        )
    except subprocess.TimeoutExpired:
        diagnostics.log.warning("gradle dependency locking timed out for %s after 180s", target_dir)
    finally:
        init_script.unlink(missing_ok=True)


def run_trivy_scan(source_path: str, run_dir: str, lang: str = "") -> dict:
    """Run Trivy filesystem scan on source_path; save raw output as trivy_report.json.

    Called by the pipeline orchestrator (not the LLM) before the Security phase starts.
    Requires Trivy to be installed at /usr/local/bin/trivy or on PATH.

    lang: detected source language (e.g. "csharp", "java21", "kotlin") — when
    set, a best-effort restore/lockfile step runs first so Trivy's dependency
    scanner has a full graph to read instead of just direct references. See
    _maybe_restore_dotnet_lockfile() and _maybe_restore_jvm_lockfile().

    Returns a summary dict with vulnerability counts; full CVE data is written to
    <run_dir>/trivy_report.json for the LLM to read via read_trivy_report().
    """
    sp = Path(source_path)
    rd = Path(run_dir)
    output_path = rd / "trivy_report.json"

    if not sp.exists():
        result = {"error": f"Source path not found: {source_path}", "vulnerabilities": [], "summary": {}}
        output_path.write_text(json.dumps(result), encoding="utf-8")
        return result

    _maybe_restore_dotnet_lockfile(sp, lang)
    _maybe_restore_jvm_lockfile(sp, lang)

    cmd = [
        "trivy", "fs", str(sp),
        "--scanners", "vuln,secret",
        "--format", "json",
        "--quiet",
        "--output", str(output_path),
    ]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except FileNotFoundError:
        result = {
            "error": "Trivy not found. Install: curl -sfL https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh | sh -s -- -b /usr/local/bin v0.52.2",
            "vulnerabilities": [],
            "summary": {},
        }
        output_path.write_text(json.dumps(result), encoding="utf-8")
        return result
    except subprocess.TimeoutExpired:
        result = {"error": "Trivy scan timed out after 180s", "vulnerabilities": [], "summary": {}}
        output_path.write_text(json.dumps(result), encoding="utf-8")
        return result

    # Trivy exits non-zero when vulnerabilities are found; that is expected.
    if not output_path.exists():
        stderr_snippet = (proc.stderr or proc.stdout or "")[:500]
        result = {"error": f"Trivy produced no output: {stderr_snippet}", "vulnerabilities": [], "summary": {}}
        output_path.write_text(json.dumps(result), encoding="utf-8")
        return result

    try:
        raw = json.loads(output_path.read_text(encoding="utf-8"))
    except Exception as exc:
        result = {"error": f"Failed to parse Trivy JSON: {exc}", "vulnerabilities": [], "summary": {}}
        output_path.write_text(json.dumps(result), encoding="utf-8")
        return result

    # Parse Trivy Results[] into a flat vulnerability list
    vulns: list[dict] = []
    idx = 0
    sev_counts: dict[str, int] = {}
    for result_item in raw.get("Results", []):
        target = result_item.get("Target", "unknown")
        for v in result_item.get("Vulnerabilities", []) or []:
            idx += 1
            cve_id = v.get("VulnerabilityID", "")
            pkg = v.get("PkgName", "")
            installed = v.get("InstalledVersion", "?")
            fixed = v.get("FixedVersion", "") or ""
            sev_raw = str(v.get("Severity", "UNKNOWN")).upper()
            sev = _TRIVY_SEV_MAP.get(sev_raw, "MEDIUM")
            title = v.get("Title") or f"{pkg}: {cve_id}"
            desc = (v.get("Description") or "")[:600]
            url = v.get("PrimaryURL", "")
            sev_counts[sev] = sev_counts.get(sev, 0) + 1
            vulns.append({
                "id": f"CVE-{idx:03d}",
                "cve_id": cve_id,
                "pkg_name": pkg,
                "installed_version": installed,
                "fixed_version": fixed,
                "title": title,
                "severity": sev,
                "description": desc,
                "location": f"{target} · {pkg}=={installed}",
                "remediation": (
                    f"Upgrade {pkg} to {fixed}" if fixed else
                    f"No upstream fix yet for {pkg} {installed}; monitor {url or 'NVD'}"
                ),
                "primary_url": url,
                "category": "SUPPLY_CHAIN",
                "cwe_id": "",
                "confirmed": True,
                "affects_migration": sev in {"CRITICAL", "HIGH"},
            })

    summary = {"total": len(vulns), **{k: v for k, v in sev_counts.items()}}

    # Rewrite the file with the enriched structure so read_trivy_report() gets everything
    enriched = {
        "scan_target": str(sp),
        "schema_version": raw.get("SchemaVersion"),
        "summary": summary,
        "vulnerabilities": vulns,
        "raw_results": raw.get("Results", []),
    }
    output_path.write_text(json.dumps(enriched, indent=2), encoding="utf-8")

    return {"scan_target": str(sp), "summary": summary, "vulnerability_count": len(vulns)}


def read_trivy_report(run_dir: str) -> dict:
    """Read the Trivy CVE scan report saved in the run directory.

    The pipeline runs Trivy automatically before the Security phase. Call this tool
    early in your analysis to see all dependency CVEs found by Trivy, then incorporate
    critical/high CVEs as additional findings in your submit_security_findings call.

    Returns the full trivy_report.json: summary counts + vulnerabilities[].
    Each vulnerability has: id, cve_id, pkg_name, installed_version, fixed_version,
    severity, description, location, remediation, primary_url, confirmed, affects_migration.
    """
    p = Path(run_dir) / "trivy_report.json"
    if not p.exists():
        return {
            "error": f"trivy_report.json not found in {run_dir}. Trivy may not be installed.",
            "vulnerabilities": [],
            "summary": {},
        }
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"error": f"Failed to read trivy_report.json: {exc}", "vulnerabilities": [], "summary": {}}
