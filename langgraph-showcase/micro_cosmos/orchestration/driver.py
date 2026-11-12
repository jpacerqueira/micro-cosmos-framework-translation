"""Micro-Cosmos full pipeline driver.

Runs the complete end-to-end pipeline:
  Analysis:   Observer → Gate 1 → Cartographer → Gate 2 → Architect → Gate 3 → Security → Gate 4
  Generation: Code Writer (TDD loop per seam) → Writer → PR Reviewer → Gate 5
  Post-gate:  Trivy scan of generated output code → Done
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from pathlib import Path

import httpx

from micro_cosmos import diagnostics
from micro_cosmos.orchestration.pipeline import (
    PHASE_AFTER_GATE,
    MicroCosmosOrchestrator,
    PipelineEvent,
    PipelinePhase,
)
from micro_cosmos.settings import get_settings

__all__ = ["run_full_pipeline"]

# Child of the "micro_cosmos" logger configured in micro_cosmos/__init__.py — same
# handler/formatter as micro_cosmos.diagnostics, so these lines appear in
# `docker compose logs` and `gcloud run services logs read` with no extra
# setup either side. INFO covers state transitions (fallback, ready,
# 401, timeout); DEBUG adds a line per individual poll — opt in via
# MICRO_COSMOS_LOG_LEVEL=DEBUG when debugging the readiness wait itself, since
# at the default poll_interval this can run for up to llm_ready_timeout_seconds.
log = logging.getLogger("micro_cosmos.orchestration.driver")


async def _wait_for_llm_ready(
    base_url: str,
    model_ids: set[str],
    *,
    timeout_seconds: int,
    api_key: str = "",
    poll_interval: float = 10.0,
    skip_native: bool = False,
) -> tuple[bool, str]:
    """Poll for whether model_ids are actually loaded/ready before the
    pipeline sends real traffic. Best-effort: never raises. Returns
    (ready, message) — the caller decides whether to proceed on timeout;
    this never blocks a run indefinitely.

    Tries LM Studio's native REST API first (NOT the OpenAI-compat
    /v1/models shim — that endpoint's loaded-vs-catalog behavior is
    JIT-loading-dependent and less reliable for LM Studio specifically):
    GET {host}/api/v0/models returns e.g.
    {"data": [{"id": "...", "state": "loaded"|"not-loaded", ...}], "object": "list"}.
    LM Studio's own bug tracker has reports of this endpoint sometimes
    returning only the currently-loaded model rather than the full catalog —
    a model ID present with no "state" key is treated as loaded too, to be
    robust to that.

    This native endpoint doesn't exist on other OpenAI-compatible backends
    (e.g. vLLM, added 2026-07-11 as an LM Studio alternative for
    nvidia-rtx-pro-6000 — see deploy_cloudrun-vllm-llms.py) — any non-200
    response there is treated as "not LM Studio," and readiness falls back
    to a plain GET {base_url}/v1/models returning 200. That's sufficient for
    engines that don't bind their port until the configured model is
    already loaded (vLLM's `vllm serve` included), unlike LM Studio's split
    bind-then-load design which is exactly why the native state-checking
    path above exists in the first place.

    `api_key`, if set, is sent as `Authorization: Bearer {api_key}` on both
    probes — required when LM Studio's own "Require Authentication" server
    setting is on (confirmed 2026-07-13: a real local instance rejected both
    endpoints with 401 invalid_api_key, blocking every run at this wait for
    the full timeout since neither branch could ever see a 200). Same
    parameter `build_llm()` already sends for real inference calls
    (`micro_cosmos/settings.py`'s `llm_api_key`) — harmless to send even
    when the server has no auth enabled (ignored, per LM Studio's docs: "any
    non-empty value is accepted" in that mode).
    """
    rest_base = base_url.rstrip("/")
    if rest_base.endswith("/v1"):
        rest_base = rest_base[: -len("/v1")]
    native_url = f"{rest_base}/api/v0/models"
    openai_url = f"{rest_base}/v1/models"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    log.info(
        "readiness wait starting: native=%s openai=%s models=%s api_key_configured=%s timeout=%ss poll_interval=%ss",
        native_url, openai_url, sorted(model_ids), bool(api_key), timeout_seconds, poll_interval,
    )

    is_lmstudio = not skip_native   # LiteLLM gateway has no /api/v0/models
    deadline = time.monotonic() + timeout_seconds
    async with httpx.AsyncClient(timeout=10) as client:
        while True:
            try:
                if is_lmstudio:
                    resp = await client.get(native_url, headers=headers)
                    if resp.status_code == 200:
                        entries = resp.json().get("data", [])
                        by_id = {m.get("id"): m.get("state", "loaded") for m in entries}
                        log.info("GET %s -> 200 OK — %s", native_url, by_id)
                        if all(by_id.get(mid) == "loaded" for mid in model_ids):
                            log.info("ready via native endpoint %s — %s", native_url, by_id)
                            return True, "ready"
                    else:
                        if resp.status_code == 401:
                            log.warning(
                                "GET %s -> 401 (invalid/missing API key) — falling back to the OpenAI-compat "
                                "endpoint. If this persists, LLM_API_KEY likely doesn't match the "
                                "server's configured token.",
                                native_url,
                            )
                        else:
                            log.info(
                                "GET %s -> %s (not LM Studio, or native REST API unavailable) — falling back "
                                "to the OpenAI-compat endpoint.",
                                native_url, resp.status_code,
                            )
                        is_lmstudio = False   # fall through to the OpenAI-compat check below, same iteration
                if not is_lmstudio:
                    resp = await client.get(openai_url, headers=headers)
                    if resp.status_code == 200:
                        log.info("GET %s -> 200 OK", openai_url)
                        log.info("ready via OpenAI-compat endpoint %s", openai_url)
                        return True, "ready"
                    elif resp.status_code == 401:
                        log.warning(
                            "GET %s -> 401 (invalid/missing API key) — will keep retrying until timeout. "
                            "Check LLM_API_KEY / VLLM_API_KEY match the server's configured token.",
                            openai_url,
                        )
                    else:
                        log.info("GET %s -> %s — will keep retrying until timeout.", openai_url, resp.status_code)
            except Exception as exc:
                log.debug("readiness probe request failed (server may not be reachable yet): %s", exc)
            if time.monotonic() >= deadline:
                message = f"timed out after {timeout_seconds}s waiting for {sorted(model_ids)} to load"
                log.warning("readiness wait %s", message)
                return False, message
            await asyncio.sleep(poll_interval)


def _build_feedback_prompt(run_dir: Path) -> str | None:
    """Read review files from the previous TDD iteration and build a Code Writer kickoff.

    Returns None when ALL reviews passed (nothing to fix).
    When any review failed, returns a directive listing every finding.

    Finding-collection itself lives in micro_cosmos.tools.seam_tools.summarize_seam_failure
    — shared with the persisted `processing.failure_reason` field and the
    retry-pass kickoff prompt, so there's one implementation of "what went
    wrong" across all three uses.
    """
    from micro_cosmos.tools.seam_tools import summarize_seam_failure

    findings_block = summarize_seam_failure(run_dir)
    if findings_block is None:
        return None

    return (
        "FIX THESE ISSUES from the previous iteration before doing anything else:\n\n"
        f"{findings_block}\n\n"
        "Steps:\n"
        "1. Call read_generated_files(run_dir=\"...\") to retrieve your previous output.\n"
        "2. Fix EVERY issue listed above — do not skip any.\n"
        "3. Re-submit via submit_seam_translation with ALL files "
        "(fixed files + unchanged files verbatim).\n"
        "Only call list_source_files if a FUNCTIONAL finding requires re-reading a source rule."
    )


async def run_full_pipeline(
    orch: MicroCosmosOrchestrator,
    source_path: str,
    source_lang: str,
    target_lang: str,
    start_phase: PipelinePhase | None = None,
) -> AsyncIterator[PipelineEvent]:
    """Run the full Micro-Cosmos pipeline end-to-end.

    Caller drives gate approvals out-of-band via orch.approve_gate / reject_gate.
    When start_phase is set, earlier phases are skipped (artifacts already on disk).
    """
    _ANALYSIS_PHASES = [
        PipelinePhase.OBSERVER,
        PipelinePhase.CARTOGRAPHER,
        PipelinePhase.ARCHITECT,
        PipelinePhase.SECURITY,
    ]

    if start_phase in _ANALYSIS_PHASES:
        _skip = _ANALYSIS_PHASES.index(start_phase)
    elif start_phase in (
        PipelinePhase.FEATURE_SPECIFIER,
        PipelinePhase.GATE_4_5,
        PipelinePhase.CODE_WRITER,
        PipelinePhase.PR_REVIEWER,
    ):
        _skip = len(_ANALYSIS_PHASES)
    else:
        _skip = 0

    await orch.initialise_session(source_path, source_lang, target_lang)

    if start_phase is not None:
        yield PipelineEvent(
            kind="pipeline_restarted",
            phase=start_phase,
            payload={"start_phase": start_phase.value},
        )
    else:
        # Only on a fresh run, not a restart — a restart means micro-cosmos-llmgateway
        # already successfully served earlier phases moments ago, so waiting
        # again would be pure overhead. Mirrors pipeline.py:456's exact
        # skip_llm resolution (per-run override takes precedence over the
        # global setting).
        _skip_llm_resolved = (
            orch._skip_llm if orch._skip_llm is not None else get_settings().skip_llm
        )
        if not _skip_llm_resolved:
            settings = get_settings()
            if settings.llm_engine == "vertex":
                # Vertex is a fully managed endpoint — there's no local GPU
                # cold start to wait for, so the LM-Studio-native readiness
                # poll is meaningless here. The first real LLM call is the
                # true readiness check, exactly as it already is for
                # lmstudio/vllm once _wait_for_llm_ready succeeds.
                pass
            else:
                model_ids = {settings.model_reasoning, settings.model_fast}
                yield PipelineEvent(
                    kind="agent_event",
                    phase=PipelinePhase.OBSERVER,
                    payload={
                        "author": "llmgateway",
                        "parts": [{"type": "text", "text": f"[LLMGateway] waiting for {', '.join(sorted(model_ids))} to load…"}],
                    },
                )
                ready, message = await _wait_for_llm_ready(
                    settings.llm_base_url,
                    model_ids,
                    timeout_seconds=settings.llm_ready_timeout_seconds,
                    api_key=settings.llm_api_key,
                    skip_native=settings.uses_llm_gateway(),
                )
                if ready:
                    yield PipelineEvent(
                        kind="agent_event",
                        phase=PipelinePhase.OBSERVER,
                        payload={
                            "author": "llmgateway",
                            "parts": [{"type": "text", "text": "[LLMGateway] model loaded — starting pipeline."}],
                        },
                    )
                else:
                    yield PipelineEvent(
                        kind="warning",
                        phase=PipelinePhase.OBSERVER,
                        payload=diagnostics.warning(
                            phase=PipelinePhase.OBSERVER.value,
                            source="llmgateway",
                            message=f"[LLMGateway] {message} — proceeding anyway; the first real LLM call will surface the actual error if the model truly isn't ready.",
                        ).to_payload(),
                    )

    # ── Analysis phases (Observer → Gate 4 / Security) ────────────────────────
    for _i, agent_phase in enumerate(_ANALYSIS_PHASES):
        if _i < _skip:
            yield PipelineEvent(
                kind="phase_skipped",
                phase=agent_phase,
                payload={"reason": "restart"},
            )
            continue
        orch.current_phase = agent_phase

        async for ev in orch.run_phase(agent_phase):
            yield ev

        gate_phase = PHASE_AFTER_GATE[agent_phase]
        orch.current_phase = gate_phase
        async for ev in orch.open_gate(gate_phase):
            yield ev

        gate_state = orch.gate_states[gate_phase.value]
        while gate_state.decision.value == "REJECTED":
            orch.current_phase = agent_phase
            async for ev in orch.run_phase(agent_phase):
                yield ev
            orch.current_phase = gate_phase
            async for ev in orch.open_gate(gate_phase):
                yield ev
            gate_state = orch.gate_states[gate_phase.value]

        if gate_state.decision.value == "ESCALATED":
            yield PipelineEvent(
                kind="error",
                phase=gate_phase,
                payload={
                    "message": f"Gate {gate_phase.value} escalated after 3 rejections. "
                    "Pipeline halted pending engagement-director override."
                },
            )
            return

    # ── Code generation — TDD loop per seam ──────────────────────────────────

    MAX_TDD_ITERATIONS = get_settings().max_tdd_iterations_per_seam

    _REVIEW_FILES = {
        PipelinePhase.SKEPTICAL_REVIEW: "skeptical_review.json",
        PipelinePhase.TEST_REVIEW: "test_review.json",
        PipelinePhase.FUNCTIONAL_REVIEW: "functional_review.json",
    }

    def _build_seam_kickoff(seam_data: dict) -> str:
        """Build a rich, seam-specific kickoff prompt from the seam report record."""
        seam_id = seam_data.get("id", "unknown")
        seam_type = seam_data.get("type", "object")
        source_loc = seam_data.get("source_location", "")
        sub_note = seam_data.get("substitution_note", "")
        evidence = seam_data.get("evidence", [])
        work = seam_data.get("work", {})
        steps = work.get("steps", [])
        effort = work.get("effort", "")
        risk = work.get("risk", "")

        lines = [f"Begin Code Writer phase — translate seam: {seam_id}", ""]
        lines.append(f"Seam type : {seam_type}")
        if effort:
            lines.append(f"Effort    : {effort}" + (f" | risk: {risk}" if risk else ""))
        if source_loc:
            lines.append(f"Source    : {source_loc.split(':')[0]}")
        if evidence:
            lines.append(f"Evidence  : {'; '.join(evidence)}")
        if sub_note:
            lines += ["", "Architecture guidance:", f"  {sub_note}"]
        if steps:
            lines += ["", "Migration steps (from the seam report — implement all of them):"]
            for i, step in enumerate(steps, 1):
                lines.append(f"  {i}. {step}")
        lines += [
            "",
            "Follow the steps in your system instruction.",
            "CRITICAL: do NOT output file content as text — ALL files go in submit_seam_translation only.",
        ]
        return "\n".join(lines)

    async def _run_tdd_loop_for_seam(
        seam_kickoff: str | None, *, max_iterations: int, result: dict,
        seam_id: str | None = None,
    ) -> AsyncIterator[PipelineEvent]:
        """Runs the Code Writer → 3-review-gate cycle up to max_iterations times.

        Reused for both the main per-seam pass (max_iterations=MAX_TDD_ITERATIONS)
        and the single-attempt retry pass after all seams complete
        (max_iterations=1) — the phase sequence is identical in both cases,
        only the iteration budget and seam_kickoff content differ, both
        already parameters here.

        Async generators can't return a value through normal `async for`
        iteration, so the outcome is communicated via the caller-owned
        `result` dict, populated before this returns:
          result["attempts"]: int            (iterations actually run)
          result["passed"]: bool
          result["failure_reason"]: str | None   (None iff passed)
        """
        from micro_cosmos.tools.seam_tools import summarize_seam_failure

        for iteration in range(1, max_iterations + 1):
            if orch.stop_requested:
                orch.stop_requested = False  # consume — whichever checkpoint sees it first wins
                result["passed"] = False
                result["stopped"] = True
                result["failure_reason"] = "Stopped by user before completing the TDD loop for this seam."
                yield PipelineEvent(
                    kind="tdd_loop_stopped",
                    phase=PipelinePhase.CODE_WRITER,
                    payload={"reason": "user_requested", "seam": seam_id, "mid_seam": True},
                )
                return

            if iteration > 1:
                # Clear the previous iteration's Functional Review tool-call history
                # (list_source_files/read_source_file calls, full file contents) before
                # Code Writer's next turn — otherwise it compounds every iteration and is
                # a major contributor to ContextWindowExceededError on later iterations.
                await orch.reset_session()

            # Iteration 1: use the seam-specific kickoff (or default if not provided).
            # Iteration 2+: replace with a FIX prompt listing every failing finding.
            cw_prompt = (
                _build_feedback_prompt(orch.run_dir)
                if iteration > 1
                else seam_kickoff
            )
            orch.current_phase = PipelinePhase.CODE_WRITER
            async for ev in orch.run_phase(PipelinePhase.CODE_WRITER, override_prompt=cw_prompt):
                yield ev

            for review_phase in [
                PipelinePhase.SKEPTICAL_REVIEW,
                PipelinePhase.TEST_REVIEW,
                PipelinePhase.FUNCTIONAL_REVIEW,
            ]:
                (orch.run_dir / _REVIEW_FILES[review_phase]).unlink(missing_ok=True)
                await orch.reset_session()  # clear prior agent event history so reviewers start clean
                orch.current_phase = review_phase
                async for ev in orch.run_phase(review_phase):
                    yield ev

            def _passed(key: str) -> bool:
                v = orch.artifacts.get(key)
                if isinstance(v, str):
                    try:
                        v = json.loads(v)
                    except Exception:
                        return False
                return isinstance(v, dict) and v.get("passed", False)

            result["attempts"] = iteration

            if _passed("skeptical_review") and _passed("test_review") and _passed("functional_review"):
                result["passed"] = True
                result["failure_reason"] = None
                return

            if iteration >= max_iterations:
                result["passed"] = False
                result["failure_reason"] = summarize_seam_failure(orch.run_dir)
                yield PipelineEvent(
                    kind="warning",
                    phase=PipelinePhase.FUNCTIONAL_REVIEW,
                    payload={
                        "message": (
                            f"TDD loop did not reach a clean pass after {max_iterations} "
                            "iteration(s). Proceeding with best available translation."
                        ),
                        "source": "tdd_loop",
                        "severity": "WARNING",
                    },
                )
                return

    async def _run_all_seams() -> AsyncIterator[PipelineEvent]:
        from micro_cosmos.tools.seam_tools import init_seam_processing, update_seam_processing

        seams_data = orch.get_all_seams_data()
        total = len(seams_data)

        # Pre-seed every seam's processing status as "pending" — idempotent,
        # a no-op if already initialised (e.g. this is the Gate-5-rejection
        # re-run, which force-resets processing separately before calling
        # _run_all_seams() again — see below).
        init_seam_processing(orch.run_dir)
        orch.artifacts.pop("seam", None)  # invalidate load_artifact's cache — see note below

        # ── Write canonical project dir name ONCE so all seams land in the same
        # output folder even when the LLM passes a seam-specific sub-path as
        # source_path (e.g. "common_domain" instead of the repo root).
        from micro_cosmos.tools.writer_tools import _project_dir_name
        proj_dir = _project_dir_name(source_path, target_lang)
        try:
            _proj_dir_file = orch.run_dir / "reports" / "project_dir.txt"
            _proj_dir_file.parent.mkdir(parents=True, exist_ok=True)
            _proj_dir_file.write_text(proj_dir, encoding="utf-8")
        except Exception:
            pass

        # ── Generate skills directory ONCE before any code files are written ──
        # This makes the skills immediately available as the seam loop runs,
        # rather than only appearing after the last seam completes.
        try:
            from micro_cosmos.tools.writer_tools import _write_output_skills
            skills_target = orch.run_dir / "reports" / f"{proj_dir}_skills"
            if not skills_target.exists():
                first_seam = seams_data[0].get("id", "project") if seams_data else "project"
                skills_path = _write_output_skills(
                    source_path=source_path,
                    source_lang=source_lang,
                    target_lang=target_lang,
                    seam_name=first_seam,
                    run_path=orch.run_dir,
                    project_dir=proj_dir,
                )
                yield PipelineEvent(
                    kind="info",
                    phase=PipelinePhase.CODE_WRITER,
                    payload={
                        "message": f"Skills directory created: {proj_dir}_skills/",
                        "skills_dir": skills_path,
                    },
                )
        except Exception:
            pass

        # ── Generate Kiro.dev Powers into reports/ ────────────────────────────
        # Generated from embedded Python strings (like Claude skills) — no
        # static directory dependency. Runs in both LLM and deterministic modes.
        try:
            from micro_cosmos.tools.writer_tools import _write_kiro_powers
            _kiro_dst = orch.run_dir / "reports" / "kiro-dev-powers-app-modernization"
            if not _kiro_dst.exists():
                _kiro_path = _write_kiro_powers(
                    run_path=orch.run_dir,
                    source_path=source_path,
                    source_lang=source_lang,
                    target_lang=target_lang,
                )
                yield PipelineEvent(
                    kind="info",
                    phase=PipelinePhase.CODE_WRITER,
                    payload={"message": f"kiro-dev-powers generated at {_kiro_path}"},
                )
        except Exception:
            pass

        # ── Generate OpenSpec (github.com/Fission-AI/OpenSpec) tree into reports/ ─
        # Derived from feature_specs.json/tnas.json/security_report.json — all
        # exist by this point (FEATURE_SPECIFIER + Gate 4.5 run before CODE_WRITER).
        # This is the one-shot "make it exist ASAP" call, same guard as skills/kiro
        # above; a later forced refresh (content changed after a Gate 3/4.5
        # rejection + re-run) is handled by the zip endpoint's force-regenerate
        # path (app.py::generate_zip), not here.
        try:
            from micro_cosmos.tools.writer_tools import _write_openspec
            _openspec_dst = orch.run_dir / "reports" / "openspec"
            if not _openspec_dst.exists():
                # run_in_executor, not a direct call — this does ~5 synchronous JSON
                # reads plus writes a whole file tree, and calling it straight on the
                # event loop would block every concurrent run's SSE/gate handling for
                # its duration, unlike this same PR's two app.py call sites for the
                # identical function, which already use the executor correctly.
                _openspec_path = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: _write_openspec(
                        run_path=orch.run_dir,
                        source_path=source_path,
                        source_lang=source_lang,
                        target_lang=target_lang,
                    ),
                )
                yield PipelineEvent(
                    kind="info",
                    phase=PipelinePhase.CODE_WRITER,
                    payload={"message": f"OpenSpec tree generated at {_openspec_path}"},
                )
        except Exception:
            # Logged, not silently swallowed — this same PR's other two call sites
            # for _write_openspec (app.py) either log a warning or surface an HTTP
            # error; a bare `except: pass` here meant a real bug (or even just a
            # not-ready-yet FileNotFoundError) left zero trace anywhere, and the
            # openspec/ folder would just silently never appear under Reports.
            diagnostics.log.exception("post-CODE_WRITER OpenSpec generation failed for %s", orch.run_id)

        # ── Seam-by-seam translation loop ─────────────────────────────────────
        # `stop_occurred` tracks whether a user-requested stop fired anywhere in this
        # pass (either between seams, below, or mid-seam inside _run_tdd_loop_for_seam
        # via tdd_result["stopped"]) — used after the loop to skip the retry pass too,
        # since retrying seams the user just asked to stop would defeat the request.
        stop_occurred = False

        def _mark_remaining_skipped(from_idx: int) -> list[str]:
            remaining = seams_data[from_idx:]
            for _s in remaining:
                update_seam_processing(
                    orch.run_dir, _s.get("id") or _s.get("name", "main"),
                    status="failed", attempts=0,
                    failure_reason="Skipped — TDD loop stopped by user before this seam started.",
                )
            orch.artifacts.pop("seam", None)
            return [s.get("id") for s in remaining]

        for _idx, seam_data in enumerate(seams_data):
            if orch.stop_requested:
                orch.stop_requested = False  # consume — one request, one stop
                remaining_ids = _mark_remaining_skipped(_idx)
                yield PipelineEvent(
                    kind="tdd_loop_stopped",
                    phase=PipelinePhase.CODE_WRITER,
                    payload={
                        "reason": "user_requested",
                        "remaining_seams": remaining_ids,
                        "remaining_seam_count": len(remaining_ids),
                    },
                )
                stop_occurred = True
                break

            seam_name = seam_data.get("id") or seam_data.get("name", "main")
            seam_kickoff = _build_seam_kickoff(seam_data)

            yield PipelineEvent(
                kind="seam_started",
                phase=PipelinePhase.CODE_WRITER,
                payload={"seam": seam_name, "total_seams": total},
            )
            orch.clear_review_artifacts()
            await orch.reset_session(extra_state={"current_seam": seam_name})

            tdd_result: dict = {}
            async for ev in _run_tdd_loop_for_seam(
                seam_kickoff, max_iterations=MAX_TDD_ITERATIONS, result=tdd_result,
                seam_id=seam_name,
            ):
                yield ev

            orch.current_phase = PipelinePhase.WRITER
            async for ev in orch.run_phase(PipelinePhase.WRITER):  # always runs — best-effort code is always packaged
                yield ev

            status = "success" if tdd_result.get("passed") else "failed"
            update_seam_processing(
                orch.run_dir, seam_name,
                status=status,
                attempts=tdd_result.get("attempts", 0),
                failure_reason=tdd_result.get("failure_reason"),
            )
            orch.artifacts.pop("seam", None)  # invalidate cache so the next load_artifact("seam") re-reads disk

            yield PipelineEvent(
                kind="seam_completed",
                phase=PipelinePhase.WRITER,
                payload={
                    "seam": seam_name,
                    "status": status,
                    "attempts": tdd_result.get("attempts", 0),
                    "failure_reason": tdd_result.get("failure_reason"),
                },
            )

            if tdd_result.get("stopped"):
                stop_occurred = True
                remaining_ids = _mark_remaining_skipped(_idx + 1)
                if remaining_ids:
                    yield PipelineEvent(
                        kind="tdd_loop_stopped",
                        phase=PipelinePhase.CODE_WRITER,
                        payload={
                            "reason": "user_requested",
                            "remaining_seams": remaining_ids,
                            "remaining_seam_count": len(remaining_ids),
                        },
                    )
                break

        if stop_occurred:
            return  # a user-requested stop must not trigger the retry pass either

        # ── Retry pass: one focused extra attempt per seam that ended up
        # "failed" after the main pass, with the kickoff prompt enriched
        # with the accumulated failure reason from that pass ────────────────
        # seam.json is normally written by the post-OBSERVER/CARTOGRAPHER hooks in
        # pipeline.py, but those hooks swallow their own exceptions — so a failure
        # up there leaves no seam.json here while the seam loop still runs (on
        # get_all_seams_data()'s synthetic-seam fallback). Reading it unguarded
        # turned that recoverable state into a top-level pipeline crash; an empty
        # dict yields no failed seams, so the retry pass simply no-ops instead.
        seam_path = orch.run_dir / "seam.json"
        seam_report = json.loads(seam_path.read_text(encoding="utf-8")) if seam_path.exists() else {}
        failed_seams = [
            s for s in seam_report.get("seams", [])
            if s.get("processing", {}).get("status") == "failed"
        ]

        if failed_seams:
            yield PipelineEvent(
                kind="retry_pass_started",
                phase=PipelinePhase.CODE_WRITER,
                payload={
                    "failed_seam_count": len(failed_seams),
                    "seams": [s.get("id") for s in failed_seams],
                },
            )

        for seam_data in failed_seams:
            seam_name = seam_data.get("id") or seam_data.get("name", "main")
            prior_reason = seam_data.get("processing", {}).get("failure_reason")
            enriched_kickoff = _build_seam_kickoff(seam_data) + (
                f"\n\nPRIOR ATTEMPT FAILED — address this before anything else:\n  {prior_reason}\n"
                if prior_reason else ""
            )

            orch.clear_review_artifacts()
            await orch.reset_session(extra_state={"current_seam": seam_name})

            retry_result: dict = {}
            async for ev in _run_tdd_loop_for_seam(
                enriched_kickoff, max_iterations=1, result=retry_result,
                seam_id=seam_name,
            ):
                yield ev

            orch.current_phase = PipelinePhase.WRITER
            async for ev in orch.run_phase(PipelinePhase.WRITER):
                yield ev

            new_status = "success" if retry_result.get("passed") else "failed"
            retry_failure_reason = None if retry_result.get("passed") else retry_result.get("failure_reason")
            update_seam_processing(
                orch.run_dir, seam_name,
                status=new_status,
                retry_attempts=1,
                failure_reason=retry_failure_reason,
            )
            orch.artifacts.pop("seam", None)

            yield PipelineEvent(
                kind="retry_pass_completed",
                phase=PipelinePhase.WRITER,
                payload={
                    "seam": seam_name,
                    "status": new_status,
                    "retry_attempts": 1,
                    "failure_reason": retry_failure_reason,
                },
            )

    # ── Feature Specifier (before seam loop — needs seam.json + tnas.json only) ─
    #
    # Feature Specifier's own prompt asks for specs covering every seam in a
    # single LLM call. Confirmed live, 2026-08-24: for a real 53-seam estate
    # that pushed one request to ~15K input tokens before the model had
    # produced a single output token, against a 16,384-token context window
    # — the call never returned (stuck well past the configured 1-hour
    # llm_timeout). Deterministic mode is unaffected — its fallback in
    # _direct_tool_fallback builds every spec directly in Python, no LLM
    # call at all — so batching only kicks in for real LLM mode on estates
    # bigger than one batch.
    _FEATURE_SPEC_BATCH_SIZE = 8

    async def _run_feature_specifier() -> AsyncIterator[PipelineEvent]:
        skip_llm = orch._skip_llm if orch._skip_llm is not None else get_settings().skip_llm
        seam_ids: list[str] = []
        if not skip_llm:
            try:
                seam_report = json.loads((orch.run_dir / "seam.json").read_text(encoding="utf-8"))
                seam_ids = [s.get("id", "") for s in seam_report.get("seams", []) if s.get("id")]
            except (OSError, json.JSONDecodeError):
                pass

        if skip_llm or len(seam_ids) <= _FEATURE_SPEC_BATCH_SIZE:
            orch.current_phase = PipelinePhase.FEATURE_SPECIFIER
            async for ev in orch.run_phase(PipelinePhase.FEATURE_SPECIFIER):
                yield ev
            return

        batches = [
            seam_ids[i:i + _FEATURE_SPEC_BATCH_SIZE]
            for i in range(0, len(seam_ids), _FEATURE_SPEC_BATCH_SIZE)
        ]
        for batch_num, batch in enumerate(batches, 1):
            # Reset between batches (and before the first) so each batch's
            # prompt starts small instead of accumulating every prior
            # batch's conversation on top of its own — the same reasoning
            # as the per-seam reset in the Code Writer TDD loop above.
            # feature_specifier_batch_seam_ids lets _direct_tool_fallback
            # scope a mid-batch crash recovery to just this batch too (see
            # pipeline.py), instead of regenerating every other batch's
            # seams too (harmless now that submit_feature_specs merges by
            # seam_id, but wasteful and confusing in the run log).
            await orch.reset_session(extra_state={"feature_specifier_batch_seam_ids": batch})
            prompt = (
                f"Begin Phase — Feature Specifier, batch {batch_num}/{len(batches)}.\n\n"
                f"Generate feature specs for ONLY these {len(batch)} seam IDs "
                "(every other seam is covered by a different batch — do not "
                "include them):\n"
                + "\n".join(f"  - {sid}" for sid in batch)
                + "\n\nCall read_seam_data(run_dir=…, seam_ids="
                + json.dumps(batch)
                + ") to load just their data, then call submit_feature_specs "
                "with specs for exactly these seams in a single call."
            )
            orch.current_phase = PipelinePhase.FEATURE_SPECIFIER
            async for ev in orch.run_phase(PipelinePhase.FEATURE_SPECIFIER, override_prompt=prompt):
                yield ev

            # run_phase()'s own generic "was the artifact valid" check isn't a
            # reliable per-batch signal — it only tells us the LAST call in
            # this batch produced something shaped like a valid artifact, not
            # that every seam in THIS batch specifically landed on disk.
            # Verify the one thing that actually matters directly.
            fs_path = orch.run_dir / "feature_specs.json"
            try:
                written_ids = {
                    s.get("seam_id")
                    for s in json.loads(fs_path.read_text(encoding="utf-8")).get("specs", [])
                } if fs_path.exists() else set()
            except (OSError, json.JSONDecodeError):
                written_ids = set()
            missing = [sid for sid in batch if sid not in written_ids]
            if missing:
                from micro_cosmos.orchestration.pipeline import _direct_tool_fallback
                session = await orch.session_service.get_session(
                    app_name=orch.APP_NAME, user_id=orch.user_id, session_id=orch.session_id
                )
                fb_state = dict(session.state) if session else {}
                fb_state["feature_specifier_batch_seam_ids"] = missing
                fallback, fallback_error = _direct_tool_fallback(PipelinePhase.FEATURE_SPECIFIER, fb_state)
                yield PipelineEvent(
                    kind="warning",
                    phase=PipelinePhase.FEATURE_SPECIFIER,
                    payload=diagnostics.warning(
                        phase=PipelinePhase.FEATURE_SPECIFIER.value,
                        source="feature_specifier_batch_verify",
                        message=(
                            f"Batch {batch_num}/{len(batches)}: {len(missing)} of {len(batch)} "
                            f"seam(s) never reached feature_specs.json (agent replied without "
                            f"calling submit_feature_specs, or the call failed) — deterministic "
                            f"fallback " + ("recovered them." if fallback is not None else
                                            f"also failed: {fallback_error}")
                        ),
                    ).to_payload(),
                )

            # submit_feature_specs merges into feature_specs.json and returns
            # only a confirmation. run_phase saves feature_specs_result from
            # session state, which can stay on an earlier batch. Refresh it
            # from the merged file after every batch, including a fallback
            # recovery, so the artifact matches the file.
            from micro_cosmos.orchestration.pipeline import _read_feature_specs_file
            written_specs = _read_feature_specs_file(orch.run_dir)
            if written_specs is not None:
                orch._save_artifact("feature_specs_result", written_specs)

    if start_phase not in (
        PipelinePhase.GATE_4_5,
        PipelinePhase.CODE_WRITER,
        PipelinePhase.PR_REVIEWER,
    ):
        async for ev in _run_feature_specifier():
            yield ev

    # ── Gate 4.5 "Planning" — human approves scope before code gen starts ──────
    if start_phase not in (PipelinePhase.CODE_WRITER, PipelinePhase.PR_REVIEWER):
        _gate_4_5 = PipelinePhase.GATE_4_5
        orch.current_phase = _gate_4_5
        async for ev in orch.open_gate(_gate_4_5):
            yield ev

        _gs_4_5 = orch.gate_states[_gate_4_5.value]
        while _gs_4_5.decision.value == "REJECTED":
            # Re-run Feature Specifier so rejection notes become a RejectionConstraint
            async for ev in _run_feature_specifier():
                yield ev
            orch.current_phase = _gate_4_5
            async for ev in orch.open_gate(_gate_4_5):
                yield ev
            _gs_4_5 = orch.gate_states[_gate_4_5.value]

        if _gs_4_5.decision.value == "ESCALATED":
            yield PipelineEvent(
                kind="error",
                phase=_gate_4_5,
                payload={
                    "message": "Gate gate_4_5 escalated after 3 rejections. "
                    "Pipeline halted pending engineering-lead override."
                },
            )
            return

    # ── Pause after planning ──────────────────────────────────────────────────
    # Fixed-at-launch per-run setting: end the run here, with analysis and
    # planning complete, instead of entering the seam TDD loop. Deliberately
    # placed *after* Gate 4.5 fully resolves (its rejection/re-specify loop and
    # escalation check both run unmodified above) so this only ever fires on an
    # approved planning gate.
    #
    # Guarded by the same start_phase condition as the blocks around it, so an
    # explicit restart into CODE_WRITER still bypasses the pause — a paused run
    # is stoppable, not permanently sealed.
    #
    # Emits the ordinary pipeline_completed event rather than a new event kind:
    # SSE closes cleanly, the run reaches a terminal state, and the zip/report
    # endpoints need no special-casing (they already zip current state on demand
    # and skip reports whose input artifacts are missing). The paused flag only
    # changes the wording of the completion card.
    # Deterministic ETL runs write the destination project here, including when
    # the run pauses after planning. Databricks and Snowflake are the target
    # of the analysis, so the warehouse project has to exist before the seam
    # loop (and still exist when that loop is skipped).
    _skip_llm_for_etl = orch._skip_llm if orch._skip_llm is not None else get_settings().skip_llm
    if _skip_llm_for_etl:
        try:
            from micro_cosmos.etl.catalog import is_etl_target
            if is_etl_target(target_lang):
                from micro_cosmos.tools.coder_tools import _submit_etl_translation
                etl_written = _submit_etl_translation(
                    source_path, source_lang, target_lang, "deterministic", str(orch.run_dir),
                )
                yield PipelineEvent(
                    kind="info",
                    phase=PipelinePhase.CODE_WRITER,
                    payload={
                        "message": (
                            f"Deterministic {target_lang} project written: "
                            f"{etl_written.get('output_dir') or 'no files'}"
                        ),
                    },
                )
        except Exception:
            diagnostics.log.exception(
                "deterministic ETL translation failed for %s", orch.run_id,
            )

    if orch.pause_after_planning and start_phase not in (
        PipelinePhase.CODE_WRITER,
        PipelinePhase.PR_REVIEWER,
    ):
        orch.current_phase = PipelinePhase.DONE
        yield PipelineEvent(
            kind="pipeline_completed",
            phase=PipelinePhase.DONE,
            payload={
                "artifacts": list(orch.artifacts.keys()),
                "paused_after_planning": True,
                "skipped_phases": [
                    PipelinePhase.CODE_WRITER.value,
                    PipelinePhase.SKEPTICAL_REVIEW.value,
                    PipelinePhase.TEST_REVIEW.value,
                    PipelinePhase.FUNCTIONAL_REVIEW.value,
                    PipelinePhase.WRITER.value,
                    PipelinePhase.PR_REVIEWER.value,
                    PipelinePhase.GATE_5.value,
                ],
            },
        )
        return

    # ── Source-code vector index (built once here, before any seam translation
    # starts — source_path is fixed by now and never changes for the rest of
    # the run). If this fails, search_relevant_source() builds it lazily on its
    # own first call instead, so this is a front-loading optimisation, not a
    # hard dependency. ──────────────────────────────────────────────────────
    if start_phase != PipelinePhase.PR_REVIEWER:
        try:
            from micro_cosmos.retrieval.source_index import load_source_index
            ir_graph = orch.load_artifact("ir_graph") or {}
            src_idx = load_source_index(orch.run_dir, source_path, source_lang, ir_graph)
            yield PipelineEvent(
                kind="info",
                phase=PipelinePhase.CODE_WRITER,
                payload={"message": f"Source index ready: {src_idx.chunk_count} chunks, mode={src_idx.mode}"},
            )
        except Exception:
            diagnostics.log.exception(
                "source index build failed for %s — search_relevant_source will build it lazily",
                orch.run_id,
            )

    # ── Seam TDD loop ──────────────────────────────────────────────────────────
    if start_phase != PipelinePhase.PR_REVIEWER:
        async for ev in _run_all_seams():
            yield ev

    # Translate depth stops once the seam tree exists. PR Reviewer and Gate 5
    # are not opened. Default False keeps a full showcase run on the PR gate.
    if orch.stop_after_code_translation and start_phase != PipelinePhase.PR_REVIEWER:
        orch.current_phase = PipelinePhase.DONE
        yield PipelineEvent(
            kind="pipeline_completed",
            phase=PipelinePhase.DONE,
            payload={
                "artifacts": list(orch.artifacts.keys()),
                "stopped_after_code_translation": True,
                "skipped_phases": [
                    PipelinePhase.PR_REVIEWER.value,
                    PipelinePhase.GATE_5.value,
                ],
            },
        )
        return

    # ── PR Reviewer → Gate 5 ──────────────────────────────────────────────────
    orch.current_phase = PipelinePhase.PR_REVIEWER
    async for ev in orch.run_phase(PipelinePhase.PR_REVIEWER):
        yield ev

    gate_phase = PHASE_AFTER_GATE[PipelinePhase.PR_REVIEWER]
    orch.current_phase = gate_phase
    async for ev in orch.open_gate(gate_phase):
        yield ev

    gate_state = orch.gate_states[gate_phase.value]
    while gate_state.decision.value == "REJECTED":
        # A full seam re-run: reset every seam's processing status back to
        # pending first, so the Processing tab reflects only the current
        # (post-rejection) pass rather than accumulating attempt counts
        # across the rejection boundary.
        from micro_cosmos.tools.seam_tools import init_seam_processing
        init_seam_processing(orch.run_dir, force=True)
        orch.artifacts.pop("seam", None)

        async for ev in _run_all_seams():
            yield ev
        orch.current_phase = PipelinePhase.PR_REVIEWER
        async for ev in orch.run_phase(PipelinePhase.PR_REVIEWER):
            yield ev
        orch.current_phase = gate_phase
        async for ev in orch.open_gate(gate_phase):
            yield ev
        gate_state = orch.gate_states[gate_phase.value]

    if gate_state.decision.value == "ESCALATED":
        yield PipelineEvent(
            kind="error",
            phase=gate_phase,
            payload={
                "message": f"Gate {gate_phase.value} escalated after 3 rejections. "
                "Pipeline halted pending engagement-director override."
            },
        )
        return

    # ── Post-Gate-5: Trivy scan of generated output ───────────────────────────
    async for ev in orch._run_trivy_output_scan():
        yield ev

    # ── Generate output security HTML report ──────────────────────────────────
    try:
        import subprocess as _sp
        from pathlib import Path as _Path
        _scripts = _Path(__file__).resolve().parents[2] / "scripts"
        _script  = _scripts / "generate_output_security.js"
        _reports = orch.run_dir / "reports"
        _reports.mkdir(exist_ok=True)
        _out = _reports / "output-security-report.html"
        if _script.exists():
            _r = _sp.run(
                ["node", str(_script), str(orch.run_dir), str(_out)],
                capture_output=True, text=True, timeout=60,
            )
            if _r.returncode == 0:
                diagnostics.log.info("generate_output_security: %s", _r.stdout.strip())
            else:
                diagnostics.log.warning(
                    "generate_output_security failed: %s",
                    (_r.stderr or _r.stdout or "").strip()[:400],
                )
    except Exception:
        diagnostics.log.exception("post-gate5 output security report generation failed for %s", orch.run_id)

    # ── Done ─────────────────────────────────────────────────────────────────
    orch.current_phase = PipelinePhase.DONE
    yield PipelineEvent(
        kind="pipeline_completed",
        phase=PipelinePhase.DONE,
        payload={"artifacts": list(orch.artifacts.keys())},
    )
