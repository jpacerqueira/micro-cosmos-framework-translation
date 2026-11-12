"""Structural facts from the IR graph via networkx.

This is the "structure half" of the hybrid retrieval — things that embeddings
cannot answer: fan-in rankings, callers, callees, cycle membership, member counts.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class GraphIndex:
    """Lightweight wrapper around a networkx DiGraph built from ir_graph.json."""

    def __init__(self, g, nodes_by_id: dict[str, dict]) -> None:
        self._g = g
        self._nodes_by_id = nodes_by_id

    # ── Node facts ────────────────────────────────────────────────────────────

    def structural_facts(self, node_id: str) -> dict[str, Any]:
        """Return a dict of structural facts for a node id.

        Always returns a dict (may have is_unknown=True if node_id not in graph).
        """
        if node_id not in self._g:
            return {"node_id": node_id, "is_unknown": True}

        import networkx as nx

        g = self._g
        node_data = self._nodes_by_id.get(node_id, {})
        predecessors = list(g.predecessors(node_id))
        successors = list(g.successors(node_id))

        # Members: nodes that this node DEFINES (children in DEFINES edges)
        members = [
            t
            for _, t, d in g.out_edges(node_id, data=True)
            if d.get("edge_type") == "DEFINES"
        ]

        # Cycle membership via SCC
        sccs = list(nx.strongly_connected_components(g))
        in_cycle = any(node_id in scc and len(scc) > 1 for scc in sccs)
        cycle_peers: list[str] = []
        for scc in sccs:
            if node_id in scc and len(scc) > 1:
                cycle_peers = sorted(scc - {node_id})[:8]
                break

        return {
            "node_id": node_id,
            "name": node_data.get("name", node_id),
            "type": node_data.get("type", ""),
            "source_location": node_data.get("source_location", ""),
            "fan_in": len(predecessors),
            "fan_out": len(successors),
            "callers": predecessors[:10],
            "callees": successors[:10],
            "member_count": len(members),
            "members": members[:12],
            "in_cycle": in_cycle,
            "cycle_peers": cycle_peers,
        }

    def neighbourhood(self, node_id: str, hops: int = 1) -> list[str]:
        """Return node IDs within `hops` edges of `node_id`."""
        if node_id not in self._g:
            return []
        import networkx as nx

        reachable = nx.ego_graph(self._g, node_id, radius=hops, undirected=True)
        return [n for n in reachable.nodes if n != node_id]

    def top_by_fan_in(self, n: int = 10) -> list[tuple[str, int]]:
        """Return [(node_id, fan_in)] sorted descending."""
        return sorted(
            ((nid, self._g.in_degree(nid)) for nid in self._g.nodes),
            key=lambda x: x[1],
            reverse=True,
        )[:n]

    def resolve_node_mentions(self, text: str) -> list[str]:
        """Find node IDs whose names appear (case-insensitive) in `text`."""
        lower = text.lower()
        hits = []
        for nid, data in self._nodes_by_id.items():
            name = data.get("name", "")
            if name and len(name) > 3 and name.lower() in lower:
                hits.append(nid)
        return hits


def build_graph_index(ir_graph: dict) -> GraphIndex:
    """Build a GraphIndex from the raw ir_graph dict."""
    import networkx as nx

    g: nx.DiGraph = nx.DiGraph()
    nodes_by_id: dict[str, dict] = {}

    for node in ir_graph.get("nodes", []):
        nid = node.get("id")
        if nid:
            g.add_node(nid)
            nodes_by_id[nid] = node

    for edge in ir_graph.get("edges", []):
        src = edge.get("source_id")
        tgt = edge.get("target_id")
        etype = edge.get("type", "")
        if src and tgt and src in g and tgt in g:
            g.add_edge(src, tgt, edge_type=etype)

    return GraphIndex(g=g, nodes_by_id=nodes_by_id)


def load_graph_index(run_dir: Path) -> GraphIndex | None:
    """Load ir_graph.json from a run directory and return a GraphIndex.  Returns
    None if the artifact is missing or malformed."""
    p = Path(run_dir) / "ir_graph.json"
    if not p.exists():
        return None
    try:
        ir = json.loads(p.read_text(encoding="utf-8"))
        if not ir.get("nodes"):
            return None
        return build_graph_index(ir)
    except Exception:
        return None
