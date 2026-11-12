package com.bankxyz.fraud.support;

import java.util.concurrent.atomic.AtomicLong;

/**
 * Generates short, unique transaction IDs for scenarios that don't care about
 * the literal value. Every entity that stores TXN_ID (Transaction, FraudAlert,
 * WatchlistHit, MqFailureLog, SlaBreachLog) declares it as VARCHAR(16) — a
 * System.nanoTime()-based id overflows that and fails the insert silently
 * wherever the write is wrapped in a try/catch (e.g. WatchlistService.logHit).
 */
public final class TestIds {

    private static final AtomicLong COUNTER = new AtomicLong();

    private TestIds() { }

    /** Exactly 16 characters: "TXNT" + a 12-digit zero-padded counter. */
    public static String nextTxnId() {
        return "TXNT" + String.format("%012d", COUNTER.incrementAndGet());
    }
}
