"""Tests for scripts/generate_full_report.js and its app.py wiring.

generate_full_report.js is a plain Node script (same (run_dir, out) CLI
convention as every other scripts/generate_*.js), so its content is tested by
actually invoking `node` against a seeded fixture run directory — there is no
Python-side logic to unit test directly for the generator itself.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "generate_full_report.js"


def _run_generator(run_dir: Path, out_path: Path) -> subprocess.CompletedProcess:
    # Mirrors _generate_report_file()'s out_path.parent.mkdir(...) in app.py —
    # the real call site always ensures this before invoking any generator script.
    out_path.parent.mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        ["node", str(SCRIPT), str(run_dir), str(out_path)],
        capture_output=True, text=True, timeout=30,
    )


def _seed_partial_fixture(run_dir: Path) -> None:
    """Seeds a deliberately partial run: some JSON present, some missing;
    2 of the 13 HTML reports pre-generated, the rest absent; a Kiro folder
    with 2 powers; an OpenSpec folder with project.md + one spec."""
    reports_dir = run_dir / "reports"
    reports_dir.mkdir(parents=True)

    (run_dir / "run_meta.json").write_text(json.dumps({
        "source_path": "examples/legacy_estate", "source_lang": "cobol", "target_lang": "go",
        "skip_llm": True,
    }))
    (run_dir / "ir_graph.json").write_text(json.dumps({"nodes": [], "edges": []}))
    (run_dir / "seam.json").write_text(json.dumps({"seams": []}))
    # tnas.json, security_report.json, etc. deliberately absent.

    (reports_dir / "hotspots.html").write_text("<html><body>fake hotspots</body></html>")
    (reports_dir / "security-report.html").write_text("<html><body>fake security</body></html>")

    kiro_dir = reports_dir / "kiro-dev-powers-app-modernization"
    (kiro_dir / "micro-cosmos-security-power").mkdir(parents=True)
    (kiro_dir / "micro-cosmos-security-power" / "POWER.md").write_text("# Security Power\ncontent here")
    (kiro_dir / "micro-cosmos-monitoring-power").mkdir(parents=True)
    (kiro_dir / "micro-cosmos-monitoring-power" / "POWER.md").write_text("# Monitoring Power\ncontent here")

    openspec_dir = reports_dir / "openspec"
    (openspec_dir / "specs" / "security").mkdir(parents=True)
    (openspec_dir / "project.md").write_text("# Project\ncontext here")
    (openspec_dir / "specs" / "security" / "spec.md").write_text("## ADDED Requirements\n### Requirement: X")


def test_generator_runs_clean_and_status_table_reflects_partial_fixture(tmp_path: Path):
    run_dir = tmp_path / "run"
    _seed_partial_fixture(run_dir)
    out_path = run_dir / "reports" / "full-app-migration-report.html"

    result = _run_generator(run_dir, out_path)
    assert result.returncode == 0, result.stderr
    assert out_path.exists()

    html = out_path.read_text()
    assert "[object Object]" not in html
    assert "undefined" not in html.replace("Underworld", "")  # sanity, not a real risk here but cheap to assert

    # Present items marked Generated, with a clickable link where applicable
    assert '<a href="hotspots.html">Hotspots &amp; coupling</a>' in html
    assert '<a href="security-report.html">Source security analysis</a>' in html
    assert "micro-cosmos-security-power" in html
    assert "micro-cosmos-monitoring-power" in html

    # Absent items marked Not yet generated
    assert html.count("Not yet generated") > 0
    assert "Executive summary</td><td><span style=\"color:#91969C;\">Not yet generated" in html

    # Iframe embedding only for present reports
    assert '<iframe src="hotspots.html"' in html
    assert '<iframe src="executive-summary.html"' not in html

    # Raw markdown content embedded for present Kiro/OpenSpec files
    assert "content here" in html
    assert "### Requirement: X" in html

    # Source -> target languages surfaced prominently near the top, not buried
    # in a sub-report — read straight from run_meta.json.
    assert '<div class="metric-value">cobol</div>' in html
    assert '<div class="metric-value">go</div>' in html


def test_generator_handles_completely_empty_run_dir(tmp_path: Path):
    """No prerequisite artifacts at all — must not crash, everything reads
    as 'Not yet generated' (matches the tolerant/best-effort convention
    already used by monitoring.html)."""
    run_dir = tmp_path / "empty-run"
    run_dir.mkdir()
    out_path = run_dir / "reports" / "full-app-migration-report.html"

    result = _run_generator(run_dir, out_path)
    assert result.returncode == 0, result.stderr
    html = out_path.read_text()
    assert "Not yet generated" in html


def test_full_report_is_last_key_in_file_to_script(monkeypatch, tmp_path: Path):
    import micro_cosmos.settings as settings_mod
    s = settings_mod.Settings(skip_llm=True, runs_dir=str(tmp_path))
    monkeypatch.setattr(settings_mod, "_settings", s)

    import importlib
    app_module = importlib.import_module("micro_cosmos.web.app")
    assert list(app_module._FILE_TO_SCRIPT.keys())[-1] == "full-app-migration-report.html"
    assert "full-app-migration-report.html" not in app_module._REPORT_PREREQUISITES


async def test_run_file_always_regenerates_full_report(monkeypatch, tmp_path: Path):
    import micro_cosmos.settings as settings_mod
    s = settings_mod.Settings(skip_llm=True, runs_dir=str(tmp_path))
    monkeypatch.setattr(settings_mod, "_settings", s)

    import importlib
    app_module = importlib.import_module("micro_cosmos.web.app")

    run_id = "regen-test"
    run_dir = tmp_path / run_id
    _seed_partial_fixture(run_dir)
    (run_dir / "run_meta.json").write_text(json.dumps({
        "source_path": "examples/legacy_estate", "source_lang": "cobol", "target_lang": "go",
        "skip_llm": True,
    }))

    stale_path = run_dir / "reports" / "full-app-migration-report.html"
    stale_path.write_text("STALE-SENTINEL-CONTENT")

    run = app_module.Run(run_id, "examples/legacy_estate", "cobol", "go", skip_llm=True)
    app_module.RUNS[run_id] = run

    await app_module.run_file(run_id, "full-app-migration-report.html")

    assert "STALE-SENTINEL-CONTENT" not in stale_path.read_text()
    assert "Not yet generated" in stale_path.read_text() or "Generated" in stale_path.read_text()
