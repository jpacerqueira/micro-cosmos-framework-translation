#!/usr/bin/env bash
###############################################################################
# uli-bootstrap.sh - idempotent JetStream provisioning.
#
# Reads streams/streams.yaml and applies it via the `nats` CLI. Safe to run
# repeatedly - existing streams/consumers are updated, missing ones created.
#
# Requires: nats-cli >= 0.1.4, yq.
#   Usage:   ./uli-bootstrap.sh nats://nats.can-system.svc.cluster.local:4222
###############################################################################
set -euo pipefail

NATS_URL="${1:-nats://localhost:4222}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STREAMS_YAML="${SCRIPT_DIR}/../streams/streams.yaml"

command -v nats >/dev/null || { echo "nats CLI not found"; exit 1; }
command -v yq   >/dev/null || { echo "yq not found";       exit 1; }

echo "Provisioning streams against ${NATS_URL}"

stream_count=$(yq '.streams | length' "${STREAMS_YAML}")
for i in $(seq 0 $((stream_count - 1))); do
  name=$(yq ".streams[$i].name" "${STREAMS_YAML}")
  subjects=$(yq ".streams[$i].subjects | join(\",\")" "${STREAMS_YAML}")
  retention=$(yq ".streams[$i].retention" "${STREAMS_YAML}")
  storage=$(yq ".streams[$i].storage" "${STREAMS_YAML}")
  max_age=$(yq ".streams[$i].max_age // \"0\"" "${STREAMS_YAML}")
  max_bytes=$(yq ".streams[$i].max_bytes // -1" "${STREAMS_YAML}")
  replicas=$(yq ".streams[$i].num_replicas // 1" "${STREAMS_YAML}")

  echo " -> stream ${name} (${subjects})"
  nats --server="${NATS_URL}" stream add "${name}" \
    --subjects="${subjects}" \
    --retention="${retention}" \
    --storage="${storage}" \
    --max-age="${max_age}" \
    --max-bytes="${max_bytes}" \
    --replicas="${replicas}" \
    --discard=old \
    --dupe-window=2m \
    --defaults || \
  nats --server="${NATS_URL}" stream update "${name}" \
    --subjects="${subjects}" \
    --retention="${retention}" \
    --storage="${storage}" \
    --max-age="${max_age}" \
    --max-bytes="${max_bytes}" \
    --replicas="${replicas}" \
    --defaults
done

consumer_count=$(yq '.consumers | length' "${STREAMS_YAML}")
for i in $(seq 0 $((consumer_count - 1))); do
  stream=$(yq    ".consumers[$i].stream"          "${STREAMS_YAML}")
  name=$(yq      ".consumers[$i].name"            "${STREAMS_YAML}")
  durable=$(yq   ".consumers[$i].durable"         "${STREAMS_YAML}")
  filter=$(yq    ".consumers[$i].filter_subject"  "${STREAMS_YAML}")
  ack_wait=$(yq  ".consumers[$i].ack_wait"        "${STREAMS_YAML}")
  max_deliver=$(yq ".consumers[$i].max_deliver"   "${STREAMS_YAML}")

  echo " -> consumer ${stream}/${name} filter=${filter}"
  nats --server="${NATS_URL}" consumer add "${stream}" "${name}" \
    --pull \
    --deliver=all \
    --ack=explicit \
    --filter="${filter}" \
    --wait="${ack_wait}" \
    --max-deliver="${max_deliver}" \
    --replay=instant \
    --defaults || \
  nats --server="${NATS_URL}" consumer update "${stream}" "${name}" \
    --filter="${filter}" \
    --wait="${ack_wait}" \
    --max-deliver="${max_deliver}" \
    --defaults
done

echo "Done."
