# CI and image publish

GitHub Actions for the two Compose showcases. They never deploy together.

## Tests

`.github/workflows/test.yml` — push to `main` and pull requests.

Each job checks out the repo, `cd`s into one showcase, and runs:

```bash
docker compose build micro-cosmos
docker compose run --no-deps --rm -e SKIP_LLM=true micro-cosmos pytest -q --tb=line
```

Jobs: **Google ADK** (`google-cloud-showcase`), **LangGraph** (`langgraph-showcase`). Separate runners. Gateway is not started.

## Publish one image

`.github/workflows/deploy.yml` — Actions → **Deploy image** → Run workflow. Pick one showcase.

After that showcase's tests pass, the app image is pushed as:

- `ghcr.io/<owner>/micro-cosmos:<showcase>`
- `ghcr.io/<owner>/micro-cosmos:<showcase>-<sha>`

`<showcase>` is `google-cloud-showcase` or `langgraph-showcase`.

Cloud Run is still `/deploy-gcp`. This command does not call `gcloud`.
