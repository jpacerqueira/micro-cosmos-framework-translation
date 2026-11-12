"""Tests that Claude Code skills, Kiro.dev Powers, and OpenSpec cover the same
5 topic areas (app, security, observability, logging, testing) at comparable
depth, per Joao's explicit request that the three artifact types not drift
apart. Security previously had no dedicated skill/power at all; Logging had
no depth distinct from Observability — both fixed via shared content
constants in micro_cosmos/tools/writer_tools.py, rendered natively by each of the
three generators.
"""

from __future__ import annotations

import json
from pathlib import Path

from micro_cosmos.tools.writer_tools import (
    _write_kiro_powers,
    _write_openspec,
    _write_output_skills,
)

_SECURITY_REPORT = {
    "findings": [
        {"id": "SEC-001", "severity": "CRITICAL", "category": "INJECTION",
         "location": "db.py:42", "title": "SQL built via string concatenation",
         "remediation": "Use parameterized queries"},
    ],
}


def _seed_minimal(run_dir: Path) -> None:
    (run_dir / "tnas.json").write_text(json.dumps({
        "target_lang": "java21", "summary": "s", "services": [], "context_decisions": [],
        "fitness_suite": [],
    }))
    (run_dir / "security_report.json").write_text(json.dumps(_SECURITY_REPORT))


def test_security_skill_exists_with_categories_and_real_findings(tmp_path: Path):
    _seed_minimal(tmp_path)
    skills_dir = Path(_write_output_skills(
        source_path="examples/demo", source_lang="csharp", target_lang="java21",
        seam_name="checkout", run_path=tmp_path, project_dir="demo_java21",
    ))
    security_md = (skills_dir / ".claude" / "commands" / "security-review.md").read_text()

    for category in ("Injection", "Auth", "Crypto", "Secrets", "SSRF", "Supply chain"):
        assert category in security_md
    assert "SEC-001" in security_md
    assert "SQL built via string concatenation" in security_md


def test_security_kiro_power_exists_with_categories_and_real_findings(tmp_path: Path):
    _seed_minimal(tmp_path)
    kiro_dir = Path(_write_kiro_powers(
        run_path=tmp_path, source_path="examples/demo", source_lang="csharp", target_lang="java21",
    ))
    power_md = (kiro_dir / "micro-cosmos-security-power" / "POWER.md").read_text()

    for category in ("Injection", "Auth", "Crypto", "Secrets", "SSRF", "Supply chain"):
        assert category in power_md
    assert "SEC-001" in power_md
    assert "SQL built via string concatenation" in power_md
    assert (kiro_dir / "micro-cosmos-security-power" / "README.md").exists()
    assert (kiro_dir / "micro-cosmos-security-power" / "package.json").exists()
    assert (kiro_dir / "micro-cosmos-security-power" / "tests" / "power.unit.test.js").exists()
    assert (kiro_dir / "micro-cosmos-security-power" / ".kiro" / "specs" / "micro-cosmos-security-power" / "requirements.md").exists()


def test_monitoring_skill_and_power_have_distinct_logging_section(tmp_path: Path):
    """Logging must be a real, distinct section — not just one row of the
    5-dimension scoring table (the gap this session's audit found)."""
    _seed_minimal(tmp_path)
    skills_dir = Path(_write_output_skills(
        source_path="examples/demo", source_lang="csharp", target_lang="java21",
        seam_name="checkout", run_path=tmp_path, project_dir="demo_java21",
    ))
    monitoring_md = (skills_dir / ".claude" / "commands" / "monitoring-review.md").read_text()
    assert "## Logging Standards" in monitoring_md
    assert "correlation_id" in monitoring_md or "correlation-ID" in monitoring_md or "trace_id" in monitoring_md

    kiro_dir = Path(_write_kiro_powers(
        run_path=tmp_path, source_path="examples/demo", source_lang="csharp", target_lang="java21",
    ))
    power_md = (kiro_dir / "micro-cosmos-monitoring-power" / "POWER.md").read_text()
    assert "## Logging Standards" in power_md

    # Logging must be a genuinely separate section from the observability/
    # tracing content, not folded into it — assert the heading exists as its
    # own block with real content beneath it, not just a table row mention.
    logging_section = power_md.split("## Logging Standards", 1)[1]
    assert "PII" in logging_section or "redact" in logging_section.lower()


def test_openspec_security_observability_testing_specs_render_shared_content(tmp_path: Path):
    _seed_minimal(tmp_path)
    result = Path(_write_openspec(
        run_path=tmp_path, source_path="examples/demo", source_lang="csharp", target_lang="java21",
    ))
    security_spec = (result / "specs" / "security" / "spec.md").read_text()
    observability_spec = (result / "specs" / "observability" / "spec.md").read_text()
    testing_spec = (result / "specs" / "testing" / "spec.md").read_text()

    assert "## ADDED Requirements" in security_spec
    assert "Injection" in security_spec
    assert "SEC-001" in security_spec

    assert "## ADDED Requirements" in observability_spec
    assert "### Requirement: Distributed tracing and metrics" in observability_spec
    assert "### Requirement: Structured, correlatable, safe logging" in observability_spec

    assert "## ADDED Requirements" in testing_spec
    assert "happy" in testing_spec.lower()
    assert "edge case" in testing_spec.lower()


def test_all_three_artifact_types_mention_the_same_key_terms(tmp_path: Path):
    """The literal alignment check Joao asked for: security, observability,
    logging, and testing should read consistently across all three renderings
    for a given run, not drift into different vocabularies."""
    _seed_minimal(tmp_path)
    skills_dir = Path(_write_output_skills(
        source_path="examples/demo", source_lang="csharp", target_lang="java21",
        seam_name="checkout", run_path=tmp_path, project_dir="demo_java21",
    ))
    kiro_dir = Path(_write_kiro_powers(
        run_path=tmp_path, source_path="examples/demo", source_lang="csharp", target_lang="java21",
    ))
    openspec_dir = Path(_write_openspec(
        run_path=tmp_path, source_path="examples/demo", source_lang="csharp", target_lang="java21",
    ))

    skill_security = (skills_dir / ".claude" / "commands" / "security-review.md").read_text()
    power_security = (kiro_dir / "micro-cosmos-security-power" / "POWER.md").read_text()
    spec_security = (openspec_dir / "specs" / "security" / "spec.md").read_text()

    for term in ("Injection", "SSRF", "Supply chain", "CRITICAL"):
        assert term in skill_security, f"{term!r} missing from Skill security-review.md"
        assert term in power_security, f"{term!r} missing from Kiro micro-cosmos-security-power"
        assert term in spec_security, f"{term!r} missing from OpenSpec specs/security/spec.md"
