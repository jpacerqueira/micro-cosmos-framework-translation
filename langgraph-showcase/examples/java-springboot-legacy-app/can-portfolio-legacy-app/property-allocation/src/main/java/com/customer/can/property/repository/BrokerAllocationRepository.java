package com.customer.can.property.repository;

import com.customer.can.property.domain.BrokerAllocation;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;
import java.util.List;

@Repository
public interface BrokerAllocationRepository extends JpaRepository<BrokerAllocation, String> {
    List<BrokerAllocation> findByPortfolioId(String portfolioId);
    List<BrokerAllocation> findByPropertyId(String propertyId);
}
