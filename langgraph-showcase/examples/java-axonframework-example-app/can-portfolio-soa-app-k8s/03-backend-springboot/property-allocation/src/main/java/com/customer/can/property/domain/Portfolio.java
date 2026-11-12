package com.customer.can.property.domain;

import com.customer.can.common.commands.PortfolioCommands.AddPropertyToPortfolio;
import com.customer.can.common.commands.PortfolioCommands.AllocatePropertyToBroker;
import com.customer.can.common.commands.PortfolioCommands.ClosePortfolio;
import com.customer.can.common.commands.PortfolioCommands.CreatePortfolio;
import com.customer.can.common.commands.PortfolioCommands.SubmitValuation;
import com.customer.can.common.events.PortfolioEvents.PortfolioClosed;
import com.customer.can.common.events.PortfolioEvents.PortfolioCreated;
import com.customer.can.common.events.PortfolioEvents.PropertyAddedToPortfolio;
import com.customer.can.common.events.PortfolioEvents.PropertyAllocatedToBroker;
import com.customer.can.common.events.PortfolioEvents.ValuationSubmitted;

import org.axonframework.commandhandling.CommandHandler;
import org.axonframework.eventsourcing.EventSourcingHandler;
import org.axonframework.modelling.command.AggregateIdentifier;
import org.axonframework.modelling.command.AggregateLifecycle;
import org.axonframework.spring.stereotype.Aggregate;

import java.time.Instant;
import java.time.LocalDate;
import java.util.HashMap;
import java.util.Map;
import java.util.UUID;

/**
 * Portfolio aggregate - the consistency boundary for one portfolio of
 * properties. Implements CQRS/ES with Axon: commands mutate state by
 * applying events, and the aggregate is rehydrated from its event stream.
 *
 * <p>Invariants enforced here:
 * <ul>
 *   <li>A portfolio cannot be modified after it is closed.</li>
 *   <li>Final bid date must not precede cut-off date.</li>
 *   <li>The same property cannot be added to a portfolio twice.</li>
 *   <li>A property must exist in the portfolio before it can be allocated
 *       to a broker or have a valuation submitted against it.</li>
 * </ul>
 */
@Aggregate
public class Portfolio {

    @AggregateIdentifier
    private UUID portfolioId;

    private boolean closed;
    private LocalDate cutOffDate;
    private LocalDate finalBidDate;
    private final Map<UUID, PropertyState> properties = new HashMap<>();

    /** Required by Axon. */
    protected Portfolio() {}

    @CommandHandler
    public Portfolio(CreatePortfolio cmd) {
        if (cmd.finalBidDate().isBefore(cmd.cutOffDate())) {
            throw new IllegalArgumentException("finalBidDate must not be before cutOffDate");
        }
        AggregateLifecycle.apply(new PortfolioCreated(
                cmd.portfolioId(), cmd.name(), cmd.description(),
                cmd.cutOffDate(), cmd.finalBidDate(), cmd.projectPhase(),
                Instant.now()
        ));
    }

    @CommandHandler
    public void handle(AddPropertyToPortfolio cmd) {
        ensureOpen();
        if (properties.containsKey(cmd.propertyId())) {
            throw new IllegalStateException("Property already in portfolio: " + cmd.propertyId());
        }
        AggregateLifecycle.apply(new PropertyAddedToPortfolio(
                cmd.portfolioId(), cmd.propertyId(), cmd.propertyName(),
                cmd.addressLine1(), cmd.city(), cmd.postcode(), cmd.valuation(),
                Instant.now()
        ));
    }

    @CommandHandler
    public void handle(AllocatePropertyToBroker cmd) {
        ensureOpen();
        ensurePropertyExists(cmd.propertyId());
        AggregateLifecycle.apply(new PropertyAllocatedToBroker(
                cmd.portfolioId(), cmd.propertyId(), cmd.brokerCompanyId(),
                cmd.allocationDate(), cmd.allocationStatus(),
                Instant.now()
        ));
    }

    @CommandHandler
    public void handle(SubmitValuation cmd) {
        ensureOpen();
        ensurePropertyExists(cmd.propertyId());
        AggregateLifecycle.apply(new ValuationSubmitted(
                cmd.portfolioId(), cmd.propertyId(), cmd.valuerId(),
                cmd.capitalValuation(), cmd.valuationDate(),
                Instant.now()
        ));
    }

    @CommandHandler
    public void handle(ClosePortfolio cmd) {
        ensureOpen();
        AggregateLifecycle.apply(new PortfolioClosed(cmd.portfolioId(), cmd.reason(), Instant.now()));
    }

    // -- Event sourcing handlers --------------------------------------------

    @EventSourcingHandler
    void on(PortfolioCreated e) {
        this.portfolioId   = e.portfolioId();
        this.cutOffDate    = e.cutOffDate();
        this.finalBidDate  = e.finalBidDate();
        this.closed        = false;
    }

    @EventSourcingHandler
    void on(PropertyAddedToPortfolio e) {
        properties.put(e.propertyId(), new PropertyState(e.propertyId(), false));
    }

    @EventSourcingHandler
    void on(PropertyAllocatedToBroker e) {
        var p = properties.get(e.propertyId());
        if (p != null) {
            properties.put(e.propertyId(), new PropertyState(p.propertyId(), true));
        }
    }

    @EventSourcingHandler
    void on(PortfolioClosed e) {
        this.closed = true;
    }

    // -- Helpers ------------------------------------------------------------

    private void ensureOpen() {
        if (closed) {
            throw new IllegalStateException("Portfolio is closed");
        }
    }

    private void ensurePropertyExists(UUID propertyId) {
        if (!properties.containsKey(propertyId)) {
            throw new IllegalStateException("Property not in portfolio: " + propertyId);
        }
    }

    private record PropertyState(UUID propertyId, boolean allocated) {}
}
