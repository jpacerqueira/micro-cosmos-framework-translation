package com.bankxyz.fraud.support;

import org.apache.activemq.ActiveMQConnectionFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;
import org.springframework.jms.core.JmsTemplate;
import org.springframework.jms.support.converter.MappingJackson2MessageConverter;
import org.springframework.jms.support.converter.MessageConverter;
import org.springframework.jms.support.converter.MessageType;

/**
 * Replaces the production JmsTemplate bean (JmsConfig) with a
 * failure-injectable one so alert_management.feature can exercise the
 * non-fatal MQ failure path against the same embedded broker.
 *
 * Deliberately named differently from JmsConfig#jmsTemplate() — reusing that
 * bean name would make this a same-name override instead of a type-based
 * @Primary resolution, and JmsConfig's plain JmsTemplate would silently keep
 * winning autowiring depending on configuration processing order.
 */
@TestConfiguration
public class TestJmsConfig {

    @Value("${spring.activemq.broker-url}")
    private String brokerUrl;

    @Bean
    @Primary
    public JmsTemplate testJmsTemplate() {
        ActiveMQConnectionFactory factory = new ActiveMQConnectionFactory(brokerUrl);
        factory.setTrustAllPackages(true);

        MappingJackson2MessageConverter converter = new MappingJackson2MessageConverter();
        converter.setTargetType(MessageType.TEXT);
        converter.setTypeIdPropertyName("_type");

        FailureInjectingJmsTemplate template = new FailureInjectingJmsTemplate(factory);
        template.setMessageConverter(converter);
        return template;
    }
}
