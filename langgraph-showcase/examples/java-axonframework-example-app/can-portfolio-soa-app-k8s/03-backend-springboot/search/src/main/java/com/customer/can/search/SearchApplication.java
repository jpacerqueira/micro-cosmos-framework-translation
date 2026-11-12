package com.customer.can.search;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * Search service. Subscribes to {@code uli.events.>} on NATS, indexes
 * properties/portfolios/documents into a denormalised PostgreSQL table
 * with a {@code tsvector} column, and exposes a REST search endpoint.
 *
 * <p>This avoids the operational cost of running Elasticsearch for the
 * MVP while still giving the BFF fast text/filter queries.
 */
@SpringBootApplication
public class SearchApplication {
    public static void main(String[] args) {
        SpringApplication.run(SearchApplication.class, args);
    }
}
