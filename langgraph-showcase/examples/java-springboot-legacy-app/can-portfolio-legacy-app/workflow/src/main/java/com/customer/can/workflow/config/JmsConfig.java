package com.customer.can.workflow.config;

import org.apache.activemq.ActiveMQConnectionFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.jms.config.DefaultJmsListenerContainerFactory;
import org.springframework.jms.core.JmsTemplate;

import javax.jms.ConnectionFactory;

@Configuration
public class JmsConfig {
    @Value("${spring.activemq.broker-url:tcp://localhost:61616}")
    private String brokerUrl;
    @Value("${spring.activemq.user:admin}")
    private String user;
    @Value("${spring.activemq.password:admin}")
    private String password;

    @Bean
    public ConnectionFactory connectionFactory() {
        ActiveMQConnectionFactory f = new ActiveMQConnectionFactory();
        f.setBrokerURL(brokerUrl);
        f.setUserName(user);
        f.setPassword(password);
        return f;
    }

    @Bean
    public JmsTemplate jmsTemplate(ConnectionFactory cf) {
        JmsTemplate t = new JmsTemplate(cf);
        t.setPubSubDomain(true);
        return t;
    }

    @Bean
    public DefaultJmsListenerContainerFactory jmsListenerContainerFactory(ConnectionFactory cf) {
        DefaultJmsListenerContainerFactory f = new DefaultJmsListenerContainerFactory();
        f.setConnectionFactory(cf);
        f.setPubSubDomain(true);
        f.setSessionTransacted(true);
        return f;
    }
}
