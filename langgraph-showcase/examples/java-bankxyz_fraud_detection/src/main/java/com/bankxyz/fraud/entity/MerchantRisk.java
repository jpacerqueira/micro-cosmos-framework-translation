package com.bankxyz.fraud.entity;

import javax.persistence.*;
import java.time.LocalDate;
import java.time.LocalDateTime;

/**
 * Maps to MERCHANT_RISK.
 * Maintained by the fraud operations team.
 * Read by FraudRulesService for the merchant risk scoring signal.
 */
@Entity
@Table(name = "MERCHANT_RISK")
public class MerchantRisk {

    @Id
    @Column(name = "MERCHANT_CODE", length = 8, nullable = false)
    private String merchantCode;

    @Column(name = "MERCHANT_NAME", length = 80)
    private String merchantName;

    /** 'Y' = blocked entirely → merchant score = 1.0 */
    @Column(name = "BLOCKED_FLAG", length = 1, nullable = false)
    private String blockedFlag = "N";

    /** 'HIGH', 'MED ', 'LOW ' */
    @Column(name = "RISK_BAND", length = 4, nullable = false)
    private String riskBand = "LOW ";

    @Column(name = "BLOCK_REASON", length = 80)
    private String blockReason;

    @Column(name = "EFFECTIVE_FROM", nullable = false)
    private LocalDate effectiveFrom = LocalDate.now();

    @Column(name = "EFFECTIVE_TO")
    private LocalDate effectiveTo;

    @Column(name = "LAST_UPDATE_TS", nullable = false)
    private LocalDateTime lastUpdateTs = LocalDateTime.now();

    public boolean isBlocked() { return "Y".equals(blockedFlag); }

    // ----- getters / setters -----

    public String getMerchantCode() { return merchantCode; }
    public void setMerchantCode(String v) { this.merchantCode = v; }

    public String getMerchantName() { return merchantName; }
    public void setMerchantName(String v) { this.merchantName = v; }

    public String getBlockedFlag() { return blockedFlag; }
    public void setBlockedFlag(String v) { this.blockedFlag = v; }

    public String getRiskBand() { return riskBand; }
    public void setRiskBand(String v) { this.riskBand = v; }

    public String getBlockReason() { return blockReason; }
    public void setBlockReason(String v) { this.blockReason = v; }

    public LocalDate getEffectiveFrom() { return effectiveFrom; }
    public void setEffectiveFrom(LocalDate v) { this.effectiveFrom = v; }

    public LocalDate getEffectiveTo() { return effectiveTo; }
    public void setEffectiveTo(LocalDate v) { this.effectiveTo = v; }

    public LocalDateTime getLastUpdateTs() { return lastUpdateTs; }
    public void setLastUpdateTs(LocalDateTime v) { this.lastUpdateTs = v; }
}
