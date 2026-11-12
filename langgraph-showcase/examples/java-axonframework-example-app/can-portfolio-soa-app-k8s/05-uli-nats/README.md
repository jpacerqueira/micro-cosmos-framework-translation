# 05-uli-nats - Universal Layer of Interoperability

Every message that crosses a service boundary is wrapped in a **ULI envelope**
and travels over **NATS JetStream** (in-cluster) and/or **Azure Event Hubs**
(out-of-cluster, durable, audit-friendly). Both transports carry the same
envelope, so downstream services do not care which one a message arrived on.

## Why a layer?

The SAD calls for asynchronous communication between microservices
(Choreography pattern), centralised correlation/causation tracking, and
the ability to bridge events to long-term durable storage. Rolling that
into one library and one message format - the ULI - gives us:

- A single envelope shape across NATS, Kafka/Event Hubs, and Axon's bus.
- Correlation/causation propagation for free (filled by the library, not
  by every service).
- A consistent dead-letter and replay strategy.
- Loose coupling: services subscribe to subjects, not to each other.

## Envelope

```json
{
  "messageId":     "0d6b…",
  "correlationId": "9c1a…",
  "causationId":   "0a35…",
  "subject":       "uli.events.portfolio.PortfolioCreated",
  "type":          "PortfolioCreated",
  "source":        "property-allocation",
  "timestamp":     "2026-05-05T10:15:00.123Z",
  "headers":       { "tenant": "internal", "trace.parent": "00-…" },
  "payload":       { ... typed event body ... }
}
```

## Subject naming

```
uli.<kind>.<bounded-context>.<MessageType>
```

| Kind | Examples |
|---|---|
| `commands` | `uli.commands.portfolio.AllocatePropertyToBroker` |
| `events`   | `uli.events.portfolio.PropertyAllocatedToBroker` |
| `queries`  | `uli.queries.search.PortfolioByName` |
| `dlq`      | `uli.dlq.portfolio.events` |

## Streams (JetStream)

| Stream | Subjects | Retention | Replicas |
|---|---|---|---|
| `ULI_EVENTS`   | `uli.events.>`   | 7 days, 50 GiB | 3 |
| `ULI_COMMANDS` | `uli.commands.>` | 24 hours       | 3 |
| `ULI_DLQ`      | `uli.dlq.>`      | 30 days        | 3 |

## Event Hubs bridge

A small Spring Boot service (`bridge/eventhub-bridge`) consumes
`uli.events.>` from NATS and republishes onto a Kafka-compatible Azure
Event Hubs namespace. This gives you:

- Durable, geo-redundant retention beyond the JetStream window.
- A consumption point for analytics tools that speak Kafka.
- An audit-friendly replay source.

## Consumer guidelines

1. Always acknowledge messages explicitly - never auto-ack.
2. Use **durable consumers** with named consumer groups so re-deploys
   resume from the right offset.
3. Dedup on `messageId` via `uli.inbox` before applying side effects.
4. On exception, re-publish to `uli.dlq.<subject>` with the error.
