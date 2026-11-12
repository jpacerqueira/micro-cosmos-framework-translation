package com.bankxyz.fraud.service;

import com.bankxyz.fraud.domain.Channel;

import java.math.BigDecimal;

/**
 * Shared data structure passed between fraud detection services.
 *
 * Carries input transaction data and accumulates scoring results as it is
 * passed through each service in the fraud pipeline.
 * All monetary fields are BigDecimal — never float/double.
 */
public class FraudCommArea {

    // ---- Transaction input ----

    private String txnId;
    private String acctNo;
    private BigDecimal txnAmount;
    private String merchantCode;
    private Channel channel;
    private String txnCountry;
    private String cardType;
    private boolean cnpFlag;

    // ---- Fraud result (set by FraudRulesService / sub-services) ----

    private BigDecimal fraudScore = BigDecimal.ZERO;
    private boolean fraudFlag = false;
    private String returnCode = "00";
    private String message = "";

    // ---- Signal 3: Velocity (set by VelocityCheckService) ----

    private BigDecimal velocityScore = BigDecimal.ZERO;
    private long txnCount = 0;
    private BigDecimal txnSum = BigDecimal.ZERO;

    // ---- Signal 4: Customer profile (set by CustomerProfileService) ----

    private BigDecimal profileScore = BigDecimal.ZERO;
    private boolean crossBorder = false;

    // ---- Signal 5: Watchlist (set by WatchlistService) ----

    private BigDecimal watchlistScore = BigDecimal.ZERO;
    private boolean ofacHit = false;
    private boolean pepHit = false;
    private boolean internalHit = false;
    private String watchlistReason = "";

    // ---- Per-call scoring weights (adjusted for chip+PIN mode) ----

    private BigDecimal weightAmount;
    private BigDecimal weightMerchant;
    private BigDecimal weightVelocity;
    private BigDecimal weightProfile;
    private BigDecimal weightWatchlist;

    // ---- Alert ID set by AlertWriterService ----

    private Long alertId;

    // ----- getters / setters -----

    public String getTxnId() { return txnId; }
    public void setTxnId(String v) { this.txnId = v; }

    public String getAcctNo() { return acctNo; }
    public void setAcctNo(String v) { this.acctNo = v; }

    public BigDecimal getTxnAmount() { return txnAmount; }
    public void setTxnAmount(BigDecimal v) { this.txnAmount = v; }

    public String getMerchantCode() { return merchantCode; }
    public void setMerchantCode(String v) { this.merchantCode = v; }

    public Channel getChannel() { return channel; }
    public void setChannel(Channel v) { this.channel = v; }

    public String getTxnCountry() { return txnCountry; }
    public void setTxnCountry(String v) { this.txnCountry = v; }

    public String getCardType() { return cardType; }
    public void setCardType(String v) { this.cardType = v; }

    public boolean isCnpFlag() { return cnpFlag; }
    public void setCnpFlag(boolean v) { this.cnpFlag = v; }

    public BigDecimal getFraudScore() { return fraudScore; }
    public void setFraudScore(BigDecimal v) { this.fraudScore = v; }

    public boolean isFraudFlag() { return fraudFlag; }
    public void setFraudFlag(boolean v) { this.fraudFlag = v; }

    public String getReturnCode() { return returnCode; }
    public void setReturnCode(String v) { this.returnCode = v; }

    public String getMessage() { return message; }
    public void setMessage(String v) { this.message = v; }

    public BigDecimal getVelocityScore() { return velocityScore; }
    public void setVelocityScore(BigDecimal v) { this.velocityScore = v; }

    public long getTxnCount() { return txnCount; }
    public void setTxnCount(long v) { this.txnCount = v; }

    public BigDecimal getTxnSum() { return txnSum; }
    public void setTxnSum(BigDecimal v) { this.txnSum = v; }

    public BigDecimal getProfileScore() { return profileScore; }
    public void setProfileScore(BigDecimal v) { this.profileScore = v; }

    public boolean isCrossBorder() { return crossBorder; }
    public void setCrossBorder(boolean v) { this.crossBorder = v; }

    public BigDecimal getWatchlistScore() { return watchlistScore; }
    public void setWatchlistScore(BigDecimal v) { this.watchlistScore = v; }

    public boolean isOfacHit() { return ofacHit; }
    public void setOfacHit(boolean v) { this.ofacHit = v; }

    public boolean isPepHit() { return pepHit; }
    public void setPepHit(boolean v) { this.pepHit = v; }

    public boolean isInternalHit() { return internalHit; }
    public void setInternalHit(boolean v) { this.internalHit = v; }

    public String getWatchlistReason() { return watchlistReason; }
    public void setWatchlistReason(String v) { this.watchlistReason = v; }

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

    public Long getAlertId() { return alertId; }
    public void setAlertId(Long v) { this.alertId = v; }
}
