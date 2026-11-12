package com.bankxyz.fraud.entity;

import javax.persistence.*;
import java.time.LocalDate;

/**
 * Maps to WATCHLIST.
 * Consolidated sanctions and fraud watchlist.
 * Sources: OFAC (daily), PEP (weekly), internal BankXYZ fraud operations.
 *
 * LIST_TYPE: 'OFAC', 'PEP', 'INTERNAL'
 */
@Entity
@Table(name = "WATCHLIST")
public class WatchlistEntry {

    @Id
    @GeneratedValue(strategy = GenerationType.SEQUENCE, generator = "watchlist_seq_gen")
    @SequenceGenerator(name = "watchlist_seq_gen", sequenceName = "WATCHLIST_SEQ", allocationSize = 1)
    @Column(name = "WATCHLIST_ID", nullable = false)
    private Long watchlistId;

    @Column(name = "LIST_TYPE", length = 10, nullable = false)
    private String listType;

    @Column(name = "MATCH_NAME", length = 100)
    private String matchName;

    @Column(name = "MATCH_ACCT", length = 10)
    private String matchAcct;

    @Column(name = "LIST_STATUS", length = 6, nullable = false)
    private String listStatus = "ACTIVE";

    @Column(name = "REF_NUMBER", length = 20)
    private String refNumber;

    @Column(name = "ADDED_BY", length = 8, nullable = false)
    private String addedBy = "SYSTEM";

    @Column(name = "EFFECTIVE_FROM", nullable = false)
    private LocalDate effectiveFrom = LocalDate.now();

    @Column(name = "EFFECTIVE_TO")
    private LocalDate effectiveTo;

    // ----- getters / setters -----

    public Long getWatchlistId() { return watchlistId; }
    public void setWatchlistId(Long v) { this.watchlistId = v; }

    public String getListType() { return listType; }
    public void setListType(String v) { this.listType = v; }

    public String getMatchName() { return matchName; }
    public void setMatchName(String v) { this.matchName = v; }

    public String getMatchAcct() { return matchAcct; }
    public void setMatchAcct(String v) { this.matchAcct = v; }

    public String getListStatus() { return listStatus; }
    public void setListStatus(String v) { this.listStatus = v; }

    public String getRefNumber() { return refNumber; }
    public void setRefNumber(String v) { this.refNumber = v; }

    public String getAddedBy() { return addedBy; }
    public void setAddedBy(String v) { this.addedBy = v; }

    public LocalDate getEffectiveFrom() { return effectiveFrom; }
    public void setEffectiveFrom(LocalDate v) { this.effectiveFrom = v; }

    public LocalDate getEffectiveTo() { return effectiveTo; }
    public void setEffectiveTo(LocalDate v) { this.effectiveTo = v; }
}
