---
name: run-isolation
description: Run ID isolation boundaries — what is and is not isolated between concurrent runs
metadata:
  type: project
---

Verified 2026-06-29 during analysis of run `a23b8d06` (LLM) running alongside a concurrent deterministic run.

## Isolated per run (safe)

| Boundary | Mechanism |
|---|---|
| ADK session state | `InMemorySessionService()` instantiated in `MicroCosmosOrchestrator.__init__` — one instance per orchestrator |
| File system | `self.run_dir = Path(runs_dir) / run_id` — distinct subtree per run |
| Orchestrator instance | `RUNS: dict[str, Run]` in `app.py` — keyed by run_id |
| `APP_NAME = "source"` | Class constant; harmless because session service is per-instance |

## NOT isolated (cross-run risk)

| Shared state | Location | Risk |
|---|---|---|
| `_current_run_dir: str` | `coder_tools.py:113` | Concurrent CODE_WRITER phases — last `set_run_dir()` call wins |
| `_seam_translation_cache: dict` | `coder_tools.py:109` | Cache keys are seam IDs; two runs with the same seam ID could collide |

The three errors observed in run `a23b8d06` were entirely within-run issues. No cross-run contamination contributed to them.
