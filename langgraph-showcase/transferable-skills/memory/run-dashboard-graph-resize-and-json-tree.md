---
name: run-dashboard-graph-resize-and-json-tree
description: Two run.html dashboard UX fixes (2026-08-06) — drag-to-resize the IR property graph panel, and a collapsible JSON tree renderer replacing raw JSON.stringify blobs in the Trace tab — plus ten follow-ups: a margin:auto-on-<main> overflow regression, a left/right panel-order swap (drag math flipped to match), a stale-static-asset-cache false alarm (real fix in static-asset-cache-busting.md), a tab-menu reorder, reusing jsonTreeHtml() for the Artifacts tab too, Expand-all/Collapse-all buttons above it via event delegation, detecting JSON embedded in Trace-tab prose text (fenced or raw/unfenced), a contrasting "active" highlight on the clicked Artifacts button, (2026-08-10) a third flexbox-shrink variant in the Seams tab where overflow-y:auto on one sibling but not the other crushed it into its own tiny nested scrollbar, and (2026-08-10) a fourth variant — a fixed-width flex label with no min-width:0 let a long unbroken service-name word overflow into the adjacent column instead of wrapping — plus ~50% more spacing in gate-summary rows
metadata:
  type: project
---

## The asks

Joao raised two separate, real UX problems on the run dashboard (`run.html`):

1. The IR property graph panel (`.graph-panel`, the cytoscape `#cy` canvas) sits in a
   permanently 50/50 `.dashboard` grid split with the right-hand tabbed panel — no way to
   give the graph more (or less) horizontal room without resizing the whole browser window.
   Panning *inside* the graph already worked (click-drag pans via `userPanningEnabled`, plus
   a wheel handler) — this was specifically about the panel's own fixed width, not panning.
2. The Trace tab (LLM mode) renders tool-call arguments and responses via raw
   `JSON.stringify(...)` — a single, almost-whitespace-free string that overflows the panel
   instead of wrapping, and gives no way to explore a large nested object except an arbitrary
   240/200-char truncation.

Both were planned and confirmed before any file was touched, per this project's
propose-before-implement convention.

## Fix 1 — drag-to-resize graph panel

`.dashboard` (`app.css`) changed from `display: grid; grid-template-columns: 1fr 1fr` to
`display: flex`, with `.graph-panel` given `flex: 0 0 <px>` (a concrete pixel basis, settable
from JS) and `.tab-pane-area` given `flex: 1 1 auto`. Grid's `grid-template-columns` is
awkward to drive dynamically from JS on every mouse move; a flex-basis in pixels is trivial.

A new `<div class="dashboard-resizer" role="separator" aria-orientation="vertical" tabindex="0">`
sits between the two panels in `run.html`. `dashboard.js` wires `mousedown`/`mousemove`/`mouseup`
on it: drag sets `.graph-panel`'s `flex` to a clamped pixel width (`min 320px`, `max = dashboard
width − 320px − resizer width`) and calls `cy.resize()` on every move so the cytoscape canvas
stays correctly sized *without* calling `cy.fit()` mid-drag (would cause jumpy re-centering —
fit stays a deliberate action via the pre-existing "⊡ Fit" button). The chosen width persists
to `localStorage` (`source:graph-panel-width`, same pattern as `base.html`'s existing
`source:debug` toggle) and is restored on page load. Arrow-key resize is wired on the
separator too (24px per keypress) for keyboard accessibility, since it's a `role="separator"`.

## Fix 2 — collapsible JSON tree in the Trace tab

**Root cause of the "disformatted text"**: `appendTrace()` rendered `function_call`/
`function_response` parts via `JSON.stringify(p.args)` / `JSON.stringify(p.response).slice(0,240)`
— compact JSON has almost no whitespace, and `.fcall`/`.fresp` had no `overflow-wrap` rule, so
the browser can't break a long space-free token and it overflows the panel width instead of
wrapping. (`.text` already had `white-space: pre-wrap` and wrapped fine — this was specifically
the JSON-blob spots.)

New `jsonTreeHtml(value, depth)` in `dashboard.js` — recursively renders objects/arrays as
nested `<details class="json-node"><summary>{ N keys }</summary>...</details>` /
`[ N items ]`, primitives as colour-coded `<span class="json-val json-string/number/bool/null">`
(reusing `escapeHtml()` on every key/value, same XSS discipline as the rest of this file — no
new HTML-escaping logic invented). Default: `depth <= 1` renders `open`, deeper nodes start
collapsed — click any `<summary>` to expand. All three call sites in `appendTrace()` now use
it: `function_call` args (depth 0, so the call's own object is expanded), `function_response`
(depth 1, one level shallower by default since responses tend to be larger/less immediately
relevant than the call args that produced them — the old fixed 240-char truncation is gone,
full data is now reachable by expanding), and the top-level no-`parts` fallback (depth 1, same
reasoning, its old 200-char truncation is also gone).

Colours reuse the graph legend's existing palette rather than inventing a new one: strings
blue `#3d6b8a`, numbers/booleans green `#5c8a5c`, null/punctuation `var(--muted)` — same
colours already used for `dot-program`/`dot-procedure` etc. `overflow-wrap: anywhere` added to
`#trace`, `.trace-entry`, `.trace-entry .text`, and the new `.json-tree` as a general safety
net for any other long unbroken token (a hash, a URL) that isn't inside the tree structure.

**Deliberately not touched**: the Diagnostics tab's own `<details class="diag-context/diag-traceback">`
blocks render pre-formatted `JSON.stringify(ctx, null, 2)` inside a `<pre>` already (readable,
if flat) — the same nested-collapsible treatment could apply there later, but it wasn't asked
for this round.

## Verified live

Both features tested against the real running `docker compose` container (not just read/reasoned
about) via a headless Playwright session, reusing an existing run (no new pipeline run needed —
this is pure DOM/CSS behavior, exercised by calling `appendTrace()` directly with a synthetic
payload rather than waiting on a real LLM tool call):

- Resizer: dragging the handle changes `.graph-panel`'s real rendered width (confirmed via
  `getBoundingClientRect()`, not just the CSS value), persists to `localStorage`, and the
  persisted width is restored correctly after a full page reload. Arrow-key resize on the
  focused separator also confirmed (±24px per press).
- JSON tree: a synthetic trace entry with a 4-level-deep nested object, an array of file
  objects, and one deliberately long unbroken string (no spaces, the exact shape that broke
  before) rendered 13 collapsible nodes total; the deepest node (depth > 1) was collapsed by
  default as designed; the trace panel's `scrollWidth` did not exceed its `clientWidth` (i.e.
  the long unbroken string actually wrapped instead of overflowing); clicking a `<summary>`
  correctly toggled that node's open state.

## Files changed

| File | Change |
|---|---|
| `micro_cosmos/web/templates/run.html` | New `.dashboard-resizer` separator div between `.graph-panel` and `.tab-pane-area` |
| `micro_cosmos/web/static/css/app.css` | `.dashboard` grid→flex; `.dashboard-resizer` styles; `.json-tree`/`.json-node`/`.json-key`/`.json-val*` styles; `overflow-wrap: anywhere` on `#trace`/`.trace-entry`/`.text` |
| `micro_cosmos/web/static/js/dashboard.js` | New drag-to-resize IIFE (mousedown/mousemove/mouseup + keyboard + localStorage persistence); new `jsonTreeHtml()` function; `appendTrace()`'s three JSON-dump call sites rewired to use it |

## Lesson

Both fixes were found by reading the actual rendering code rather than guessing from the
symptom description alone — the graph "fixed size" turned out to be a `grid-template-columns:
1fr 1fr` with no drag handle at all (not a JS bug), and the trace "disformatted text" turned out
to be a missing `overflow-wrap` rule interacting with `JSON.stringify`'s near-zero whitespace
output (not a font/layout bug). Planning both against the real current code before proposing a
fix — rather than proposing generic "make it resizable"/"format the JSON" fixes in the
abstract — is what let the plan name exact files, exact CSS properties, and exact function call
sites up front.

## Follow-up, same day: Fix 1 regressed the dashboard layout — not a grid/flex direction bug, a leftover `margin: 0 auto`

Joao reported the tab menu (Gates/Seams/Trace/Processing/Artifacts/Ask/Diagnostics) was no
longer showing beside the IR graph "as it displays now" and asked for it back side by side —
i.e. Fix 1 above broke something. First hypothesis (grid→flex accidentally introduced
`flex-wrap`, or some responsive breakpoint collapsed the row to a column) was checked directly
against the computed styles and **ruled out**: `getComputedStyle(dashboard).flexWrap` was
confirmed `nowrap`, `flexDirection` `row`, and `grep -c "@media"` on the whole stylesheet
returned `0` — no breakpoint exists at all. Headless-browser screenshots at three viewport
widths (900/1024/1280) all showed the two panels at identical `top` values (never stacked).

**The real bug, found by walking the DOM ancestor chain's `getBoundingClientRect().width` one
level at a time**: `body` correctly matched the viewport (`1280px`), but `main` — body's
*direct* flex child — rendered at `2146px`, wider than its own parent. Root cause: the generic
`main { max-width: 1400px; margin: 0 auto; padding: 32px; }` rule (written to horizontally
centre content on the non-run pages) was never fully overridden by `body.run-page main` — that
rule replaces `max-width`/`padding`/adds flex properties, but never touches `margin`, so
`margin: 0 auto` cascaded through untouched. **`margin: auto` on a flex item disables
cross-axis stretch** (a genuine, if obscure, part of the flexbox spec — auto margins on the
cross axis take precedence over `align-items: stretch`) — so instead of `main` stretching to
fill `body`'s width, it shrank-to-fit its own content's preferred (max-content) width, which
cascades down through `.run-shell` → `.dashboard` → `.graph-panel` → the cytoscape canvas
(measured with a `width` attribute of `1015px` at the time), and that intrinsic content width
became `main`'s own effective width, overflowing its parent. Confirmed directly: adding
`min-width: 0` at three levels (`.dashboard`, `body.run-page main`, `.run-shell`) — the more
commonly-cited fix for the sibling "flex items don't shrink below content" gotcha — made
**zero difference** (`main`'s rendered width stayed exactly `2146px` before and after); only
adding an explicit `margin: 0` to `body.run-page main` fixed it, confirming the auto-margin
mechanism was the actual cause, not a `min-width: auto` floor.

Once fixed, `main`'s width tracked the viewport exactly at every tested size (900/1024/1280),
and `.dashboard`'s width became `viewport − .run-shell's horizontal padding` as expected — both
the resizer and the JSON tree were re-verified working correctly afterward (the fix only
touched `margin`/`min-width`, nothing either feature depends on).

**Open question, not resolved**: why this was invisible before Fix 1, if `main`'s leftover
`margin: 0 auto` is pre-existing and unrelated to grid vs. flex. Two live possibilities, neither
confirmed: (a) the bug already existed under the old `grid-template-columns: 1fr 1fr` `.dashboard`
too, just below the threshold of visible overflow, because CSS Grid's own auto-sizing algorithm
for `1fr` tracks under indefinite available space happened to compute a smaller aggregate
min/max-content contribution than flex's row-sum does for the same children — plausible but not
verified against the pre-Fix-1 CSS; (b) the cytoscape canvas's own `1015px` measured width is
itself partly a *product* of the (now-fixed) oversized container at some earlier render pass,
in which case the two bugs partially fed each other. Either way, the fix (explicit `margin: 0`
on `body.run-page main`, plus the defensive `min-width: 0` chain) closes the actual overflow
regardless of which theory is complete — flagged here so a future investigation into "why did
grid not show this" doesn't have to re-derive the ancestor-chain trace from scratch.

### Files changed (this follow-up)

| File | Change |
|---|---|
| `micro_cosmos/web/static/css/app.css` | `body.run-page main` gets explicit `margin: 0` (the actual fix); `min-width: 0` added to `.dashboard`, `body.run-page main`, `.run-shell` (defensive, ruled out as the primary cause but kept as a hardening measure against the same class of bug) |

### Lesson (this follow-up)

`min-width: 0` is the textbook fix for "flex item won't shrink below its content" and was the
first thing tried — but textbook-fix-first without measuring first cost a full round-trip here
(confirmed via a live diagnostic script showing the width genuinely unchanged before vs. after)
before the actual cause (an auto margin disabling stretch, a *different* flexbox gotcha with
the same visible symptom) was found by continuing to walk the ancestor chain rather than
stopping at the first plausible textbook explanation.

## Follow-up 2, same day: panel order swapped — tab menu now left, graph now right

Joao asked for the two panels swapped: the tabbed menu (Gates/Seams/Trace/Processing/
Artifacts/Ask/Diagnostics) should come first, on the left; the IR property graph should be
second, on the right. Purely a DOM-order change in `run.html` — moved the whole `.tab-pane-area`
block to before `.graph-panel`, with `.dashboard-resizer` staying between them. No CSS change
needed (`.dashboard .graph-panel`/`.tab-pane-area` flex rules are class-keyed, not
position-keyed — flex lays out children in DOM order automatically).

**The drag-resize math in `dashboard.js` needed an explicit flip, since it wasn't
position-agnostic.** The mousemove handler computed the graph panel's width as `e.clientX −
dashboard.left` — correct when the graph panel starts at the dashboard's left edge, wrong now
that it's the *right*-hand panel (its width is the distance from the cursor to the dashboard's
*right* edge, i.e. `dashboard.right − e.clientX`). Same for the keyboard handler: previously
`ArrowRight` grew the (left-hand) graph panel; now that it's on the right, `ArrowLeft` grows it
and `ArrowRight` shrinks it (arrow direction still maps to "which way the visual divider moves,"
just with the panel on the other side of it). Verified live: dragging the resizer rightward now
correctly *shrinks* the graph panel (since moving the boundary right hands space to the
left-hand tab area), and `ArrowLeft`/`ArrowRight` grow/shrink it respectively — plus a full
re-run of every earlier check (viewport-overflow fix, JSON tree) to confirm the reorder didn't
regress either.

### Files changed (follow-up 2)

| File | Change |
|---|---|
| `micro_cosmos/web/templates/run.html` | `.tab-pane-area` block moved before `.graph-panel` (with `.dashboard-resizer` between them, unchanged) |
| `micro_cosmos/web/static/js/dashboard.js` | Drag math flipped to anchor off `dashboard.right` instead of `dashboard.left`; arrow-key grow/shrink direction flipped to match |

## Follow-up 3, same day: reported "graph below Gates again" after the swap — root cause was stale browser cache, not a new layout bug, but exposed a real missing cache-control gap

Joao reported the tab menu was again showing below (not beside) the IR graph, right after
follow-up 2 shipped. Checked directly, not assumed: `getComputedStyle` confirmed `flex-wrap:
nowrap`/`flex-direction: row` in the running container, and zero `@media` blocks exist anywhere
— so this was **not** a repeat of the same regression. The actual cause is a genuine
cache-coherency gap: `micro_cosmos/web/app.py` mounted `/static` via plain `StaticFiles(...)`, which
sends only `Last-Modified`/`ETag`, **no `Cache-Control` header at all** — browsers fall back to
heuristic caching for such responses, meaning a previously-fetched `app.css` can be served from
disk cache for a while with zero server round-trip, even after the server-side file has changed
several times. Given how many rapid successive `docker cp`/rebuild cycles happened earlier this
same session, a stale `app.css` sitting alongside the freshly-served `run.html` is a very
plausible real occurrence, not just a theory: the reordered `run.html` now has **3** children in
`.dashboard`, but an `app.css` cached from *before* the grid→flex conversion still has
`grid-template-columns: 1fr 1fr` (2 columns) — a grid container with 2 defined columns and 3
real children auto-wraps the 3rd item to a new row, which is exactly "graph drops below Gates."

See `transferable-skills/memory/static-asset-cache-busting.md` for the fix (a `static_url()`
Jinja global that appends a `?v=<mtime>` cache-busting query param, plus a `Cache-Control:
no-cache` override on the static mount) — kept in its own file since this is an app-wide
infrastructure fix, not specific to the dashboard/graph feature this file otherwise covers.

### Lesson (follow-up 3)

The *symptom* ("graph below Gates") was identical to follow-up 1's regression, but the cause was
completely different (stale cache vs. a real CSS bug) — worth always re-verifying the mechanism
from scratch (`getComputedStyle`, `@media` grep) rather than assuming a repeat report means the
same root cause, especially during a session with many rapid successive deploys of the same
files, which is exactly the condition that makes cache staleness likely in the first place.

## Follow-up 4, same day: tab menu reordered — Gates, Seams, Artifacts, Ask, Processing, Diagnostics, Trace

Joao asked for the tab-bar order changed (his first message listed "diagnostics" twice by
typo — clarified via `AskUserQuestion` before touching anything, rather than guessing which of
the two plausible orders he meant). Final order: Gates, Seams, Artifacts, Ask, Processing,
Diagnostics, Trace (previously Gates, Seams, Trace, Processing, Artifacts, Ask, Diagnostics).
Pure DOM reorder of the `<button class="tab-btn">` elements in `run.html`'s `.tab-bar`, plus the
corresponding `.tab-panel` divs moved to match (not functionally required — panels are shown/
hidden by `data-tab`/id lookup in `dashboard.js`, not DOM order — but kept in sync for anyone
reading the template). Verified live: clicked through all 7 tabs via Playwright, confirmed each
button's own panel activates correctly in the new order.

## Follow-up 5, same day: the Artifacts tab's raw JSON dump also converted to the same collapsible tree

Joao asked for every Artifacts-tab button (IR graph, Bounded contexts, Seam report, Work
streams, TNAS · fitness suite, Security report, Input/Output Trivy scan, PR review report) to
render like a browser's native JSON viewer too — same ask as the original Trace-tab fix, just a
different tab. `fetchAndShowArtifact()` (`dashboard.js`) previously set
`artifactView.textContent = JSON.stringify(data, null, 2)` — a flat, non-interactive pretty-print
inside a `<pre id="artifact-view">`. Reused the exact same `jsonTreeHtml()` function built for
the Trace tab rather than writing a second renderer: `artifactView.innerHTML =
jsonTreeHtml(data, 0)`. Changed `#artifact-view` from `<pre>` to `<div>` in `run.html` (a `<pre>`
preserves all whitespace, which would have visually broken the indentation of the generated
`<details>`/`<div>` tree markup) and added `font-family: var(--mono)` + `padding: 12px` directly
to `.artifact-view` in CSS to preserve the monospace look `<pre>` used to provide for free.
Error/not-yet-available messages still use `textContent` (plain text, unaffected).

**Verified live** across 4 real artifacts (`ir_graph`, `bounded_context_map`, `seam`,
`work_streams`) on an existing run: each rendered as a `<div>` (not `<pre>`) containing multiple
`.json-node`/`<details>` elements with no raw escaped-JSON text visible, and clicking a
`<summary>` correctly toggled that node open/closed — plus a screenshot confirming the visual
result matches a native browser JSON viewer (indentation, `▶`/`▼` disclosure triangles, `{ N
keys }`/`[ N items ]` counts).

### Files changed (follow-ups 4 & 5)

| File | Change |
|---|---|
| `micro_cosmos/web/templates/run.html` | Tab-bar buttons and `.tab-panel` divs reordered; `#artifact-view` changed from `<pre>` to `<div>` |
| `micro_cosmos/web/static/css/app.css` | `.artifact-view` gets explicit `font-family: var(--mono)` + `padding: 12px` (lost `<pre>`'s free defaults) |
| `micro_cosmos/web/static/js/dashboard.js` | `fetchAndShowArtifact()`'s success path now renders via `jsonTreeHtml()` instead of `JSON.stringify` |

### Lesson (follow-up 5)

Building `jsonTreeHtml()` as a standalone function (not inlined into `appendTrace()`) the first
time paid off immediately — extending it to a second, unrelated tab was a 2-line change (swap
the render call, adjust the container tag/CSS) instead of writing a second tree renderer.

## Follow-up 6, same day: "Expand all" / "Collapse all" buttons above the Artifacts JSON tree

Joao asked for two buttons above the JSON tree in the Artifacts tab — one to expand every node,
one to collapse every node — while still letting individual sections be toggled manually
afterward, independent of the bulk action.

Added a `.json-tree-controls` block (two `<button data-tree-action="expand|collapse">`, styled
identically to the existing `.graph-level-btn`/`.graph-fit-btn` toolbar buttons — reused the
class list rather than inventing a new button style) rendered above the `.json-tree` div in
`fetchAndShowArtifact()`. A **single delegated click listener on `artifactView` itself** (added
once, outside the fetch function) handles both buttons: `artifactView.querySelectorAll(".json-node")`
+ set `.open` on each. Delegation matters here specifically because `artifactView.innerHTML` is
replaced wholesale on every artifact fetch — a listener attached to the buttons directly would
be destroyed and need re-attaching each time; a listener on the stable parent survives every
re-render for free.

**Verified live**: 31 total `.json-node`s on a real artifact (`ir_graph`), 5 open by default
(the existing `depth <= 1` rule); "Expand all" → 31/31 open; "Collapse all" → 0 open; manually
clicking one `<summary>` after "Collapse all" → exactly 1 open; expanding all then manually
collapsing one → exactly 30 remain open (confirms the bulk actions and per-node manual toggling
don't interfere with each other — clicking a native `<details>` element's `open` property is
just a boolean flip, unaffected by how it was last set).

### Files changed (follow-up 6)

| File | Change |
|---|---|
| `micro_cosmos/web/static/css/app.css` | `.json-tree-btn` added to the existing `.graph-level-btn`/`.graph-fit-btn` rule; new `.json-tree-controls` layout rule |
| `micro_cosmos/web/static/js/dashboard.js` | `fetchAndShowArtifact()` renders the two buttons above `.json-tree`; new delegated click listener on `artifactView` |

### Lesson (follow-up 6)

Event delegation on the stable container (rather than the buttons that get destroyed and
recreated on every fetch) is the same underlying pattern that already made `jsonTreeHtml()`
itself easy to extend to a second tab — this codebase's dynamic content areas (`artifactView`,
`trace`) are all replaced wholesale on update, so any control living inside them needs a
delegated listener on the container, not a direct one on the control.

## Follow-up 7, same day: embedded JSON inside Trace-tab prose text also gets the collapsible tree

Joao noticed some agentic/deterministic Trace entries print JSON that never got the nesting
treatment — specifically `text`-type trace parts (the agent's own reasoning/output), as opposed
to the `function_call`/`function_response` parts that already used `jsonTreeHtml()`. Real
examples from a live Cartographer and Architect run: an agent emits prose plus a fenced
` ```json ... ``` ` block, or — the harder case, found on the *second* example he gave — prose
followed by **raw, unfenced JSON** (the model's own stated intent was "no markdown fences," and
it actually followed that instruction this time, unlike the fenced example).

New `extractJsonFromText(text)` mirrors `app.py`'s existing `_extract_json()` (same fenced-block
regex) but extends it for the unfenced-prose-then-JSON shape, which `_extract_json()` doesn't
need to handle (it's only ever called on text already known to be JSON-ish). Tries, in order:
(1) the whole text is already valid JSON — cheapest, covers pure-JSON-no-prose; (2) a fenced
` ```json ``` ` block, prose before/after kept as plain text; (3) **prose followed by unfenced
JSON** — tries every `{`/`[` character position in the text as a possible JSON start, taking the
first one that parses cleanly through to the end of the string. Returns `null` (unchanged plain
text rendering) if nothing matches, so genuine prose with no JSON anywhere is completely
unaffected.

**Real gap caught by testing the user's second example, not assumed correct from the first**:
the initial version of this fix only implemented (1)+(2) above — "try the fenced block, else try
the whole text as JSON." That handles pure JSON and fenced-JSON-with-prose, but not
prose-followed-by-raw-JSON specifically, which is exactly the shape of the Architect example —
a multi-line bullet list of constraints, then a bare `{` starting the real JSON with no fence at
all. Caught by testing against that second real example before committing, not by reasoning
about the regex in the abstract.

**Verified live**, all four shapes, against the real run (`9dcf6f50`) via `appendTrace()` called
directly with each real text: fenced JSON + prose (Cartographer bounded-context-map output, 9
tree nodes, prose kept separate, no leakage into it); unfenced pure JSON (no prose at all);
unfenced JSON preceded by a markdown bullet list (Architect TNAS output, 7 tree nodes, prose
kept separate); and a plain-prose-only regression check (no JSON anywhere → renders exactly as
before, `hasJsonTree: false`) to confirm the new detection never fires on genuine prose.

### Files changed (follow-up 7)

| File | Change |
|---|---|
| `micro_cosmos/web/static/js/dashboard.js` | New `extractJsonFromText()`; `appendTrace()`'s `text`-part branch now calls it and renders any detected JSON via the existing `jsonTreeHtml()`, falling back to the original plain-text rendering when nothing is detected |

### Lesson (follow-up 7)

The user's *second* example wasn't a duplicate confirmation of the first — it was a different
real shape (no fence at all) that the first version of the fix genuinely didn't handle. Treating
each new example as a potential new test case rather than "more of the same" is what caught this
before it shipped incomplete.

## Follow-up 8, same day: the clicked Artifacts button now shows a contrasting "active" highlight

Joao asked: when you click an artifact button (e.g. "Input Trivy scan"), give it a contrasting
colour so it's visually clear which report is currently showing below — there was no such
indicator at all before, only a separate `.ready` class (green-ish, meaning "this artifact has
been generated/loaded at least once," unrelated to *which one is currently selected*).

New `.art-btn.active` rule reuses the exact filled-contrast treatment already used for
`.graph-level-btn.active` (ink background, light text, ink border) rather than inventing a new
colour — placed *after* `.art-btn.ready` in the stylesheet so its background/colour wins when a
button is both `.ready` and `.active` at once (a real, common case — the artifact you just
clicked has, by definition, just been loaded). Click handler now clears `.active` from every
`.art-btn` before adding it to the one just clicked — mutually exclusive, same pattern as a tab.

**Verified live**: clicking `ir_graph` highlights only it; clicking `trivy_report` next moves
the highlight there and `ir_graph` correctly reverts to its normal background; the doubly-classed
button (`"art-btn active ready"`) resolves to the `.active` ink-background/white-text style, not
the `.ready` green one — confirmed via `getComputedStyle`, not just class-list inspection. Plus a
screenshot showing "INPUT TRIVY SCAN" solid-highlighted against the other buttons.

### Files changed (follow-up 8)

| File | Change |
|---|---|
| `micro_cosmos/web/static/css/app.css` | New `.art-btn.active`/`.art-btn.active:hover` rule |
| `micro_cosmos/web/static/js/dashboard.js` | `.art-btn` click handler now clears `.active` from all artifact buttons before adding it to the clicked one |

### Lesson (follow-up 8)

Checking `getComputedStyle` rather than just `element.className` mattered here — two classes
both being present (`active ready`) doesn't tell you which one's styles actually render; only
checking the resolved style (or deliberately controlling source order and verifying it) confirms
the *intended* one wins.

## Follow-up 9 (2026-08-10): a third variant of the flexbox-shrink gotcha, in the new Seams tab

Joao shared a screenshot of the Seams tab (source seams + the new [[target-architecture-seams-panel]]
section below them) and asked for all three visible groupings — the source-seam stream cards, the
"Target architecture & features" heading, and its "Target Features" list — to sit at the same
level with **one shared scrollbar**, not behave inconsistently.

Live Playwright measurement against the exact run in the screenshot (not a guess) found: `#seam-feed`
(source seams) had `scrollHeight: 179px` but `clientHeight: 93px` — squeezed into its own tiny
independently-scrolling box — while its sibling `.seam-target-section` (no overflow override) sat
at its full natural `946px`, completely unsquashed. Both are flex-column children of `#tab-seams`
(`.tab-panel`), which already had the correct, single, bounded `overflow-y: auto` — the intended
one-scrollbar-for-the-whole-tab container.

**The precise mechanism (third variant of a now-three-times-seen class of bug)**: per the flexbox
spec, an item's *automatic* minimum size — used when flex-shrink needs to squeeze it — is `0` if
the item's own `overflow` is anything other than `visible`, but stays content-based
(`min-height: auto`, refuses to shrink below content) if `overflow` is `visible`. `#seam-feed` had
`overflow-y: auto` set on it directly; `.seam-target-section` didn't. So when the combined content
didn't fit, **all the shrink pressure landed on `#seam-feed` alone** — crushed down to whatever was
left after its sibling took its full natural height, growing its own nested scrollbar to
compensate. This is the third distinct flexbox pitfall found on this exact page (`margin: auto`
disabling stretch in follow-up 1; the standard `min-width: auto` "won't shrink below content"
false lead in that same investigation; now this one) — worth keeping a running list, since each
looks like "the same overflow bug" at a glance but has a genuinely different cause each time.

**Fix**: removed `overflow-y: auto` from `.tab-seams #seam-feed` (kept its `padding`). Falling
back to the default `visible` makes it behave like `.seam-target-section` — both flow naturally,
and `#tab-seams`'s already-correct `overflow-y: auto` becomes the single scroll owner for all
three sections together.

**Verified live in both modes** (deterministic: `examples/java-springboot-legacy-app`, 23 seams;
LLM mode: confirmed identical CSS structure — `run.html`'s Seams-tab markup has no `skip_llm`
branching, so this was expected but checked, not assumed): after the fix, `#seam-feed` and
`.seam-target-section` both report `scrollHeight === clientHeight` (no independent squeeze on
either), while the parent `#tab-seams` correctly reports `scrollHeight > clientHeight` (it's now
the one thing that actually needs to scroll). Scrolling `#tab-seams` by a fixed offset moved both
sections' bounding-rect positions by the *identical* amount — confirming they now move together
under one shared scrollbar, not two independent regions.

### Files changed (follow-up 9)

| File | Change |
|---|---|
| `micro_cosmos/web/static/css/app.css` | Removed `overflow-y: auto` from `.tab-seams #seam-feed` |

## Follow-up 10 (2026-08-10): Gate summary rows too tight, plus a real label-overflow collision

Joao shared a screenshot of the Gate 3 ("TNAS & migration plan") panel asking for ~50% more space
between service name, risk badge, and description. Investigating `gsKV()`/`buildGateSummary()`
(`dashboard.js`) and the `.gs-*` rules (`app.css`) surfaced a second, more serious issue in the
same screenshot, not just tightness: `.gs-label` (the fixed `width: 140px` service-name column)
had no wrap rule. A service ID like `FRAUDPERSISTENCESERVICE` is a single unbroken word — with no
`overflow-wrap` set, the browser let it overflow straight past the 140px box into the adjacent
risk/value column instead of wrapping, producing exactly the screenshot's
`FRAUDPERSISTENCESERVICEMEDIUM risk` collision (shorter names like `FRAUDSCORINGSERVICE`
happened to fit, which is why the same screenshot looked inconsistent row to row — not every row
was actually broken, only the ones with long enough identifiers).

**This is the fourth variant of the same "flex item won't shrink/wrap below its content" family
already tracked in this file** (follow-up 1's `margin: auto`; follow-up 9's asymmetric
`overflow-y` shrink pressure) — here the mechanism is the flex item's *automatic minimum width*
defaulting to the full unbroken word's width regardless of the declared `width: 140px`, unless
`min-width: 0` overrides it. Fixed with `min-width: 0` + `overflow-wrap: break-word` together:
`min-width: 0` lets the box actually shrink to 140px, and `overflow-wrap` then lets the long word
wrap within it instead of spilling over.

Fixed both the collision and the general spacing together, in the shared `.gs-*` block — used by
every gate's summary panel (Gate 1 through Gate 5), not just Gate 3:
- `.gs-label`: `min-width: 0` + `overflow-wrap: break-word` (the real fix, above).
- `.gs-row`: `gap: 12px → 18px`, `padding: 3px 0 → 5px 0` (~50% more, per the request).
- `.gs-note` / `.gs-list`: vertical margins increased ~50% to match; left-margin bumped
  `152px → 158px` to stay aligned under the value column now that the row gap grew from 12→18.

Joao verified this one live himself rather than a scripted Playwright check.

### Files changed (follow-up 10)

| File | Change |
|---|---|
| `micro_cosmos/web/static/css/app.css` | `.gs-label` gets `min-width: 0` + `overflow-wrap: break-word`; `.gs-row`/`.gs-note`/`.gs-list` spacing increased ~50% |
