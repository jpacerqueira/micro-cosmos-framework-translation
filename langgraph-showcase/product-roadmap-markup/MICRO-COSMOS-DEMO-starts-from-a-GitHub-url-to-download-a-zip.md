# Micro-Cosmos demo — start a run from a GitHub URL (download-as-zip)

**Operation**: let a user paste a public GitHub repository URL (optionally with a branch/tag/commit)
into the demo/home "start a run" form instead of only a local `source_path` or a manually-uploaded
`.zip`. The app downloads that repo as a zip (GitHub's `codeload.github.com` archive endpoint —
no `git`/`git clone` dependency needed), extracts it server-side using the same logic `/demo/upload`
already uses for user-uploaded zips, and feeds the extracted directory into `create_run()` as
`source_path`, exactly as today.

This is additive to the existing two entry points (typed local path on `index.html`, drag-and-drop
zip upload on `demo.html`) — it does not replace either.

---

## Current state (researched 2026-08-26)

- **Two existing ways to get source code into a run**:
  - `index.html:13-17` — plain text `source_path` input, submitted directly to `POST /runs`.
  - `demo.html:360-372,433-436,671-770` — drag-and-drop `.zip` uploader that posts to
    `POST /demo/upload`, which extracts the zip server-side and writes the resulting local path into
    a **hidden** `#demo-source-path-input`, then the visible form submits that resolved path to
    `POST /runs` as normal. **This is the template to clone for GitHub URLs** — same
    resolve-to-local-path-then-submit shape, just swapping "read an uploaded file" for
    "download a remote zip."
  - `micro_cosmos/web/app.py:1569-1660` (`/demo/upload`) already does everything needed downstream of
    having zip bytes: `zipfile.ZipFile(io.BytesIO(content))`, strips a single common root dir (the
    exact shape GitHub's codeload zips use: `<repo>-<branch>/...`), path-traversal guard via
    `target.relative_to(dest)` (line 1624-1628), filename sanitization via
    `re.sub(r"[^a-zA-Z0-9_\-]", "_", stem)` (line 1589), writes into `examples/<safe_name>`.
- **`source_path` is consumed as a pre-existing local directory, nothing more**:
  `micro_cosmos/tools/source_tools.py:83-115` (`list_source_files`) does `Path(source_path)` and errors
  if it doesn't exist. No fetch/download logic exists anywhere in `micro_cosmos/` today (confirmed: no
  `requests.get`/`urlopen` for remote content anywhere in the codebase).
- **`run_meta.json` persistence pattern** (established by `skip_llm`/`auto_approve_gates`, see
  CLAUDE.md "Auto-approve gates"): a new field must be threaded through the same three points —
  `Run.__init__` (`app.py:166-188`) stores it on `self`, `create_run()` (`app.py:348-412`) writes it
  into the `run_meta.json` dict (lines 381-391), `_restore_run()` (`app.py:273-289`) reads it back
  with a safe default.
- **No SSRF/URL-allowlisting code exists anywhere in the repo** — this needs to be designed from
  scratch, not adapted from an existing pattern.
- **Source code currently lives outside `run_dir` entirely** (e.g. `examples/foo`, sibling to
  `runs/<id>/`), never inside `runs/<id>/`. A GitHub-URL feature can keep that convention
  (`examples/<safe_repo_name>`, same as `/demo/upload`'s destination) rather than inventing a new
  per-run source location.

---

## Proposed design

### 1. Input surface
Add a "GitHub URL" field alongside the existing local-path and zip-upload options on `demo.html`
(and optionally `index.html`), e.g. a tab/toggle: **Local path | Upload zip | GitHub URL**. Accepts
`https://github.com/<owner>/<repo>` with an optional `/tree/<ref>` suffix, or a bare
`owner/repo[@ref]` shorthand.

### 2. New endpoint: `POST /demo/fetch-github`
Mirrors `/demo/upload`'s contract (same response shape: resolved local `source_path`), but instead
of reading `UploadFile` bytes, it:
1. **Validates the URL** — must parse as `github.com` or `www.github.com` host, path matches
   `^/[\w.-]+/[\w.-]+(/tree/[\w.\-/]+)?/?$`, scheme is `https`. Reject everything else (no
   IP literals, no other hosts, no redirects followed blindly — see Security below).
2. **Builds the codeload zip URL**: `https://codeload.github.com/<owner>/<repo>/zip/refs/heads/<ref>`
   (default ref `HEAD`/the repo's default branch, resolved via GitHub's public REST API
   `GET /repos/<owner>/<repo>` `default_branch` field if no ref given — one extra unauthenticated API
   call, subject to GitHub's low unauthenticated rate limit, worth surfacing in the UI if it fails).
3. **Downloads with limits**: streamed GET with a size cap (reuse `/demo/upload`'s 200MB cap) and a
   request timeout (e.g. 30s connect / 120s total) — a slow or huge remote repo must not hang the
   request indefinitely.
4. **Extracts using the exact same logic `/demo/upload` already has** (`app.py:1569-1660`):
   `zipfile.ZipFile`, strip common root dir, path-traversal guard, filename sanitization, write to
   `examples/<safe_name>`. This should be refactored into a shared helper
   (`_extract_uploaded_zip(content: bytes, safe_name: str) -> Path`) called by both `/demo/upload`
   and `/demo/fetch-github`, rather than duplicated.
5. Returns the resolved local path as JSON, same shape `/demo/upload` returns today, so
   `demo.html`'s existing JS (populate hidden `#demo-source-path-input`, then submit `#demo-form`)
   needs only a second success-handler wired to the new endpoint, not a rewrite.

### 3. Persisting provenance
Add `github_url: str = ""` to `Run.__init__`, the `create_run()` `run_meta.json` write, and
`_restore_run()`'s `meta.get("github_url", "")` read — following the exact pattern documented in
CLAUDE.md for `auto_approve_gates`. Purely informational (displayed on the run page so a viewer
knows the source came from a URL, not a manual upload) — it does not change any pipeline behavior,
since by the time `create_run()` runs, `source_path` is already a resolved local directory.

### 4. Reuse Finding-0-style zip hygiene
`product-roadmap-markup/AppsFlow-Typescript-rebuild-with-Micro-Cosmos.md`'s Finding 0 (skip `__MACOSX/`
and `._*` files during source discovery) applies here too — GitHub zips don't carry that junk, but
if the shared extraction helper is reused for both upload paths, that fix (if not already applied)
benefits GitHub-sourced runs for free.

---

## Security considerations (must design, nothing to copy)

- **SSRF**: the fetch step makes a server-side request to a user-supplied host. Hard-restrict to
  `github.com`/`codeload.github.com`/`api.github.com` exact hostnames (no wildcard, no
  redirect-following across hosts — set `allow_redirects=False` or validate each hop). Do not allow
  the user to supply the codeload/API URL directly, only `owner/repo[@ref]`, which this endpoint
  itself turns into the codeload URL — this closes off arbitrary-host SSRF entirely since the host
  is never attacker-controlled.
- **Resource exhaustion**: size cap + timeout (above) prevent a giant or slow-responding repo from
  tying up a worker. Also cap extracted (uncompressed) size, not just compressed download size, to
  guard against a zip bomb — `/demo/upload` should arguably get this same check if it doesn't have
  it already.
- **Path traversal**: already solved by reusing `/demo/upload`'s `target.relative_to(dest)` guard.
- **Rate limiting / auth**: unauthenticated GitHub API calls are capped at 60/hour per IP. If this
  demo runs behind a shared IP (e.g. Cloud Run), consider an optional `GITHUB_TOKEN` env var used
  only to raise this API's rate limit (5,000/hour) — never required, never exposed to the client.
- **Private repos**: out of scope for v1 — codeload zip downloads for private repos require an
  authenticated request; document this as a known limitation rather than silently failing.

---

## Effort estimate

| Item | Size | Estimate |
|---|---|---|
| Refactor `/demo/upload`'s extraction logic into a shared helper | XS | 1-2 hours |
| `POST /demo/fetch-github`: URL validation, codeload URL construction, default-branch lookup, streamed download with size/timeout limits | S | half a day |
| `demo.html` UI: URL input + tab/toggle, JS wiring to the new endpoint reusing the existing hidden-input-then-submit pattern | S | half a day |
| `github_url` persistence (`Run.__init__`, `create_run`, `_restore_run`) | XS | under an hour |
| Zip-bomb (uncompressed-size) guard, applied to both `/demo/upload` and the new endpoint | XS | 1-2 hours |
| Manual test: public repo happy path, bad URL, private repo (expected failure), oversized repo (expected rejection) | XS | 1-2 hours |

**Total: ~1.5-2 days.**

---

## Recommended order of work

1. Refactor shared zip-extraction helper out of `/demo/upload` (no behavior change, sets up reuse).
2. Add the zip-bomb (uncompressed size) guard to that shared helper.
3. Implement `POST /demo/fetch-github` (URL validation → codeload URL → streamed download → shared
   extraction helper).
4. Wire `demo.html`'s UI (URL input + JS) to the new endpoint.
5. Add `github_url` persistence following the `auto_approve_gates` pattern.
6. Manual test pass against a small real public GitHub repo end-to-end (fetch → extract → run
   starts → pipeline proceeds normally, since `source_path` downstream is unchanged).
