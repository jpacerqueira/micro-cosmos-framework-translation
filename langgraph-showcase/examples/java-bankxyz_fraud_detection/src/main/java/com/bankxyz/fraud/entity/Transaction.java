package com.bankxyz.fraud.entity;

import javax.persistence.*;
import java.math.BigDecimal;
import java.time.LocalDateTime;

/**
 * Maps to TXN_QUEUE.
 * Staging table for transactions awaiting fraud scoring.
 * Written by: authorisation feed and card scheme gateway.
 * Read by: TransactionMonitorService (batch), RealtimeCheckController, VelocityCheckService.
 *
 * All monetary fields use BigDecimal — never float/double.
 */
@Entity
@Table(name = "TXN_QUEUE")
public class Transaction {

    @Id
    @Column(name = "TXN_ID", length = 16, nullable = false)
    private String txnId;

    @Column(name = "ACCT_NO", length = 10, nullable = false)
    private String acctNo;

    /** NUMBER(15,2). Never use float. */
    @Column(name = "TXN_AMOUNT", precision = 15, scale = 2, nullable = false)
    private BigDecimal txnAmount;

    @Column(name = "MERCHANT_CODE", length = 8)
    private String merchantCode;

    @Column(name = "CHANNEL", length = 8, nullable = false)
    private String channel = "UNKNOWN";

    @Column(name = "TXN_COUNTRY", length = 3, nullable = false)
    private String txnCountry = "GBR";

    @Column(name = "CARD_LAST4", length = 4)
    private String cardLast4;

    @Column(name = "CARD_TYPE", length = 2)
    private String cardType;

    /** Card-not-present flag: 'Y' or 'N'. */
    @Column(name = "CNP_FLAG", length = 1, nullable = false)
    private String cnpFlag = "N";

    /** TXN_STATUS: 'P'=Pending, 'S'=Scored, 'E'=Error */
    @Column(name = "TXN_STATUS", length = 1, nullable = false)
    private String txnStatus = "P";

    @Column(name = "TXN_TS", nullable = false)
    private LocalDateTime txnTs = LocalDateTime.now();

    @Column(name = "PROC_TS")
    private LocalDateTime procTs;

    @Column(name = "BATCH_DATE", length = 10)
    private String batchDate;

    public boolean isCnp() { return "Y".equals(cnpFlag); }

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

    public String getCardLast4() { return cardLast4; }
    public void setCardLast4(String v) { this.cardLast4 = v; }

    public String getCardType() { return cardType; }
    public void setCardType(String v) { this.cardType = v; }

    public String getCnpFlag() { return cnpFlag; }
    public void setCnpFlag(String v) { this.cnpFlag = v; }

    public String getTxnStatus() { return txnStatus; }
    public void setTxnStatus(String v) { this.txnStatus = v; }

    public LocalDateTime getTxnTs() { return txnTs; }
    public void setTxnTs(LocalDateTime v) { this.txnTs = v; }

    public LocalDateTime getProcTs() { return procTs; }
    public void setProcTs(LocalDateTime v) { this.procTs = v; }

    public String getBatchDate() { return batchDate; }
    public void setBatchDate(String v) { this.batchDate = v; }
}
