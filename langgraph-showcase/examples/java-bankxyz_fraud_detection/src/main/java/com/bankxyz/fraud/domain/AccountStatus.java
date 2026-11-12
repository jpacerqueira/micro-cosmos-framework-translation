package com.bankxyz.fraud.domain;

/**
 * Account status state machine.
 *
 * Values: 'A'=Active, 'F'=Frozen, 'C'=Closed.
 * Business invariant: FROZEN or CLOSED → fraud score forced to 1.0.
 */
public enum AccountStatus {
    ACTIVE('A'),
    FROZEN('F'),
    CLOSED('C');

    private final char code;

    AccountStatus(char code) { this.code = code; }

    public char getCode() { return code; }

    public static AccountStatus fromCode(String code) {
        if (code == null || code.isEmpty()) return ACTIVE;
        char c = code.trim().charAt(0);
        for (AccountStatus s : values()) {
            if (s.code == c) return s;
        }
        throw new IllegalArgumentException("Unknown account status: " + code);
    }

    public boolean isInactive() {
        return this == FROZEN || this == CLOSED;
    }
}
