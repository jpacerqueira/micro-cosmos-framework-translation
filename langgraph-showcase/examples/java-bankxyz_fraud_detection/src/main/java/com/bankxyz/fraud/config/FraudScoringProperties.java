package com.bankxyz.fraud.config;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;

/**
 * Externalised fraud scoring constants.
 *
 * Values can be overridden in application.properties or via environment
 * variable overrides with no rebuild.
 */
@Component
@ConfigurationProperties(prefix = "fraud.scoring")
public class FraudScoringProperties {

    /** Score at or above which a REVIEW alert is created (default 0.7500) */
    private BigDecimal scoreThreshold = new BigDecimal("0.7500");

    /** Score at or above which a real-time transaction is DECLINED (0.9000) */
    private BigDecimal declineThreshold = new BigDecimal("0.9000");

    /** Amount bands for signal 1 scoring */
    private BigDecimal highAmountLimit = new BigDecimal("5000.00");
    private BigDecimal medAmountLimit  = new BigDecimal("1000.00");
    private BigDecimal lowAmountLimit  = new BigDecimal("200.00");

    /** Velocity limit — batch uses 10, real-time uses 5 (halved window) */
    private int velocityLimitBatch    = 10;
    private int velocityLimitRealtime = 5;

    /** Signal weights — must sum to 1.0 */
    private BigDecimal weightAmount    = new BigDecimal("0.2500");
    private BigDecimal weightMerchant  = new BigDecimal("0.2500");
    private BigDecimal weightVelocity  = new BigDecimal("0.2000");
    private BigDecimal weightProfile   = new BigDecimal("0.2000");
    private BigDecimal weightWatchlist = new BigDecimal("0.1000");

    /** Real-time SLA limit in milliseconds (BRD-2009-FD-004) */
    private int slaLimitMs = 180;

    // ----- getters / setters -----

    public BigDecimal getScoreThreshold() { return scoreThreshold; }
    public void setScoreThreshold(BigDecimal v) { this.scoreThreshold = v; }

    public BigDecimal getDeclineThreshold() { return declineThreshold; }
    public void setDeclineThreshold(BigDecimal v) { this.declineThreshold = v; }

    public BigDecimal getHighAmountLimit() { return highAmountLimit; }
    public void setHighAmountLimit(BigDecimal v) { this.highAmountLimit = v; }

    public BigDecimal getMedAmountLimit() { return medAmountLimit; }
    public void setMedAmountLimit(BigDecimal v) { this.medAmountLimit = v; }

    public BigDecimal getLowAmountLimit() { return lowAmountLimit; }
    public void setLowAmountLimit(BigDecimal v) { this.lowAmountLimit = v; }

    public int getVelocityLimitBatch() { return velocityLimitBatch; }
    public void setVelocityLimitBatch(int v) { this.velocityLimitBatch = v; }

    public int getVelocityLimitRealtime() { return velocityLimitRealtime; }
    public void setVelocityLimitRealtime(int v) { this.velocityLimitRealtime = v; }

    public BigDecimal getWeightAmount() { return weightAmount; }
    public void setWeightAmount(BigDecimal v) { this.weightAmount = v; }

    public BigDecimal getWeightMerchant() { return weightMerchant; }
    public void setWeightMerchant(BigDecimal v) { this.weightMerchant = v; }

    public BigDecimal getWeightVelocity() { return weightVelocity; }
    public void setWeightVelocity(BigDecimal v) { this.weightVelocity = v; }

    public BigDecimal getWeightProfile() { return weightProfile; }
    public void setWeightProfile(BigDecimal v) { this.weightProfile = v; }

    public BigDecimal getWeightWatchlist() { return weightWatchlist; }
    public void setWeightWatchlist(BigDecimal v) { this.weightWatchlist = v; }

    public int getSlaLimitMs() { return slaLimitMs; }
    public void setSlaLimitMs(int v) { this.slaLimitMs = v; }
}
