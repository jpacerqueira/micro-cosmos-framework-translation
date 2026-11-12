package com.customer.can.common.uli;

import com.fasterxml.jackson.annotation.JsonInclude;

import java.time.Instant;
import java.util.Map;
import java.util.UUID;

/**
 * Universal Layer of Interoperability (ULI) envelope.
 *
 * <p>Every message that crosses a service boundary - whether it travels over
 * NATS, Axon command/event bus, Event Hubs/Kafka, or HTTP - is wrapped in an
 * envelope of this shape. Wrapping is what makes the layer "universal":
 * downstream services do not care how the message arrived, only that the
 * envelope conforms.
 *
 * <p>Fields:
 * <ul>
 *   <li>{@code messageId} - unique per message; used for idempotency.</li>
 *   <li>{@code correlationId} - shared by all messages in a logical request,
 *       enabling cross-service tracing as required by the SAD's
 *       "Correlate Requests with a unique Correlation_ID" pattern.</li>
 *   <li>{@code causationId} - the {@code messageId} of the message that
 *       caused this one. Lets us reconstruct command/event chains.</li>
 *   <li>{@code subject} - subject path (NATS-style), e.g.
 *       {@code uli.events.portfolio.PortfolioCreated}.</li>
 *   <li>{@code type} - canonical type name of the payload.</li>
 *   <li>{@code source} - service that produced the message
 *       (e.g. {@code property-allocation}).</li>
 *   <li>{@code payload} - the message body, opaque at this layer.</li>
 *   <li>{@code headers} - arbitrary metadata (tenant, user, trace context).</li>
 * </ul>
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record UliEnvelope<T>(
        String messageId,
        String correlationId,
        String causationId,
        String subject,
        String type,
        String source,
        Instant timestamp,
        Map<String, String> headers,
        T payload
) {

    public static <T> UliEnvelope<T> of(String subject, String type, String source, T payload) {
        return new UliEnvelope<>(
                UUID.randomUUID().toString(),
                UUID.randomUUID().toString(),
                null,
                subject,
                type,
                source,
                Instant.now(),
                Map.of(),
                payload
        );
    }

    public <U> UliEnvelope<U> withPayload(String newType, U newPayload) {
        return new UliEnvelope<>(
                UUID.randomUUID().toString(),
                this.correlationId, // propagate
                this.messageId,     // becomes causation
                this.subject,
                newType,
                this.source,
                Instant.now(),
                this.headers,
                newPayload
        );
    }
}
