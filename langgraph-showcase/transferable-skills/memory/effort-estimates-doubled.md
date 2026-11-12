---
name: effort-estimates-doubled
description: Effort/story-point estimates doubled at their single source (_work_for_seam), plus two pre-existing enum-drift bugs (deterministic mode always showing "MEDIUM", a report badge always defaulting to blue) fixed in the same pass (2026-08-10)
metadata:
  type: project
---

Joao disagreed with the pipeline's effort/story-point estimates being too low and asked for them
to be doubled. Every effort/story-point number in the app — `seam.json`, `work_streams.json`,
`feature_specs.json`, every HTML report, the Gate 4.5 dashboard panel, and the Jira export —
traces back to exactly **one** function: `_work_for_seam()` in `micro_cosmos/tools/seam_tools.py`.
It derives `effort` (`XS`/`S`/`M`/`L`, never actually `"XL"` even though that value is documented
downstream) and a hard-coded `story_points` integer per branch from a seam's fan-in (or edge
count, for `link`-type seams). Nothing downstream re-estimates: the Feature Specifier agent is
explicitly instructed to **copy** `work.effort`/`work.story_points` verbatim, in both LLM and
deterministic mode, and every report script/dashboard panel just sums or buckets those copied
numbers. So doubling happens in exactly one place and propagates everywhere automatically — no
need to touch `produce_seam_report()`, `produce_work_streams()`, `feature_spec_tools.py`, or any
`scripts/generate_*.js` file's arithmetic.

## The doubling

Doubled every literal `pts` value in `_work_for_seam()`'s 11 branches (boundary/object/link each
have 3-4 fan-in tiers, preprocessing is flat): `XS` 2→4, `S` 3→6, `M` 5→10, `L` 8→16. The `effort`
labels (`XS`/`S`/`M`/`L`) and `risk` values are untouched — Joao explicitly chose "double the
numbers only" over the alternative of also bumping labels up a tier / introducing a real `XL`
tier, to keep the change minimal and match "increase them by x2" literally.

## Two pre-existing bugs found and fixed in the same pass

Both caused by the same root issue: a long-form enum (`SMALL`/`MEDIUM`/`LARGE`/`XL`) was assumed
in two places that only ever actually receive the short codes `_work_for_seam()` produces.
Neither bug is *caused* by the doubling, but Joao approved fixing both while touching this code,
since otherwise the corrected/doubled numbers wouldn't display right everywhere:

1. **`micro_cosmos/orchestration/pipeline.py`'s deterministic-mode Feature Specifier fallback** validated
   `effort in ("SMALL", "MEDIUM", "LARGE", "XL")` — a short code like `"S"` or `"XS"` can never
   match that tuple, so every seam's `feature_specs.json` entry silently fell back to
   `effort: "MEDIUM"` regardless of its real computed tier, in deterministic mode only (LLM mode
   just copies the field and was unaffected by this specific check, though the same wrong enum
   was also documented — misleadingly, not behaviorally — in the agent's own instructions).
   Fixed to check against `("XS", "S", "M", "L", "XL")` with a `"M"` default instead of `"MEDIUM"`.
2. **`scripts/generate_feature_specs.js`'s `effortBadge()`** keyed its color-styles dict on the
   same wrong long-form enum, so every real badge (always a short code) fell through to the
   default `MEDIUM`/blue style — every seam looked like medium effort regardless of reality.
   Re-keyed to `XS`/`S`/`M`/`L`/`XL`, matching the convention `dashboard.js`'s own Gate 4.5 effort
   histogram already uses (`["XS","S","M","L","XL"]`) — that histogram was already correct; only
   this one report script had the wrong keys.

Both were caught by tracing every consumer of `work.effort`/`work.story_points` before touching
anything, not by symptom-chasing — worth remembering: when a field flows through several
independent consumers (agent instructions, a deterministic fallback, N report scripts, a
dashboard panel), check each one's *own* enum/key assumptions rather than assuming they all agree
with the producer.

## Verification

New `tests/test_seam_effort.py` — parametrized over every fan-in threshold in every seam type
(boundary/object/link/preprocessing), asserting the doubled `story_points` values, plus a
regression test reproducing the enum-check logic to confirm it now resolves to the real short
code instead of always `"M"`. All pass; confirmed the 5 pre-existing unrelated test failures
(documented in [[stop-tdd-loop-button]]) are unaffected.

Live verification (deterministic mode, `examples/java-springboot-legacy-app`, run driven directly
via `run_full_pipeline()` with gates auto-approved, same technique as the Stop-TDD-loop testing):
`seam.json`'s `work_summary.total_story_points` came out to 126 for 23 seams (7 object + 12 link
+ 4 preprocessing, 0 boundary) — consistent with the new doubled per-branch values, not the old
halved ones. `feature_specs.json` showed real per-seam effort tiers (`"S"`, `"XS"`) instead of a
wall of `"MEDIUM"`, confirming bug fix #1. Generated `reports/feature-specs.html` for that run and
grepped the rendered badge spans: 17 `"S"` and 6 `"XS"` badges all rendered their own (green)
style, not the blue `MEDIUM` default — confirming bug fix #2.

## Files changed

| File | Change |
|---|---|
| `micro_cosmos/tools/seam_tools.py` | Doubled every `story_points` literal in `_work_for_seam()` |
| `micro_cosmos/orchestration/pipeline.py` | Fixed deterministic-mode effort enum check + default |
| `scripts/generate_feature_specs.js` | Fixed `effortBadge()`'s enum keys |
| `micro_cosmos/agents/feature_specifier.py` | Corrected the effort enum in the instruction docstring |
| `tests/test_seam_effort.py` | New automated regression test |
