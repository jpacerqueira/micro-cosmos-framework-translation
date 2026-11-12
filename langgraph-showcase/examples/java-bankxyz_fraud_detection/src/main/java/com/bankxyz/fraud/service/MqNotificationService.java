package com.bankxyz.fraud.service;

import com.fasterxml.jackson.annotation.JsonProperty;
import com.bankxyz.fraud.entity.MqFailureLog;
import com.bankxyz.fraud.repository.MqFailureLogRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jms.core.JmsTemplate;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;

/**
 * MQ notification service.
 *
 * Puts a JSON message to FRAUD.ALERT.QUEUE so the case management system
 * can pick up the alert in real time.
 *
 * Business invariants:
 *   - A failed MQ put is logged but does NOT fail the calling alert transaction
 *   - JSON field names are stable for case management system compatibility
 */
@Service
public class MqNotificationService {

    private static final Logger log = LoggerFactory.getLogger(MqNotificationService.class);

    private final JmsTemplate jmsTemplate;
    private final MqFailureLogRepository failureLogRepo;

    @Value("${fraud.mq.alert-queue}")
    private String alertQueue;

    public MqNotificationService(JmsTemplate jmsTemplate,
                                  MqFailureLogRepository failureLogRepo) {
        this.jmsTemplate = jmsTemplate;
        this.failureLogRepo = failureLogRepo;
    }

    /**
     * Send fraud alert notification to FRAUD.ALERT.QUEUE.
     * Non-fatal: logs failure to MQ_FAILURE_LOG but never throws to caller.
     */
    public void notify(FraudCommArea commArea) {
        try {
            AlertMessage msg = new AlertMessage(commArea);
            jmsTemplate.convertAndSend(alertQueue, msg);
            log.info("MQ alert sent: txn={} acct={} score={}",
                    commArea.getTxnId(), commArea.getAcctNo(), commArea.getFraudScore());
        } catch (Exception e) {
            log.error("MQ put failed for txn={} acct={}: {}",
                    commArea.getTxnId(), commArea.getAcctNo(), e.getMessage());
            logMqFailure(commArea);
        }
    }

    private void logMqFailure(FraudCommArea commArea) {
        try {
            MqFailureLog entry = new MqFailureLog();
            entry.setTxnId(commArea.getTxnId());
            entry.setAcctNo(commArea.getAcctNo());
            entry.setReasonCode(1);
            failureLogRepo.save(entry);
        } catch (Exception ex) {
            log.error("Failed to log MQ failure for txn={}: {}", commArea.getTxnId(), ex.getMessage());
        }
    }

    /**
     * JSON payload for FRAUD.ALERT.QUEUE.
     * Field names are stable for case management system compatibility.
     */
    public static class AlertMessage {
        @JsonProperty("alert_id")   private Long alertId;
        @JsonProperty("txn_id")     private String txnId;
        @JsonProperty("acct_no")    private String acctNo;
        @JsonProperty("amount")     private BigDecimal amount;
        @JsonProperty("score")      private BigDecimal score;
        @JsonProperty("channel")    private String channel;
        @JsonProperty("country")    private String country;
        @JsonProperty("status")     private String status = "PENDING";

        public AlertMessage(FraudCommArea ca) {
            this.alertId = ca.getAlertId();
            this.txnId   = ca.getTxnId();
            this.acctNo  = ca.getAcctNo();
            this.amount  = ca.getTxnAmount();
            this.score   = ca.getFraudScore();
            this.channel = ca.getChannel() != null ? ca.getChannel().name() : null;
            this.country = ca.getTxnCountry();
        }

        // getters for Jackson serialisation
        public Long getAlertId()     { return alertId; }
        public String getTxnId()     { return txnId; }
        public String getAcctNo()    { return acctNo; }
        public BigDecimal getAmount(){ return amount; }
        public BigDecimal getScore() { return score; }
        public String getChannel()   { return channel; }
        public String getCountry()   { return country; }
        public String getStatus()    { return status; }
    }
}
