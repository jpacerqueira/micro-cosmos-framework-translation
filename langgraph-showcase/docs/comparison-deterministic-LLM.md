## Deterministic vs LLM mode — stage by stage

Every stage in the pipeline diagram, compared side by side. See the [pipeline diagram](../README.md#what-the-pipeline-does) and [Run modes](../README.md#run-modes) in the README for the full narrative version of this.

| Stage | Deterministic mode | LLM mode |
|---|---|---|
| Trivy prescan | Runs as normal — Trivy is a subprocess, not an LLM call | Same — identical in both modes |
| Observer | Symbolic IR graph from file-extension scanning; `security_hints` and `cqrs_framework_hints` still computed by deterministic post-hooks (manifest + annotation scan, no model call) | `observer_agent` produces an LLM-analyzed IR graph (semantic summaries, signatures, source excerpts) on top of the same deterministic `security_hints`/`cqrs_framework_hints` hooks |
| Gate 1 | Human approval gate — identical in both modes | Same |
| Cartographer | Real deterministic classifier (`analyse_bounded_contexts` — 14 ordered path rules, dead-code isolation, cross-context calls derived from IR edges), not a stub; `seam.json`/`work_streams.json` come from the same structural analysis | `cartographer_agent` produces LLM-analyzed bounded contexts on top of the same structural seam/work-stream data |
| Gate 2 | Human approval gate — identical | Same |
| Architect | Stub `tnas.json` via `derive_tnas()` (hardcoded literals per dimension); HTML reports generated from the stub artifact; not framework-aware even if `cqrs_framework_hints` detected one | `architect_agent` produces named-dimension fitness-suite prose and real architectural notes; explicitly instructed to name a detected CQRS/ES framework instead of proposing a generic pattern |
| Gate 3 | Human approval gate — identical | Same |
| Security | Deterministic CVE placeholder from `scan_source_for_security()` | `security_agent` produces real findings (severity, CWE ID, location, remediation) plus `reports/security-report.html` |
| Gate 4 | Human approval gate — identical | Same |
| Feature Specifier | Mechanical specs: title derived from the seam ID, three generic acceptance criteria, no API-surface inference | LLM-enriched specs: business value, inferred API surface, story-point estimate, Jira labels, per-seam acceptance criteria |
| Gate 4.5 "Planning" | Opens normally; panel shows the deterministic specs — approve/reject as usual | Same panel UI — only spec quality differs from deterministic mode |
| Skills + Kiro.dev Powers | Generated once before the seam loop, from embedded Python — identical output in both modes | Same |
| Code Writer | **Not executed** — no code translation; a warning event is emitted per seam | Runs per seam with a rich kickoff (seam type, source file, migration steps, architecture guidance); up to 5 TDD iterations |
| Skeptical Review | Not executed (no code to review) | Checks every function for stubs, wrong types, logic errors |
| Test Review | Not executed | Enforces happy-path + rule-violation + edge-case tests |
| Functional Review | Not executed | Verifies source business rules are faithfully preserved |
| Writer | Not executed | Writes translated files into `reports/<project>_<lang>/`, appends a seam section to the generated module README |
| PR Reviewer | Not executed | 8-check automated code review; writes `review_report.json` |
| Gate 5 | Still opens — PR Reviewer has no deterministic fallback (warns "no deterministic fallback for pr_reviewer" and saves nothing), so Gate 5 blocks on an empty `review_report.json` rather than being skipped | Human approves/rejects a real 8-check `review_report.json`; rejection re-runs the full seam TDD loop |
| Trivy output scan | Still runs — Trivy is a subprocess, not an LLM call | Runs against `reports/<project>_<lang>/`; writes `trivy_output_report.json` + `reports/output-security-report.html` |

Deterministic vs LLM mode is one global setting (`SKIP_LLM`) that also governs the ASK tab (extractive-only answers) and embeddings (lexical fallback), not just the pipeline stages above.
