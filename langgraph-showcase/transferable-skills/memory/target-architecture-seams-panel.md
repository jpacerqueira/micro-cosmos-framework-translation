---
name: target-architecture-seams-panel
description: "Target architecture & features" section added to the Seams tab, below the existing source-seam view — reuses tnas.json/feature_specs.json (already computed, never rendered as anything but raw JSON before), plus a case-sensitivity gotcha carried over from the same-day effort-badge bug (2026-08-10)
metadata:
  type: project
---

Joao asked: the Seams tab shows source-side seams already (`seam.json`/`work_streams.json`, via
`_streamCard()`/`_seamRow()` in `dashboard.js`) — could it also show the target-side seams and
features below that, in the same tab?

## Where the target data already lived

No new backend work was needed — both artifacts already exist, fully computed, in both LLM and
deterministic mode:

- **`tnas.json`** (Architect phase, after Gate 3) — `services[]`, each a target
  service/component: `service_id`, `migration_risk` (`LOW`/`MEDIUM`/`HIGH`, uppercase), `rationale`.
  Plus `context_decisions[]` (`context`, `communication_style`, `data_store`, `execution_model`)
  and, LLM mode only, a `pattern_recommendation` per service (e.g. "hexagonal / ports-and-adapters").
- **`feature_specs.json`** (Feature Specifier phase, after Gate 4) — `specs[]`, one per source
  seam: `title`, `business_value`, `story_points`, `api_surface` (inferred REST/gRPC endpoint,
  null if not applicable).

Both are already served generically via `GET /runs/{run_id}/artifacts/{key}` (`orch.
load_artifact(key)` just reads `<run_dir>/<key>.json`) — so this was a pure frontend addition.
Before this change they were only visible as raw JSON in the Artifacts tab's generic
`jsonTreeHtml()` viewer, never as styled cards anywhere.

`scripts/generate_synthesis.js`'s `buildDomains()` already had the exact join logic to mirror:
match `tnas.services[].service_id` (falling back to the older `.name` key) against
`context_decisions[].context` by bounded-context name, to pair a service with its communication
style. Ported that same join into `dashboard.js` rather than inventing a new one.

## Design decision: two independent sub-sections, not one

Confirmed with Joao: split into **Target Services** (from `tnas.json`) and **Target Features**
(from `feature_specs.json`), not merged — because they land at different pipeline phases (Gate 3
vs Gate 4). `loadTargetPanel()` fetches both in parallel and 404-tolerates each independently, so
`renderTargetPanel()` can show real data for one while the other still shows its own "not yet
available" hint. Verified live: right after Gate 3, Target Services was already populated while
Target Features correctly still showed its pending message — not a shared blocking state.

Also confirmed: target seams means the **target architecture** (what Architect decided the
target services/components should look like), not the **actual translated output** per seam.
The latter isn't tracked anywhere today as a consolidated per-seam index — `write_manifest.json`
and `seam_result.json` both get overwritten on every seam iteration and only ever hold the
*last-processed* seam by the time a run finishes; `feature_specs.json.specs[].translated_files`
looks purpose-built for this but nothing populates it. Building that would need new Writer-phase
instrumentation — flagged as a possible future request, deliberately out of scope here.

## The case-sensitivity bug this would have reintroduced

Earlier the same day, [[effort-estimates-doubled]] found and fixed a bug where an uppercase enum
from one part of the pipeline didn't match a lowercase-keyed CSS/validation elsewhere. The exact
same shape of bug was sitting right here: `tnas.services[].migration_risk` is uppercase
(`"LOW"`/`"MEDIUM"`/`"HIGH"`), but the existing `.ws-risk-low/-medium/-high` CSS classes (already
used by `_streamCard()` for source-seam risk) are lowercase-keyed. `_targetServiceCard()`
explicitly lowercases `migration_risk` before building the class name — caught by cross-checking
the CSS rule's actual key casing before writing the JS, not after seeing an unstyled badge live.
Verified via `getComputedStyle`: the rendered badge's `background-color` matched `.ws-risk-low`'s
real CSS value, not an unstyled fallback.

## Verification

New `tests/test_target_architecture_data.py` — runs Observer→Cartographer→Architect (and
separately, through Feature Specifier) via the `skip_llm_orch` fixture pattern already
established in `test_pipeline.py`, and asserts: every `tnas.services[].service_id` has a matching
`context_decisions[]` entry (the join key the dashboard depends on — if these ever drift, the
join silently renders a service with no communication-style tag rather than erroring); `
migration_risk` stays in the uppercase vocabulary the frontend lowercases; `feature_specs.json`
specs carry `title`/`business_value`/`story_points`/`api_surface`. Note: `examples/legacy_estate`
(the COBOL sample most other tests in this repo use) produces **zero** real seams in `seam.json`
for this pipeline — `read_seam_data()` (used by the Feature Specifier) has no synthetic-seam
fallback the way `MicroCosmosOrchestrator.get_all_seams_data()` does, so the feature-specs test uses
`examples/java-springboot-legacy-app` instead, which has real seams.

Live via Playwright, deterministic mode: approved gates 1-3, switched to the Seams tab — Target
Services showed real service cards, Target Features correctly showed its pending hint. Approved
gate 4 (Feature Specifier runs), switched tabs away and back — Target Features now populated too.
Risk badges confirmed rendering their real color via `getComputedStyle`, not unstyled.

## Files changed

| File | Change |
|---|---|
| `micro_cosmos/web/templates/run.html` | New `#target-feed` block in the Seams tab panel |
| `micro_cosmos/web/static/js/dashboard.js` | `_targetServiceCard()`, `_targetFeatureRow()`, `renderTargetPanel()`, `loadTargetPanel()` |
| `micro_cosmos/web/static/css/app.css` | New `.seam-target-*` rules (reuses `.ws-card`/`.ws-seam-row`/`.ws-risk` as-is) |
| `tests/test_target_architecture_data.py` | New automated regression test |
