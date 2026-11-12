---
name: c-source-support-and-gnucobol-golden-master
description: Added real C source parsing (tree-sitter deep parser + call extractor) and GnuCOBOL to the container for golden-master/differential testing; found and fixed two bugs invisible until "c" existed as a source language, plus two already-diagnosed container bugs (BUG-3, BUG-6) reproduced and fixed along the way (2026-09-04)
metadata:
  type: project
---

Two independent gaps blocked the planned weekend validation (CBSA COBOL + a small GNU coreutils
C subset through the real pipeline): equivalence for a COBOL estate could only be judged by code
review (nothing could compile/run the *original* COBOL to diff against), and Observer had zero
real support for C at all.

## GnuCOBOL for golden-master testing

Added `gnucobol4` to the Dockerfile — a real `cobc` compiler/runtime, so a COBOL source estate's
original code can actually be compiled and run to produce reference output, needed to prove
translated output is behaviourally equivalent via differential testing rather than judged by code
review alone.

While verifying this in a real container build, reproduced two other already-diagnosed-but-never-
merged bugs and fixed them too, since a container with 32 known-failing internal tests wasn't a
credible base for the validation work to come:

- **BUG-6 (#55)** — `examples/` was never `COPY`'d into the image, only ever mounted as a volume
  at `docker run` time. A plain `docker run micro-cosmos pytest` failed ~30 tests with
  FileNotFoundError-shaped errors (Databricks, NATS, CQRS seam detection) that look like real
  regressions but are actually just an absent fixture tree. Live pipeline runs never surfaced this
  because they mount `examples/` in as a volume, which papers over the missing `COPY` at build
  time.
- **BUG-3 (#52), Dockerfile-only pieces** — the .NET SDK install only bundles its own "LTS"
  runtime (.NET 10 as of this writing), but `coder_tools.py`'s C# scaffold hardcodes
  `<TargetFramework>net8.0</TargetFramework>` — every C# test execution failed outright with "You
  must install or update .NET to run this application" until the `net8.0` runtime was installed
  explicitly alongside the SDK's own bundle. Maven was also installed ahead of future real Java
  test execution.

Deliberately **not** included at this point: BUG-3's `sandboxrunner` user / privilege-dropping
pieces. Those support a sandboxed real-test-execution feature (`fitness_runner.py`'s
`_sandbox_preexec`, "the Test Agent") that wasn't on `main` at all yet — adding the user then
would have referenced Python code that didn't exist. See [[test-agent-sandboxed-execution]] for
where that landed 4 days later.

Confirmed live: full suite went from 32 failed / 199 passed in a freshly built container
(reproducing BUG-6 exactly) to 1 failed / 230 passed — the one remaining failure is the
pre-existing, separately-tracked container-vs-host ADF/Databricks discrepancy (#55).

## Real C source support

`.c`/`.h` files were discovered by extension but never structurally parsed — no entry in
`_CALL_EXTRACTORS` or `_DEEP_PARSERS`, so a C estate got none of the class/paragraph/call-graph
extraction every other supported language gets.

Added `_parse_c_ts_file` (tree-sitter deep parser, following the exact Java/C# pattern — struct
definitions → `DATA_STRUCTURE`, functions → `PROCEDURE`, fields → `DATA_ITEM`) and
`_extract_calls_c` (local `#include` → cross-file dependency edges, system includes excluded).
Unlike the Java tree-sitter parser (which only builds `DEFINES` structure), this also extracts
real intra-file function-to-function `CALLS` edges — C's flat, non-overloaded function namespace
makes resolving a call target by name unambiguous, and seam/hotspot detection needs a real call
graph to be meaningful.

`tree-sitter` and `tree-sitter-c` are now real, declared dependencies in `pyproject.toml` rather
than something that merely happened to work in an ad-hoc local dev environment — confirmed live
that `_TS_AVAILABLE` and `_CS_TS_AVAILABLE` (Java/C#'s own tree-sitter parsers) are **both
`False`** in the actual container today, meaning those richer parsers have likely never actually
run in production. Declaring the C dependency properly here; Java/C#'s pre-existing gap is a
separate, unfixed issue — flagged, not addressed, by this change.

### Two real bugs, both invisible until "c" existed as a source language to exercise them

1. `_extensions_for` did fuzzy-only prefix matching with no exact-match check first (unlike
   `_call_extractor_for`/`_deep_parser_for`, which already have one). `"cobol".startswith("c")` is
   `True`, and cobol is registered earlier in the dict, so `source_lang="c"` silently resolved to
   COBOL's extensions instead of its own. Fixed by checking for an exact key match before falling
   into the fuzzy-matching loop.
2. `.c`/`.h` pairs sharing a base name (`account.c` + `account.h` — the near-universal C
   convention) collided into two `PROGRAM` nodes with the identical generated id
   (`"prog.Account"` twice), making any edge touching either file ambiguous about which one it
   meant. Fixed with a distinct `_h` suffix for headers, applied consistently in both
   `parse_source_estate`'s file-node creation and `_extract_calls_c`'s include-edge target
   resolution.

## Verification

Real container build: `tree-sitter-c` installs and `_C_TS_AVAILABLE` is `True`; full suite 242
passed / 1 pre-existing unrelated failure / 1 skipped (up from 230 passed before this change, 12
new tests in `tests/test_c_parser.py`, zero regressions).

## Follow-on documentation gaps this surfaced (fixed same week)

`docs/one-pager.md`, `docs/security-brief.md`, and `CLAUDE.md`'s own "What this project does"
line all still said "Java, Kotlin, Python, C#, or Go" as the source-language set — stale even
before this change (Kotlin/Go have never had a source parser) and now also missing COBOL, PHP,
and C entirely. Corrected to "Java, Python, C#, COBOL, PHP, or C (Kotlin/Go target-only)" wherever
found — see the "Fix: source-language list wrong" entry in `changes-log.md`. `demo.html`'s
source-language `<datalist>` had the same gap in reverse (C parsing existed but wasn't offered as
a selectable option) — fixed separately; `go`/`kotlin` are still listed there as source options
despite having no real parser, flagged but not fixed.

## Files changed

| File | Change |
|---|---|
| `Dockerfile` | `gnucobol4`, Maven, .NET 8 runtime, `COPY examples` |
| `micro_cosmos/tools/observer_tools.py` | `_parse_c_ts_file`, `_extract_calls_c`, `_extensions_for` exact-match fix, `.c`/`.h` id-collision fix |
| `pyproject.toml` | Declared `tree-sitter`, `tree-sitter-c` dependencies |
| `tests/test_c_parser.py` | New — 12 tests |
