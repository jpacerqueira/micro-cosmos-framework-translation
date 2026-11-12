import json, logging, re
from typing import List, Union

RISK_ORDER = {'HIGH': 2, 'MEDIUM': 1, 'LOW': 0}
_log = logging.getLogger(__name__)


def _load(source: Union[str, dict]) -> dict:
    """Accept either a file path (str/Path) or an already-loaded dict."""
    if isinstance(source, dict):
        return source
    with open(source) as f:
        return json.load(f)


def validate_clusters(ir_path: str, cluster_path: str) -> None:
    with open(ir_path) as f: ir = json.load(f)
    with open(cluster_path) as f: data = json.load(f)

    ir_prog = {n['id'] for n in ir['nodes'] if n['type'] == 'PROGRAM'}
    clusters = data['clusters']
    errors = []

    seen = {}
    for c in clusters:
        for nid in c['node_ids']:
            if nid not in ir_prog:
                errors.append(f"{c['cluster_id']}: node '{nid}' not in IR")
            if nid in seen:
                errors.append(f"{c['cluster_id']}: node '{nid}' already in {seen[nid]}")
            seen[nid] = c['cluster_id']

    missing = ir_prog - set(seen)
    if missing:
        errors.append(f"{len(missing)} PROGRAM nodes not in any cluster: {list(missing)[:5]}...")

    total_nodes = sum(len(c['node_ids']) for c in clusters)
    min_size = max(2, total_nodes // 200)
    max_size = max(50, total_nodes // 3)

    # Allow a single cluster only for genuinely tiny repos (< 10 PROGRAM nodes).
    if len(clusters) < 2 and len(ir_prog) >= 10:
        errors.append(f"Cluster count {len(clusters)}: need at least 2")
    if total_nodes and len(clusters) > total_nodes * 0.5:
        errors.append(f"Cluster count {len(clusters)} exceeds 50% of node count — too fine-grained")
    if total_nodes and (total_nodes / len(clusters)) > 300:
        errors.append(f"Average cluster size {total_nodes//len(clusters)} too large — check path-stripping")

    for c in clusters:
        n = len(c['node_ids'])
        if n < min_size:
            errors.append(f"{c['cluster_id']}: {n} nodes below minimum {min_size}")
        if n > max_size:
            errors.append(f"{c['cluster_id']}: {n} nodes above maximum {max_size}")

    if errors:
        raise ValueError("Cluster validation failed:\n" + "\n".join(errors))
    _log.debug("clusters OK — %d clusters, %d nodes", len(clusters), len(seen))


def validate_bcm(ir_path, bcm_path) -> None:
    ir  = _load(ir_path)
    bcm = _load(bcm_path)

    ir_prog = {n['id'] for n in ir['nodes'] if n['type'] == 'PROGRAM'}
    contexts = bcm['contexts']
    # Floor scales with IR size so small repos aren't penalised
    min_ctx_size = max(2, len(ir_prog) // 50)
    errors = []

    names = [c['name'] for c in contexts]
    for name in names:
        if names.count(name) > 1:
            errors.append(f"Duplicate context name: '{name}'")

    for c in contexts:
        for nid in c['node_ids']:
            if nid not in ir_prog:
                errors.append(f"Context '{c['name']}': node '{nid}' not in IR")
        if len(c['node_ids']) < min_ctx_size:
            errors.append(
                f"Context '{c['name']}': only {len(c['node_ids'])} nodes (min {min_ctx_size})"
            )
        if c['migration_risk'] not in RISK_ORDER:
            errors.append(f"Context '{c['name']}': invalid risk '{c['migration_risk']}'")

    if errors:
        raise ValueError("BCM validation failed:\n" + "\n".join(errors))
    _log.debug("BCM OK — %d contexts", len(contexts))


def collect_tnas_errors(tnas: dict, bcm: dict) -> List[str]:
    valid = {c['name'] for c in bcm['contexts']}
    all_referenced = []
    errors = []

    for svc in tnas.get('services', []):
        node_ids = svc.get('node_ids', [])
        if not node_ids:
            errors.append(f"Service '{svc.get('name','?')}': empty node_ids")
        for nid in node_ids:
            if nid not in valid:
                errors.append(f"Service '{svc.get('name','?')}': phantom context '{nid}'")
            all_referenced.append(nid)
        if svc.get('migration_risk') not in RISK_ORDER:
            errors.append(f"Service '{svc.get('name','?')}': invalid risk")

    unrepresented = valid - set(all_referenced)
    if unrepresented:
        errors.append(f"BCM contexts missing from TNAS: {sorted(unrepresented)}")

    duplicates = [n for n in all_referenced if all_referenced.count(n) > 1]
    if duplicates:
        errors.append(f"Contexts appear in multiple services: {list(set(duplicates))}")

    return errors


def validate_tnas(bcm_path, tnas_path) -> None:
    """Accept file paths or already-loaded dicts."""
    bcm  = _load(bcm_path)
    tnas = _load(tnas_path)
    errors = collect_tnas_errors(tnas, bcm)
    if errors:
        raise ValueError("TNAS validation failed:\n" + "\n".join(errors))
    _log.debug("TNAS OK — %d services", len(tnas['services']))
