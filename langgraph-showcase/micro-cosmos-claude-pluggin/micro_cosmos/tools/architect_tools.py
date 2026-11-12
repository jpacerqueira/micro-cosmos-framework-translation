"""Architect Agent tools — Technology-Neutral Architecture Specification derivation."""

from __future__ import annotations


# ── Migration risk table (keyed by BCM context name) ─────────────────────────

_MIGRATION_RISK: dict[str, tuple[str, str]] = {
    "Authentication": (
        "HIGH",
        "Authentication boundaries must preserve token validity and session state "
        "across the migration boundary.",
    ),
    "ExternalIntegrations": (
        "HIGH",
        "External API contracts are not under our control and may behave differently "
        "under Java HTTP client semantics.",
    ),
    "Messaging": (
        "HIGH",
        "Event ordering and delivery guarantees differ between Node.js Cloud Functions "
        "and Java runtimes.",
    ),
    "BackendCore": (
        "MEDIUM",
        "Core API surface is large; interface contracts must be preserved exactly to "
        "avoid breaking downstream consumers.",
    ),
    "DataTransfer": (
        "MEDIUM",
        "DTO serialisation behaviour differs between TypeScript and Java; field "
        "nullability and date formats require explicit mapping.",
    ),
    "ProjectManagement": (
        "MEDIUM",
        "Business logic density is high; domain invariants must be verified by the "
        "fitness suite after migration.",
    ),
    "People": (
        "MEDIUM",
        "People data intersects with authentication and project assignment; "
        "cross-context dependencies require care.",
    ),
    "Admin": (
        "MEDIUM",
        "Admin operations have wide blast radius; incorrect migration could affect "
        "all tenants.",
    ),
    "Frontend": (
        "LOW",
        "Frontend code is not migrated to Java; this context is extracted as a seam "
        "boundary only.",
    ),
    "TestUnit": (
        "LOW",
        "Test doubles and unit specs are rewritten in the target language as part of "
        "normal migration.",
    ),
    "TestE2E": (
        "LOW",
        "E2E tests run against the deployed interface and are language-agnostic.",
    ),
    "Configuration": (
        "LOW",
        "Configuration extraction is a prerequisite step with no runtime risk.",
    ),
    "Shared": (
        "LOW",
        "Residual utilities with no direct domain ownership; low coupling.",
    ),
}

# Async contexts override the default sync-http communication style
_ASYNC_CONTEXTS = frozenset({"Messaging", "ExternalIntegrations"})


def derive_tnas(source_path: str, source_lang: str, target_lang: str) -> dict:
    """Return the TNAS for source_path migrated to target_lang.

    Structure:
    - services[]: one entry per BCM context — service_id, node_ids (from BCM),
      rationale, migration_risk, risk_reason.
    - context_decisions[]: one entry per context with architectural decisions.
    - valid_context_names: list of context names for the Architect agent to reference.
    - available_contexts: list of {name, risk, node_count} for the agent's rationale.
    - contradictions[], summary, target_lang, fitness_suite included.
    """
    from micro_cosmos.tools.cartographer_tools import analyse_bounded_contexts
    from micro_cosmos.fitness import build_canonical_suite

    bc = analyse_bounded_contexts(source_path, source_lang)
    fitness_suite = build_canonical_suite(target_lang).model_dump(mode="json")

    contexts = bc.get("contexts", [])

    # ── Services ──────────────────────────────────────────────────────────────
    services = []
    for ctx in contexts:
        ctx_name = ctx["name"]
        risk, reason = _MIGRATION_RISK.get(ctx_name, ("LOW", "No specific risk identified."))
        services.append({
            "service_id": ctx_name,
            "node_ids":   ctx["node_ids"],
            "rationale":  ctx["rationale"],
            "migration_risk": risk,
            "risk_reason": reason,
        })

    # ── Validation ────────────────────────────────────────────────────────────
    ctx_names_in_bcm = {ctx["name"] for ctx in contexts}
    for svc in services:
        assert svc["service_id"] in ctx_names_in_bcm, \
            f"service_id '{svc['service_id']}' not in BCM contexts"
        assert svc["service_id"], "service_id must not be empty"
        assert not any("*" in nid for nid in svc["node_ids"]), \
            f"service '{svc['service_id']}' contains glob strings in node_ids"

    # ── Context decisions ─────────────────────────────────────────────────────
    context_decisions = []
    for ctx in contexts:
        ctx_name = ctx["name"]
        comm_style = (
            "async-event" if ctx_name in _ASYNC_CONTEXTS else "sync-http"
        )
        decision = {
            "context":             ctx_name,
            "confidence":          ctx["confidence"],
            "service_granularity": "micro-service",
            "communication_style": comm_style,
            "data_store":          "relational",
            "execution_model":     "container",
            "consistency_model":   "STRONG",
        }
        context_decisions.append(decision)

    from micro_cosmos.etl.catalog import is_etl_target
    if is_etl_target(target_lang):
        store = {
            "databricks": "databricks",
            "snowflake_dbt": "snowflake",
            "bigquery_dataform": "bigquery",
        }.get(target_lang, "warehouse")
        execution = {
            "databricks": "sql-warehouse",
            "snowflake_dbt": "dbt",
            "bigquery_dataform": "dataform",
        }.get(target_lang, "warehouse")
        for decision in context_decisions:
            decision["service_granularity"] = "table"
            decision["communication_style"] = "async-event"
            decision["data_store"] = store
            decision["execution_model"] = execution
            decision["consistency_model"] = "EVENTUAL"
            decision["target_platform"] = target_lang

    # ── Fields for the Architect LLM agent to reason about ───────────────────
    valid_context_names = sorted(ctx_names_in_bcm)
    available_contexts = [
        {
            "name":        ctx["name"],
            "risk":        _MIGRATION_RISK.get(ctx["name"], ("LOW", ""))[0],
            "node_count":  len(ctx["node_ids"]),
            "rationale":   ctx["rationale"],
        }
        for ctx in contexts
    ]

    high_risk = [c["name"] for c in available_contexts if c["risk"] == "HIGH"]
    med_risk  = [c["name"] for c in available_contexts if c["risk"] == "MEDIUM"]
    if is_etl_target(target_lang):
        summary = (
            f"Warehouse models are grouped into {len(contexts)} layers and migrated to "
            f"{target_lang}. Each layer is a table target with its own effort. "
            f"High-risk layers: {', '.join(high_risk) or 'none'}. "
            f"Medium-risk layers: {', '.join(med_risk) or 'none'}."
        )
    else:
        summary = (
            f"The codebase is split into {len(contexts)} bounded contexts migrated to "
            f"{target_lang}. High-risk contexts requiring careful boundary management: "
            f"{', '.join(high_risk) or 'none'}. Medium-risk contexts: "
            f"{', '.join(med_risk) or 'none'}. Low-risk contexts (test, config, frontend) "
            f"can proceed in parallel with domain migrations."
        )

    return {
        "target_lang":         target_lang,
        "services":            services,
        "context_decisions":   context_decisions,
        "contradictions":      [],
        "fitness_suite":       fitness_suite,
        "valid_context_names": valid_context_names,
        "available_contexts":  available_contexts,
        "summary":             summary,
    }
