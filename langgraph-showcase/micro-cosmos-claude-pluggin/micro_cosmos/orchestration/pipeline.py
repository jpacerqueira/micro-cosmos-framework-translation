"""Micro-Cosmos orchestrator — drives the full pipeline:

Analysis:  Observer → Gate 1 → Cartographer → Gate 2 → Architect → Gate 3 → Security → Gate 4
Generation: Code Writer (TDD loop) → Writer → Feature Specifier → PR Reviewer → Gate 5 → [Trivy output scan] → Done
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess

from micro_cosmos import toon as _toon

from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from micro_cosmos.langgraph_runtime import (
    Content as _Content,
    InMemorySessionService,
    LlmAgent,
    Part as _Part,
    Runner,
)


class genai_types:  # noqa: N801 — pipeline calls genai_types.Content / Part.from_text
    Content = _Content
    Part = _Part

from micro_cosmos.agents import (
    build_architect_agent,
    build_cartographer_agent,
    build_code_writer_agent,
    build_feature_specifier_agent,
    build_functional_reviewer_agent,
    build_observer_agent,
    build_pr_reviewer_agent,
    build_security_agent,
    build_skeptical_reviewer_agent,
    build_test_reviewer_agent,
    build_writer_agent,
)
from micro_cosmos import diagnostics
from micro_cosmos.gates import GATE_DEFINITIONS, approve, initial_gate_states, reject
from micro_cosmos.schema.gate import GateDecision, GateState, RejectionConstraint
from micro_cosmos.settings import get_settings
from micro_cosmos.tools.architect_tools import derive_tnas
from micro_cosmos.tools.cartographer_tools import analyse_bounded_contexts
from micro_cosmos.tools.fitness_runner import run_accumulated_test_execution
from micro_cosmos.tools.equivalence_tools import run_accumulated_equivalence_check
from micro_cosmos.tools.framework_tools import detect_cqrs_frameworks
from micro_cosmos.tools.observer_tools import _ir_cache, observe_source_estate
from micro_cosmos.tools.seam_tools import produce_seam_report, produce_work_streams
from micro_cosmos.tools.security_tools import (
    _maybe_restore_dotnet_lockfile,
    _maybe_restore_jvm_lockfile,
    run_trivy_scan,
    scan_source_for_security,
)


class PipelinePhase(str, Enum):
    # Analysis phases (from Micro-Cosmos)
    OBSERVER = "observer"
    GATE_1 = "gate_1"
    CARTOGRAPHER = "cartographer"
    GATE_2 = "gate_2"
    ARCHITECT = "architect"
    GATE_3 = "gate_3"
    SECURITY = "security"
    GATE_4 = "gate_4"           # Security gate — source code CVE and vulnerability review
    # Planning phase + gate (runs before code generation)
    FEATURE_SPECIFIER = "feature_specifier"   # seam-by-seam feature specs + Jira/OpenAPI export
    GATE_4_5 = "gate_4_5"      # Planning gate — human reviews translation scope before code gen
    # Code generation phases (Micro-Cosmos)
    CODE_WRITER = "code_writer"
    SKEPTICAL_REVIEW = "skeptical_review"
    TEST_REVIEW = "test_review"
    FUNCTIONAL_REVIEW = "functional_review"
    WRITER = "writer"
    PR_REVIEWER = "pr_reviewer"
    GATE_5 = "gate_5"           # PR approval gate — human sign-off on generated code
    DONE = "done"


PHASE_AFTER_GATE = {
    PipelinePhase.OBSERVER:          PipelinePhase.GATE_1,
    PipelinePhase.CARTOGRAPHER:      PipelinePhase.GATE_2,
    PipelinePhase.ARCHITECT:         PipelinePhase.GATE_3,
    PipelinePhase.SECURITY:          PipelinePhase.GATE_4,
    PipelinePhase.FEATURE_SPECIFIER: PipelinePhase.GATE_4_5,
    PipelinePhase.PR_REVIEWER:       PipelinePhase.GATE_5,
}

GATE_TO_AGENT_NAME = {
    PipelinePhase.GATE_1:   "observer_agent",
    PipelinePhase.GATE_2:   "cartographer_agent",
    PipelinePhase.GATE_3:   "architect_agent",
    PipelinePhase.GATE_4:   "security_agent",
    PipelinePhase.GATE_4_5: "feature_specifier_agent",
    PipelinePhase.GATE_5:   "pr_reviewer_agent",
}


@dataclass
class PipelineEvent:
    """One unit of progress emitted by the orchestrator."""

    kind: str
    phase: PipelinePhase
    payload: dict[str, Any]

    def to_json(self) -> str:
        return json.dumps(
            {"kind": self.kind, "phase": self.phase.value, "payload": self.payload},
            default=str,
        )


PHASE_AGENT_BUILDERS = {
    PipelinePhase.OBSERVER: build_observer_agent,
    PipelinePhase.CARTOGRAPHER: build_cartographer_agent,
    PipelinePhase.ARCHITECT: build_architect_agent,
    PipelinePhase.SECURITY: build_security_agent,
    PipelinePhase.CODE_WRITER: build_code_writer_agent,
    PipelinePhase.SKEPTICAL_REVIEW: build_skeptical_reviewer_agent,
    PipelinePhase.TEST_REVIEW: build_test_reviewer_agent,
    PipelinePhase.FUNCTIONAL_REVIEW: build_functional_reviewer_agent,
    PipelinePhase.WRITER: build_writer_agent,
    PipelinePhase.FEATURE_SPECIFIER: build_feature_specifier_agent,
    PipelinePhase.PR_REVIEWER: build_pr_reviewer_agent,
}


_VALID_COMMUNICATION_STYLES = frozenset({"sync-http", "async-event"})


def _is_valid_fitness_suite(value: Any) -> bool:
    """A real fitness_suite has a non-empty "functions" list of {id, spec, ...}
    dicts — confirmed via a live LM Studio run that a local model can return a
    non-empty but entirely reinvented dict shape, which a bare truthiness
    check would wrongly accept."""
    if not isinstance(value, dict):
        return False
    functions = value.get("functions")
    return (
        isinstance(functions, list) and len(functions) > 0
        and all(isinstance(f, dict) and f.get("id") and f.get("spec") for f in functions)
    )


def _is_valid_context_decisions(value: Any) -> bool:
    """Every entry must have the real "context" key (not "name" or anything
    else an LLM might substitute) and a communication_style from the actual
    enum derive_tnas() uses — confirmed via a live LM Studio run that a local
    model can return a non-empty but reinterpreted list (free-form prose like
    "CQRS with event sourcing" instead of "async-event"), which nothing
    downstream would ever recognize."""
    if not isinstance(value, list) or not value:
        return False
    return all(
        isinstance(d, dict) and d.get("context") and d.get("communication_style") in _VALID_COMMUNICATION_STYLES
        for d in value
    )


# Fraction of the real IR node population that must appear in SOME context's
# node_ids. analyse_bounded_contexts() (the deterministic classifier) already
# requires 100% coverage internally (raises ValueError otherwise) — this is a
# deliberately slightly more lenient bar for the LLM path, giving room for a
# genuinely reasonable response to omit a handful of edge-case nodes, while
# still decisively catching the kind of collapse a live LM Studio run
# actually produced: 33 of 902 real nodes (3.7%) classified, with every
# context that WAS produced individually well-formed enough to pass every
# other check above.
_MIN_CONTEXT_COVERAGE = 0.85


def _bounded_context_map_coverage(bcm: dict, ir: dict) -> float:
    """Fraction of ir_graph's real node ids that appear in some context's
    node_ids. A structurally well-formed bcm can still silently omit most of
    the estate — a per-context shape check alone (see
    _is_valid_bounded_context_map) cannot catch this, since every individual
    context can look perfectly fine while the estate as a whole is barely
    covered."""
    all_ids = {n.get("id") for n in ir.get("nodes", []) if n.get("id")}
    if not all_ids:
        return 1.0
    covered: set[str] = set()
    for ctx in bcm.get("contexts", []):
        covered.update(ctx.get("node_ids", []) or [])
    return len(covered & all_ids) / len(all_ids)


def _is_valid_bounded_context_map(v: dict, ir: dict | None = None) -> bool:
    """Every context must have the real "name" and a non-empty "node_ids" —
    confirmed via a live LM Studio run that a local model can rename these to
    something else entirely (observed: "context_name" and "nodes") while
    still producing a structurally-plausible-looking contexts list. The old
    check only verified the ABSENCE of glob characters inside node_ids, which
    trivially passes when node_ids doesn't exist under that name at all —
    same class of presence-only bug as fitness_suite/context_decisions above,
    just one level deeper (per-context, not per-artifact).

    When ir is provided, ALSO rejects a structurally-fine-looking bcm that
    covers too little of the real estate (see _bounded_context_map_coverage)
    — a different, coarser failure mode than per-context shape, confirmed
    via the same live run.
    """
    contexts = v.get("contexts")
    if not isinstance(contexts, list) or len(contexts) < 2:
        return False
    if not isinstance(v.get("cross_context_calls"), list) or not v.get("cross_context_calls"):
        return False
    for ctx in contexts:
        if not isinstance(ctx, dict) or not ctx.get("name"):
            return False
        node_ids = ctx.get("node_ids")
        if not isinstance(node_ids, list) or not node_ids or any("*" in nid for nid in node_ids):
            return False
    if ir is not None and _bounded_context_map_coverage(v, ir) < _MIN_CONTEXT_COVERAGE:
        return False
    # analyse_bounded_contexts() no longer raises when a context still exceeds the 40%
    # concentration cap after Step 1b's refinement attempt (issue #87) — it returns a real,
    # otherwise-usable artifact flagged via this field instead. Treat it the same as any
    # other invalid-artifact case: Gate 2 still opens with its "review carefully" warning
    # banner, but reject-and-restart now has a real classification to act on.
    if v.get("over_concentrated_contexts"):
        return False
    return True


def _test_execution_hard_failed(run_dir: Path) -> bool:
    """True iff test_execution.json shows a real, deterministic compile/test
    failure for the current seam.

    Used to skip the Test Reviewer's own LLM turn entirely rather than run it
    only to have submit_test_review force-override the verdict anyway —
    confirmed live: every TDD iteration was paying for a full LLM call even
    when a real compile error already made the outcome a foregone
    conclusion, wasting real tokens/time on a turn whose opinion could never
    change the result.
    """
    try:
        raw = json.loads((run_dir / "test_execution.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(raw, dict) and bool(raw.get("ran")) and not raw.get("passed", True)


def _is_valid_feature_specs(v: dict) -> bool:
    """submit_feature_specs() writes the full {specs, work_streams, summary,
    ...} object straight to feature_specs.json and only returns a small
    {"ok": True, "specs_written": N, ...} confirmation as its own output_key
    value. Without this check, that confirmation dict (or a model's
    plain-text response that happens to parse into some other dict shape
    without ever calling the real tool — confirmed live, BUG-7) passes a
    bare isinstance(dict) default, silently standing in for a real specs
    artifact and never triggering the deterministic fallback.

    Deliberately does NOT require a non-empty list (dropped per PR #78's
    review, 2026-09-10): a genuinely seam-free estate has zero real specs to
    produce, which is a legitimate outcome, not a failure — the confirmation
    stub this check exists to catch has no "specs" key at all (not even an
    empty list), so requiring the key to be a list is already sufficient to
    reject it without also rejecting an honestly-empty real result."""
    return (
        isinstance(v.get("specs"), list)
        and all(isinstance(s, dict) and s.get("seam_id") for s in v.get("specs", []))
    )


def _read_feature_specs_file(run_dir: Path) -> dict | None:
    """The merged specs the tool persists. The phase artifact key is
    feature_specs_result, and the tool's own return value is only a
    confirmation stub, so callers must read this file to keep the artifact
    aligned with what was actually written.
    """
    path = Path(run_dir) / "feature_specs.json"
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return None
    if isinstance(value, dict) and _is_valid_feature_specs(value):
        return value
    return None


def _is_valid_artifact(key: str, value: Any, ir: dict | None = None) -> bool:
    if not isinstance(value, dict):
        return False
    _checks: dict[str, Any] = {
        # nodes must be a list — reject the submit_observer_output summary dict
        # which has "nodes": <int> and would otherwise fool this check.
        "ir_graph":            lambda v: isinstance(v.get("nodes"), list),
        "bounded_context_map": lambda v: _is_valid_bounded_context_map(v, ir),
        "tnas":                lambda v: any(k in v for k in ("services", "target_lang")),
        "security_report":     lambda v: isinstance(v.get("findings"), list),
        # A seam_result missing "pr" is a malformed Code Writer submission —
        # accepting it as valid would let a broken/partial submission stand
        # in for a real one.
        "seam_result":         lambda v: isinstance(v.get("pr"), dict),
        "review_report":       lambda v: isinstance(v.get("review_passed"), bool),
        # TDD review artifacts (see the SKEPTICAL_REVIEW/TEST_REVIEW/
        # FUNCTIONAL_REVIEW _direct_tool_fallback cases below) must have a
        # real passed/findings shape — otherwise a stale prior-seam's
        # skeptical_review.json on disk could be silently accepted as this
        # seam's review, masking a reviewer agent that crashed without
        # submitting anything.
        "skeptical_review":    lambda v: isinstance(v.get("passed"), bool) and isinstance(v.get("findings"), list),
        "test_review":         lambda v: isinstance(v.get("passed"), bool) and isinstance(v.get("findings"), list),
        "functional_review":   lambda v: isinstance(v.get("passed"), bool) and isinstance(v.get("findings"), list),
        "feature_specs":       _is_valid_feature_specs,
        # feature_specifier_agent's ADK output_key is "feature_specs_result"
        # (micro_cosmos/agents/feature_specifier.py) — NOT "feature_specs". Every
        # _is_valid_artifact(agent.output_key, ...) call in run_phase() and
        # open_gate() looks up THIS key, not "feature_specs" — confirmed live
        # (review of PR #78, 2026-09-10) that the "feature_specs" entry above
        # was dead code for that reason: _checks.get("feature_specs_result")
        # returned None and fell through to the unconditional `True` default,
        # so BUG-7's fallback-trigger check has never actually fired for a
        # real (non-skip_llm) run, and #63's new Gate 4.5 validity banner was
        # a no-op for the exact scenario it was built for. Same validator,
        # registered under the key that's actually used at runtime.
        "feature_specs_result": _is_valid_feature_specs,
    }
    check = _checks.get(key)
    return check(value) if check else True


def _direct_tool_fallback(phase: "PipelinePhase", state: dict) -> tuple[dict | None, str | None]:
    """Returns (result, error_message).

    error_message is None both on success and on the genuine "no case
    registered for this phase" outcome — those are indistinguishable to
    callers today, and that's fine, since neither is a bug. It is set only
    when a registered fallback tool actually raised — e.g. a real
    ValueError from cartographer_tools.py's own path-classification safety
    check (see the ProjectManagement over-broad-context incident,
    2026-08-04) — so callers can surface the real cause instead of the
    generic "no deterministic fallback" message, which made that incident
    far harder to diagnose than it needed to be.
    """
    sp = state.get("source_path", "")
    sl = state.get("source_lang", "")
    tl = state.get("target_lang", "")
    try:
        if phase == PipelinePhase.OBSERVER:
            cached = _ir_cache.get(f"{sp}:{sl}")
            if cached is not None:
                return cached, None
            return observe_source_estate(sp, sl), None
        if phase == PipelinePhase.CARTOGRAPHER:
            return analyse_bounded_contexts(sp, sl), None
        if phase == PipelinePhase.ARCHITECT:
            return derive_tnas(sp, sl, tl), None
        if phase == PipelinePhase.SECURITY:
            from micro_cosmos.tools.security_tools import submit_security_findings
            raw = scan_source_for_security(sp, sl)
            return submit_security_findings(
                scope_summary=raw.get("scope_summary", ""),
                findings=raw.get("findings", []),
                source_architecture_risk=raw.get("source_architecture_risk", "MEDIUM"),
                destination_architecture_risk="UNKNOWN",
                source_lang=sl,
                target_lang=tl,
                risk_ranking=raw.get("risk_ranking", []),
                follow_up_checks=raw.get("follow_up_checks", []),
            ), None
        if phase == PipelinePhase.FEATURE_SPECIFIER:
            import re as _re
            from micro_cosmos.tools.feature_spec_tools import read_seam_data, submit_feature_specs
            run_dir = state.get("run_dir", "")
            if not run_dir:
                return None, None
            # When this fallback fires mid-batch (driver.py's per-batch
            # Feature Specifier loop for large estates —
            # feature_specifier_batch_seam_ids), scope the deterministic
            # regeneration to just THIS batch's seam ids. Without this, a
            # single failed batch would regenerate specs for every seam in
            # the estate — harmless to the file itself now that
            # submit_feature_specs merges by seam_id, but wasteful and
            # confusing in the run log for a large estate.
            batch_seam_ids = state.get("feature_specifier_batch_seam_ids") or None
            data = read_seam_data(run_dir, seam_ids=batch_seam_ids)
            if not data.get("seams"):
                # A real, legitimate outcome for a genuinely seam-free estate
                # — not a failure. Returning None here (found via PR #78's
                # review, 2026-09-10) left self.artifacts["feature_specs_
                # result"] never populated at all, which _is_valid_
                # feature_specs() then correctly-but-unhelpfully treated
                # identically to the actual bug it exists to catch (a
                # crashed turn's confirmation-stub artifact) — Gate 4.5 would
                # never open, even with auto_approve_gates=True, for an
                # estate with nothing to specify. An explicit, valid, empty
                # result is the honest answer: zero seams genuinely need
                # zero specs.
                return {"specs": [], "work_streams": data.get("work_streams", []),
                        "summary": "No seams identified for this estate — nothing to specify."}, None
            target_lang = data.get("target_lang") or tl or "unknown"
            source_lang = data.get("source_lang") or sl or "unknown"
            ws_map: dict[str, str] = {
                sid: ws.get("id", "ws_default")
                for ws in data.get("work_streams", [])
                for sid in ws.get("seam_ids", [])
            }
            specs = []
            for seam in data.get("seams", []):
                seam_id = seam.get("id", "")
                work    = seam.get("work") if isinstance(seam.get("work"), dict) else {}
                effort  = (work.get("effort") or "M").upper()
                risk    = (work.get("risk")   or "MEDIUM").upper()
                raw_name = _re.sub(r"^seam_(object|context|boundary|link|preprocessing)_", "", seam_id)
                raw_name = _re.sub(r"([A-Z])", r" \1", raw_name).replace("_", " ").strip().title()
                title    = raw_name[:60] or seam_id
                steps    = work.get("steps", [])
                tech     = (seam.get("substitution_note") or "").strip()
                if steps:
                    tech = (tech + " " + " ".join(f"{i+1}. {s}" for i, s in enumerate(steps[:5]))).strip()
                specs.append({
                    "seam_id":            seam_id,
                    "work_stream_id":     ws_map.get(seam_id, "ws_default"),
                    "title":              title,
                    "description":        (
                        f"Migration of {seam_id} from {source_lang} to {target_lang}. "
                        + (seam.get("substitution_note") or "")
                    ).strip(),
                    "business_value":     (
                        f"Modernises this component as part of the {source_lang}→{target_lang} migration."
                    ),
                    "acceptance_criteria": [
                        "Component behaves identically to the source under all existing test cases.",
                        "Monetary values use the correct decimal type; no float or double on financial fields.",
                        "All public interfaces are preserved with equivalent signatures.",
                    ],
                    "technical_notes":    tech or f"Translate {seam_id} to {target_lang}.",
                    "migration_phase":    work.get("migration_phase", "phase-1"),
                    "story_points":       int(work.get("story_points") or 3),
                    "effort":             effort if effort in ("XS", "S", "M", "L", "XL") else "M",
                    "risk":               risk   if risk   in ("LOW", "MEDIUM", "HIGH", "CRITICAL") else "MEDIUM",
                    "dependencies":       [],
                    "api_surface":        None,
                    "jira_issue_type":    "Story",
                    "jira_labels":        ["migration", target_lang, work.get("migration_phase", "phase-1")],
                })
            # submit_feature_specs() writes the full {specs, work_streams,
            # summary, ...} object straight to feature_specs.json but only
            # *returns* a small {"ok": True, "specs_written": N, ...}
            # confirmation. Returning that confirmation here would make the
            # caller's self._save_artifact() call re-write feature_specs.json
            # with just the confirmation stub, clobbering the correct file
            # this same call just wrote to disk a line above (confirmed live,
            # BUG-7). Re-read the real file back so the fallback's own output
            # matches what it actually persisted.
            result = submit_feature_specs(specs=specs, run_dir=run_dir)
            if not result.get("ok"):
                return result, None
            try:
                written = json.loads((Path(run_dir) / "feature_specs.json").read_text(encoding="utf-8"))
            except Exception:
                written = None
            return (written if isinstance(written, dict) else result), None
        if phase == PipelinePhase.CODE_WRITER:
            # A Code Writer agent that crashes or replies with plain text
            # instead of calling submit_seam_translation must not leave
            # ADK's raw text response sitting in seam_result.json — that
            # string passes the outer json.loads() (it's a valid JSON
            # string literal) but poisons every downstream reader that
            # expects a dict (skeptical checks, the Test Agent), each
            # surfacing a confusing raw "could not parse" message instead
            # of an actionable one. Confirmed live, 2026-08-24: that raw
            # message then gets fed back into the next retry's fix-prompt,
            # and a small model reacts to it as free text instead of
            # regenerating code — a self-reinforcing spiral with no code
            # ever produced.
            #
            # submit_seam_translation(files=[], ...) already has a real,
            # documented fallback for exactly this case: it calls
            # generate_and_verify_seam(), which emits real (if
            # business-logic-empty) DDD scaffolding files, so the
            # accumulated project stays buildable, and returns
            # passed=False with a PR body that plainly states what
            # happened — a clear, actionable retry signal instead of a
            # bare parse error.
            from micro_cosmos.tools.coder_tools import submit_seam_translation
            run_dir = state.get("run_dir", "")
            seam_name = state.get("current_seam", "") or "unknown_seam"
            return submit_seam_translation(
                files=[],
                source_path=sp,
                source_lang=sl,
                target_lang=tl,
                seam_name=seam_name,
                run_dir=run_dir,
            ), None
        if phase in (
            PipelinePhase.SKEPTICAL_REVIEW,
            PipelinePhase.TEST_REVIEW,
            PipelinePhase.FUNCTIONAL_REVIEW,
        ):
            # A reviewer agent that crashes without calling its submit tool
            # must not be treated as "no opinion" — without a synthesized
            # failing review here, _passed() in driver.py would see no fresh
            # artifact and could fall through to a stale prior-seam's
            # <review>.json still sitting in orch.artifacts, which reads as
            # passed=True even though THIS seam was never actually reviewed.
            run_dir = state.get("run_dir", "")
            reason = f"{phase.value.replace('_', ' ').title()} agent did not submit a review (crashed or returned no tool call)."
            if phase == PipelinePhase.SKEPTICAL_REVIEW:
                from micro_cosmos.tools.coding_loop_tools import submit_code_review
                return submit_code_review(
                    findings=[{"file": "<unknown>", "symbol": "", "issue": reason, "severity": "BLOCKER"}],
                    passed=False,
                    run_dir=run_dir,
                ), None
            if phase == PipelinePhase.TEST_REVIEW:
                from micro_cosmos.tools.coding_loop_tools import submit_test_review
                return submit_test_review(
                    findings=[{"test_file": "<unknown>", "test_name": "", "issue": reason, "severity": "BLOCKER"}],
                    passed=False,
                    has_happy_path=False, has_rule_violation=False, has_edge_case=False,
                    run_dir=run_dir,
                ), None
            from micro_cosmos.tools.coding_loop_tools import submit_functional_review
            return submit_functional_review(
                findings=[{"source_behavior": "<unknown>", "issue": reason, "severity": "BLOCKER"}],
                passed=False,
                run_dir=run_dir,
            ), None
        if phase == PipelinePhase.WRITER:
            from micro_cosmos.tools.writer_tools import write_output_files
            return write_output_files(
                source_path=sp,
                source_lang=sl,
                target_lang=tl,
                seam_name=state.get("current_seam", "") or "",
                run_dir=state.get("run_dir", ""),
            ), None
    except Exception as exc:
        diagnostics.log.exception("direct_tool_fallback failed for phase %s", phase.value)
        return None, f"{type(exc).__name__}: {exc}"
    return None, None


async def _drain_runner(runner: Runner, user_id: str, session_id: str, message: Any) -> list[Any]:
    events: list[Any] = []
    try:
        async for ev in runner.run_async(user_id=user_id, session_id=session_id, new_message=message):
            events.append(ev)
    except ValueError as exc:
        if "not found" in str(exc) and "Tool" in str(exc):
            diagnostics.log.warning("LLM hallucinated tool name — treating as no-op: %s", exc)
            return events
        raise
    return events


def _strip_data_fences(text: str) -> str:
    text = text.strip()
    m = re.search(r"```(?:json|toon)?\s*([\s\S]+?)\s*```", text)
    return m.group(1).strip() if m else text


def build_pipeline() -> dict[PipelinePhase, LlmAgent]:
    return {phase: builder() for phase, builder in PHASE_AGENT_BUILDERS.items()}


class MicroCosmosOrchestrator:
    """Phase-aware pipeline runner for the three analysis agents."""

    APP_NAME = "source"

    def __init__(
        self,
        run_id: str,
        skip_llm: bool | None = None,
        auto_approve_gates: bool = False,
        auto_approve_reviewer_name: str = "",
        pause_after_planning: bool = False,
        skip_gate_validation: bool = False,
        stop_after_code_translation: bool = False,
    ) -> None:
        self.agents = build_pipeline()
        self.session_service = InMemorySessionService()
        self.gate_states: dict[str, GateState] = initial_gate_states()
        self.current_phase: PipelinePhase = PipelinePhase.OBSERVER
        self.session_id: str = "source-session"
        self.user_id: str = "source-user"
        self.run_id = run_id
        self._skip_llm = skip_llm
        self._gate_events: dict[str, asyncio.Event] = {
            g["id"]: asyncio.Event() for g in GATE_DEFINITIONS
        }
        self.stop_requested: bool = False
        self.auto_approve_gates: bool = auto_approve_gates
        self.auto_approve_reviewer_name: str = auto_approve_reviewer_name
        # Fixed-at-launch per-run setting (the auto_approve_gates pattern, NOT the
        # live-mutation stop_requested one): when true, run_full_pipeline() ends the
        # run right after Gate 4.5 resolves instead of entering the seam TDD loop.
        self.pause_after_planning: bool = pause_after_planning
        # Plugin and other unattended runs continue when an artifact is thin.
        # The validity warning above is still emitted. The gate does not wait.
        self.skip_gate_validation: bool = skip_gate_validation
        # Translate depth writes the seam tree and returns before PR Reviewer and Gate 5.
        self.stop_after_code_translation: bool = stop_after_code_translation
        self.artifacts: dict[str, Any] = {}
        self.run_dir = Path(get_settings().runs_dir) / run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._extra_initial_state: dict[str, Any] = {}
        # Clear module-level caches so each new run starts clean
        self._clear_tool_caches()

    @staticmethod
    def _clear_tool_caches() -> None:
        from micro_cosmos.tools.observer_tools import (
            _ir_cache, _source_files_cache, _source_content_cache,
        )
        _ir_cache.clear()
        _source_files_cache.clear()
        _source_content_cache.clear()

    def _save_artifact(self, key: str, value: Any) -> None:
        if isinstance(value, dict) and tuple(value.keys()) == (key,):
            value = value[key]
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, dict):
                    value = parsed.get(key, parsed)
            except (json.JSONDecodeError, TypeError):
                try:
                    parsed = _toon.loads(value)
                    if isinstance(parsed, dict):
                        value = parsed.get(key, parsed)
                except Exception:
                    pass
        self.artifacts[key] = value
        try:
            (self.run_dir / f"{key}.json").write_text(
                json.dumps(value, indent=2, default=str), encoding="utf-8"
            )
        except Exception:
            diagnostics.log.exception("Failed to write artifact %s to disk", key)

    def _maybe_set_source_path(self, session: Any) -> None:
        if session.state.get("source_path"):
            return
        ir = self.artifacts.get("ir_graph", {})
        if not isinstance(ir, dict):
            return
        paths: list[Path] = []
        for node in ir.get("nodes", []):
            loc = node.get("source_location", "") or ""
            if not loc:
                continue
            file_part = loc.split(":")[0]
            p = Path(file_part)
            if p.is_file():
                paths.append(p.parent)
        if not paths:
            return
        common = paths[0]
        for p in paths[1:]:
            try:
                p.relative_to(common)
            except ValueError:
                try:
                    common = Path(*[a for a, b in zip(common.parts, p.parts) if a == b])
                except TypeError:
                    return
        if common.is_dir():
            session.state["source_path"] = str(common)

    def load_artifact(self, key: str) -> Any | None:
        if key in self.artifacts:
            return self.artifacts[key]
        path = self.run_dir / f"{key}.json"
        if path.exists():
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                # ADK can double-encode: unwrap a JSON string that is itself JSON.
                if isinstance(value, str):
                    try:
                        value = json.loads(value)
                    except Exception:
                        pass
                self.artifacts[key] = value
                return value
            except Exception:
                diagnostics.log.exception("Failed to read artifact %s from disk", key)
        return None

    async def reset_session(self, extra_state: dict | None = None) -> None:
        try:
            session = await self.session_service.get_session(
                app_name=self.APP_NAME,
                user_id=self.user_id,
                session_id=self.session_id,
            )
            if session is None:
                return
            preserved: dict[str, Any] = {
                k: session.state.get(k, "")
                for k in ("source_path", "source_lang", "target_lang", "run_dir", "current_seam")
            }
            for key, val in self.artifacts.items():
                try:
                    toon_str = _toon.dumps(val)
                    if len(toon_str) < 50_000:
                        preserved[key] = toon_str
                except Exception:
                    pass
            if extra_state:
                preserved.update(extra_state)
            await self.session_service.delete_session(
                app_name=self.APP_NAME,
                user_id=self.user_id,
                session_id=self.session_id,
            )
            await self.session_service.create_session(
                app_name=self.APP_NAME,
                user_id=self.user_id,
                session_id=self.session_id,
                state=preserved,
            )
        except Exception:
            diagnostics.log.exception("reset_session failed; continuing with existing session")

    async def initialise_session(
        self,
        source_path: str,
        source_lang: str,
        target_lang: str,
    ) -> None:
        try:
            await self.session_service.create_session(
                app_name=self.APP_NAME,
                user_id=self.user_id,
                session_id=self.session_id,
                state={
                    "source_path": source_path,
                    "source_lang": source_lang,
                    "target_lang": target_lang,
                    "run_dir": str(self.run_dir),
                    **self._extra_initial_state,
                },
            )
        except Exception:
            diagnostics.log.exception("Failed to create session")
            raise

    async def run_phase(self, phase: PipelinePhase, override_prompt: str | None = None) -> AsyncIterator[PipelineEvent]:
        agent = self.agents[phase]

        try:
            runner = Runner(
                app_name=self.APP_NAME,
                agent=agent,
                session_service=self.session_service,
            )
        except Exception as exc:
            diag = diagnostics.from_exception(
                exc,
                phase=phase.value,
                source="orchestrator.runner_init",
                message=f"Failed to construct ADK Runner for {agent.name}",
            )
            yield PipelineEvent(kind="error", phase=phase, payload=diag.to_payload())
            return

        yield PipelineEvent(
            kind="phase_started",
            phase=phase,
            payload={"agent": agent.name},
        )

        if self._skip_llm if self._skip_llm is not None else get_settings().skip_llm:
            try:
                session = await self.session_service.get_session(
                    app_name=self.APP_NAME, user_id=self.user_id, session_id=self.session_id
                )
                state = session.state if session else {}
                # Must run BEFORE _direct_tool_fallback — submit_test_review's
                # deterministic path (inside that call) reads test_execution.json
                # directly off disk, so the real result has to exist first.
                if phase == PipelinePhase.TEST_REVIEW:
                    async for ev in self._run_test_execution_prescan():
                        yield ev
                # Same reasoning, for submit_functional_review's equivalence_result.json read.
                if phase == PipelinePhase.FUNCTIONAL_REVIEW:
                    async for ev in self._run_equivalence_prescan():
                        yield ev
                fallback, fallback_error = _direct_tool_fallback(phase, state)
                if fallback is not None:
                    self._save_artifact(agent.output_key, fallback)
                    if phase == PipelinePhase.OBSERVER and session is not None:
                        self._maybe_set_source_path(session)
                else:
                    message = (
                        f"skip_llm=true, deterministic fallback for {phase.value} raised: {fallback_error}"
                        if fallback_error
                        else f"skip_llm=true but no deterministic fallback for {phase.value}."
                    )
                    yield PipelineEvent(
                        kind="warning",
                        phase=phase,
                        payload=diagnostics.warning(
                            phase=phase.value,
                            source=agent.name,
                            message=message,
                        ).to_payload(),
                    )
            except Exception as exc:
                diag = diagnostics.from_exception(
                    exc, phase=phase.value, source=agent.name,
                    message=f"skip_llm deterministic fallback failed for {phase.value}",
                )
                yield PipelineEvent(kind="error", phase=phase, payload=diag.to_payload())
                return
            # Seam-production hooks — must run in both LLM and deterministic modes
            # so that work_streams.json and seam.json exist for downstream reports.
            if phase == PipelinePhase.OBSERVER:
                # CQRS/event-sourcing framework detection, mirroring the LLM-mode
                # post-phase hook below. Deliberately runs BEFORE seam production so the
                # enriched ir dict is what seam detection sees — the same ordering the
                # LLM path gets for free. Previously this only existed in the post-phase
                # hooks section, which this branch's early `return` never reaches, so
                # cqrs_framework_hints was never written in Deterministic mode at all.
                try:
                    _sp = state.get("source_path", "")
                    if _sp:
                        ir = self.load_artifact("ir_graph")
                        if isinstance(ir, dict):
                            ir["cqrs_framework_hints"] = detect_cqrs_frameworks(_sp, ir)
                            self._save_artifact("ir_graph", ir)
                except Exception:
                    diagnostics.log.exception("post-observer CQRS framework detection failed for %s", self.run_id)
                try:
                    ir = self.load_artifact("ir_graph")
                    if isinstance(ir, dict) and isinstance(ir.get("nodes"), list):
                        seam_report = produce_seam_report(
                            ir,
                            run_id=self.run_id,
                            source_path=state.get("source_path"),
                            target_lang=state.get("target_lang"),
                        )
                        produce_work_streams(seam_report, bcm=None, run_id=self.run_id)
                except Exception:
                    diagnostics.log.exception("post-observer seam production failed for %s", self.run_id)
            if phase == PipelinePhase.CARTOGRAPHER:
                try:
                    bcm = self.load_artifact("bounded_context_map")
                    if bcm:
                        ir = self.load_artifact("ir_graph")
                        if ir and isinstance(ir.get("nodes"), list):
                            seam_report = produce_seam_report(
                                ir,
                                run_id=self.run_id,
                                bcm=bcm,
                                source_path=state.get("source_path"),
                                target_lang=state.get("target_lang"),
                            )
                        else:
                            seam_path = self.run_dir / "seam.json"
                            seam_report = json.loads(seam_path.read_text(encoding="utf-8")) if seam_path.exists() else None
                        if seam_report:
                            produce_work_streams(seam_report, bcm=bcm, run_id=self.run_id)
                except Exception:
                    diagnostics.log.exception("post-cartographer work_streams refresh failed for %s", self.run_id)
            # Source-side Trivy scan — must run in both LLM and deterministic modes,
            # same reasoning as the seam-production hooks above: run_trivy_scan()
            # only needs source_path/source_lang (already in session state
            # regardless of skip_llm) and Trivy/JDK/Gradle/.NET are already in the
            # image, so there's no LLM dependency gating this. Previously this only
            # ran via the pre-phase hook below, which the skip_llm branch's early
            # `return` never reached — trivy_report.json was never written in
            # Deterministic mode as a result.
            if phase == PipelinePhase.SECURITY:
                async for ev in self._run_trivy_prescan():
                    yield ev
            yield PipelineEvent(
                kind="phase_completed",
                phase=phase,
                payload={"agent": agent.name, "output_key": agent.output_key},
            )
            return

        # ── Pre-phase hooks (run before the LLM starts) ───────────────────────
        if phase == PipelinePhase.SECURITY:
            async for ev in self._run_trivy_prescan():
                yield ev

        # Must run BEFORE the Test Reviewer agent's own turn (and before any
        # crash/invalid-artifact recovery calls _direct_tool_fallback for this
        # phase) — the real signal has to already be on disk either way.
        if phase == PipelinePhase.TEST_REVIEW:
            async for ev in self._run_test_execution_prescan():
                yield ev
            if _test_execution_hard_failed(self.run_dir):
                from micro_cosmos.tools.coding_loop_tools import submit_test_review
                result = submit_test_review(
                    findings=[], passed=True, has_happy_path=True,
                    has_rule_violation=True, has_edge_case=True, run_dir=str(self.run_dir),
                )
                self._save_artifact(agent.output_key, result)
                yield PipelineEvent(
                    kind="phase_completed", phase=phase,
                    payload={"agent": agent.name, "output_key": agent.output_key, "skipped_llm_call": True},
                )
                return

        # Same reasoning, for submit_functional_review's equivalence_result.json read.
        if phase == PipelinePhase.FUNCTIONAL_REVIEW:
            async for ev in self._run_equivalence_prescan():
                yield ev
            if _test_execution_hard_failed(self.run_dir):
                from micro_cosmos.tools.coding_loop_tools import submit_functional_review
                result = submit_functional_review(findings=[], passed=True, run_dir=str(self.run_dir))
                self._save_artifact(agent.output_key, result)
                yield PipelineEvent(
                    kind="phase_completed", phase=phase,
                    payload={"agent": agent.name, "output_key": agent.output_key, "skipped_llm_call": True},
                )
                return

        if phase in (
            PipelinePhase.CODE_WRITER,
            PipelinePhase.SKEPTICAL_REVIEW,
            PipelinePhase.TEST_REVIEW,
            PipelinePhase.FUNCTIONAL_REVIEW,
        ):
            from micro_cosmos.tools.run_context import set_run_dir
            set_run_dir(str(self.run_dir))

        prompt = override_prompt if override_prompt is not None else _phase_kickoff_prompt(phase)
        try:
            user_message = genai_types.Content(
                role="user", parts=[genai_types.Part.from_text(text=prompt)]
            )
        except Exception as exc:
            diag = diagnostics.from_exception(
                exc,
                phase=phase.value,
                source="orchestrator.message_build",
                message="Failed to build kick-off message",
            )
            yield PipelineEvent(kind="error", phase=phase, payload=diag.to_payload())
            return

        # Best-effort pre-flight warning — session.state alone (cheap, already in
        # memory) is not the whole prompt (it excludes this turn's own tool-call
        # history, which ADK/LiteLLM only see once the call is in flight), so this
        # can only warn early, never guarantee the call will fit. Never let this
        # check itself break a phase.
        try:
            _pf_session = await self.session_service.get_session(
                app_name=self.APP_NAME, user_id=self.user_id, session_id=self.session_id
            )
            if _pf_session is not None:
                approx_tokens = len(json.dumps(_pf_session.state, default=str)) // 4
                budget = get_settings().model_context_length
                if approx_tokens > int(budget * 0.85):
                    yield PipelineEvent(
                        kind="warning",
                        phase=phase,
                        payload=diagnostics.warning(
                            phase=phase.value,
                            source=agent.name,
                            message=(
                                f"Session state is already ~{approx_tokens} tokens against a "
                                f"{budget}-token model context window before this call starts "
                                "(excludes this turn's own tool-call history) — high risk of "
                                "ContextWindowExceededError."
                            ),
                        ).to_payload(),
                    )
        except Exception:
            pass

        agent_events: list[Any] = []
        crashed = False
        try:
            # litellm's own `timeout=` (settings.py's llm_timeout, passed to LiteLlm)
            # only bounds httpx's per-chunk read wait — confirmed live against a
            # local Ollama backend that finished prompt processing instantly
            # and then emitted literally zero tokens (not even a partial one) for
            # 20-66+ minutes before being killed by hand: a full engine-side
            # generation stall, not a slow-but-progressing response, and litellm's
            # timeout never fired for it. Enforce a real wall-clock ceiling here
            # so a stuck backend fails into the same crash-recovery path below
            # (deterministic fallback + _run_post_phase_hooks) instead of hanging
            # the phase — and the whole pipeline — indefinitely.
            _llm_timeout = get_settings().llm_timeout
            try:
                agent_events = await asyncio.wait_for(
                    _drain_runner(runner, self.user_id, self.session_id, user_message),
                    timeout=_llm_timeout,
                )
            except TimeoutError as exc:
                raise TimeoutError(
                    f"LLM backend produced no response within llm_timeout={_llm_timeout}s "
                    "(prompt may have processed but generation never started/completed)"
                ) from exc
        except Exception as exc:
            diag = diagnostics.from_exception(
                exc,
                phase=phase.value,
                source=agent.name,
                message=f"Agent {agent.name} crashed: {type(exc).__name__}: {exc}",
                context={"output_key": agent.output_key},
            )
            yield PipelineEvent(kind="error", phase=phase, payload=diag.to_payload())
            crashed = True
            # Even after LLM crash, attempt deterministic fallback so the gate still opens.
            # If this attempt itself fails (swallowed below), the artifact-validation
            # block right after this except clause will call _direct_tool_fallback a
            # second time for the same phase/state (review of PR #78, 2026-09-10) — for
            # OBSERVER/CARTOGRAPHER/ARCHITECT that's a full source-estate re-scan, twice,
            # back to back. Accepted as-is: needs a genuine double failure to trigger,
            # and the alternative (threading a "don't retry" flag through) adds real
            # complexity for a low-likelihood, self-correcting-on-next-run edge case.
            if agent.output_key:
                try:
                    _fb_session = await self.session_service.get_session(
                        app_name=self.APP_NAME, user_id=self.user_id, session_id=self.session_id
                    )
                    _fb_state = _fb_session.state if _fb_session else {}
                    fallback, _fallback_error = _direct_tool_fallback(phase, _fb_state)
                    if fallback is not None:
                        self._save_artifact(agent.output_key, fallback)
                except Exception:
                    pass
            # Deliberately NOT returning here (was `return` until BUG-11/12/13,
            # #60/#61/#62) — falling through to the same artifact-validation and
            # "Post-phase hooks" sections the happy path below runs. Confirmed
            # live (3 phases in a row on one real run, reproduced across two
            # separate runs of the same estate): a crash used to skip Observer's
            # CQRS-hint detection, Cartographer's seam/work-stream refresh, and
            # Architect's HTML-report/RAG-index generation entirely — a crash
            # in LLM mode was silently degrading the pipeline *below* the
            # deterministic-mode floor, even though the fallback artifact these
            # hooks would run against is exactly as valid an input as a
            # successful agent turn's own output. `agent_events` stays `[]`
            # (never reassigned since the try block raised), so the loop right
            # below this is a harmless no-op; the artifact-validation block
            # re-reads `self.artifacts` and finds the fallback already valid,
            # so it will not call `_direct_tool_fallback` a second time.

        for event in agent_events:
            payload = _serialise_event(event)
            yield PipelineEvent(kind="agent_event", phase=phase, payload=payload)

        # Set unconditionally, before the try below — the final phase_completed
        # yield after "Post-phase hooks" reads this even when the try raises
        # and falls through (review of PR #78, 2026-09-10: leaving this
        # assignment inside the try risked a NameError there once the except
        # block stopped returning early, since a plain attribute access can't
        # itself fail but everything before it in the try could raise first).
        output_key = agent.output_key
        try:
            session = await self.session_service.get_session(
                app_name=self.APP_NAME, user_id=self.user_id, session_id=self.session_id
            )
            # Only bounded_context_map's validator actually uses this (its
            # coverage check) — loaded unconditionally since it's cheap and
            # already-cached after Observer, but harmless for every other key.
            _validation_ir = self.load_artifact("ir_graph")
            if output_key and session and output_key in session.state:
                raw = session.state[output_key]
                if isinstance(raw, str):
                    raw = _strip_data_fences(raw)
                    session.state[output_key] = raw
                _disk = self.run_dir / f"{output_key}.json"
                if _disk.exists():
                    try:
                        _disk_val = json.loads(_disk.read_text(encoding="utf-8"))
                        if _is_valid_artifact(output_key, _disk_val, ir=_validation_ir):
                            raw = _disk_val
                    except Exception:
                        pass
                self._save_artifact(output_key, raw)

            if output_key == "feature_specs_result":
                written_specs = _read_feature_specs_file(self.run_dir)
                if written_specs is not None:
                    self._save_artifact(output_key, written_specs)

            if output_key:
                saved = self.artifacts.get(output_key)
                if not _is_valid_artifact(output_key, saved, ir=_validation_ir):
                    fallback, fallback_error = _direct_tool_fallback(phase, session.state if session else {})
                    if fallback is not None:
                        self._save_artifact(output_key, fallback)
                    else:
                        yield PipelineEvent(
                            kind="warning",
                            phase=phase,
                            payload=diagnostics.warning(
                                phase=phase.value,
                                source=agent.name,
                                message=(
                                    f"Agent produced an invalid '{output_key}' artifact "
                                    "and the direct-tool fallback also failed"
                                    + (f": {fallback_error}" if fallback_error else ".")
                                ),
                            ).to_payload(),
                        )

            if phase == PipelinePhase.OBSERVER and session is not None:
                self._maybe_set_source_path(session)
        except Exception as exc:
            diag = diagnostics.from_exception(
                exc,
                phase=phase.value,
                source="orchestrator.state_snapshot",
                message="Failed to snapshot session state after phase",
            )
            yield PipelineEvent(kind="error", phase=phase, payload=diag.to_payload())
            # Same fix, same reasoning as the LLM-crash handler above (review
            # of PR #78, 2026-09-10): this is a second, structurally
            # identical place post-phase hooks could be skipped — anything
            # raising here (get_session, load_artifact, _is_valid_artifact,
            # _direct_tool_fallback, _save_artifact) is independent of
            # whether the agent's own LLM call succeeded, and reproduces
            # #60/#61/#62's exact bug class via a different trigger if left
            # returning early. The hooks below are already defensively coded
            # (their own try/except + isinstance guards) — safe to attempt
            # even when whatever's in self.artifacts/on disk right now is
            # incomplete.
            crashed = True

        # ── Post-phase hooks ───────────────────────────────────────────────────
        if phase == PipelinePhase.OBSERVER:
            try:
                ir = self.load_artifact("ir_graph")
                if isinstance(ir, dict) and isinstance(ir.get("nodes"), list):
                    _session = await self.session_service.get_session(
                        app_name=self.APP_NAME, user_id=self.user_id, session_id=self.session_id
                    )
                    _state = _session.state if _session else {}
                    _sp = _state.get("source_path")
                    seam_report = produce_seam_report(
                        ir,
                        run_id=self.run_id,
                        source_path=_sp,
                        target_lang=_state.get("target_lang"),
                    )
                    produce_work_streams(seam_report, bcm=None, run_id=self.run_id)
            except Exception:
                diagnostics.log.exception("post-observer seam production failed for %s", self.run_id)
            # Lightweight deterministic security pre-scan — enriches IR with security_hints
            # so the Cartographer and Architect agents can flag migration-relevant risks early.
            try:
                session = await self.session_service.get_session(
                    app_name=self.APP_NAME, user_id=self.user_id, session_id=self.session_id
                )
                state = session.state if session else {}
                sp = state.get("source_path", "")
                sl = state.get("source_lang", "")
                if sp and sl:
                    hints = scan_source_for_security(sp, sl)
                    ir = self.load_artifact("ir_graph")
                    if isinstance(ir, dict):
                        # Strip large fields (code_snippet, matched_text) to keep IR compact —
                        # full snippets are only needed by the Security agent at Phase 4.
                        top = []
                        for f in hints.get("findings", [])[:5]:
                            top.append({
                                k: v for k, v in f.items()
                                if k not in ("code_snippet", "matched_text")
                            })
                        ir["security_hints"] = {
                            "finding_count": len(hints.get("findings", [])),
                            "source_architecture_risk": hints.get("source_architecture_risk", "LOW"),
                            "top_findings": top,
                        }
                        self._save_artifact("ir_graph", ir)
            except Exception:
                diagnostics.log.exception("post-observer security hints scan failed for %s", self.run_id)
            # Lightweight deterministic CQRS/event-sourcing framework detection — enriches
            # IR with cqrs_framework_hints so the Architect agent can recommend/preserve a
            # framework the codebase already commits to, rather than reasoning about
            # CQRS/ES in a vacuum.
            try:
                session = await self.session_service.get_session(
                    app_name=self.APP_NAME, user_id=self.user_id, session_id=self.session_id
                )
                sp = (session.state if session else {}).get("source_path", "")
                if sp:
                    ir = self.load_artifact("ir_graph")
                    if isinstance(ir, dict):
                        ir["cqrs_framework_hints"] = detect_cqrs_frameworks(sp, ir)
                        self._save_artifact("ir_graph", ir)
            except Exception:
                diagnostics.log.exception("post-observer CQRS framework detection failed for %s", self.run_id)

        if phase == PipelinePhase.SECURITY:
            try:
                scripts_dir = Path(__file__).resolve().parents[2] / "scripts"
                reports_dir = self.run_dir / "reports"
                reports_dir.mkdir(exist_ok=True)
                sec_script = scripts_dir / "generate_security.js"
                sec_out = reports_dir / "security-report.html"
                if sec_script.exists() and (self.run_dir / "security_report.json").exists():
                    r = subprocess.run(
                        ["node", str(sec_script), str(self.run_dir), str(sec_out)],
                        capture_output=True, text=True, timeout=60,
                    )
                    if r.returncode == 0:
                        diagnostics.log.info("generate_security: %s", r.stdout.strip())
                    else:
                        diagnostics.log.warning(
                            "generate_security failed: %s",
                            (r.stderr or r.stdout or "").strip()[:400],
                        )
            except Exception:
                diagnostics.log.exception("post-security report generation failed for %s", self.run_id)

        if phase == PipelinePhase.ARCHITECT:
            # Ensure fitness_suite is present AND structurally valid — merge it in
            # from the deterministic tool if the LLM trimmed it, replaced it with
            # its own invented shape, or left it some other way malformed.
            #
            # A truthiness check alone ("not tnas.get('fitness_suite')") is NOT
            # enough: confirmed via a real LM Studio run (qwen2.5-coder-7b) that a
            # local model can return a non-empty fitness_suite dict that is
            # entirely made up (e.g. {"read_heavy_services": [...], ...} instead
            # of {"functions": [...]}) — truthy, so the old check silently kept
            # it, and every canonical fitness check went dark for that run.
            try:
                tnas = self.load_artifact("tnas")
                if isinstance(tnas, dict) and not _is_valid_fitness_suite(tnas.get("fitness_suite")):
                    from micro_cosmos.fitness import build_canonical_suite
                    session = await self.session_service.get_session(
                        app_name=self.APP_NAME, user_id=self.user_id, session_id=self.session_id
                    )
                    state = session.state if session else {}
                    tnas["fitness_suite"] = build_canonical_suite(
                        state.get("target_lang", "java21")
                    ).model_dump(mode="json")
                    self._save_artifact("tnas", tnas)
            except Exception:
                diagnostics.log.exception("post-architect fitness_suite merge failed for %s", self.run_id)
            # Same reasoning, same real-world evidence, for context_decisions: the
            # same live run returned a non-empty but reinterpreted list — "name"
            # instead of "context" as the key, and communication_style values like
            # "CQRS with event sourcing" instead of the sync-http/async-event enum
            # every downstream check actually reads. A presence-only check would
            # have kept that garbage; this validates the actual shape.
            try:
                tnas = self.load_artifact("tnas")
                if isinstance(tnas, dict) and not _is_valid_context_decisions(tnas.get("context_decisions")):
                    session = await self.session_service.get_session(
                        app_name=self.APP_NAME, user_id=self.user_id, session_id=self.session_id
                    )
                    state = session.state if session else {}
                    rederived = derive_tnas(
                        state.get("source_path", ""),
                        state.get("source_lang", ""),
                        state.get("target_lang", "java21"),
                    )
                    tnas["context_decisions"] = rederived.get("context_decisions", [])
                    self._save_artifact("tnas", tnas)
            except Exception:
                diagnostics.log.exception("post-architect context_decisions merge failed for %s", self.run_id)
            # Generate all HTML reports and build the RAG index.
            async for ev in self._run_architect_reports():
                yield ev

        if phase == PipelinePhase.CARTOGRAPHER:
            try:
                bcm = self.load_artifact("bounded_context_map")
                if bcm:
                    ir = self.load_artifact("ir_graph")
                    if ir and isinstance(ir.get("nodes"), list):
                        _session = await self.session_service.get_session(
                            app_name=self.APP_NAME, user_id=self.user_id, session_id=self.session_id
                        )
                        _state = _session.state if _session else {}
                        _sp = _state.get("source_path")
                        seam_report = produce_seam_report(
                            ir,
                            run_id=self.run_id,
                            bcm=bcm,
                            source_path=_sp,
                            target_lang=_state.get("target_lang"),
                        )
                    else:
                        seam_path = self.run_dir / "seam.json"
                        seam_report = json.loads(seam_path.read_text(encoding="utf-8")) if seam_path.exists() else None
                    if seam_report:
                        produce_work_streams(seam_report, bcm=bcm, run_id=self.run_id)
            except Exception:
                diagnostics.log.exception("post-cartographer work_streams refresh failed for %s", self.run_id)

        # recovered_from_crash lets the UI tell a genuine success apart from
        # a fallback-recovered, degraded result (review of PR #78, 2026-09-10)
        # — without it, dashboard.js's markPhase() unconditionally overwrites
        # the earlier "error" pill with a green "done" one and the live-status
        # line with a success checkmark, silently erasing the exact signal
        # #60/#61/#62 exist to surface.
        yield PipelineEvent(
            kind="phase_completed",
            phase=phase,
            payload={"agent": agent.name, "output_key": output_key, "recovered_from_crash": crashed},
        )

    async def _run_architect_reports(self) -> AsyncIterator[PipelineEvent]:
        """Generate HTML reports and build the RAG index after the Architect LLM phase."""
        phase = PipelinePhase.ARCHITECT

        # Ensure run_meta.json exists (needed by Node.js report generators)
        meta_path = self.run_dir / "run_meta.json"
        if not meta_path.exists():
            try:
                session = await self.session_service.get_session(
                    app_name=self.APP_NAME, user_id=self.user_id, session_id=self.session_id
                )
                state = session.state if session else {}
                meta_path.write_text(
                    json.dumps({
                        "source_path": state.get("source_path", ""),
                        "source_lang": state.get("source_lang", ""),
                        "target_lang": state.get("target_lang", "java21"),
                    }),
                    encoding="utf-8",
                )
            except Exception:
                diagnostics.log.exception("Could not write run_meta.json before report generation")

        scripts_dir = Path(__file__).resolve().parents[2] / "scripts"
        reports_dir = self.run_dir / "reports"
        reports_dir.mkdir(exist_ok=True)

        _html_required: dict[str, list[str]] = {
            "generate_briefing":       ["run_meta.json", "bounded_context_map.json", "tnas.json",
                                        "work_streams.json", "seam.json"],
            "generate_synthesis":      ["run_meta.json", "bounded_context_map.json", "tnas.json",
                                        "work_streams.json", "seam.json", "ir_graph.json"],
            "generate_graph":          ["run_meta.json", "bounded_context_map.json", "ir_graph.json"],
            "generate_exec_summary":   ["run_meta.json"],
            "generate_hotspots":       ["run_meta.json", "ir_graph.json"],
            "generate_sprint_plan":    ["run_meta.json", "work_streams.json"],
            "generate_adrs":           ["run_meta.json", "tnas.json"],
            "generate_fitness_stubs":  ["run_meta.json", "tnas.json"],
            "generate_deadcode":       ["run_meta.json", "ir_graph.json"],
        }
        _script_to_html: dict[str, str] = {
            "generate_briefing.js":      "migration-briefing.html",
            "generate_synthesis.js":     "project-synthesis.html",
            "generate_graph.js":         "ir-graph.html",
            "generate_exec_summary.js":  "executive-summary.html",
            "generate_hotspots.js":      "hotspots.html",
            "generate_sprint_plan.js":   "sprint-plan.html",
            "generate_adrs.js":          "architecture-decisions.html",
            "generate_fitness_stubs.js": "fitness-stubs.html",
            "generate_deadcode.js":      "dead-code.html",
        }
        for script_name, label in [
            ("generate_briefing.js",      "generate_briefing"),
            ("generate_synthesis.js",     "generate_synthesis"),
            ("generate_graph.js",         "generate_graph"),
            ("generate_exec_summary.js",  "generate_exec_summary"),
            ("generate_hotspots.js",      "generate_hotspots"),
            ("generate_sprint_plan.js",   "generate_sprint_plan"),
            ("generate_adrs.js",          "generate_adrs"),
            ("generate_fitness_stubs.js", "generate_fitness_stubs"),
            ("generate_deadcode.js",      "generate_deadcode"),
        ]:
            try:
                script = scripts_dir / script_name
                required = _html_required[label]
                if script.exists() and all((self.run_dir / f).exists() for f in required):
                    out_path = reports_dir / _script_to_html[script_name]
                    r = subprocess.run(
                        ["node", str(script), str(self.run_dir), str(out_path)],
                        capture_output=True, text=True, timeout=60,
                    )
                    if r.returncode == 0:
                        diagnostics.log.info("%s: %s", label, r.stdout.strip())
                    else:
                        diagnostics.log.warning(
                            "%s failed: %s", label,
                            (r.stderr or r.stdout or "").strip()[:400],
                        )
            except Exception:
                diagnostics.log.exception("%s failed for %s", label, self.run_id)

        # Build the RAG/vector sidecar now that all artifacts + HTML reports exist.
        try:
            from micro_cosmos.retrieval.index import build_index
            idx = build_index(self.run_dir)
            diagnostics.log.info(
                "index built for %s (%d chunks, mode=%s)",
                self.run_id, idx.chunk_count, idx.mode,
            )
        except Exception:
            diagnostics.log.exception("index build failed for %s — continuing", self.run_id)

        # yield nothing — phase_completed is emitted by run_phase() after all hooks
        return
        yield  # make this a valid async generator

    async def _run_trivy_prescan(self) -> AsyncIterator[PipelineEvent]:
        """Run Trivy filesystem scan before the Security LLM phase.

        Emits pipeline events for scan start/complete so the trace shows Trivy progress.
        Saves trivy_report.json so the Security agent can read it via read_trivy_report().
        """
        phase = PipelinePhase.SECURITY
        try:
            session = await self.session_service.get_session(
                app_name=self.APP_NAME, user_id=self.user_id, session_id=self.session_id
            )
            state = session.state if session else {}
            sp = state.get("source_path", "")
            if not sp:
                return
            source_lang = state.get("source_lang", "")

            yield PipelineEvent(
                kind="agent_event",
                phase=phase,
                payload={
                    "author": "trivy",
                    "parts": [{"type": "text", "text": f"[Trivy] Starting filesystem scan of {sp} …"}],
                },
            )

            result = run_trivy_scan(sp, str(self.run_dir), lang=source_lang)

            if result.get("error"):
                yield PipelineEvent(
                    kind="warning",
                    phase=phase,
                    payload=diagnostics.warning(
                        phase=phase.value,
                        source="trivy",
                        message=f"Trivy scan warning: {result['error']}",
                    ).to_payload(),
                )
            else:
                summary = result.get("summary", {})
                total = summary.get("total", 0)
                crit = summary.get("CRITICAL", 0)
                high = summary.get("HIGH", 0)
                yield PipelineEvent(
                    kind="agent_event",
                    phase=phase,
                    payload={
                        "author": "trivy",
                        "parts": [{
                            "type": "text",
                            "text": (
                                f"[Trivy] Scan complete — {total} CVE(s) found "
                                f"({crit} CRITICAL, {high} HIGH). "
                                f"Results saved to trivy_report.json."
                            ),
                        }],
                    },
                )
                diagnostics.log.info(
                    "trivy scan complete for %s: %d CVEs (%d critical, %d high)",
                    self.run_id, total, crit, high,
                )
        except Exception:
            diagnostics.log.exception("_run_trivy_prescan failed for %s — continuing", self.run_id)
        return
        yield  # valid async generator

    async def _run_test_execution_prescan(self) -> AsyncIterator[PipelineEvent]:
        """Run real per-language test execution before the Test Review phase.

        Emits pipeline events so the trace shows execution progress under a
        distinct "test-execution" author. Saves test_execution.json so
        submit_test_review() (coding_loop_tools.py) can force-correct its own
        `passed` field with a real signal — see fitness_runner.py's
        run_accumulated_test_execution() docstring for why this can't simply
        reuse the fitness suite's own per-seam exec_result.
        """
        phase = PipelinePhase.TEST_REVIEW
        try:
            session = await self.session_service.get_session(
                app_name=self.APP_NAME, user_id=self.user_id, session_id=self.session_id
            )
            state = session.state if session else {}
            target_lang = state.get("target_lang", "")

            yield PipelineEvent(
                kind="agent_event",
                phase=phase,
                payload={
                    "author": "test-execution",
                    "parts": [{
                        "type": "text",
                        "text": "[Test Execution] Running real tests against the accumulated project …",
                    }],
                },
            )

            # asyncio.to_thread — not a direct call. run_accumulated_test_execution
            # shells out via a blocking subprocess.run() with its own timeout; called
            # directly from this async method, that blocks the whole process's event
            # loop (every concurrent run's SSE stream, gate approvals, HTTP requests)
            # for the full subprocess duration. Unlike the pre-existing Trivy prescan
            # (same blocking pattern, but fires once per pipeline run), this hook
            # fires on every TDD iteration — the cumulative stall is far worse.
            result = await asyncio.to_thread(
                run_accumulated_test_execution, str(self.run_dir), target_lang
            )

            if not result.get("ran"):
                yield PipelineEvent(
                    kind="agent_event",
                    phase=phase,
                    payload={
                        "author": "test-execution",
                        "parts": [{
                            "type": "text",
                            "text": f"[Test Execution] Skipped — {result.get('message', '')}",
                        }],
                    },
                )
            else:
                status = "PASSED" if result.get("passed") else "FAILED"
                yield PipelineEvent(
                    kind="agent_event",
                    phase=phase,
                    payload={
                        "author": "test-execution",
                        "parts": [{
                            "type": "text",
                            "text": (
                                f"[Test Execution] {status} — "
                                "results saved to test_execution.json."
                            ),
                        }],
                    },
                )
        except Exception:
            diagnostics.log.exception("_run_test_execution_prescan failed for %s — continuing", self.run_id)
        return
        yield  # valid async generator

    async def _run_equivalence_prescan(self) -> AsyncIterator[PipelineEvent]:
        """Run real differential testing before the Functional Review phase.

        Emits pipeline events under a distinct "equivalence-check" author.
        Saves equivalence_result.json so submit_functional_review()
        (coding_loop_tools.py) can force-correct its own `passed` field with
        a real signal — see equivalence_tools.run_accumulated_equivalence_check's
        docstring for exactly what is and is not checked (target-side
        differential testing against Code-Writer-supplied vectors; no
        source-vs-target comparison yet).
        """
        phase = PipelinePhase.FUNCTIONAL_REVIEW
        try:
            session = await self.session_service.get_session(
                app_name=self.APP_NAME, user_id=self.user_id, session_id=self.session_id
            )
            state = session.state if session else {}
            target_lang = state.get("target_lang", "")

            yield PipelineEvent(
                kind="agent_event",
                phase=phase,
                payload={
                    "author": "equivalence-check",
                    "parts": [{
                        "type": "text",
                        "text": "[Equivalence Check] Comparing real output against any supplied test vectors …",
                    }],
                },
            )

            # asyncio.to_thread — see _run_test_execution_prescan's comment above
            # for why: run_accumulated_equivalence_check shells out (compiling
            # and running the per-language harness) via blocking subprocess.run()
            # calls, so calling it directly here would stall the whole app's
            # event loop for the harness's full duration, once per TDD iteration.
            result = await asyncio.to_thread(
                run_accumulated_equivalence_check, str(self.run_dir), target_lang
            )

            if not result.get("ran"):
                yield PipelineEvent(
                    kind="agent_event",
                    phase=phase,
                    payload={
                        "author": "equivalence-check",
                        "parts": [{
                            "type": "text",
                            "text": f"[Equivalence Check] Skipped — {result.get('message', '')}",
                        }],
                    },
                )
            else:
                status = "PASSED" if result.get("passed") else "FAILED"
                yield PipelineEvent(
                    kind="agent_event",
                    phase=phase,
                    payload={
                        "author": "equivalence-check",
                        "parts": [{
                            "type": "text",
                            "text": (
                                f"[Equivalence Check] {status} — "
                                "results saved to equivalence_result.json."
                            ),
                        }],
                    },
                )
        except Exception:
            diagnostics.log.exception("_run_equivalence_prescan failed for %s — continuing", self.run_id)
        return
        yield  # valid async generator

    async def _run_trivy_output_scan(self) -> AsyncIterator[PipelineEvent]:
        """Run Trivy on the generated output directory after Gate 5 (PR approval).

        Saves results to trivy_output_report.json so the web UI and ASK tab can surface
        CVEs found in the translated code alongside the source CVEs from Gate 4.
        """
        phase = PipelinePhase.GATE_5
        try:
            # Find the output directory written by the Writer agent.
            # Priority: write_manifest.json → output/ → any project subdir.
            output_dir = self.run_dir / "output"
            manifest_path = self.run_dir / "write_manifest.json"
            if manifest_path.exists():
                try:
                    import json as _json
                    _manifest = _json.loads(manifest_path.read_text(encoding="utf-8"))
                    _od = Path(_manifest.get("output_dir", ""))
                    if _od.is_dir():
                        output_dir = _od
                except Exception:
                    pass
            if not output_dir.exists():
                candidates = [p for p in self.run_dir.iterdir() if p.is_dir() and p.name not in {
                    "reports", "vectors", "output"
                } and not p.name.startswith(".")]
                if candidates:
                    output_dir = candidates[0]

            if not output_dir.exists():
                diagnostics.log.warning(
                    "trivy output scan skipped for %s — no output directory found", self.run_id
                )
                return

            session = await self.session_service.get_session(
                app_name=self.APP_NAME, user_id=self.user_id, session_id=self.session_id
            )
            state = session.state if session else {}
            target_lang = state.get("target_lang", "")

            yield PipelineEvent(
                kind="agent_event",
                phase=phase,
                payload={
                    "author": "trivy",
                    "parts": [{"type": "text", "text": f"[Trivy] Scanning generated output at {output_dir} …"}],
                },
            )

            _maybe_restore_dotnet_lockfile(output_dir, target_lang)
            _maybe_restore_jvm_lockfile(output_dir, target_lang)

            out_path = self.run_dir / "trivy_output_report.json"
            cmd = [
                "trivy", "fs", str(output_dir),
                "--scanners", "vuln,secret",
                "--format", "json",
                "--quiet",
                "--output", str(out_path),
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)

            if out_path.exists():
                import json as _json
                try:
                    raw = _json.loads(out_path.read_text(encoding="utf-8"))
                    # Enrich into the same {summary, vulnerabilities} format as trivy_report.json
                    _SEV_MAP = {"CRITICAL": "CRITICAL", "HIGH": "HIGH", "MEDIUM": "MEDIUM",
                                "LOW": "LOW", "UNKNOWN": "MEDIUM"}
                    vulns: list[dict] = []
                    sev_counts: dict[str, int] = {}
                    for idx, result_item in enumerate(raw.get("Results", []), 1):
                        target = result_item.get("Target", "unknown")
                        for v in result_item.get("Vulnerabilities", []) or []:
                            sev = _SEV_MAP.get(str(v.get("Severity", "UNKNOWN")).upper(), "MEDIUM")
                            pkg = v.get("PkgName", "")
                            installed = v.get("InstalledVersion", "?")
                            fixed = v.get("FixedVersion", "") or ""
                            cve_id = v.get("VulnerabilityID", "")
                            url = v.get("PrimaryURL", "")
                            sev_counts[sev] = sev_counts.get(sev, 0) + 1
                            vulns.append({
                                "id": f"CVE-OUT-{idx:03d}",
                                "cve_id": cve_id,
                                "pkg_name": pkg,
                                "installed_version": installed,
                                "fixed_version": fixed,
                                "title": v.get("Title") or f"{pkg}: {cve_id}",
                                "severity": sev,
                                "description": (v.get("Description") or "")[:600],
                                "location": f"{target} · {pkg}=={installed}",
                                "remediation": (
                                    f"Upgrade {pkg} to {fixed}" if fixed else
                                    f"No upstream fix yet for {pkg} {installed}; monitor {url or 'NVD'}"
                                ),
                                "primary_url": url,
                                "category": "SUPPLY_CHAIN",
                                "confirmed": True,
                                "affects_migration": sev in {"CRITICAL", "HIGH"},
                            })
                    enriched = {
                        "scan_target": str(output_dir),
                        "summary": {"total": len(vulns), **sev_counts},
                        "vulnerabilities": vulns,
                    }
                    out_path.write_text(_json.dumps(enriched, indent=2), encoding="utf-8")
                    total = len(vulns)
                    yield PipelineEvent(
                        kind="agent_event",
                        phase=phase,
                        payload={
                            "author": "trivy",
                            "parts": [{"type": "text", "text": (
                                f"[Trivy] Output scan complete — {total} CVE(s) found in generated code. "
                                f"Results saved to trivy_output_report.json."
                            )}],
                        },
                    )
                    diagnostics.log.info("trivy output scan: %d CVEs in generated code for %s", total, self.run_id)
                except Exception:
                    diagnostics.log.exception("trivy output scan enrichment failed for %s", self.run_id)
            else:
                err = (result.stderr or result.stdout or "")[:300]
                yield PipelineEvent(
                    kind="warning",
                    phase=phase,
                    payload=diagnostics.warning(
                        phase=phase.value,
                        source="trivy-output",
                        message=f"Trivy output scan produced no report: {err}",
                    ).to_payload(),
                )
        except FileNotFoundError:
            diagnostics.log.warning("trivy binary not found — output scan skipped for %s", self.run_id)
        except Exception:
            diagnostics.log.exception("_run_trivy_output_scan failed for %s — continuing", self.run_id)
        return
        yield  # valid async generator

    def clear_review_artifacts(self) -> None:
        """Remove review artifacts from disk and memory before a new TDD iteration."""
        for key in ("skeptical_review", "test_review", "functional_review", "seam_translation"):
            (self.run_dir / f"{key}.json").unlink(missing_ok=True)
            self.artifacts.pop(key, None)

    def get_all_seams(self) -> list[str]:
        """Return the list of seam names to translate (from seam.json or bounded_context_map)."""
        return [s.get("id") or s.get("name", "main") for s in self.get_all_seams_data()]

    def get_all_seams_data(self) -> list[dict]:
        """Return full seam records from seam.json, falling back to name-only dicts.

        Each record contains at minimum ``id``; seam.json records also carry
        ``type``, ``source_location``, ``evidence``, ``substitution_note``, and
        ``work`` (with ``title``, ``steps``, ``effort``, ``story_points``, ``risk``).
        """
        seam_path = self.run_dir / "seam.json"
        if seam_path.exists():
            try:
                import json as _json
                raw = _json.loads(seam_path.read_text())
                seams = raw.get("seams", [])
                if seams:
                    return seams
            except Exception:
                pass
        # Fallback: one seam per bounded context (no rich metadata)
        bcm = self.artifacts.get("bounded_context_map", {})
        if isinstance(bcm, dict):
            contexts = bcm.get("contexts", [])
            if contexts:
                return [
                    {"id": c.get("name", f"context_{i}"), "type": "object"}
                    for i, c in enumerate(contexts)
                ]
        return [{"id": "main", "type": "object"}]

    async def open_gate(self, gate_phase: PipelinePhase) -> AsyncIterator[PipelineEvent]:
        gate_id = gate_phase.value
        try:
            state = self.gate_states[gate_id]
            agent_name = GATE_TO_AGENT_NAME[gate_phase]
            agent = next(a for a in self.agents.values() if a.name == agent_name)
            artifact = self.artifacts.get(agent.output_key, {})
            state.pending_artifact_sha = _maybe_extract_sha(artifact)
            state.stamp(produced_by="orchestrator")
            # A human-approval gate is the whole point of catching what the
            # pipeline can't catch itself — but it can only do that if the
            # gate UI actually shows when the thing being presented isn't a
            # real artifact at all. Confirmed live (#63/BUG-14): a cascade of
            # upstream context-overflow crashes (see #60-#62) left
            # feature_specs.json holding stale, confused LLM prose instead of
            # real specs, and Gate 4.5 opened looking identical to a normal
            # review — no signal to the reviewer that they were about to
            # approve garbage. _is_valid_artifact already exists and is used
            # to decide whether run_phase() needs a deterministic fallback;
            # reusing the exact same check here, at the one place a human
            # actually sees the artifact, is a direct, low-risk backstop
            # against any other way an invalid artifact could reach a gate.
            artifact_valid = _is_valid_artifact(
                agent.output_key, artifact, ir=self.load_artifact("ir_graph")
            )
        except Exception as exc:
            diag = diagnostics.from_exception(
                exc,
                phase=gate_phase.value,
                source="orchestrator.open_gate",
                message=f"Failed to prepare gate {gate_id}",
            )
            yield PipelineEvent(kind="error", phase=gate_phase, payload=diag.to_payload())
            return

        if not artifact_valid:
            yield PipelineEvent(
                kind="warning",
                phase=gate_phase,
                payload=diagnostics.warning(
                    phase=gate_phase.value,
                    source="orchestrator.open_gate",
                    message=(
                        f"Gate {gate_id} is opening with an artifact that fails its own "
                        f"validity check ('{agent.output_key}') — this may be leftover "
                        "prose from a crashed agent turn rather than a real result. "
                        "Review carefully before approving."
                    ),
                ).to_payload(),
            )

        yield PipelineEvent(
            kind="gate_opened",
            phase=gate_phase,
            payload={
                "gate_id": gate_id,
                "gate_name": state.gate_name,
                "expected_reviewer_role": state.expected_reviewer_role,
                "artifact_sha": state.pending_artifact_sha,
                "artifact_valid": artifact_valid,
                "artifact": artifact,
            },
        )

        # Deliberately excludes an invalid artifact in LLM mode (review of PR
        # #78, 2026-09-10) — auto-approve exists for the expected/common
        # case, not the "something crashed upstream" case, and unattended
        # LLM-mode runs are exactly the runs most exposed to the
        # crash-recovery cascade this same PR addresses (no human is
        # watching the SSE stream to notice the warning above). A genuinely
        # invalid artifact still blocks on the manual wait below even when
        # auto_approve_gates=True.
        #
        # Scoped to LLM mode only — deterministic mode has no LLM-call-crash
        # concept at all (every phase's output comes straight from
        # _direct_tool_fallback, never an agent turn), and at least one
        # phase (PR_REVIEWER) has no deterministic fallback registered for
        # it at all — a pre-existing, already-warned-about, accepted gap
        # (see "skip_llm=true but no deterministic fallback for
        # pr_reviewer"), not a crash. Applying this check mode-agnostically
        # would permanently block auto-approve at Gate 5 for every
        # deterministic-mode run, which is a different, unrelated problem
        # from the one this fix targets.
        _skip_llm_now = self._skip_llm if self._skip_llm is not None else get_settings().skip_llm
        if self.skip_gate_validation or (
            self.auto_approve_gates and (artifact_valid or _skip_llm_now)
        ):
            self.approve_gate(
                gate_id,
                reviewer_name=self.auto_approve_reviewer_name or "pipeline",
                notes=(
                    "gate validation skipped"
                    if self.skip_gate_validation
                    else "auto-approved to next gate"
                ),
            )

        await self._gate_events[gate_id].wait()
        self._gate_events[gate_id].clear()

        if state.decision == GateDecision.REJECTED:
            yield PipelineEvent(
                kind="warning",
                phase=gate_phase,
                payload=diagnostics.warning(
                    phase=gate_phase.value,
                    source="gate_review",
                    message=(
                        f"Gate {gate_id} rejected (count={state.rejection_count}). "
                        "Agent will re-run with the rejection constraint applied."
                    ),
                    context={"rejection_count": state.rejection_count},
                ).to_payload(),
            )
        elif state.decision == GateDecision.ESCALATED:
            yield PipelineEvent(
                kind="error",
                phase=gate_phase,
                payload=diagnostics.from_exception(
                    RuntimeError(f"Gate {gate_id} escalated after 3 rejections"),
                    phase=gate_phase.value,
                    source="gate_review",
                    message=(
                        f"Gate {gate_id} escalated after 3 rejections. "
                        "Pipeline halted pending engagement-director override."
                    ),
                ).to_payload(),
            )

        approval_reviewer_name = None
        approval_notes = None
        if state.decision == GateDecision.APPROVED and state.approvals:
            approval_reviewer_name = state.approvals[-1].reviewer_name
            approval_notes = state.approvals[-1].notes

        yield PipelineEvent(
            kind="gate_resolved",
            phase=gate_phase,
            payload={
                "gate_id": gate_id,
                "decision": state.decision.value,
                "rejection_count": state.rejection_count,
                "reviewer_name": approval_reviewer_name,
                "notes": approval_notes,
            },
        )

    def approve_gate(self, gate_id: str, reviewer_name: str, notes: str = "") -> None:
        state = self.gate_states[gate_id]
        approve(state, reviewer_name=reviewer_name, notes=notes)
        self._gate_events[gate_id].set()

    async def reject_gate(
        self, gate_id: str, reviewer_name: str, reason: str
    ) -> RejectionConstraint:
        gate_phase = PipelinePhase(gate_id)
        applies_to = GATE_TO_AGENT_NAME[gate_phase]
        state = self.gate_states[gate_id]
        _, constraint = reject(
            state, reviewer_name=reviewer_name, reason=reason, applies_to_agent=applies_to
        )
        try:
            session = await self.session_service.get_session(
                app_name=self.APP_NAME, user_id=self.user_id, session_id=self.session_id
            )
            if session is not None:
                key = f"{gate_id}_constraints"
                existing = session.state.get(key, [])
                existing.append(constraint.model_dump(mode="json"))
                session.state[key] = existing
        except Exception as exc:
            diagnostics.log.exception(
                "Failed to persist rejection constraint for %s: %s", gate_id, exc
            )
        self._gate_events[gate_id].set()
        return constraint

    def gate_state_snapshot(self) -> list[dict[str, Any]]:
        return [self.gate_states[g["id"]].model_dump(mode="json") for g in GATE_DEFINITIONS]


def _phase_kickoff_prompt(phase: PipelinePhase) -> str:
    return {
        PipelinePhase.OBSERVER: (
            "Begin Phase 1. Parse the source estate, catalogue dead code, scan "
            "performance issues, and retrieve documentation. Return the JSON IR."
        ),
        PipelinePhase.CARTOGRAPHER: (
            "Begin Phase 2. Identify bounded contexts via three-way voted "
            "analysis. Return the JSON context map."
        ),
        PipelinePhase.ARCHITECT: (
            "Begin Phase 3. Derive the TNAS and emit the canonical fitness "
            "suite. Return the JSON TNAS."
        ),
        PipelinePhase.SECURITY: (
            "Begin Phase 4 — Security Analysis. "
            "Step 0: call read_trivy_report(run_dir=…) to load dependency CVEs found by Trivy. "
            "Step 0.5: call read_manifest_files to audit dependencies and .env files. "
            "Step 1: call scan_source_for_security — each finding includes a code_snippet. "
            "Step 2: for every HIGH/CRITICAL finding call read_file_snippet to confirm or dismiss. "
            "Step 3: call search_in_source for patterns you suspect from your reading. "
            "Step 4: call read_source_file on key auth and config files. "
            "Step 5-6: assess source and destination architecture risk. "
            "Step 7: call submit_security_findings with all findings including Trivy CVEs."
        ),
        PipelinePhase.CODE_WRITER: (
            "Begin code generation. "
            "Translate the current seam to the target language following the TNAS. "
            "Call submit_seam_translation when complete."
        ),
        PipelinePhase.SKEPTICAL_REVIEW: "Review the generated code for correctness and completeness. Call submit_skeptical_review.",
        PipelinePhase.TEST_REVIEW: "Review test coverage of the generated code. Call submit_test_review.",
        PipelinePhase.FUNCTIONAL_REVIEW: "Review whether the generated code faithfully reproduces source behaviour. Call submit_functional_review.",
        PipelinePhase.WRITER: "Write the translated output files to disk. Call write_output_files.",
        PipelinePhase.FEATURE_SPECIFIER: (
            "Generate feature specifications for every seam. "
            "Call read_seam_data(run_dir=…) to load all analysis data, "
            "then call submit_feature_specs with specs for ALL seams in a single call."
        ),
        PipelinePhase.PR_REVIEWER: "Review the complete generated project output for PR readiness. Call submit_pr_review.",
    }.get(phase, "Proceed.")


def _serialise_event(event: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"author": getattr(event, "author", "unknown")}
    content = getattr(event, "content", None)
    if content and getattr(content, "parts", None):
        parts_out = []
        for p in content.parts:
            if getattr(p, "text", None):
                parts_out.append({"type": "text", "text": p.text})
            elif getattr(p, "function_call", None):
                fc = p.function_call
                parts_out.append({
                    "type": "function_call",
                    "name": fc.name,
                    "args": dict(fc.args) if fc.args else {},
                })
            elif getattr(p, "function_response", None):
                fr = p.function_response
                parts_out.append({
                    "type": "function_response",
                    "name": fr.name,
                    "response": dict(fr.response) if fr.response else {},
                })
        out["parts"] = parts_out
    if hasattr(event, "is_final_response"):
        try:
            out["is_final_response"] = bool(event.is_final_response())
        except Exception:
            pass
    return out


def _maybe_extract_sha(artifact: Any) -> str:
    if isinstance(artifact, dict) and "sha" in artifact and artifact["sha"]:
        return artifact["sha"]
    import hashlib
    payload = json.dumps(artifact, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]
