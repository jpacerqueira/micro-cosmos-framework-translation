---
name: databricks-cartographer-classification
description: Why Cartographer/Architect failed with "no deterministic fallback" on Databricks notebook estates (2026-08-04) — two path-classification bugs plus a missing generic drill-deeper layer
metadata:
  type: project
---

## The question that started this

Joao ran a live deterministic-mode pipeline against a new PySpark/Databricks example (`examples/azure_databricks_project_to_bigquery_v1_0`) on the Cloud Run deployment. Cartographer and Architect both failed with `"skip_llm=true but no deterministic fallback for cartographer."` — a message that, on its face, means "this phase has no deterministic tool registered." That was misleading: Cartographer and Architect both have registered fallbacks (`analyse_bounded_contexts`/`derive_tnas`), the same ones that work correctly for Java/COBOL every day.

## Root cause #1, found first: exception swallowing

`_direct_tool_fallback()` in `pipeline.py` wrapped its whole dispatch table in one blanket `try/except: return None`, so "tool genuinely not implemented for this phase" and "tool raised a real exception" were indistinguishable to every caller. Fixed by changing the return type to `(result, error_message)` — `error_message` stays `None` for both success and the genuine no-fallback case (those two still don't need distinguishing), but is now populated with the real exception text when a registered tool actually raises. This alone didn't fix anything — it just made the real error visible instead of hidden, which is what let the next two causes get found instead of guessed at.

## Root cause #2: an over-broad substring match

With the real error surfaced, it read: `ValueError: Context 'ProjectManagement' contains 24/24 prog.* nodes (100%) — exceeds 40% limit.` Cartographer's Rule 9 (in `_classify_prog_node`, `cartographer_tools.py`) matched the bare substring `"/project"` — which matched inside `project2_next_bis_domain`, a Databricks data-mesh domain folder name that has nothing to do with project management. Every file in the estate shared this substring, so every file landed in one context, tripping the classifier's own >40%-single-context safety check (only enforced once an estate has ≥20 `prog.*` nodes — smaller estates never hit this, which is exactly why it went unnoticed on the smaller committed `project1_databricks_adf` example). Fixed by requiring the trailing slash: `"/project/"`.

## Root cause #3, found by re-testing rather than assuming the first fix was enough

After fixing Rule 9, the exact same `ValueError` still fired — now against a different single bucket. Rule 14c (the generic structural fallback, used for any non-TS/Java/C# codebase) unconditionally discarded any path segment starting with a digit: `not re.match(r"^\d", p)`. This silently dropped Databricks' own naming convention for pipeline-stage folders — `01_bis_hub`, `02_branded_spoke`, `03_warehouse_streaming` — which is exactly the segment carrying the estate's real domain signal. Fixed: numeric-prefixed segments now contribute their stripped remainder (`01_bis_hub` → `bis_hub`) instead of being discarded outright; only bare numeric segments with no suffix are still dropped.

## The deeper structural gap this exposed

`analyse_bounded_contexts()` already had a "drill deeper when one context captures >40% of nodes" mechanism (Step 1b) — built because a single-module Java/Kotlin project legitimately collapses to one top-level bucket, and the fix for that is to drill one level deeper into the package path. But that re-drill only had classifiers for Java/C#/COBOL (`_classify_java_layer`/`_classify_csharp_layer`/`_classify_cobol_layer`) — nothing for Python/notebook estates, so any Python codebase that legitimately needed the re-drill had nowhere to go. Added `_classify_generic_layer()`: takes the file's immediate parent directory, strips any ordinal prefix the same way as Rule 14c, and uses that as the drilled-down context. Wired into Step 1b's existing `or` chain, so this benefits any future non-JVM/COBOL estate that trips the 40% check, not just Databricks.

## Verified live, before/after, real and synthetic estates

Built a 24-file synthetic repro matching the reported estate's directory structure (not committed — ephemeral, `/tmp/databricks_repro/`), since the real estate was only ever uploaded live via `/demo/upload`, never committed to this repo.

| Estate | Before | After |
|---|---|---|
| Synthetic repro (24 files) | `ValueError`, both Cartographer + Architect fail | 4 contexts: BisHub, BrandedSpoke, WarehouseStreaming, EtlJobs — both phases succeed |
| `examples/project1_databricks_adf` (already committed, same numbered-notebook convention) | 1 context, 18/18 prog nodes — silently "worked" only because it stayed under the 20-node threshold | 7 contexts: BisAnalytics, DataProfiling, DataQuality, EtlJobs, PaymentDiagnostics, Tests, Examples |

Full `tests/` suite before/after (`git stash` diff): identical 9 pre-existing, unrelated failures — no regressions, nothing newly fixed by accident.

## Lesson

Same pattern as the COBOL seam investigation ([[cobol-seam-detection]]): the first fix that made the reported symptom go away (Rule 9) wasn't sufficient, and re-testing immediately after applying it — rather than declaring done — is what surfaced root cause #3. Also: a safety check that's only enforced above a node-count threshold (here, 20) can hide a real classification bug indefinitely on every smaller example, which is exactly what happened with `project1_databricks_adf` sitting at 18 nodes.
