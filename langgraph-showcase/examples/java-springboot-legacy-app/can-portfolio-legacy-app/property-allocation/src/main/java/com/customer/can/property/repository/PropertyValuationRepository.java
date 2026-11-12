package com.customer.can.property.repository;

import com.customer.can.property.domain.PropertyValuation;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;
import java.util.List;

@Repository
public interface PropertyValuationRepository extends JpaRepository<PropertyValuation, String> {
    List<PropertyValuation> findByPropertyId(String propertyId);
    List<PropertyValuation> findByPortfolioId(String portfolioId);
}
