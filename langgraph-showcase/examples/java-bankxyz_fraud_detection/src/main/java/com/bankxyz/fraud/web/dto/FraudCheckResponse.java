package com.bankxyz.fraud.web.dto;

import com.bankxyz.fraud.domain.AuthDecision;

import java.math.BigDecimal;

/**
 * Response from the real-time authorisation check endpoint.
 *
 * returnCode values:
 *   APPROVE  → '00'
 *   REVIEW   → '20'  (flagged but allowed through)
 *   DECLINE  → '10'  (blocked)
 */
public class FraudCheckResponse {

    private String txnId;
    private AuthDecision decision;
    private String returnCode;
    private BigDecimal fraudScore;
    private String message;
    private long elapsedMs;

    public FraudCheckResponse(String txnId, AuthDecision decision,
                               BigDecimal fraudScore, String message, long elapsedMs) {
        this.txnId      = txnId;
        this.decision   = decision;
        this.returnCode = decision.getReturnCode();
        this.fraudScore = fraudScore;
        this.message    = message;
        this.elapsedMs  = elapsedMs;
    }

    // ----- getters -----

    public String getTxnId()          { return txnId; }
    public AuthDecision getDecision()  { return decision; }
    public String getReturnCode()      { return returnCode; }
    public BigDecimal getFraudScore()  { return fraudScore; }
    public String getMessage()         { return message; }
    public long getElapsedMs()         { return elapsedMs; }
}
