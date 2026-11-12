---
name: github-actions-ci
description: GitHub Actions runs each showcase's pytest in its own image, and a manual workflow publishes one image to GHCR (2026-09-28)
metadata:
  type: project
---

Root workflows live in `.github/workflows/` of the public repo, not inside a showcase.

`test.yml` runs on push to `main` and on pull requests. Two jobs, two runners:

| Job | Working directory | Command |
|---|---|---|
| Google ADK | `google-cloud-showcase` | `docker compose build micro-cosmos` then `docker compose run --no-deps --rm -e SKIP_LLM=true micro-cosmos pytest -q --tb=line` |
| LangGraph | `langgraph-showcase` | same |

`SKIP_LLM=true` keeps CI on the deterministic path. `--no-deps` does not start `llm-gateway`, so the jobs never bind host **8080** or **4001**.

`deploy.yml` is `workflow_dispatch` only. The input `showcase` is `google-cloud-showcase` or `langgraph-showcase`. It re-runs that folder's tests, then pushes one image:

- `ghcr.io/<owner>/micro-cosmos:google-cloud-showcase`
- `ghcr.io/<owner>/micro-cosmos:langgraph-showcase`

plus the same tag with the commit SHA. Do not publish both in one run.

Cloud Run (`/deploy-gcp`, `deployment/`) is a separate path. This workflow only builds the Compose app image and stores it on GHCR.
