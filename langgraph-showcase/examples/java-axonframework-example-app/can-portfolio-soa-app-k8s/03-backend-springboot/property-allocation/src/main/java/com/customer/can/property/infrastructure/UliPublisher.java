package com.customer.can.property.infrastructure;

import com.customer.can.common.uli.UliEnvelope;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.nats.client.Connection;
import io.nats.client.JetStream;
import io.nats.client.JetStreamApiException;
import io.nats.client.api.PublishAck;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.time.Instant;
import java.util.Map;
import java.util.UUID;

/**
 * Publishes domain events to NATS JetStream as ULI envelopes. This is the
 * service-side end of the SAD's "Universal Layer of Interoperability":
 * downstream consumers (workflow process managers, the search projection,
 * the Event Hubs bridge) subscribe to {@code uli.events.>} subjects and
 * decode the envelope without knowing about Axon.
 */
@Component
public class UliPublisher {

    private static final Logger log = LoggerFactory.getLogger(UliPublisher.class);

    private final JetStream jetStream;
    private final ObjectMapper mapper;
    private final String source;

    public UliPublisher(Connection nats, ObjectMapper mapper) throws IOException {
        this.jetStream = nats.jetStream();
        this.mapper = mapper;
        this.source = "property-allocation";
    }

    public <T> void publish(String subject, String type, T payload) {
        String corrId = MDC.get("correlationId");
        if (corrId == null) corrId = UUID.randomUUID().toString();

        UliEnvelope<T> env = new UliEnvelope<>(
                UUID.randomUUID().toString(),
                corrId,
                MDC.get("causationId"),
                subject,
                type,
                source,
                Instant.now(),
                Map.of("trace.parent", String.valueOf(MDC.get("traceId"))),
                payload
        );
        try {
            byte[] data = mapper.writeValueAsBytes(env);
            PublishAck ack = jetStream.publish(subject, data);
            log.debug("ULI published subject={} seq={} stream={}",
                    subject, ack.getSeqno(), ack.getStream());
        } catch (IOException | JetStreamApiException e) {
            log.error("ULI publish failed for subject={}", subject, e);
            throw new RuntimeException("ULI publish failed", e);
        }
    }
}
