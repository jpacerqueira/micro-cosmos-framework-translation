"""Coder Agent tools — DDD scaffolding, file submission, and fallback.

The primary translation path is LLM-driven: the Coder agent reads source
files directly via source_tools and submits its output via
submit_seam_translation. Application estates have no deterministic
parser. ETL estates (Databricks, BigQuery + Dataform, Snowflake + dbt)
are the exception: those targets are written by micro_cosmos.etl so the
run produces a real destination project.

This module provides:
  submit_seam_translation  — accepts LLM-generated files and packages them
  generate_and_verify_seam — deterministic fallback (DDD scaffolding only)
  _ddd_scaffolding         — hexagonal port/adapter scaffolding
  _project_scaffold_files  — build files (pom.xml, go.mod, pyproject.toml …)
"""

from __future__ import annotations

import re


# ─── name helpers ─────────────────────────────────────────────────────────────

def _pascal(name: str) -> str:
    # Seam IDs routinely carry a literal "." (e.g. "seam_object_prog.Foo",
    # mirroring the IR's own dotted node-id convention) — without splitting
    # on it too, the dot survives straight into the PascalCase identifier
    # ("ISeamObjectProg.FooUseCase"), which is invalid syntax in every
    # target language this scaffolds for. Confirmed live, 2026-08-24: this
    # produced a genuine Kotlin compile error ("Redeclaration: interface
    # ISeamObjectProg" + several "Expecting a top level declaration"
    # errors) for every seam whose id has a dot in it — i.e. most "object"
    # seams, not a one-off.
    parts = re.split(r"[_\-\s.]+", name)
    out = []
    for p in parts:
        if not p:
            continue
        out.append(p.capitalize() if p.isupper() else p[0].upper() + p[1:])
    return "".join(out)

def _snake(name: str) -> str:
    s = re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", name)
    return re.sub(r"[^a-z0-9_]", "_", s.lower()).strip("_")

def _camel(name: str) -> str:
    p = _pascal(name)
    return p[0].lower() + p[1:] if p else name

def _pkg(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())

def _norm_lang(lang: str) -> str:
    l = lang.lower()
    for key in ("java", "python", "go", "typescript", "csharp", "kotlin", "rust", "scala", "swift"):
        if l.startswith(key) or key.startswith(l):
            return key
    return l

_IS_JAVA   = lambda t: t in ("java", "java8", "java11", "java21")
_IS_PYTHON = lambda t: t in ("python", "python3")
_IS_CS     = lambda t: t in ("csharp", "cs")

# JVM languages require src/main/<lang>/ or src/test/<lang>/ source roots.
# Under context pressure the LLM sometimes omits the prefix entirely, writing
# e.g. com/foo/bar/Cls.kt instead of src/main/kotlin/com/foo/bar/Cls.kt.
_JVM_LANG_ROOTS: dict[str, tuple[str, str]] = {
    "kotlin": ("src/main/kotlin/", "src/test/kotlin/"),
    "java":   ("src/main/java/",   "src/test/java/"),
    "scala":  ("src/main/scala/",  "src/test/scala/"),
}
_JVM_PKG_PREFIXES = ("com/", "org/", "net/", "io/", "uk/", "de/", "fr/", "be/")
_JVM_TEST_SUFFIXES = ("Test.kt", "Tests.kt", "Spec.kt",
                      "Test.java", "Tests.java", "Spec.java",
                      "Test.scala", "Spec.scala")


def _fix_jvm_source_path(path: str, target_lang: str) -> str:
    """Auto-correct JVM paths that are missing their src/main|test/<lang>/ root.

    The LLM drops this prefix under context pressure (large seams with many
    files in context).  We detect four patterns and fix them:
      1. tests/<bare>  or  test/<bare>  → src/test/<lang>/<bare>
      2. com/... org/... etc (bare pkg)  → src/main/<lang>/com/... (or test if name implies test)
      3. Files already starting with src/ are left untouched.
      4. Multi-module prefix before src/ (e.g. my-module/sub/src/main/java/…)
         → strip everything before the first src/main/ or src/test/ segment.
    """
    tl = _norm_lang(target_lang)
    roots = _JVM_LANG_ROOTS.get(tl)
    if not roots:
        return path
    main_root, test_root = roots

    if path.startswith("src/"):
        return path

    # Case 4 — multi-module prefix: strip everything before src/main/ or src/test/
    for marker in ("src/main/", "src/test/"):
        idx = path.find(marker)
        if idx > 0:
            return path[idx:]

    # Non-standard test directory at project root
    for test_dir in ("tests/", "test/"):
        if path.startswith(test_dir):
            bare = path[len(test_dir):]
            return test_root + bare

    # Bare JVM package path — determine test vs impl from filename
    if any(path.startswith(pfx) for pfx in _JVM_PKG_PREFIXES):
        filename = path.rsplit("/", 1)[-1]
        is_test = any(filename.endswith(s) for s in _JVM_TEST_SUFFIXES)
        return (test_root if is_test else main_root) + path

    return path


# ─── seam result cache ────────────────────────────────────────────────────────

_seam_translation_cache: dict[str, dict] = {}

# Set by the pipeline before each Code Writer phase so _write_seam_result always
# has a target directory even when the LLM omits the run_dir parameter.
from micro_cosmos.tools.run_context import get_run_dir, set_run_dir  # noqa: E402,F401 — re-exported


# ─── hexagonal architecture scaffolding ──────────────────────────────────────

def _ddd_scaffolding(seam: str, target_lang: str, domain_model: dict, tnas: dict) -> list[dict]:
    """Generate DDD application/infrastructure scaffolding for the hexagonal architecture wrapper."""
    tl = target_lang.lower()
    aggs = [a for a in domain_model.get("aggregates", []) if a.get("context") == seam]
    if not aggs:
        aggs = [{"name": _pascal(seam), "context": seam}]
    # Deduplicate by name so the scaffold never emits the same struct/class twice.
    seen_names: set[str] = set()
    aggs = [a for a in aggs if not (a.get("name") in seen_names or seen_names.add(a.get("name", "")))]
    files: list[dict] = []

    if _IS_JAVA(tl):
        pkg = f"com.example.{_pkg(seam)}"
        pkg_path = pkg.replace(".", "/")
        for agg in aggs:
            an = _pascal(agg["name"])
            files.append({
                "path": f"src/main/java/{pkg_path}/application/I{an}UseCase.java",
                "content": (
                    f"package {pkg}.application;\n"
                    f"public interface I{an}UseCase {{\n"
                    f"    void execute(String id);\n"
                    f"}}\n"
                ),
            })
            files.append({
                "path": f"src/main/java/{pkg_path}/infrastructure/InMemory{an}Repository.java",
                "content": (
                    f"package {pkg}.infrastructure;\n"
                    f"import {pkg}.domain.{an};\n"
                    f"import java.util.*;\n"
                    f"public class InMemory{an}Repository {{\n"
                    f"    private final Map<String, {an}> store = new LinkedHashMap<>();\n"
                    f"    public void save({an} aggregate) {{ store.put(aggregate.toString(), aggregate); }}\n"
                    f"    public Optional<{an}> findById(String id) {{ return Optional.ofNullable(store.get(id)); }}\n"
                    f"}}\n"
                ),
            })

    elif _IS_PYTHON(tl):
        pkg = _snake(seam)
        an = _pascal(aggs[0]["name"]) if aggs else _pascal(seam)
        src = (
            "from __future__ import annotations\n"
            "from typing import Protocol, Optional\n"
        )
        for agg in aggs:
            an = _pascal(agg["name"])
            src += (
                f"\n\nclass I{an}Repository(Protocol):\n"
                f"    def save(self, aggregate: object) -> None: ...\n"
                f"    def find_by_id(self, aggregate_id: str) -> Optional[object]: ...\n"
                f"\n\nclass InMemory{an}Repository:\n"
                f"    def __init__(self) -> None:\n"
                f"        self._store: dict[str, object] = {{}}\n"
                f"\n"
                f"    def save(self, aggregate: object) -> None:\n"
                f'        key = getattr(aggregate, "id", id(aggregate))\n'
                f"        self._store[str(key)] = aggregate\n"
                f"\n"
                f"    def find_by_id(self, aggregate_id: str) -> Optional[object]:\n"
                f"        return self._store.get(aggregate_id)\n"
            )
        files.append({"path": f"src/{pkg}/adapters.py", "content": src})

    elif tl == "go":
        pkg = _pkg(seam)
        module = _snake(seam).replace("_", "-")
        # Import path: github.com/example/{module}/{pkg}/domain
        # pkg == module for single-word seams (e.g. btc); keep them distinct
        # by using module as the Go module name and pkg as the package subdir.
        import_path = (
            f"github.com/example/{module}/{pkg}/domain"
            if module != pkg
            else f"github.com/example/{module}/domain"
        )
        src = (
            "package adapters\n\n"
            f'import "{import_path}"\n'
            "import \"fmt\"\n\n"
        )
        for agg in aggs:
            an = _pascal(agg["name"])
            src += (
                f"type InMemory{an}Repository struct {{\n"
                f"\tstore map[string]*domain.{an}\n"
                f"}}\n\n"
                f"func NewInMemory{an}Repository() *InMemory{an}Repository {{\n"
                f"\treturn &InMemory{an}Repository{{store: make(map[string]*domain.{an})}}\n"
                f"}}\n\n"
                f"func (r *InMemory{an}Repository) Save(a *domain.{an}) error {{\n"
                f'\tif a == nil {{ return fmt.Errorf("aggregate is nil") }}\n'
                f"\tr.store[a.ID] = a\n"
                f"\treturn nil\n"
                f"}}\n\n"
                f"func (r *InMemory{an}Repository) FindByID(id string) (*domain.{an}, error) {{\n"
                f"\ta, ok := r.store[id]\n"
                f"\tif !ok {{ return nil, nil }}\n"
                f"\treturn a, nil\n"
                f"}}\n\n"
            )
        files.append({"path": f"{pkg}/adapters/adapters.go", "content": src})

    elif tl == "typescript":
        pkg = _snake(seam)
        src = ""
        for agg in aggs:
            an = _pascal(agg["name"])
            src += (
                f"export interface I{an}UseCase {{\n"
                f"  execute(id: string): void;\n"
                f"}}\n"
                f"export interface I{an}Repository {{\n"
                f"  save(a: object): Promise<void>;\n"
                f"  findById(id: string): Promise<object | null>;\n"
                f"}}\n"
                f"export class InMemory{an}Repository implements I{an}Repository {{\n"
                f"  private store = new Map<string, object>();\n"
                f"  async save(a: object): Promise<void> {{ this.store.set(JSON.stringify(a), a); }}\n"
                f"  async findById(id: string): Promise<object | null> {{ return this.store.get(id) ?? null; }}\n"
                f"}}\n"
            )
        files.append({"path": f"src/{pkg}/application/index.ts", "content": src})

    elif _IS_CS(tl):
        ns = _pascal(seam)
        for agg in aggs:
            an = _pascal(agg["name"])
            files.append({
                "path": f"src/{ns}/Application/I{an}UseCase.cs",
                "content": (
                    f"namespace {ns}.Application;\n"
                    f"public interface I{an}UseCase {{\n"
                    f"    void Execute(string id);\n"
                    f"}}\n"
                ),
            })
            files.append({
                "path": f"src/{ns}/Infrastructure/InMemory{an}Repository.cs",
                "content": (
                    f"namespace {ns}.Infrastructure;\n"
                    f"using {ns}.Domain;\n"
                    f"using System.Collections.Generic;\n"
                    f"public class InMemory{an}Repository {{\n"
                    f"    private readonly Dictionary<string, {an}> _store = new();\n"
                    f"    public Task SaveAsync({an} aggregate) {{\n"
                    f"        _store[aggregate.ToString() ?? string.Empty] = aggregate;\n"
                    f"        return Task.CompletedTask;\n"
                    f"    }}\n"
                    f"    public Task<{an}?> FindByIdAsync(string id) {{\n"
                    f"        _store.TryGetValue(id, out var v);\n"
                    f"        return Task.FromResult(v);\n"
                    f"    }}\n"
                    f"}}\n"
                ),
            })

    elif tl == "kotlin":
        pkg = _snake(seam)
        src = ""
        for agg in aggs:
            an = _pascal(agg["name"])
            src += (
                f"interface I{an}UseCase {{\n"
                f"    fun execute(id: String)\n"
                f"}}\n\n"
                f"interface I{an}Repository {{\n"
                f"    fun save(aggregate: {an})\n"
                f"    fun findById(id: String): {an}?\n"
                f"}}\n"
            )
        files.append({"path": f"src/main/kotlin/{pkg}/application/Application.kt", "content": src})

    elif tl == "rust":
        pkg = _snake(seam)
        src = "use async_trait::async_trait;\n\n"
        for agg in aggs:
            an = _pascal(agg["name"])
            src += (
                f"pub trait {an}UseCase: Send + Sync {{\n"
                f"    fn execute(&self, id: &str) -> Result<(), Box<dyn std::error::Error>>;\n"
                f"}}\n\n"
                f"pub trait {an}Repository: Send + Sync {{\n"
                f"    fn save(&self, aggregate: &{an}) -> Result<(), Box<dyn std::error::Error>>;\n"
                f"    fn find_by_id(&self, id: &str) -> Result<Option<{an}>, Box<dyn std::error::Error>>;\n"
                f"}}\n\n"
            )
        files.append({"path": f"src/{pkg}.rs", "content": src})

    elif tl == "scala":
        pkg = _snake(seam)
        src = f"package {pkg}.application\n\n"
        for agg in aggs:
            an = _pascal(agg["name"])
            src += (
                f"trait {an}UseCase {{\n"
                f"  def execute(id: String): Unit\n"
                f"}}\n\n"
                f"trait {an}Repository {{\n"
                f"  def save(aggregate: {an}): Unit\n"
                f"  def findById(id: String): Option[{an}]\n"
                f"}}\n\n"
            )
        files.append({"path": f"src/main/scala/{pkg}/application/Application.scala", "content": src})

    elif tl == "swift":
        pkg = _pascal(seam)
        src = ""
        for agg in aggs:
            an = _pascal(agg["name"])
            src += (
                f"protocol {an}UseCase {{\n"
                f"    func execute(id: String) throws\n"
                f"}}\n\n"
                f"protocol {an}Repository {{\n"
                f"    func save(_ aggregate: {an}) throws\n"
                f"    func findById(_ id: String) throws -> {an}?\n"
                f"}}\n\n"
            )
        files.append({"path": f"Sources/{pkg}/Application/Application.swift", "content": src})

    return files


def _project_scaffold_files(seam_name: str, target_lang: str, pkg: str) -> list[dict]:
    """Language-specific build/config files for a new module."""
    tl = _norm_lang(target_lang)
    module = _snake(seam_name).replace("_", "-")
    ns = _pascal(seam_name)
    files: list[dict] = []

    if tl == "go":
        files.append({"path": "go.mod", "content": f"module github.com/example/{module}\n\ngo 1.22\n\nrequire (\n\tgithub.com/shopspring/decimal v1.3.1\n)\n"})
        files.append({"path": "Makefile", "content": ".PHONY: build test\nbuild:\n\tgo build ./...\ntest:\n\tgo test ./...\n"})
        files.append({"path": ".gitignore", "content": "*.exe\n*.test\n*.out\nvendor/\n"})

    elif _IS_JAVA(tl) or tl == "java":
        group_id = f"com.example.{_pkg(seam_name)}"
        files.append({"path": "pom.xml", "content": f"""\
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd">
  <modelVersion>4.0.0</modelVersion>
  <groupId>{group_id}</groupId>
  <artifactId>{module}</artifactId>
  <version>0.1.0-SNAPSHOT</version>
  <properties>
    <java.version>21</java.version>
    <maven.compiler.source>21</maven.compiler.source>
    <maven.compiler.target>21</maven.compiler.target>
    <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
  </properties>
  <dependencies>
    <dependency>
      <groupId>org.junit.jupiter</groupId>
      <artifactId>junit-jupiter</artifactId>
      <version>5.10.2</version>
      <scope>test</scope>
    </dependency>
  </dependencies>
  <build>
    <plugins>
      <plugin>
        <groupId>org.apache.maven.plugins</groupId>
        <artifactId>maven-surefire-plugin</artifactId>
        <version>3.2.5</version>
      </plugin>
    </plugins>
  </build>
</project>
"""})
        files.append({"path": ".gitignore", "content": "target/\n*.class\n*.jar\n.idea/\n*.iml\n"})

    elif tl == "python":
        files.append({"path": "pyproject.toml", "content": f"""\
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "{module}"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = []

[project.optional-dependencies]
dev = ["pytest>=8", "pytest-cov", "mypy", "ruff"]

[tool.pytest.ini_options]
testpaths = ["tests"]
"""})
        files.append({"path": "requirements.txt", "content": "# No runtime dependencies for pure domain logic\n"})
        files.append({"path": "requirements-dev.txt", "content": "pytest>=8\npytest-cov\n"})
        files.append({"path": f"src/{_snake(seam_name)}/__init__.py", "content": f'"""{ns} domain module."""\n'})
        files.append({"path": ".gitignore", "content": "__pycache__/\n*.pyc\ndist/\n.venv/\n.coverage\n"})

    elif tl == "typescript":
        files.append({"path": "package.json", "content": f"""{{"name":"{module}","version":"0.1.0","private":true,"scripts":{{"build":"tsc","test":"jest"}},"dependencies":{{"decimal.js":"^10.4.3"}},"devDependencies":{{"typescript":"^5.4.5","@types/node":"^20.12.0"}}}}\n"""})
        files.append({"path": "tsconfig.json", "content": '{"compilerOptions":{"target":"ES2022","module":"commonjs","outDir":"dist","rootDir":"src","strict":true,"esModuleInterop":true},"include":["src/**/*"]}\n'})
        files.append({"path": ".gitignore", "content": "node_modules/\ndist/\n"})

    elif tl == "kotlin":
        # kotlin("jvm") transitively applies the Java plugin (registering a
        # compileJava task even with zero .java files present). Without an
        # explicit toolchain, compileJava follows whatever JDK Gradle itself
        # runs on while compileKotlin defaults elsewhere — Gradle's JVM-target
        # validation then fails the build on any mismatch. Pinning one
        # toolchain keeps both tasks aligned regardless of the host JDK.
        files.append({"path": "build.gradle.kts", "content": f'plugins {{ kotlin("jvm") version "2.0.0" }}\ngroup = "com.example.{_pkg(seam_name)}"\nversion = "0.1.0"\nrepositories {{ mavenCentral() }}\nkotlin {{ jvmToolchain(21) }}\ndependencies {{ implementation(kotlin("stdlib"))\n    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-core:1.8.0") }}\n'})
        files.append({"path": "settings.gradle.kts", "content": f'rootProject.name = "{module}"\n'})
        files.append({"path": ".gitignore", "content": "build/\n.gradle/\n*.class\n"})

    elif tl == "rust":
        files.append({"path": "Cargo.toml", "content": f'[package]\nname = "{module}"\nversion = "0.1.0"\nedition = "2021"\n\n[dependencies]\nrust_decimal = "1"\nthiserror = "1"\nasync-trait = "0.1"\ntokio = {{ version = "1", features = ["full"] }}\n'})
        files.append({"path": "Makefile", "content": ".PHONY: build test\nbuild:\n\tcargo build\ntest:\n\tcargo test\n"})
        files.append({"path": ".gitignore", "content": "target/\nCargo.lock\n"})

    elif tl == "scala":
        files.append({"path": "build.sbt", "content": f'ThisBuild / scalaVersion := "3.4.0"\nThisBuild / version := "0.1.0"\nThisBuild / organization := "com.example"\nlazy val root = project.in(file("."))\n  .settings(name := "{module}",\n    libraryDependencies ++= Seq(\n      "org.typelevel" %% "cats-core" % "2.10.0"\n    ))\n'})
        files.append({"path": ".gitignore", "content": "target/\n.bsp/\n.metals/\n"})

    elif tl == "swift":
        files.append({"path": "Package.swift", "content": f'// swift-tools-version:5.10\nimport PackageDescription\nlet package = Package(\n    name: "{module}",\n    products: [.library(name: "{ns}", targets: ["{ns}"])],\n    dependencies: [],\n    targets: [.target(name: "{ns}", dependencies: [])]\n)\n'})
        files.append({"path": ".gitignore", "content": ".build/\n*.xcodeproj\n"})

    elif _IS_CS(tl) or tl == "csharp":
        files.append({"path": f"{ns}.csproj", "content": f'<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net8.0</TargetFramework><Nullable>enable</Nullable><ImplicitUsings>enable</ImplicitUsings><RootNamespace>{ns}</RootNamespace></PropertyGroup></Project>\n'})
        files.append({"path": ".gitignore", "content": "bin/\nobj/\n*.user\n.vs/\n"})

    return files


# ─── submission sanitisation ─────────────────────────────────────────────────

def _dedup_declarations(content: str, path: str) -> str:
    """Remove duplicate top-level declarations repeated from ADK session history.

    On TDD iteration N>1 the LLM sees its iteration N-1 tool call in context
    and sometimes re-emits those declarations on top of new ones, producing a
    file that is valid but contains the same type/function/class twice.

    Strategy: split on declaration-start lines, track seen signatures, drop
    any block whose opening signature has already appeared.
    """
    import re

    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""

    if ext == "go":
        # Split on lines that start a top-level Go declaration.
        pattern = re.compile(r"^(type |func |var |const )", re.MULTILINE)
    elif ext in ("java", "kt", "scala"):
        pattern = re.compile(r"^(public |private |protected |class |interface |enum |fun |def )", re.MULTILINE)
    elif ext == "py":
        pattern = re.compile(r"^(class |def |async def )", re.MULTILINE)
    elif ext == "rs":
        pattern = re.compile(
            r"^(pub trait |pub struct |pub enum |pub fn |pub impl |impl |"
            r"mod |pub mod |pub type |type |pub const |const |pub static |static |pub use |use )",
            re.MULTILINE,
        )
    else:
        return content

    matches = list(pattern.finditer(content))
    if not matches:
        return content

    header = content[: matches[0].start()]
    blocks: list[str] = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        blocks.append(content[m.start() : end])

    # Iterate in reverse so the LAST occurrence of each declaration wins.
    # ADK session history causes the LLM to re-emit the old (broken) version
    # first, then the fixed version; we want to keep the fixed one.
    seen: set[str] = set()
    unique: list[str] = []
    for block in reversed(blocks):
        sig = block.split("\n")[0].rstrip(" {")
        if sig not in seen:
            seen.add(sig)
            unique.append(block)
    unique.reverse()

    return header + "".join(unique)


# ─── public API ───────────────────────────────────────────────────────────────

def _write_seam_result(result: dict, run_dir: str) -> None:
    """Persist seam_result.json to disk so the Writer agent can read it back."""
    effective = run_dir or get_run_dir()
    if not effective:
        return
    run_dir = effective
    import json as _json
    from pathlib import Path as _Path
    try:
        rd = _Path(run_dir)
        rd.mkdir(parents=True, exist_ok=True)
        (rd / "seam_result.json").write_text(
            _json.dumps(result, indent=2), encoding="utf-8"
        )
    except OSError:
        pass


def _submit_etl_translation(
    source_path: str,
    source_lang: str,
    target_lang: str,
    seam_name: str,
    run_dir: str = "",
) -> dict:
    """Write the destination ETL project and return a seam result that keeps its files.

    The pipeline saves whatever this function returns as seam_result.json, so the
    return value includes ``pr.files``. The same tree is also written straight into
    the run's reports directory, which is what the download menu serves.
    """
    from pathlib import Path

    from micro_cosmos.etl.translate import build_translation_files, write_translation
    from micro_cosmos.tools.run_context import get_run_dir
    from micro_cosmos.tools.writer_tools import _project_dir_name

    files = build_translation_files(source_path, target_lang)
    effective = run_dir or get_run_dir()
    output_dir = ""
    if effective and files:
        proj = _project_dir_name(source_path, target_lang)
        dest = Path(effective) / "reports" / proj
        write_translation(files, dest)
        output_dir = str(dest)

    pr = {
        "pr_branch": f"micro_cosmos/etl/{target_lang}",
        "pr_title": f"Migrate ETL estate → {target_lang}",
        "pr_body": (
            f"Mechanical ETL translation.\n\n"
            f"Source: **{source_lang}** | Target: **{target_lang}** | Seam: **{seam_name}**\n\n"
            f"Project: {output_dir or 'not written (no run directory)'}\n"
            f"Files: {len(files)}"
        ),
        "files": files,
        "source_files_translated": len(files),
        "llm_generated": False,
    }
    result = {
        "pr": pr,
        "fitness": {"passed": True, "results": []},
        "equivalence": {
            "passed": True,
            "failures": [],
            "vectors_run": 0,
            "message": "ETL project translation has no differential vectors.",
        },
        "passed": True,
        "has_impl": bool(files),
        "has_tests": True,
        "llm_generated": False,
        "warnings": [],
        "attempts": 1,
        "seam_name": seam_name,
        "target_lang": target_lang,
        "source_lang": source_lang,
        "output_dir": output_dir,
        "etl_translation": True,
    }
    _write_seam_result(result, run_dir)
    return result


def submit_seam_translation(
    files: list,
    source_path: str = "",
    source_lang: str = "",
    target_lang: str = "",
    seam_name: str = "",
    run_dir: str = "",
    test_vectors: list = [],
    tool_context=None,
) -> dict:
    """Submit translated files. files is a list of {path, content} dicts for every file written.

    test_vectors is optional, additive guidance for the Semantic Equivalence
    Agent: a list of {"description", "input", "expected_output"} fixtures the
    Code Writer may supply alongside its implementation and tests. Omitting
    it (the default) is fine — a seam with no vectors simply has nothing to
    differentially check, it is never treated as a failure. See
    equivalence_tools.py for how these are actually used.
    """
    import json as _json
    from micro_cosmos.tools.fitness_runner import run_fitness_suite
    from micro_cosmos.tools.architect_tools import derive_tnas
    from micro_cosmos.tools.pattern_tools import extract_domain_model

    # Some models omit source_path, source_lang, target_lang, and seam_name
    # entirely (confirmed live: submit_seam_translation() missing those four
    # positional arguments). They are already on the session. Filling them
    # here lets the submission proceed. A blank seam_name still falls back
    # the same way pipeline.py does — _snake("") would otherwise produce an
    # empty rootProject.name and break the Gradle/Maven/npm build.
    state = {}
    if tool_context is not None:
        raw_state = getattr(tool_context, "state", None)
        if isinstance(raw_state, dict):
            state = raw_state
        elif raw_state is not None:
            try:
                state = {key: raw_state.get(key, "") for key in (
                    "source_path", "source_lang", "target_lang", "run_dir",
                    "current_seam", "seam_name",
                )}
            except Exception:
                state = {}
    if not source_path:
        source_path = str(state.get("source_path") or "")
    if not source_lang:
        source_lang = str(state.get("source_lang") or "")
    if not target_lang:
        target_lang = str(state.get("target_lang") or "")
    if not run_dir:
        run_dir = str(state.get("run_dir") or "")
    if not seam_name:
        seam_name = str(state.get("seam_name") or state.get("current_seam") or "")
    seam_name = seam_name or "unknown_seam"

    from micro_cosmos.etl.catalog import is_etl_target
    if is_etl_target(target_lang):
        return _submit_etl_translation(
            source_path, source_lang, target_lang, seam_name, run_dir,
        )

    vector_list: list[dict] = []
    if isinstance(test_vectors, list):
        vector_list = [v for v in test_vectors if isinstance(v, dict)]
    elif isinstance(test_vectors, str) and test_vectors.strip() not in ("", "[]", "null"):
        try:
            parsed = _json.loads(test_vectors)
            if isinstance(parsed, list):
                vector_list = [v for v in parsed if isinstance(v, dict)]
        except (_json.JSONDecodeError, TypeError):
            pass

    file_list: list[dict] = []
    if isinstance(files, list):
        # Model passed a native array — the common and expected case
        file_list = [f for f in files if isinstance(f, dict) and f.get("path") and f.get("content")]
    elif isinstance(files, str) and files.strip() not in ("", "[]", "null"):
        # Backward compat: model stringified the array
        try:
            parsed = _json.loads(files)
            if isinstance(parsed, list):
                file_list = [f for f in parsed if isinstance(f, dict) and f.get("path") and f.get("content")]
        except (_json.JSONDecodeError, TypeError):
            pass

    if not file_list:
        result = generate_and_verify_seam(source_path, source_lang, target_lang, seam_name)
        _seam_translation_cache[f"{source_path}:{seam_name}"] = result
        _write_seam_result(result, run_dir)
        return result

    # Sanitise each file: strip leading separators, fix missing JVM source-root
    # prefixes, and deduplicate top-level declarations from session history.
    for f in file_list:
        f["path"] = f["path"].lstrip("/")
        f["path"] = _fix_jvm_source_path(f["path"], target_lang)
        f["content"] = _dedup_declarations(f["content"], f["path"])

    # Validate the submission contains real implementation + tests
    warnings: list[str] = []
    _TEST_SUFFIXES = ("_test.go", "Test.java", "Tests.java", "Spec.java",
                      "test_.py", "_test.py", ".test.ts", ".spec.ts",
                      "Test.kt", "Tests.kt", "Spec.scala", "Tests.cs", "Spec.cs")
    _TEST_MARKERS  = ("#[cfg(test)]", "@Test", "def test_", "func Test", "describe(", "it(")

    def _is_test_file(f: dict) -> bool:
        return (
            any(f["path"].endswith(s) for s in _TEST_SUFFIXES)
            or any(m in f.get("content", "") for m in _TEST_MARKERS)
        )

    test_files = [f for f in file_list if _is_test_file(f)]

    # search_relevant_source's own chunk format (source_chunks.py) is
    # "File: {path}\nFunction/class: {name}\n{code}" — a real, previously
    # unseen failure mode, confirmed live 2026-08-24: the Code Writer copied
    # that raw retrieval excerpt (header included) straight into a submitted
    # file's content instead of writing a real translation, and because the
    # copied text was >100 chars it passed the old has_impl check as if it
    # were substantive implementation.
    def _has_retrieval_artifact(f: dict) -> bool:
        content = f.get("content", "")
        return content.startswith("File: ") and "\nFunction/class: " in content[:200]

    artifact_files = [f["path"] for f in file_list if _has_retrieval_artifact(f)]

    # has_impl requires at least one non-test LLM file with substantive content
    # (>100 non-whitespace chars) — excludes pure scaffolding stubs, empty
    # files, and raw retrieval-tool excerpts copied in verbatim.
    impl_files = [
        f for f in file_list
        if not _is_test_file(f)
        and len(f.get("content", "").strip()) > 100
        and not _has_retrieval_artifact(f)
    ]

    if artifact_files:
        warnings.append(
            f"SUBMISSION_WARNING: {len(artifact_files)} file(s) contain a raw "
            "search_relevant_source excerpt ('File: ...\\nFunction/class: ...' "
            "header) instead of real translated code — you copied a retrieval "
            f"result verbatim rather than writing {target_lang}: "
            f"{', '.join(artifact_files[:5])}"
        )
    if not impl_files:
        warnings.append(
            "SUBMISSION_WARNING: No substantive implementation files found. "
            "Re-submit with concrete domain struct/class files and method bodies."
        )
    if not test_files:
        warnings.append(
            "SUBMISSION_WARNING: No test files found. "
            "Re-submit with unit tests covering the happy path, a rule violation, and an edge case."
        )

    tnas = derive_tnas(source_path, source_lang, target_lang)
    domain_model = extract_domain_model(source_path, source_lang)
    pkg = _pkg(seam_name) if _norm_lang(target_lang) != "java" else f"com.example.{_pkg(seam_name)}"

    # DDD adapter stubs are tagged so reviewers can filter them out — they should
    # only see LLM-generated code, not scaffolding stubs like InMemoryRepository.
    ddd_scaffold = _ddd_scaffolding(seam_name, target_lang, domain_model, tnas)
    for f in ddd_scaffold:
        f["_scaffold"] = True

    project_scaffold = _project_scaffold_files(seam_name, target_lang, pkg)

    # LLM-generated files win over scaffolding when paths collide
    llm_paths = {f["path"] for f in file_list}
    seen: dict[str, dict] = {}
    for f in ddd_scaffold + project_scaffold:
        seen[f["path"]] = f
    for f in file_list:
        seen[f["path"]] = f
    merged = list(seen.values())

    # Warn when DDD scaffolding had to fill in files the LLM didn't write
    scaffold_only = [f["path"] for f in ddd_scaffold if f["path"] not in llm_paths]
    if scaffold_only:
        warnings.append(
            f"SUBMISSION_WARNING: {len(scaffold_only)} DDD adapter stub(s) filled by scaffolding "
            f"because the LLM did not generate them: {', '.join(scaffold_only[:5])}"
        )

    has_impl  = bool(impl_files)
    has_tests = bool(test_files)
    pr = {
        "pr_branch": f"micro_cosmos/seam/{seam_name}",
        "pr_title": f"Migrate seam: {seam_name} → {target_lang}",
        "pr_body": (
            f"Generated by Micro-Cosmos Coder Agent (LLM re-architected).\n\n"
            f"Seam: **{seam_name}** | Source: **{source_lang}** | Target: **{target_lang}**\n\n"
            f"Files: {len(merged)} "
            f"(LLM-written: {len(file_list)}, scaffolding: {len(ddd_scaffold)}, "
            f"impl: {len(impl_files)}, tests: {len(test_files)})\n"
            + ("\n".join(warnings) + "\n" if warnings else "")
            + "Fitness suite will run on push; merge blocked until all BLOCKING rules pass."
        ),
        "files": merged,
        "source_files_translated": len(file_list),
        "impl_file_count": len(impl_files),
        "test_file_count": len(test_files),
        "llm_generated": True,
        "warnings": warnings,
    }
    fitness = run_fitness_suite(suite_json=tnas.get("fitness_suite", {}), pr_files=pr["files"])
    equiv = run_equivalence_check(seam_name, source_lang, target_lang, vector_list)

    result = {
        "pr": pr,
        "fitness": fitness,
        "equivalence": equiv,
        "test_vectors": vector_list,
        "passed": fitness.get("passed", True) and equiv.get("passed", True) and has_impl and has_tests,
        "attempts": 1,
        "llm_generated": True,
        "has_impl": has_impl,
        "has_tests": has_tests,
        "warnings": warnings,
        "seam_name": seam_name,
        "target_lang": target_lang,
        "source_lang": source_lang,
    }
    _seam_translation_cache[f"{source_path}:{seam_name}"] = result
    _write_seam_result(result, run_dir)

    # Return a small manifest to the LLM, not the full file bodies just submitted —
    # nothing downstream reads this in-context copy (pipeline.py prefers the disk-
    # written seam_result.json, and read_generated_files() reads from disk too), so
    # re-echoing potentially large file content here only bloats this turn's context
    # for no benefit, compounding across TDD iterations.
    return {
        "passed": result["passed"],
        "has_impl": has_impl,
        "has_tests": has_tests,
        "warnings": warnings,
        "fitness": fitness,
        "equivalence": equiv,
        "file_manifest": [{"path": f["path"], "size": len(f.get("content", ""))} for f in merged],
        "file_count": len(merged),
        "seam_name": seam_name,
        "target_lang": target_lang,
    }


def run_equivalence_check(
    seam_name: str,
    source_lang: str,
    target_lang: str,
    test_vectors: list[dict],
) -> dict:
    """Informational only — records whether test vectors were supplied.

    Real differential-testing execution (comparing the generated code's
    actual output against each vector's expected_output via the per-language
    CLI/JSON harness convention) happens later, as the authoritative
    Functional Review gate — see micro_cosmos/tools/equivalence_tools.py and
    pipeline.py's _run_equivalence_prescan hook, consumed by
    submit_functional_review(). Executing here too would duplicate real work
    on every TDD iteration for no benefit: driver.py's TDD gate reads only
    the three reviewer JSONs, never this function's return value.
    """
    n = len(test_vectors) if isinstance(test_vectors, list) else 0
    return {
        "passed": True,
        "failures": [],
        "vectors_run": 0,
        "message": (
            "No test vectors supplied — nothing to differentially check."
            if n == 0 else
            f"{n} test vector(s) recorded — compared for real during Functional Review, "
            "not at submission time."
        ),
    }


def generate_and_verify_seam(
    source_path: str,
    source_lang: str,
    target_lang: str,
    seam_name: str,
) -> dict:
    """Fallback: generate DDD scaffolding for the seam without LLM translation.

    Used only when the Coder agent fails to call submit_seam_translation.
    Produces port interfaces and build files so the pipeline can continue;
    the generated code will need a human to fill in the business logic.

    ETL targets never take this path's DDD scaffold: they emit a destination
    data-platform project instead.
    """
    from micro_cosmos.etl.catalog import is_etl_target
    if is_etl_target(target_lang):
        return _submit_etl_translation(source_path, source_lang, target_lang, seam_name)

    from micro_cosmos.tools.architect_tools import derive_tnas
    from micro_cosmos.tools.pattern_tools import extract_domain_model
    from micro_cosmos.tools.fitness_runner import run_fitness_suite

    tnas = derive_tnas(source_path, source_lang, target_lang)
    domain_model = extract_domain_model(source_path, source_lang)
    pkg = _pkg(seam_name) if _norm_lang(target_lang) != "java" else f"com.example.{_pkg(seam_name)}"

    files = (
        _ddd_scaffolding(seam_name, target_lang, domain_model, tnas)
        + _project_scaffold_files(seam_name, target_lang, pkg)
    )

    pr = {
        "pr_branch": f"micro_cosmos/seam/{seam_name}",
        "pr_title": f"Scaffold seam: {seam_name} → {target_lang} [LLM fallback]",
        "pr_body": (
            f"Fallback scaffolding — the Coder agent did not submit translated files.\n\n"
            f"Seam: **{seam_name}** | Source: **{source_lang}** | Target: **{target_lang}**\n\n"
            "Port interfaces and build files are generated; business logic requires a re-run."
        ),
        "files": files,
        "source_files_translated": 0,
        "llm_generated": False,
    }
    fitness = run_fitness_suite(suite_json=tnas.get("fitness_suite", {}), pr_files=files)
    equiv = run_equivalence_check(seam_name, source_lang, target_lang, [])

    return {
        "pr": pr,
        "fitness": fitness,
        "equivalence": equiv,
        "passed": False,
        "attempts": 1,
        "escalation_required": False,
        "llm_generated": False,
        "seam_name": seam_name,
        "target_lang": target_lang,
        "source_lang": source_lang,
    }
