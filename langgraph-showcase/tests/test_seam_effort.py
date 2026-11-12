"""Tests for effort/story-point estimation in micro_cosmos/tools/seam_tools.py.

_work_for_seam() is the single source of truth for every effort/story_points/risk
number in the app (seam.json, work_streams.json, feature_specs.json, all HTML
reports, the Gate 4.5 dashboard panel, Jira export all copy or sum these values —
see transferable-skills/memory/effort-estimates-doubled.md). Locks in the doubled
story-point scale so a future change to these thresholds is deliberate, not silent.
"""

from __future__ import annotations

import pytest

from micro_cosmos.tools.seam_tools import _work_for_seam


def _seam(stype: str, fan_in: int, **extra) -> dict:
    return {
        "type": stype,
        "evidence": [f"fan-in: {fan_in}"],
        "location": "com.example.Widget",
        **extra,
    }


@pytest.mark.parametrize(
    "fan_in, expected_effort, expected_points",
    [(35, "L", 16), (15, "M", 10), (2, "S", 6)],
)
def test_boundary_seam_effort_and_points(fan_in, expected_effort, expected_points):
    work = _work_for_seam(_seam("boundary", fan_in))
    assert work["effort"] == expected_effort
    assert work["story_points"] == expected_points


@pytest.mark.parametrize(
    "fan_in, expected_effort, expected_points",
    [(60, "L", 16), (20, "M", 10), (8, "S", 6), (1, "XS", 4)],
)
def test_object_seam_effort_and_points(fan_in, expected_effort, expected_points):
    work = _work_for_seam(_seam("object", fan_in))
    assert work["effort"] == expected_effort
    assert work["story_points"] == expected_points


@pytest.mark.parametrize(
    "edges, expected_effort, expected_points",
    [(20, "L", 16), (8, "M", 10), (1, "S", 6)],
)
def test_link_seam_effort_and_points(edges, expected_effort, expected_points):
    work = _work_for_seam(_seam("link", edges, side_a="foo/", side_b="bar/"))
    assert work["effort"] == expected_effort
    assert work["story_points"] == expected_points


def test_preprocessing_seam_effort_and_points():
    work = _work_for_seam(_seam("preprocessing", 0))
    assert work["effort"] == "S"
    assert work["story_points"] == 6


def test_deterministic_mode_effort_passthrough_not_forced_to_medium():
    """Regression: the Feature Specifier's deterministic fallback used to validate
    `effort` against the long-form enum (SMALL/MEDIUM/LARGE/XL), which never matches
    the actual short codes (XS/S/M/L) _work_for_seam produces — silently forcing
    every seam's feature-spec effort to "MEDIUM" regardless of its real tier."""
    work = _work_for_seam(_seam("object", 1))
    assert work["effort"] == "XS"

    effort = (work.get("effort") or "M").upper()
    resolved = effort if effort in ("XS", "S", "M", "L", "XL") else "M"
    assert resolved == "XS"


# ── Message-bus seams (BUG-2) ────────────────────────────────────────────────
# These are scored by ROLE, not fan-in: an event-sourced aggregate with a single
# handler is still among the hardest things in an estate to migrate. Critically,
# _work_for_seam's final `else` is an unguarded catch-all — without an explicit
# `message` branch every one of these silently becomes a config/Settings seam at
# a flat S/6pts with os.environ migration steps.

def _msg_seam(role: str, side_a: str = "PortfolioCreated", side_b: str = "A, B") -> dict:
    return {
        "type": "message",
        "message_role": role,
        "location": f"{side_a} -> {side_b}",
        "side_a": side_a,
        "side_b": side_b,
        "evidence": ["2 component(s) handle 'PortfolioCreated' (event)"],
    }


@pytest.mark.parametrize(
    "role, expected_effort, expected_points, expected_risk",
    [
        ("saga", "L", 16, "high"),
        ("aggregate", "M", 10, "high"),
        ("cross-context", "M", 10, "medium"),
        ("intra-context", "S", 6, "low"),
    ],
)
def test_message_seam_effort_by_role(role, expected_effort, expected_points, expected_risk):
    work = _work_for_seam(_msg_seam(role))
    assert work["effort"] == expected_effort
    assert work["story_points"] == expected_points
    assert work["risk"] == expected_risk


def test_message_seam_does_not_fall_through_to_preprocessing_default():
    """Regression guard for the catch-all `else`: a message seam must never be
    described as a Settings/config extraction."""
    for role in ("saga", "aggregate", "cross-context", "intra-context"):
        work = _work_for_seam(_msg_seam(role))
        assert "Settings" not in work["title"], f"{role} fell through to the config branch"
        assert not any("os.environ" in s for s in work["steps"]), role


def test_message_seam_with_unknown_role_still_avoids_config_branch():
    """An unrecognised role must degrade to the intra-context message tier, not to
    the preprocessing fallback."""
    work = _work_for_seam(_msg_seam("something-new"))
    assert "Settings" not in work["title"]
    assert work["story_points"] == 6


def test_external_integration_is_top_tier():
    work = _work_for_seam(_msg_seam("external-integration", side_a="uli.events.>"))
    assert (work["effort"], work["story_points"], work["risk"]) == ("L", 16, "high")


def test_unknown_seam_type_warns_and_degrades_safely(caplog):
    """The final branch used to be a bare `else` meaning preprocessing, so a future
    seam type — or a rename — was silently scored as a config/Settings extraction.
    It must still return safe defaults (never raise mid-run) but say so loudly."""
    import logging
    with caplog.at_level(logging.WARNING, logger="micro_cosmos.tools.seam_tools"):
        work = _work_for_seam({
            "type": "totally-new-type", "location": "x", "evidence": [],
            "side_a": "a", "side_b": "b",
        })
    assert work["story_points"] == 6      # safe default, no exception
    assert any("unrecognised seam type" in r.message for r in caplog.records)


def test_preprocessing_does_not_warn(caplog):
    import logging
    with caplog.at_level(logging.WARNING, logger="micro_cosmos.tools.seam_tools"):
        _work_for_seam(_seam("preprocessing", 0))
    assert not any("unrecognised seam type" in r.message for r in caplog.records)
