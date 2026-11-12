package com.bankxyz.fraud.entity;

import com.bankxyz.fraud.domain.AlertStatus;

import javax.persistence.*;
import java.math.BigDecimal;
import java.time.LocalDateTime;

/**
 * Maps to FRAUD_ALERTS.
 * Written by AlertWriterService within a single @Transactional UOW.
 * ALERT_ID sourced from Oracle sequence FD_SEQ.
 *
 * ALERT_STATUS is an explicit state machine (AlertStatus enum):
 *   PENDING → REVIEWED → CLOSED
 *   PENDING → ESCALATED  (OFAC/PEP mandatory escalation)
 */
@Entity
@Table(name = "FRAUD_ALERTS")
public class FraudAlert {

    @Id
    @GeneratedValue(strategy = GenerationType.SEQUENCE, generator = "fd_seq_gen")
    @SequenceGenerator(name = "fd_seq_gen", sequenceName = "FD_SEQ", allocationSize = 1)
    @Column(name = "ALERT_ID", nullable = false)
    private Long alertId;

    @Column(name = "TXN_ID", length = 16, nullable = false)
    private String txnId;

    @Column(name = "ACCT_NO", length = 10, nullable = false)
    private String acctNo;

    /** NUMBER(15,2). Never use float. */
    @Column(name = "TXN_AMOUNT", precision = 15, scale = 2, nullable = false)
    private BigDecimal txnAmount;

    /** NUMBER(7,4) — score range 0.0000–1.0000. */
    @Column(name = "FRAUD_SCORE", precision = 7, scale = 4, nullable = false)
    private BigDecimal fraudScore;

    @Enumerated(EnumType.STRING)
    @Column(name = "ALERT_STATUS", length = 10, nullable = false)
    private AlertStatus alertStatus = AlertStatus.PENDING;

    @Column(name = "ANALYST_ID", length = 8)
    private String analystId;

    @Column(name = "RESOLUTION_NOTES", length = 255)
    private String resolutionNotes;

    @Column(name = "ARCHIVED_FLAG", length = 1, nullable = false)
    private String archivedFlag = "N";

    @Column(name = "ARCHIVE_TS")
    private LocalDateTime archiveTs;

    @Column(name = "CREATED_TS", nullable = false)
    private LocalDateTime createdTs = LocalDateTime.now();

    @Column(name = "LAST_UPDATE_TS", nullable = false)
    private LocalDateTime lastUpdateTs = LocalDateTime.now();

    // ----- getters / setters -----

    public Long getAlertId() { return alertId; }
    public void setAlertId(Long v) { this.alertId = v; }

    public String getTxnId() { return txnId; }
    public void setTxnId(String v) { this.txnId = v; }

    public String getAcctNo() { return acctNo; }
    public void setAcctNo(String v) { this.acctNo = v; }

    public BigDecimal getTxnAmount() { return txnAmount; }
    public void setTxnAmount(BigDecimal v) { this.txnAmount = v; }

    public BigDecimal getFraudScore() { return fraudScore; }
    public void setFraudScore(BigDecimal v) { this.fraudScore = v; }

    public AlertStatus getAlertStatus() { return alertStatus; }
    public void setAlertStatus(AlertStatus v) { this.alertStatus = v; }

    public String getAnalystId() { return analystId; }
    public void setAnalystId(String v) { this.analystId = v; }

    public String getResolutionNotes() { return resolutionNotes; }
    public void setResolutionNotes(String v) { this.resolutionNotes = v; }

    public String getArchivedFlag() { return archivedFlag; }
    public void setArchivedFlag(String v) { this.archivedFlag = v; }

    public LocalDateTime getArchiveTs() { return archiveTs; }
    public void setArchiveTs(LocalDateTime v) { this.archiveTs = v; }

    public LocalDateTime getCreatedTs() { return createdTs; }
    public void setCreatedTs(LocalDateTime v) { this.createdTs = v; }

    public LocalDateTime getLastUpdateTs() { return lastUpdateTs; }
    public void setLastUpdateTs(LocalDateTime v) { this.lastUpdateTs = v; }
}
