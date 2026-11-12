# Bug 1 — `AttributeError` in the ADF scheduler detector, cascading through 3 phases

**Run affected:** `e1acbc0c`
**Mode:** Deterministic (`skip_llm: true`), `auto_approve_gates: true`
**Estate:** `examples/java-bankxyz_fraud_detection` (java → kotlin)
**Symptom:** Pipeline crashed with `FileNotFoundError: [Errno 2] No such file or directory: '/app/runs/e1acbc0c/seam.json'`
**Reproduced on a fresh run:** `c4178994` (same source/settings) — byte-identical failure sequence, confirming this is fully deterministic, not a one-off. Verification run deleted after confirming; `e1acbc0c` is the run of record for this writeup.
**Date found:** 2026-08-19
**Status:** ✅ **RESOLVED** — both fixes implemented, tested and verified live (2026-08-19). See §10 Results.

---

## Plain-English walkthrough (read this first)

A condensed, narrative version of the full analysis below — same facts, same section numbers, written for a quick first read before diving into the technical detail.

**Why this isn't a "Databricks bug" (→ full detail in §0).** The detector is called `adf_scheduler_tools.py` (ADF = Azure Data Factory), which makes it look scoped to Databricks/ADF projects. It isn't. `discover_task_graph()` — the function that dispatches to it — is called **unconditionally on every deterministic-mode run**, from two places, with **no language check anywhere**:
- `seam_tools.py:371` inside `_detect_seams()`
- `cartographer_tools.py:496` inside `analyse_bounded_contexts()`

The ADF detector specifically works by *scanning file content*, not by filename (unlike the Databricks Asset Bundle detector, which just checks for `databricks.yml`). To do that, it walks **every single `.json` file anywhere under the source root** — including build output, test reports, anything — looking for something shaped like an ADF pipeline. So it runs identically whether the estate is Java, COBOL, C#, Python, or PySpark. The failing estate here, `examples/java-bankxyz_fraud_detection`, is a plain Maven/Java project with zero relation to Databricks — it just happened to contain a JSON file that broke the scanner.

**Summary (→ full detail in §1).** The `FileNotFoundError` on `seam.json` that the UI actually showed is the *last* domino, not the cause. Three earlier phases silently failed first; nobody noticed because gates were auto-approved.

**Root cause (→ full detail in §2).** In `adf_scheduler_tools.py`:
- `_load_json()` only catches unreadable/malformed JSON (`OSError`, `JSONDecodeError`) and returns `{}` in that case — but valid JSON doesn't have to be a `dict` (a JSON array is equally valid at the top level).
- `_is_adf_pipeline()` blindly calls `.get("properties")` on whatever `_load_json()` returned, assuming it's always a dict.
- `_find_pipeline_files()` runs this over every `.json` file in the tree via `root.rglob("*.json")`.

The specific file that broke it: `examples/java-bankxyz_fraud_detection/target/cucumber-report/cucumber.json` — a Maven-generated Cucumber test report whose JSON root is a **list**. `doc.get("properties")` on a list → `AttributeError: 'list' object has no attribute 'get'`.

**The cascade, confirmed twice — in `e1acbc0c`'s logs and a fresh reproduction run (→ full detail in §3).** This one exception breaks three separate call sites:
1. **Post-Observer hook** (`pipeline.py:566`) → `produce_seam_report()` fails → caught by a broad `except Exception`, logged, but **`seam.json`/`work_streams.json` never get written**.
2. **Cartographer's deterministic fallback** (`analyse_bounded_contexts`) → fails → caught inside `_direct_tool_fallback`'s own handler → **`bounded_context_map.json` never written**.
3. **Architect's deterministic fallback** (`derive_tnas` → `analyse_bounded_contexts`) → same failure → **`tnas.json` never written**.

None of these are immediately fatal — each just logs a warning and lets the phase "complete" with no artifact. `security_report.json`/`trivy_report.json` exist because Security's scanner reads source directly, independent of the broken artifacts. Because `auto_approve_gates: true`, every gate (1→4.5) auto-approved instantly with nobody seeing these three warnings.

The seam loop still ran once, on a **synthetic placeholder seam** (there's a fallback for when the real seam count is zero) — which is why the review JSONs and Kiro/Skills output exist on disk. Then the retry-pass code (`driver.py:644`) unconditionally does `(orch.run_dir / "seam.json").read_text(...)` with no existence check — and since `seam.json` genuinely never got written, this throws the uncaught `FileNotFoundError` that crashed the whole run.

**Two distinct bugs (→ full detail in §4).**
- **Bug 1a** (root cause): `adf_scheduler_tools.py` doesn't validate JSON shape — language-agnostic, can hit any estate.
- **Bug 1b** (crash site): `driver.py:644` assumes `seam.json` always exists with no guard — a separate, independently-worth-fixing resilience gap.

**The fix, now applied (→ full detail in §5, results in §10).**
- Fix 1a: add `if not isinstance(doc, dict): return False` at the top of `_is_adf_pipeline()`.
- Fix 1b: guard the `driver.py:644` read with `.exists()`, falling back to `{}` so the retry pass just sees zero failed seams instead of crashing.

**Testing, all executed (→ plan in §6, results in §10).** 11 new tests (verified to fail against the unfixed code first); full suite went 150 → **161 passed, 0 failed**; an **11-estate before/after regression sweep** across Java ×3, COBOL ×2, C#, Python ×2 and PySpark ×3 in which **exactly one row changed — the broken one** — and ten were byte-identical; plus a live rebuilt-container run at the exact `e1acbc0c` config that completed all 6 gates with zero `AttributeError`.

**Logging plan (→ full detail in §7).** A `changes-log.md` entry, a new `transferable-skills/memory/` file capturing the "content-shape detectors must validate shape and are language-agnostic if unguarded" lesson, no `CLAUDE.md` change needed (no new architecture, just a bug fix).

**Status:** ✅ resolved — fixes applied, 11 tests added, full regression sweep and live container verification clean. Full evidence in §10.

---

## 0. Important clarification — this is NOT a Databricks/ADF-specific bug

The name "ADF scheduler detector" makes this look like it should only matter for Databricks/Azure Data Factory estates. **It doesn't.** The failing run here is a completely ordinary Java/Maven project (`examples/java-bankxyz_fraud_detection`) with no relationship to Databricks, PySpark, or Azure Data Factory whatsoever.

The reason a "Databricks-only" component broke a plain Java run is architectural: `discover_task_graph()` (the scheduler-format registry in `micro_cosmos/tools/scheduler_tools.py`) is invoked **unconditionally, for every estate, regardless of source or target language** — there is no `if source_lang in (...)` gate anywhere before it runs. It's called from two places that both run on every deterministic pipeline execution:

- `micro_cosmos/tools/seam_tools.py:371` (`_detect_seams()`, guarded only by `if source_path:`, which is always true)
- `micro_cosmos/tools/cartographer_tools.py:496` (`analyse_bounded_contexts()`, Step 1a — no language check at all)

One of the registered detectors, `detect_adf_scheduler()`, works by **content shape, not filename** (unlike the Databricks Asset Bundle detector, which just checks for a `databricks.yml` file). To do that, it recursively scans **every single `*.json` file anywhere under the estate root** — `target/`, `build/`, test-report output, anything — looking for a document shaped like an ADF pipeline definition. This scan runs identically whether the estate is Java, COBOL, C#, Python, or PySpark.

`examples/java-bankxyz_fraud_detection` triggered the crash purely because it happens to contain a Maven build artifact — `target/cucumber-report/cucumber.json`, a Cucumber test report — whose JSON root is a **list**, not a dict. **Any** estate in **any** language with **any** stray non-dict-rooted JSON file anywhere under its root will hit the identical crash. This is why the plan below fixes the detector itself (language-agnostic), not something scoped to Databricks/ADF estates.

---

## 1. Summary

The crash the UI showed (`FileNotFoundError` on `seam.json`) is a **downstream symptom**, not the root cause. The actual bug is an unguarded `AttributeError` in the Azure Data Factory (ADF) scheduler detector, which silently broke seam production, bounded-context classification, and TNAS (target architecture) derivation for this entire run — three phases in a row — well before the fatal crash even happened. Because this run had `auto_approve_gates: true`, no human ever saw the intermediate warnings that would normally have surfaced this at Gate 2/3 before it snowballed.

---

## 2. Root cause

**File:** `micro_cosmos/tools/adf_scheduler_tools.py`

```python
def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}          # only guards malformed / unreadable JSON

def _is_adf_pipeline(doc: dict) -> bool:
    props = doc.get("properties")   # assumes doc is always a dict
    return isinstance(props, dict) and isinstance(props.get("activities"), list)

def _find_pipeline_files(source_path: str) -> list[Path]:
    root = Path(source_path)
    if not root.is_dir():
        return []
    return [f for f in root.rglob("*.json") if _is_adf_pipeline(_load_json(f))]
```

`_find_pipeline_files()` recursively scans **every** `*.json` file under the source estate root (`root.rglob("*.json")`) — not just plausible ADF-pipeline locations — looking for Azure Data Factory pipeline definitions to feed the scheduler-driven seam-detection feature.

`_load_json()` only guards against JSON that is malformed or unreadable (`OSError`/`json.JSONDecodeError`). It does **not** guard against JSON that parses successfully but isn't a JSON object at the top level (a list, string, number, etc. are all valid JSON). `_is_adf_pipeline()` then unconditionally calls `.get("properties")` on whatever came back.

### The triggering file

Confirmed by parsing every `*.json` file in the estate:

```
examples/java-bankxyz_fraud_detection/target/cucumber-report/cucumber.json  →  top-level type: list
```

This is a Cucumber test-report artifact (a Maven build output, `target/`), whose JSON root is an array of scenario objects. When `_find_pipeline_files()` reaches it:

```
props = doc.get("properties")
        ^^^^^^^
AttributeError: 'list' object has no attribute 'get'
```

This exception is raised **inside `_find_pipeline_files()`'s list comprehension**, with no try/except anywhere in `adf_scheduler_tools.py` or in the calling `discover_task_graph()` (`micro_cosmos/tools/scheduler_tools.py:41`) to catch it.

---

## 3. The cascade — confirmed from container logs, twice (`e1acbc0c` at 13:19:22–23, reproduced on `c4178994` at 13:53:23–26)

`discover_task_graph()` is called from three separate places in the pipeline, and this one exception broke all three, identically, on both runs:

| # | Call site | What it feeds | What happened | Consequence |
|---|---|---|---|---|
| 1 | `micro_cosmos/tools/seam_tools.py:371` (`_detect_seams`), invoked via `produce_seam_report()` from the **post-Observer hook** in `pipeline.py:566` | `seam.json`, `work_streams.json` | Exception raised, caught by a blanket `except Exception` at `pipeline.py:570-571`, logged as `post-observer seam production failed for <run_id>` | **`seam.json` / `work_streams.json` never written** |
| 2 | `micro_cosmos/tools/cartographer_tools.py:496` (`analyse_bounded_contexts`), called from **Cartographer's deterministic fallback** (`_direct_tool_fallback`, `pipeline.py:195`) | `bounded_context_map.json` | Exception caught inside `_direct_tool_fallback`'s own `except Exception` (`pipeline.py:301-303`), returned as `(None, "AttributeError: ...")` | **`bounded_context_map.json` never written** |
| 3 | Same `analyse_bounded_contexts()` call, reached via `derive_tnas()` from **Architect's deterministic fallback** (`pipeline.py:197`) | `tnas.json` | Same catch/return pattern | **`tnas.json` never written** |

None of these three failures are fatal by themselves. `pipeline.py:538-552`'s handling of a failed deterministic fallback is deliberately non-fatal — it just emits a `warning` PipelineEvent (`"skip_llm=true, deterministic fallback for cartographer raised: AttributeError: ..."`) and lets the phase "complete" with no artifact saved. This is why `security_report.json` and `trivy_report.json` **do** exist for both runs — the deterministic Security scanner (`scan_source_for_security`) reads source files directly and has no dependency on `bounded_context_map.json`/`tnas.json`.

### Why nobody caught it before the crash

Both runs have `"auto_approve_gates": true`. Every gate (1 → 4.5) auto-approved itself instantly via `MicroCosmosOrchestrator.open_gate()`'s auto-approve branch, with no human ever seeing the three warning events above. In a manually-gated run, an engineer would have seen empty/missing `bounded_context_map.json`/`tnas.json` in the Gate 2/3 summary panels and stopped before the seam loop ever started.

### The actual crash

`_run_all_seams()` (`micro_cosmos/orchestration/driver.py`) still received a non-empty `seams_data` list — `orchestrator.get_all_seams_data()` has a **synthetic-seam fallback** for when the real seam count is zero, so the loop ran exactly one synthetic "main" seam through the TDD loop. This is why `skeptical_review.json` / `test_review.json` / `functional_review.json` (each containing the expected deterministic-mode "agent did not submit a review" placeholder) and the Kiro Powers / Claude Code Skills output under `reports/` all exist on disk for both runs — that part of the pipeline behaved exactly as designed for deterministic mode.

Immediately after that single-seam loop finishes, the post-loop **retry pass** does this with no guard at all:

```python
# micro_cosmos/orchestration/driver.py:644
seam_report = json.loads((orch.run_dir / "seam.json").read_text(encoding="utf-8"))
```

This line assumes `seam.json` already exists by this point in *every* code path. It doesn't — because of the cascade above — so `.read_text()` raises an uncaught `FileNotFoundError`. Nothing in `_run_all_seams()` or `run_full_pipeline()` catches it, so it propagates all the way up to `micro_cosmos/web/app.py`'s `_run_pipeline()`, which logs it as `Top-level pipeline failure` and marks the whole run as crashed — the error the user saw in the UI, on both `e1acbc0c` and the reproduction run `c4178994`.

---

## 4. Two distinct bugs, one incident

### Bug 1a — Primary / root cause: unguarded non-dict JSON in the ADF detector

- **File:** `micro_cosmos/tools/adf_scheduler_tools.py`
- **Functions:** `_is_adf_pipeline()` (line 43-45), `_find_pipeline_files()` (line 48-52)
- **Problem:** `_is_adf_pipeline()` assumes its argument is always a `dict`. `_load_json()`'s exception handling only covers unparseable JSON, not validly-parsed non-dict JSON (list/str/int/bool/null are all legal top-level JSON values). `_find_pipeline_files()` also scans the **entire** estate tree recursively, including build output / generated reports / test artifacts (`target/`, `build/`, `node_modules/`, etc.) that have no relevance to scheduler detection at all — this is what makes hitting an unrelated array-rooted JSON file likely on any real-world estate, of any language, not just Databricks/ADF ones.
- **Blast radius:** Any source estate — for any language, any pipeline, Databricks-related or not — that contains **one** JSON file anywhere under its root whose top level isn't an object will break `discover_task_graph()`, which in turn breaks `produce_seam_report()` (post-Observer hook) and `analyse_bounded_contexts()` (used by both Cartographer's and Architect's deterministic fallbacks, and — per `transferable-skills/memory/databricks-bundle-task-graph-seams.md` / `scheduler-registry-adf-support.md` — also reachable from the LLM-mode agent tools that call the same functions). Java, COBOL, C#, Python, and PySpark estates are all equally exposed; this is confirmed to be language-agnostic, not a Databricks-scoped issue.

### Bug 1b — Secondary / crash bug: unguarded retry-pass read of `seam.json`

- **File:** `micro_cosmos/orchestration/driver.py:644`
- **Problem:** The post-seam-loop retry pass reads `seam.json` from disk with no existence check and no try/except, assuming upstream seam production always succeeds. When it doesn't — for this reason, or any other future reason — this line turns a recoverable "no seams to retry" situation into a hard, unrecoverable pipeline crash.
- **Why this matters independently of Bug 1a:** Even after Bug 1a is fixed, this line remains a single point of failure for the whole pipeline. Any other future failure mode that prevents `seam.json` from being written (a different exception in `produce_seam_report`, a disk/permissions issue, etc.) will crash the run the exact same way, regardless of estate language.

---

## 5. Fix plan (approved, not yet implemented)

### Fix 1a — `adf_scheduler_tools.py`

```python
def _is_adf_pipeline(doc: dict) -> bool:
    if not isinstance(doc, dict):
        return False
    props = doc.get("properties")
    return isinstance(props, dict) and isinstance(props.get("activities"), list)
```
Minimal, single-line-of-defense fix — closes the crash for any non-dict top-level JSON, not just the one file that happened to trigger it. Language-agnostic by construction, since the bug itself is language-agnostic.

**Deliberately scoped out for now:** narrowing `_find_pipeline_files()`'s scan to skip `target/`/`build/`/`node_modules/`-style directories. A legitimate follow-up (less wasted I/O, fewer chances of hitting more unrelated file shapes in the future) but not required to fix the crash, and changing scan scope needs its own scrutiny against every registered scheduler format.

### Fix 1b — `driver.py:644`

```python
seam_path = orch.run_dir / "seam.json"
seam_report = json.loads(seam_path.read_text(encoding="utf-8")) if seam_path.exists() else {}
failed_seams = [
    s for s in seam_report.get("seams", [])
    if s.get("processing", {}).get("status") == "failed"
]
```
`seam_report.get("seams", [])` on an empty dict correctly yields `failed_seams = []`, so the retry-pass block is skipped cleanly. This fix stands on its own value independent of Fix 1a — it makes the pipeline resilient to *any* future reason `seam.json` might be missing at this point.

---

## 6. Testing plan (approved)

Two-layered, deliberately broader than "the reported estate now works": (1) prove `examples/java-bankxyz_fraud_detection` now succeeds, and (2) prove nothing else — no other Java example, no other language's Observer/Cartographer/seam-detection/deterministic-regex-parsing path — changes behavior as a side effect. Given Section 0 above, this is not optional scope-padding: the bug is proven language-agnostic, so the regression check must be too.

1. **New unit tests in `tests/test_adf_scheduler.py`**: a non-dict-JSON-in-estate fixture proving `detect_adf_scheduler`/`parse_adf_scheduler`/`discover_task_graph` no longer raise; a parametrized test asserting `_is_adf_pipeline()` returns `False` (never raises) for list/str/int/`None` top-level JSON. The file's existing 6 tests must keep passing unchanged (proves the guard doesn't alter real-ADF detection).
2. **New driver-level test** (`tests/test_pipeline.py` or a focused new file, matching `tests/test_stop_tdd_loop.py`'s precedent) simulating a missing `seam.json` at the retry-pass checkpoint and asserting graceful skip instead of `FileNotFoundError`.
3. **Primary confirmation**: re-run `examples/java-bankxyz_fraud_detection` (same settings as `e1acbc0c`) end-to-end via the live container. Confirm no `AttributeError`, all four previously-missing artifacts now exist, and the run reaches Gate 5 / `pipeline_completed`.
4. **Full-estate regression sweep — every other example, every other language, byte-for-byte before/after.** Run Observer → Cartographer → Architect → seam detection in deterministic mode against every estate below, snapshot output artifacts, diff before/after the fix:

   | Estate | Language | Expectation |
   |---|---|---|
   | `examples/java-bankxyz_fraud_detection` | Java | **Changes** — broken → working (the reported case) |
   | `examples/java-springboot-legacy-app` | Java | Byte-identical |
   | `examples/java-axonframework-example-app` | Java (Axon) | Byte-identical |
   | `examples/cobol-bankxyz_fraud_detection` | COBOL | Byte-identical (standing regression check per `cobol-seam-detection.md`) |
   | `examples/cobol-mainframe-banking-teller` | COBOL | Byte-identical |
   | `examples/csharp-bankxyz_fraud_detection` | C# | Byte-identical |
   | `examples/fraud_detection` | Python | Byte-identical |
   | `examples/legacy_estate` | Python | Byte-identical |
   | `examples/databricks_bundle_default_python` | PySpark / DAB | Byte-identical (filename-based detector, expected unaffected) |
   | `examples/databricks_adf_notebooks_project` | PySpark / ADF | Byte-identical — direct regression check for Fix 1a's *working* path |
   | `examples/databricks_adf_project1_profile` | PySpark / ADF | Byte-identical, different notebookPath convention |

   Only the first row is expected to change. Any diff elsewhere blocks the fix from being considered complete.
5. **Full automated suite**: `pytest tests/` before/after, confirming pre-existing/pre-documented failures are unchanged in count and identity, and nothing newly fails.

---

## 7. Logging plan (approved)

1. **`changes-log.md`** — new dated entry (`## Bug fix: AttributeError in ADF scheduler detector cascading through 3 phases (2026-08-19)`), prose + a `### Files changed` table, cross-referencing this doc and `transferable-skills/memory/scheduler-registry-adf-support.md`.
2. **`transferable-skills/memory/`** — new file (e.g. `adf-scheduler-non-dict-json-crash.md`, `type: project`) documenting the root cause, the language-agnostic nature of the bug (Section 0's clarification), the 3-phase cascade, and the `driver.py:644` hardening. General lesson to capture: *any content-shape-based detector that scans arbitrary files across an estate (as opposed to a fixed filename like `databricks.yml`) must validate the parsed shape defensively and runs for every estate regardless of language if it isn't itself language-gated — "valid JSON" does not mean "valid dict," and a component named after one ecosystem (ADF) can still break an unrelated one (plain Java) if it's wired in unconditionally.* Link from `[[scheduler-registry-adf-support]]`, index in `MEMORY.md`.
3. **`CLAUDE.md`** — no structural change needed; this is a bug fix within already-documented architecture, not a new phase or mechanism.

---

## 8. Verification checklist before calling this done

- [ ] `_is_adf_pipeline()` returns `False` (never raises) for list/str/int/`None` top-level JSON
- [ ] `driver.py`'s retry-pass read no longer raises when `seam.json` is absent
- [ ] New tests pass; full `pytest tests/` shows no new failures and no previously-passing test now failing
- [ ] Full-estate regression sweep (Section 6, item 4) shows zero diffs outside the `java-bankxyz_fraud_detection` row
- [ ] Live re-run of `examples/java-bankxyz_fraud_detection` (same settings as `e1acbc0c`) completes without the original crash and with all four previously-missing artifacts present
- [ ] `changes-log.md` entry added
- [ ] `transferable-skills/memory/` new file added + linked from `scheduler-registry-adf-support.md` + indexed in `MEMORY.md`

---

## 9. Files referenced in this analysis

| File | Role in this incident |
|---|---|
| `micro_cosmos/tools/adf_scheduler_tools.py` | Root cause — unguarded `.get()` on non-dict JSON |
| `micro_cosmos/tools/scheduler_tools.py` | `discover_task_graph()` — dispatches to `detect_adf_scheduler()` unconditionally for every language, propagates the exception uncaught |
| `micro_cosmos/tools/seam_tools.py` | `_detect_seams()` — calls `discover_task_graph()` for scheduler-driven seams, no language gate |
| `micro_cosmos/tools/cartographer_tools.py` | `analyse_bounded_contexts()` — also calls `discover_task_graph()` unconditionally (Step 1a) |
| `micro_cosmos/tools/architect_tools.py` | `derive_tnas()` — calls `analyse_bounded_contexts()`, inherits the same failure |
| `micro_cosmos/orchestration/pipeline.py` | Post-Observer seam-production hook (line ~566); deterministic-fallback dispatch and non-fatal warning handling (line ~527-559); `_direct_tool_fallback()`'s own catch-and-return (line ~301-303) |
| `micro_cosmos/orchestration/driver.py` | `_run_all_seams()` — synthetic-seam fallback that let the seam loop run anyway (line ~565+); unguarded retry-pass read of `seam.json` (line 644) — the actual crash site |
| `micro_cosmos/web/app.py` | `_run_pipeline()` — top-level catch that logs `Top-level pipeline failure` and marks the run as crashed |
| `examples/java-bankxyz_fraud_detection/target/cucumber-report/cucumber.json` | The specific file that triggered the `AttributeError` — a list-rooted Cucumber test report under a Maven build output directory, with zero relation to Databricks/ADF |

---

## 10. RESULTS — implementation & verification (2026-08-19)

All work below was executed after plan approval. Every number is measured, not estimated.

### 10.1 Fixes applied

| # | File | Change | Verified by |
|---|---|---|---|
| Fix 1a | `micro_cosmos/tools/adf_scheduler_tools.py` | `_is_adf_pipeline()` returns `False` for any non-dict document instead of calling `.get()` on it | 7 parametrized unit tests + live run |
| Fix 1a′ | `micro_cosmos/tools/adf_scheduler_tools.py` | `_load_json()` return annotation corrected `dict` → `object` (it could always return a list/str/int/None; the annotation was actively misleading and is what made the caller's wrong assumption look safe) | code review / type accuracy |
| Fix 1b | `micro_cosmos/orchestration/driver.py:644` | Retry-pass read of `seam.json` guarded with `.exists()`, falling back to `{}` | 2 new driver-level tests + live run |

### 10.2 Test results

| Stage | Result |
|---|---|
| Baseline, before any change | **150 passed, 1 skipped, 0 failed** (matches the documented 2026-08-14 baseline exactly) |
| New tests run against **unfixed** code | **11 failed, 7 passed** — every new test genuinely reproduces the bug; the 7 pre-existing ADF tests were unaffected |
| Full suite, after both fixes | **161 passed, 1 skipped, 0 failed** |
| Net | +11 tests, **zero** regressions, zero newly-failing tests |

New tests added:

| File | Test | Covers |
|---|---|---|
| `tests/test_adf_scheduler.py` | `test_is_adf_pipeline_rejects_non_dict_documents` (7 params: `[]`, list-of-dicts, `"str"`, `42`, `3.14`, `True`, `None`) | Fix 1a at unit level |
| `tests/test_adf_scheduler.py` | `test_non_dict_json_in_estate_does_not_crash_detection` | Full estate with a Cucumber-shaped list-rooted JSON + a real ADF pipeline; asserts detection still works |
| `tests/test_adf_scheduler.py` | `test_non_adf_estate_with_non_dict_json_stays_undetected` | Guards against the opposite error — the fix must not turn a non-ADF estate into a detected one |
| `tests/test_seam_retry_pass_guard.py` | `test_pipeline_survives_missing_seam_json_at_retry_pass` | Fix 1b — deletes `seam.json` at `seam_started`, asserts `pipeline_completed` still reached |
| `tests/test_seam_retry_pass_guard.py` | `test_retry_pass_is_skipped_when_seam_json_absent` | Retry pass no-ops instead of firing against nothing |

### 10.3 Retrofit regression sweep — 11 estates, before vs after

Driven through the **real** pipeline path (`initialise_session()` → `run_phase()` for OBSERVER → CARTOGRAPHER → ARCHITECT), so the post-phase seam-production hooks are genuinely exercised rather than bypassed by calling `identify_seams()` directly.

| Estate | Lang | Before | After | Verdict |
|---|---|---|---|---|
| `java-bankxyz_fraud_detection` | java | 924 IR nodes, **0 contexts, 0 seams, 0 streams, 0 tnas, 2 errors** | 924 IR nodes, **11 contexts, 53 seams, 11 streams, 11 tnas, 0 errors** | ✅ **FIXED** (the target) |
| `java-springboot-legacy-app` | java | 674 / 9 / 23 / 11 / 9 | identical | ✅ identical |
| `java-axonframework-example-app` | java | 251 / 12 / 8 / 11 / 12 | identical | ✅ identical |
| `cobol-bankxyz_fraud_detection` | cobol | 894 / 9 / 11 / 11 / 9 | identical | ✅ identical |
| `cobol-mainframe-banking-teller` | cobol | 402 / 5 / 7 / 11 / 5 | identical | ✅ identical |
| `csharp-bankxyz_fraud_detection` | csharp | 306 / 8 / 12 / 11 / 8 | identical | ✅ identical |
| `fraud_detection` | python | 18 / 1 / 0 / 11 / 1 | identical | ✅ identical |
| `legacy_estate` | cobol | 1 / 1 / 0 / 11 / 1 | identical | ✅ identical |
| `databricks_bundle_default_python` | pyspark | 8 / 4 / 2 / 11 / 4 | identical | ✅ identical |
| `databricks_adf_notebooks_project` | pyspark | 7 / 4 / 4 / 11 / 4 | identical | ✅ identical |
| `databricks_adf_project1_profile` | pyspark | 18 / 8 / 8 / 11 / 8 | identical | ✅ identical |

*(columns: IR nodes / contexts / seams / work streams / TNAS services)*

Compared fields per estate: `ir_nodes`, `ir_edges`, `contexts`, `seam_total`, `seam_types`, `seam_pts`, `streams`, `tnas_services`, `artifacts_present`, error count. **Exactly one row changed — the broken one. Ten rows byte-identical. Zero regressions across Java ×3, COBOL ×2, C#, Python ×2, PySpark/DAB, PySpark/ADF ×2.**

Detail for the fixed row:
- Contexts (0 → 11): Application, Batch, Classes, Config, Domain, Entity, Oracle, Repository, Service, TestUnit, Web
- Seams: 0 → **53** (25 `object`, 22 `link`, 6 `preprocessing`), 328 story points
- Artifacts on disk: 1 → 5 (`ir_graph`, `bounded_context_map`, `seam`, `work_streams`, `tnas`)
- Errors: 2 → **0** (both `AttributeError: 'list' object has no attribute 'get'` warnings gone)

### 10.4 Live docker-compose verification

Image **rebuilt** (`docker compose up -d --build`) so the fixes are baked in, not just `docker cp`'d — confirmed by grepping the running container for both changed lines.

| Check | Result |
|---|---|
| Run config | `java · examples/java-bankxyz_fraud_detection → kotlin`, deterministic, auto-approve ON — identical to `e1acbc0c` |
| Run id | `2e0b0ad7` |
| Gates | **all 6 APPROVED** (gate_1, gate_2, gate_3, gate_4, gate_4_5, gate_5) |
| Previously-missing artifacts | `bounded_context_map.json`, `tnas.json`, `seam.json`, `work_streams.json` — **all 4 present** |
| Also produced | `feature_specs.json` (53 specs), `trivy_output_report.json` (written only *after* Gate 5 — proves full completion) |
| Pipeline output | 53 seams / 328 pts / 11 contexts / 11 streams / 11 TNAS services — matches the sweep exactly |
| `AttributeError` in logs | **0** |
| `Top-level pipeline failure` in logs | **0** |
| `post-observer seam production failed` | **0** |
| Non-Java spot-check | `csharp-bankxyz_fraud_detection → java21`, run `bdbd93ea` — **all 6 gates APPROVED**, full artifact set produced |

Both throwaway verification runs (`2e0b0ad7`, `bdbd93ea`) were deleted after confirming, with container CPU checked as idle first (per the known "don't delete a live run's directory" incident). `runs/e1acbc0c` was left untouched.

### 10.5 New issues found during this work

| Issue | Severity | Action |
|---|---|---|
| `_load_json()` was annotated `-> dict` but could return any JSON type | Low (latent) | **Fixed** (Fix 1a′) — the wrong annotation is precisely what made `_is_adf_pipeline()`'s `.get()` look type-safe to a reader |
| `GET /runs/{id}/gates` returns a JSON **list**, not a dict keyed by gate_id | None — not a bug | No change. Noted here only because a verification script assumed a dict and silently polled `None`; anyone scripting against this endpoint should expect a list |

No other new bugs surfaced.

### 10.6 Pending / unresolved (deliberately not fixed)

| Item | Why not fixed now |
|---|---|
| `_find_pipeline_files()` rglobs the **entire** estate including `target/`, `build/`, `node_modules/` | Out of approved scope. The `isinstance` guard fully closes the crash; narrowing the scan is a performance/robustness improvement that changes detection scope and deserves its own regression pass against all scheduler formats. **Recommended follow-up.** |
| `discover_task_graph()` runs for every estate regardless of `source_lang` | Architectural, by design (a Java repo *could* legitimately contain ADF pipeline JSON). Language-gating it would be a behavioural change needing product input, not a bug fix. |
| `pipeline.py`'s post-OBSERVER/CARTOGRAPHER hooks swallow exceptions into a log line only | Pre-existing, deliberate (non-fatal hooks). This incident showed the downside — three phases lost their artifacts with only a log line — but changing it to surface a UI-visible error is a product decision, not part of this fix. Worth considering given `auto_approve_gates` hides these warnings entirely. |
| `examples/legacy_estate` is Python but every test passes `source_lang="cobol"` | Pre-existing, already documented in `transferable-skills/memory/cobol-seam-detection.md`. Untouched — the sweep used `cobol` to match existing convention. |
| pytest/pytest-asyncio not installed in the Docker image (`pip install .` omits the `dev` extra) | Pre-existing. Requires `pip install pytest pytest-asyncio httpx` inside the container before each suite run on a fresh image. Separate image-size decision. |

---

## 11. Review summary — final hand-off state (2026-08-19)

Everything below was staged, nothing committed. This is the scannable version of §10 for review.

### 11.1 Fixes

| # | File | Change |
|---|---|---|
| 1a | `micro_cosmos/tools/adf_scheduler_tools.py` | `_is_adf_pipeline()` returns `False` for any non-dict document instead of calling `.get()` on it |
| 1a′ | `micro_cosmos/tools/adf_scheduler_tools.py` | `_load_json()` annotation `dict` → `object` — it could always return a list/str/int/None, and the wrong annotation is precisely what made the caller's `.get()` look type-safe |
| 1b | `micro_cosmos/orchestration/driver.py:644` | Retry-pass read of `seam.json` guarded with `.exists()` → `{}` |

### 11.2 Tests

| Stage | Result |
|---|---|
| Baseline (pre-change) | 150 passed, 1 skipped, **0 failed** — matches documented 2026-08-14 baseline |
| New tests vs **unfixed** code | **11 failed**, 7 passed — proves every new test genuinely catches the bug |
| Full suite after fixes | **161 passed, 1 skipped, 0 failed** |
| Net | +11 tests, zero regressions |

### 11.3 Retrofit sweep — 11 estates, before vs after

| Estate | Lang | Verdict |
|---|---|---|
| java-bankxyz_fraud_detection | java | ✅ **FIXED** — 0→11 contexts, 0→53 seams (25 obj/22 link/6 prep, 328 pts), 0→11 streams, 0→11 TNAS, 2 errors→0, 1→5 artifacts |
| java-springboot-legacy-app | java | ✅ identical |
| java-axonframework-example-app | java | ✅ identical |
| cobol-bankxyz_fraud_detection | cobol | ✅ identical |
| cobol-mainframe-banking-teller | cobol | ✅ identical |
| csharp-bankxyz_fraud_detection | csharp | ✅ identical |
| fraud_detection | python | ✅ identical |
| legacy_estate | cobol | ✅ identical |
| databricks_bundle_default_python | pyspark | ✅ identical |
| databricks_adf_notebooks_project | pyspark | ✅ identical |
| databricks_adf_project1_profile | pyspark | ✅ identical |

Compared IR nodes/edges, contexts, seam count + types + points, streams, TNAS services, artifact list, error count. **Exactly one row changed — the broken one.**

### 11.4 Live docker-compose

Image rebuilt (fixes baked in, verified by grepping the running container — not just `docker cp`).

| Check | Result |
|---|---|
| `2e0b0ad7` — exact `e1acbc0c` config | all **6 gates APPROVED** |
| 4 previously-missing artifacts | all present + `feature_specs.json` (53) + `trivy_output_report.json` (post-Gate-5 ⇒ full completion) |
| `AttributeError` / `Top-level pipeline failure` | **0 / 0** |
| C# → java21 spot-check (`bdbd93ea`) | all 6 gates APPROVED, full artifact set |

Throwaway runs deleted (container CPU checked idle first, per the known "don't delete a live run's directory" incident); `runs/e1acbc0c` untouched.

### 11.5 New issues found

- **Fixed:** the `-> dict` annotation on `_load_json()` (latent, and causally part of the bug).
- **Not a bug:** `GET /runs/{id}/gates` returns a *list*, not a dict — a verification poll script assumed a dict and silently read `None`. Recorded for anyone scripting that endpoint.

### 11.6 Unresolved / deliberately deferred

1. `_find_pipeline_files()` still rglobs `target/`, `build/`, `node_modules/` — the guard closes the crash; narrowing scan scope needs its own regression pass.
2. `discover_task_graph()` isn't language-gated — arguably correct (a Java repo *could* hold ADF JSON); gating is a product decision.
3. `pipeline.py`'s post-phase hooks swallow exceptions to a log line only — this incident is the argument for surfacing them, especially since auto-approve hides the warnings. Product decision.
4. `examples/legacy_estate` is Python but tests pass `source_lang="cobol"` — pre-existing, already documented.
5. pytest not in the Docker image — needs `pip install pytest pytest-asyncio httpx` per fresh image.

### 11.7 Files staged for commit

| File | Status |
|---|---|
| `micro_cosmos/orchestration/driver.py` | modified — Fix 1b |
| `micro_cosmos/tools/adf_scheduler_tools.py` | modified — Fix 1a + 1a′ |
| `tests/test_adf_scheduler.py` | modified — 9 new tests |
| `tests/test_seam_retry_pass_guard.py` | **new** — 2 new tests |
| `docs/bug-1-AttributeError-in-the-ADF-scheduler-detector-cascading-through-3-phases.MD` | **new** (git-tracked rename from the spaced filename) + §10/§11 results |
| `changes-log.md` | modified — dated entry + Files changed table |
| `transferable-skills/memory/adf-scheduler-non-dict-json-crash.md` | **new** memory file |
| `transferable-skills/memory/scheduler-registry-adf-support.md` | modified — cross-link to the new memory |

Commit message drafted, `Bug fix: …(2026-08-19)` convention, **not committed** — awaiting review.
