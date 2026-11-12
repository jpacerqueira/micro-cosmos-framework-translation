package com.bankxyz.fraud.service;

import com.bankxyz.fraud.config.FraudScoringProperties;
import com.bankxyz.fraud.repository.TransactionRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.time.LocalDateTime;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.when;

/** Unit tests for {@link VelocityCheckService}, with {@link TransactionRepository} mocked. */
@ExtendWith(MockitoExtension.class)
class VelocityCheckServiceTest {

    @Mock private TransactionRepository txnRepo;

    private VelocityCheckService velocityService;

    @BeforeEach
    void setUp() {
        velocityService = new VelocityCheckService(txnRepo, new FraudScoringProperties());
    }

    @Test
    void zeroPriorTransactionsGivesAZeroScore() {
        when(txnRepo.countVelocity(eq("ACC0000001"), any(LocalDateTime.class))).thenReturn(0L);
        when(txnRepo.sumVelocityAmount(eq("ACC0000001"), any(LocalDateTime.class))).thenReturn(null);

        FraudCommArea ca = new FraudCommArea();
        ca.setAcctNo("ACC0000001");
        velocityService.checkVelocity(ca, 5);

        assertThat(ca.getTxnCount()).isZero();
        assertThat(ca.getTxnSum()).isEqualByComparingTo(BigDecimal.ZERO);
        assertThat(ca.getVelocityScore()).isEqualByComparingTo(BigDecimal.ZERO);
    }

    @Test
    void countBelowLimitIsNormalisedToCountOverLimit() {
        when(txnRepo.countVelocity(eq("ACC0000001"), any(LocalDateTime.class))).thenReturn(2L);
        when(txnRepo.sumVelocityAmount(eq("ACC0000001"), any(LocalDateTime.class)))
                .thenReturn(new BigDecimal("200.00"));

        FraudCommArea ca = new FraudCommArea();
        ca.setAcctNo("ACC0000001");
        velocityService.checkVelocity(ca, 5);

        assertThat(ca.getTxnCount()).isEqualTo(2L);
        assertThat(ca.getTxnSum()).isEqualByComparingTo(new BigDecimal("200.00"));
        assertThat(ca.getVelocityScore()).isEqualByComparingTo(new BigDecimal("0.4000"));
    }

    @Test
    void countAtTheLimitIsCappedAtOne() {
        when(txnRepo.countVelocity(eq("ACC0000001"), any(LocalDateTime.class))).thenReturn(5L);
        when(txnRepo.sumVelocityAmount(eq("ACC0000001"), any(LocalDateTime.class)))
                .thenReturn(new BigDecimal("500.00"));

        FraudCommArea ca = new FraudCommArea();
        ca.setAcctNo("ACC0000001");
        velocityService.checkVelocity(ca, 5);

        assertThat(ca.getVelocityScore()).isEqualByComparingTo(BigDecimal.ONE);
    }

    @Test
    void countAboveTheLimitIsStillCappedAtOne() {
        when(txnRepo.countVelocity(eq("ACC0000001"), any(LocalDateTime.class))).thenReturn(11L);
        when(txnRepo.sumVelocityAmount(eq("ACC0000001"), any(LocalDateTime.class)))
                .thenReturn(new BigDecimal("1100.00"));

        FraudCommArea ca = new FraudCommArea();
        ca.setAcctNo("ACC0000001");
        velocityService.checkVelocity(ca, 10);

        assertThat(ca.getVelocityScore()).isEqualByComparingTo(BigDecimal.ONE);
    }
}
