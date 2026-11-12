# micro-cosmos-framework-translation
A Sandbox mode for LLM assisted Framework Translation and upgrade of a code base using LangGraph pipelines.



### Contact : joao@fuelbigdata.com - for a Cloud Run , GKE or EKS or ECS Demo.



The Open Langgraph Mode is here free of charge. It's the first of 2 separate deployments of the same source-to-source pipeline. Use The LangGraph Pipeline version here for free in Docker. Its langgraph folder has its own `docker-compose.yml` and its own LiteLLM `llm-gateway`. Deploy one or the other. They are not meant to run together: both publish the app on **8080** and the gateway on **4001**.

```bash
# Google ADK + this folder's gateway (default ollama / gemma4:latest)
cd google-cloud-showcase
docker compose up --build
# http://localhost:8080

# LangGraph + this folder's gateway (default ollama / gemma4:latest)
cd langgraph-showcase
docker compose up --build
# http://localhost:8080
```

Stop one stack (`docker compose down` in that folder) before starting the other. Deterministic mode is the default and does not call a model. LLM mode uses only the gateway in the compose file you started.

## Framework comparison

| Role | `google-cloud-showcase` | `langgraph-showcase` |
|---|---|---|
| Agent framework | Google ADK `LlmAgent` + `Runner` | LangGraph `StateGraph` (`agent` / `tools` nodes) |
| LLM client | ADK `LiteLlm` | LiteLLM `acompletion` via `GatewayModel` |
| Model gateway | Its own LiteLLM Proxy | Its own LiteLLM Proxy |
| Default profile | `ollama` | `ollama` |
| Default model | `gemma4:latest` | `gemma4:latest` |
| Model id the app sends | `openai/<tag>` or `vertex_ai/<tag>` | Same ids |
| Google Cloud backend | `LLM_ENGINE=vertex` or `LLM_PROFILE=vertex` | Same |
| AWS backend | `LLM_PROFILE=bedrock` | `LLM_PROFILE=bedrock` |
| Deterministic mode | `skip_llm` tool fallbacks | Same fallbacks; the graph is not built |
| Session | ADK `InMemorySessionService` | Same API, implemented in `langgraph_runtime.py` |
| Tools, scanners, reports, skills | Unchanged ADK tree | Same tree; imports point at the LangGraph runtime |
| App host port | **8080** | **8080** |
| Gateway host port | **4001** | **4001** |
| Tests | `docker compose run --no-deps --rm micro-cosmos pytest -q` in that folder | Same command in that folder |
| GitHub Actions | `.github/workflows/test.yml` job **Google ADK** | `.github/workflows/test.yml` job **LangGraph** |

## GitHub Actions

`.github/workflows/test.yml` runs on every push to `main` and on pull requests. The two jobs run on separate runners, each inside that showcase’s own app image (`docker compose build micro-cosmos`, then `pytest` with `SKIP_LLM=true`). They do not start the gateway and they do not bind 8080 or 4001 on the same machine.

`.github/workflows/deploy.yml` is manual (**Actions → Deploy image → Run workflow**). Pick one showcase. It re-runs that showcase’s tests, then pushes a single image to GHCR:

- `ghcr.io/jpacerqueira/micro-cosmos:google-cloud-showcase`
- `ghcr.io/jpacerqueira/micro-cosmos:langgraph-showcase`

Only the selected image is published.

Switching cloud only changes `LLM_PROFILE` in that folder’s `.env` and restarts that folder’s `llm-gateway`. The app keeps talking to `http://llm-gateway:4000/v1` on its own compose network.
