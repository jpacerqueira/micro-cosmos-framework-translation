package com.customer.can.property.domain;

import javax.persistence.*;
import java.util.Date;

@Entity
@Table(name = "PROPERTY")
public class Property {
    @Id
    @Column(name = "ID", length = 36)
    private String id;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "PORTFOLIO_ID", nullable = false)
    private Portfolio portfolio;

    @Column(name = "NAME", nullable = false, length = 255)
    private String name;

    @Column(name = "ADDRESS", length = 500)
    private String address;

    @Column(name = "CITY", length = 100)
    private String city;

    @Column(name = "POSTCODE", length = 20)
    private String postcode;

    @Column(name = "PROPERTY_TYPE", length = 50)
    private String propertyType;

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
    public Portfolio getPortfolio() { return portfolio; }
    public void setPortfolio(Portfolio portfolio) { this.portfolio = portfolio; }
    public String getName() { return name; }
    public void setName(String name) { this.name = name; }
    public String getAddress() { return address; }
    public void setAddress(String address) { this.address = address; }
    public String getCity() { return city; }
    public void setCity(String city) { this.city = city; }
    public String getPostcode() { return postcode; }
    public void setPostcode(String postcode) { this.postcode = postcode; }
    public String getPropertyType() { return propertyType; }
    public void setPropertyType(String propertyType) { this.propertyType = propertyType; }
    public String getStatus() { return status; }
    public void setStatus(String status) { this.status = status; }
    public Date getCreatedAt() { return createdAt; }
    public void setCreatedAt(Date createdAt) { this.createdAt = createdAt; }
}
