package com.bankxyz.fraud.entity;

import javax.persistence.*;
import java.time.LocalDateTime;

/**
 * Maps to SLA_BREACH_LOG.
 * Written by RealtimeCheckController whenever a real-time check exceeds the 180ms SLA.
 * Reviewed during incident post-mortems (see INC-2023-4471) and capacity planning.
 */
@Entity
@Table(name = "SLA_BREACH_LOG")
public class SlaBreachLog {

    @Id
    @GeneratedValue(strategy = GenerationType.SEQUENCE, generator = "sla_breach_seq_gen")
    @SequenceGenerator(name = "sla_breach_seq_gen", sequenceName = "SLA_BREACH_SEQ", allocationSize = 1)
    @Column(name = "BREACH_ID", nullable = false)
    private Long breachId;

    @Column(name = "TXN_ID", length = 16, nullable = false)
    private String txnId;

    @Column(name = "ACCT_NO", length = 10, nullable = false)
    private String acctNo;

    @Column(name = "ELAPSED_MS", nullable = false)
    private Integer elapsedMs;

    @Column(name = "BREACH_TS", nullable = false)
    private LocalDateTime breachTs = LocalDateTime.now();

    // ----- getters / setters -----

    public Long getBreachId() { return breachId; }
    public void setBreachId(Long v) { this.breachId = v; }

    public String getTxnId() { return txnId; }
    public void setTxnId(String v) { this.txnId = v; }

    public String getAcctNo() { return acctNo; }
    public void setAcctNo(String v) { this.acctNo = v; }

    public Integer getElapsedMs() { return elapsedMs; }
    public void setElapsedMs(Integer v) { this.elapsedMs = v; }

    public LocalDateTime getBreachTs() { return breachTs; }
    public void setBreachTs(LocalDateTime v) { this.breachTs = v; }
}
