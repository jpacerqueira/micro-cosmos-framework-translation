# Agent Skills — micro-cosmos / micro_cosmos/agents

This folder contains the LLM agents that form the full source-to-target modernisation
pipeline. Micro-Cosmos extends the analysis pipeline with **code generation, multi-pass
review, and file materialisation**, producing production-quality target-language code from
any supported source estate.

---

## Pipeline overview

```
Source estate (files on disk)
        │
        ▼
  [Observer] ── Gate 1 ──► [Cartographer] ── Gate 2 ──► [Pattern] ── Gate 3 ──► [Architect] ── Gate 4
      │                          │                          │                         │
  ir_graph               bounded_context_map           domain_model                 tnas
  (output_key)            (output_key)                 (output_key)            (output_key)
                                                                                     │
                                                         ┌───────────────────────────┘
                                                         ▼
                                                  [Code Writer] ◄──── Gate 5 (loop)
                                                         │        ▲
                                              seam_result.json    │
                                                         │        │  SkepticalReviewer
                                                         │        │  FunctionalReviewer
                                                         │        │  TestReviewer
                                                         ▼
                                                    [Writer] ── Gate 6 ──► [PR Reviewer]
                                                         │                       │
                                                  write_manifest            review_report
                                                  (output_key)              (output_key)
```

Each gate reinjects reviewer constraints into session state and reruns the preceding agent.
The Code Writer loop runs until all three reviewer agents (Skeptical, Functional, Test)
produce zero BLOCKER findings or the retry cap is reached.

---

## Agent 1 — Observer

**File:** `observer.py`  
**Output key:** `ir_graph`  
**Gate variable:** `{gate_1_constraints?}`

### Skill

Reads every source file in the estate and produces a semantic IR property graph.
The **only** agent that touches raw source files. The LLM reasons about what the code
actually does and submits structured observations that enrich the deterministic symbolic parser.

### Tools

| Tool | Defined in | Purpose |
|---|---|---|
| `list_source_files` | `source_tools.py` | Walk source estate; return file list with truncated excerpts |
| `read_source_file` | `source_tools.py` | Read a single file in full |
| `submit_observer_output` | `observer_tools.py` | Run symbolic parser, attach LLM observations, merge annotations via FAISS, cache IR |

### Session state consumed

| Variable | Description |
|---|---|
| `{source_path?}` | Filesystem root of the source estate |
| `{source_lang?}` | Language tag: `java`, `python`, `go`, `cobol`, `rust`, `kotlin`, `scala`, `c`, `cpp`, `ruby`, `swift`, `sql`, `terraform`, … |
| `{gate_1_constraints?}` | Rejection feedback from Gate 1 reviewer (empty on first run) |

### What the IR contains after this agent

The `submit_observer_output` tool runs `observe_source_estate`, which:
1. Runs `parse_source_estate` → one `PROGRAM` node per file, plus class/method/field nodes
   and `CALLS`/`DEFINES`/`REFERENCES`/`WRITES` edges for all languages with a deep parser.
2. Runs `catalogue_dead_code` → flags nodes with no inbound `CALLS` edge.
3. Runs `scan_performance_anti_patterns` → SQL-in-loop, file-open-in-loop, Axon checks
   (`MISSING_AGGREGATE_IDENTIFIER` CRITICAL, `BYPASS_COMMAND_GATEWAY` HIGH).
4. Runs `retrieve_documentation` → reads `.md`/`.rst`/`.txt`/`.adoc` files for RAG context.
5. Merges `function_summaries` from the LLM — exact name match first, then **FAISS cosine
   similarity** (`NodeVectorIndex` in `vector_index.py`, threshold 0.60, backed by
   `sentence-transformers all-MiniLM-L6-v2` with char-trigram TF-IDF fallback) so
   annotations are not silently dropped when the LLM names a function differently.

### Language skill matrix

| Language | File detection (`_LANG_EXTENSIONS`) | Call edges (`_CALL_EXTRACTORS`) | Deep node extraction (`_DEEP_PARSERS`) | WRITES edges | LLM instruction guidance |
|---|---|---|---|---|---|
| Python 2 / 3 | ✅ `.py` | ✅ top-level imports | ✅ AST (`ast` module) + regex fallback for Python 2 | — | ✅ Full OOP + type annotations + docstrings |
| PHP | ✅ `.php` `.phtml` | ✅ require/include/use | ✅ class/interface/trait/method/property + DocBlock | — | ✅ Namespace, visibility, return types |
| **Java / Java 8–21** | ✅ `.java` + `.sql` | ✅ import-based (`_extract_calls_java`) | ✅ `_parse_java_file` — class/interface/enum/record, methods, fields, Axon annotations, `throws`, `is_static`, SQL `CREATE TABLE` | — | ✅ Full OOP: FQN, annotations, generics, `throws`, `is_static`, Axon-aware |
| JavaScript / Node.js | ✅ `.js` `.mjs` `.cjs` (also `nodejs`) | ✅ ES import + require() | ✅ `_parse_javascript_file` — classes, named functions, arrow functions, Express routes | — | ✅ Classes, components, Express route registrations |
| TypeScript / React.js | ✅ `.ts` `.tsx` (also `react`, `jsx`) | ✅ (shared with JS extractor) | ✅ `_parse_typescript_file` — extends JS parser + interfaces, type aliases, Angular/NestJS decorators, React component detection | — | ✅ Interfaces, type aliases, decorators, JSX component guidance |
| C# | ✅ `.cs` | ✅ `using`-based (`_extract_calls_csharp`) | ✅ `_parse_csharp_file` — namespace, class/interface/struct/enum/record, `[Attribute]`, methods, properties | — | ✅ Namespace, OOP hierarchy, C# attributes, access modifiers, `is_static` |
| Go | ✅ `.go` | ✅ import path strings (`_extract_calls_go`) | ✅ `_parse_go_file` — structs/interfaces/type aliases, methods with receiver, free functions, exported fields | ✅ `recv.Field =` mutations | ✅ Package, receiver type, goroutines, exported symbols |
| Rust | ✅ `.rs` | ✅ `use`/`mod`/`extern crate` (`_extract_calls_rust`) | ✅ `_parse_rust_file` — structs/enums/traits, impl blocks, functions, struct fields, pub visibility | ✅ `self.field =` mutations | ✅ Module path, trait/impl, lifetimes, pub visibility, async |
| Kotlin | ✅ `.kt` | ✅ import class names (`_extract_calls_kotlin`) | ✅ `_parse_kotlin_file` — data/sealed/object/enum classes, interfaces, suspend functions, properties, annotations | — | ✅ Data classes, sealed, companion, suspend functions |
| Scala | ✅ `.scala` | ✅ import class names + `{...}` multi-import (`_extract_calls_scala`) | ✅ `_parse_scala_file` — case/sealed classes, objects, traits, defs, implicit/override, vals/vars | — | ✅ Case class, sealed trait, implicits, trait mixins |
| C | ✅ `.c` | ✅ `#include "..."` local headers (`_extract_calls_c`) | ✅ `_parse_c_file` — structs/unions/enums, typedefs, function definitions | — | ✅ Struct layout, function signatures, preprocessor guards |
| C++ | ✅ `.cpp` `.cc` `.cxx` | ✅ `#include "..."` local headers (shared with C) | ✅ `_parse_cpp_file` — extends C parser + namespaces, class declarations, `ClassName::method` definitions | — | ✅ Namespace, class hierarchy, templates, header pairing |
| Ruby | ✅ `.rb` | ✅ require/require_relative/autoload (`_extract_calls_ruby`) | ✅ `_parse_ruby_file` — modules, classes with superclass, methods, instance variables | — | ✅ Modules, mixins, method visibility, instance variables |
| Swift | ✅ `.swift` | ✅ `import` non-stdlib (`_extract_calls_swift`) | ✅ `_parse_swift_file` — classes/structs/protocols/enums/actors, extensions, functions, properties, annotations | — | ✅ Protocols, extensions, async/throws, property wrappers |
| SQL (standalone) | ✅ `.sql` | ✅ `\i`/`\ir` psql directives (`_extract_calls_sql`) | ✅ `_parse_sql_file` — tables, views, procedures, functions, triggers, FK REFERENCES edges | — | ✅ CREATE TABLE/VIEW/PROCEDURE/FUNCTION/TRIGGER, FK, indexes |
| Terraform | ✅ `.tf` `.tfvars` | ✅ relative `source = "..."` (`_extract_calls_terraform`) | ✅ `_parse_terraform_file` — resources, modules, variables, outputs, data sources, providers, module REFERENCES edges | — | ✅ resource, module, variable, output, data, provider |

**Legend:** ✅ implemented · — not applicable / not yet emitted

### Annotation merging — FAISS vector index

`submit_observer_output` builds a `NodeVectorIndex` (`micro_cosmos/tools/vector_index.py`) from
all parsed IR nodes on every call. When LLM `function_summaries` names do not exactly match
parsed node names, cosine nearest-neighbour search (threshold 0.60) resolves the mismatch.

Embedding strategy: `sentence-transformers all-MiniLM-L6-v2` (384-d, already a project
dependency, lazy singleton) → char-trigram TF-IDF fallback. Index backed by `faiss.IndexFlatIP`
when `faiss-cpu` is installed, pure-numpy `_NumpyFlatIP` otherwise.

---

## Agent 2 — Cartographer

**File:** `cartographer.py`  
**Output key:** `bounded_context_map`  
**Gate variable:** `{gate_2_constraints?}`

### Skill

Identifies bounded contexts by running three independent deterministic analyses over the IR
and merging them with weighted voting. The LLM renames each cluster to a meaningful domain
name and adds a one-sentence rationale.

### Tools

| Tool | Defined in | Purpose |
|---|---|---|
| `analyse_bounded_contexts` | `cartographer_tools.py` | Run three-way analysis; return voted context clusters |

### Session state consumed

| Variable | Description |
|---|---|
| `{source_path?}` | IR cache lookup key |
| `{source_lang?}` | IR cache lookup key; informs naming conventions |
| `{gate_2_constraints?}` | Rejection feedback from Gate 2 reviewer |

### How the voting works

| Analyses agreeing | Confidence assigned |
|---|---|
| 3 of 3 | `HIGH` |
| 2 of 3 | `MEDIUM` |
| 1 of 3 | `LOW` — flagged to gate reviewer |

Three analyses:
1. **Co-mutation clustering** (`CO_MUTATES_WITH` edges) — active for Go and Rust which emit `WRITES` edges.
2. **Call-graph connectivity** (`CALLS` edges) — active for all 16 languages.
3. **Table ownership** heuristic — absence of inbound `CALLS` as proxy for data ownership.

### Language-idiomatic naming

| Language(s) | Naming convention |
|---|---|
| Java, Kotlin, Scala | Domain package segment (`PaymentProcessing`) |
| Go | Package name or feature folder |
| Rust | Crate or module name |
| C, C++ | Subsystem or library name |
| C# | Namespace or assembly name |
| Ruby | Gem name, engine, or top-level module |
| Swift | Framework or feature module name |
| JavaScript, TypeScript, Node.js | Feature folder or service name |
| React.js / JSX | UI domain or page-region name |
| SQL | Data domain derived from table prefix or schema name |
| Terraform | Infrastructure domain (`NetworkingLayer`) |

---

## Agent 3 — Pattern

**File:** `pattern.py`  
**Output key:** `domain_model`  
**Gate variable:** `{gate_3_constraints?}`

### Skill

Extracts the modern software design patterns implicit in the IR: aggregates, domain events,
hexagonal ports, and finite state machines. Adds business-level descriptions and invariant
lists to each aggregate — these invariants become hard requirements on the generated code.

### Tools

| Tool | Defined in | Purpose |
|---|---|---|
| `extract_domain_model` | `pattern_tools.py` | Walk IR graph; detect aggregates, FSMs, events, ports; return structured domain model |

### Session state consumed

| Variable | Description |
|---|---|
| `{source_path?}` | IR cache lookup key |
| `{source_lang?}` | IR cache lookup key |
| `{gate_3_constraints?}` | Rejection feedback from Gate 3 reviewer |

### What the LLM must add

- `business_description` per aggregate — one sentence describing the real-world concept owned.
- `invariants` list — rules that must never be violated (e.g. `"balance must never go negative"`).
  These are enforced as explicit guards in the generated code by the Code Writer.
- `trigger_descriptions` per FSM transition — one sentence in business terms (not technical).
- Top-level `summary` — 2–3 sentences for the human gate reviewer.

---

## Agent 4 — Architect

**File:** `architect.py`  
**Output key:** `tnas`  
**Gate variable:** `{gate_4_constraints?}`

### Skill

Derives the Technology-Neutral Architecture Specification (TNAS) — the service decomposition
plan consumed by the Code Writer. Uses seam analysis to inform service boundaries and
architect notes.

### Tools

| Tool | Defined in | Purpose |
|---|---|---|
| `derive_tnas` | `architect_tools.py` | Assemble bounded contexts into services; return `valid_context_names` |
| `identify_seams` | `seam_tools.py` | Find object / boundary / link / preprocessing seams in the IR |

### Session state consumed

| Variable | Description |
|---|---|
| `{source_path?}` | IR cache lookup key |
| `{source_lang?}` | Source language |
| `{target_lang?}` | Target language |
| `{gate_4_constraints?}` | Rejection feedback from Gate 4 reviewer |

### Hard validation rules

1. Every name in `node_ids` must exist in `valid_context_names`.
2. No service may have empty `node_ids`.
3. No bounded-context name may appear in more than one service.
4. Every `rationale` must cite at least two context names from its own `node_ids`.

### Migration risk heuristics

| Source → Target | Baseline | Elevated to HIGH when |
|---|---|---|
| Java → Kotlin | LOW | External contract coupling or Spring annotation semantics change |
| Java → Go | MEDIUM | OOP hierarchy depth > 3, thread-local state, checked exceptions |
| Java → Rust | HIGH | Shared mutable state, complex generics, lifecycle dependencies |
| Python → Go / Rust | MEDIUM | Dynamic typing, duck-typed interfaces need explicit trait/interface |
| JavaScript → TypeScript | LOW | Implicit `any` types, runtime type coercion patterns |
| Node.js → Go | MEDIUM | Callback/promise chains → goroutine/channel model mismatch |
| C → Go / Rust | HIGH | Pointer arithmetic, manual memory management, `void*` |
| C++ → Rust | HIGH | RAII ownership model differs from Rust's borrow checker |
| Ruby → Go / Java | MEDIUM | Dynamic metaprogramming, open classes, Rails convention-over-config |
| Swift → Kotlin | LOW | Protocol-oriented → interface-oriented; `@State` → `StateFlow` |
| COBOL → Java / Kotlin | HIGH | Any stateful module, REDEFINES clauses, packed decimals |
| SQL stored procedures with business logic | MEDIUM | Shared mutable state, triggers, cursor loops |
| Pure SQL DDL | LOW | — |
| Terraform (any source lang) | MEDIUM | Provider-specific resources not available in target cloud → HIGH |
| React.js → any backend lang | HIGH | DOM dependency, client-side state management |

### Seam-aware notes requirement

For every HIGH-risk seam from `identify_seams`, `architect_notes` must name the seam
location, explain the boundary risk, and give a specific recommendation (e.g. "introduce a
port/adapter before migration"). Generic advice without seam location references is rejected.

---

## Agent 5 — Code Writer

**File:** `code_writer.py`  
**Output key:** `seam_result` (written via `submit_seam_translation`)  
**Gate variable:** Gate 5 loop (driven by three reviewer agents)

### Skill

Re-architects source code into idiomatic, production-quality target-language code seam by
seam. Reads domain model invariants and architect notes, queries spec docs for target-language
patterns, and produces both implementation files and a matching test suite. Runs in a
correction loop until all reviewers pass.

### Tools

| Tool | Defined in | Purpose |
|---|---|---|
| `list_source_files` | `source_tools.py` | List source files for the current seam |
| `read_source_file` | `source_tools.py` | Read a single source file in full |
| `read_generated_files` | `coding_loop_tools.py` | Read files produced in a previous iteration |
| `submit_seam_translation` | `coder_tools.py` | Submit the finished seam translation |
| `query_spec_docs` | `spec_tools.py` | Look up target-language patterns from indexed spec docs (ChromaDB RAG) |

### Session state consumed

| Variable | Description |
|---|---|
| `{source_path?}` | Source estate root |
| `{source_lang?}` | Source language |
| `{target_lang?}` | Target language |
| `{current_seam?}` | Seam name being translated in this iteration |
| `{run_dir?}` | Run output directory for file I/O |
| `{domain_model?}` | Injected from Pattern agent output |
| `{tnas?}` | Injected from Architect agent output |

### Correction loop behaviour

If the kickoff message starts with `"FIX THESE ISSUES"`:
1. Reads previous output via `read_generated_files`.
2. Fixes every listed issue — no skips.
3. Re-submits ALL files (fixed + unchanged verbatim).

### Hard requirements on generated code

- Every aggregate invariant from `domain_model` must be enforced by an explicit guard.
- Monetary fields must use the exact-precision decimal type for `{target_lang?}`:
  Java → `BigDecimal`, Python → `decimal.Decimal`, Go → `shopspring/decimal`, C# → `decimal`, Kotlin → `BigDecimal`.
- No stub bodies, `panic("not implemented")`, `raise NotImplementedError()`, or TODO-only functions.
- Tests must cover: happy path, rule violation (invalid input rejected), and at least one edge case.

---

## Agent 6 — Writer

**File:** `writer.py`  
**Output key:** `write_manifest`

### Skill

Reads `seam_result.json` from the run directory and materialises all translated files onto
disk under `runs/{run_id}/output/`. Produces a manifest listing each file's path, size, and
language.

### Tools

| Tool | Defined in | Purpose |
|---|---|---|
| `write_output_files` | `writer_tools.py` | Read seam_result; write all translated files; return manifest |

### Session state consumed

| Variable | Description |
|---|---|
| `{source_path?}` | Source estate root |
| `{source_lang?}` | Source language |
| `{target_lang?}` | Target language |
| `{current_seam?}` | Seam name |
| `{run_dir?}` | Run output directory |

---

## Agent 7 — PR Reviewer

**File:** `reviewer.py`  
**Output key:** `review_report`

### Skill

Performs seven sequential automated checks across all translated files. Findings are classified
BLOCKER / MAJOR / MINOR and consumed by Gate 6.

### Tools

| Tool | Defined in | Purpose |
|---|---|---|
| `review_output_files` | `reviewer_tools.py` | Run seven checks; return structured review report |

### Seven checks (in order)

1. **File coverage** — translated source files exist, not just port stubs.
2. **Decimal hygiene** — no `float`/`double` on monetary fields.
3. **Import integrity** — decimal imports present where decimal types are used.
4. **TODO density** — less than 40% TODO comment lines per file.
5. **Method coverage** — each class has at least one method.
6. **Port presence** — hexagonal port interfaces exist.
7. **Structural parse** — brace balance in compiled-language files.

---

## Agent 8 — Functional Reviewer

**File:** `functional_reviewer.py`  
**Output key:** submitted via `submit_functional_review`

### Skill

Verifies generated code preserves every business rule from the source. Reads source and
generated files for the current seam, builds an invariant checklist, and cross-references
every calculation, validation, and conditional branch.

### Tools

| Tool | Defined in | Purpose |
|---|---|---|
| `list_source_files` | `source_tools.py` | List source files for the current seam |
| `read_source_file` | `source_tools.py` | Read a source file in full |
| `read_generated_files` | `coding_loop_tools.py` | Read generated files from the run directory |
| `submit_functional_review` | `coding_loop_tools.py` | Submit review findings |
| `query_spec_docs` | `spec_tools.py` | Look up target-language patterns |

### Hard rules

- A source invariant with no corresponding guard in the generated code → **BLOCKER**.
- A guard with a looser bound (e.g. source checks `> 0` but generated checks `>= 0`) → **MAJOR**.
- Every calculation must use identical operators, operand order, and precision.
- Every validation (required field, range guard, non-null) must be present.

---

## Agent 9 — Test Reviewer

**File:** `test_reviewer.py`  
**Output key:** submitted via `submit_test_review`

### Skill

Enforces TDD discipline. Verifies generated tests prove real behaviours — not just that
objects can be constructed.

### Tools

| Tool | Defined in | Purpose |
|---|---|---|
| `read_generated_files` | `coding_loop_tools.py` | Read generated files |
| `submit_test_review` | `coding_loop_tools.py` | Submit test review findings |
| `query_spec_docs` | `spec_tools.py` | Look up target-language test patterns |

### Required test categories

| Category | Definition |
|---|---|
| Happy path | Valid input → operation succeeds with expected result |
| Rule violation | Invalid input → system rejects with expected error/exception |
| Edge case | Boundary value, empty collection, zero, max/min, null reference |

### Finding criteria

- Test with no assertion → **MAJOR**.
- Trivial assertion (`assertTrue(true)`, `assertEquals(1, 1)`) → **MAJOR**.
- Missing happy path, rule-violation, or edge-case category → **MAJOR**.
- Fewer than 3 test methods per class → **MINOR**.

---

## Agent 10 — Skeptical Code Reviewer

**File:** `skeptical_reviewer.py`  
**Output key:** submitted via `submit_code_review`

### Skill

Deliberately sceptical review of every function and method for stubs, non-idiomatic patterns,
incorrect decimal types, and incomplete control flows.

### Tools

| Tool | Defined in | Purpose |
|---|---|---|
| `read_generated_files` | `coding_loop_tools.py` | Read generated files |
| `submit_code_review` | `coding_loop_tools.py` | Submit review findings |
| `query_spec_docs` | `spec_tools.py` | Look up target-language idioms |

### Finding triggers

- Empty body / stub / hard-coded return → **BLOCKER**.
- Monetary field using float/double instead of decimal type → **BLOCKER**.
- COBOL-style variable names not renamed (`WS-AMT`, `PROC-000`) → **MAJOR**.
- Non-idiomatic patterns (Java raw types, Python mutable defaults, Go ignored errors) → **MAJOR**.
- Uninitialized variable in a conditional branch → **MAJOR**.

---

## Extension process — adding a new language

All languages currently tracked in `_LANG_EXTENSIONS` now have full implementations.
Follow these steps when adding a **new** language.

1. Add entry to `_LANG_EXTENSIONS` in `observer_tools.py`.
2. Implement `_extract_calls_<lang>` and register in `_CALL_EXTRACTORS`.
3. Implement `_parse_<lang>_file` and register in `_DEEP_PARSERS`. Emit `WRITES` edges for
   field-mutation detection to enable co-mutation clustering in Cartographer.
4. Update `OBSERVER_INSTRUCTION` in `observer.py`.
5. Update `CARTOGRAPHER_INSTRUCTION` idiomatic-naming table.
6. Update `ARCHITECT_INSTRUCTION` migration-risk heuristics table.
7. Update `SKEPTICAL_REVIEWER_INSTRUCTION` decimal-type table in `skeptical_reviewer.py`.
8. Update `CODE_WRITER_INSTRUCTION` decimal-type guidance.
9. Update this file.

---

## Known issues

| Issue | Location | Severity | Status |
|---|---|---|---|
| ~~Java deep parser absent~~ | `micro_cosmos/tools/observer_tools.py` | HIGH | ✅ **Fixed** |
| ~~JavaScript/TypeScript deep parsers absent~~ | `micro_cosmos/tools/observer_tools.py` | HIGH | ✅ **Fixed** |
| ~~C# deep parser and call extractor absent~~ | `micro_cosmos/tools/observer_tools.py` | HIGH | ✅ **Fixed** |
| ~~Go deep parser and call extractor absent~~ | `micro_cosmos/tools/observer_tools.py` | HIGH | ✅ **Fixed** — emits WRITES edges |
| ~~Rust deep parser and call extractor absent~~ | `micro_cosmos/tools/observer_tools.py` | HIGH | ✅ **Fixed** — emits WRITES edges |
| ~~Kotlin deep parser and call extractor absent~~ | `micro_cosmos/tools/observer_tools.py` | HIGH | ✅ **Fixed** |
| ~~Scala deep parser and call extractor absent~~ | `micro_cosmos/tools/observer_tools.py` | HIGH | ✅ **Fixed** |
| ~~C / C++ deep parsers and call extractors absent~~ | `micro_cosmos/tools/observer_tools.py` | HIGH | ✅ **Fixed** |
| ~~Ruby deep parser and call extractor absent~~ | `micro_cosmos/tools/observer_tools.py` | MEDIUM | ✅ **Fixed** |
| ~~Swift deep parser and call extractor absent~~ | `micro_cosmos/tools/observer_tools.py` | MEDIUM | ✅ **Fixed** |
| ~~`source_lang="sql"` has no standalone `_LANG_EXTENSIONS` entry~~ | `micro_cosmos/tools/observer_tools.py` | LOW | ✅ **Fixed** — `_parse_sql_file` + `_extract_calls_sql` |
| ~~Terraform has no `_LANG_EXTENSIONS` entry~~ | `micro_cosmos/tools/observer_tools.py` | LOW | ✅ **Fixed** — `_parse_terraform_file` + `_extract_calls_terraform` |
| ~~LLM annotation merging drops mismatched names~~ | `micro_cosmos/tools/observer_tools.py` | MEDIUM | ✅ **Fixed** — FAISS `NodeVectorIndex` cosine fallback (threshold 0.60) |
| `WRITES` edges absent for Java, Python, Kotlin, Scala, C, C++, Ruby, Swift | `micro_cosmos/tools/observer_tools.py` | MEDIUM | **Open** — Go and Rust emit WRITES; remaining languages need field-assignment detection |
| `analyse_table_ownership` uses `CALLS` absence as data-ownership proxy | `micro_cosmos/tools/cartographer_tools.py` | MEDIUM | **Open** — false positives for OOP entry-point classes; should use `WRITES` to `DATA_STRUCTURE` targets |
| Skeptical Reviewer decimal table missing Ruby / Swift / Rust / Scala / C / C++ | `micro_cosmos/agents/skeptical_reviewer.py` | LOW | **Open** — add exact-precision decimal type guidance per language |
