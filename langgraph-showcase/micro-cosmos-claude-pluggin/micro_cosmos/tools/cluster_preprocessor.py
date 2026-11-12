"""Clustering pre-processor — runs before the BCM agent.

Uses pure path-partitioning: nodes are grouped by directory tree position.
No graph traversal is used to form initial groups — edges are only consulted
in step 4 to decide which small group to merge into a larger neighbour.
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

# Greedy: strips everything up to and including the LAST anchor directory.
_ANCHORS = re.compile(r'^.*(?:src|app|lib|functions|packages|services)/')

TARGET_MAX_CLUSTERS = 30


def _dir_key(source_location: str, depth: int = 2) -> tuple:
    """
    Parse source_location into a directory key of `depth` segments.

    Strip everything up to and including the LAST anchor directory
    (src/, app/, lib/, functions/, packages/, services/), then take
    the first `depth` directory segments from the remaining path
    (filename excluded).

    Examples (depth=2):
      /repo/app/src/features/timesheets/page.ts
        -> remaining: features/timesheets/page.ts
        -> ("features", "timesheets")

      /repo/functions/src/api/nestjs/features/allocation/service.ts
        -> remaining: api/nestjs/features/allocation/service.ts
        -> ("api", "nestjs")

      /repo/app/e2e/admin/client-sectors.spec.ts
        -> remaining: e2e/admin/client-sectors.spec.ts
        -> ("e2e", "admin")
    """
    fpath = source_location.rsplit(":", 1)[0] if ":" in source_location else source_location
    stripped = _ANCHORS.sub("", fpath)
    if stripped == fpath:
        # No anchor found — use last depth+1 parts
        parts = Path(fpath).parts
        stripped = "/".join(parts[max(0, len(parts) - depth - 1):])

    segments = [s for s in Path(stripped).parts[:-1] if s]
    return tuple(segments[i] if i < len(segments) else "root" for i in range(depth))


def build_clusters(nodes, edges, min_nodes=5, max_nodes=200):
    """
    Partition PROGRAM nodes into clusters using only file-path structure.

    Steps 1-3: pure dict assignment based on directory path. No graph traversal.
    Step 4:    edges used only to pick a merge target for undersized groups.
    Step 5:    extra merges to bring total cluster count within TARGET_MAX_CLUSTERS.
    """
    # Deduplicate PROGRAM nodes by ID (multiple index.ts files share the same
    # prog.Index ID — keep first occurrence of each unique ID).
    seen_ids: set = set()
    prog_nodes = []
    for n in nodes:
        if n.get("type") == "PROGRAM" and n["id"] not in seen_ids:
            seen_ids.add(n["id"])
            prog_nodes.append(n)

    prog_ids    = {n["id"] for n in prog_nodes}
    nodes_by_id = {n["id"]: n for n in prog_nodes}

    call_edges = [
        e for e in edges
        if e.get("type") == "CALLS"
        and e["source_id"] in prog_ids
        and e["target_id"] in prog_ids
    ]

    # Step 1-2: assign by (primary_dir, secondary_dir) — dict assignment, no traversal
    groups: dict = defaultdict(list)
    for n in prog_nodes:
        key = _dir_key(n.get("source_location", ""), depth=2)
        groups[key].append(n["id"])

    # Step 3: split groups exceeding max_nodes by adding tertiary_dir
    depth = 2
    while any(len(v) > max_nodes for v in groups.values()):
        depth += 1
        new_groups: dict = defaultdict(list)
        for key, nids in groups.items():
            if len(nids) <= max_nodes:
                new_groups[key] = nids
                continue
            for nid in nids:
                loc = nodes_by_id.get(nid, {}).get("source_location", "")
                new_key = _dir_key(loc, depth=depth)
                new_groups[new_key].append(nid)
        groups = new_groups
        if depth > 8:
            break

    # Helper: cross-group CALLS edge count
    def _inter_edges(a, b):
        a, b = set(a), set(b)
        return sum(
            1 for e in call_edges
            if (e["source_id"] in a and e["target_id"] in b)
            or (e["source_id"] in b and e["target_id"] in a)
        )

    # Step 4: merge groups smaller than min_nodes
    changed = True
    while changed:
        changed = False
        for sk in sorted(groups, key=lambda k: len(groups[k])):
            if sk not in groups or len(groups[sk]) >= min_nodes:
                continue
            others = [k for k in groups if k != sk]
            if not others:
                break
            best = max(others, key=lambda k: _inter_edges(groups[sk], groups[k]))
            if _inter_edges(groups[sk], groups[best]) > 0:
                target = best
            else:
                same = [k for k in others if k[0] == sk[0]]
                target = max(same, key=lambda k: len(groups[k])) if same \
                    else max(others, key=lambda k: len(groups[k]))
            groups[target] = groups[target] + groups.pop(sk)
            changed = True
            break

    # Step 5: merge smallest pairs until cluster count <= TARGET_MAX_CLUSTERS
    while len(groups) > TARGET_MAX_CLUSTERS:
        sorted_keys = sorted(groups, key=lambda k: len(groups[k]))
        merged = False
        for sk in sorted_keys:
            if sk not in groups:
                continue
            candidates = [
                k for k in groups
                if k != sk and len(groups[k]) + len(groups[sk]) <= max_nodes
            ]
            if not candidates:
                continue
            # Prefer same primary_dir, then highest edge count, then largest
            same = [k for k in candidates if k[0] == sk[0]]
            if same:
                target = max(same, key=lambda k: (
                    _inter_edges(groups[sk], groups[k]), len(groups[k])
                ))
            else:
                target = max(candidates, key=lambda k: (
                    _inter_edges(groups[sk], groups[k]), len(groups[k])
                ))
            groups[target] = groups[target] + groups.pop(sk)
            merged = True
            break
        if not merged:
            break  # Cannot reduce further without violating max_nodes

    # If everything merged into one group, split it in half so the validator
    # (and the Cartographer) always receive at least two clusters.
    if len(groups) == 1:
        key, nids = next(iter(groups.items()))
        nids_sorted = sorted(nids)
        mid = len(nids_sorted) // 2
        groups = {
            (key[0], key[1] if len(key) > 1 else "a"): nids_sorted[:mid],
            (key[0], key[1] + "_b" if len(key) > 1 else "b"): nids_sorted[mid:],
        }

    return list(groups.values())


def build_cluster_candidates(ir_path, out_path, min_nodes=5, max_nodes=200):
    """Read ir_graph.json, partition by path, write cluster_candidates.json."""
    ir          = json.loads(Path(ir_path).read_text(encoding="utf-8"))
    nodes_raw   = ir.get("nodes", [])
    edges_raw   = ir.get("edges", [])

    # Deduplicated PROGRAM ID set (matches what the validator expects)
    seen: set = set()
    prog_ids = set()
    nodes_by_id = {}
    for n in nodes_raw:
        if n.get("type") == "PROGRAM" and n["id"] not in seen:
            seen.add(n["id"])
            prog_ids.add(n["id"])
            nodes_by_id[n["id"]] = n

    call_edges = [
        e for e in edges_raw
        if e.get("type") == "CALLS"
        and e["source_id"] in prog_ids
        and e["target_id"] in prog_ids
    ]

    # BCM validator uses max(2, len(ir_prog) // 50) as its minimum context size.
    # Since clusters map 1:1 to contexts, enforce the same floor here so clusters
    # never exit this step smaller than what validate_bcm will accept.
    min_nodes = max(min_nodes, len(prog_ids) // 50)

    partitions = build_clusters(nodes_raw, edges_raw, min_nodes, max_nodes)

    fan_in: dict = defaultdict(int)
    for e in call_edges:
        fan_in[e["target_id"]] += 1

    prog_ds: dict = defaultdict(set)
    for e in edges_raw:
        if e.get("type") == "DEFINES" and e["source_id"] in prog_ids:
            tgt_id = e["target_id"]
            tgt = next((n for n in nodes_raw if n["id"] == tgt_id), None)
            if tgt and tgt.get("type") == "DATA_STRUCTURE":
                prog_ds[e["source_id"]].add(tgt_id)

    clusters = []
    for idx, node_ids in enumerate(sorted(partitions, key=len, reverse=True), 1):
        cluster_id = f"cluster_{idx:03d}"

        domain_hints = sorted({
            nodes_by_id.get(nid, {}).get("attributes", {}).get("domain", "")
            for nid in node_ids
        } - {""})

        node_summaries = {
            nid: (nodes_by_id.get(nid, {}).get("summary") or "")[:100]
            for nid in node_ids
        }

        inbound = sum(fan_in.get(nid, 0) for nid in node_ids)

        ds_counter: dict = defaultdict(int)
        for nid in node_ids:
            for ds_id in prog_ds.get(nid, set()):
                ds_counter[ds_id] += 1
        shared_ds = sorted(ds for ds, cnt in ds_counter.items() if cnt >= 2)

        sample_loc  = nodes_by_id.get(node_ids[0], {}).get("source_location", "")
        primary_dir = "/".join(_dir_key(sample_loc, depth=2))

        clusters.append({
            "cluster_id":             cluster_id,
            "node_ids":               sorted(node_ids),
            "primary_directory":      primary_dir,
            "node_summaries":         node_summaries,
            "domain_hints":           domain_hints,
            "inbound_edge_count":     inbound,
            "shared_data_structures": shared_ds,
        })

    result = {
        "total_program_nodes": len(prog_ids),
        "cluster_count":       len(clusters),
        "min_nodes_enforced":  min_nodes,
        "max_nodes_enforced":  max_nodes,
        "clusters":            clusters,
    }

    Path(out_path).write_text(json.dumps(result, indent=2), encoding="utf-8")

    _log.info(
        "cluster_preprocessor: %d clusters, %d PROGRAM nodes",
        len(clusters), len(prog_ids),
    )
    for c in clusters:
        top_hint = c["domain_hints"][0] if c["domain_hints"] else "—"
        _log.debug(
            "  %-14s %-30s %6d  %s",
            c["cluster_id"], c["primary_directory"], len(c["node_ids"]), top_hint,
        )

    return result
