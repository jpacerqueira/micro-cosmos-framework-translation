# How to read `full-app-migration-report.html`

*A guide for anyone who received a `<run-id>_full.zip` file and hasn't used the Micro-Cosmos
tool itself — you don't need an account, a login, or any software beyond a web browser.*

---

## 1. What you were sent

Micro-Cosmos is a tool that analyses a legacy codebase and produces a migration/modernisation
assessment. Someone ran it and sent you the complete output as a single zip file, named something
like:

```
a1b2c3d4_full.zip
```

That zip contains every report, data file, and generated artifact the tool produced for that run.
You don't need to open most of it by hand — one file inside ties everything together:

```
full-app-migration-report.html
```

This guide is about that one file: how to open it, how it's laid out, how to find out what's
being migrated from and to, and how to navigate into the sub-reports it links together.

---

## 2. Opening the report

1. **Unzip** the file you received (double-click it, or right-click → Extract, on any OS).
   This creates a folder named after the run, e.g. `a1b2c3d4/`.
2. Inside it, open the `reports` subfolder.
3. Find and double-click:
   ```
   a1b2c3d4/reports/full-app-migration-report.html
   ```
   It opens directly in your default web browser (Chrome, Edge, Firefox, Safari — any of them
   work). There is nothing to install and nothing to log into — it's a self-contained web page.

If your browser asks for permission to "view local files" or shows a security banner, that's
normal for HTML files opened directly from disk (not from a live website) — you can dismiss it.

---

## 3. What you'll see: the page layout, top to bottom

The report has five parts, always in this order:

| Part | What it is |
|---|---|
| **1. Migration summary** | Three boxes at the very top: **source language**, **target language**, and **run mode**, plus the original source path. See [§4](#4-finding-the-source--target-languages). |
| **2. Status table** | A single table listing everything the tool produced for this run, and whether each item was actually generated. See [§5](#5-reading-the-status-table). |
| **3. Reports** | The full content of every individual analysis report, each in its own collapsible section. See [§6](#6-navigating-the-sub-reports). |
| **4. Kiro.dev Powers** | Reusable AI-assistant configuration files produced as a byproduct (only relevant if your team uses the Kiro.dev tool — safe to ignore otherwise). |
| **5. Claude Code skills** | Same idea, but for Claude Code (Anthropic's coding assistant) — also safe to ignore if you don't use it. |

---

## 4. Finding the source → target languages

Every report is built for exactly one migration: one **source** language/technology going to one
**target** language/technology (e.g. "COBOL → Go", or "Java 8 → Kotlin"). Two ways to find that:

- **Fastest**: look at the three boxes right at the top of the page, under the heading
  "Migration" — they show the source language, the target language, and whether the run used a
  real AI model ("LLM") or a fast rules-based fallback ("Deterministic"). The original codebase's
  file path is printed just below those boxes.
- **In prose, with reasoning**: expand the **Executive summary** or **Migration briefing**
  sub-report (see [§6](#6-navigating-the-sub-reports)) — both describe the same source → target
  migration in narrative form, including *why* that target was chosen, not just the two names.

---

## 5. Reading the status table

Every row shows a **name** and a **status**:

- **Generated** (green) — this item exists and its full content is included further down the
  page. If it's a report, its name is a clickable link.
- **Not yet generated** (grey) — the pipeline run didn't produce this particular item. This is
  often expected, not an error — see [§7](#7-why-some-items-say-not-yet-generated) below.

The table is organised into the same groups as the page sections:

- **HTML reports** — the 13 analysis reports (see the [glossary](#8-what-each-report-actually-tells-you) for what each one tells you).
- **Data artifacts (*.json)** — the raw structured data files the reports were built from. These
  are technical/machine-readable; you generally don't need to open them yourself unless you're
  handing this run to a developer for follow-up.
- **Generated exports** — an OpenAPI specification and a Jira import file, for teams that want to
  feed the findings directly into an API-design tool or a Jira backlog.
- **Kiro.dev Powers / OpenSpec / Claude Code skills** — developer-tooling byproducts, described in
  [§3](#3-what-youll-see-the-page-layout-top-to-bottom).

---

## 6. Navigating the sub-reports

Everything under **Reports**, **Kiro.dev Powers**, and **Claude Code skills** is inside a
collapsed panel, shown like this:

```
▸ Hotspots & coupling
▸ Source security analysis
▸ Migration sprint plan
```

**Click anywhere on a panel's title line to expand it.** Click again to collapse it back down —
this keeps the page manageable instead of showing everything at once.

- For an item marked **Generated**, expanding it reveals the *entire real report* embedded
  directly in the page — you can read, scroll, and (for most reports) use the report's own
  "↓ Download PDF" button inside that section if you want a standalone copy of just that one
  report.
- For an item marked **Not yet generated**, expanding it shows a plain link instead of the report
  itself. Clicking that link won't work from an unzipped, offline copy — it's only clickable when
  viewed live from the Micro-Cosmos web app itself (see [§7](#7-why-some-items-say-not-yet-generated)).
- Kiro Powers and Claude Code skills sections show their raw configuration text directly (in a
  monospace block) rather than a formatted report — that's expected, they're config files, not
  narrative reports.

**Tip:** use your browser's page search (Ctrl+F / Cmd+F) to jump straight to a section by name,
e.g. searching "Security" will take you to both the status-table row and the expandable panel.

---

## 7. Why some items say "Not yet generated"

Not every report is generated automatically for every run — some are only built the first time
someone actually opens them in the live app, or once a particular stage of analysis has produced
enough data. Seeing a few "Not yet generated" rows does **not** mean the run failed. If you need
one of those specific reports, ask whoever sent you the zip to open it once in the live app (or
click "Generate full.zip" again there) and re-send the zip — the missing report will then be
included and fully readable offline.

One more nuance worth knowing: a handful of rows are explicitly labelled "— most recent seam
only" (Seam translation result, Skeptical/Test/Functional review). These reflect only the last
piece of code the tool was actively working on when the run finished, not a full history of every
piece — that's expected and not a data-loss issue.

---

## 8. What each report actually tells you

A plain-English cheat sheet for the 13 reports, in the order they appear on the page:

| Report | What it tells you |
|---|---|
| **Executive summary** | The one-page version — start here if you only read one thing. |
| **Migration briefing** | A narrative walkthrough of the codebase and the proposed migration approach. |
| **Project synthesis** | A deeper technical overview tying the whole codebase together. |
| **Hotspots & coupling** | Which parts of the code are most tangled, most depended-upon, or riskiest to change. |
| **Dead code & waste** | Code that appears unused and could likely be deleted rather than migrated. |
| **Architecture decisions** | The key design choices proposed for the target architecture, with reasoning. |
| **Fitness test stubs** | Automated checks proposed to verify the new code meets architectural rules (e.g. "no floating-point money values"). |
| **Telemetry gap analysis** | Where logging, metrics, and tracing are missing or weak today. |
| **Source security analysis** | Security findings in the *existing* codebase (vulnerabilities, risky patterns, dependency CVEs). |
| **Output security scan** | Security scan results for the *newly generated* code (only present if code generation actually ran). |
| **IR graph** | An interactive, explorable map of the codebase's internal structure — click around to see how pieces connect. |
| **Migration sprint plan** | A proposed breakdown of the migration into work items/sprints. |
| **Build output features** | The functional specifications derived for what the migrated system needs to do. |

---

## 9. Questions?

This report was generated automatically and isn't monitored by anyone — if something looks wrong,
missing, or you have questions about the findings, reply to whoever emailed you the zip rather
than trying to "fix" anything in the file itself.
