# Bug 2 — Seam estimation is blind to CQRS / event-driven coupling

**Reported by:** Joao Cerqueira, 2026-08-19 — "the complexity is not reflected in the results as expected… taking into account springboot and extra axonframework, the latter axonframework should have more story points."
**Runs analysed:** `8ab0f6b1` (Fraud Banking), `807c0972` (SpringBoot-Legacy), `d92e257b` (AxonFramework) — all `java → kotlin`, Deterministic, Auto-approve ON
**Verdict:** ✅ **Real bug, and a significant one.** Not cosmetic. Same bug *class* as the already-fixed Databricks scheduler-seam gap.
**Status:** ✅ **RESOLVED** (§9), and the four deferred items from §9.8 subsequently closed or converted to visible gaps (§10).

---

## 1. The reported symptom

Three Java estates, ranked by the story points the pipeline produced:

| Run | App | Story points | Seams |
|---|---|---:|---:|
| `8ab0f6b1` | Fraud Banking | **328** | 53 |
| `807c0972` | SpringBoot-Legacy | **126** | 23 |
| `d92e257b` | AxonFramework | **42** | 8 |

The AxonFramework app is a distributed CQRS/event-sourced system — SpringBoot **plus** Axon on top — yet it scores the lowest of the three, by a wide margin.

## 2. Is the expectation actually justified? Partly — and the honest answer matters

By raw size the Axon app genuinely *is* the smallest, so some gap is legitimate:

| App | `.java` files | LOC | Maven modules | Bounded contexts |
|---|---:|---:|---:|---:|
| Fraud Banking | 66 | 4,782 | 1 | 11 |
| SpringBoot-Legacy | 54 | 2,607 | 8 | 9 |
| AxonFramework | 28 | 1,807 | **9** | **12** |

So "Axon should have more points than SpringBoot in absolute terms" is not automatically true — it has roughly half the code.

**But normalising by size proves the estimator is still wrong**, because the Axon app scores *lowest per unit of code* despite being the most architecturally distributed of the three:

| App | pts / 100 LOC | pts / file | Modules | Contexts |
|---|---:|---:|---:|---:|
| Fraud Banking | **6.86** | 4.97 | 1 | 11 |
| SpringBoot-Legacy | **4.83** | 2.33 | 8 | 9 |
| AxonFramework | **2.32** | 1.50 | 9 | 12 |

The app with the **most** modules (9) and the **most** bounded contexts (12) — a genuinely distributed, event-sourced, multi-service estate — is rated the *easiest to migrate per line of code*, less than a third of a single-module CRUD app. That ranking is indefensible, and it is what makes this a bug rather than a tuning preference.

## 3. Root cause — seam detection only understands direct method calls

`_detect_seams()` (`micro_cosmos/tools/seam_tools.py`) finds seams three ways:

1. Fan-in on `CALLS` edges (a node called by ≥ N callers is a substitution point)
2. `CALLS` edges that cross a bounded-context boundary
3. ETL scheduler task graphs (`discover_task_graph()` — DAB / ADF `depends_on`)

**All three are blind to a message bus.** In an Axon application, an aggregate does not call a projection — it emits an event, the event bus routes it, and a `@EventHandler` elsewhere reacts. There is no source-level `CALLS` edge between them. The coupling is real, architecturally central, and invisible.

The measured collapse in call-graph density is stark:

| App | `CALLS` edges | CALLS / file | cross-context calls |
|---|---:|---:|---:|
| Fraud Banking | 143 | 2.17 | 21 |
| SpringBoot-Legacy | 51 | 0.94 | 12 |
| AxonFramework | **11** | **0.39** | **4** |

Eleven call edges across 251 IR nodes and 9 modules. The estimator has almost nothing to measure, so it returns almost nothing — not because the app is simple, but because its coupling doesn't take the shape the estimator looks for.

### The signal exists in the IR and is discarded

This is the crux. Observer **already parses and stores** the Axon annotations (restored/hardened by the CQRS-detection work — see `transferable-skills/memory/cqrs-framework-detection.md`). In `runs/d92e257b/ir_graph.json`, 20 nodes carry Axon attributes:

| `handler_type` | Count |
|---|---:|
| `event` | 10 |
| `command` | 5 |
| `event-sourcing` | 4 |
| (`is_axon_aggregate`) | 1 |

And in the source itself: 10 `@EventHandler`, 5 `@CommandHandler`, 4 `@EventSourcingHandler`, 4 `@Saga`, 2 `@Aggregate`, 2 `@ProcessingGroup`.

Seam detection references **none** of it:
```
$ grep -cin "axon|cqrs|handler_type" micro_cosmos/tools/seam_tools.py       → 0
$ grep -cin "axon|cqrs|handler_type" micro_cosmos/tools/cartographer_tools.py → 0
```

### Proof in the output: the 8 seams are all trivia

The complete seam list for the Axon run:

| Type | Location | Effort |
|---|---|---|
| object | `prog.PortfolioReadRepository` | XS · 4pts |
| object | `prog.PropertyReadEntity` | XS · 4pts |
| object | `prog.PropertyReadRepository` | XS · 4pts |
| preprocessing | `prog.AppConfig` | S · 6pts |
| preprocessing | `prog.BffConfig` | S · 6pts |
| link | `BackendCore ↔ PropertyAllocation` | S · 6pts |
| link | `CommonDomain ↔ PropertyAllocation` | S · 6pts |
| link | `BackendCore ↔ UserAuth` | S · 6pts |

Three read-side repositories/entities, two Spring config classes, three context links. **Zero aggregates. Zero command handlers. Zero event handlers. Zero sagas.** Every genuinely hard part of migrating an event-sourced system — rebuilding aggregates, preserving event schemas and ordering, re-implementing sagas, maintaining projection consistency — contributes exactly nothing to the estimate.

## 4. This is a known bug class in this codebase

`transferable-skills/memory/databricks-bundle-task-graph-seams.md` records the identical failure for Databricks:

> "A DAB job's tasks are chained by the *scheduler* (`depends_on` in the YAML) — `notebook_task` and `python_wheel_task` share no actual function call in the source code at all, so neither mechanism had anything to find."

That was fixed by adding a scheduler-driven seam pass that reads the estate's own declared task graph instead of inferring from code. **An Axon event bus is the same situation with a different declaration mechanism** — the coupling is declared in annotations and message types rather than YAML, but it is equally explicit and equally invisible to `CALLS`-based detection. The fix shape is already established.

## 5. Secondary bug found while investigating — `cqrs_framework_hints` never populated in Deterministic mode

`runs/d92e257b/ir_graph.json` has **no `cqrs_framework_hints` key at all** (verified: `"cqrs_framework_hints" in ir` → `False`; top-level keys are `dead_code`, `documentation_bundle`, `edges`, `nodes`, `performance_findings`, `source_excerpts`, `source_lang`, `source_snapshot_sha`, `warnings`).

Cause: in `micro_cosmos/orchestration/pipeline.py::run_phase()`, the `skip_llm` branch begins at **line 527** and `return`s at **line 604**. The post-OBSERVER CQRS detection hook lives at **line ~790**, inside the "Post-phase hooks" section that starts at **line 748** — unreachable in Deterministic mode.

This is precisely the bug already documented and fixed for the source-side Trivy scan in `transferable-skills/memory/deterministic-mode-trivy-scan.md` ("`run_phase()`'s `skip_llm` branch always returned before the Trivy prescan hook was reached"). The Trivy hook was moved inside the branch; the CQRS hook — added later, 2026-08-13 — has the identical gap and was never given the same treatment.

Impact is currently limited but real: the only consumer today is the Architect LLM prompt (`{ir_graph.cqrs_framework_hints.detected_frameworks?}`), so in Deterministic mode the Architect is told nothing about a detected CQRS framework. If the primary fix above starts consuming `cqrs_framework_hints` for seam detection, **this gap must be closed first or the fix silently no-ops in Deterministic mode.**

## 6. Severity

**Big bug in impact, contained in fix location.**

- *Impact:* systematically under-estimates every event-driven/message-bus architecture — Axon, Kafka/NATS choreography, MediatR, NServiceBus, Wolverine, Eventuate, Lagom (five of these are already recognised by `framework_tools.py::detect_cqrs_frameworks()`, so the estate types are expected, not hypothetical). Estimates feed the sprint plan, Jira export and effort reporting, so this directly misleads migration planning — and it *inverts* the ranking, which is worse than being uniformly low.
- *Fix location:* one new pass in `_detect_seams()` (`seam_tools.py`), structurally mirroring the existing scheduler pass, plus closing the Deterministic-mode gap in `pipeline.py`. No new phase, no schema change, no agent changes.

## 7. Suggested fix direction (not yet implemented, not yet approved)

1. **Close the Deterministic-mode gap first** — move/duplicate the post-OBSERVER `cqrs_framework_hints` hook inside `run_phase()`'s `skip_llm` branch, exactly as was done for `_run_trivy_prescan()`. Without this, anything downstream that consumes the hints is dead code in Deterministic mode.
2. **Add a CQRS/message-flow seam pass to `_detect_seams()`** — mirroring the existing scheduler pass in both shape and rationale. Candidate seam sources, all already present in the IR: each `@Aggregate` (a command-side consistency boundary), each `@Saga` (a long-running cross-context process — arguably the highest-effort seam type in an event-sourced migration), and each command/event handler pair that crosses a bounded-context boundary (the real integration contract). A message type produced in context A and handled in context B is a genuine `link` seam and should be scored as one.
3. **Revisit `_work_for_seam()` effort tiers for these new seam types.** Fan-in is a poor proxy for event-sourcing migration effort — an aggregate with one caller can still be the hardest thing in the estate. Needs an explicit, deliberate tier rather than reusing the call-graph tiers.
4. **Re-validate the ranking afterwards** using the same three runs. Success criterion is not "Axon beats Fraud in absolute points" (Axon is genuinely half the code) but "Axon's pts/100 LOC is no longer the lowest of the three", which is the specific result that is currently indefensible.

## 8. Verification data (reproducible)

All figures above came from reading the committed run artifacts directly:

```bash
# per-run metrics
python3 -c "import json;s=json.load(open('runs/d92e257b/seam.json'));print(len(s['seams']),(s.get('work_summary') or {}).get('total_story_points'))"

# CALLS-edge density
python3 -c "import json;ir=json.load(open('runs/d92e257b/ir_graph.json'));print(sum(1 for e in ir['edges'] if (e.get('kind') or e.get('type'))=='CALLS'))"

# Axon signal present in IR but unused
python3 -c "import json,collections;ir=json.load(open('runs/d92e257b/ir_graph.json'));c=collections.Counter((n.get('attributes') or {}).get('handler_type') for n in ir['nodes'] if (n.get('attributes') or {}).get('handler_type'));print(dict(c))"

# seam detection has no CQRS awareness
grep -cin "axon\|cqrs\|handler_type" micro_cosmos/tools/seam_tools.py
```

No code was changed and no runs were created or deleted during this investigation.

---

## 9. RESULTS — implementation & verification (2026-08-19)

Branch `bug/bug-2-seam-estimation-blind-to-CQRS-event-driven-coupling`. Every number measured, not estimated.

### 9.1 Design constraint honoured — decoupled, activated only when needed

The explicit requirement was that CQRS support must be **decoupled and only used if necessary** — the
direct lesson from BUG-1, where an unconditional ADF detector crashed an unrelated Java run.

Implemented as a registry in a new module, mirroring `scheduler_tools.py`'s `_SCHEDULERS` exactly:
`_MESSAGE_FLOWS = ((detect_fn, parse_fn), ...)`, each pair individually gated on its own `detect_fn`.
`discover_message_flows()` returns `{"aggregates": [], "sagas": [], "flows": []}` whenever nothing is
detected, so the seam pass's loops are empty and a non-CQRS estate is untouched. Adding Kafka /
NServiceBus / MediatR later means appending one tuple — `seam_tools.py` does not change.

**Proven empirically, not asserted:** 10 of 11 estates byte-identical (§9.4), and both non-CQRS live
runs produced `message: 0` seams with an empty `cqrs_framework_hints` (§9.5).

### 9.2 Changes

| # | File | Change |
|---|---|---|
| A1 | `micro_cosmos/tools/message_flow_tools.py` *(new)* | Decoupled registry; correlates handlers by `handles_payload`; defensive `_nodes()`/`_attrs()` guards so a malformed IR degrades to "no message seams" and never raises |
| A2 | `micro_cosmos/tools/observer_tools.py` | Recognise `@Saga`/`@SagaEventHandler`/`@StartSaga`/`@EndSaga` (new `is_axon_saga` attribute, `saga-event` handler type) through the existing import-resolution gate, so a same-named non-Axon annotation still can't false-positive |
| A3 | `micro_cosmos/tools/seam_tools.py` | New gated `message` seam pass; explicit `elif stype == "message"` branch in `_work_for_seam()`; all three hardcoded 4-type tuples extended |
| A4 | `micro_cosmos/orchestration/pipeline.py` | CQRS hook added inside the `skip_llm` branch, before seam production — closes the Deterministic-mode gap |
| A5 | `dashboard.js`, `generate_exec_summary.js`, `generate_synthesis.js` | Surface the new `message` type (colour, pill, `byType` bucket, report rows) |

**Why A3's `_work_for_seam` branch was mandatory, not cosmetic:** the function's final `else` is an
unguarded catch-all. Without an explicit branch, every message seam would silently be scored as a
*config/Settings* seam — flat S/6pts, titled "Extract … into a typed Settings interface", with
`os.environ` migration steps. A dedicated test (`test_message_seam_does_not_fall_through_to_preprocessing_default`)
now pins this shut.

Effort model — scored by **role**, not fan-in, because an event-sourced aggregate with a single
handler is still among the hardest things in an estate to migrate:

| Role | Effort | Points | Risk |
|---|---|---:|---|
| saga / process manager | L | 16 | high |
| event-sourced aggregate | M | 10 | high |
| cross-context message flow | M | 10 | medium |
| intra-context message flow | S | 6 | low |

### 9.3 Tests

| Stage | Result |
|---|---|
| Baseline before any change | **161 passed, 1 skipped, 0 failed** |
| New tests vs **unfixed** code | **7 failed + 1 hard ImportError** (`test_cqrs_seams.py` cannot even import — it depends entirely on new code) |
| Full suite after fixes | **187 passed, 1 skipped, 0 failed** |
| Net | **+26 tests, zero regressions** |

Honest note on the pre-fix check: `test_message_seam_effort_by_role[intra-context-S-6-low]` *passed*
against the unfixed code, because the preprocessing fallback coincidentally also returns S/6/low.
That is precisely why the separate "does not fall through to the config branch" assertion exists —
and that one did fail pre-fix. A test that passes both ways proves nothing.

New coverage: `tests/test_cqrs_seams.py` (aggregate/saga/flow seams, story-point propagation,
**non-CQRS estates unchanged**, 9 malformed-IR shapes that must never raise), plus additions to
`test_seam_effort.py` (role tiers + fallback guard), `test_java_axon.py` (saga parsing + non-Axon
false-positive guard) and `test_cqrs_framework_detection.py` (Deterministic-mode hint).

### 9.4 Retrofit regression sweep — 11 estates, before vs after

Driven through the real `initialise_session()` → `run_phase()` OBSERVER → CARTOGRAPHER → ARCHITECT
path. Compared IR nodes/edges, contexts, seam count + types + points, streams, TNAS services and
artifact list.

| Estate | Lang | Verdict |
|---|---|---|
| `java-axonframework-example-app` | java | ✅ **FIXED** — seams 8→15, points 42→110, `message` 0→7, IR edges 247→250 (the 3 new saga handler edges) |
| `java-bankxyz_fraud_detection` | java | ✅ identical |
| `java-springboot-legacy-app` | java | ✅ identical |
| `cobol-bankxyz_fraud_detection` | cobol | ✅ identical |
| `cobol-mainframe-banking-teller` | cobol | ✅ identical |
| `csharp-bankxyz_fraud_detection` | csharp | ✅ identical |
| `fraud_detection` | python | ✅ identical |
| `legacy_estate` | cobol | ✅ identical |
| `databricks_bundle_default_python` | pyspark | ✅ identical (hard `total == 2` test still green) |
| `databricks_adf_notebooks_project` | pyspark | ✅ identical |
| `databricks_adf_project1_profile` | pyspark | ✅ identical |

**Exactly one row changed.** Ten byte-identical.

### 9.5 The reported symptom, resolved

| App | LOC | pts before | pts after | pts/100 LOC before | pts/100 LOC after |
|---|---:|---:|---:|---:|---:|
| Fraud Banking | 4,782 | 328 | 328 | 6.86 | 6.86 |
| SpringBoot-Legacy | 2,607 | 126 | 126 | **4.83** | 4.83 |
| AxonFramework | 1,807 | 42 | **110** | **2.32 (lowest)** | **6.09** |

The agreed success criterion was **not** "Axon beats Fraud in absolute points" — Axon is genuinely
half the code. It was that Axon must no longer be rated the *easiest to migrate per line of code*.
It now sits at 6.09, above SpringBoot's 4.83, which matches the architectural reality of a
9-module, 12-bounded-context, event-sourced estate.

Seams the Axon estate now produces that it previously did not:

| Role | Seam | Effort |
|---|---|---|
| aggregate | `class.Portfolio` | M · 10pts |
| saga | `class.AllocationSaga` | L · 16pts |
| cross-context | `PropertyAddedToPortfolio → AllocationSaga, Portfolio, …` | M · 10pts |
| cross-context | `PropertyAllocatedToBroker → …` | M · 10pts |
| cross-context | `ValuationSubmitted → …` | M · 10pts |
| intra-context | `PortfolioCreated → …` | S · 6pts |
| intra-context | `PortfolioClosed → …` | S · 6pts |

Cross-context vs intra-context is correctly differentiated only when a bounded-context map is
supplied — the live pipeline does; `identify_seams()` does not and reports all flows as
intra-context. That asymmetry is pre-existing (`identify_seams` has never passed `bcm`) and is
documented rather than changed.

### 9.6 Live docker-compose verification

Image rebuilt (`docker compose up -d --build`); all four changes confirmed present in the running
container by grep before testing.

| Run | Estate | Gates | Seams / pts | `message` | `cqrs_framework_hints` |
|---|---|---|---|---:|---|
| `bab2b625` | Axon | **6/6 APPROVED** | 15 / 110 | 7 | `["AxonFramework"]` |
| `31cc6bcd` | SpringBoot | **6/6 APPROVED** | 23 / 126 | **0** | `[]` |
| `054a4eba` | Fraud | **6/6 APPROVED** | 53 / 328 | **0** | `[]` |

Zero `AttributeError`, zero `Top-level pipeline failure`, zero `post-observer seam production failed`,
zero `post-observer CQRS framework detection failed` across all three runs.

Rendering verified live, not assumed: the Axon run's `executive-summary.html` reports
`Message seams … 7`, `project-synthesis.html` carries the row, and the served `dashboard.js` contains
the new palette entries — important because `byType[s.type]?.push(s)` uses optional chaining, so an
unregistered type would have been *silently dropped* from the UI rather than erroring.

Throwaway runs deleted after container CPU was confirmed idle. `8ab0f6b1`, `807c0972`, `d92e257b`,
`25640f7f` and `e1acbc0c` left untouched.

### 9.7 New issues found during this work

| Issue | Action |
|---|---|
| `_work_for_seam`'s final `else` is an unguarded catch-all that mislabels any unrecognised seam type as a config seam | **Mitigated** for `message` with an explicit branch + regression test. The underlying catch-all remains for any *future* new type — noted below. |
| `identify_seams()` never passes `bcm`, so direct callers (and three existing test files) can't distinguish cross- from intra-context flows | **Documented, not changed** — pre-existing, and changing the public signature is out of scope. |
| A first live-verification attempt hung when three runs were started from a shell function | Not an app defect — `POST /runs` returns in ~1-10s when invoked directly. Re-run individually with `--max-time`. |

### 9.8 Unresolved / deliberately deferred

1. **Only Axon is registered.** MediatR, NServiceBus, Wolverine, Eventuate and Lagom are recognised by
   `detect_cqrs_frameworks()` but have no flow parser, so they still produce no message seams. The
   registry exists precisely so each can be added independently; none has a fixture in this repo, and
   inventing detection heuristics without one would be unverifiable (the explicit lesson from
   `cqrs-framework-detection.md`).
2. **Kafka/NATS/plain-Spring-events choreography** is not covered — same reason.
3. **`_work_for_seam`'s catch-all `else`** should arguably raise or warn on an unknown type rather than
   silently applying preprocessing semantics. Left alone as a behavioural change beyond this fix.
4. **`@ProcessingGroup` is still not captured** — it affects event-processor grouping and could refine
   intra/cross-context classification, but it is not required for seam identification.
5. **Query-side (`@QueryHandler`) flows** are collected but rarely produce multi-owner payloads in this
   fixture, so they seldom surface as seams. Untested against a real CQRS read-model-heavy estate.

---

## 10. FOLLOW-UP — the four deferred items from §9.8 (2026-08-19)

### 10.1 Fixture inventory decided the scope

A read-only inventory across the whole repo was run **before** planning, because the standing rule in
`cqrs-framework-detection.md` is that inventing detection heuristics for a framework with no fixture
is unverifiable. The evidence reshaped what was honestly achievable:

| Technology | Fixture in repo? | Evidence |
|---|---|---|
| NATS / JetStream | ✅ **Real** | `io.nats:jnats:2.17.3` in `05-uli-nats/bridge/eventhub-bridge/pom.xml`; real pull-subscribe on `uli.events.>`; `streams.yaml` declaring 3 streams + 3 durable consumers |
| Azure Event Hubs | ✅ **Real** | `com.azure:azure-messaging-eventhubs:5.18.4`, same module |
| `@ProcessingGroup` | ✅ **Real** | 2 occurrences: `PortfolioProjection`, `UliEventBridge` |
| Kafka | ❌ Zero | no `org.apache.kafka`/`@KafkaListener`/`spring-kafka` anywhere |
| MediatR / NServiceBus / Wolverine | ❌ Zero | both `.csproj` files are a .NET 4.0 MVC3 app; no package references |
| Eventuate / Lagom | ❌ Zero | no `build.gradle` exists at all; none of the 12 `pom.xml` files match |
| Spring `@EventListener` | ❌ Zero | no occurrences in any Java example |

So NATS/Event Hubs and `@ProcessingGroup` were built for real; the seven with no fixture were **not**
given speculative parsers — writing synthetic fixtures would only encode an assumption of what those
frameworks look like and then pass tests against that invention.

### 10.2 What changed

| # | Item | Resolution |
|---|---|---|
| E1 | 5 frameworks detected but unparsed | **Converted from silent to loud.** `unparsed_frameworks()` compares what detection names against what the registry can parse; the gap is logged as a warning and recorded in a new `coverage_notes` key in `seam.json` |
| E2 | Kafka/NATS uncovered | **NATS/JetStream + Azure Event Hubs parser built** against the real fixture; new `external-integration` role at L/16/high. Kafka has no fixture, so it joins E1 |
| E3 | `@ProcessingGroup` uncaptured | **Captured** as a `processing_group` node attribute, through the existing import-resolution gate |
| E4 | `_work_for_seam` catch-all | **Hardened** — explicit `preprocessing` check; an unrecognised type now warns and still degrades safely instead of being silently scored as a config seam |

**E2 is the real proof the BUG-2 registry design works:** adding a second, completely different
messaging technology required **zero changes to `seam_tools.py`** — one tuple in `_MESSAGE_FLOWS`.

One implementation detail worth recording: the NATS parser was initially gated on a per-file
`io.nats` import and found only 1 seam. The producer side is a thin wrapper — `UliEventBridge.java`
holds the literal subject strings but imports only `UliPublisher`, which is the class importing
`io.nats`. An import-per-file check therefore finds every consumer and misses every publisher. The
gate was moved to estate level (`detect_nats_flows`), which is where the decoupling guarantee
actually belongs; within an estate already known to use NATS, a dot-delimited subject literal passed
to `publish`/`subscribe`/`filterSubject` is real evidence. Seams went 1 → 6.

### 10.3 Tests

| Stage | Result |
|---|---|
| Baseline (post-BUG-2) | 187 passed, 1 skipped, 0 failed |
| New tests vs pre-follow-up code | **18 failed + `test_nats_seams.py` fails to import entirely** |
| After | **213 passed, 1 skipped, 0 failed** |
| Net | **+26 tests, zero regressions** |

New `tests/test_nats_seams.py` (subjects, producer/consumer pairing on subject, `streams.yaml`
durable consumers, L/16/high tier, non-NATS estates untouched, bad paths and malformed IR never
raise), plus additions to `test_cqrs_seams.py` (unparsed reporting, `coverage_notes` in the report,
no spurious note when fully covered), `test_java_axon.py` (processing group + non-Axon guard) and
`test_seam_effort.py` (external tier, unknown-type warning, preprocessing does *not* warn).

**One existing BUG-2 test was legitimately updated, not worked around:** adding the `"unparsed"` key
changed `discover_message_flows()`'s return shape, so the two shape assertions in
`test_cqrs_seams.py` were updated to match the new contract.

### 10.4 Retrofit sweep — 11 estates

**Exactly one row changed.** Ten byte-identical, including `databricks_bundle_default_python`'s hard
`total == 2`.

| Estate | Verdict |
|---|---|
| `java-axonframework-example-app` | ✅ **CHANGED** — seams 15→21, points 110→206, `message` 7→13 |
| All ten others | ✅ identical |

Notably **E3 caused no reclassification** of existing flows — intra/cross-context counts are
unchanged, and `ir_edges` is unchanged (`@ProcessingGroup` adds a class attribute, not an edge). The
entire delta is the 6 new `external-integration` seams.

### 10.5 Live verification

| Run | Estate | Gates | Seams / pts | roles | `coverage_notes` |
|---|---|---|---|---|---|
| `0b90dcf1` | Axon | **6/6** | 21 / 206 | aggregate 1, saga 1, intra 2, cross 3, **external 6** | `[]` |
| `e06b83a8` | SpringBoot (control) | **6/6** | 23 / 126 | none | `[]` |

Zero `AttributeError`, zero `Top-level pipeline failure`, zero `unrecognised seam type`. Rendering
confirmed live, not assumed: exec summary reports `Message seams 13`, and `GET /runs/{id}/seams`
serves 6 `external-integration` seams at L/16 to the UI.

### 10.6 An honest caveat on the new ranking

| App | LOC | pts (BUG-2) | pts (now) | pts/100 LOC (BUG-2) | pts/100 LOC (now) |
|---|---:|---:|---:|---:|---:|
| Fraud Banking | 4,782 | 328 | 328 | 6.86 | 6.86 |
| SpringBoot | 2,607 | 126 | 126 | 4.83 | 4.83 |
| Axon | 1,807 | 110 | **206** | 6.09 | **11.40** |

The Axon estate has moved from *lowest* per LOC (2.32, the original bug) to **highest** (11.40).
That direction is defensible — 9 Maven modules, 12 bounded contexts, event sourcing, a saga, and a
real external NATS→Event Hubs bridge with durable-consumer semantics — but the magnitude deserves
scrutiny rather than being presented as a clean win:

- 6 `external-integration` seams × 16pts = 96 points, nearly half the estate's total.
- Five of those are concrete subjects (`uli.events.portfolio.*`) all consumed by the same wildcard
  subscriber, plus one seam for the wildcard subscription itself. Each concrete subject is a distinct
  message schema that must be versioned and migrated independently, so this is **not** obviously
  double counting — but it is a judgement call, and if these estimates are used for real sprint
  planning the per-subject L/16 tier is the first thing to re-tune.

Flagged here rather than buried; no tuning was applied without evidence to justify a specific number.

### 10.7 Remaining gaps (now visible rather than silent)

1. **Kafka, MediatR, NServiceBus, Wolverine, Eventuate, Lagom, Spring `@EventListener`** — still no
   parsers, deliberately. They are now *reported* via `coverage_notes` when detected, so an estate
   using one gets an explicit "estimate is understated" note instead of a silent zero. Each becomes a
   ~30-line registry addition the moment a real fixture exists.
2. **`@ProcessingGroup` is captured but not yet used to refine flow classification.** The plan
   allowed for using it to distinguish independently-deployable processors; it is stored on the node
   and available, but flow roles are still derived from bounded context only. Deferred rather than
   applied speculatively, since on this fixture it would not have changed a single seam.
3. **NATS subject extraction is literal-only.** A subject built at runtime from a variable or
   constant (`jetStream.publish(subject, data)` in `UliPublisher`) is invisible — only string literals
   are matched. Constant-folding across classes was out of scope.
4. **`streams.yaml` is parsed with a small line reader**, not a YAML library, to avoid adding a
   dependency for one optional file. It handles the real fixture's shape; deeply nested or
   multi-document YAML would need a real parser.

---

## 11. Post-change incident: reported "no story points / specs not calculated" — false alarm, caused by run deletion (2026-08-19)

**Reported:** run `0b90dcf1` showed no story points in the Seams tab and no feature specs, immediately
after the §10 follow-up shipped. Read as a regression introduced by the `external-integration` work.

**It was not a regression. The run's directory had been deleted** during verification cleanup while
it was still open in the browser. `runs/0b90dcf1/` no longer existed, so every artifact request
returned `404 {"error": ... "Run not found"}` — the Seams tab rendered with no points and feature
specs appeared "not calculated", which is visually indistinguishable from a broken calculation.

**Evidence gathered before concluding:**

| Check | Result |
|---|---|
| `runs/0b90dcf1/` on disk | **absent** (deleted during cleanup) |
| `GET /runs/0b90dcf1/{seams,artifacts/seam,artifacts/feature_specs}` | **404 "Run not found"** on all three |
| Control: `GET /runs/883c1fb4/artifacts/feature_specs` | **200**, 32,054 bytes |
| Repro via direct phases (OBSERVER→FEATURE_SPECIFIER) | 21 seams / 206 pts, **21 specs / 206 pts** |
| Repro via full `run_full_pipeline()` with gates | 21 seams / 206 pts, **21 specs / 206 pts**, 0 seams missing a `work` block |

Two independent reproductions on the identical estate and config produced complete, correct output,
so the feature was never broken.

**Confirmed on a fresh run (`e0cc54bb`, run by Joao):** 6/6 gates APPROVED including `gate_4_5`
(planning), 14 artifacts, 21 seams / 206 pts, 21 specs / 206 pts, 11 work streams / 206 pts, zero
seams missing a `work` block, zero specs missing `story_points`, and `seam.id` set exactly equal to
`feature_specs.seam_id` set. Planning is obtained.

**Root cause of the false alarm, and the standing rule it produces:** a completed run is not scratch
space. It is the artifact the human is reading. Deleting a run directory to "tidy up" makes a healthy
feature look broken in the most convincing possible way — the UI shows exactly the symptom a real
calculation bug would produce, and the evidence needed to disprove it has just been destroyed. See
`transferable-skills/memory/run-directory-deletion-discipline.md`.

**Not changed as a result:** no code fix was warranted. One defensive improvement was considered and
deliberately deferred — the UI could distinguish "run not found" from "artifact not yet generated"
rather than rendering both as empty panels. That is a real UX gap this incident exposed, but it is a
product decision, not part of this fix, and is recorded in §10.7's spirit as a follow-up.

---

## 12. PR #45 review fixes — two precision defects in the NATS parser (2026-08-20)

Samuel Mbah reviewed PR #45, pulled the branch, independently reproduced the 213/1/0 suite result and
traced the registry design. He confirmed the Axon work (the actual BUG-2) as correct and well-tested,
and found **two precision defects scoped to the new NATS/Event Hubs parser**. Both were reproduced
locally before fixing — neither was accepted on description alone.

His framing is the important part: *neither crashes anything*, so both produce **a confident wrong
number rather than an obviously broken one**. For a change whose entire purpose is estimate accuracy,
that is the worst failure shape.

### 12.1 Defect 1 — any dotted string literal was treated as a NATS subject

`parse_nats_flows()` matched every `subscribe()`/`publish()`/`filterSubject()` call carrying a
dot-delimited literal, anywhere in the estate, with no check the call was actually NATS.

Reproduced: in an estate that genuinely uses NATS, two unrelated MQTT calls
(`c.subscribe("sensors.factory.temperature")`, `c.publish("sensors.factory.humidity", …)`) were scored
as full `external-integration` seams at **L/16pts each**, with NATS-specific migration guidance
("recreate durable consumer settings", "external brokers redeliver on at-least-once") attached to
code with nothing to do with NATS.

**This was my regression, introduced knowingly.** §10.2 records that the per-file `io.nats` import
gate was removed because it missed the thin-wrapper producer — `UliEventBridge.java` holds the subject
literals but imports only `UliPublisher`, which is the class importing `io.nats`. Removing the check
fixed that false negative and created this false positive. The correct answer was neither extreme.

**Fix — two-pass namespace gating.** Pass 1 establishes the estate's real NATS subject namespaces from
files that genuinely import NATS/Event Hubs, plus whatever `streams.yaml` declares. Pass 2 accepts a
subject from a non-importing file only when it falls inside one of those namespaces. This admits the
thin-wrapper publisher (`uli.events.portfolio.*` sits under the `uli.events.>` namespace established
by real NATS code) and rejects the unrelated broker (`sensors.*` matches no known namespace).

### 12.2 Defect 2 — wildcard pairing ignored subtree boundaries

`_root()` compared only the first two dot-separated segments, so a producer on
`uli.events.portfolio.Created` was paired with a subscriber on `uli.events.billing.>` — identical
two-segment prefix, entirely unrelated subtree.

Reproduced: `consumers = ['BillingSub', 'RealNats']` where only `RealNats` (subscribing
`uli.events.>`) genuinely covers that subject.

**Fix — real NATS wildcard semantics.** `_root()` is replaced by `_subject_matches(pattern, subject)`
implementing token-wise matching: `*` matches exactly one token, `>` matches one or more trailing
tokens and is valid only as the final token. Now `uli.events.>` matches
`uli.events.portfolio.Created` while `uli.events.billing.>` does not.

### 12.3 Verification

| Check | Result |
|---|---|
| Both defects reproduced against the reviewed commit | ✅ MQTT subjects leaked; `BillingSub` wrongly paired |
| Both behavioural tests fail pre-fix | ✅ confirmed by running them against `HEAD`'s parser |
| Suite | 213 → **225 passed, 1 skipped, 0 failed** (+12) |
| 11-estate regression sweep vs the reviewed commit | ✅ **11/11 byte-identical** |
| Real Axon fixture | unchanged — 6 `external-integration` seams, same subjects |

The sweep being fully identical is the expected and correct outcome: both defects required a
*second* messaging technology or a *sibling* subtree to manifest, and the real fixture has neither.
The bugs were real, but latent on today's fixtures — which is exactly why they needed a synthetic
reproduction to surface and a regression test to keep out.

New tests in `tests/test_nats_seams.py`: unrelated-broker rejection, thin-wrapper producer still
detected (guards against re-introducing the false negative while fixing the false positive), subtree
boundary respected, and 9 parametrized cases pinning NATS wildcard semantics.

### 12.4 Not changed

The §10.6 caveat stands unaltered — 6 external-integration seams at 16pts each is still ~47% of the
Axon estate's total, and the per-subject flat tier remains the first thing to re-tune before these
numbers drive real sprint planning. Samuel's review did not dispute the tier, and no evidence emerged
in this pass to justify changing a specific number.
