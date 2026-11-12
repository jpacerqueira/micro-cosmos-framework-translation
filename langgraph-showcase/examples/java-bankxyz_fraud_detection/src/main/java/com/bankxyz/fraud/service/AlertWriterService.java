package com.bankxyz.fraud.service;

import com.bankxyz.fraud.entity.FraudAlert;
import com.bankxyz.fraud.repository.FraudAlertRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * Fraud alert writer.
 *
 * Writes a fraud alert row to FRAUD_ALERTS and sends a notification
 * to the case management queue via MqNotificationService.
 *
 * Business invariants:
 *   - ALERT_ID is generated from Oracle sequence FD_SEQ
 *   - Alert status is always PENDING on creation
 *   - DB write and MQ notification are in a single @Transactional UOW
 *   - DB failure causes full rollback
 */
@Service
public class AlertWriterService {

    private static final Logger log = LoggerFactory.getLogger(AlertWriterService.class);

    private final FraudAlertRepository alertRepo;
    private final MqNotificationService mqNotify;

    public AlertWriterService(FraudAlertRepository alertRepo,
                               MqNotificationService mqNotify) {
        this.alertRepo = alertRepo;
        this.mqNotify = mqNotify;
    }

    /**
     * Write a fraud alert and send MQ notification within a single transaction.
     *
     * Populates commArea.alertId with the generated ALERT_ID.
     * A DB failure rolls back the alert insert.
     * An MQ failure is logged but does NOT roll back the DB write (non-fatal).
     */
    @Transactional
    public void writeAlert(FraudCommArea commArea) {
        FraudAlert alert = new FraudAlert();
        alert.setTxnId(commArea.getTxnId());
        alert.setAcctNo(commArea.getAcctNo());
        alert.setTxnAmount(commArea.getTxnAmount());
        alert.setFraudScore(commArea.getFraudScore());

        alert = alertRepo.save(alert);
        commArea.setAlertId(alert.getAlertId());

        log.info("Fraud alert created: alertId={} txn={} acct={} score={}",
                alert.getAlertId(), commArea.getTxnId(),
                commArea.getAcctNo(), commArea.getFraudScore());

        // MQ notification — non-fatal; failure logged, not rethrown
        mqNotify.notify(commArea);

        commArea.setReturnCode("00");
        commArea.setMessage("Fraud alert written successfully");
    }
}

