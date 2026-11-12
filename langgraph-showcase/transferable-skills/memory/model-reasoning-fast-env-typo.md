---
name: model-reasoning-fast-env-typo
description: MODEL_REASONING/MODEL_FAST had a "gema4-e4b" typo in .env.example (missing the second "m") that silently deadlocked the LM Studio readiness wait for the full 25-minute timeout on every LLM-mode run (2026-07-20)
metadata:
  type: project
---

## The bug

`.env.example` (and, transitively, whatever environment was seeded from
it) had:
```
MODEL_REASONING=google/gema4-e4b
MODEL_FAST=google/gema4-e4b
```
missing the second "m" — should be `google/gemma-4-e4b`. `git blame`
shows this was introduced 2026-07-01, unrelated to any of this session's
other work.

## Why this deadlocks a run rather than erroring loudly

`micro_cosmos/orchestration/driver.py`'s `_wait_for_llm_ready()` builds
`model_ids = {settings.model_reasoning, settings.model_fast}` and polls
LM Studio's native `GET /api/v0/models` until every id in that set reports
`"loaded"`. With the typo, `model_ids` contains the literal string
`"google/gema4-e4b"`, which never appears as a key in LM Studio's response
— even though the *correct* model (`google/gemma-4-e4b`) is genuinely
loaded and LM Studio reports it as such on every single poll. Confirmed
live in container logs: dozens of consecutive
```
GET http://host.docker.internal:1234/api/v0/models -> 200 OK — {'google/gemma-4-e4b': 'loaded', ...}
```
lines, none of which ever satisfy `all(by_id.get(mid) == "loaded" for mid in model_ids)`
because the key being checked doesn't exist. This isn't a crash or a
visible error anywhere — the pipeline just polls every 5-10s for the full
`llm_ready_timeout_seconds` (floored at 1500s / 25 min, see
[[project_gcp_deployment]]'s note on that floor) before giving up and
proceeding anyway. From the UI, a fresh LLM-mode run just looks
permanently "not starting" — no error, no artifacts, nothing until the
timeout eventually lapses. Worse: real inference calls afterward would
*also* target the same nonexistent model name and likely fail too.

**Two real runs hit this live during this session** (`bae5b1f2`,
`3690c43e`) — both looked "hung," and both were the identical root cause,
not two different bugs.

## Fix

1. `.env.example`: corrected both lines to `google/gemma-4-e4b`.
2. The **running container** had the stale typo baked into its env
   (confirmed via `docker exec ... printenv`, even though the host's own
   `.env` file already had the correct spelling) — `.env` values are only
   re-substituted into a container on an actual recreate, not automatically
   on every `docker compose up`. Fixed via `docker compose up -d --force-recreate`,
   confirmed post-recreate via the same `printenv` check.
3. The two stuck runs could not be resumed — they had no artifacts on disk
   yet for the "restore on startup" mechanism to reconstruct from — they
   had to be started fresh.

## Lesson worth generalizing

A model-name mismatch between "what the app is polling for" and "what's
actually loaded" fails *silently and slowly* (a 25-minute wait, not an
error) rather than fast and loud. If a fresh LLM-mode run looks stuck with
no error and no progress, the first check should be: does the readiness-wait
log's polled model id **exactly** match a key in the same log line's
reported catalog — a one-character typo is enough to break it, and
`docker exec <container> printenv | grep MODEL_` is the fastest way to see
what the *running* container actually has, since it can differ from the
current `.env` file on disk if the container hasn't been recreated since.
