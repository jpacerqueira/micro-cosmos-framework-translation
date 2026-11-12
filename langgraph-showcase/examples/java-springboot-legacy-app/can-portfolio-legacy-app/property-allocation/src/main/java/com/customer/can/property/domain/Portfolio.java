package com.customer.can.property.domain;

import javax.persistence.*;
import java.util.Date;
import java.util.List;

@Entity
@Table(name = "PORTFOLIO")
public class Portfolio {
    @Id
    @Column(name = "ID", length = 36)
    private String id;

    @Column(name = "NAME", nullable = false, length = 255)
    private String name;

    @Column(name = "DESCRIPTION", columnDefinition = "CLOB")
    private String description;

    @Column(name = "STATUS", length = 50)
    private String status = "OPEN";

    @Column(name = "CUT_OFF_DATE")
    @Temporal(TemporalType.DATE)
    private Date cutOffDate;

    @Column(name = "FINAL_BID_DATE")
    @Temporal(TemporalType.DATE)
    private Date finalBidDate;

    @Column(name = "PROJECT_PHASE", length = 50)
    private String projectPhase;

    @Column(name = "CREATED_AT")
    @Temporal(TemporalType.TIMESTAMP)
    private Date createdAt;

    @Column(name = "UPDATED_AT")
    @Temporal(TemporalType.TIMESTAMP)
    private Date updatedAt;

    @Column(name = "CREATED_BY", length = 36)
    private String createdBy;

    @Column(name = "CORRELATION_ID", length = 36)
    private String correlationId;

    @OneToMany(mappedBy = "portfolio", fetch = FetchType.LAZY, cascade = CascadeType.ALL)
    private List<Property> properties;

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
    public String getName() { return name; }
    public void setName(String name) { this.name = name; }
    public String getDescription() { return description; }
    public void setDescription(String description) { this.description = description; }
    public String getStatus() { return status; }
    public void setStatus(String status) { this.status = status; }
    public Date getCutOffDate() { return cutOffDate; }
    public void setCutOffDate(Date cutOffDate) { this.cutOffDate = cutOffDate; }
    public Date getFinalBidDate() { return finalBidDate; }
    public void setFinalBidDate(Date finalBidDate) { this.finalBidDate = finalBidDate; }
    public String getProjectPhase() { return projectPhase; }
    public void setProjectPhase(String projectPhase) { this.projectPhase = projectPhase; }
    public Date getCreatedAt() { return createdAt; }
    public void setCreatedAt(Date createdAt) { this.createdAt = createdAt; }
    public Date getUpdatedAt() { return updatedAt; }
    public void setUpdatedAt(Date updatedAt) { this.updatedAt = updatedAt; }
    public String getCreatedBy() { return createdBy; }
    public void setCreatedBy(String createdBy) { this.createdBy = createdBy; }
    public String getCorrelationId() { return correlationId; }
    public void setCorrelationId(String correlationId) { this.correlationId = correlationId; }
    public List<Property> getProperties() { return properties; }
    public void setProperties(List<Property> properties) { this.properties = properties; }
}
