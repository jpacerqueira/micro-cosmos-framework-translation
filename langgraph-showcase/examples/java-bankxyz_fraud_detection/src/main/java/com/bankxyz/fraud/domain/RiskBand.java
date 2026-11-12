package com.bankxyz.fraud.domain;

/**
 * Merchant risk classification.
 *
 * Score mapping in FraudRulesService:
 *   BLOCKED → 1.0000
 *   HIGH    → 0.8000
 *   MED     → 0.4000
 *   LOW     → 0.1000
 *   UNKNOWN → 0.0000
 */
public enum RiskBand {
    HIGH("HIGH"),
    MED("MED "),
    LOW("LOW "),
    UNKNOWN("    ");

    private final String bandValue;

    RiskBand(String bandValue) { this.bandValue = bandValue; }

    public String getBandValue() { return bandValue; }

    public static RiskBand fromString(String value) {
        if (value == null) return UNKNOWN;
        String trimmed = value.trim().toUpperCase();
        for (RiskBand r : values()) {
            if (r.name().equals(trimmed) || r.bandValue.trim().equals(trimmed)) {
                return r;
            }
        }
        return UNKNOWN;
    }
}
