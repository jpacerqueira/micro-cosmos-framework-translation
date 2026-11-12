#!/bin/bash
# Container entrypoint for the vLLM-based Cloud Run GPU service (alternative
# to lmstudio-entrypoint.sh — see Dockerfile.vllm for why).
#
# The model is NOT baked into the image — HF_HOME points at
# $HOME/.cache/huggingface, mounted as a Cloud Storage FUSE volume by
# deploy_cloudrun-vllm-llms.py, so the ~17GB download persists across
# redeploys and cold starts (same rationale as lmstudio-entrypoint.sh's
# .lmstudio/models mount).
set -euo pipefail

: "${MODEL_ID:?MODEL_ID env var required}"
: "${MODEL_CONTEXT_LENGTH:=262144}"
: "${GPU_MEMORY_UTILIZATION:=0.9}"
: "${LMSTUDIO_REASONING_PARSER:=}"  # e.g. "qwen3" for Qwen3.6 — empty/unset for models with no reasoning parser.
                                    # Named LMSTUDIO_* (not VLLM_*, renamed 2026-07-13) — this is this repo's
                                    # own entrypoint convention, not a real vLLM-recognized env var; the VLLM_
                                    # prefix made vLLM's own env scanner log a false-positive "Unknown vLLM
                                    # environment variable" warning for it every startup (envs.py:2094).
: "${LMSTUDIO_TOOL_CALL_PARSER:=}"  # e.g. "hermes" — REQUIRED for this pipeline's agents (ADK FunctionTool /
                                    # OpenAI function-calling) to work at all; without --enable-auto-tool-choice
                                    # + a parser, vLLM returns tool calls as plain text instead of structured
                                    # tool_calls, silently breaking every tool-using agent. Empty disables it.
                                    # Same LMSTUDIO_* rename rationale as LMSTUDIO_REASONING_PARSER above.
: "${VLLM_API_KEY:=}"               # optional — same secret micro-cosmos-web sends as LLM_API_KEY
                                    # (micro_cosmos/settings.py's build_llm()); when set, vLLM enforces it via
                                    # --api-key on every /v1 request. Empty disables auth entirely (the
                                    # --ingress=internal Cloud Run boundary is then the only protection,
                                    # same threat model as LM Studio's own request-time auth, which has no
                                    # equivalent CLI flag — see deploy_cloudrun-lmstudio-llms.py's header).
: "${LMSTUDIO_CHAT_TEMPLATE:=}"     # e.g. "examples/tool_chat_template_gemma4.jinja" — Gemma 4's own vLLM
                                    # deployment recipe requires this alongside --tool-call-parser for tool
                                    # calling to work at all (confirmed via docs.vllm.ai's Gemma4 recipe, not
                                    # guessed); Qwen3.6/hermes needed no such template. Bundled in the
                                    # vllm/vllm-openai:gemma4 image itself — a relative path resolves against
                                    # that image's own WORKDIR, no download/mount needed. Empty omits the flag
                                    # entirely (models with no tool-calling template of their own).
: "${LMSTUDIO_ENABLE_THINKING:=}"   # "true" forces Gemma 4's chain-of-thought "thinking mode" on for every
                                    # request by default. NOT on by default even with --reasoning-parser
                                    # gemma4 set above — that flag only parses reasoning content out of the
                                    # response IF the model produces it; it doesn't make the model reason in
                                    # the first place (confirmed via vLLM's own docs, not guessed). Passed as
                                    # --default-chat-template-kwargs '{"enable_thinking": true}' — the chat
                                    # template itself injects the real <|think|> control token into the
                                    # assembled prompt; this is not something to splice into request text by
                                    # hand. Thinking tokens count against the same --max-model-len/max_tokens
                                    # budget as everything else — a model already running near its context
                                    # limit may need that raised. Empty/unset leaves vLLM's own
                                    # thinking-disabled default in place.
PORT="${PORT:-8000}"   # vLLM's own native default (Cloud Run always injects the
                       # real PORT matching --port at deploy time; this fallback
                       # only matters for a non-Cloud-Run local run)
: "${LMSTUDIO_WATCHDOG_TIMEOUT_SECONDS:=1500}"  # matches micro_cosmos/settings.py's
                                    # llm_ready_timeout_seconds floor/default (25 min) — how long the
                                    # watchdog below waits for /v1/models to report 200 before giving up.
                                    # Added 2026-07-13: CONFIRMED (not assumed) that Cloud Run's own
                                    # TCP-only startup probe marks this container "Ready" as soon as
                                    # APIServer binds the port, well before EngineCore/the model is
                                    # actually able to serve — a real log showed APIServer's own startup
                                    # banner ~1 minute before "Starting to load model" even began. Without
                                    # this watchdog, a container stuck in that state (EngineCore crashed
                                    # or never started) looks "Ready" to Cloud Run forever, serving 404s
                                    # to every real request — see transferable-skills/memory/gcp-deployment.md's
                                    # 2026-07-13 entries for the live incident that motivated this.
: "${LMSTUDIO_WATCHDOG_POLL_SECONDS:=10}"       # same interval as driver.py's own readiness poll

export HF_HOME="${HF_HOME:-${HOME}/.cache/huggingface}"

echo "[entrypoint] vLLM home: ${HOME}, HF_HOME: ${HF_HOME}"
echo "[entrypoint] serving ${MODEL_ID} (context ${MODEL_CONTEXT_LENGTH}, gpu_memory_utilization=${GPU_MEMORY_UTILIZATION}, reasoning_parser=${LMSTUDIO_REASONING_PARSER:-none}, gpu_type=${GPU_TYPE:-unknown}, vram=${LMSTUDIO_VRAM_GB:-unknown}GB)…"
# No explicit --quantization flag: vLLM auto-detects quantization from the
# checkpoint's own HF config (quantization_config field) when present — the
# current default, google/gemma-4-31B-it, has none at all (plain BF16, no
# quantization); Qwen/Qwen3.6-35B-A3B-FP8 (an earlier default) carried an
# fp8 quantization_config, and google/gemma-4-31B-it-qat-w4a16-ct (an even
# earlier, never-deployed default) carried a compressed-tensors/w4a16 one.
# A hardcoded flag here would silently be WRONG the moment MODEL_ID points at
# a differently-quantized (or unquantized) checkpoint — this happened once
# already in this file (an earlier version hardcoded
# "--quantization compressed-tensors", wrong the moment the model changed).
#
# No --kv-cache-dtype flag: left at vLLM's own "auto" default. A prior
# version of this file hardcoded "--kv-cache-dtype bfloat16" to sidestep the
# uncalibrated fp8_e4m3 (scale=1.0) numerics "auto" resolves to on this GPU
# generation — CONFIRMED WRONG via a live crash (2026-07-14): vLLM forces
# the TRITON_ATTN backend for any Gemma 4 model ("Gemma4 model has
# heterogeneous head dimensions... Forcing TRITON_ATTN backend"), and that
# backend's triton_reshape_and_cache_flash kernel asserts
# `kv_cache_dtype == "auto" or kv_cache_dtype.startswith("fp8")` — an
# explicit "bfloat16" string fails that assertion every time, right after
# the model finishes loading, on every single startup attempt. Cloud Run's
# TCP startup probe then never observes port 8000 open across the whole
# crash-loop, so the deploy fails with a "startup probes timed out" error
# that looks like a slow-load timing issue but is actually this deterministic
# crash. If the "auto" → uncalibrated fp8 numerics concern turns out to
# matter for this pipeline's output quality, revisit with a calibrated fp8
# checkpoint rather than reintroducing an explicit bfloat16 value.
#
# --reasoning-parser only passed when LMSTUDIO_REASONING_PARSER is set (e.g.
# "qwen3") — Qwen3.6's "thinking" output needs this to keep chain-of-thought
# out of the main response content; hardcoding it would break a model with
# no reasoning parser of that name (e.g. Gemma).
#
# --enable-auto-tool-choice + --tool-call-parser only passed when
# LMSTUDIO_TOOL_CALL_PARSER is set (e.g. "hermes" for Qwen3-class models) —
# without this, vLLM does NOT parse OpenAI-style tool/function calls at all;
# it returns them as plain text instead of a structured tool_calls array,
# which would silently break every ADK FunctionTool-using agent in this
# pipeline (nearly all of them). Verified via vLLM's own tool-calling docs,
# not guessed. Conditional, not hardcoded, for the same reason as
# --reasoning-parser: the right parser name is model-family-specific.
#
# Captured via tee (same pattern as lmstudio-entrypoint.sh's lms load/get)
# so a crash prints real diagnostics instead of Cloud Run's bare "Container
# called exit(1)" — this is a first attempt on a new serving stack and will
# very likely need log evidence to iterate on, same as the LM Studio path did.
VLLM_ARGS=(
  --gpu-memory-utilization "${GPU_MEMORY_UTILIZATION}"
  --max-model-len "${MODEL_CONTEXT_LENGTH}"
  --host 0.0.0.0 --port "${PORT}"
)
if [ -n "${LMSTUDIO_REASONING_PARSER}" ]; then
  VLLM_ARGS+=(--reasoning-parser "${LMSTUDIO_REASONING_PARSER}")
fi
if [ -n "${LMSTUDIO_TOOL_CALL_PARSER}" ]; then
  VLLM_ARGS+=(--enable-auto-tool-choice --tool-call-parser "${LMSTUDIO_TOOL_CALL_PARSER}")
fi
if [ -n "${LMSTUDIO_CHAT_TEMPLATE}" ]; then
  VLLM_ARGS+=(--chat-template "${LMSTUDIO_CHAT_TEMPLATE}")
fi
if [ "${LMSTUDIO_ENABLE_THINKING}" = "true" ]; then
  VLLM_ARGS+=(--default-chat-template-kwargs '{"enable_thinking": true}')
fi
if [ -n "${VLLM_API_KEY}" ]; then
  VLLM_ARGS+=(--api-key "${VLLM_API_KEY}")
fi

SERVE_LOG="$(mktemp)"

# Run vllm serve in the BACKGROUND so this script can supervise it with a
# real readiness self-check, instead of just blocking in the foreground and
# trusting Cloud Run's own TCP-only startup probe (which does NOT reflect
# real model readiness — see LMSTUDIO_WATCHDOG_TIMEOUT_SECONDS above).
# stdout/stderr still captured to SERVE_LOG, still mirrored live to the
# container's own stdout (via the background `tail -f`) so Cloud Run logs
# look the same as before this change.
vllm serve "${MODEL_ID}" "${VLLM_ARGS[@]}" > "${SERVE_LOG}" 2>&1 &
VLLM_PID=$!
tail -f "${SERVE_LOG}" &
TAIL_PID=$!

# Forward Cloud Run's shutdown signal to the actual vllm serve process —
# without this trap, backgrounding the process means bash (PID 1 in the
# container) would not otherwise propagate SIGTERM to it on scale-down/
# redeploy, and the container could take much longer to stop than it should.
cleanup() {
  kill "${TAIL_PID}" 2>/dev/null || true
  if kill -0 "${VLLM_PID}" 2>/dev/null; then
    kill -TERM "${VLLM_PID}" 2>/dev/null || true
    wait "${VLLM_PID}" 2>/dev/null || true
  fi
  rm -f "${SERVE_LOG}"
}
trap 'cleanup; exit 0' TERM INT

WATCHDOG_HEADERS=()
if [ -n "${VLLM_API_KEY}" ]; then
  WATCHDOG_HEADERS=(-H "Authorization: Bearer ${VLLM_API_KEY}")
fi

echo "[entrypoint] watchdog: waiting up to ${LMSTUDIO_WATCHDOG_TIMEOUT_SECONDS}s for ${MODEL_ID} to report ready on http://localhost:${PORT}/v1/models…"
deadline=$(( $(date +%s) + LMSTUDIO_WATCHDOG_TIMEOUT_SECONDS ))
ready=0
while [ "$(date +%s)" -lt "${deadline}" ]; do
  if ! kill -0 "${VLLM_PID}" 2>/dev/null; then
    echo "[entrypoint] vllm serve process exited during startup, before ever becoming ready" >&2
    break
  fi
  status=$(curl -s -o /dev/null -w '%{http_code}' "${WATCHDOG_HEADERS[@]+"${WATCHDOG_HEADERS[@]}"}" "http://localhost:${PORT}/v1/models" 2>/dev/null || echo 000)
  if [ "${status}" = "200" ]; then
    echo "[entrypoint] watchdog: ${MODEL_ID} is up (200 from /v1/models)"
    ready=1
    break
  fi
  sleep "${LMSTUDIO_WATCHDOG_POLL_SECONDS}"
done

if [ "${ready}" -ne 1 ]; then
  echo "[entrypoint] watchdog: model never became ready within ${LMSTUDIO_WATCHDOG_TIMEOUT_SECONDS}s — failing loudly instead of staying silently 'Ready' with a non-functional backend" >&2
  echo "[entrypoint] last 50 lines of vllm serve output:" >&2
  tail -n 50 "${SERVE_LOG}" >&2
  echo "[entrypoint] config at failure: model=${MODEL_ID} context=${MODEL_CONTEXT_LENGTH} gpu_memory_utilization=${GPU_MEMORY_UTILIZATION} gpu_type=${GPU_TYPE:-unknown} vram=${LMSTUDIO_VRAM_GB:-unknown}GB" >&2
  cleanup
  exit 1
fi

# Model confirmed ready — the crash-loop risk this watchdog exists for is
# now behind us. Supervise the real process for the rest of the container's
# life; if it crashes later, exit with its real code so Cloud Run sees a
# genuine crash-loop instead of a silently-dead container.
set +e
wait "${VLLM_PID}"
serve_exit=$?
set -e
kill "${TAIL_PID}" 2>/dev/null || true
if [ "${serve_exit}" -ne 0 ]; then
  echo "[entrypoint] vllm serve exited (code ${serve_exit}) — last 50 lines of ${SERVE_LOG}:" >&2
  tail -n 50 "${SERVE_LOG}" >&2
  rm -f "${SERVE_LOG}"
  exit "${serve_exit}"
fi
rm -f "${SERVE_LOG}"
echo "[entrypoint] vllm serve exited cleanly (graceful shutdown)"
