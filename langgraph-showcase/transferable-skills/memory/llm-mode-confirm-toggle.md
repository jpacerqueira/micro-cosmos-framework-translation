---
name: llm-mode-confirm-toggle
description: New-run form now confirms before starting an LLM-mode run — inline panel inside the run/launch box, not a page-covering modal; a real document.body-in-<head> bug was found and fixed along the way (2026-08-06)
metadata:
  type: project
---

## The ask

Joao wanted a specific piece of friction added to the new-run flow: when the
`skip_llm` mode toggle is left in LLM mode and the user clicks "start run",
confirm first ("deterministic is faster and uses fewer resources") rather
than starting immediately. Deterministic mode should submit with no prompt,
unchanged.

## Where this lives

Both `index.html` (home page) and `demo.html` (`/demo`) render the identical
`skip_llm` checkbox markup and both `hx-post="/runs"` declaratively via
htmx — **neither page has a custom JS submit handler**, confirmed by grep
before writing any code. `dashboard.js` (the app's one existing large JS
file) is only loaded on `run.html`, not on either new-run page, so it plays
no role here. There is no pre-existing confirm/modal/dialog convention
anywhere in this codebase (grepped for `confirm(`, `modal`, `dialog` across
every template/JS/CSS file — zero hits) — this is the first one.

## Mechanism: htmx's `htmx:confirm` event, not a custom submit handler

Rather than writing a `submit` listener that fights htmx's own request
lifecycle, this hooks htmx's documented `htmx:confirm` event (present since
htmx 1.9, and confirmed present in the vendored 2.0.3): call
`evt.preventDefault()`, then conditionally call `evt.detail.issueRequest(true)`
later once the user has actually decided. This is the idiomatic htmx pattern
for "sometimes confirm, sometimes don't" — a static `hx-confirm="..."`
attribute can't express "only when this other checkbox is unchecked."

## Real bug found and fixed: `document.body` doesn't exist yet in a `<head>` script

The new script tag was added to `base.html`'s `<head>`, right after
`htmx.min.js`. First version of `run-confirm.js` did
`document.body.addEventListener("htmx:confirm", ...)` at the top level of
the file. **This would have thrown immediately and silently** —
`document.body` is `null` while a classic (non-`defer`, non-`async`) script
in `<head>` is executing, since the browser hasn't parsed `<body>` yet. The
listener would never attach; htmx would just proceed with its default
(no-op) confirm behavior on every submit, and nothing about the failure
would be visible without opening the browser console. Caught before ever
shipping, not live — spotted by re-reading the script placement while
writing the second version, not by testing the first one, since testing was
interrupted mid-flow this session (see "Session note" below). Fixed by
listening on `document` instead of `document.body` — `document` always
exists, and htmx's custom events bubble to it the same way, so no other
change was needed. Worth remembering for any future `<head>`-loaded script
in this app: don't touch `document.body` at top-level scope.

## Design iteration: full-page modal → inline panel inside the existing box

First implementation (approved and shipped initially): a single
page-covering `.modal-overlay` + `.modal-panel`, added once to `base.html`,
shown/hidden via the `htmx:confirm` handler. Verified working end-to-end via
a real headless-browser (Playwright) session against the live
`docker compose` container: modal appears on LLM-mode submit, Cancel
aborts (no request sent, no navigation), Continue proceeds (real request
sent, run created), deterministic-mode submit shows no modal at all.

**Then explicitly changed**: Joao asked for the same message/behavior but
rendered *inside* the existing box — the "Launch analysis" panel on
`/demo`, the run-form panel on `/` — not as a screen-covering overlay.
Removed the single shared `#llm-confirm-overlay` from `base.html` entirely;
the confirm block (`h3.llm-confirm-title` + `p.llm-confirm-text` +
`.llm-confirm-actions` with Cancel/Continue buttons) is now duplicated as
the last child of each page's own `<form>`, right after its submit button —
consistent with this codebase's existing convention of duplicating the
`skip_llm` toggle markup itself between the two templates, rather than a
shared Jinja include. `run-confirm.js` now does `form.querySelector(".llm-confirm-inline")`
(scoped to the triggering form) instead of a single global `#id` lookup,
and additionally hides the real submit button while the inline panel is
shown (restored on Cancel) so there's no ambiguity about which button does
what while it's up.

## Verified live, both pages, both design iterations

Real headless-browser (Playwright) sessions against the actual running
`docker compose` container (not just read the code) for the final inline
version: on `/`, unchecking the toggle and submitting shows the panel
inline inside `.run-form` (confirmed via `getBoundingClientRect()` that
it's not a full-viewport element), hides the submit button while shown,
Cancel restores both and leaves the URL unchanged, checking the toggle
(deterministic) submits with no panel at all. On `/demo`, the same panel
renders as a descendant of `.demo-launch` (confirmed via `Node.contains()`),
Cancel behaves identically. Confirming ("Continue with LLM mode") was also
exercised once on `/` earlier in the session and did start a real run —
cleaned up afterward (test artifacts only, matched by their distinctive
`source_path`/`target_lang` combination; genuine unrelated runs already in
`runs/` were left untouched after checking their `run_meta.json` first).

**Pre-existing, unrelated noise observed during every test run, not a
regression from this change**: every page load throws
`Cannot read properties of undefined (reading 'layoutBase')` in the
console — traced to the `cytoscape`/`dagre` vendor scripts that `base.html`
loads on every page regardless of whether that page has a graph container
(`index.html`/`demo.html` don't). Not investigated further or fixed here —
flagged so a future session doesn't mistake it for something this change
introduced.

## Session note: an in-progress background run must not have its directory deleted from under it

While cleaning up a test-created run mid-verification, deleting
`runs/<id>/` while that run's async pipeline task was still actively
writing artifacts caused a tight `FileNotFoundError` retry loop
(`_save_artifact`/`produce_seam_report` failing repeatedly against the
now-missing directory) that appears to have driven the container to being
killed (exit 137) shortly after. No delete-run endpoint exists in
`app.py` — cleanup of stray test runs is filesystem-only. Lesson: check
`docker stats`/container CPU is idle (or that the run has actually reached
a terminal phase) before deleting a run's directory that a live session
might still be writing to, not just that its `run_meta.json` matches a
test fixture's source path.

## Files changed

| File | Change |
|---|---|
| `micro_cosmos/web/static/js/run-confirm.js` | New file — `htmx:confirm` handler, scoped to the triggering form's own `.llm-confirm-inline` panel |
| `micro_cosmos/web/templates/base.html` | `<script src="/static/js/run-confirm.js">` added in `<head>`; the (now-removed) global overlay markup lived here briefly during the first design iteration |
| `micro_cosmos/web/templates/index.html` | `.llm-confirm-inline` block added as the last child of `.run-form`, after the submit button |
| `micro_cosmos/web/templates/demo.html` | Same block added as the last child of `#demo-form`, inside `.demo-launch` |
| `micro_cosmos/web/static/css/app.css` | `.llm-confirm-inline`/`.llm-confirm-title`/`.llm-confirm-text`/`.llm-confirm-actions` (inline panel, sage background + accent left-border, matching `.started-card`'s existing look) and reusable `.modal-btn`/`.modal-btn-primary`/`.modal-btn-secondary` button styles |

## Lesson

Two iterations, both real: first shipped a technically-correct, tested
overlay; the second, explicit ask ("inside that box, not a full-screen
thing") was a genuine UX preference, not a bug in the first version — worth
remembering that "propose before implementing" doesn't mean the first
approved design is necessarily final once the person actually sees it
running. Also: the `document.body`-in-`<head>` bug is the kind of thing
that only surfaces by actually running the code in a browser and checking
the console, or by re-reading script placement carefully — a pure code
review of the handler logic alone (which was itself correct) would not
have caught it.
