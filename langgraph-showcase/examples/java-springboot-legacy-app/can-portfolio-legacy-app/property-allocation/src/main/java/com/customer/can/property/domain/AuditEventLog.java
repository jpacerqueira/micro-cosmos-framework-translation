package com.customer.can.property.domain;

import javax.persistence.*;
import java.util.Date;

@Entity
@Table(name = "PROPERTY_JOURNAL")
public class AuditEventLog {
    @Id
    @Column(name = "ID", length = 36)
    private String id;

    @Column(name = "PORTFOLIO_ID", length = 36, nullable = false)
    private String portfolioId;

    @Column(name = "ENTITY_TYPE", length = 100)
    private String entityType;

    @Column(name = "ENTITY_ID", length = 36)
    private String entityId;

    @Column(name = "EVENT_TYPE", length = 100)
    private String eventType;

    @Column(name = "PAYLOAD", columnDefinition = "CLOB")
    private String payload;

    @Column(name = "CORRELATION_ID", length = 36)
    private String correlationId;

    @Column(name = "CREATED_AT")
    @Temporal(TemporalType.TIMESTAMP)
    private Date createdAt;

    @Column(name = "CREATED_BY", length = 100)
    private String createdBy;

    @PrePersist
    public void prePersist() {
        if (this.id == null) {
            this.id = java.util.UUID.randomUUID().toString();
        }
        this.createdAt = new Date();
    }

    public String getId() { return id; }
    public void setId(String id) { this.id = id; }
    public String getPortfolioId() { return portfolioId; }
    public void setPortfolioId(String portfolioId) { this.portfolioId = portfolioId; }
    public String getEntityType() { return entityType; }
    public void setEntityType(String entityType) { this.entityType = entityType; }
    public String getEntityId() { return entityId; }
    public void setEntityId(String entityId) { this.entityId = entityId; }
    public String getEventType() { return eventType; }
    public void setEventType(String eventType) { this.eventType = eventType; }
    public String getPayload() { return payload; }
    public void setPayload(String payload) { this.payload = payload; }
    public String getCorrelationId() { return correlationId; }
    public void setCorrelationId(String correlationId) { this.correlationId = correlationId; }
    public Date getCreatedAt() { return createdAt; }
    public void setCreatedAt(Date createdAt) { this.createdAt = createdAt; }
    public String getCreatedBy() { return createdBy; }
    public void setCreatedBy(String createdBy) { this.createdBy = createdBy; }
}
