package com.customer.can.property.application;

import com.customer.can.common.events.PortfolioEvents.PortfolioClosed;
import com.customer.can.common.events.PortfolioEvents.PortfolioCreated;
import com.customer.can.common.events.PortfolioEvents.PropertyAddedToPortfolio;
import com.customer.can.common.events.PortfolioEvents.PropertyAllocatedToBroker;
import com.customer.can.common.events.PortfolioEvents.ValuationSubmitted;
import com.customer.can.property.infrastructure.UliPublisher;

import org.axonframework.config.ProcessingGroup;
import org.axonframework.eventhandling.EventHandler;
import org.springframework.stereotype.Component;

/**
 * Axon -> NATS bridge. Runs in its own processing group so backpressure
 * on NATS does not block the projection that updates the read model.
 *
 * <p>Subjects follow {@code uli.events.<bounded-context>.<EventType>}.
 */
@Component
@ProcessingGroup("uli-publisher")
public class UliEventBridge {

    private final UliPublisher uli;

    public UliEventBridge(UliPublisher uli) {
        this.uli = uli;
    }

    @EventHandler
    public void on(PortfolioCreated e) {
        uli.publish("uli.events.portfolio.PortfolioCreated", "PortfolioCreated", e);
    }

    @EventHandler
    public void on(PropertyAddedToPortfolio e) {
        uli.publish("uli.events.portfolio.PropertyAddedToPortfolio", "PropertyAddedToPortfolio", e);
    }

    @EventHandler
    public void on(PropertyAllocatedToBroker e) {
        uli.publish("uli.events.portfolio.PropertyAllocatedToBroker", "PropertyAllocatedToBroker", e);
    }

    @EventHandler
    public void on(ValuationSubmitted e) {
        uli.publish("uli.events.portfolio.ValuationSubmitted", "ValuationSubmitted", e);
    }

    @EventHandler
    public void on(PortfolioClosed e) {
        uli.publish("uli.events.portfolio.PortfolioClosed", "PortfolioClosed", e);
    }
}
