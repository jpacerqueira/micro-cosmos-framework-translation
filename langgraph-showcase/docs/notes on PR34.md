# Notes on PR #34

## Bug fix: ruff `target-version` left at `py39` after `requires-python` was raised to `>=3.10`

PR #34 ("Deterministic VS LLM comparison table") raised `pyproject.toml`'s `requires-python` from
`>=3.9` to `>=3.10` to resolve a `uv sync` dependency-resolution conflict — a real, needed fix. But
its commit message described the change backwards ("modified minimum version of python to 3.9",
when the diff actually raised the floor to 3.10). Reviewer @joaocbynd caught the message/diff
mismatch on the PR; a repo-wide grep afterwards found the second, silent half of the problem:
`[tool.ruff]`'s `target-version` was left at `"py39"`, un-synced with the new `requires-python`
floor.

**Fixed:** `target-version` → `"py310"`.

Not touched: the merged commit message on `main` — rewriting already-merged, shared history for a
wording issue isn't worth the disruption; this note is the correction for the record instead.

**Verified:** `uv sync --extra dev` succeeds cleanly. `uv run ruff check .` findings went from 735
(at `py39`) to 759 (at `py310`) — the +24 delta is exactly `UP006`/`UP037`/`UP045` (PEP 585/604
modernization suggestions ruff now correctly offers now that 3.10+ syntax is in scope), not new
errors caused by the config change. Fixing that pre-existing lint debt is out of scope here.

### Files changed

| File | Change |
|---|---|
| `pyproject.toml` | `[tool.ruff] target-version`: `"py39"` → `"py310"` |
