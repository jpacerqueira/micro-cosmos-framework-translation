package com.customer.can.property.infrastructure;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import lombok.Getter;
import lombok.Setter;

import java.time.LocalDate;
import java.util.UUID;

@Entity
@Table(name = "portfolio_view", schema = "portfolio")
@Getter
@Setter
public class PortfolioReadEntity {
    @Id
    @Column(name = "portfolio_id")
    private UUID portfolioId;

    private String name;
    private String description;

    @Column(name = "cut_off_date")
    private LocalDate cutOffDate;

    @Column(name = "final_bid_date")
    private LocalDate finalBidDate;

    @Column(name = "project_phase")
    private String projectPhase;

    private String status;
}
