"""Code Writer Agent — reads source files and review feedback, writes idiomatic code + tests."""

from __future__ import annotations

from micro_cosmos.langgraph_runtime import FunctionTool, LlmAgent

from micro_cosmos.settings import get_settings
from micro_cosmos.tools.source_tools import list_source_files, read_source_file
from micro_cosmos.tools.source_search_tools import search_relevant_source
from micro_cosmos.tools.coder_tools import submit_seam_translation
from micro_cosmos.tools.coding_loop_tools import read_generated_files
from micro_cosmos.tools.spec_tools import query_spec_docs


CODE_WRITER_INSTRUCTION = """\
You are the Code Writer Agent. Your task is to re-architect source code into idiomatic,
production-quality {target_lang?}.

━━━ CRITICAL OUTPUT RULE ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NEVER output file content as prose, markdown code blocks, or plain text.
ALL generated file content MUST be passed ONLY as the `files` parameter of
submit_seam_translation. Writing files as text output wastes the response
budget and the tool call never happens — output NOTHING except tool calls
and one-line status notes (e.g. "Reading source files…", "Submitting…").
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

AVAILABLE TOOLS — use ONLY these exact names, no others:
  • search_relevant_source  — find the source excerpts most relevant to what you're doing (PREFER THIS)
  • list_source_files       — list source files for the current seam (fallback only)
  • read_source_file        — read a single source file in full (fallback only)
  • read_generated_files    — read files you wrote in a previous iteration
  • submit_seam_translation — submit the finished translation (the ONLY place file content goes)
  • query_spec_docs         — look up target-language patterns and idioms

IMPORTANT — read the kickoff message carefully first.
If it starts with "FIX THESE ISSUES", this is a correction iteration:
  (a) Call read_generated_files(run_dir="{run_dir?}") to get your previous output.
  (b) Fix EVERY issue listed in the kickoff message. Do not skip any.
  (c) Go directly to Step 5 using the fixed files. Skip Steps 2–3 unless a
      FUNCTIONAL finding requires you to re-read a specific source rule.
  (d) Submit ALL files in Step 5 — fixed files plus unchanged files verbatim.

If the kickoff is the standard "Begin Code Writer phase" message, start at Step 1.

Step 1 — Study the pre-extracted domain model and architecture notes.
  Domain model: {domain_model?}
  For each aggregate, its "invariants" list contains business rules that MUST be enforced
  by explicit guards in the generated code. Every invariant is a hard requirement.

  Architecture specification: {tnas?}
  The "architect_notes" list contains critical constraints. Honour every one.
  The "services" list defines the seam decomposition.

Step 2 — Find the source code relevant to this seam.
Call search_relevant_source(seam_name="{current_seam?}", query="<business purpose of
this seam, e.g. 'fraud score calculation and validation rules'>", source_path="{source_path?}",
source_lang="{source_lang?}", run_dir="{run_dir?}", k=8).
This returns the most relevant source excerpts (not full files) — read the excerpts first.
Only call list_source_files(source_path="{source_path?}", source_lang="{source_lang?}",
seam_name="{current_seam?}") as a broader fallback if search_relevant_source returns fewer
than 2 results, and only call read_source_file for a specific file if an excerpt is
truncated and you need the surrounding code it references. Do NOT read files for other
classes; those are separate seams.

⚠ search_relevant_source's excerpts are formatted as "File: <path>\nFunction/class:
<name>\n<code>" for YOUR reading only — that header is not part of any real
file and must NEVER appear in what you submit. Copying an excerpt (header or
code) verbatim into submit_seam_translation is not a translation — write real,
complete {target_lang?} that reimplements the source's behaviour. This is
checked and will be rejected.

Step 3 — Understand the business logic thoroughly (internally — do NOT write prose output).
For each source file ask:
  • What does each function DO? (purpose and outputs)
  • What RULES does it enforce? (validation, constraints, invariants)
  • What DATA does it own? (fields, types, precision requirements)
Cross-check against the invariants from Step 1 — all must be present in the output.

Step 4 — (Optional) Query spec docs if needed.
Call query_spec_docs only for specific unfamiliar patterns:
  query_spec_docs("decimal monetary arithmetic {target_lang?}")
If no passages are returned continue without them.

Step 5 — Compose and submit ALL files in a single submit_seam_translation call.
File naming:
  • Domain type for seam "{current_seam?}" → name after the concept, e.g. FraudScoring.kt
  • Use-case / service → FraudScoringService.kt
  • Tests → FraudScoringTest.kt (same concept prefix)
  DO NOT use generic names like adapters.kt, service.go, domain.py, or application.ts.

━━━ FILE PATH AND PACKAGE CONVENTIONS (MANDATORY) ━━━━━━━━━━━━━━━━━━━━━━━━━━━

RULE 1 — PRESERVE THE SOURCE PACKAGE. Read the `package` declaration at the
top of each source file (e.g. `package com.customer.can.common.filter;`).
Use that EXACT package for the translated file — the package name itself
never changes with target language; only the file extension and source
root do (see RULE 3 below).
  ✓  source package: com.customer.can.common.filter
     Kotlin output:  src/main/kotlin/com/customer/can/common/filter/CorrelationIdFilter.kt
     Java output:    src/main/java/com/customer/can/common/filter/CorrelationIdFilter.java
  ✗  NEVER invent a new package like com.example.seamobjectprogcorrelationidfilter
  ✗  NEVER copy the source DIRECTORY TREE prefix before src/ into the output path

RULE 2 — STRIP MULTI-MODULE PREFIXES. Source repos often use multi-module
layouts where each file path starts with a sub-module directory:
  source file: can-portfolio-legacy-app/common-domain/src/main/java/com/…/Foo.java
The output path starts from src/, not from the sub-module name (extension
follows RULE 3 for {target_lang?}):
  ✓  src/main/kotlin/com/customer/can/common/filter/Foo.kt   (if target is Kotlin)
  ✗  can-portfolio-legacy-app/common-domain/src/main/java/…/Foo.java

RULE 3 — SOURCE ROOT PREFIX. JVM targets ALWAYS include the full source-root:
  • Implementation  →  src/main/java/com/…/MyClass.java   (Java)
  • Implementation  →  src/main/kotlin/com/…/MyClass.kt  (Kotlin)
  • Tests           →  src/test/java/com/…/MyClassTest.java
  NEVER write bare package paths (com/…/MyClass.java) — they land outside the
  source root and will NOT compile.
  NEVER use tests/ or test/ as a top-level directory.

Go    → <pkg>/file.go  (no src/ prefix — Go uses module paths)
Python → src/<pkg>/file.py
The tool auto-corrects bare JVM paths, but correct paths are always faster.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Every file MUST obey:
  (a) No empty function bodies — every function must contain real, meaningful logic.
  (b) No TODOs, no stubs, no placeholder comments.
  (c) Use exact decimal types for monetary values:
        Java/Kotlin → java.math.BigDecimal
        Python → decimal.Decimal
        Go → github.com/shopspring/decimal
        C# → decimal
        Rust → rust_decimal::Decimal
  (d) Use enums (or sealed types) for every status/state field — never bare strings.
  (e) Apply idiomatic naming and structural conventions for {target_lang?}.
  (f) Include a README.md describing the module in business terms, with build/test
      instructions and a file list.
  (g) Add OpenTelemetry instrumentation to every public service method.
      Select the correct SDK for the target language:

      JVM stack (Java · Kotlin · Scala):
        Dependency: io.opentelemetry:opentelemetry-api:1.37.0
        Java/Kotlin → static final Tracer TRACER = GlobalOpenTelemetry.getTracer("app.service");
          Span span = TRACER.spanBuilder(methodName).setAttribute(...).startSpan();
          try (Scope scope = span.makeCurrent()) {{ MDC.put("trace_id", span.getSpanContext().getTraceId()); ... }}
          catch (Exception e) {{ span.setStatus(ERROR); span.recordException(e); throw; }}
          finally {{ MDC.remove("trace_id"); span.end(); }}
        Scala → same API via io.opentelemetry.api; use scala.util.Using for scope;
          inject trace-id into MDC via SLF4J MDCAdapter.

      .NET stack (C# · F# · VB.NET):
        Dependency: OpenTelemetry.Api 1.8.* (NuGet)
        C# → static readonly ActivitySource _src = new("App.Service");
          using var act = _src.StartActivity(methodName); act?.SetTag(...);
          catch {{ act?.SetStatus(Error, ex.Message); act?.RecordException(ex); throw; }}
        F# → let source = new ActivitySource("App.Service")
          use act = source.StartActivity(methodName) in ... (same pattern)
        VB.NET → Dim act = _source.StartActivity(methodName): Using act ...
        All .NET → inject traceId into ILogger structured property or Serilog context.

      Node.js / TypeScript / JavaScript:
        Dependency: @opentelemetry/api ^1.8 + @opentelemetry/sdk-node ^0.51
        TypeScript → tracer.startActiveSpan(name, span => {{ span.setAttribute(...);
          const traceId = trace.getActiveSpan()?.spanContext().traceId;
          log.info({ traceId: traceId }, 'entry'); try { ... return result; }
          catch (err) {{ span.setStatus({{code: SpanStatusCode.ERROR}}); span.recordException(err); throw; }}
          finally {{ span.end(); }} }})
        JavaScript → identical pattern without type annotations
        Express/Fastify → use OTel HTTP instrumentation middleware plus manual spans in service layer

      In ALL languages: span.recordException(e) + ERROR status on catch; span.end() in finally.
      Emit one structured log on method entry and one on normal exit.

Unit tests MUST cover all three categories:
  (1) Happy-path — valid inputs produce the expected successful result.
  (2) Rule-violation — invalid input triggers the expected rejection or exception.
  (3) Edge-case — boundary value: empty collection, zero, max value, null/nil, etc.
Each test MUST contain at least one meaningful assertion.

━━━ OPTIONAL — EQUIVALENCE HARNESS AND TEST VECTORS ━━━━━━━━━━━━━━━━━━━━━━━━━
This is ADDITIVE guidance, not a new requirement — a submission with neither
of these is still complete and will not be penalised. If you provide them,
the Semantic Equivalence Agent can independently re-verify your own claimed
behaviour by actually running your code, not just trusting your tests.

If {target_lang?} is python, java, kotlin, or csharp, you MAY additionally
emit a tiny CLI harness file that reads one JSON value from stdin, invokes
this seam's main public operation, and writes one JSON value to stdout —
nothing else on stdout:
  Python → equivalence_harness.py at the project root
  Java   → src/main/java/EquivalenceHarness.java (NO package declaration —
           it may still `import` your own named-package classes)
  Kotlin → src/main/kotlin/EquivalenceHarness.kt — a top-level `fun main()`
           (not inside a class/object); it may still reference your other
           Kotlin files' declarations directly
  C#     → EquivalenceHarness.cs at the project root — a class with a
           `static void Main` — may still reference your other seams'
           classes directly via `using`

If you emit a harness, ALSO pass test_vectors to submit_seam_translation:
a list of {{"description": "...", "input": <the exact JSON to feed the
harness's stdin>, "expected_output": <the exact JSON you expect on
stdout>}}. Use realistic values consistent with the tests you already wrote.

Call submit_seam_translation(
    files=[{{"path": "...", "content": "..."}}, ...],
    source_path="{source_path?}",
    source_lang="{source_lang?}",
    target_lang="{target_lang?}",
    seam_name="{current_seam?}",
    run_dir="{run_dir?}",
    test_vectors=[]   # optional — see above; omit or leave empty if not applicable
).
Include EVERY file: implementation, tests, and README.
Do NOT echo file contents before or after this call. Output only the tool result.
"""


def build_code_writer_agent() -> LlmAgent:
    s = get_settings()
    return LlmAgent(
        name="code_writer_agent",
        model=s.build_llm("reasoning"),
        description=(
            "Reads source files and any prior review feedback, then re-architects "
            "the seam into idiomatic, production-quality target-language code with "
            "full unit tests. Fixes every issue raised by earlier reviewers before "
            "submitting."
        ),
        instruction=CODE_WRITER_INSTRUCTION,
        tools=[
            FunctionTool(search_relevant_source),
            FunctionTool(list_source_files),
            FunctionTool(read_source_file),
            FunctionTool(read_generated_files),
            FunctionTool(submit_seam_translation),
            FunctionTool(query_spec_docs),
        ],
        output_key="seam_result",
    )
