package com.bankxyz.fraud.repository;

import com.bankxyz.fraud.entity.FraudAlert;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

/**
 * Data access for FRAUD_ALERTS.
 * ALERT_ID is auto-generated from Oracle sequence FD_SEQ via @SequenceGenerator.
 */
@Repository
public interface FraudAlertRepository extends JpaRepository<FraudAlert, Long> {
}
