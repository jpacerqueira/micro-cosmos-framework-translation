---
name: openapi-rename-and-openspec-artifact
description: Renamed the mislabeled OpenAPI export (was internally "openspec"), added a real Fission-AI/OpenSpec artifact alongside Skills/Kiro Powers, and aligned Security/Logging content across all three (2026-08-13)
metadata:
  type: project
---

Joao opened a generated report (`runs/.../reports/openspec.yaml`) and noticed it was genuinely an
OpenAPI 3.1.0 document (`openapi: 3.1.0`, `info`, `paths`, `components`) mislabeled "openspec"
throughout the codebase — internal function/route/filename only; the UI-visible label already
correctly said "OpenAPI 3.1 spec". Three asks: (1) rename it correctly, (2) add a genuinely new
"OpenSpec" artifact (the real [Fission-AI/OpenSpec](https://github.com/Fission-AI/OpenSpec)
Markdown spec-driven-development convention) alongside the existing Skills/Kiro.dev Powers
artifacts, with its own menu entry and generate/regenerate/download capability, (3) make Skills,
Kiro Powers, and OpenSpec cover the same 5 topics (app, security, observability, logging, testing)
at similar depth.

## The naming collision was real, and resolving it in the right order mattered

Before touching anything, confirmed via two `AskUserQuestion` rounds: (a) straight rename, no
compatibility alias — this is an internal tool with no external API consumers; (b) OpenSpec
content must be derived from real per-run pipeline artifacts, not a generic template like
Skills/Kiro Powers (both are pure templates parameterized only by source/target language). Did
Change 1 (the rename) in isolation before Change 2 (the new artifact) so no single diff mixed
"renaming away from openspec" and "renaming toward openspec for something else" — a real
readability trap if done in the same pass.

## Skills/Kiro Powers have a real, pre-existing "Regenerate" bug — found, not fixed, in the existing two

`_write_output_skills`/`_write_kiro_powers` (`micro_cosmos/tools/writer_tools.py`) take no run-artifact
input at all — only `source_lang`/`target_lang`/`seam_name`/`project_dir` — and every call site
guards with `if not dir.exists(): ...`. Their "Regenerate" button (`run.html`'s `dl-regen-btn`)
only ever re-zips existing folder contents; it never re-invokes the writer function. Once the
folder exists for a run, content is frozen forever, and "Regenerate" is a silent no-op. This was
flagged but deliberately NOT fixed for Skills/Kiro Powers themselves (out of the requested scope,
and their content genuinely never changes mid-run since it's not artifact-derived) — but it's the
exact bug class the new OpenSpec artifact was designed to avoid from day one, since its content
*can* legitimately change (a Gate 3/4.5 rejection + re-run produces different `tnas.json`/
`feature_specs.json`). OpenSpec's "Generate" and "Regenerate" are the same force-refresh code path
for exactly this reason.

**Lesson for future artifact-generator work in this codebase**: before adding "Regenerate" to
anything, check whether the underlying writer function is actually re-invoked, or whether the
existing pattern only re-zips stale content — this bug is easy to introduce silently by copying
the Skills/Kiro Powers pattern verbatim without noticing the guard.

## Content-parity audit found two real, differently-shaped gaps

Checked before designing anything: **Security had zero dedicated Skill/Power** — only a 4-line
bolted-on checklist inside the code-reviewer power, nothing in its Skill counterpart at all.
**Logging had no depth distinct from Observability** — one row in a 5-dimension scoring table; all
real content (six full per-language code-sample sections in the Kiro power) was tracing/OTel-only.
**Testing already had real, decent depth** (3-category taxonomy, enforced as BLOCKER) — left
alone except pointing at the new shared constant for consistency.

Fixed with one shared-content source per topic in `writer_tools.py`
(`_SECURITY_CATEGORIES`/`_TESTING_TAXONOMY_CHECKLIST`/`_LOGGING_STANDARDS_CHECKLIST`/
`_OBSERVABILITY_CHECKLIST`), rendered natively by all three generators — a Skill checklist, a Kiro
POWER.md expanded form, and an OpenSpec ADDED-Requirements/Scenario block. This is the direct fix
for "these three artifact types shouldn't drift apart" — a category added to the shared constant
automatically appears in all three next time they're generated, rather than needing three
hand-synced edits.

One nuance: `micro-cosmos-code-reviewer-power`'s existing "### 3. Test Coverage" section is a **plain**
(non-f) string in the source — converting it to an f-string to interpolate the shared constant
risked breaking on literal `{Aggregate}`-style placeholder text elsewhere in that same ~120-line
string (Python would try to evaluate `{Aggregate}` as an expression). Kept it a plain string and
manually synced the equivalent wording instead of literally sharing the Python constant at that
one call site — still content-aligned, just not mechanically DRY there. Worth knowing before
touching that block again.

## Real bugs the live deterministic-mode run caught that the hand-written unit-test fixtures missed

Ran the actual analysis chain (`Observer → Cartographer → Architect → Security → Feature
Specifier`, via the same `_direct_tool_fallback` path `tests/test_pipeline.py` already uses)
against a real example estate before calling this done — caught two bugs unit tests with synthetic
fixtures didn't:

1. **`tnas.json`'s `fitness_suite` is `{"functions": [...], "target_language": ...}`, not a bare
   list** — `architect_tools.py`'s `build_canonical_suite(target_lang).model_dump(mode="json")`
   serializes the whole `FitnessSuite` object. The new OpenSpec `design.md` builder assumed a bare
   list and crashed (`AttributeError: 'str' object has no attribute 'get'` — iterating a dict
   yields its keys). The hand-written test fixture had made the same wrong assumption, so it never
   caught this. Fixed both the generator and the fixture, with a regression assertion added.
2. **`_direct_tool_fallback`'s `FEATURE_SPECIFIER` branch returns a summary dict
   (`{"ok", "path", "specs_written", ...}`), not the specs list** — `submit_feature_specs` writes
   `feature_specs.json` to disk as a side effect and returns a summary of that write, not the
   artifact itself. A first draft of the live-check script re-serialized that summary dict *over*
   the correctly-written file, clobbering it. Fixed by reading the real artifact back from disk
   after calling the fallback, rather than trusting its return value to be the artifact.

**Lesson, repeated from this session's CQRS-detection work**: a synthetic unit-test fixture,
however carefully hand-written, encodes the author's *assumption* about a shape — it can pass
while a live run against the real artifact-producing code proves that assumption wrong. Always run
the live check before calling a cross-artifact generator complete, especially one (like this)
whose whole point is reading multiple other artifacts' real shapes.

## Verification status: deterministic mode complete, LLM mode partial

Deterministic-mode live check is complete and passed end-to-end (Observer → Feature Specifier →
`export_openapi`/`_write_openspec`/`_write_output_skills`/`_write_kiro_powers`, against a real
example estate, zero cross-artifact drift). An LLM-mode live check (`skip_llm=False`, real ADK
agents against local LM Studio) got through Observer, Cartographer, Architect, and Security
successfully with real LLM-produced artifacts — then the container was killed (`exit 137`)
partway through Feature Specifier, most likely memory pressure from running the LLM pipeline and
the live web UI at the same time (Joao was actively browsing the app in his browser during the
same window, confirmed via the container's own request logs). This was environmental, not a code
issue, and Joao confirmed the deterministic + partial-LLM verification already done is sufficient
for now — he'll run the container himself next rather than have me retry the LLM-mode check.

**Unrelated finding surfaced while investigating this**: `examples/java-axonframework-modern-app`
and `examples/java-springboot-legacy-app` both appeared as deleted in `git status` at different
points during this session, each time paired with a new untracked sibling directory
(`*-example-app`, `*-sample1-app`) containing the same content. Confirmed with Joao: this is
expected — those example directories were being renamed (by him, outside this session), not a
data-loss bug. Content was verified intact before he confirmed (e.g. `Portfolio.java`'s
`@Aggregate`/`@CommandHandler` annotations all present in the renamed copy) — worth knowing this
pattern can happen in this repo if it comes up again: check content parity before assuming
`git status` deletions are real.

## Files changed

| File | Change |
|---|---|
| `micro_cosmos/tools/feature_spec_tools.py` | `export_openspec` → `export_openapi` |
| `micro_cosmos/web/app.py` | Rename (2 blocks); new 4-way folder classifier; force-regenerate branches |
| `micro_cosmos/web/templates/run.html` | Rename; new "OpenSpec" dropdown menu group |
| `micro_cosmos/web/static/js/dashboard.js`, `scripts/generate_feature_specs.js` | Rename |
| `micro_cosmos/agents/feature_specifier.py`, `micro_cosmos/orchestration/pipeline.py` | Rename (prose/comment) |
| `micro_cosmos/tools/writer_tools.py` | New `_write_openspec`; shared content constants; new security Skill/Power; Logging Standards retrofit |
| `micro_cosmos/orchestration/driver.py` | New guarded `_write_openspec` call |
| `tests/test_openapi_rename.py`, `tests/test_openspec_generator.py`, `tests/test_download_folder_classification.py`, `tests/test_skills_kiro_openspec_parity.py` | New files |
