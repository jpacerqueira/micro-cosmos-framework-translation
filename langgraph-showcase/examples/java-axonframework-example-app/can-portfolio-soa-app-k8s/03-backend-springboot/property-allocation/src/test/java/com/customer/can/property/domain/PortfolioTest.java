package com.customer.can.property.domain;

import com.customer.can.common.commands.PortfolioCommands.AddPropertyToPortfolio;
import com.customer.can.common.commands.PortfolioCommands.AllocatePropertyToBroker;
import com.customer.can.common.commands.PortfolioCommands.ClosePortfolio;
import com.customer.can.common.commands.PortfolioCommands.CreatePortfolio;
import com.customer.can.common.events.PortfolioEvents.PortfolioClosed;
import com.customer.can.common.events.PortfolioEvents.PortfolioCreated;
import com.customer.can.common.events.PortfolioEvents.PropertyAddedToPortfolio;
import com.customer.can.common.events.PortfolioEvents.PropertyAllocatedToBroker;

import org.axonframework.test.aggregate.AggregateTestFixture;
import org.axonframework.test.matchers.Matchers;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.UUID;

/**
 * Aggregate tests use the Axon "given-when-expect" fixture: events that
 * already happened, the command under test, and the events (or exception)
 * we expect. This validates the invariants without booting Spring.
 */
class PortfolioTest {

    private AggregateTestFixture<Portfolio> fixture;
    private final UUID id = UUID.randomUUID();
    private final UUID propId = UUID.randomUUID();
    private final UUID brokerId = UUID.randomUUID();

    @BeforeEach
    void setUp() {
        fixture = new AggregateTestFixture<>(Portfolio.class);
    }

    @Test
    void creating_portfolio_emits_PortfolioCreated() {
        fixture.givenNoPriorActivity()
               .when(new CreatePortfolio(id, "Q3 Wave", "test", LocalDate.now(),
                       LocalDate.now().plusDays(30), "BIDDING"))
               .expectEventsMatching(Matchers.payloadsMatching(
                   Matchers.exactSequenceOf(Matchers.messageWithPayload(
                       org.hamcrest.Matchers.isA(PortfolioCreated.class)))));
    }

    @Test
    void final_bid_before_cut_off_is_rejected() {
        fixture.givenNoPriorActivity()
               .when(new CreatePortfolio(id, "bad", null,
                       LocalDate.of(2026, 6, 1),
                       LocalDate.of(2026, 5, 1), "BIDDING"))
               .expectException(IllegalArgumentException.class);
    }

    @Test
    void cannot_add_same_property_twice() {
        fixture.given(new PortfolioCreated(id, "P", null,
                       LocalDate.now(), LocalDate.now().plusDays(30), "BIDDING",
                       java.time.Instant.now()),
                       new PropertyAddedToPortfolio(id, propId, "X", "1 St",
                       "London", "EC1", BigDecimal.TEN, java.time.Instant.now()))
               .when(new AddPropertyToPortfolio(id, propId, "X", "1 St",
                       "London", "EC1", BigDecimal.TEN))
               .expectException(IllegalStateException.class);
    }

    @Test
    void allocate_emits_PropertyAllocatedToBroker() {
        fixture.given(new PortfolioCreated(id, "P", null,
                       LocalDate.now(), LocalDate.now().plusDays(30), "BIDDING",
                       java.time.Instant.now()),
                       new PropertyAddedToPortfolio(id, propId, "X", "1 St",
                       "London", "EC1", BigDecimal.TEN, java.time.Instant.now()))
               .when(new AllocatePropertyToBroker(id, propId, brokerId,
                       LocalDate.now(), "ALLOCATED"))
               .expectEventsMatching(Matchers.payloadsMatching(
                   Matchers.exactSequenceOf(Matchers.messageWithPayload(
                       org.hamcrest.Matchers.isA(PropertyAllocatedToBroker.class)))));
    }

    @Test
    void cannot_modify_after_close() {
        fixture.given(new PortfolioCreated(id, "P", null,
                       LocalDate.now(), LocalDate.now().plusDays(30), "BIDDING",
                       java.time.Instant.now()),
                       new PortfolioClosed(id, "done", java.time.Instant.now()))
               .when(new ClosePortfolio(id, "again"))
               .expectException(IllegalStateException.class);
    }
}
