package com.bankxyz.fraud.domain;

/**
 * Transaction channel.
 *
 * Channel values (fixed-length, space-padded to 8 chars):
 *   ATM, ONLINE, BRANCH, CHIPPIN.
 * CHIPPIN skips the profile check to meet the 180ms SLA (BAU-2021-09).
 */
public enum Channel {
    ATM("ATM     "),
    ONLINE("ONLINE  "),
    BRANCH("BRANCH  "),
    CHIPPIN("CHIPPIN "),
    UNKNOWN("UNKNOWN ");

    private final String channelValue;

    Channel(String channelValue) { this.channelValue = channelValue; }

    public String getChannelValue() { return channelValue; }

    /** True for chip+PIN transactions — profile check is skipped to meet 180ms SLA (BAU-2021-09). */
    public boolean isChipPin() { return this == CHIPPIN; }

    public static Channel fromString(String value) {
        if (value == null) return UNKNOWN;
        String trimmed = value.trim().toUpperCase();
        for (Channel c : values()) {
            if (c.name().equals(trimmed) || c.channelValue.trim().equals(trimmed)) {
                return c;
            }
        }
        return UNKNOWN;
    }
}
