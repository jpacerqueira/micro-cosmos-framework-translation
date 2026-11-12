---
name: landing-page-example-chooser
description: The example chooser (demo.html) is now served at /; index.html was deleted; /demo is a 308 redirect; /demo/* API sub-routes keep their paths (2026-09-16). Supersedes nav-new-run-links-to-demo.md.
metadata:
  type: project
---

Joao asked for the current `/` page to disappear and `/demo` to become `/`, keeping every current
`/demo` behaviour plus the new pause-after-planning toggle.

## What moved

- `demo.html` is served at `GET /` (`demo_page` in `app.py`).
- `index.html` (the free-text `source_path` landing form) was **deleted**.
- `GET /demo` is a 308 redirect to `/` so existing bookmarks, docs and screenshots keep working.
- Login redirects (both the already-authenticated bounce and the successful POST) land on `/`.
- The two topbar links collapsed to a single `<a href="/">New run</a>` in `base.html`.

This was low-risk because `/` was already nearly orphaned: both login redirects and both nav
links already pointed at `/demo` (see the superseded [[nav-new-run-links-to-demo]]), nothing
linked to `/`, and no test exercised it.

## What must not move

The `/demo/detect-lang`, `/demo/upload` and `/demo/fetch-github` **API sub-routes keep their
paths**. They are called by the page's own JS (`demo.html` hard-codes those URLs), and renaming
them would churn the template for no user-visible gain. Tests that cover the route move must
assert that `/demo/detect-lang` still returns 200, not that it redirects.

## Accepted trade-off

`index.html` held the only free-text `source_path` field (`demo.html`'s equivalent is hidden and
set by clicking a card). Runs are therefore launched only from an example card, the GitHub-URL
box, or a zip upload — all three of which land content under `examples/`. Pointing at an
arbitrary mounted path from the UI is no longer possible. Do not reintroduce a free-text path
field on `/` unless Joao asks for it explicitly.

This also means **copying a new estate into `examples/` makes it a visible card** in the picker
(language badges from `detect_all_langs`). That is a product change, not just a test-fixture
change — ask before adding one. The AxonBank fixture copy on 2026-09-16 was an explicit yes
(see [[cartographer-fixture-must-travel-with-test]]).
