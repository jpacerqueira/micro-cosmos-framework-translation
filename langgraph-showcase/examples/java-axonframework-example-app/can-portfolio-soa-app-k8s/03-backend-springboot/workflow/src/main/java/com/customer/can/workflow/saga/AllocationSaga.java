package com.customer.can.workflow.saga;

import com.customer.can.common.events.PortfolioEvents.PropertyAddedToPortfolio;
import com.customer.can.common.events.PortfolioEvents.PropertyAllocatedToBroker;
import com.customer.can.common.events.PortfolioEvents.ValuationSubmitted;

import org.axonframework.eventhandling.EventHandler;
import org.axonframework.modelling.saga.EndSaga;
import org.axonframework.modelling.saga.SagaEventHandler;
import org.axonframework.modelling.saga.StartSaga;
import org.axonframework.spring.stereotype.Saga;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.UUID;

/**
 * Allocation Saga - implements the SAD's "Orchestration" pattern.
 *
 * <p>Started when a property is added to a portfolio. Ends when a valuation
 * has been submitted for that property. Times out and compensates if no
 * valuation arrives within the configured deadline (deadline scheduling left
 * as an exercise for production hardening).
 */
@Saga
public class AllocationSaga {

    private static final Logger log = LoggerFactory.getLogger(AllocationSaga.class);

    private UUID propertyId;
    private UUID portfolioId;
    private boolean allocated;
    private boolean valued;

    @StartSaga
    @SagaEventHandler(associationProperty = "propertyId")
    public void on(PropertyAddedToPortfolio e) {
        this.portfolioId = e.portfolioId();
        this.propertyId  = e.propertyId();
        log.info("AllocationSaga started portfolio={} property={}", portfolioId, propertyId);
    }

    @SagaEventHandler(associationProperty = "propertyId")
    public void on(PropertyAllocatedToBroker e) {
        this.allocated = true;
        log.info("Property allocated portfolio={} property={} broker={}",
                portfolioId, propertyId, e.brokerCompanyId());
    }

    @EndSaga
    @SagaEventHandler(associationProperty = "propertyId")
    public void on(ValuationSubmitted e) {
        this.valued = true;
        log.info("AllocationSaga complete portfolio={} property={} allocated={} valued={}",
                portfolioId, propertyId, allocated, valued);
    }
}
