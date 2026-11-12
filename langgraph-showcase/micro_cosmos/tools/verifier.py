"""The Verifier — checks LLM claims against the IR.

This is the architectural primitive that makes hallucination preventable.
Any node ID an agent references must already exist in the IR. Anything
else is rejected and the agent is asked to retry."""

from __future__ import annotations

from micro_cosmos.schema.ir import IRGraph


def verify_against_ir(claimed_node_ids: list[str], ir_json: dict) -> dict:
    """Verify that every claimed node ID exists in the IR.

    Args:
        claimed_node_ids: Node IDs the agent has referenced in its output.
        ir_json: Serialised IRGraph.

    Returns:
        Dict with keys ``ok`` (bool), ``hallucinated`` (list of IDs not in
        the IR), and ``verified_count``.
    """
    ir = IRGraph.model_validate(ir_json)
    known = ir.node_ids()
    hallucinated = [nid for nid in claimed_node_ids if nid not in known]
    return {
        "ok": len(hallucinated) == 0,
        "hallucinated": hallucinated,
        "verified_count": len(claimed_node_ids) - len(hallucinated),
    }
