# Run explainability — plain-English + 3-slide summaries

`../.claude/commands/explain-run.md` (`/explain-run <run-id>`) turns a
run's technical artifacts into two stakeholder-facing deliverables:

1. A plain-English narrative (a few paragraphs, posted directly in chat)
2. A 1-2-3 slide markdown summary (Slide 1: What & Why, Slide 2: What We
   Found, Slide 3: Status & Next Steps)

Both are also saved to `runs/<run-id>/reports/plain-english-summary.md`
and `runs/<run-id>/reports/three-slide-summary.md`.

**Deliberately complements, not duplicates, `scripts/generate_exec_summary.js`**
(→ `reports/executive-summary.html`), which already produces a structured
one-page HTML executive summary from the same artifact set
(`run_meta.json`, `ir_graph.json`, `bounded_context_map.json`,
`seam.json`, `work_streams.json`, `tnas.json`, `security_report.json`).
The existing script covers "a report to open"; `/explain-run` covers "the
story in two minutes" — conversational, ultra-condensed, and generated
directly in a Claude Code session rather than requiring the HTML report
to be built and opened first.

**Design rule, not just a formatting preference**: every internal term
must be translated to its business meaning on first use — "seam" → "a
clean line where the old and new systems can be safely split/connected,"
"gate" → "a human approval checkpoint," etc. The command file itself
carries worked examples of this translation rather than leaving it to
inference, since the failure mode here isn't a missing artifact, it's
silently reverting to internal jargon a non-technical reader won't
recognize.

If a future request asks for other stakeholder-facing output formats
(e.g. a longer written report, a different slide count, audience-specific
variants), extend `/explain-run` with an optional `$ARGUMENTS` flag rather
than creating a parallel command — the artifact-reading and
jargon-translation logic should stay in one place.
