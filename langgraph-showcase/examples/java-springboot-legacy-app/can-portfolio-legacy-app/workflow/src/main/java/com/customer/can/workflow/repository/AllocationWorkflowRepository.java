package com.customer.can.workflow.repository;

import com.customer.can.workflow.domain.AllocationWorkflow;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;
import java.util.List;
import java.util.Optional;

@Repository
public interface AllocationWorkflowRepository extends JpaRepository<AllocationWorkflow, String> {
    Optional<AllocationWorkflow> findByPropertyId(String propertyId);
    List<AllocationWorkflow> findByPortfolioId(String portfolioId);
    List<AllocationWorkflow> findByState(String state);
}
