package com.customer.can.common.commands;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import org.axonframework.modelling.command.TargetAggregateIdentifier;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.UUID;

/**
 * Domain commands. Each command is an immutable Java record and carries
 * {@code @TargetAggregateIdentifier} so Axon can route it to the right
 * aggregate instance. Validation is enforced at the API boundary
 * (controller / GraphQL resolver) before dispatch.
 */
public final class PortfolioCommands {

    private PortfolioCommands() {}

    public record CreatePortfolio(
            @TargetAggregateIdentifier @NotNull UUID portfolioId,
            @NotBlank String name,
            String description,
            @NotNull LocalDate cutOffDate,
            @NotNull LocalDate finalBidDate,
            @NotBlank String projectPhase
    ) {}

    public record AddPropertyToPortfolio(
            @TargetAggregateIdentifier @NotNull UUID portfolioId,
            @NotNull UUID propertyId,
            @NotBlank String propertyName,
            String addressLine1,
            String city,
            String postcode,
            BigDecimal valuation
    ) {}

    public record AllocatePropertyToBroker(
            @TargetAggregateIdentifier @NotNull UUID portfolioId,
            @NotNull UUID propertyId,
            @NotNull UUID brokerCompanyId,
            @NotNull LocalDate allocationDate,
            String allocationStatus
    ) {}

    public record SubmitValuation(
            @TargetAggregateIdentifier @NotNull UUID portfolioId,
            @NotNull UUID propertyId,
            @NotNull UUID valuerId,
            @NotNull BigDecimal capitalValuation,
            @NotNull LocalDate valuationDate
    ) {}

    public record ClosePortfolio(
            @TargetAggregateIdentifier @NotNull UUID portfolioId,
            String reason
    ) {}
}
