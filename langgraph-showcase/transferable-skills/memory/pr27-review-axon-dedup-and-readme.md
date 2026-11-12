---
name: pr27-review-axon-dedup-and-readme
description: Fixed 2 blocking findings from Samuel Mbah's PR #27 review — a real method-ID dedup order bug in the Axon package-private-method regex added this session, and 3 stale /export/openspec README references left over from the OpenAPI rename (2026-08-13)
metadata:
  type: project
---

Samuel Mbah reviewed PR #27 (the CQRS-framework-detection + OpenAPI-rename/OpenSpec-artifact work,
see [[project_cqrs_framework_detection]] and [[project_openapi_openspec_rename]]) and found two
blocking issues before merge.

## The dedup-order bug — a real correctness bug in the exact feature being shipped

`_parse_java_file` (`micro_cosmos/tools/observer_tools.py`) processes two separate regexes for methods:
`_JAVA_METHOD_RE` (requires an access modifier) and `_JAVA_PKG_METHOD_RE` (requires at least one
annotation, no modifier — added this session specifically to catch Axon's `@EventSourcingHandler`
convention of naming handlers `on` with no access modifier). They were iterated as two fully
sequential passes:
```python
for method_re in (_JAVA_METHOD_RE, _JAVA_PKG_METHOD_RE):
    for m in method_re.finditer(content):
        ...
```
The dedup logic assigns the first-seen `method_id` for a given name the *unsuffixed* id, and every
later occurrence gets suffixed with its own line number. Since Axon's own convention is every
handler in a class is named `on` (real overloads, differentiated only by parameter type), and since
a real codebase can plausibly have SOME `on(...)` overloads with an explicit access modifier and
others bare package-private (an inconsistency you'd genuinely see across a team's code, not a
contrived scenario) — running pass 1 (`_JAVA_METHOD_RE`) to completion before pass 2 started meant
a *later-in-file* modifier-bearing overload would always claim the unsuffixed id ahead of an
*earlier-in-file* package-private one, since loop order (which pattern matched) trumped true source
position. This silently pushed the real, correctly-first-declared handler onto an unpredictable
suffixed id — exactly the kind of bug that corrupts downstream consumers (anything that looks up
`method.ClassName.on` expecting the first overload) without ever raising an exception.

**Fix**: merge both regexes' `finditer()` results into one list, `sorted(..., key=lambda m:
m.start())`, before processing — one combined pass in true source order, regardless of which
pattern matched each occurrence.

**Lesson for future regex-based parser extensions in this file**: whenever a second/third regex
pattern is added to cover a case the first pattern's structure can't (here: no-modifier annotated
methods vs. modifier-bearing methods), and both patterns feed the SAME dedup/id-assignment logic,
they must be merged and re-sorted by position before that shared logic runs — never iterated as
independent sequential passes. This is the second real bug this exact code area has produced this
session (see [[project_cqrs_framework_detection]] for the constructor-matching and
package-private-method gaps found by the live check) — worth treating `_parse_java_file`'s method
handling as a spot that deserves extra scrutiny on any future touch.

## The stale README — a real 404 for anyone following the docs

`README.md` still named the old `/export/openspec` route and `openspec.yaml` filename in 3 places
(a menu-item table, an ASK-tab feature bullet, a repo-structure tree comment) — all left over from
before [[project_openapi_openspec_rename]]'s straight rename (no compat alias). Fixed all 3.
(Two other superficially-similar "openspec" hits — an external `intent-driven.dev` reference link
and a screenshot filename `images/openspec.png` — are unrelated to the app's route and correctly
left untouched.)

## Also fixed, unprompted but trivial: Dockerfile didn't COPY tests/

Every container rebuild lost the whole `tests/` directory, requiring a manual `docker cp` before
any pytest run — added `COPY tests /app/tests`. Test dependencies (`pytest`/`pytest-asyncio`,
already declared as `pyproject.toml`'s `dev` extra) are still installed ad hoc inside the running
container, not baked into the image — that's a separate production-image-size decision, not made
here without being asked.

## New unrelated finding surfaced, not fixed here

`tests/test_tools.py::test_fitness_suite_passes_clean_code` fails on this same container —
`run_fitness_suite`'s real-test-execution sub-check runs pytest against a synthetic fixture with no
test functions, gets "no tests ran," and appears to treat that as a failure rather than a vacuous
pass. Confirmed unrelated to this fix by code path (never touches `_parse_java_file`). Flagged for
the broader PR #26/#27 review pass Joao asked for next, not fixed as part of these two review
comments.

## Files changed

| File | Change |
|---|---|
| `micro_cosmos/tools/observer_tools.py` | Merged + position-sorted method regex matches |
| `tests/test_java_axon.py` | New regression test |
| `README.md` | 3 stale route/filename references fixed |
| `Dockerfile` | `COPY tests /app/tests` added |
