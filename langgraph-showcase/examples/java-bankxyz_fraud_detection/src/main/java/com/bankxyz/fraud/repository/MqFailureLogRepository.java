package com.bankxyz.fraud.repository;

import com.bankxyz.fraud.entity.MqFailureLog;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

/**
 * Data access for MQ_FAILURE_LOG.
 */
@Repository
public interface MqFailureLogRepository extends JpaRepository<MqFailureLog, Long> {
}
