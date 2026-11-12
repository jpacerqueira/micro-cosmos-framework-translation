package com.customer.can.property.infrastructure;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import lombok.Getter;
import lombok.Setter;
import org.springframework.data.jpa.repository.JpaRepository;

import java.math.BigDecimal;
import java.util.UUID;

@Entity
@Table(name = "property_view", schema = "portfolio")
@Getter
@Setter
public class PropertyReadEntity {
    @Id
    @Column(name = "property_id")
    private UUID propertyId;

    @Column(name = "portfolio_id")
    private UUID portfolioId;

    private String name;

    @Column(name = "address_line_1")
    private String addressLine1;

    private String city;
    private String postcode;
    private BigDecimal valuation;

    @Column(name = "broker_company_id")
    private UUID brokerCompanyId;

    @Column(name = "allocation_status")
    private String allocationStatus;
}
