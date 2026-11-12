package com.customer.can.workflow.messaging;

import com.customer.can.common.messaging.JmsEnvelope;
import com.customer.can.workflow.service.AllocationWorkflowService;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.Logger;
import org.apache.logging.log4j.ThreadContext;
import org.springframework.jms.annotation.JmsListener;
import org.springframework.stereotype.Component;

@Component
public class WorkflowEventListener {
    private static final Logger log = LogManager.getLogger(WorkflowEventListener.class);

    private final AllocationWorkflowService workflowService;
    private final ObjectMapper objectMapper;

    public WorkflowEventListener(AllocationWorkflowService workflowService, ObjectMapper objectMapper) {
        this.workflowService = workflowService;
        this.objectMapper = objectMapper;
    }

    @JmsListener(destination = "portfolio.events", containerFactory = "jmsListenerContainerFactory")
    public void handlePortfolioEvent(String message) {
        try {
            JmsEnvelope envelope = objectMapper.readValue(message, JmsEnvelope.class);
            ThreadContext.put("correlationId", envelope.getCorrelationId());
            log.info("action=workflow_event_received eventType={}", envelope.getEventType());

            if ("PROPERTY_ADDED".equals(envelope.getEventType())) {
                String payload = envelope.getPayload();
                com.fasterxml.jackson.databind.JsonNode node = objectMapper.readTree(payload);
                String propertyId = node.path("id").asText();
                String portfolioId = node.path("portfolio").path("id").asText();
                if (propertyId != null && !propertyId.isEmpty()) {
                    workflowService.createOrGet(propertyId, portfolioId);
                    log.info("action=workflow_initialized propertyId={}", propertyId);
                }
            }
        } catch (Exception e) {
            log.error("action=workflow_event_error error={}", e.getMessage(), e);
        } finally {
            ThreadContext.clearAll();
        }
    }
}
