package com.customer.can.property.infrastructure;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.UUID;

@Repository
public interface PropertyReadRepository extends JpaRepository<PropertyReadEntity, UUID> {
    List<PropertyReadEntity> findByPortfolioId(UUID portfolioId);
    List<PropertyReadEntity> findByBrokerCompanyId(UUID brokerCompanyId);
}
