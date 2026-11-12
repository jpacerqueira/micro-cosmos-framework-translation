# Explain a Micro-Cosmos run in plain English

Turns a run's technical artifacts into (1) a plain-English narrative of
what the pipeline did and why, and (2) a 1-2-3 slide-style markdown
summary — for a stakeholder who won't read HTML reports, JSON, or terms
like "seam," "bounded context," or "TNAS."

`$ARGUMENTS` = run ID (e.g. `1821ae7d`)

**This complements, not duplicates, `scripts/generate_exec_summary.js`**
(`reports/executive-summary.html`) — that script already produces a
structured one-page HTML summary for non-technical stakeholders. This
command reads the *same* artifacts but produces two different, lighter
deliverables: a conversational narrative (posted directly in this chat)
and an ultra-condensed 3-slide version — useful when someone wants the
story in two minutes, not a report to open. If `executive-summary.html`
already exists for this run, skim it first — reuse its framing rather
than re-deriving language choices from scratch.

## Steps

1. Read whichever of these exist under `runs/$ARGUMENTS/` (same set
   `generate_exec_summary.js` and `/debug-run` already read — skip
   anything missing, don't error):
   `run_meta.json`, `ir_graph.json`, `bounded_context_map.json`,
   `seam.json`, `work_streams.json`, `tnas.json`, `security_report.json`,
   `feature_specs.json`, `review_report.json`.
2. Identify: source language/framework → target language/framework, the
   project's size/shape (from `ir_graph.json`'s node/edge counts), how
   many independent pieces of work it was broken into (`work_streams.json`
   — translate "work streams" as "independent chunks of work a team could
   parallelize"), what architectural boundaries were found
   (`bounded_context_map.json`/`seam.json` — translate "seam" as "a clean
   line where the old and new systems can be safely split/connected"),
   what security issues were found and their severity
   (`security_report.json`), and current pipeline status (which gates are
   approved/pending — check the run's live state via the web UI or
   `micro_cosmos/gates/__init__.py`'s `GATE_DEFINITIONS` for gate names/order).
3. Translate every technical term on first use — a stakeholder shouldn't
   need to know what a "gate," "TNAS," "IR graph," or "fitness function"
   is. State the *business* meaning: e.g. "Gate 3 (Architecture Review)"
   → "a human checkpoint where an engineering lead signs off on the
   proposed target architecture before any code is written."
4. Produce two outputs — print both directly in this response, and also
   save them to `runs/$ARGUMENTS/reports/plain-english-summary.md` and
   `runs/$ARGUMENTS/reports/three-slide-summary.md` so they persist
   alongside the run's other reports:

   **A. Plain-English narrative** (a few short paragraphs): what this
   project is, why it's being translated, what the pipeline found, what
   decisions were made and why, what's flagged as risky, and where things
   stand right now. Write it the way you'd explain the work to a project
   sponsor who has no engineering background — plain sentences, no
   bullet-jargon-lists of internal artifact names.

   **B. Three-slide markdown summary** — exactly this shape, nothing more:
   ```markdown
   ## Slide 1 — What & Why
   [1-3 sentences: what's being translated, from what, to what, and why]

   ## Slide 2 — What We Found
   [3-5 bullets, plain English: architecture shape, key risks/security
   findings, biggest surprises — no artifact/field names]

   ## Slide 3 — Status & Next Steps
   [Where the run stands now (which approvals are done/pending), and
   what happens next]
   ```
   Keep each slide short enough to read in under 20 seconds — this is a
   high-level summary, not a report. If a section has nothing meaningful
   to say yet (e.g. run hasn't reached Security phase), say so plainly
   ("Security review hasn't run yet") rather than inventing content.

## Report

After producing both, state in one line which artifacts were available
vs. missing (so the reader knows how complete this run's picture is).
