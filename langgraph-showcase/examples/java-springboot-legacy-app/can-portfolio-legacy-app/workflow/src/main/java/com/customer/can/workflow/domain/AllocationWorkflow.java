package com.customer.can.workflow.domain;

import javax.persistence.*;
import java.util.Date;

@Entity
@Table(name = "ALLOCATION_WORKFLOW")
public class AllocationWorkflow {
    @Id
    @Column(name = "ID", length = 36)
    private String id;

    @Column(name = "PROPERTY_ID", length = 36, nullable = false)
    private String propertyId;

    @Column(name = "PORTFOLIO_ID", length = 36, nullable = false)
    private String portfolioId;

    @Column(name = "STATE", length = 50, nullable = false)
    private String state = "PENDING";

    @Column(name = "BROKER_ID", length = 36)
    private String brokerId;

    @Column(name = "VALUER_ID", length = 36)
    private String valuerId;

    @Column(name = "UPDATED_AT")
    @Temporal(TemporalType.TIMESTAMP)
    private Date updatedAt;

    @Column(name = "CREATED_AT")
    @Temporal(TemporalType.TIMESTAMP)
    private Date createdAt;

    @PrePersist
    public void prePersist() {
        if (this.id == null) {
            this.id = java.util.UUID.randomUUID().toString();
        }
        this.createdAt = new Date();
        this.updatedAt = new Date();
    }

    @PreUpdate
    public void preUpdate() {
        this.updatedAt = new Date();
    }

    public String getId() { return id; }
    public void setId(String id) { this.id = id; }
    public String getPropertyId() { return propertyId; }
    public void setPropertyId(String propertyId) { this.propertyId = propertyId; }
    public String getPortfolioId() { return portfolioId; }
    public void setPortfolioId(String portfolioId) { this.portfolioId = portfolioId; }
    public String getState() { return state; }
    public void setState(String state) { this.state = state; }
    public String getBrokerId() { return brokerId; }
    public void setBrokerId(String brokerId) { this.brokerId = brokerId; }
    public String getValuerId() { return valuerId; }
    public void setValuerId(String valuerId) { this.valuerId = valuerId; }
    public Date getUpdatedAt() { return updatedAt; }
    public void setUpdatedAt(Date updatedAt) { this.updatedAt = updatedAt; }
    public Date getCreatedAt() { return createdAt; }
    public void setCreatedAt(Date createdAt) { this.createdAt = createdAt; }
}
