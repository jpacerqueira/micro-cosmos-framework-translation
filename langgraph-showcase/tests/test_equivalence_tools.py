"""Semantic Equivalence Agent tests — differential testing against
Code-Writer-supplied test vectors (see micro_cosmos/tools/equivalence_tools.py).
"""

from __future__ import annotations

import json
import shutil

import pytest

from micro_cosmos.tools.coder_tools import run_equivalence_check, submit_seam_translation
from micro_cosmos.tools.coding_loop_tools import submit_functional_review
from micro_cosmos.tools.equivalence_tools import _values_match, run_accumulated_equivalence_check


# ─── _values_match ─────────────────────────────────────────────────────────

def test_values_match_numeric_tolerance() -> None:
    assert _values_match(90.0000001, 90) is True
    assert _values_match(110.0, 90) is False


def test_values_match_bool_is_not_numeric() -> None:
    # bool is a subclass of int in Python — must not let True == 1 slip through.
    assert _values_match(True, 1) is False
    assert _values_match(True, True) is True


def test_values_match_dict_requires_same_keys() -> None:
    assert _values_match({"a": 1}, {"a": 1, "b": 2}) is False
    assert _values_match({"a": 1, "b": 2}, {"a": 1, "b": 2}) is True


def test_values_match_list_is_order_sensitive() -> None:
    assert _values_match([1, 2, 3], [3, 2, 1]) is False
    assert _values_match([1, 2, 3], [1, 2, 3]) is True


# ─── run_equivalence_check (coder_tools.py) — now non-executing/informational ──

def test_run_equivalence_check_no_vectors_is_not_a_failure() -> None:
    """This used to unconditionally return passed=False — dead code
    downstream, but visible in the Code Writer's own tool response. Confirms
    the fix: no vectors means nothing to check, not an automatic failure."""
    result = run_equivalence_check("seam1", "cobol", "java21", [])
    assert result["passed"] is True


def test_run_equivalence_check_with_vectors_does_not_execute_anything() -> None:
    """Real execution happens later (the pipeline hook), never at submission
    time — this call must stay a cheap, static record, not run code."""
    result = run_equivalence_check("seam1", "cobol", "java21", [{"input": 1, "expected_output": 1}])
    assert result["passed"] is True
    assert result["vectors_run"] == 0


# ─── run_accumulated_equivalence_check ─────────────────────────────────────

def test_run_accumulated_equivalence_check_no_seam_result_yet(tmp_path) -> None:
    result = run_accumulated_equivalence_check(str(tmp_path), "python")
    assert result["ran"] is False
    assert (tmp_path / "equivalence_result.json").exists()


def test_run_accumulated_equivalence_check_no_vectors_supplied(tmp_path) -> None:
    (tmp_path / "seam_result.json").write_text(json.dumps({
        "pr": {"files": [{"path": "src/x.py", "content": "x = 1\n"}]},
    }))
    result = run_accumulated_equivalence_check(str(tmp_path), "python")
    assert result["ran"] is False


def test_run_accumulated_equivalence_check_unwired_language_is_not_a_failure(tmp_path) -> None:
    """Rust (and any other language absent from _INVOKERS) is an honest
    no-op today — vectors present but not evaluated must not be reported as
    ran=True/passed=False."""
    (tmp_path / "seam_result.json").write_text(json.dumps({
        "target_lang": "rust",
        "test_vectors": [{"description": "x", "input": 1, "expected_output": 1}],
        "pr": {"files": [{"path": "src/lib.rs", "content": "fn x() {}\n"}]},
    }))
    result = run_accumulated_equivalence_check(str(tmp_path), "rust")
    assert result["ran"] is False
    assert "not yet wired up" in result["message"]


def test_run_accumulated_equivalence_check_catches_real_python_bug(tmp_path) -> None:
    seam_result = {
        "target_lang": "python",
        "test_vectors": [
            {"description": "10% discount on 100", "input": {"total": 100, "pct": 10}, "expected_output": 90},
        ],
        "pr": {
            "files": [
                {"path": "src/pricing.py", "content": (
                    "def apply_discount(total, pct):\n"
                    "    return total + (total * pct / 100)\n"  # BUG: should subtract
                )},
                {"path": "equivalence_harness.py", "content": (
                    "import sys, json\n"
                    "from src.pricing import apply_discount\n\n"
                    "data = json.load(sys.stdin)\n"
                    "print(json.dumps(apply_discount(data['total'], data['pct'])))\n"
                )},
            ]
        },
    }
    (tmp_path / "seam_result.json").write_text(json.dumps(seam_result))

    result = run_accumulated_equivalence_check(str(tmp_path), "python")

    assert result["ran"] is True
    assert result["passed"] is False
    assert result["vectors_run"] == 1
    assert "expected 90" in result["failures"][0]


def test_run_accumulated_equivalence_check_passes_correct_python_impl(tmp_path) -> None:
    seam_result = {
        "target_lang": "python",
        "test_vectors": [
            {"description": "10% discount on 100", "input": {"total": 100, "pct": 10}, "expected_output": 90},
        ],
        "pr": {
            "files": [
                {"path": "src/pricing.py", "content": (
                    "def apply_discount(total, pct):\n"
                    "    return total - (total * pct / 100)\n"
                )},
                {"path": "equivalence_harness.py", "content": (
                    "import sys, json\n"
                    "from src.pricing import apply_discount\n\n"
                    "data = json.load(sys.stdin)\n"
                    "print(json.dumps(apply_discount(data['total'], data['pct'])))\n"
                )},
            ]
        },
    }
    (tmp_path / "seam_result.json").write_text(json.dumps(seam_result))

    result = run_accumulated_equivalence_check(str(tmp_path), "python")

    assert result["ran"] is True
    assert result["passed"] is True


@pytest.mark.skipif(shutil.which("mvn") is None, reason="Maven not installed")
def test_run_accumulated_equivalence_check_catches_real_java_bug(tmp_path) -> None:
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
</project>
"""
    harness = """\
import com.example.Pricing;
import java.util.Scanner;

public class EquivalenceHarness {
    public static void main(String[] args) {
        Scanner sc = new Scanner(System.in).useDelimiter("\\\\A");
        String input = sc.hasNext() ? sc.next() : "{}";
        double total = Double.parseDouble(input.replaceAll(".*\\"total\\"\\\\s*:\\\\s*([0-9.]+).*", "$1"));
        double pct = Double.parseDouble(input.replaceAll(".*\\"pct\\"\\\\s*:\\\\s*([0-9.]+).*", "$1"));
        System.out.println(Pricing.applyDiscount(total, pct));
    }
}
"""
    seam_result = {
        "target_lang": "java",
        "test_vectors": [
            {"description": "10% discount on 100", "input": {"total": 100.0, "pct": 10.0}, "expected_output": 90.0},
        ],
        "pr": {
            "files": [
                {"path": "pom.xml", "content": pom},
                {"path": "src/main/java/com/example/Pricing.java", "content": (
                    "package com.example;\n"
                    "public class Pricing {\n"
                    "    public static double applyDiscount(double total, double pct) {\n"
                    "        return total + (total * pct / 100);\n"  # BUG
                    "    }\n"
                    "}\n"
                )},
                {"path": "src/main/java/EquivalenceHarness.java", "content": harness},
            ]
        },
    }
    (tmp_path / "seam_result.json").write_text(json.dumps(seam_result))

    result = run_accumulated_equivalence_check(str(tmp_path), "java")

    assert result["ran"] is True
    assert result["passed"] is False
    assert result["vectors_run"] == 1


@pytest.mark.skipif(shutil.which("gradle") is None, reason="Gradle not installed")
def test_run_accumulated_equivalence_check_catches_real_kotlin_bug(tmp_path) -> None:
    gradle_build = """\
plugins { kotlin("jvm") version "2.0.0" }
group = "com.example.pricing"
version = "0.1.0"
repositories { mavenCentral() }
dependencies { implementation(kotlin("stdlib")) }
"""
    settings = 'rootProject.name = "pricing"\n'
    pricing = """\
class Pricing {
    fun applyDiscount(total: Double, pct: Double): Double {
        return total + (total * pct / 100)  // BUG: should subtract
    }
}
"""
    harness = """\
import java.io.BufferedReader
import java.io.InputStreamReader

fun main() {
    val input = BufferedReader(InputStreamReader(System.`in`)).readText()
    val total = Regex("\\"total\\"\\\\s*:\\\\s*([0-9.]+)").find(input)!!.groupValues[1].toDouble()
    val pct = Regex("\\"pct\\"\\\\s*:\\\\s*([0-9.]+)").find(input)!!.groupValues[1].toDouble()
    println(Pricing().applyDiscount(total, pct))
}
"""
    seam_result = {
        "target_lang": "kotlin",
        "test_vectors": [
            {"description": "10% discount on 100", "input": {"total": 100.0, "pct": 10.0}, "expected_output": 90.0},
        ],
        "pr": {
            "files": [
                {"path": "build.gradle.kts", "content": gradle_build},
                {"path": "settings.gradle.kts", "content": settings},
                {"path": "src/main/kotlin/Pricing.kt", "content": pricing},
                {"path": "src/main/kotlin/EquivalenceHarness.kt", "content": harness},
            ]
        },
    }
    (tmp_path / "seam_result.json").write_text(json.dumps(seam_result))

    result = run_accumulated_equivalence_check(str(tmp_path), "kotlin")

    assert result["ran"] is True
    assert result["passed"] is False
    assert result["vectors_run"] == 1


@pytest.mark.skipif(shutil.which("dotnet") is None, reason=".NET SDK not installed")
def test_run_accumulated_equivalence_check_catches_real_csharp_bug(tmp_path) -> None:
    pricing_csproj = (
        '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
        "<TargetFramework>net8.0</TargetFramework><Nullable>enable</Nullable>"
        "<ImplicitUsings>enable</ImplicitUsings><RootNamespace>Pricing</RootNamespace>"
        "</PropertyGroup></Project>\n"
    )
    pricing_cs = (
        "namespace Pricing;\n"
        "public class PricingService {\n"
        "    public static double ApplyDiscount(double total, double pct) {\n"
        "        return total + (total * pct / 100);\n"  # BUG
        "    }\n"
        "}\n"
    )
    harness = (
        "using System.Text.Json;\n"
        "using Pricing;\n\n"
        "public static class EquivalenceHarness {\n"
        "    public static void Main() {\n"
        "        string input = Console.In.ReadToEnd();\n"
        "        var doc = JsonDocument.Parse(input);\n"
        "        double total = doc.RootElement.GetProperty(\"total\").GetDouble();\n"
        "        double pct = doc.RootElement.GetProperty(\"pct\").GetDouble();\n"
        "        Console.WriteLine(PricingService.ApplyDiscount(total, pct));\n"
        "    }\n"
        "}\n"
    )
    seam_result = {
        "target_lang": "csharp",
        "test_vectors": [
            {"description": "10% discount on 100", "input": {"total": 100.0, "pct": 10.0}, "expected_output": 90.0},
        ],
        "pr": {
            "files": [
                {"path": "Pricing.csproj", "content": pricing_csproj},
                {"path": "PricingService.cs", "content": pricing_cs},
                {"path": "EquivalenceHarness.cs", "content": harness},
            ]
        },
    }
    (tmp_path / "seam_result.json").write_text(json.dumps(seam_result))

    result = run_accumulated_equivalence_check(str(tmp_path), "csharp")

    assert result["ran"] is True
    assert result["passed"] is False
    assert result["vectors_run"] == 1


def test_invoke_kotlin_reports_missing_harness(tmp_path) -> None:
    from micro_cosmos.tools.equivalence_tools import _invoke_kotlin
    ok, _stdout, error = _invoke_kotlin(tmp_path, "{}")
    assert ok is False
    assert "EquivalenceHarness.kt" in error


def test_invoke_kotlin_reports_missing_build_file(tmp_path) -> None:
    from micro_cosmos.tools.equivalence_tools import _invoke_kotlin
    kt_dir = tmp_path / "src" / "main" / "kotlin"
    kt_dir.mkdir(parents=True)
    (kt_dir / "EquivalenceHarness.kt").write_text("fun main() {}\n")
    ok, _stdout, error = _invoke_kotlin(tmp_path, "{}")
    assert ok is False
    assert "build.gradle" in error


def test_invoke_csharp_reports_missing_harness(tmp_path) -> None:
    from micro_cosmos.tools.equivalence_tools import _invoke_csharp
    ok, _stdout, error = _invoke_csharp(tmp_path, "{}")
    assert ok is False
    assert "EquivalenceHarness.cs" in error


# ─── submit_functional_review force-correction ─────────────────────────────

def test_submit_functional_review_forced_to_fail_by_real_equivalence_mismatch(tmp_path) -> None:
    (tmp_path / "equivalence_result.json").write_text(json.dumps({
        "ran": True,
        "passed": False,
        "vectors_run": 1,
        "failures": ["10% discount on 100: expected 90, got 110.0"],
        "message": "1/1 vector(s) mismatched.",
    }))

    result = submit_functional_review(findings=[], passed=True, run_dir=str(tmp_path))

    assert result["passed"] is False
    assert result["severity_counts"]["BLOCKER"] == 1
    assert any(f["source_behavior"] == "<real equivalence check>" for f in result["findings"])


def test_submit_functional_review_unaffected_when_equivalence_passed(tmp_path) -> None:
    (tmp_path / "equivalence_result.json").write_text(json.dumps({
        "ran": True, "passed": True, "vectors_run": 1, "failures": [], "message": "1/1 matched.",
    }))
    result = submit_functional_review(findings=[], passed=True, run_dir=str(tmp_path))
    assert result["passed"] is True


def test_submit_functional_review_unaffected_when_equivalence_never_ran(tmp_path) -> None:
    (tmp_path / "equivalence_result.json").write_text(json.dumps({
        "ran": False, "passed": True, "vectors_run": 0, "failures": [],
        "message": "No test vectors supplied for this seam — nothing to differentially check.",
    }))
    result = submit_functional_review(findings=[], passed=True, run_dir=str(tmp_path))
    assert result["passed"] is True


def test_submit_functional_review_forced_to_fail_when_code_does_not_compile(tmp_path) -> None:
    """"Does this behave like the source" is unanswerable for code that
    doesn't even compile. Before this fix, a seam with a real compile
    failure but no test vectors (equivalence_result.json: ran=false,
    passed=true — an honest "nothing to check") had nothing forcing
    Functional Review's own passed=True verdict to be corrected."""
    (tmp_path / "test_execution.json").write_text(json.dumps({
        "ran": True, "passed": False,
        "message": "e: Application.kt:1:11 Redeclaration: interface Foo",
        "target_lang": "kotlin", "exec_result": None,
    }))
    (tmp_path / "equivalence_result.json").write_text(json.dumps({
        "ran": False, "passed": True, "vectors_run": 0, "failures": [],
        "message": "No test vectors supplied for this seam — nothing to differentially check.",
    }))

    result = submit_functional_review(findings=[], passed=True, run_dir=str(tmp_path))

    assert result["passed"] is False
    assert result["severity_counts"]["BLOCKER"] == 1
    assert any(f["source_behavior"] == "<real execution>" for f in result["findings"])


def test_submit_functional_review_unaffected_when_test_execution_never_ran(tmp_path) -> None:
    result = submit_functional_review(findings=[], passed=True, run_dir=str(tmp_path))
    assert result["passed"] is True


# ─── submit_seam_translation threads test_vectors through to seam_result.json ──

def test_submit_seam_translation_persists_test_vectors(tmp_path) -> None:
    from micro_cosmos.tools.run_context import set_run_dir
    set_run_dir(str(tmp_path))

    vectors = [{"description": "x", "input": 1, "expected_output": 1}]
    submit_seam_translation(
        files=[
            {"path": "src/x.py", "content": "def f(a):\n    return a\n" * 20},
            {"path": "tests/test_x.py", "content": "def test_f():\n    assert True\n"},
        ],
        source_path="examples/legacy_estate",
        source_lang="python",
        target_lang="python",
        seam_name="seam1",
        run_dir=str(tmp_path),
        test_vectors=vectors,
    )

    written = json.loads((tmp_path / "seam_result.json").read_text())
    assert written["test_vectors"] == vectors


def test_submit_seam_translation_defaults_test_vectors_to_empty(tmp_path) -> None:
    """Must have a concrete Python default (not None) — an LLM caller that
    omits this optional parameter must not have its whole tool call silently
    dropped by ADK (the same footgun already fixed for the three review
    submit_* functions)."""
    from micro_cosmos.tools.run_context import set_run_dir
    set_run_dir(str(tmp_path))

    result = submit_seam_translation(
        files=[
            {"path": "src/x.py", "content": "def f(a):\n    return a\n" * 20},
            {"path": "tests/test_x.py", "content": "def test_f():\n    assert True\n"},
        ],
        source_path="examples/legacy_estate",
        source_lang="python",
        target_lang="python",
        seam_name="seam1",
        run_dir=str(tmp_path),
    )
    assert result["passed"] is not None  # ran to completion, no missing-arg crash
    written = json.loads((tmp_path / "seam_result.json").read_text())
    assert written["test_vectors"] == []
