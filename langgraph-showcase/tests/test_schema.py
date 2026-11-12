"""Schema tests — SHA stamping and round-trip."""

from __future__ import annotations

from micro_cosmos.schema import (
    BoundedContext,
    Confidence,
    IREdge,
    IREdgeType,
    IRGraph,
    IRNode,
    IRNodeType,
)


def test_ir_node_sha_is_stable() -> None:
    n1 = IRNode(
        id="prog.A", type=IRNodeType.PROGRAM, name="A", source_location="a.src:1"
    ).stamp()
    n2 = IRNode(
        id="prog.A", type=IRNodeType.PROGRAM, name="A", source_location="a.src:1"
    ).stamp()
    assert n1.sha == n2.sha
    assert len(n1.sha) == 16


def test_ir_graph_roundtrip() -> None:
    g = IRGraph(
        nodes=[
            IRNode(id="prog.A", type=IRNodeType.PROGRAM, name="A", source_location="a.src:1"),
            IRNode(id="data.X", type=IRNodeType.DATA_ITEM, name="X", source_location="a.src:5"),
        ],
        edges=[
            IREdge(source_id="prog.A", target_id="data.X", type=IREdgeType.READS),
        ],
        source_lang="cobol",
    )
    g.stamp()
    raw = g.model_dump_json()
    g2 = IRGraph.model_validate_json(raw)
    assert g2.sha == g.sha
    assert g2.node_ids() == {"prog.A", "data.X"}


def test_bounded_context_confidence_round_trip() -> None:
    ctx = BoundedContext(
        name="Credit Decisioning",
        node_ids=["prog.A", "prog.B"],
        confidence=Confidence.HIGH,
        rationale="all three analyses agree",
    ).stamp()
    raw = ctx.model_dump_json()
    ctx2 = BoundedContext.model_validate_json(raw)
    assert ctx2.confidence == Confidence.HIGH
    assert ctx2.sha == ctx.sha
