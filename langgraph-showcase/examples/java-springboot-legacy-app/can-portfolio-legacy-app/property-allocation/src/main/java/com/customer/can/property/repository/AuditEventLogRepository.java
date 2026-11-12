package com.customer.can.property.repository;

import com.customer.can.property.domain.AuditEventLog;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;
import java.util.List;

@Repository
public interface AuditEventLogRepository extends JpaRepository<AuditEventLog, String> {
    List<AuditEventLog> findByPortfolioIdOrderByCreatedAtDesc(String portfolioId);
}
