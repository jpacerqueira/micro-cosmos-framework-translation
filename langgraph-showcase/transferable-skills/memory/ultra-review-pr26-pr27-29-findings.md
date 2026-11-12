# Ultra-mode code review of PR #26/#27 — 29 findings fixed

Joao asked for a `/code-review` at `max` effort against the full PR #27 commit range (PR #26 was
confirmed via `git log` to be a single already-merged commit, so out of scope on its own). The
skill forked into 8 parallel finder agents + a consolidator; after dedup, `ReportFindings` reported
29 distinct findings across `observer_tools.py`, `writer_tools.py`, `framework_tools.py`,
`driver.py`, `app.py`, `run.html`, and 5 files in the Java Axon example app. Joao explicitly asked
to be consulted before any fix — the findings were presented plain-text first, nothing changed
until he said "Fix, all."

## Observer / Java-Axon parsing fixes (`micro_cosmos/tools/observer_tools.py`)

- **Wildcard Axon imports weren't resolved.** `_java_import_map` only ever returned the explicit
  `import x.Y;` → `Y` map; a file importing `org.axonframework.eventsourcing.*` and then using a
  bare `@EventSourcingHandler` never matched. Fixed by having `_java_import_map` also return the
  set of wildcard-imported packages, and `_axon_annotations` accepts a name if it's either an exact
  import match OR a known Axon annotation name with some wildcard package starting with
  `org.axonframework`.
- **Nested-class member misattribution.** `_owner_class(pos)` used to mean "name of the last class
  declared before this position" — wrong whenever an outer class contains a nested class; a member
  declared after the nested class but still inside the outer class's body got attributed to the
  nested class instead. Rewritten to compute real brace-depth-tracked body ranges per class
  (`cls_body_ranges: list[tuple[start,end,name]]`) and pick the **smallest enclosing range**
  containing `pos`. Regression test asserts a member after a nested type still resolves to the
  outer class, and that this doesn't introduce a `MISSING_AGGREGATE_IDENTIFIER` false positive.
- **Regex catastrophic backtracking.** `_JAVA_ANN`/`_JAVA_ANN_REQUIRED` used `\s*\n\s*` — `\s`
  already matches `\n`, so a long blank-line run had exponentially many ways to split across the
  three groups. Fixed to `[ \t]*\n\s*` (no overlap). Verified by timing a `.search()` against a
  synthetic 8000-blank-line input directly (not just "looks fine now").
- **SQL DDL alongside a Java estate wasn't scanned at all.** `_LANG_EXTENSIONS` for
  `java`/`java8`/`java11`/`java21` didn't include `.sql`, so migration/schema files sitting next to
  a Java estate were silently invisible to Observer. Added `.sql`. The `CREATE TABLE` regex itself
  was also too narrow (`^\s*CREATE\s+TABLE\s+(\w+)`) — didn't handle `IF NOT EXISTS` or
  schema-qualified/quoted names (`schema."My Table"`, `` `tbl` ``). Broadened it, and changed the
  table node id from `f"class.{name}"` to `f"table.{name}"` so a table can't collide with a
  same-named Java class in the IR graph.
- **`n.get("attributes", {})` null-unsafe pattern** (4 spots in the Axon performance-antipattern
  scan) — a `dict.get(key, default)` default only fires when the key is *absent*, not when its
  value is explicit JSON `null`. Fixed to `(n.get("attributes") or {})`, the pattern already used
  elsewhere in this codebase (`spec.get("acceptance_criteria") or []`). This same class of bug
  recurred in `framework_tools.py` (see below) — worth grepping for `.get(\w+, {})`/`.get(\w+, \[\])`
  again if a future review has spare capacity, since it's clearly not fully swept yet.

## Writer / OpenSpec generator fixes (`micro_cosmos/tools/writer_tools.py`)

- **Markdown table injection.** Untrusted, per-run dynamic text (security-finding titles,
  requirement descriptions, etc.) interpolated directly into a `|`-delimited table row: a literal
  `|` in the text silently shifted column boundaries and corrupted the rendered table. Fixed with a
  new `_md_cell(value)` helper (`str(value).replace("|", "\\|")`) applied everywhere genuinely
  dynamic content is interpolated — not applied to static, already-safe strings.
- **WHEN/THEN scenario parsing was both case-sensitive and substring-unsafe.**
  `.removeprefix("When")` missed all-caps `"WHEN ..."`; `"then" in lower` matched inside
  `"lengthen"`/`"strengthen"`. Fixed with word-boundary regexes (`_OPENSPEC_WHEN_RE`/
  `_OPENSPEC_THEN_RE`, `\bwhen\b`/`\bthen\b`, `re.IGNORECASE`).
  `test_write_openspec_handles_explicit_nulls_without_crashing_or_leaking_none` and a parametrized
  WHEN/THEN test cover both.
- **Explicit-null handling** across `_openspec_spec_from_feature_specs`/`_openspec_security_spec`/
  design.md builders — several `.get(key, default)` calls hit the same "default doesn't apply to
  JSON `null`" bug as above; fixed with the same `or` pattern throughout, plus isinstance guards on
  findings before iterating (a `security_report.json` findings value of `null` used to crash the
  generator rather than degrade gracefully).
- **Duplicated shared-content logic** — `_openspec_observability_spec`/`_openspec_testing_spec` had
  copy-pasted inline loops; extracted into `_truncate_heading`/`_checklist_to_scenarios` helpers.
- **Deduplicated severity ordering + a findings cap.** Both `_security_findings_block` and
  `_openspec_security_spec` had their own local severity-order dict; now both import `_SEV_ORDER`
  from `micro_cosmos/tools/security_tools.py` (single source of truth). Added `_SECURITY_FINDINGS_LIMIT
  = 40` so a pathological run with thousands of findings can't blow up a generated report.
- **Work-stream slug collisions** — two work streams that slugify to the same folder name used to
  silently overwrite each other's `spec.md`. Fixed with a `used_slugs: dict[str,str]`
  disambiguation pass.
- **Deliberately NOT fixed**: did not convert the large pre-existing plain-string Kiro POWER.md
  templates to f-strings to get literal reuse of `_TESTING_TAXONOMY_CHECKLIST`/
  `_OBSERVABILITY_CHECKLIST` — those templates contain literal `{Aggregate}`-style placeholder text
  that would need real escaping work with no functional benefit beyond DRY. Fixed the misleading
  "shared content" comment instead of the code.

## Async/logging fixes (`micro_cosmos/orchestration/driver.py`)

- `_write_openspec` (sync, file-I/O heavy) was called directly inside an async generator, unlike
  its two sibling call sites in `app.py` which already wrap the equivalent call in
  `asyncio.get_event_loop().run_in_executor(None, lambda: ...)`. Fixed to match. A bare
  `except Exception: pass` around it was also silently swallowing real failures — changed to
  `diagnostics.log.exception(...)` so a broken OpenSpec generation shows up in logs instead of
  vanishing.

## `framework_tools.py` — CQRS framework registry de-hardcoding

`_CQRS_FRAMEWORK_SIGNATURES` (a `dict`) renamed/restructured to `_CQRS_FRAMEWORKS` (a
`list[tuple[name, signatures]]`), mirroring the registry pattern already established in
`scheduler_tools.py`'s `_SCHEDULERS`. Same `n.get("attributes", {})` → `(n.get("attributes") or {})`
null-safety fix applied here too. See [[cqrs-framework-detection]] for the original feature this
extends.

## `app.py` / `run.html` — OpenSpec menu cleanup

- Added a stale-`openspec.yaml` cleanup block next to the existing `openapi.yaml` full-zip
  generation block (left over from the OpenAPI rename — see [[openapi-rename-and-openspec-artifact]]).
- Removed the now-dead `download_openspec` template context key.
- `run.html`'s OpenSpec menu block used to gate the button itself behind
  `{% if download_openspec %}...{% else %}Not yet generated{% endif %}` — but the folder name
  (`openspec`) never varies, unlike Skills/Kiro which are seam-specific, so the button should
  always render; only the download *link* needs to stay conditional on `zip_openspec_ready`.

## Example-app Java fixes (6 files, real bugs in the CAN Axon fixture used for testing)

These are fixture/example-app files, not Micro-Cosmos product code, but real bugs worth fixing since
this fixture is used to exercise the pipeline against real Axon/Spring/NATS code:

- **`PortfolioController.java` — IDOR-style bug.** Axon routes commands on the
  `@TargetAggregateIdentifier` field inside the command body, **not** on the URL path variable.
  `addProperty`/`allocate`/`submitValuation` accepted a `{id}` path segment purely for REST
  ergonomics but never checked it matched the command body's `portfolioId` — a caller could target
  one portfolio in the URL while actually mutating a different one via the body. Fixed with an
  explicit `if (!id.equals(body.portfolioId())) return badRequest()` guard on all three endpoints.
- **`BffConfig.java` — two issues.** `.requestMatchers("/graphiql/**").permitAll()` in the `!local`
  security chain left the GraphQL IDE open with no auth in non-local environments. `propagateBearer()`
  was a no-op stub — outbound `WebClient` calls never forwarded the inbound caller's Authorization
  header, meaning downstream services couldn't identify the real caller. Fixed: removed the
  `permitAll()`, implemented header forwarding via `RequestContextHolder`/`ServletRequestAttributes`
  to read the current inbound request.
- **`PortfolioGraphQl.java`** — `properties()` resolver called `UUID.fromString(...)` on
  `portfolio.get("portfolioId")` with no null guard; a missing/null id threw instead of returning an
  empty list.
- **`EventHubBridgeApplication.java` — ack/nak scoping bug.** `BridgeLoop.pump()` used to
  accumulate every NATS message across the whole poll and only ack/nak the entire original batch
  after all Event Hubs sub-batches were sent. If sub-batch 2 of 3 failed, sub-batch 1's
  already-durably-sent messages got NAK'd too, and JetStream would redeliver + republish them —
  duplicate events downstream. Fixed by tracking `pending` per sub-batch and calling a new
  `flushAndAck(EventDataBatch, List<Message>)` immediately after each sub-batch is sent, so only the
  messages a given sub-batch actually represents get acked or nak'd.
- **`B2bInvitationService.java`** — logged the raw external email address on both the success and
  failure paths. Added a `maskEmail()` helper (`j***@domain.com`-style) and used it in both log
  calls — app logs typically have looser access control and longer retention than the identity
  system itself.
- All 6 fixes verified via a real `mvn compile` (Maven + JDK available on host, network access for
  dependency resolution) — not just brace/paren-balance heuristics. `webapp-bff`, `user-auth`,
  `eventhub-bridge` modules all compiled clean. `property-allocation` has a **pre-existing, unrelated**
  compile error in `PortfolioProjection.java` (missing Lombok-generated setters) confirmed via
  `git log` to be from the user's own unrelated rename commit, not touched by this fix batch —
  correctly left alone and flagged as an FYI rather than silently fixed or silently ignored.

## Verification

Full suite: 133 passed, 1 skipped, same 6 known-and-explained pre-existing failures (5 already
documented + `test_fitness_suite_passes_clean_code`, flagged unrelated in an earlier review pass).
A dedicated live end-to-end script ran Observer→Cartographer→Architect→Security→Feature Specifier
against the real `examples/java-axonframework-example-app` fixture and asserted: the constructor
command-handler is still detected (regression guard for an earlier fix), `openapi.yaml` still
generates valid `openapi: 3.1.0`, the generated OpenSpec security spec contains no literal `"None"`
string, and Skills/Kiro Powers both generate with the security artifact present — confirming the
fixes work against real code, not only synthetic test fixtures.

## Judgment calls made and surfaced to Joao rather than silently applied

- Did not fix `test_fitness_suite_passes_clean_code` (pre-existing, environmental, not one of the
  29 findings).
- Did not fix the newly-discovered `PortfolioProjection.java` compile error (out of scope, predates
  this branch).
- Did not rewrite the user's own already-made commit to fix its message-convention violation.
- Did not attempt every theoretical CREATE-TABLE SQL edge case (multi-line declarations, quoted
  identifiers containing spaces) — fixed the two concretely-reported cases plus basic
  backtick/quote/bracket handling, documented the remaining limitation in a code comment.
