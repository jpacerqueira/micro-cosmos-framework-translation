# `.env` setup docs for new joiners + a real SKIP_LLM/.env wiring bug found along the way

Joao asked for a new "step 0" in `README.md`'s Quickstart explaining `.env` configuration before a
first `docker compose up --build`, so a new joiner can build the app on local Docker Desktop
without guessing at required variables.

## The bug found while writing the docs

`docker-compose.yml`'s `environment:` block hardcoded 5 values as literal YAML strings instead of
`${VAR}` substitutions: `SKIP_LLM: "true"`, `MODEL_TEMPERATURE: "0.2"`, `LLM_TIMEOUT: "28800"`,
`MAX_TDD_ITERATIONS_PER_SEAM: "3"`, `GOOGLE_GENAI_USE_VERTEXAI: "FALSE"`. `CLAUDE.md`'s own
documented command — `SKIP_LLM=false docker compose up` — never actually worked, because Docker
Compose only substitutes `${VAR}` references that literally appear in the compose file; exporting a
shell variable that has no matching `${VAR}` placeholder has zero effect on a hardcoded string. The
only way to switch to LLM mode was to hand-edit the literal string in `docker-compose.yml` itself.

**Caught before fixing, not after**: this was surfaced to Joao via `AskUserQuestion` before any
code changed, since it wasn't one of the 29 [[project_ultra_review_29_findings]] and fixing it
meant expanding scope on an explicitly-scoped documentation task. He chose "fix, then document"
over "document current (broken) behavior" or "flag only."

## The fix

Converted all 5 to `${VAR:-<current-default>}` syntax, preserving today's exact defaults so nobody
running without a `.env` file sees any behavior change — verified via `docker compose config`
(defaults resolve identically) and `SKIP_LLM=false docker compose config` (now correctly resolves
to `"false"`, which it silently failed to do before this fix). `LLM_BASE_URL` — previously
hardcoded with no substitution at all — was also converted to
`${LLM_BASE_URL:-http://host.docker.internal:1234/v1}`, so switching to Ollama or a custom
port no longer requires editing the compose file directly, matching the pattern the file's own
inline comments already implied was possible.

**Gotcha hit while editing**: the original file had trailing whitespace on several lines
(`MODEL_REASONING: ${MODEL_REASONING} # google/gemma-4-e4b # google/gemma-4-12b ` — trailing space
before the line break) that made an `Edit` tool `old_string` match fail even though the visible
text looked identical. Rewrote the whole file with `Write` instead of chasing exact whitespace with
`Edit`. Worth remembering for this specific file if it's edited again — check for trailing
whitespace before assuming an `Edit` match failure is a content mismatch.

## Documentation changes

- `.env.example` gained `SKIP_LLM` and `LLM_BASE_URL` (previously undocumented there despite
  being referenced everywhere else — `CLAUDE.md`, `README.md`, `deployment/README.md`), with an
  explicit "safe to leave everything unset for a first run" framing at the top, since Deterministic
  mode needs none of it.
- `README.md`'s Quickstart gained "### 0. Configure your `.env` file (first time only)" before the
  existing "Start the container" step — explains `cp .env.example .env`, that the file is
  git-ignored and optional for Deterministic mode, then a table of every variable marking whether
  it's required for LLM mode. Cross-references the existing `## Configuration` and `## Run modes`
  sections rather than duplicating their content (avoids a 3rd copy of the same model-config info
  drifting out of sync, the same anti-duplication call made in [[cqrs-framework-detection]]-style
  registry work and [[openapi-rename-and-openspec-artifact]]'s shared-content constants).
- Step 1's `docker compose up` corrected to `docker compose up --build`, matching `CLAUDE.md`'s
  documented command exactly, so a new joiner's very first run picks up the current `Dockerfile`
  rather than risking a stale cached image if one somehow already exists.

## Why this matters beyond just docs

Any future `.env`-documented variable that isn't also wired into `docker-compose.yml` via `${VAR}`
substitution is dead documentation — it looks configurable but silently does nothing when set via
`docker compose`. If a new variable is added to `.env.example` in the future, check it's actually
referenced in `docker-compose.yml` too, or explicitly note in the `.env.example` comment that it
only applies to a different entry point (e.g. `deployment/deploy.py`).

**Correction (2026-09-08):** this entry previously cited `VERTEX_STAGING_BUCKET` as a good example
of a correctly deploy-scoped variable — that was wrong, caught while reviewing `.env.example`
during the `llm_engine=vertex` work. `VERTEX_STAGING_BUCKET` isn't read by `deployment/deploy.py`,
`deploy_cloudrun-micro-cosmos-app.py`, or anywhere else in the codebase — it was dead documentation
citing another piece of dead documentation, not a real "deploy-only" variable. It's been removed
from `.env.example`. Lesson: grep for a variable's actual reader before citing it as a good
example, don't assume from its presence in `.env.example` alone that it's wired up somewhere.
