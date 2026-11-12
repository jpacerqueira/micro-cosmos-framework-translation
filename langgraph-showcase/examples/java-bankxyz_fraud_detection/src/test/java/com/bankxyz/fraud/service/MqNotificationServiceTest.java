package com.bankxyz.fraud.service;

import com.bankxyz.fraud.repository.MqFailureLogRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.jms.UncategorizedJmsException;
import org.springframework.jms.core.JmsTemplate;
import org.springframework.test.util.ReflectionTestUtils;

import java.math.BigDecimal;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.catchThrowable;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;

/**
 * Unit tests for {@link MqNotificationService} — the non-fatal MQ failure
 * invariant (ARCHITECTURE.md §8 invariant 9) is exercised here at the unit
 * level with a mocked {@link JmsTemplate}, and separately end to end against
 * the embedded broker by alert_management.feature.
 */
@ExtendWith(MockitoExtension.class)
class MqNotificationServiceTest {

    private static final String ALERT_QUEUE = "FRAUD.ALERT.QUEUE";

    @Mock private JmsTemplate jmsTemplate;
    @Mock private MqFailureLogRepository failureLogRepo;

    private MqNotificationService mqNotificationService;

    @BeforeEach
    void setUp() {
        mqNotificationService = new MqNotificationService(jmsTemplate, failureLogRepo);
        ReflectionTestUtils.setField(mqNotificationService, "alertQueue", ALERT_QUEUE);
    }

    private static FraudCommArea commArea() {
        FraudCommArea ca = new FraudCommArea();
        ca.setTxnId("TXN0000000000001");
        ca.setAcctNo("ACC0000001");
        ca.setTxnAmount(new BigDecimal("100.00"));
        ca.setFraudScore(new BigDecimal("0.8000"));
        return ca;
    }

    @Test
    void sendsTheAlertMessageToTheConfiguredQueue() {
        mqNotificationService.notify(commArea());

        ArgumentCaptor<Object> captor = ArgumentCaptor.forClass(Object.class);
        verify(jmsTemplate).convertAndSend(eq(ALERT_QUEUE), captor.capture());
        assertThat(captor.getValue()).isInstanceOf(MqNotificationService.AlertMessage.class);
        MqNotificationService.AlertMessage message = (MqNotificationService.AlertMessage) captor.getValue();
        assertThat(message.getTxnId()).isEqualTo("TXN0000000000001");
        assertThat(message.getAcctNo()).isEqualTo("ACC0000001");
        assertThat(message.getStatus()).isEqualTo("PENDING");
        verify(failureLogRepo, never()).save(any());
    }

    @Test
    void nullChannelSerialisesToANullChannelField() {
        FraudCommArea ca = commArea();
        ca.setChannel(null);

        mqNotificationService.notify(ca);

        ArgumentCaptor<Object> captor = ArgumentCaptor.forClass(Object.class);
        verify(jmsTemplate).convertAndSend(eq(ALERT_QUEUE), captor.capture());
        assertThat(((MqNotificationService.AlertMessage) captor.getValue()).getChannel()).isNull();
    }

    @Test
    void aFailedMqPutIsLoggedAndNeverPropagatedToTheCaller() {
        doThrow(new UncategorizedJmsException("broker unavailable"))
                .when(jmsTemplate).convertAndSend(eq(ALERT_QUEUE), any(Object.class));

        FraudCommArea ca = commArea();

        // Must not throw — the alert transaction must stand regardless of MQ health.
        mqNotificationService.notify(ca);

        ArgumentCaptor<com.bankxyz.fraud.entity.MqFailureLog> captor =
                ArgumentCaptor.forClass(com.bankxyz.fraud.entity.MqFailureLog.class);
        verify(failureLogRepo).save(captor.capture());
        assertThat(captor.getValue().getTxnId()).isEqualTo("TXN0000000000001");
        assertThat(captor.getValue().getAcctNo()).isEqualTo("ACC0000001");
        assertThat(captor.getValue().getReasonCode()).isEqualTo(1);
    }

    @Test
    void aFailureLoggingErrorIsAlsoSwallowed() {
        // Belt-and-braces: even if writing to MQ_FAILURE_LOG itself throws, the
        // caller (AlertWriterService, inside its own @Transactional) must not see it.
        doThrow(new UncategorizedJmsException("broker unavailable"))
                .when(jmsTemplate).convertAndSend(eq(ALERT_QUEUE), any(Object.class));
        doThrow(new RuntimeException("H2 is down")).when(failureLogRepo).save(any());

        assertThat(catchThrowable(() -> mqNotificationService.notify(commArea()))).isNull();
    }
}
