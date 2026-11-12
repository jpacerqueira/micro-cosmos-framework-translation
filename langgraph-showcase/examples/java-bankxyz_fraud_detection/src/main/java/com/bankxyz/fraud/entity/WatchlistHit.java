package com.bankxyz.fraud.entity;

import javax.persistence.*;
import java.time.LocalDateTime;

/**
 * Maps to WATCHLIST_HITS.
 * Audit log of every watchlist match regardless of outcome.
 * Written by WatchlistService.
 */
@Entity
@Table(name = "WATCHLIST_HITS")
public class WatchlistHit {

    @Id
    @GeneratedValue(strategy = GenerationType.SEQUENCE, generator = "wl_hits_seq_gen")
    @SequenceGenerator(name = "wl_hits_seq_gen", sequenceName = "WL_HITS_SEQ", allocationSize = 1)
    @Column(name = "HIT_ID", nullable = false)
    private Long hitId;

    @Column(name = "ACCT_NO", length = 10, nullable = false)
    private String acctNo;

    @Column(name = "TXN_ID", length = 16, nullable = false)
    private String txnId;

    @Column(name = "HIT_TYPE", length = 40, nullable = false)
    private String hitType;

    @Column(name = "HIT_REASON", length = 80, nullable = false)
    private String hitReason;

    @Column(name = "HIT_TS", nullable = false)
    private LocalDateTime hitTs = LocalDateTime.now();

    // ----- getters / setters -----

    public Long getHitId() { return hitId; }
    public void setHitId(Long v) { this.hitId = v; }

    public String getAcctNo() { return acctNo; }
    public void setAcctNo(String v) { this.acctNo = v; }

    public String getTxnId() { return txnId; }
    public void setTxnId(String v) { this.txnId = v; }

    public String getHitType() { return hitType; }
    public void setHitType(String v) { this.hitType = v; }

    public String getHitReason() { return hitReason; }
    public void setHitReason(String v) { this.hitReason = v; }

    public LocalDateTime getHitTs() { return hitTs; }
    public void setHitTs(LocalDateTime v) { this.hitTs = v; }
}
