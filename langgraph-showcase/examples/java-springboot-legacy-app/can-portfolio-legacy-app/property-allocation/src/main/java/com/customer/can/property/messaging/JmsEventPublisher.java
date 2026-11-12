package com.customer.can.property.messaging;

import com.customer.can.common.messaging.JmsEnvelope;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.Logger;
import org.apache.logging.log4j.ThreadContext;
import org.springframework.jms.core.JmsTemplate;
import org.springframework.stereotype.Component;

@Component
public class JmsEventPublisher {
    private static final Logger log = LogManager.getLogger(JmsEventPublisher.class);
    private static final String PORTFOLIO_TOPIC = "portfolio.events";

    private final JmsTemplate jmsTemplate;
    private final ObjectMapper objectMapper;

    public JmsEventPublisher(JmsTemplate jmsTemplate, ObjectMapper objectMapper) {
        this.jmsTemplate = jmsTemplate;
        this.objectMapper = objectMapper;
    }

    public void publishPortfolioEvent(String eventType, String aggregateId, String payload) {
        JmsEnvelope envelope = new JmsEnvelope(
                ThreadContext.get("correlationId"),
                eventType,
                "property-allocation",
                payload
        );
        try {
            String json = objectMapper.writeValueAsString(envelope);
            jmsTemplate.convertAndSend(PORTFOLIO_TOPIC, json);
            log.info("action=publish_event eventType={} aggregateId={}", eventType, aggregateId);
        } catch (JsonProcessingException e) {
            log.error("Failed to serialize JMS envelope for event={}", eventType, e);
        }
    }
}
