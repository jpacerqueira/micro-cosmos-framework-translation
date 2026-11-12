package com.bankxyz.fraud.support;

/**
 * Test-only toggle read by {@link FailureInjectingJmsTemplate} to simulate the
 * FRAUD.ALERT.QUEUE broker being unavailable, without tearing down the
 * embedded ActiveMQ broker used by every other scenario.
 */
public final class MqFailureSwitch {

    private static volatile boolean failNext = false;

    private MqFailureSwitch() { }

    public static void simulateFailure() { failNext = true; }

    public static void reset() { failNext = false; }

    public static boolean shouldFail() { return failNext; }
}
