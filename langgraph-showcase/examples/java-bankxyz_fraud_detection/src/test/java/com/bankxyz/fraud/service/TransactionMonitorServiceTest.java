package com.bankxyz.fraud.service;

import com.bankxyz.fraud.config.FraudScoringProperties;
import com.bankxyz.fraud.entity.Transaction;
import com.bankxyz.fraud.repository.TransactionRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.data.domain.Pageable;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.Arrays;
import java.util.Collections;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * Unit tests for {@link TransactionMonitorService}, with {@link FraudRulesService}
 * and {@link AlertWriterService} mocked so the batch orchestration logic (which
 * transactions get picked up, stamped, alerted, or skipped on error) is isolated
 * from the scoring engine itself.
 */
@ExtendWith(MockitoExtension.class)
class TransactionMonitorServiceTest {

    @Mock private TransactionRepository txnRepo;
    @Mock private FraudRulesService rulesService;
    @Mock private AlertWriterService alertService;

    private TransactionMonitorService monitorService;

    @BeforeEach
    void setUp() {
        monitorService = new TransactionMonitorService(txnRepo, rulesService, alertService,
                new FraudScoringProperties());
    }

    private static Transaction pendingTxn(String txnId, String acctNo) {
        Transaction txn = new Transaction();
        txn.setTxnId(txnId);
        txn.setAcctNo(acctNo);
        txn.setTxnAmount(new BigDecimal("50.00"));
        txn.setChannel("ONLINE");
        txn.setTxnStatus("P");
        txn.setTxnTs(LocalDateTime.now());
        return txn;
    }

    @Test
    void emptyBatchWindowReportsNoPendingTransactions() {
        when(txnRepo.findByTxnStatusOrderByTxnTs(eq("P"), any(Pageable.class)))
                .thenReturn(Collections.emptyList());

        String summary = monitorService.processBatch(500);

        assertThat(summary).isEqualTo("NO PENDING TRANSACTIONS IN BATCH");
        verify(rulesService, never()).score(any(), anyInt());
    }

    @Test
    void cleanTransactionIsScoredAndStampedButNotAlerted() {
        Transaction txn = pendingTxn("TXN-B001", "ACC0000001");
        when(txnRepo.findByTxnStatusOrderByTxnTs(eq("P"), any(Pageable.class)))
                .thenReturn(Collections.singletonList(txn));

        String summary = monitorService.processBatch(500);

        assertThat(summary).isEqualTo("BATCH COMPLETE: SCORED=1 FLAGGED=0 ERRORS=0");
        verify(alertService, never()).writeAlert(any());
        verify(txnRepo).stampProcessed(eq("TXN-B001"), any(LocalDateTime.class));
    }

    @Test
    void flaggedTransactionIsScoredAlertedAndStamped() {
        Transaction txn = pendingTxn("TXN-B002", "ACC0000002");
        when(txnRepo.findByTxnStatusOrderByTxnTs(eq("P"), any(Pageable.class)))
                .thenReturn(Collections.singletonList(txn));
        org.mockito.Mockito.doAnswer(invocation -> {
            FraudCommArea ca = invocation.getArgument(0);
            ca.setFraudFlag(true);
            return null;
        }).when(rulesService).score(any(), anyInt());

        String summary = monitorService.processBatch(500);

        assertThat(summary).isEqualTo("BATCH COMPLETE: SCORED=1 FLAGGED=1 ERRORS=0");
        verify(alertService).writeAlert(any());
        verify(txnRepo).stampProcessed(eq("TXN-B002"), any(LocalDateTime.class));
    }

    @Test
    void aScoringFailureOnOneTransactionDoesNotAbortTheRestOfTheBatch() {
        Transaction failing = pendingTxn("TXN-B003", "ACC0000003");
        Transaction healthy = pendingTxn("TXN-B004", "ACC0000004");
        when(txnRepo.findByTxnStatusOrderByTxnTs(eq("P"), any(Pageable.class)))
                .thenReturn(Arrays.asList(failing, healthy));

        doThrow(new RuntimeException("Oracle timeout"))
                .when(rulesService).score(argThatTxn("ACC0000003"), anyInt());

        String summary = monitorService.processBatch(500);

        assertThat(summary).isEqualTo("BATCH COMPLETE: SCORED=1 FLAGGED=0 ERRORS=1");
        // The failed transaction is never stamped 'S' — it stays 'P' for the next run.
        verify(txnRepo, never()).stampProcessed(eq("TXN-B003"), any());
        verify(txnRepo).stampProcessed(eq("TXN-B004"), any(LocalDateTime.class));
    }

    @Test
    void respectsTheMaximumTransactionsCap() {
        when(txnRepo.findByTxnStatusOrderByTxnTs(eq("P"), any(Pageable.class)))
                .thenReturn(Collections.emptyList());

        monitorService.processBatch(2);

        verify(txnRepo).findByTxnStatusOrderByTxnTs(eq("P"),
                eq(org.springframework.data.domain.PageRequest.of(0, 2)));
    }

    private static FraudCommArea argThatTxn(String acctNo) {
        return org.mockito.ArgumentMatchers.argThat(ca -> ca != null && acctNo.equals(ca.getAcctNo()));
    }
}
