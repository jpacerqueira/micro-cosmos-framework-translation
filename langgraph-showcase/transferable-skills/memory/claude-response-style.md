---
name: claude-response-style
description: How Claude Code should behave on this project — propose before implement, terse, precise
metadata:
  type: feedback
---

**Always propose before implementing.** On any feature or bug fix that touches more than one file, write the proposal (what changes, where, why) as a table or structured summary. Wait for "go" / "yes apply" before editing files.

**Why:** The owner manages the design and wants to approve architectural decisions before they land in the codebase.

---

**No trailing summaries.** Do not add a bullet-point recap of everything just done at the end of a response. The diff and commit message carry that information.

**How to apply:** End with one sentence on what changed and what's next, if anything.

---

**Technical precision over reassurance.** When asked for a diagnostic analysis, give the root cause, the exact file/line, and the data-path proof.

**How to apply:** State "the root cause is X" not "it seems like X might be causing this". Reserve hedging for genuinely ambiguous cases.

---

**Commit message style:** `Type: short description (YYYY-MM-DD)` — e.g. `Feature:`, `Bug fix:`, `Fix + Feature:`, `Docs + Feature:`. Always use a HEREDOC for the commit message body.
