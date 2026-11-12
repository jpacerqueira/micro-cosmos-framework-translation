"""Tests for Cartographer's deterministic path-rule classifier
(micro_cosmos/tools/cartographer_tools.py::_classify_prog_node), Rule 4
"ExternalIntegrations."

Rule 4 used to match two literal vendor-specific directory names
(/bamboohr/, /slack-api/) baked into example rationale text shown to every
customer regardless of their actual codebase — removed and replaced with
generic third-party-integration category patterns (HR/payroll, ERP/CRM,
communications/alerting) per Joao's request to de-brand generated output.
"""

from __future__ import annotations

import pytest

from micro_cosmos.orchestration.pipeline import _is_valid_bounded_context_map
from micro_cosmos.tools.cartographer_tools import _classify_prog_node, analyse_bounded_contexts
from micro_cosmos.tools.observer_tools import _ir_cache


def test_axonbank_java_layer_split_stays_under_concentration_limit():
    """Regression for the Cartographer crash on examples/AxonFramework_AxonBank:
    Step 1b's over-concentration override used to be a no-op for this estate's
    package shape (org/axonframework/samples/bank/<subpkg>/File.java) — the old
    fixed-3-segment-offset heuristic in _classify_java_layer relabeled all 23
    core-api nodes to the same 'Bank' bucket, leaving concentration at 50% and
    letting Step 7's 40% guard raise unconditionally."""
    result = analyse_bounded_contexts("examples/AxonFramework_AxonBank", "java")
    contexts = result["contexts"]
    prog_total = sum(
        1 for c in contexts for nid in c["node_ids"] if nid.startswith("prog.")
    )
    assert prog_total >= 20  # exercises the 40% guard path at all
    for c in contexts:
        prog_count = sum(1 for nid in c["node_ids"] if nid.startswith("prog."))
        assert prog_count / prog_total <= 0.4, f"{c['name']}: {prog_count}/{prog_total}"
    names = {c["name"] for c in contexts}
    assert {"Bankaccount", "Banktransfer"} <= names


def test_over_concentrated_context_degrades_gracefully_instead_of_raising():
    """Regression for issue #87: when a context still exceeds the 40% concentration cap
    after Step 1b's refinement attempt (here: a bare filename with no '/', which every
    sub-classifier requires to find a domain split), analyse_bounded_contexts() must
    return a flagged artifact instead of raising — a missing bounded_context_map.json
    silently starves context-boundary seam detection and work-stream grouping."""
    source_path, source_lang = "synthetic/over-concentrated-estate", "python"
    key = f"{source_path}:{source_lang}"
    _ir_cache[key] = {
        "nodes": [
            {"id": f"prog.mod{i}", "source_location": "root.py"} for i in range(25)
        ],
        "edges": [],
        "dead_code": [],
    }
    try:
        result = analyse_bounded_contexts(source_path, source_lang)
    finally:
        del _ir_cache[key]

    assert result["contexts"]
    assert result["over_concentrated_contexts"]
    flagged = result["over_concentrated_contexts"][0]
    assert flagged["prog_count"] == flagged["prog_total"] == 25
    assert flagged["pct"] == 100
    assert _is_valid_bounded_context_map(result) is False


@pytest.mark.parametrize("path", [
    "/repo/src/external-api/client.ts",
    "/repo/src/third-party/wrapper.ts",
    "/repo/src/hris/employee_sync.ts",
    "/repo/src/hr-integration/onboarding.ts",
    "/repo/src/payroll/run.ts",
    "/repo/src/erp/inventory.ts",
    "/repo/src/crm/leads.ts",
    "/repo/src/alerts-api/webhook.ts",
    "/repo/src/chatops/bot.ts",
    "/repo/src/comms-api/notifier.ts",
])
def test_generic_integration_patterns_classify_as_external_integrations(path):
    assert _classify_prog_node(path) == "ExternalIntegrations"


@pytest.mark.parametrize("path", [
    "/repo/src/bamboohr/employee.ts",
    "/repo/src/slack-api/client.ts",
])
def test_old_vendor_specific_paths_no_longer_hardcoded_to_external_integrations(path):
    """The classifier is no longer coupled to these two vendor names — a path
    containing them falls through to the generic structural fallback (Rule
    14) instead of being hardcoded to "ExternalIntegrations"."""
    assert _classify_prog_node(path) != "ExternalIntegrations"
