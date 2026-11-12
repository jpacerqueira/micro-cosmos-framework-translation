"""Tests for the download-folder classifier in micro_cosmos/web/app.py, extended
from a closed 3-way system (output/skills/kiro) to 4-way (+ openspec).

The real risk being guarded against: a new artifact folder that isn't
explicitly classified falls into the generic `else` branch and gets silently
swept into "Translated code" (output) downloads — see
transferable-skills/memory/cqrs-framework-detection.md-style regressions this
session has already caught elsewhere for the same "generic bucket" pattern.
"""

from __future__ import annotations

from pathlib import Path

from micro_cosmos.web.app import (
    _KIRO_POWERS_FOLDER,
    _OPENSPEC_FOLDER,
    _resolve_zip_target,
    _scan_download_folders,
    _scan_one_dir,
)


def test_scan_one_dir_classifies_all_four_types_separately(tmp_path: Path):
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "my_project_java21").mkdir()          # -> output
    (reports / "my_project_java21_skills").mkdir()    # -> skills
    (reports / _KIRO_POWERS_FOLDER).mkdir()           # -> kiro
    (reports / _OPENSPEC_FOLDER).mkdir()              # -> openspec

    output_name, skills_name, kiro_name, openspec_name = _scan_one_dir(reports)

    assert output_name == "my_project_java21"
    assert skills_name == "my_project_java21_skills"
    assert kiro_name == _KIRO_POWERS_FOLDER
    assert openspec_name == _OPENSPEC_FOLDER
    # The critical regression guard: openspec must NOT be misclassified as output.
    assert output_name != _OPENSPEC_FOLDER


def test_scan_one_dir_openspec_alone_does_not_become_output(tmp_path: Path):
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / _OPENSPEC_FOLDER).mkdir()

    output_name, skills_name, kiro_name, openspec_name = _scan_one_dir(reports)

    assert openspec_name == _OPENSPEC_FOLDER
    assert output_name is None


def test_scan_download_folders_includes_openspec_key(tmp_path: Path):
    (tmp_path / "reports" / _OPENSPEC_FOLDER).mkdir(parents=True)

    folders = _scan_download_folders(tmp_path)

    assert "openspec" in folders
    assert folders["openspec"] == _OPENSPEC_FOLDER


def test_resolve_zip_target_openspec_label_and_404(tmp_path: Path):
    import pytest
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        _resolve_zip_target(tmp_path, "run-1", "openspec")
    assert exc_info.value.status_code == 404
    assert "OpenSpec" in exc_info.value.detail


def test_resolve_zip_target_openspec_success(tmp_path: Path):
    openspec_dir = tmp_path / "reports" / _OPENSPEC_FOLDER
    openspec_dir.mkdir(parents=True)

    target, reports_dir, zip_path = _resolve_zip_target(tmp_path, "run-1", "openspec")

    assert target == openspec_dir
    assert zip_path.name == f"{_OPENSPEC_FOLDER}.zip"
