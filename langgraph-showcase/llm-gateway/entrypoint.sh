#!/bin/sh
# LiteLLM Proxy: load exactly one profile. Dormant backends stay on disk unused.
set -eu
PROFILE="${LLM_PROFILE:-ollama}"
case "$PROFILE" in
  ollama|lmstudio|bedrock|vertex|vllm) ;;
  *)
    echo "llm-gateway: unknown LLM_PROFILE='$PROFILE' (use ollama, lmstudio, bedrock, vertex, or vllm)" >&2
    exit 1
    ;;
esac
CONFIG="/app/config/profiles/${PROFILE}.yaml"
if [ ! -f "$CONFIG" ]; then
  echo "llm-gateway: missing profile file $CONFIG" >&2
  exit 1
fi
echo "llm-gateway: active_profile=${PROFILE} config=${CONFIG}"
echo "llm-gateway: dormant=ollama,lmstudio,bedrock,vertex,vllm (minus ${PROFILE}); no failover"
export PYTHONPATH="/app/config/profiles:/app/config:${PYTHONPATH:-}"
mkdir -p /app/logs 2>/dev/null || true
# Skip the image's Prisma/DB entrypoint — this proxy is stateless YAML only.
# --detailed_debug: full LiteLLM request/response traces; custom callback adds UTC timeframes.
exec litellm --config "$CONFIG" --port 4000 --host 0.0.0.0 --detailed_debug
