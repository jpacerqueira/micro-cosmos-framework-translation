"""Tests for micro_cosmos.tools.writer_tools._write_openspec — the new OpenSpec
(github.com/Fission-AI/OpenSpec) tree generator, derived from this run's own
feature_specs.json / tnas.json / work_streams.json / security_report.json.

Unlike _write_output_skills/_write_kiro_powers (pure templates, safe to write
once and never touch again), this generator's content is artifact-derived and
must be able to refresh after a Gate 3/4.5 rejection + re-run — see
test_write_openspec_force_overwrites_on_second_call below for the regression
guard on that specific property.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from micro_cosmos.tools.writer_tools import _write_openspec, _openspec_scenario, _truncate_heading, _md_cell

_FEATURE_SPECS = {
    "source_path": "examples/demo-estate",
    "target_lang": "java21",
    "specs": [
        {
            "seam_id": "fraud-scoring", "title": "Fraud scoring endpoint",
            "description": "Score a transaction for fraud risk.",
            "business_value": "Blocks fraudulent transactions before settlement.",
            "acceptance_criteria": [
                "a transaction with risk score above threshold is rejected",
            ],
            "work_stream_id": "ws_01", "work_stream_name": "Fraud Core",
            "api_surface": {"endpoints": [{"method": "POST", "path": "/score"}]},
        },
        {
            "seam_id": "audit-log", "title": "Audit logging",
            "description": "Persist an audit trail for every scoring decision.",
            "business_value": "Regulatory compliance.",
            "acceptance_criteria": ["every scoring decision is persisted with a timestamp"],
            "work_stream_id": "ws_01", "work_stream_name": "Fraud Core",
        },
    ],
}

_TNAS = {
    "target_lang": "java21",
    "summary": "The codebase is split into 3 bounded contexts.",
    "migration_sequence_rationale": "FraudCore must migrate first; nothing else depends on it.",
    "architect_notes": ["FraudCore is the highest-risk context.", "Use CQRS for FraudCore."],
    "services": [
        {"service_id": "FraudCore", "rationale": "core scoring logic",
         "pattern_recommendation": "CQRS with event sourcing", "migration_sequence": 1},
    ],
    "context_decisions": [
        {"context": "FraudCore", "confidence": "HIGH", "communication_style": "sync-http",
         "data_store": "relational", "execution_model": "container", "consistency_model": "STRONG"},
    ],
    # fitness_suite is a serialized FitnessSuite object (functions nested under
    # a "functions" key), not a bare list — matches architect_tools.py's
    # build_canonical_suite(target_lang).model_dump(mode="json") exactly. A
    # live deterministic-mode run caught a real bug where this generator
    # assumed a bare list and crashed with AttributeError on the real shape.
    "fitness_suite": {"functions": [{"id": "F1", "name": "No float for money"}], "target_language": "java21"},
}

_WORK_STREAMS = {
    "work_streams": [
        {"id": "ws_01", "name": "Fraud Core", "seam_ids": ["fraud-scoring", "audit-log"]},
    ],
}

_SECURITY_REPORT = {
    "findings": [
        {"id": "SEC-001", "severity": "HIGH", "category": "SECRETS",
         "location": "config.py:12", "title": "Hardcoded API key",
         "remediation": "Move to env var"},
    ],
}


def _seed(run_dir: Path, *, feature_specs=True, tnas=True, work_streams=True, security=True) -> None:
    if feature_specs:
        (run_dir / "feature_specs.json").write_text(json.dumps(_FEATURE_SPECS))
    if tnas:
        (run_dir / "tnas.json").write_text(json.dumps(_TNAS))
    if work_streams:
        (run_dir / "work_streams.json").write_text(json.dumps(_WORK_STREAMS))
    if security:
        (run_dir / "security_report.json").write_text(json.dumps(_SECURITY_REPORT))


def test_write_openspec_full_tree(tmp_path: Path):
    _seed(tmp_path)
    result = _write_openspec(run_path=tmp_path, source_path=_FEATURE_SPECS["source_path"],
                              source_lang="csharp", target_lang="java21")
    openspec_dir = Path(result)

    assert (openspec_dir / "project.md").exists()
    assert (openspec_dir / "specs" / "fraud-core" / "spec.md").exists()
    assert (openspec_dir / "specs" / "security" / "spec.md").exists()
    assert (openspec_dir / "specs" / "observability" / "spec.md").exists()
    assert (openspec_dir / "specs" / "testing" / "spec.md").exists()
    change_dirs = list((openspec_dir / "changes").iterdir())
    assert len(change_dirs) == 1
    change_dir = change_dirs[0]
    assert (change_dir / "proposal.md").exists()
    assert (change_dir / "design.md").exists()
    assert (change_dir / "tasks.md").exists()
    assert (openspec_dir / "archive").is_dir()
    assert list((openspec_dir / "archive").iterdir()) == []


def test_spec_md_scenario_format_and_verbatim_criteria(tmp_path: Path):
    _seed(tmp_path)
    result = Path(_write_openspec(run_path=tmp_path, source_path=_FEATURE_SPECS["source_path"],
                                   source_lang="csharp", target_lang="java21"))
    spec_md = (result / "specs" / "fraud-core" / "spec.md").read_text()

    assert "## ADDED Requirements" in spec_md
    assert "### Requirement: Fraud scoring endpoint" in spec_md
    assert "#### Scenario:" in spec_md
    assert spec_md.count("- **WHEN**") == spec_md.count("- **THEN**")
    assert spec_md.count("- **WHEN**") >= 2
    # The criterion text must survive verbatim — no fabrication.
    assert "a transaction with risk score above threshold is rejected" in spec_md
    assert "every scoring decision is persisted with a timestamp" in spec_md


def test_tasks_md_numbering_matches_seam_count(tmp_path: Path):
    _seed(tmp_path)
    result = Path(_write_openspec(run_path=tmp_path, source_path=_FEATURE_SPECS["source_path"],
                                   source_lang="csharp", target_lang="java21"))
    change_dir = next((result / "changes").iterdir())
    tasks_md = (change_dir / "tasks.md").read_text()

    checklist_lines = [l for l in tasks_md.splitlines() if l.strip().startswith("- [ ]")]
    total_seams = sum(len(ws["seam_ids"]) for ws in _WORK_STREAMS["work_streams"])
    assert len(checklist_lines) == total_seams
    assert "- [ ] 1.1 Migrate seam `fraud-scoring`" in tasks_md
    assert "- [ ] 1.2 Migrate seam `audit-log`" in tasks_md


def test_proposal_and_design_content_from_tnas(tmp_path: Path):
    _seed(tmp_path)
    result = Path(_write_openspec(run_path=tmp_path, source_path=_FEATURE_SPECS["source_path"],
                                   source_lang="csharp", target_lang="java21"))
    change_dir = next((result / "changes").iterdir())
    proposal = (change_dir / "proposal.md").read_text()
    design = (change_dir / "design.md").read_text()

    assert _TNAS["summary"] in proposal
    assert _TNAS["migration_sequence_rationale"] in proposal
    for note in _TNAS["architect_notes"]:
        assert note in proposal

    assert "FraudCore" in design
    assert "sync-http" in design
    assert "relational" in design
    assert "CQRS with event sourcing" in design
    # Regression guard: fitness_suite is {"functions": [...]}, not a bare
    # list — a live deterministic-mode run caught this generator crashing
    # with AttributeError before this assertion existed.
    assert "No float for money" in design


def test_security_spec_includes_real_findings_when_present(tmp_path: Path):
    _seed(tmp_path)
    result = Path(_write_openspec(run_path=tmp_path, source_path=_FEATURE_SPECS["source_path"],
                                   source_lang="csharp", target_lang="java21"))
    security_spec = (result / "specs" / "security" / "spec.md").read_text()

    assert "SEC-001" in security_spec
    assert "Hardcoded API key" in security_spec
    assert "Move to env var" in security_spec
    # Static baseline categories always render too, regardless of real findings.
    assert "Injection" in security_spec
    assert "Supply chain" in security_spec


def test_graceful_degradation_when_only_tnas_available(tmp_path: Path):
    _seed(tmp_path, feature_specs=False, work_streams=False, security=False)
    result = Path(_write_openspec(run_path=tmp_path, source_path="examples/demo",
                                   source_lang="csharp", target_lang="java21"))

    assert (result / "specs" / "_pending" / "spec.md").exists()
    change_dir = next((result / "changes").iterdir())
    proposal = (change_dir / "proposal.md").read_text()
    assert _TNAS["summary"] in proposal
    # security/observability/testing specs still render — they don't depend on
    # feature_specs.json/tnas.json at all.
    assert (result / "specs" / "security" / "spec.md").exists()
    assert (result / "specs" / "testing" / "spec.md").exists()


def test_raises_file_not_found_when_nothing_available(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        _write_openspec(run_path=tmp_path, source_path="examples/demo",
                         source_lang="csharp", target_lang="java21")


def test_force_overwrites_on_second_call(tmp_path: Path):
    """The core regression guard: unlike Skills/Kiro Powers (frozen once
    written), OpenSpec content must refresh when the underlying artifact
    changes — e.g. after a Gate 3/4.5 rejection and re-run."""
    _seed(tmp_path)
    result = Path(_write_openspec(run_path=tmp_path, source_path=_FEATURE_SPECS["source_path"],
                                   source_lang="csharp", target_lang="java21"))
    spec_md_before = (result / "specs" / "fraud-core" / "spec.md").read_text()
    assert "Fraud scoring endpoint" in spec_md_before

    mutated = json.loads(json.dumps(_FEATURE_SPECS))
    mutated["specs"][0]["title"] = "Renamed Fraud Detection Capability"
    (tmp_path / "feature_specs.json").write_text(json.dumps(mutated))

    _write_openspec(run_path=tmp_path, source_path=_FEATURE_SPECS["source_path"],
                     source_lang="csharp", target_lang="java21")
    spec_md_after = (result / "specs" / "fraud-core" / "spec.md").read_text()

    assert "Renamed Fraud Detection Capability" in spec_md_after
    assert "### Requirement: Fraud scoring endpoint" not in spec_md_after


# ── PR #27 follow-up review regression tests ────────────────────────────────

@pytest.mark.parametrize("criterion,must_contain,must_not_contain", [
    # word-boundary: "then" inside "strengthen"/"lengthen" must not sever the word
    ("the system must strengthen password validation before accepting it",
     ["strengthen"], ["- **WHEN** the system must streng"]),
    ("Latency must not lengthen when load increases",
     ["lengthen"], ["- **WHEN** Latency must not leng"]),
    # case-insensitivity: all-caps WHEN/THEN must not duplicate "WHEN WHEN"
    ("WHEN a payment is submitted THEN it is processed within 2 seconds",
     ["- **WHEN** a payment is submitted", "- **THEN** it is processed within 2 seconds"],
     ["WHEN WHEN"]),
])
def test_openspec_scenario_when_then_split_is_word_boundary_and_case_insensitive(
    criterion, must_contain, must_not_contain,
):
    rendered = _openspec_scenario(criterion, "Title", 0)
    for s in must_contain:
        assert s in rendered, f"expected {s!r} in {rendered!r}"
    for s in must_not_contain:
        assert s not in rendered, f"unexpected {s!r} in {rendered!r}"


def test_truncate_heading_cuts_at_word_boundary_with_ellipsis():
    long_text = "Every public service method creates an OTel span via the tracer API"
    result = _truncate_heading(long_text, limit=40)
    assert len(result) <= 41
    assert result.endswith("…")
    assert not long_text.split()[0] or result.rstrip("…") in long_text
    # never cuts mid-word: the truncated text (minus ellipsis) must end exactly
    # at a word boundary from the original string
    stripped = result.rstrip("…")
    assert long_text.startswith(stripped)
    assert long_text[len(stripped):len(stripped) + 1] in (" ", "")


def test_truncate_heading_leaves_short_text_untouched():
    assert _truncate_heading("short text") == "short text"


def test_md_cell_escapes_pipe_and_handles_none():
    assert _md_cell("SQL | injection") == "SQL \\| injection"
    assert _md_cell(None) == ""
    assert _md_cell(42) == "42"


def test_write_openspec_handles_explicit_nulls_without_crashing_or_leaking_none(tmp_path: Path):
    """None-safety regression: `.get(key, default)`'s default only applies when
    the key is missing, not when the value is explicitly JSON null — several
    spots in the generator used to crash or render the literal text "None"."""
    feature_specs = {
        "source_path": "examples/demo", "target_lang": "java21",
        "specs": [{
            "seam_id": "s1", "title": None, "description": None, "acceptance_criteria": None,
            "work_stream_id": "ws1", "work_stream_name": "Alpha",
            "api_surface": {"endpoints": [None, {"method": None, "path": None}]},
        }],
    }
    (tmp_path / "feature_specs.json").write_text(json.dumps(feature_specs))
    tnas = {"target_lang": "java21", "summary": "s", "context_decisions": None,
            "services": None, "fitness_suite": None}
    (tmp_path / "tnas.json").write_text(json.dumps(tnas))
    security_report = {"findings": [{
        "id": "SEC-1", "severity": "HIGH", "category": "INJECTION",
        "location": "a|b", "title": "SQL | injection", "remediation": None,
    }]}
    (tmp_path / "security_report.json").write_text(json.dumps(security_report))

    result = Path(_write_openspec(run_path=tmp_path, source_path="examples/demo",
                                   source_lang="csharp", target_lang="java21"))

    spec_md = (result / "specs" / "alpha" / "spec.md").read_text()
    assert "None" not in spec_md

    design_md = next((result / "changes").iterdir()).joinpath("design.md").read_text()
    assert "None" not in design_md

    security_md = (result / "specs" / "security" / "spec.md").read_text()
    findings_section = security_md.split("Findings below", 1)[1]
    assert "None" not in findings_section
    # pipe-containing dynamic content must be escaped, not corrupt the table row
    assert "SQL \\| injection" in findings_section
    assert "`a\\|b`" in findings_section


def test_write_openspec_disambiguates_colliding_work_stream_slugs(tmp_path: Path):
    """Two different work streams whose names differ only by case/punctuation
    used to collapse to the same directory slug, and the second one silently
    overwrote the first's spec.md."""
    feature_specs = {
        "source_path": "examples/demo", "target_lang": "java21",
        "specs": [
            {"seam_id": "s1", "title": "T1", "description": "d", "acceptance_criteria": ["c1"],
             "work_stream_id": "ws1", "work_stream_name": "Payment Processing"},
            {"seam_id": "s2", "title": "T2", "description": "d", "acceptance_criteria": ["c2"],
             "work_stream_id": "ws2", "work_stream_name": "payment-processing"},
        ],
    }
    (tmp_path / "feature_specs.json").write_text(json.dumps(feature_specs))

    result = Path(_write_openspec(run_path=tmp_path, source_path="examples/demo",
                                   source_lang="csharp", target_lang="java21"))
    spec_dirs = sorted(p.name for p in (result / "specs").iterdir() if p.is_dir())
    payment_dirs = [d for d in spec_dirs if "payment" in d]
    assert len(payment_dirs) == 2, f"expected 2 disambiguated dirs, got: {spec_dirs}"
    for d in payment_dirs:
        assert (result / "specs" / d / "spec.md").exists()
