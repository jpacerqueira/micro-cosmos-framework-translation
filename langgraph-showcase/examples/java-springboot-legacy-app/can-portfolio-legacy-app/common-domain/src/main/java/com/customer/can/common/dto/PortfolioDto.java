package com.customer.can.common.dto;

import java.util.Date;
import java.util.List;

public class PortfolioDto {
    private String id;
    private String name;
    private String description;
    private String status;
    private Date cutOffDate;
    private Date finalBidDate;
    private String projectPhase;
    private Date createdAt;
    private String createdBy;
    private List<PropertyDto> properties;

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
    public String getCreatedBy() { return createdBy; }
    public void setCreatedBy(String createdBy) { this.createdBy = createdBy; }
    public List<PropertyDto> getProperties() { return properties; }
    public void setProperties(List<PropertyDto> properties) { this.properties = properties; }
}
