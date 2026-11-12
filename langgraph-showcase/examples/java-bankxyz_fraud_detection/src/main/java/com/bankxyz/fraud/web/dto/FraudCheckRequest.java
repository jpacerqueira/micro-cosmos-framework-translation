package com.bankxyz.fraud.web.dto;

import java.math.BigDecimal;

/**
 * Inbound request for the real-time authorisation check endpoint.
 * All monetary fields are BigDecimal — never float/double.
 */
public class FraudCheckRequest {

    private String txnId;

    private String acctNo;

    /** BigDecimal — never float/double */
    private BigDecimal txnAmount;

    private String merchantCode;

    /**
     * Accepted values: ATM, ONLINE, BRANCH, CHIPPIN.
     * CHIPPIN → profile check skipped (BAU-2021-09).
     */
    private String channel;

    /** ISO 3166-1 alpha-3 country code */
    private String txnCountry;

    /** DB=Debit, CR=Credit, PP=Prepaid */
    private String cardType;

    /** true = card-not-present */
    private boolean cnpFlag;

    // ----- getters / setters -----

    public String getTxnId() { return txnId; }
    public void setTxnId(String v) { this.txnId = v; }

    public String getAcctNo() { return acctNo; }
    public void setAcctNo(String v) { this.acctNo = v; }

    public BigDecimal getTxnAmount() { return txnAmount; }
    public void setTxnAmount(BigDecimal v) { this.txnAmount = v; }

    public String getMerchantCode() { return merchantCode; }
    public void setMerchantCode(String v) { this.merchantCode = v; }

    public String getChannel() { return channel; }
    public void setChannel(String v) { this.channel = v; }

    public String getTxnCountry() { return txnCountry; }
    public void setTxnCountry(String v) { this.txnCountry = v; }

    public String getCardType() { return cardType; }
    public void setCardType(String v) { this.cardType = v; }

    public boolean isCnpFlag() { return cnpFlag; }
    public void setCnpFlag(boolean v) { this.cnpFlag = v; }
}
