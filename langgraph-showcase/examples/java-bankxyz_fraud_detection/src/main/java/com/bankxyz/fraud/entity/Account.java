package com.bankxyz.fraud.entity;

import com.bankxyz.fraud.domain.AccountStatus;

import javax.persistence.*;
import java.time.LocalDateTime;

/**
 * Maps to ACCOUNT_MASTER.
 * Single source of truth for account status and daily limits.
 * Written by: core banking feed (nightly batch).
 * Read by: FraudRulesService, CustomerProfileService, WatchlistService, RealtimeCheckController.
 */
@Entity
@Table(name = "ACCOUNT_MASTER")
public class Account {

    @Id
    @Column(name = "ACCT_NO", length = 10, nullable = false)
    private String acctNo;

    @Column(name = "CUST_ID", length = 9, nullable = false)
    private String custId;

    @Column(name = "CUST_FULL_NAME", length = 50, nullable = false)
    private String custFullName;

    /**
     * Account status — explicit state machine (see AccountStatus enum).
     * Stored as single char: 'A', 'F', 'C'.
     * Invariant: FROZEN or CLOSED forces fraud score to 1.0 in FraudRulesService.
     */
    @Column(name = "ACCT_STATUS", length = 1, nullable = false)
    private String acctStatus = "A";

    @Column(name = "ACCT_TYPE", length = 2, nullable = false)
    private String acctType;

    @Column(name = "HOME_COUNTRY", length = 3, nullable = false)
    private String homeCountry = "GBR";

    @Column(name = "DAILY_TXN_COUNT", nullable = false)
    private Integer dailyTxnCount = 0;

    @Column(name = "LAST_VELOCITY_TS")
    private LocalDateTime lastVelocityTs;

    @Column(name = "LAST_UPDATE_TS", nullable = false)
    private LocalDateTime lastUpdateTs = LocalDateTime.now();

    public AccountStatus getStatus() {
        return AccountStatus.fromCode(acctStatus);
    }

    // ----- getters / setters -----

    public String getAcctNo() { return acctNo; }
    public void setAcctNo(String v) { this.acctNo = v; }

    public String getCustId() { return custId; }
    public void setCustId(String v) { this.custId = v; }

    public String getCustFullName() { return custFullName; }
    public void setCustFullName(String v) { this.custFullName = v; }

    public String getAcctStatus() { return acctStatus; }
    public void setAcctStatus(String v) { this.acctStatus = v; }

    public String getAcctType() { return acctType; }
    public void setAcctType(String v) { this.acctType = v; }

    public String getHomeCountry() { return homeCountry; }
    public void setHomeCountry(String v) { this.homeCountry = v; }

    public Integer getDailyTxnCount() { return dailyTxnCount; }
    public void setDailyTxnCount(Integer v) { this.dailyTxnCount = v; }

    public LocalDateTime getLastVelocityTs() { return lastVelocityTs; }
    public void setLastVelocityTs(LocalDateTime v) { this.lastVelocityTs = v; }

    public LocalDateTime getLastUpdateTs() { return lastUpdateTs; }
    public void setLastUpdateTs(LocalDateTime v) { this.lastUpdateTs = v; }
}
