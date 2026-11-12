---
name: cobol-seam-detection
description: Why COBOL seam detection produced zero object/boundary seams (2026-07-22) — three compounding causes, none of them the COBOL parser or a tree-sitter gap
metadata:
  type: project
---

## The question that started this

Joao asked why the pipeline can't calculate seams for COBOL (`cobol-bankxyz_fraud_detection`, `cobol-mainframe-banking-teller`). First checked: is this a tree-sitter gap? **No** — tree-sitter was never implemented for COBOL, and was never meant to be (a prior team decision: mainframe/COBOL parsing is deliberately bespoke regex/fixed-column logic, not AST-based, unlike Java/C#). Confirmed via `git blame`/`changes-log.md` that this was a deliberate scope decision, not an oversight or regression.

So the real question was: why does the (correctly-scoped, working-as-designed) regex parser's output fail to produce seams downstream?

## Three compounding causes, found by reproducing live against a real example, not reasoned about in the abstract

Before any fix: `examples/cobol-bankxyz_fraud_detection` produced **8 seams, all type `link`** (from the existing bounded-context-crossing fallback in `seam_tools.py`, explicitly built for "codebases where all files share a single flat directory (e.g. COBOL mainframe programs)"). Object, boundary, and preprocessing seams were genuinely zero, not just thin.

**1. Parser-level (the more fundamental cause, found second — don't stop at the first plausible explanation):** `_parse_cobol_file` in `observer_tools.py` never created a node for a program's "mainline" — the standard COBOL pattern of real logic (including `PERFORM`s) running directly under `PROCEDURE DIVISION`, before any named paragraph header exists. `current_para_id` stayed `None` until the first paragraph header, silently dropping every `PERFORM` issued before it (no source node to attribute the `CALLS` edge to — `if current_para_id:` guarded edge creation and just skipped). Confirmed directly against real files: `FDRULES.cbl` and `FDALERT.cbl` both have 40-80+ lines of mainline logic before their first paragraph header. The whole 9-program estate had only **2** `PROCEDURE`→`PROCEDURE` edges against ~49 raw `PERFORM` statements grepped across the files — most of the real call graph was being thrown away before it ever reached seam detection.

**2. Seam-detection-level:** `_detect_seams()` in `seam_tools.py` only ever examined `PROGRAM`-type nodes and `PROGRAM`→`PROGRAM` `CALLS` edges. Correct assumption for Java/C# (one file per class, most meaningful calls cross file boundaries) but wrong for COBOL — one COBOL program (one file, one `PROGRAM` node) contains all its real internal structure in its paragraphs (`PROCEDURE` nodes), connected by intra-program `PERFORM`. That entire signal was invisible to seam detection regardless of cause #1.

**3. Seam-detection-level:** `_FAN_IN_THRESHOLD = 3` was tuned against Java-scale codebases. This estate's two real cross-program hubs — `FDRULES` and `FDALERT`, each called by `FDRTCHK` and `FDTXNMON` — top out at 2 callers each. One below the threshold, for the two most obviously important seam candidates in the whole estate.

**Explicitly ruled out:** switching to a better COBOL parser (ProLeap, tree-sitter-cobol) would not have fixed any of this on its own — the regex parser's *output* for paragraphs/data/calls was already structurally correct where it wasn't hitting bug #1; the bug is entirely in what happens to that data afterward. A higher-fidelity parser feeding the same broken downstream logic still produces zero seams.

## Fix

- `observer_tools.py`: synthesizes a `proc.<program>.mainline` `PROCEDURE` node the instant `PROCEDURE DIVISION` is seen, giving mainline `PERFORM`s a real source node. Overwritten the moment a real paragraph header appears, same as any other paragraph transition — no special-casing needed downstream.
- `seam_tools.py`: new `_adaptive_fan_in_threshold(callers_of, absolute, floor=2)` — falls back to the estate's own observed max fan-in when it never reaches the absolute threshold, floored at 2 (a single caller isn't meaningfully a hub). No-op for estates that already clear the threshold on their own — **verified**, not assumed: Java's seam count is byte-for-byte unchanged (58 seams, same 25/0/27/6 breakdown) before and after this change.
- `seam_tools.py`: new `PROCEDURE`-level fan-in pass, structurally identical to the existing `PROGRAM`-level one, over intra-program `CALLS` edges — this is what actually surfaces COBOL's real internal substitution points (e.g. a shared paragraph called from several places in the same program).

## Verified live, before/after, same real example

| Metric | Before | After |
|---|---|---|
| `PROCEDURE`↔`PROCEDURE` edges | 2 | 23 |
| Total seams | 8 (all `link`) | 11 (3 `object`, 8 `link`) |
| `FDRULES` flagged | No | Yes |
| `FDALERT` flagged | No | Yes |
| `proc.FDALERT.return-to-caller` flagged | No | Yes |
| Java seam count (regression check) | 58 | 58 (unchanged) |

`tests/test_cobol_seams.py` (3 tests) — each verified to fail against the pre-fix code and pass against the fix, not just written and assumed correct. Full `tests/` suite before/after: same 9 pre-existing failures (fitness suite, Java Axon parsing, gate states, pipeline artifact validation), unrelated, unchanged.

## Lesson

Two "reproduce it live, don't stop at the first plausible cause" moments in one investigation: the seam-detection filtering (cause #2/#3) was the more *obvious* hypothesis and would have been an easy place to stop, but it wasn't sufficient on its own — most of the real call-graph data was already being discarded one layer earlier, at parse time (cause #1), which only surfaced by actually diffing raw `grep`-counted `PERFORM` statements against the parsed edge count rather than trusting that the parser's output was complete.

## Known unrelated finding, not fixed here

`tests/test_pipeline.py`'s `ESTATE = "examples/legacy_estate"` docstring calls this "the legacy COBOL estate" and the tests pass `source_lang="cobol"` against it — but that directory is actually Python files (`credit_decisioner.py` etc.), not COBOL. Pre-existing, unrelated to this fix, not touched — flagged here so it isn't rediscovered and conflated with this investigation.
