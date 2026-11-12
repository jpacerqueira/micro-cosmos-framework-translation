package com.customer.can.property.infrastructure;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.UUID;

@Repository
public interface PortfolioReadRepository extends JpaRepository<PortfolioReadEntity, UUID> {
    List<PortfolioReadEntity> findByStatus(String status);
}
