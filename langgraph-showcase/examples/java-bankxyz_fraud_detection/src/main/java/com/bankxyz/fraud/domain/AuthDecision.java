package com.bankxyz.fraud.domain;

/**
 * Real-time authorisation decision.
 *
 * returnCode values:
 *   APPROVE  '00' — score < 0.75, or SLA breached (BRD-2009-FD-004 default)
 *   REVIEW   '20' — score >= 0.75: alert created, transaction allowed through
 *   DECLINE  '10' — score >= 0.90: transaction blocked
 */
public enum AuthDecision {
    APPROVE("00"),
    REVIEW("20"),
    DECLINE("10");

    private final String returnCode;

    AuthDecision(String returnCode) { this.returnCode = returnCode; }

    public String getReturnCode() { return returnCode; }
}
