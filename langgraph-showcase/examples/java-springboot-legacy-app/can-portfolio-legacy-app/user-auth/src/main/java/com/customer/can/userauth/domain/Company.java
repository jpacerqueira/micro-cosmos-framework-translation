package com.customer.can.userauth.domain;

import javax.persistence.*;
import java.util.Date;

@Entity
@Table(name = "COMPANY")
public class Company {
    @Id
    @Column(name = "ID", length = 36)
    private String id;

    @Column(name = "NAME", nullable = false, length = 255)
    private String name;

    @Column(name = "COMPANY_TYPE", nullable = false, length = 50)
    private String companyType;

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
    public String getName() { return name; }
    public void setName(String name) { this.name = name; }
    public String getCompanyType() { return companyType; }
    public void setCompanyType(String companyType) { this.companyType = companyType; }
    public Date getCreatedAt() { return createdAt; }
    public void setCreatedAt(Date createdAt) { this.createdAt = createdAt; }
}
