package com.bankxyz.fraud.entity;

import javax.persistence.*;
import java.time.LocalDateTime;

/**
 * Maps to MQ_FAILURE_LOG.
 * Written by MqNotificationService when a JMS put to FRAUD.ALERT.QUEUE fails.
 * A failed MQ put is logged but does NOT fail the alert transaction (non-fatal).
 */
@Entity
@Table(name = "MQ_FAILURE_LOG")
public class MqFailureLog {

    @Id
    @GeneratedValue(strategy = GenerationType.SEQUENCE, generator = "mq_fail_seq_gen")
    @SequenceGenerator(name = "mq_fail_seq_gen", sequenceName = "MQ_FAIL_SEQ", allocationSize = 1)
    @Column(name = "FAIL_ID", nullable = false)
    private Long failId;

    @Column(name = "TXN_ID", length = 16, nullable = false)
    private String txnId;

    @Column(name = "ACCT_NO", length = 10, nullable = false)
    private String acctNo;

    @Column(name = "REASON_CODE", nullable = false)
    private Integer reasonCode = 0;

    @Column(name = "FAILED_TS", nullable = false)
    private LocalDateTime failedTs = LocalDateTime.now();

    // ----- getters / setters -----

    public Long getFailId() { return failId; }
    public void setFailId(Long v) { this.failId = v; }

    public String getTxnId() { return txnId; }
    public void setTxnId(String v) { this.txnId = v; }

    public String getAcctNo() { return acctNo; }
    public void setAcctNo(String v) { this.acctNo = v; }

    public Integer getReasonCode() { return reasonCode; }
    public void setReasonCode(Integer v) { this.reasonCode = v; }

    public LocalDateTime getFailedTs() { return failedTs; }
    public void setFailedTs(LocalDateTime v) { this.failedTs = v; }
}
