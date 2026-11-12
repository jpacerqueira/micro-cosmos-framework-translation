package com.bankxyz.fraud.domain;

/**
 * Fraud alert status state machine.
 *
 * Valid transitions: PENDING → REVIEWED → CLOSED
 *                    PENDING → ESCALATED  (OFAC/PEP hits)
 */
public enum AlertStatus {
    PENDING,
    REVIEWED,
    CLOSED,
    ESCALATED;
}
