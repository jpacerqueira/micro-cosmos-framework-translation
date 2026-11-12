"""Deterministic detection of known CQRS/event-sourcing frameworks already in use in a
source codebase — via dependency-manifest coordinates, and, where a concrete source
signal already exists (Axon annotations parsed by observer_tools.py), that too.

Feeds `ir_graph.json`'s `cqrs_framework_hints` field (set by a post-OBSERVER pipeline
hook, mirroring the existing `security_hints` field) so the Architect agent can name a
framework the codebase already commits to instead of reasoning about CQRS/ES from
scratch.
"""

from __future__ import annotations

from micro_cosmos.tools.security_tools import read_manifest_files

# Extension point for adding a new CQRS/ES framework later — append a
# (name, manifest-signature-substrings) entry here. Mirrors the registry
# convention scheduler_tools.py already established for the analogous "one of
# several known formats may be present, try each" detection problem (its
# _SCHEDULERS list of (detect_fn, parse_fn) pairs), rather than an ad hoc
# private dict with no equivalent registration point.
_CQRS_FRAMEWORKS: list[tuple[str, tuple[str, ...]]] = [
    ("AxonFramework", ("org.axonframework",)),
    ("Eventuate", ("io.eventuate",)),
    ("Lagom", ("com.lightbend.lagom",)),
    ("MediatR", ("mediatr",)),
    ("NServiceBus", ("nservicebus",)),
    ("Wolverine", ("wolverinefx",)),
]


def detect_cqrs_frameworks(source_path: str, ir_json: dict) -> dict:
    """Deterministic detection of known CQRS/event-sourcing frameworks already in use in
    the source codebase.

    Two tiers:
    - Manifest coordinates (all frameworks in _CQRS_FRAMEWORKS) — reliable,
      reuses the existing read_manifest_files() dependency-manifest reader. Matched
      case-insensitively against the raw content of pom.xml / build.gradle(.kts) /
      *.csproj / package.json etc. (whichever manifests read_manifest_files finds).
    - Axon source annotations already on the IR graph (is_axon_aggregate, set by
      _parse_java_file only when @Aggregate resolves to an org.axonframework.* import) —
      catches Axon usage even when the manifest itself wasn't discovered/readable.
    """
    manifests = read_manifest_files(source_path)
    detected: dict[str, str] = {}
    for f in manifests.get("files", []):
        content_lower = f.get("content", "").lower()
        for name, signatures in _CQRS_FRAMEWORKS:
            if name in detected:
                continue
            if any(sig in content_lower for sig in signatures):
                detected[name] = f"dependency found in {f.get('path', '?')}"

    # `or {}`, not `.get("attributes", {})` — the default only applies when the key
    # is missing, not when a node's "attributes" is explicitly null (e.g. a
    # hand-edited or non-pydantic-written ir_graph.json).
    axon_aggregate_count = sum(
        1 for n in ir_json.get("nodes", [])
        if (n.get("attributes") or {}).get("is_axon_aggregate") == "true"
    )
    if axon_aggregate_count and "AxonFramework" not in detected:
        detected["AxonFramework"] = f"{axon_aggregate_count} @Aggregate class(es) detected in source"

    return {
        "detected_frameworks": sorted(detected),
        "evidence": detected,
    }
