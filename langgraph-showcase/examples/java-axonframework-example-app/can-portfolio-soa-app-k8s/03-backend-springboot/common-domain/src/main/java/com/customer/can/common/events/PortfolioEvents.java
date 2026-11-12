package com.customer.can.common.events;

import java.math.BigDecimal;
import java.time.Instant;
import java.time.LocalDate;
import java.util.UUID;

/**
 * Domain events emitted by aggregates. Events are immutable, named in past
 * tense, and carry only what subscribers need - no behaviour. Projections
 * (read models) and process managers consume these via the Axon event bus
 * and/or the NATS ULI bridge.
 */
public final class PortfolioEvents {

    private PortfolioEvents() {}

    public record PortfolioCreated(
            UUID portfolioId,
            String name,
            String description,
            LocalDate cutOffDate,
            LocalDate finalBidDate,
            String projectPhase,
            Instant occurredAt
    ) {}

    public record PropertyAddedToPortfolio(
            UUID portfolioId,
            UUID propertyId,
            String propertyName,
            String addressLine1,
            String city,
            String postcode,
            BigDecimal valuation,
            Instant occurredAt
    ) {}

    public record PropertyAllocatedToBroker(
            UUID portfolioId,
            UUID propertyId,
            UUID brokerCompanyId,
            LocalDate allocationDate,
            String allocationStatus,
            Instant occurredAt
    ) {}

    public record ValuationSubmitted(
            UUID portfolioId,
            UUID propertyId,
            UUID valuerId,
            BigDecimal capitalValuation,
            LocalDate valuationDate,
            Instant occurredAt
    ) {}

    public record PortfolioClosed(
            UUID portfolioId,
            String reason,
            Instant occurredAt
    ) {}
}
