package com.bankxyz.fraud.entity;

import javax.persistence.*;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;

/**
 * Maps to CUST_PROFILE.
 * Pre-computed customer behaviour profile, refreshed nightly by the profile batch job.
 * Read by CustomerProfileService to avoid the N+1 anti-pattern of recalculating
 * from raw history on every scoring call.
 */
@Entity
@Table(name = "CUST_PROFILE")
public class CustomerProfile {

    @Id
    @Column(name = "ACCT_NO", length = 10, nullable = false)
    private String acctNo;

    /** NUMBER(15,2) — never float */
    @Column(name = "AVG_TXN_AMOUNT", precision = 15, scale = 2, nullable = false)
    private BigDecimal avgTxnAmount = BigDecimal.ZERO;

    /** NUMBER(15,2) — never float */
    @Column(name = "MAX_TXN_AMOUNT", precision = 15, scale = 2, nullable = false)
    private BigDecimal maxTxnAmount = BigDecimal.ZERO;

    @Column(name = "USUAL_COUNTRY", length = 3, nullable = false)
    private String usualCountry = "GBR";

    @Column(name = "USUAL_CHANNEL", length = 8, nullable = false)
    private String usualChannel = "UNKNOWN ";

    /** Usual activity start hour (0-23). Maps to USUAL_HR_START SMALLINT. */
    @Column(name = "USUAL_HR_START", nullable = false)
    private Integer usualHrStart = 7;

    /** Usual activity end hour (0-23). Maps to USUAL_HR_END SMALLINT. */
    @Column(name = "USUAL_HR_END", nullable = false)
    private Integer usualHrEnd = 22;

    @Column(name = "PROFILE_DATE", nullable = false)
    private LocalDate profileDate = LocalDate.now();

    @Column(name = "LAST_UPDATE_TS", nullable = false)
    private LocalDateTime lastUpdateTs = LocalDateTime.now();

    // ----- getters / setters -----

    public String getAcctNo() { return acctNo; }
    public void setAcctNo(String v) { this.acctNo = v; }

    public BigDecimal getAvgTxnAmount() { return avgTxnAmount; }
    public void setAvgTxnAmount(BigDecimal v) { this.avgTxnAmount = v; }

    public BigDecimal getMaxTxnAmount() { return maxTxnAmount; }
    public void setMaxTxnAmount(BigDecimal v) { this.maxTxnAmount = v; }

    public String getUsualCountry() { return usualCountry; }
    public void setUsualCountry(String v) { this.usualCountry = v; }

    public String getUsualChannel() { return usualChannel; }
    public void setUsualChannel(String v) { this.usualChannel = v; }

    public Integer getUsualHrStart() { return usualHrStart; }
    public void setUsualHrStart(Integer v) { this.usualHrStart = v; }

    public Integer getUsualHrEnd() { return usualHrEnd; }
    public void setUsualHrEnd(Integer v) { this.usualHrEnd = v; }

    public LocalDate getProfileDate() { return profileDate; }
    public void setProfileDate(LocalDate v) { this.profileDate = v; }

    public LocalDateTime getLastUpdateTs() { return lastUpdateTs; }
    public void setLastUpdateTs(LocalDateTime v) { this.lastUpdateTs = v; }
}
