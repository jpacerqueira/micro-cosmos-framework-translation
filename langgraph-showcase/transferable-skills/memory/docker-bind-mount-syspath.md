---
name: docker-bind-mount-syspath
description: python /tmp/p.py inside the micro-cosmos container imports the image's installed micro_cosmos from site-packages, not the bind-mounted source — sys.path[0] is the script's directory; PYTHONPATH=/app (or pytest) is required (2026-09-16)
metadata:
  type: project
---

A throwaway probe run as `python /tmp/p.py` inside
`docker compose run --rm -v "$PWD/micro_cosmos:/app/micro_cosmos"` reported
`TypeError: MicroCosmosOrchestrator.__init__() got an unexpected keyword argument
'pause_after_planning'` on code that was demonstrably already in the bind-mounted tree.

**Cause.** `sys.path[0]` is the *script's* directory (`/tmp`), not the working directory (`/app`).
The import then hits the image's installed `micro_cosmos` in site-packages — the copy baked in
at `docker compose build` — and never sees the mount.

**Fix.** `PYTHONPATH=/app python /tmp/p.py`, or run from `/app` as a module, or just use pytest
(rootdir is already on the path, so bind-mounted `tests/` + `micro_cosmos/` work).

This is easy to misread as "the mounted edit didn't apply" / "the container is stale" and waste
a rebuild. pytest was never affected.

Related, already known: `docker compose config --quiet` after any merge that touches
`docker-compose.yml` — a duplicate `LLM_ENGINE` key silently used the last value and once
overrode the local Ollama default with upstream's `lmstudio`.
