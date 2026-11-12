"""Tool tests — IR shape, verifier behaviour, fitness runner."""

from __future__ import annotations

import json
import shutil

import pytest

from micro_cosmos.fitness import build_canonical_suite
from micro_cosmos.tools.fitness_runner import (
    _gradle_cmd,
    assemble_accumulated_pr_files,
    run_accumulated_test_execution,
    run_fitness_suite,
)
from micro_cosmos.tools.observer_tools import (
    catalogue_dead_code,
    parse_source_estate,
    scan_performance_anti_patterns,
)
from micro_cosmos.tools.verifier import verify_against_ir

ESTATE = "examples/legacy_estate"


def test_parse_source_estate_returns_valid_ir() -> None:
    ir = parse_source_estate(ESTATE, "python")
    assert "nodes" in ir
    assert "edges" in ir
    assert any(n["id"] == "prog.CreditDecisioner" for n in ir["nodes"])


def test_parse_source_estate_extracts_call_edges() -> None:
    ir = parse_source_estate(ESTATE, "python")
    called = {e["target_id"] for e in ir["edges"]}
    assert "prog.CustomerReader" in called
    assert "prog.DecisionWriter" in called


def test_dead_code_includes_legacy_archiver() -> None:
    ir = parse_source_estate(ESTATE, "python")
    dc = catalogue_dead_code(ir)
    assert "dead_code" in dc
    # All findings must have required fields
    for finding in dc["dead_code"]:
        assert "node_id" in finding
        assert "reason" in finding
        assert "confidence" in finding


def test_dead_code_excludes_called_nodes() -> None:
    ir = parse_source_estate(ESTATE, "python")
    dc = catalogue_dead_code(ir)
    dead_ids = {f["node_id"] for f in dc["dead_code"]}
    assert "prog.CustomerReader" not in dead_ids
    assert "prog.DecisionWriter" not in dead_ids


def test_performance_scan_finds_sql_in_loop() -> None:
    ir = parse_source_estate(ESTATE, "python")
    result = scan_performance_anti_patterns(ir)
    assert "performance_findings" in result
    for finding in result["performance_findings"]:
        assert "pattern" in finding
        assert "severity" in finding
        assert "node_id" in finding


def test_verifier_rejects_hallucinated_nodes() -> None:
    ir = parse_source_estate(ESTATE, "python")
    result = verify_against_ir(["prog.CreditDecisioner", "prog.NotARealNode"], ir)
    assert result["ok"] is False
    assert "prog.NotARealNode" in result["hallucinated"]


def test_verifier_accepts_only_real_nodes() -> None:
    ir = parse_source_estate(ESTATE, "python")
    result = verify_against_ir(["prog.CreditDecisioner"], ir)
    assert result["ok"] is True
    assert result["hallucinated"] == []


def test_fitness_suite_passes_clean_code() -> None:
    suite = build_canonical_suite("python3").model_dump(mode="json")
    pr_files = [
        {"path": "src/credit/__init__.py", "content": "from decimal import Decimal\n"},
    ]
    result = run_fitness_suite(suite, pr_files)
    assert result["passed"] is True


def test_fitness_suite_catches_float_money() -> None:
    suite = build_canonical_suite("java21").model_dump(mode="json")
    pr_files = [
        {"path": "src/Credit.java", "content": "double amount = 100.50;\n"},
    ]
    result = run_fitness_suite(suite, pr_files)
    assert result["passed"] is False
    failed = [r for r in result["results"] if not r["passed"]]
    assert any(r["function_id"] == "NO_FLOAT_ON_MONETARY" for r in failed)


# ─── assemble_accumulated_pr_files / run_accumulated_test_execution ───────────

def test_assemble_accumulated_pr_files_first_seam_has_no_prior_output(tmp_path) -> None:
    """No reports/project_dir.txt yet — nothing to accumulate against, so the
    current seam's own files pass through unchanged."""
    current = [{"path": "src/foo.py", "content": "x = 1\n"}]
    result = assemble_accumulated_pr_files(str(tmp_path), current)
    assert result == [{"path": "src/foo.py", "content": "x = 1\n"}]


def test_assemble_accumulated_pr_files_merges_prior_seam_and_current_seam(tmp_path) -> None:
    proj_dir = "demo_project_python"
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "project_dir.txt").write_text(proj_dir)
    project_root = tmp_path / "reports" / proj_dir
    project_root.mkdir()
    (project_root / "existing.py").write_text("# from a prior seam\n")

    current = [{"path": "existing.py", "content": "# untouched by current seam\n"},
               {"path": "new_file.py", "content": "# from the current seam\n"}]
    result = assemble_accumulated_pr_files(str(tmp_path), current)
    by_path = {f["path"]: f["content"] for f in result}

    assert by_path["existing.py"] == "# untouched by current seam\n"
    assert by_path["new_file.py"] == "# from the current seam\n"


def test_assemble_accumulated_pr_files_merges_build_file_dependencies(tmp_path) -> None:
    """package.json is a recognised build file — a colliding path must merge
    dependencies (writer_tools._merge_build_file), not let the current seam's
    version silently overwrite the prior seam's."""
    proj_dir = "demo_project_ts"
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "project_dir.txt").write_text(proj_dir)
    project_root = tmp_path / "reports" / proj_dir
    project_root.mkdir()
    (project_root / "package.json").write_text(
        json.dumps({"dependencies": {"left-pad": "1.0.0"}})
    )

    current = [{"path": "package.json", "content": json.dumps({"dependencies": {"decimal.js": "10.0.0"}})}]
    result = assemble_accumulated_pr_files(str(tmp_path), current)
    merged = json.loads(next(f["content"] for f in result if f["path"] == "package.json"))

    assert merged["dependencies"]["left-pad"] == "1.0.0"
    assert merged["dependencies"]["decimal.js"] == "10.0.0"


def test_run_accumulated_test_execution_no_seam_result_yet(tmp_path) -> None:
    result = run_accumulated_test_execution(str(tmp_path), "python")
    assert result["ran"] is False
    assert (tmp_path / "test_execution.json").exists()


def test_run_accumulated_test_execution_runs_real_pytest(tmp_path) -> None:
    seam_result = {
        "pr": {
            "files": [
                {"path": "src/calc.py", "content": "def add(a, b):\n    return a + b\n"},
                {"path": "tests/test_calc.py", "content": (
                    "from src.calc import add\n\n"
                    "def test_add():\n    assert add(1, 2) == 3\n"
                )},
            ]
        }
    }
    (tmp_path / "seam_result.json").write_text(json.dumps(seam_result))

    result = run_accumulated_test_execution(str(tmp_path), "python")

    assert result["ran"] is True
    assert result["passed"] is True
    written = json.loads((tmp_path / "test_execution.json").read_text())
    assert written["ran"] is True


def test_gradle_cmd_falls_back_to_cli_when_no_wrapper(tmp_path) -> None:
    """Regression lock for the Kotlin/Gradle bug: _TEST_COMMANDS used to
    hardcode "./gradlew" unconditionally, which no scaffold generator ever
    emits — every Kotlin test run silently soft-passed via FileNotFoundError.
    No wrapper present here, so this must resolve to the installed `gradle` CLI."""
    assert _gradle_cmd(tmp_path) == ["gradle", "test", "-q"]


def test_gradle_cmd_prefers_wrapper_when_present(tmp_path) -> None:
    (tmp_path / "gradlew").write_text("#!/bin/sh\n")
    assert _gradle_cmd(tmp_path) == ["./gradlew", "test", "-q"]


@pytest.mark.skipif(shutil.which("mvn") is None, reason="Maven not installed")
def test_run_accumulated_test_execution_runs_real_maven(tmp_path) -> None:
    """End-to-end lock for the Java/Maven path — Maven is not installed by
    default in dev/CI images that lack the Dockerfile's tarball install, so
    this is skipped rather than failed when absent, mirroring _run_tests'
    own graceful toolchain-missing behaviour."""
    pom = """\
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>pricing</artifactId>
  <version>0.1.0-SNAPSHOT</version>
  <properties>
    <maven.compiler.source>17</maven.compiler.source>
    <maven.compiler.target>17</maven.compiler.target>
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
"""
    seam_result = {
        "pr": {
            "files": [
                {"path": "pom.xml", "content": pom},
                {"path": "src/main/java/com/example/Calc.java", "content": (
                    "package com.example;\n"
                    "public class Calc { public static int add(int a, int b) { return a + b; } }\n"
                )},
                {"path": "src/test/java/com/example/CalcTest.java", "content": (
                    "package com.example;\n"
                    "import org.junit.jupiter.api.Test;\n"
                    "import static org.junit.jupiter.api.Assertions.assertEquals;\n"
                    "class CalcTest {\n"
                    "    @Test void addsTwoNumbers() { assertEquals(5, Calc.add(2, 3)); }\n"
                    "}\n"
                )},
            ]
        }
    }
    (tmp_path / "seam_result.json").write_text(json.dumps(seam_result))

    result = run_accumulated_test_execution(str(tmp_path), "java")

    assert result["ran"] is True
    assert result["passed"] is True


@pytest.mark.skipif(shutil.which("dotnet") is None, reason=".NET SDK not installed")
def test_run_accumulated_test_execution_runs_real_dotnet(tmp_path) -> None:
    """End-to-end lock for the C#/.NET path — specifically for the fix that
    replaced an invalid bare "-q" flag (not a real dotnet-CLI option) with
    "-v minimal", which was silently breaking every fresh C# build with an
    opaque MSBuild error before a single test ever ran."""
    csproj = (
        '<Project Sdk="Microsoft.NET.Sdk">'
        "<PropertyGroup><TargetFramework>net8.0</TargetFramework></PropertyGroup>"
        "<ItemGroup>"
        '<PackageReference Include="Microsoft.NET.Test.Sdk" Version="17.10.0" />'
        '<PackageReference Include="xunit" Version="2.8.1" />'
        '<PackageReference Include="xunit.runner.visualstudio" Version="2.8.1" />'
        "</ItemGroup></Project>\n"
    )
    seam_result = {
        "pr": {
            "files": [
                {"path": "Calc.csproj", "content": csproj},
                {"path": "Calc.cs", "content": (
                    "namespace CalcApp;\n"
                    "public static class Calc { public static int Add(int a, int b) => a + b; }\n"
                )},
                {"path": "CalcTest.cs", "content": (
                    "using Xunit;\nusing CalcApp;\n"
                    "public class CalcTest {\n"
                    "    [Fact]\n"
                    "    public void AddsTwoNumbers() => Assert.Equal(5, Calc.Add(2, 3));\n"
                    "}\n"
                )},
            ]
        }
    }
    (tmp_path / "seam_result.json").write_text(json.dumps(seam_result))

    result = run_accumulated_test_execution(str(tmp_path), "csharp")

    assert result["ran"] is True
    assert result["passed"] is True
