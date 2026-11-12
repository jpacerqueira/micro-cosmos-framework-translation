---
name: static-asset-cache-busting
description: /static/* had no Cache-Control header at all, letting browsers heuristically cache a stale app.css/dashboard.js across rebuilds — fixed with a static_url() cache-busting Jinja global + an explicit no-cache override (2026-08-06)
metadata:
  type: project
---

## How this was found

Not a planned fix — found while investigating a *reported* dashboard-layout regression (see
`transferable-skills/memory/run-dashboard-graph-resize-and-json-tree.md`'s "Follow-up 3"). Joao
reported the run-dashboard's IR property graph panel had dropped below the tab menu again,
right after a panel-order swap had just shipped and been verified live. Re-checking the swap
itself (`getComputedStyle` on the live container, grepping for `@media`) ruled out a repeat of
the actual layout bug — `flex-direction: row`/`flex-wrap: nowrap` were both confirmed correct,
and zero media queries exist anywhere in the stylesheet. That pointed at a *different*
explanation for the same symptom.

## Root cause

`micro_cosmos/web/app.py` mounted static assets with plain `StaticFiles(directory=...)`
(`app.mount("/static", StaticFiles(...), name="static")`). Starlette's `StaticFiles` sends
`Last-Modified`/`ETag` on its own, but **no `Cache-Control` header** — confirmed directly via
`curl -sI`, not assumed. With no explicit caching policy, browsers fall back to **heuristic
caching** (RFC 7234 §4.2.2): a previously-fetched asset can be served straight from disk cache,
with zero server round-trip, for a computed "freshness" window — even though the file on disk
has since changed.

This session did many rapid, successive `docker cp` + full-rebuild cycles against `app.css`/
`run.html`/`dashboard.js` in a short span. That's exactly the condition under which a browser
could plausibly still be holding an `app.css` from a few edits ago while freshly fetching the
*current* `run.html` on each navigation (HTML documents are typically not cached the same way,
if at all) — a genuine stale-CSS + fresh-HTML mismatch, not a repeat of the layout bug. Concretely:
the current `run.html`'s `.dashboard` has **3** children (tab-pane-area, the resizer div,
graph-panel); an `app.css` cached from *before* the earlier grid→flex conversion still has
`grid-template-columns: 1fr 1fr` — only 2 defined columns. A grid container with 2 columns and
3 real children auto-wraps the 3rd item to a new row, landing the graph panel directly below
the tab-pane-area's first (Gates) content — reproducing the exact reported symptom, just via a
different mechanism than either of the two real dashboard bugs fixed earlier the same day.

## Fix

Two layers, deliberately not just one:

1. **`static_url(path)`** — a new function in `micro_cosmos/web/app.py`, registered as a Jinja
   global (`TEMPLATES.env.globals["static_url"] = static_url`). Appends the referenced file's
   own mtime as a `?v=<mtime>` query param: `static_url("css/app.css")` →
   `/static/css/app.css?v=1754499739`. Every `/static/...` reference in `base.html`, `login.html`,
   and `run.html` (the only three templates that reference static assets directly) now goes
   through it. This is the durable fix: any future change to a static file automatically changes
   its URL, so a browser can never serve a stale copy regardless of *any* caching policy in
   between — cache-busting via the URL itself, not via headers.
2. **`CacheControlledStaticFiles`** — a `StaticFiles` subclass overriding `get_response()` to
   set `Cache-Control: no-cache` on every response (forces revalidation — a cheap 304 if the
   `ETag` still matches — rather than ever serving purely from browser heuristic cache with no
   round-trip at all). Swapped in at the `/static` mount in place of plain `StaticFiles`. Kept as
   a second layer specifically so this class of bug can't recur even if a future template adds a
   `/static/...` reference directly instead of using `static_url()`.

## Verified

Confirmed via `curl -sI` that the `/static/css/app.css` response now carries
`Cache-Control: no-cache`, and that `static_url()`-generated URLs correctly embed the current
file's mtime as a query string. Both changes required a container **restart** (not just
`docker cp`) since `app.py` is Python, not a template/static asset — `uvicorn` isn't run with
`--reload` in this image (`Dockerfile`'s `CMD` has no `--reload` flag), so a code change only
takes effect after the process restarts.

## Files changed

| File | Change |
|---|---|
| `micro_cosmos/web/app.py` | New `static_url()` function + registered as a Jinja global; new `CacheControlledStaticFiles(StaticFiles)` subclass, swapped in at the `/static` mount |
| `micro_cosmos/web/templates/base.html` | All 7 `/static/...` references (`app.css` + 6 scripts) now use `{{ static_url(...) }}` |
| `micro_cosmos/web/templates/login.html` | Its one `app.css` reference now uses `{{ static_url(...) }}` |
| `micro_cosmos/web/templates/run.html` | Its `dashboard.js` reference now uses `{{ static_url(...) }}` |

## Lesson

The reported symptom was identical to a real bug fixed earlier the same session (graph panel
landing below the tab menu) — but the mechanism was completely different (stale browser cache
vs. a genuine CSS/flex bug). Re-deriving the mechanism from live evidence each time (computed
styles, response headers, a grep for media queries) rather than assuming "same symptom, same
cause, same fix" is what caught this — and it surfaced a real, independently-worth-fixing gap
(`/static/*` having no cache policy at all) that would otherwise have kept causing confusing,
hard-to-reproduce "my change isn't showing up" reports during any future session with several
rapid asset-only redeploys.
