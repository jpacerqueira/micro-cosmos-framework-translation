package com.customer.can.property;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * Property Allocation service - hosts the Portfolio aggregate (write side)
 * and the Portfolio read-model projections.
 */
@SpringBootApplication
public class PropertyAllocationApplication {
    public static void main(String[] args) {
        SpringApplication.run(PropertyAllocationApplication.class, args);
    }
}
