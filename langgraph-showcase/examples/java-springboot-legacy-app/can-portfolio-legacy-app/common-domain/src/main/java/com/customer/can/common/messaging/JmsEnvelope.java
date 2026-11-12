package com.customer.can.common.messaging;

import java.io.Serializable;
import java.util.Date;
import java.util.UUID;

public class JmsEnvelope implements Serializable {
    private static final long serialVersionUID = 1L;

    private String messageId;
    private String correlationId;
    private String eventType;
    private String context;
    private String payload;
    private Date timestamp;

    public JmsEnvelope() {
        this.messageId = UUID.randomUUID().toString();
        this.timestamp = new Date();
    }

    public JmsEnvelope(String correlationId, String eventType, String context, String payload) {
        this();
        this.correlationId = correlationId;
        this.eventType = eventType;
        this.context = context;
        this.payload = payload;
    }

    public String getMessageId() { return messageId; }
    public void setMessageId(String messageId) { this.messageId = messageId; }
    public String getCorrelationId() { return correlationId; }
    public void setCorrelationId(String correlationId) { this.correlationId = correlationId; }
    public String getEventType() { return eventType; }
    public void setEventType(String eventType) { this.eventType = eventType; }
    public String getContext() { return context; }
    public void setContext(String context) { this.context = context; }
    public String getPayload() { return payload; }
    public void setPayload(String payload) { this.payload = payload; }
    public Date getTimestamp() { return timestamp; }
    public void setTimestamp(Date timestamp) { this.timestamp = timestamp; }
}
