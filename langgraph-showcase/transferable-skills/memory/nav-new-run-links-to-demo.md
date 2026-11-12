---
name: nav-new-run-links-to-demo
description: SUPERSEDED 2026-09-16 by landing-page-example-chooser.md. Original (2026-08-06): topbar "New run" pointed at /demo while / still served index.html.
metadata:
  type: project
---

**Superseded 2026-09-16.** `/demo` is now a 308 to `/`, `index.html` is deleted, and the chooser
is the landing page. See [[landing-page-example-chooser]]. Kept so the 2026-08-06 nav-only change
is still readable.

Joao asked for both topbar nav links ("Demo" and "New run") to always land on
`http://localhost:8080/demo`. Previously "Demo" linked to `/demo` and "New run" linked to `/`
(the plain manual-entry new-run form, `index.html`) — two different starting points for
starting a run. One-line change in `base.html` (the shared layout every page renders through):
`<a href="/">New run</a>` → `<a href="/demo">New run</a>`. Grepped every template first to
confirm "New run" only appeared in that one place, so the shared-layout fix covers every page.

`/` (`index.html`) and its route are untouched — still reachable by direct URL, just no longer
linked from the nav. Verified live: clicking either nav link from a run-dashboard page lands on
`/demo` in both cases.
