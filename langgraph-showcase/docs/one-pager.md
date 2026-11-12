# How Micro-Cosmos Works — Process Explanation for a Client

## The core idea

Micro-Cosmos takes a codebase in one language (Java, Python, C#, COBOL, PHP, or C) and produces an equivalent codebase in a target language, plus a paper trail of why every decision was made. It is not a one-shot "translate and pray" tool — it's an 11-stage pipeline where automated analysis alternates with mandatory human checkpoints (gates). Nothing moves to the next stage until either a person signs off or the run is explicitly configured to auto-approve (a deliberate, logged choice, not a default).

## 1. Expected input

| What | Detail |
|---|---|
| Source codebase | A working repo in Java, Python, C#, COBOL, PHP, or C |
| Source language | Told to the system explicitly (not auto-detected from scratch each time) |
| Target language | The language you want to migrate to |
| Nothing else is mandatory | The pipeline runs from source code alone |

## 2. Expected output

| Artifact | What it is |
|---|---|
| `ir_graph.json` | A language-agnostic map of the codebase (classes, functions, calls, dependencies) |
| `bounded_context_map.json`, `seam.json`, `work_streams.json` | The codebase broken into discrete, independently-migratable units ("seams") with effort/risk scoring |
| `tnas.json` + HTML reports | Target-native architecture spec — what the translated system's shape should be |
| `security_report.json` | CVE and vulnerability findings in the source, plus a Trivy scan of the generated output |
| `feature_specs.json` | Per-seam specs (acceptance criteria, story points, Jira-ready) |
| Translated code, one seam at a time | Each seam goes through code generation and its own test suite before being accepted |
| 14 HTML reports + `full-app-migration-report.html` | A complete, self-contained record of every decision, artifact, and generated file — this is what actually gets handed to the client's engineering team |

## 3. How we make sure the output is what's expected

This is the part that matters most to a client, so it's worth being concrete about the specific mechanisms, not just "we have review steps":

- **Six human gates, not one.** A domain architect, a business expert, a solution architect, a security architect, an engineering lead, and a lead engineer each sign off at a different point — analysis quality, business boundaries, target architecture, security posture, migration scope, and finally the generated code itself. Each is a distinct named role because each catches a different class of mistake.
- **Structural validation on every artifact, independent of any human review.** For example, a bounded-context map is rejected outright if it has fewer than 2 contexts, no cross-context calls, or wildcard node IDs — a common LLM failure mode where it writes `"prog.*"` instead of real identifiers. A `seam_result` missing a `pr` field is rejected as malformed rather than silently accepted. This exists because an LLM can produce something shaped like valid output that isn't.
- **Per-seam TDD loop.** Each unit of code goes through Code Writer → Skeptical Review → Test Review → Functional Review, up to 3 iterations before it's marked failed (with one further focused retry after all seams complete). A seam is never "translated once and shipped" — it's translated, attacked by three different review passes, and only accepted once it survives them.
- **Deterministic mode as a ground truth.** Every phase has a non-LLM, rule-based fallback (symbolic parsing rather than model generation). This is what deterministic mode runs by default, and it's also what "fills in" if an LLM call fails validation — so the pipeline never silently ships an unvalidated LLM guess as if it were solid analysis.
- **A dedicated security pass + Trivy scan on the output, not just the input** — meaning the generated code is checked for vulnerabilities the LLM might have introduced, not just what the original code already had.
- **Full traceability.** Every artifact, every gate decision, every seam's pass/fail history lands in `runs/<run-id>/` and the reports — so any output can be traced back to exactly which agent produced it and what evidence supported it.

## 4. Required inputs from the client

- Read access to the source repository.
- A decision on the target language.
- A named person for each gate role (or explicit sign-off to auto-approve, which is logged and requires a named reviewer anyway).

## 5. Ideal inputs (not required, but they raise quality)

- An existing test suite in the source codebase — the TDD loop and functional reviews are far stronger when there's real behaviour to check against, not just static structure.
- Documented business/domain context — bounded-context detection is a heuristic; a business expert who can correct it at Gate 2 catches mislabelled boundaries early, before they propagate into wrong architecture.
- Awareness of any messaging/event infrastructure in use (Kafka, MediatR, etc.) — only Axon and NATS/JetStream + Azure Event Hubs have real parsers today; anything else is reported as detected but unparsed, not silently guessed at (see limitations below).

## 6. Risks and mitigations

| Risk | Mitigation |
|---|---|
| LLM hallucinates or misreads code structure | Deterministic, rule-based fallback exists for every phase; structural validation rejects malformed output before it ever reaches a human |
| Generated code looks plausible but is behaviourally wrong | Three-stage review (skeptical/test/functional) per seam, capped iteration budget so it fails loudly rather than looping forever |
| A gate reviewer rubber-stamps without real scrutiny | This is a process risk, not a technical one — the pipeline can't force diligence. Auto-approve is opt-in and logged with a named reviewer, precisely so it's never accidental |
| New vulnerabilities introduced during translation | Security scan runs on the output, and a Trivy scan runs at the very end, not just on the source |
| A seam can't be migrated cleanly in the iteration budget | It's marked failed rather than shipped broken; Writer still packages the best-effort result so nothing silently vanishes, and it's visible in the reports, not hidden |
| CQRS/event-driven coupling invisible to a simple call-graph | A dedicated message-seam detection pass exists specifically because this used to be a blind spot (fixed 2026-08-19 per this repo's own history) |

## 7. Limitations (be upfront about these)

- Language support is fixed: Java, Python, C#, COBOL, PHP, and C as source (Kotlin and Go are target-only — the pipeline can generate them but has no source-side parser for them). Anything else isn't supported today.
- Message-flow parsing only covers Axon and NATS/JetStream + Azure Event Hubs. Any other message bus is flagged as detected but unparsed — never silently guessed — because this project's own standing rule is that a parser only gets added alongside a real fixture to verify against.
- Deterministic mode does not generate code. It's the safe, fast default for analysis and planning, but Code Writer and Writer are skipped — actual translated code only comes out of an LLM-mode run.
- The iteration budget is finite. A seam that's fundamentally hard to translate can end up in "failed" state rather than perfect — visible and reported, but not auto-fixed indefinitely.
- Gate quality depends on the human doing the reviewing. The system can enforce that someone signs off; it cannot enforce that they read carefully.

---

*Note: gate roles, validation rules, and iteration caps were pulled straight from the current code (`gates/__init__.py`, `pipeline.py`, `settings.py`) rather than from memory, so this reflects what's actually running today, not a stale description.*
