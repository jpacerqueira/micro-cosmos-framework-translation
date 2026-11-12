"""Tests for the openspec -> openapi rename (micro_cosmos/tools/feature_spec_tools.py).

The pipeline's OpenAPI 3.1 export used to be internally named "openspec"
everywhere (function, route, filename) despite already being a genuine
OpenAPI document and already being correctly labeled in the UI ("OpenAPI 3.1
spec"). Renamed to remove the mismatch, and to free up "openspec" for the
new, separate Fission-AI/OpenSpec artifact (see test_openspec_generator.py).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

from micro_cosmos.tools import feature_spec_tools
from micro_cosmos.tools.feature_spec_tools import export_openapi

_REPO_ROOT = Path(__file__).resolve().parents[1]

# Specific patterns from the OLD mislabeling that must never reappear — every
# one of these was renamed to its openapi-equivalent. Deliberately a
# blocklist, not an allowlist: the new, unrelated Fission-AI/OpenSpec
# artifact legitimately introduces many new "openspec" identifiers
# (_write_openspec, /download/openspec, data-folder-type="openspec", the
# OpenSpec menu group, etc.) that this test must not flag.
_FORBIDDEN_OLD_PATTERNS = [
    re.compile(r"export_openspec\b"),
    re.compile(r"/export/openspec\b"),
    re.compile(r"openspec_path\b"),
    # NB: a bare "openspec.yaml" string is deliberately NOT forbidden — the
    # full-zip regenerator legitimately references that exact literal filename
    # to find and delete a *stale* pre-rename copy left over on old runs'
    # disks (see the "stale_openspec_yaml" cleanup block in app.py). That's a
    # new, correct reference to the old name, not a leftover rename bug; the
    # patterns above already cover every old code shape that actually wrote
    # OpenAPI content to a file/route/variable named "openspec".
    #
    # NB: "OpenSpec generation failed" is deliberately NOT forbidden here —
    # the new (correct) openspec zip-generation branch in generate_zip()
    # legitimately raises that exact message for the real OpenSpec artifact.
    # The old OpenAPI-export route's equivalent string was fixed to say
    # "OpenAPI generation failed" (covered by the /export/openspec and
    # export_openspec patterns above, since that whole route was renamed).
    re.compile(r"OpenSpec API documentation"),
    re.compile(r"OpenSpec YAML"),
    re.compile(r"Jira/OpenSpec export"),
]


def test_export_openapi_exists_and_export_openspec_does_not():
    assert hasattr(feature_spec_tools, "export_openapi")
    assert not hasattr(feature_spec_tools, "export_openspec")


def test_export_openapi_produces_valid_openapi_31_yaml(tmp_path: Path):
    (tmp_path / "feature_specs.json").write_text(json.dumps({
        "source_path": "examples/demo",
        "target_lang": "java21",
        "specs": [
            {
                "seam_id": "checkout", "title": "Checkout",
                "description": "Checkout flow", "acceptance_criteria": [],
                "work_stream_name": "core",
                "api_surface": {"endpoints": [{"method": "POST", "path": "/checkout"}]},
            },
        ],
    }))

    yaml_text = export_openapi(str(tmp_path))
    doc = yaml.safe_load(yaml_text)

    assert doc["openapi"] == "3.1.0"
    assert "info" in doc
    assert "/checkout" in doc["paths"]


def test_export_openapi_raises_when_no_feature_specs(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        export_openapi(str(tmp_path))


@pytest.mark.parametrize("relpath", [
    "micro_cosmos/tools/feature_spec_tools.py",
    "micro_cosmos/web/app.py",
    "micro_cosmos/web/templates/run.html",
    "micro_cosmos/web/static/js/dashboard.js",
    "scripts/generate_feature_specs.js",
    "micro_cosmos/agents/feature_specifier.py",
    "micro_cosmos/orchestration/pipeline.py",
])
def test_no_stray_openspec_naming_for_the_openapi_artifact(relpath: str):
    """None of the old, mislabeled OpenAPI-as-"openspec" identifiers may
    survive — every one was renamed to its openapi-equivalent. Does NOT
    assert "openspec" is absent entirely: the new, unrelated Fission-AI/
    OpenSpec artifact legitimately introduces plenty of "openspec" text of
    its own (see test_openspec_generator.py / test_download_folder_classification.py)."""
    text = (_REPO_ROOT / relpath).read_text(encoding="utf-8")
    for line_no, line in enumerate(text.splitlines(), start=1):
        for pattern in _FORBIDDEN_OLD_PATTERNS:
            assert not pattern.search(line), (
                f"{relpath}:{line_no} still matches the old mislabeled pattern "
                f"{pattern.pattern!r} — rename incomplete: {line!r}"
            )
