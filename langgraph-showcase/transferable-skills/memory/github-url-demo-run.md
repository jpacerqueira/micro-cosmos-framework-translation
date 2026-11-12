---
name: github-url-demo-run
description: Start a demo run from a GitHub URL (download-as-zip) — design, SSRF closure, shared extraction refactor, and full test verification (2026-08-26)
metadata:
  type: project
---

Joao asked for a third way to get source code into a demo run, alongside the existing typed
local-path form (`index.html`) and drag-and-drop zip upload (`demo.html`): paste a public GitHub
repository URL and have the server fetch it. He then pinned the exact layout himself — the
GitHub-URL box takes the top slot on `demo.html` (where the zip-upload box used to be), and the
zip-upload box moves to the bottom of the page, below the full example grid.

## Design

`POST /demo/fetch-github` (`micro_cosmos/web/app.py`) downloads the repo as a zip from
`codeload.github.com` — no `git` binary needed in the image — and reuses the exact
extraction/validation logic `/demo/upload` already had. That logic was refactored out into a new
module-level `_extract_zip_to_examples(content: bytes, safe_name: str) -> dict` helper (zip-open →
common-root-strip → path-traversal guard → write → `detect_all_langs`/subfolders/description →
card-data dict), called by both endpoints. It also gained a new uncompressed-size zip-bomb guard
(500MB cap, checked via `ZipInfo.file_size` summed across all entries before any bytes are
written) that neither endpoint had before — a real gap, not hypothetical, since a compressed zip's
declared uncompressed size is exactly the kind of thing a hostile upload would lie about.

**SSRF is closed off by construction, not by an allowlist check on attacker-supplied input.** The
endpoint only accepts a `github.com`/`www.github.com` HTTPS URL; the actual outbound requests (to
`api.github.com` for default-branch resolution, to `codeload.github.com` for the zip) are built
entirely server-side from the regex-parsed `(owner, repo, ref)` tuple. The client never gets to
supply a host string at all past the initial `github.com` check, so there's no redirect or
alternate-host trick available — this is a stronger guarantee than validating a client-controlled
URL against an allowlist, which is easy to get wrong (open redirects, DNS rebinding, etc.).

Used stdlib `urllib.request` (via `asyncio.to_thread` so the blocking call doesn't stall the event
loop) rather than adding `httpx`/`requests` as a new runtime dependency — `httpx` was already in
`pyproject.toml` but only under `[project.optional-dependencies].dev` (for `TestClient`), and one
GET-plus-streamed-download doesn't justify promoting it to a runtime dependency.

`github_url: str = ""` follows the exact `auto_approve_gates` persistence pattern documented in
CLAUDE.md — threaded through `Run.__init__` → `create_run()`'s `Form(...)` param and
`run_meta.json` write → `_restore_run()`'s safe `.get("github_url", "")` default. Purely
descriptive: `source_path` is already a resolved local directory by the time `create_run()` runs
(same as an uploaded zip), so zero pipeline code changed. Surfaced as a "GitHub source ↗" badge on
`run.html`, next to the existing mode/auto-approve badges.

`demo.html`'s `select(path, langs, githubUrl)` gained a third optional parameter that populates a
new hidden `#demo-github-url-input`, defaulting to `""` for every other selection path (built-in
card click, subfolder click, zip upload) — only the GitHub-fetch success handler passes it. A
fetched repo re-selected later via its card would lose the badge-worthy provenance on that
re-click; accepted as a minor, purely-cosmetic gap given the field is explicitly descriptive.

## Verification

**Automated — `tests/test_github_url_demo_run.py`, new file, 11 tests, all passing.** Modeled on
`test_auto_approve_gates.py`'s `TestClient` + `importlib.import_module("micro_cosmos.web.app")` pattern
(see that file for why the shadowed `app` attribute makes direct module import necessary). Split
two ways:

- **Persistence** (4 tests) — `POST /runs` persists `github_url` into `run_meta.json`, defaults to
  `""` when absent; `_restore_run()` round-trips both a present and (for `run_meta.json` files
  written before this feature existed) an absent `github_url` key.
- **`/demo/fetch-github` behavior** (7 tests) — URL/host validation needs no mocking since it runs
  before any network call: non-`github.com` host, non-HTTPS scheme, and a malformed path (no repo
  segment) all get a clean `400`, including the literal SSRF-adjacent case
  (`https://evil.com/owner/repo`). The network-touching paths mock `urllib.request.urlopen` (a
  `_FakeResponse` context-manager stand-in) rather than hitting real GitHub: a successful fetch
  with an explicit `/tree/<ref>` (extracts correctly, `github_url` echoed back in the response, one
  `urlopen` call only); the same without a ref (asserts *two* calls — `api.github.com` for
  `default_branch` first, then `codeload.github.com` built from that resolved branch, not a
  hardcoded `main`); the zip-bomb guard (patches `ZipFile.getinfo` to report a 999MB entry,
  confirms `413` and nothing written to disk); and a `404` from GitHub surfacing as a clean `404`
  rather than a `502`/stack trace.

Full-suite regression check: **236 passed, 1 skipped, 0 failed** (was 225 passed, 1 skipped before
this feature — the +11 is exactly the new file, zero change to any pre-existing test). Caught one
real process mistake while doing this: an initial `docker compose run` against an image built
*before* the new test file existed silently ran only the old 225 — `docker-compose.yml` doesn't
volume-mount `micro_cosmos/`/`tests/`, so code edits after `docker compose up --build` aren't visible to
`docker compose run` against the cached image until it's rebuilt. Re-running after `docker compose
build` picked up the new file and gave the real 236 count.

**Live/manual, against the running container with a real public repo** (`octocat/Hello-World`):
fetched via `curl` end-to-end — extracted correctly (`README` landed at the right path, common-root
stripped), a malformed URL and a non-GitHub host both returned clean `400`s, a nonexistent repo
returned a clean `404`, a Deterministic-mode run started successfully against the fetched source,
and the run page rendered the "GitHub source ↗" badge with `run_meta.json` correctly persisting
`github_url`. Test artifacts (`examples/octocat_Hello-World/`, the test run directory) were removed
and the container stopped afterward.

## Follow-up: input-below-button layout (2026-08-26, same day)

A screenshot showed the URL `<input>` squeezed into the same flex row as the title/hint/Fetch
button, cramped enough that a real GitHub URL was clipped and unreadable. Fixed by splitting
`.demo-github-zone` into two stacked rows: a new `.demo-github-top` wrapper holds
icon+title/hint+status+Fetch button exactly as before, and the `<input>` moved to be a direct
sibling below it with `width: 100%` — spanning the full box so the whole pasted URL is visible.
Pure CSS/HTML restructuring inside `demo.html`; no id changed, so none of the JS wiring
(`doFetchGithub`, event listeners) needed touching.

Verified: full suite still **236 passed, 1 skipped, 0 failed** (expected — no logic touched);
rebuilt the container and pulled the rendered `/demo` HTML to confirm the new
`.demo-github-top`/sibling-`<input>` structure is actually what's served (not just what's in the
template source); re-ran the live `octocat/Hello-World` fetch against the rebuilt container to
confirm the relocated input's `id` still wires up correctly end-to-end. Not independently
confirmed with a real browser screenshot — no browser-automation tool was available in this
environment, so the visual result (as opposed to the markup/CSS/behavior) rests on the CSS reasoning
above plus Joao's own build/test pass.

## Files changed

| File | Change |
|---|---|
| `micro_cosmos/web/app.py` | New `_extract_zip_to_examples()` shared helper (+ zip-bomb guard); `demo_upload_example()` slimmed to use it; new `POST /demo/fetch-github`; `github_url` threaded through `Run.__init__`/`create_run()`/`_restore_run()` |
| `micro_cosmos/web/templates/demo.html` | GitHub-URL box in the top slot; zip-upload box moved to a full-width row below the example grid; `select()` gained an optional `githubUrl` param; new `doFetchGithub()`; follow-up: input moved below the top row, full width |
| `micro_cosmos/web/templates/run.html`, `micro_cosmos/web/static/css/app.css` | "GitHub source ↗" badge, shown when `run.github_url` is set |
| `tests/test_github_url_demo_run.py` | New — 11 tests covering persistence + endpoint validation/behavior |
| `product-roadmap-markup/MICRO-COSMOS-DEMO-starts-from-a-GitHub-url-to-download-a-zip.md` | Original design/effort-estimate doc (written first, committed separately) |
| `README.md` | Quickstart section restructured to cover both entry points; feature table + project-structure line updated |
| `CLAUDE.md` | New "Start a demo run from a GitHub URL" section |
