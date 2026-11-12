---
name: cqrs-message-flow-seams
description: Seam detection was blind to message-bus coupling, so an event-sourced Axon estate scored lowest per LOC of three Java apps; fixed with a decoupled message-flow registry, saga parsing, and a role-based effort tier (2026-08-19)
metadata:
  type: project
---

Joao compared three Java runs (`8ab0f6b1` Fraud, `807c0972` SpringBoot, `d92e257b` Axon) and said the
Axon estate — SpringBoot *plus* Axon — was scoring far too low. Full writeup:
`docs/bug-2-seam-estimation-blind-to-CQRS-event-driven-coupling.MD`.

## Qualify the expectation before acting on it

"Axon should have more points than SpringBoot" is not automatically true — Axon is genuinely half the
code (1,807 vs 2,607 LOC). Taking the report at face value would have meant tuning numbers until the
ranking looked right, which is fitting to a preference rather than fixing a defect.

**Normalising is what turned an opinion into a provable bug.** At 2.32 pts/100 LOC the Axon estate was
rated the *easiest to migrate per line of code* of the three, despite having the most Maven modules
(9) and the most bounded contexts (12). That inversion is indefensible on any reading, and it also
gave a falsifiable success criterion: not "Axon must beat Fraud", but "Axon must stop being lowest
per LOC". It ended at 6.09 vs SpringBoot's 4.83. Pick the metric that makes the claim testable before
touching code.

## The recurring architectural lesson: coupling declared outside the call graph

Third instance of this exact class in this codebase:

| Mechanism | Where the coupling is declared | Invisible to |
|---|---|---|
| Databricks Asset Bundle | `depends_on` in job YAML | CALLS-based seam detection |
| Azure Data Factory | `dependsOn` in pipeline JSON | CALLS-based seam detection |
| **Axon / CQRS** | **`@CommandHandler`/`@EventHandler` + the message bus** | **CALLS-based seam detection** |

Measured on the Axon estate: 11 `CALLS` edges across 251 nodes and 9 modules — 0.39 per file, vs 2.17
for the CRUD estate. All 8 seams it produced were read repositories, Spring config and directory
links. Zero aggregates, handlers or sagas. **The signal was already in the IR** (20 Axon-annotated
nodes) and seam detection simply never looked at it (`grep -c "axon\|cqrs\|handler_type" seam_tools.py`
→ 0). When a whole estate class scores near zero, suspect the detector's *shape assumption* before
suspecting the estate is simple.

**Generalise:** any framework where components are wired by a broker, scheduler or annotation rather
than a direct call needs its own seam pass. There is no CALLS edge to find, and no amount of
threshold tuning will conjure one.

## Decoupling was an explicit requirement, and it is the BUG-1 lesson applied

Joao's caveat: *"CQRS event driven is coupled, I want it to be de-coupled and only used if
necessary."* Directly informed by [[adf-scheduler-non-dict-json-crash]], where an unconditional ADF
detector crashed a plain Java run.

Implemented as `micro_cosmos/tools/message_flow_tools.py` — a registry of `(detect_fn, parse_fn)` pairs
mirroring `scheduler_tools.py`'s `_SCHEDULERS`, each gated on its own detector, returning
`{"aggregates": [], "sagas": [], "flows": []}` when nothing matches so the seam pass loops over
nothing. Adding Kafka/MediatR/NServiceBus later touches only that registry, never `seam_tools.py`.

**Prove decoupling empirically, don't assert it.** 10 of 11 estates byte-identical in the sweep, and
both non-CQRS live runs produced `message: 0` with empty hints. That evidence *is* the deliverable
for a "make it decoupled" requirement.

## Three traps specific to this codebase, all real

1. **`_work_for_seam()`'s final `else` is an unguarded catch-all.** Any new seam type without an
   explicit branch is silently scored as a config/Settings seam — flat S/6pts, titled "Extract … into
   a typed Settings interface", with `os.environ` steps. A new branch is mandatory, not cosmetic.
   Guarded now by an explicit "does not fall through" test.
2. **`seam_counts` / `work_summary.by_type` are built from three hardcoded 4-type tuples.** A new type
   counts toward `total` but vanishes from every breakdown unless all three are extended.
3. **`dashboard.js` uses `byType[s.type]?.push(s)`.** Optional chaining means an unregistered type is
   *silently dropped* from the UI — no error, just missing data. Always verify a new type renders
   live rather than trusting the absence of a crash.

## A regression test that passes both ways proves nothing

Carried over from BUG-1: every new test was run against the unfixed code first. One —
`test_message_seam_effort_by_role[intra-context-S-6-low]` — *passed* pre-fix, because the
preprocessing fallback coincidentally also returns S/6/low. Had that been the only assertion, the
suite would have looked green while the fallback bug stayed wide open. The separate "must not fall
through to the config branch" assertion is what actually failed pre-fix and is the one carrying the
weight.

## Sagas were invisible, and sagas are the expensive part

`@Saga`/`@SagaEventHandler`/`@StartSaga`/`@EndSaga` were missing from `_AXON_ANNOTATION_NAMES`, so
`AllocationSaga.java` produced no IR signal at all — the single highest-effort construct in an
event-sourced migration (persisted workflow state, timeouts, compensation) was contributing zero.
Added through the existing `_axon_annotations()` import gate so a same-named non-Axon annotation
still cannot false-positive (the hardening from [[cqrs-framework-detection]]).

Effort is scored by **role, not fan-in** — an aggregate with one handler is still hard: saga L/16,
aggregate M/10, cross-context flow M/10, intra-context flow S/6. Fan-in is meaningless here; there
are no callers by construction.

## Deterministic-mode hook gap, again

`cqrs_framework_hints` was never written when `skip_llm=true`: `run_phase()`'s branch returns before
the post-phase hooks. Byte-for-byte the same gap already fixed once for the Trivy prescan. **When
adding any post-OBSERVER enrichment, check both paths** — this is now the second occurrence, so treat
it as a standing checklist item rather than a one-off.

Related: [[databricks-bundle-task-graph-seams]], [[scheduler-registry-adf-support]],
[[cqrs-framework-detection]], [[adf-scheduler-non-dict-json-crash]], [[effort-estimates-doubled]].

## Follow-up (2026-08-19): the registry proved itself, and silent gaps became visible

### A detector that can name what it cannot parse must say so

`detect_cqrs_frameworks()` recognises six frameworks from manifest coordinates, but only Axon had a
flow parser. An estate using MediatR therefore got **zero message seams and no indication anything
was missing** — an understated estimate that reads exactly like a correct one. That silence was the
real defect, not the missing parser.

Fixed by comparing what detection names against what the registry can parse
(`unparsed_frameworks()`), then surfacing the difference as a log warning **and** a `coverage_notes`
key in `seam.json`. **Generalise: whenever a detection tier and a parsing tier can disagree, compute
the difference and report it.** A capability gap the user can see is a feature; the same gap
invisible is a bug.

### The extension point paid off — second parser, zero changes to the consumer

Adding NATS/JetStream + Azure Event Hubs required **one tuple in `_MESSAGE_FLOWS`** and no change to
`seam_tools.py` at all. That is the return on building the registry rather than an if/elif — the same
payoff `scheduler_tools.py` got when ADF followed DAB. When a second instance of a category is even
plausible, the registry costs ~15 lines and removes the consumer from the blast radius entirely.

### Gate at the level the guarantee actually lives at

The NATS parser first gated per-file on an `io.nats` import and found **1 seam instead of 6**. The
producer side is a thin wrapper: `UliEventBridge.java` holds the literal subject strings but imports
only `UliPublisher`, which is the class that imports `io.nats`. So a per-file import check finds every
consumer and misses every publisher.

The decoupling guarantee belongs at **estate** level (`detect_nats_flows`), not per file. Inside an
estate already known to use NATS, a dot-delimited subject literal passed to
`publish`/`subscribe`/`filterSubject` is real evidence. Over-tight gating looks safe and silently
loses data — and it fails in the direction that produces a *plausible* wrong answer rather than an
obvious one.

### Fixture inventory before planning, not after

Seven technologies (Kafka, MediatR, NServiceBus, Wolverine, Eventuate, Lagom, Spring
`@EventListener`) have **zero** occurrences in this repo — verified, not assumed: no `build.gradle`
exists at all, and both `.csproj` files are a .NET 4.0 MVC3 app. Running that inventory first turned
"write five parsers" into "write one real parser and make five gaps visible", which is both smaller
and more honest. Writing synthetic fixtures would have encoded my own guess at each framework's shape
and then passed tests against that guess.

### Watch the direction of an over-correction

The Axon estate went from *lowest* pts/100 LOC (2.32 — the original bug) to *highest* (11.40). The
direction is defensible, but 6 external-integration seams × 16pts is nearly half the estate's total,
and five of them are concrete subjects all consumed by one wildcard subscriber. That was flagged in
the doc as the first thing to re-tune rather than quietly accepted because the number now looks
better. **A fix that overshoots is still a fix that is wrong** — say so while the evidence is fresh.

## PR #45 review (2026-08-20): I over-corrected a gate, and it cost precision

Samuel Mbah found two defects in the NATS parser. Both reproduced. Both were mine, and the first is
the instructive one.

**Relaxing a gate is not free — it trades one error direction for the other.** The follow-up section
above records, approvingly, moving the NATS gate from per-file to estate level because a per-file
`io.nats` import check missed the thin-wrapper producer. That reasoning was sound but the
implementation went to the opposite extreme: with *no* per-file check, any
`subscribe`/`publish`/`filterSubject` call with a dotted string literal counted. An unrelated MQTT
client in a NATS-using estate was scored as a full external-integration seam at L/16 with NATS
migration guidance attached.

The fix was neither extreme but a **two-pass approach**: establish the estate's real subject
namespaces from files that genuinely import the technology (plus its declared topology), then accept
subjects from other files only inside those namespaces. **When you catch yourself removing a check
because it produces false negatives, ask what false positives you are buying** — and look for the
evidence-based middle rather than flipping the switch.

**A regression test must pin both directions of a fix.** `test_thin_wrapper_producer_is_still_detected`
exists specifically so that fixing the false positive cannot silently reintroduce the false negative
that motivated the original relaxation. Whenever a fix moves a threshold, test the behaviour on *both*
sides of it, not just the one you were asked about.

**Approximate matching invents couplings.** `_root()` compared the first two dot-segments as a cheap
stand-in for NATS wildcard matching, which paired `uli.events.portfolio.Created` with an unrelated
`uli.events.billing.>` subscriber. If a domain has real matching semantics (NATS `*`/`>`, glob, CIDR,
semver), implement them — a prefix heuristic silently fabricates relationships that look plausible.

**Latent bugs need synthetic reproduction.** The 11-estate sweep was byte-identical before and after
this fix: both defects need a second messaging technology or a sibling subtree, and no fixture has
either. Real bugs, invisible to every existing regression check. A fix that changes no output on any
real fixture is not evidence the bug was imaginary — it is evidence the fixture set is thin.

**The failure shape matters more than the severity.** Samuel's framing: neither defect crashed
anything, so both produced *a confident wrong number rather than an obviously broken one*. For
anything feeding an estimate, silent plausible wrongness outranks loud breakage on the priority list.
