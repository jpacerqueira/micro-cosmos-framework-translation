package com.customer.can.property.domain;

import javax.persistence.*;
import java.util.Date;

@Entity
@Table(name = "BROKER_ALLOCATION")
public class BrokerAllocation {
    @Id
    @Column(name = "ID", length = 36)
    private String id;

    @Column(name = "PROPERTY_ID", length = 36, nullable = false)
    private String propertyId;

    @Column(name = "PORTFOLIO_ID", length = 36, nullable = false)
    private String portfolioId;

    @Column(name = "BROKER_COMPANY_ID", length = 36)
    private String brokerCompanyId;

    @Column(name = "ASSIGNED_AT")
    @Temporal(TemporalType.TIMESTAMP)
    private Date assignedAt;

    @Column(name = "STATUS", length = 50)
    private String status = "PENDING";

    @PrePersist
    public void prePersist() {
        if (this.id == null) {
            this.id = java.util.UUID.randomUUID().toString();
        }
    }

    public String getId() { return id; }
    public void setId(String id) { this.id = id; }
    public String getPropertyId() { return propertyId; }
    public void setPropertyId(String propertyId) { this.propertyId = propertyId; }
    public String getPortfolioId() { return portfolioId; }
    public void setPortfolioId(String portfolioId) { this.portfolioId = portfolioId; }
    public String getBrokerCompanyId() { return brokerCompanyId; }
    public void setBrokerCompanyId(String brokerCompanyId) { this.brokerCompanyId = brokerCompanyId; }
    public Date getAssignedAt() { return assignedAt; }
    public void setAssignedAt(Date assignedAt) { this.assignedAt = assignedAt; }
    public String getStatus() { return status; }
    public void setStatus(String status) { this.status = status; }
}
