#!/bin/sh
# JetStream stream bootstrap — runs once at startup via nats-setup container.
# Uses nats-box CLI. Replicas reduced to 1 for single-node local dev.
set -e

NATS_URL=${1:-nats://uli-publisher:nats-local-pass@nats:4222}

echo "Waiting for NATS JetStream..."
until nats -s "$NATS_URL" account info > /dev/null 2>&1; do
  sleep 2
done
echo "NATS ready."

create_or_update_stream() {
  NAME=$1; shift
  nats -s "$NATS_URL" stream add "$NAME" "$@" 2>/dev/null \
    || nats -s "$NATS_URL" stream edit "$NAME" "$@" 2>/dev/null \
    || echo "Stream $NAME already up-to-date."
}

# ULI_EVENTS — event log, 7-day retention
create_or_update_stream ULI_EVENTS \
  --subjects "uli.events.>" \
  --storage file --replicas 1 \
  --retention limits \
  --max-age 168h \
  --dupe-window 2m \
  --defaults

# ULI_COMMANDS — work-queue, 24-hour retention
create_or_update_stream ULI_COMMANDS \
  --subjects "uli.commands.>" \
  --storage file --replicas 1 \
  --retention workqueue \
  --max-age 24h \
  --defaults

# ULI_DLQ — dead-letter, 30-day retention
create_or_update_stream ULI_DLQ \
  --subjects "uli.dlq.>" \
  --storage file --replicas 1 \
  --retention limits \
  --max-age 720h \
  --defaults

echo "JetStream streams provisioned."
