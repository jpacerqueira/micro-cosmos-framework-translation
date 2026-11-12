package com.customer.can.vdr.messaging;

import com.customer.can.common.messaging.JmsEnvelope;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.Logger;
import org.apache.logging.log4j.ThreadContext;
import org.springframework.jms.core.JmsTemplate;
import org.springframework.stereotype.Component;

@Component
public class DocumentEventPublisher {
    private static final Logger log = LogManager.getLogger(DocumentEventPublisher.class);
    private static final String VDR_TOPIC = "vdr.events";

    private final JmsTemplate jmsTemplate;
    private final ObjectMapper objectMapper;

    public DocumentEventPublisher(JmsTemplate jmsTemplate, ObjectMapper objectMapper) {
        this.jmsTemplate = jmsTemplate;
        this.objectMapper = objectMapper;
    }

    public void publishDocumentEvent(String eventType, String documentId, String portfolioId) {
        try {
            JmsEnvelope envelope = new JmsEnvelope(
                    ThreadContext.get("correlationId"), eventType, "vdr-ingestion",
                    "{\"documentId\":\"" + documentId + "\",\"portfolioId\":\"" + portfolioId + "\"}");
            jmsTemplate.convertAndSend(VDR_TOPIC, objectMapper.writeValueAsString(envelope));
        } catch (JsonProcessingException e) {
            log.error("Failed to publish document event", e);
        }
    }
}
