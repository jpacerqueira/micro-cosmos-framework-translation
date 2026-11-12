package com.customer.can.uli.bridge;

import com.azure.identity.DefaultAzureCredentialBuilder;
import com.azure.messaging.eventhubs.EventData;
import com.azure.messaging.eventhubs.EventDataBatch;
import com.azure.messaging.eventhubs.EventHubClientBuilder;
import com.azure.messaging.eventhubs.EventHubProducerClient;

import io.nats.client.Connection;
import io.nats.client.JetStream;
import io.nats.client.JetStreamSubscription;
import io.nats.client.Message;
import io.nats.client.Nats;
import io.nats.client.PullSubscribeOptions;
import io.nats.client.api.AckPolicy;
import io.nats.client.api.ConsumerConfiguration;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.annotation.Bean;
import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.util.List;

/**
 * NATS -> Event Hubs bridge.
 *
 * <p>Pulls batches of {@code uli.events.>} messages from a durable JetStream
 * consumer and republishes them on a Kafka-compatible Azure Event Hubs hub.
 * Authentication uses workload identity ({@code DefaultAzureCredential}).
 *
 * <p>Acknowledgement is post-publish - we only ack NATS once Event Hubs
 * confirms the batch. On Event Hubs failure the messages are NAK'd and
 * JetStream redelivers up to {@code max_deliver} times before parking
 * them on the DLQ stream.
 */
@SpringBootApplication
@EnableScheduling
public class EventHubBridgeApplication {

    public static void main(String[] args) {
        SpringApplication.run(EventHubBridgeApplication.class, args);
    }

    @Bean(destroyMethod = "close")
    public Connection nats(@Value("${nats.url}") String url) throws Exception {
        return Nats.connect(url);
    }

    @Bean(destroyMethod = "close")
    public EventHubProducerClient producer(
            @Value("${eventhub.namespace-fqdn}") String fqdn,
            @Value("${eventhub.name}") String hub) {
        return new EventHubClientBuilder()
                .credential(fqdn, hub, new DefaultAzureCredentialBuilder().build())
                .buildProducerClient();
    }
}

@Component
class BridgeLoop {

    private static final Logger log = LoggerFactory.getLogger(BridgeLoop.class);
    private static final int BATCH = 100;
    private static final Duration WAIT = Duration.ofSeconds(2);

    private final JetStream jetStream;
    private final EventHubProducerClient producer;
    private final JetStreamSubscription sub;

    BridgeLoop(Connection nats, EventHubProducerClient producer) throws Exception {
        this.producer = producer;
        this.jetStream = nats.jetStream();

        ConsumerConfiguration cc = ConsumerConfiguration.builder()
                .durable("eventhub-bridge")
                .ackPolicy(AckPolicy.Explicit)
                .ackWait(Duration.ofSeconds(30))
                .maxDeliver(8)
                .filterSubject("uli.events.>")
                .build();
        this.sub = jetStream.subscribe("uli.events.>",
                PullSubscribeOptions.builder().durable("eventhub-bridge").configuration(cc).build());
    }

    @Scheduled(fixedDelayString = "${bridge.poll-millis:500}")
    public void pump() {
        List<Message> batch = sub.fetch(BATCH, WAIT);
        if (batch.isEmpty()) return;

        // Ack/nak is scoped per Event-Hubs sub-batch, not the whole original NATS
        // poll: when one pull doesn't fit a single EventDataBatch, tryAdd() fails
        // mid-loop and a new sub-batch is started. Acking only the messages that
        // sub-batch actually contains — immediately after IT sends successfully —
        // means a LATER sub-batch's failure only NAKs the messages that were never
        // published, instead of NAKing the whole original batch (which would cause
        // JetStream to redeliver, and this bridge to republish, messages an earlier
        // sub-batch already durably sent to Event Hubs).
        EventDataBatch ehBatch = producer.createBatch();
        List<Message> pending = new java.util.ArrayList<>();
        for (Message m : batch) {
            EventData data = new EventData(m.getData());
            data.getProperties().put("nats.subject", m.getSubject());
            if (!ehBatch.tryAdd(data)) {
                if (!flushAndAck(ehBatch, pending)) {
                    return; // already NAK'd exactly the messages that failed to send
                }
                pending = new java.util.ArrayList<>();
                ehBatch = producer.createBatch();
                ehBatch.tryAdd(data);
            }
            pending.add(m);
        }
        flushAndAck(ehBatch, pending);
    }

    /** Sends one Event Hubs sub-batch and ack/naks exactly the NATS messages it
     * corresponds to. Returns false on failure (already NAK'd). */
    private boolean flushAndAck(EventDataBatch ehBatch, List<Message> messages) {
        try {
            producer.send(ehBatch);
            for (Message m : messages) m.ack();
            log.debug("Bridged {} messages to Event Hubs", messages.size());
            return true;
        } catch (Exception e) {
            log.error("Event Hubs publish failed - NAKing {} message(s)", messages.size(), e);
            for (Message m : messages) m.nak();
            return false;
        }
    }
}
