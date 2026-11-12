package com.customer.can.property.application;

import com.customer.can.common.events.PortfolioEvents.PortfolioClosed;
import com.customer.can.common.events.PortfolioEvents.PortfolioCreated;
import com.customer.can.common.events.PortfolioEvents.PropertyAddedToPortfolio;
import com.customer.can.common.events.PortfolioEvents.PropertyAllocatedToBroker;
import com.customer.can.common.events.PortfolioEvents.ValuationSubmitted;
import com.customer.can.property.infrastructure.PortfolioReadEntity;
import com.customer.can.property.infrastructure.PortfolioReadRepository;
import com.customer.can.property.infrastructure.PropertyReadEntity;
import com.customer.can.property.infrastructure.PropertyReadRepository;

import org.axonframework.config.ProcessingGroup;
import org.axonframework.eventhandling.EventHandler;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

import java.util.UUID;

/**
 * Portfolio projection - builds the read model in PostgreSQL/Citus from the
 * Axon event stream. Runs in its own processing group so it can be rebuilt
 * independently (replay) without touching the write side.
 *
 * <p>Idempotency: each handler does an upsert keyed on the aggregate id.
 * Replays are therefore safe.
 */
@Component
@ProcessingGroup("portfolio-projection")
public class PortfolioProjection {

    private final PortfolioReadRepository portfolios;
    private final PropertyReadRepository properties;

    public PortfolioProjection(PortfolioReadRepository portfolios, PropertyReadRepository properties) {
        this.portfolios = portfolios;
        this.properties = properties;
    }

    @EventHandler
    @Transactional
    public void on(PortfolioCreated e) {
        var entity = new PortfolioReadEntity();
        entity.setPortfolioId(e.portfolioId());
        entity.setName(e.name());
        entity.setDescription(e.description());
        entity.setCutOffDate(e.cutOffDate());
        entity.setFinalBidDate(e.finalBidDate());
        entity.setProjectPhase(e.projectPhase());
        entity.setStatus("OPEN");
        portfolios.save(entity);
    }

    @EventHandler
    @Transactional
    public void on(PropertyAddedToPortfolio e) {
        var p = new PropertyReadEntity();
        p.setPropertyId(e.propertyId());
        p.setPortfolioId(e.portfolioId());
        p.setName(e.propertyName());
        p.setAddressLine1(e.addressLine1());
        p.setCity(e.city());
        p.setPostcode(e.postcode());
        p.setValuation(e.valuation());
        properties.save(p);
    }

    @EventHandler
    @Transactional
    public void on(PropertyAllocatedToBroker e) {
        properties.findById(e.propertyId()).ifPresent(p -> {
            p.setBrokerCompanyId(e.brokerCompanyId());
            p.setAllocationStatus(e.allocationStatus());
            properties.save(p);
        });
    }

    @EventHandler
    @Transactional
    public void on(ValuationSubmitted e) {
        properties.findById(e.propertyId()).ifPresent(p -> {
            p.setValuation(e.capitalValuation());
            properties.save(p);
        });
    }

    @EventHandler
    @Transactional
    public void on(PortfolioClosed e) {
        portfolios.findById(e.portfolioId()).ifPresent(pf -> {
            pf.setStatus("CLOSED");
            portfolios.save(pf);
        });
    }
}
