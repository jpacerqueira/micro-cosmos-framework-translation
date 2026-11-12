package com.bankxyz.fraud.repository;

import com.bankxyz.fraud.entity.SlaBreachLog;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

/**
 * Data access for SLA_BREACH_LOG.
 */
@Repository
public interface SlaBreachLogRepository extends JpaRepository<SlaBreachLog, Long> {
}
