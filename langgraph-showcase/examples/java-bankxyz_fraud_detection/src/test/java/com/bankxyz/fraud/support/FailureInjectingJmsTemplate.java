package com.bankxyz.fraud.support;

import org.springframework.jms.UncategorizedJmsException;
import org.springframework.jms.core.JmsTemplate;

import javax.jms.ConnectionFactory;

/**
 * Wraps the real embedded-broker JmsTemplate so a scenario can simulate
 * "MQ broker unavailable" (ARCHITECTURE.md §8 invariant 9 — a failed MQ put
 * must not roll back the alert DB write) without tearing down the shared
 * in-VM ActiveMQ broker used by every other scenario.
 */
public class FailureInjectingJmsTemplate extends JmsTemplate {

    public FailureInjectingJmsTemplate(ConnectionFactory connectionFactory) {
        super(connectionFactory);
    }

    @Override
    public void convertAndSend(String destinationName, Object message) {
        if (MqFailureSwitch.shouldFail()) {
            throw new UncategorizedJmsException("Simulated MQ broker unavailable (BDD test)");
        }
        super.convertAndSend(destinationName, message);
    }
}
