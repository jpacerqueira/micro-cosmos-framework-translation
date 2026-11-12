package com.bankxyz.fraud.service;

import com.bankxyz.fraud.entity.FraudAlert;
import com.bankxyz.fraud.repository.FraudAlertRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * Unit tests for {@link AlertWriterService}, with {@link FraudAlertRepository} and
 * {@link MqNotificationService} mocked — the real MQ non-fatal-failure behaviour is
 * covered end to end by alert_management.feature against the embedded broker.
 */
@ExtendWith(MockitoExtension.class)
class AlertWriterServiceTest {

    @Mock private FraudAlertRepository alertRepo;
    @Mock private MqNotificationService mqNotify;

    private AlertWriterService alertWriterService;

    @BeforeEach
    void setUp() {
        alertWriterService = new AlertWriterService(alertRepo, mqNotify);
    }

    @Test
    void writesTheAlertNotifiesMqAndPopulatesTheGeneratedId() {
        when(alertRepo.save(any())).thenAnswer(invocation -> {
            FraudAlert saved = invocation.getArgument(0);
            saved.setAlertId(42L);
            return saved;
        });

        FraudCommArea ca = new FraudCommArea();
        ca.setTxnId("TXN0000000000001");
        ca.setAcctNo("ACC0000001");
        ca.setTxnAmount(new BigDecimal("2500.00"));
        ca.setFraudScore(new BigDecimal("0.8250"));

        alertWriterService.writeAlert(ca);

        assertThat(ca.getAlertId()).isEqualTo(42L);
        assertThat(ca.getReturnCode()).isEqualTo("00");
        assertThat(ca.getMessage()).isEqualTo("Fraud alert written successfully");

        ArgumentCaptor<FraudAlert> captor = ArgumentCaptor.forClass(FraudAlert.class);
        verify(alertRepo).save(captor.capture());
        assertThat(captor.getValue().getTxnId()).isEqualTo("TXN0000000000001");
        assertThat(captor.getValue().getAcctNo()).isEqualTo("ACC0000001");
        assertThat(captor.getValue().getTxnAmount()).isEqualByComparingTo(new BigDecimal("2500.00"));
        assertThat(captor.getValue().getFraudScore()).isEqualByComparingTo(new BigDecimal("0.8250"));

        verify(mqNotify).notify(ca);
    }

    @Test
    void mqNotificationRunsAfterTheAlertIsSaved() {
        when(alertRepo.save(any())).thenAnswer(invocation -> {
            FraudAlert saved = invocation.getArgument(0);
            saved.setAlertId(7L);
            return saved;
        });

        FraudCommArea ca = new FraudCommArea();
        ca.setTxnId("TXN0000000000002");
        ca.setAcctNo("ACC0000002");
        ca.setTxnAmount(new BigDecimal("100.00"));
        ca.setFraudScore(new BigDecimal("0.9000"));

        alertWriterService.writeAlert(ca);

        // AlertWriterService must set commArea.alertId from the persisted row
        // BEFORE calling mqNotify, since MqNotificationService.AlertMessage reads it.
        assertThat(ca.getAlertId()).isEqualTo(7L);
        verify(mqNotify).notify(ca);
    }
}
