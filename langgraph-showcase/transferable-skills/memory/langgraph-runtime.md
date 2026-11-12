---
name: langgraph-runtime
description: This showcase runs the same pipeline on LangGraph plus LiteLLM, not Google ADK (2026-09-27)
metadata:
  type: project
---

`google-cloud-showcase` is the ADK app. This folder is the LangGraph port. Do not import `google.adk` here.

`micro_cosmos/langgraph_runtime.py` provides `LlmAgent`, `FunctionTool`, `ToolContext`, `Runner`, and `InMemorySessionService`. `Settings.build_llm()` returns `GatewayModel` (`.model` is still `openai/<tag>` or `vertex_ai/<tag>`, extras live in `._additional_args`).

LLM mode: `Runner.run_async` compiles a `StateGraph` with `agent` and `tools` nodes and calls `litellm.acompletion`. Tool functions still receive `tool_context.state`, which is the shared session dict. The final assistant text is stored on `session.state[output_key]`. Deterministic mode never builds the graph; `_direct_tool_fallback` is unchanged.

Each showcase has its own `docker-compose.yml` and its own `llm-gateway`. Default profile is `ollama` / `gemma4:latest`. Host ports are **8080** (app) and **4001** (gateway). Start one folder or the other, not both.

Older memory files that say "ADK Runner" describe the session and tool behaviour this runtime still has to preserve.
