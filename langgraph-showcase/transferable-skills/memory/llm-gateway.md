---
name: llm-gateway
description: Compose LiteLLM Proxy as OpenAI /v1 hop; Ollama active; LM Studio/vLLM/Bedrock/Vertex dormant; UTC call timeframes (2026-09-22)
metadata:
  type: project
---

`llm-gateway` is a second Compose service (`ghcr.io/berriai/litellm:main-stable`) that speaks OpenAI `/v1` to the app and routes to **one** backend. Inbound spec is OpenAI; outbound depends on `LLM_PROFILE`.

- App: `LLM_BASE_URL=http://llm-gateway:4000/v1`, `LLM_ENGINE=gateway`, `LLM_API_KEY` = gateway `LITELLM_MASTER_KEY` (default `sk-micro-cosmos-local`). Host-published proxy port is **4001** (`4001:4000`) so this stack can coexist with agentic-security's gateway on 4000.
- Active default: `LLM_PROFILE=ollama` → `ollama_chat/gemma4:latest` at `host.docker.internal:11434` with `keep_alive=60m`.
- Dormant: `lmstudio`, `vllm`, `bedrock`, `vertex` YAML under `llm-gateway/profiles/`. Switch = change `LLM_PROFILE` + `docker compose up -d llm-gateway`. **No load-balancing across profiles.**
- Proxy `timeout` / `request_timeout` is **28800s** so Code Writer / TDD loops are not killed at 180s (the agentic-security default).
- `entrypoint.sh` rejects unknown profiles, sets `PYTHONPATH` to `profiles/`, skips Prisma/DB, runs `litellm --detailed_debug`.
- Timing callback **must** sit next to the YAML: `llm-gateway/profiles/custom_callbacks.py`.
- Host venv without Compose keeps `LLM_ENGINE=ollama` and `http://localhost:11434/v1`. Cloud Run deploy scripts still point the app at LM Studio/vLLM/Vertex directly — they do not require this proxy.
- Readiness: `_wait_for_llm_ready(..., skip_native=True)` when `uses_llm_gateway()` so we only hit `GET /v1/models` on the proxy (never LiteLLM `/api/v0/models`). Direct `LLM_ENGINE=vertex` on the app still skips the wait.

## Logs

| Where | Content |
|---|---|
| `docker compose logs -f llm-gateway` | DEBUG JSON + `--detailed_debug` |
| `./logs/llm-gateway.log` | `gateway_call_start` / `_success` / `_failure` with `duration_ms`, `upstream_ms`, `overhead_ms` |
| `docker compose logs -f micro-cosmos` | App readiness + `build_llm()` lines |

No prompt bodies — `prompt_chars` only.
