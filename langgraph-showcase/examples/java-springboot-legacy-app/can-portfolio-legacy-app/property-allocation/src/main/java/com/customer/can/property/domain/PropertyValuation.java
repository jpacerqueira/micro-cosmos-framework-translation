package com.customer.can.property.domain;

import javax.persistence.*;
import java.math.BigDecimal;
import java.util.Date;

@Entity
@Table(name = "PROPERTY_VALUATION")
public class PropertyValuation {
    @Id
    @Column(name = "ID", length = 36)
    private String id;

    @Column(name = "PROPERTY_ID", length = 36, nullable = false)
    private String propertyId;

    @Column(name = "PORTFOLIO_ID", length = 36, nullable = false)
    private String portfolioId;

    @Column(name = "VALUATION_AMOUNT", precision = 18, scale = 2)
    private BigDecimal valuationAmount;

    @Column(name = "VALUATION_DATE")
    @Temporal(TemporalType.DATE)
    private Date valuationDate;

    @Column(name = "VALUER_COMPANY_ID", length = 36)
    private String valuerCompanyId;

    @Column(name = "STATUS", length = 50)
    private String status = "PENDING";

    @Column(name = "CREATED_AT")
    @Temporal(TemporalType.TIMESTAMP)
    private Date createdAt;

    @PrePersist
    public void prePersist() {
        if (this.id == null) {
            this.id = java.util.UUID.randomUUID().toString();
        }
        this.createdAt = new Date();
    }

    public String getId() { return id; }
    public void setId(String id) { this.id = id; }
    public String getPropertyId() { return propertyId; }
    public void setPropertyId(String propertyId) { this.propertyId = propertyId; }
    public String getPortfolioId() { return portfolioId; }
    public void setPortfolioId(String portfolioId) { this.portfolioId = portfolioId; }
    public BigDecimal getValuationAmount() { return valuationAmount; }
    public void setValuationAmount(BigDecimal valuationAmount) { this.valuationAmount = valuationAmount; }
    public Date getValuationDate() { return valuationDate; }
    public void setValuationDate(Date valuationDate) { this.valuationDate = valuationDate; }
    public String getValuerCompanyId() { return valuerCompanyId; }
    public void setValuerCompanyId(String valuerCompanyId) { this.valuerCompanyId = valuerCompanyId; }
    public String getStatus() { return status; }
    public void setStatus(String status) { this.status = status; }
    public Date getCreatedAt() { return createdAt; }
    public void setCreatedAt(Date createdAt) { this.createdAt = createdAt; }
}
