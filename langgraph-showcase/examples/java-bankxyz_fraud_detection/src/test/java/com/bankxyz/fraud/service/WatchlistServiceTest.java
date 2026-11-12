package com.bankxyz.fraud.service;

import com.bankxyz.fraud.entity.Account;
import com.bankxyz.fraud.entity.WatchlistHit;
import com.bankxyz.fraud.repository.AccountRepository;
import com.bankxyz.fraud.repository.WatchlistHitRepository;
import com.bankxyz.fraud.repository.WatchlistRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/** Unit tests for {@link WatchlistService}, with every repository mocked. */
@ExtendWith(MockitoExtension.class)
class WatchlistServiceTest {

    @Mock private WatchlistRepository watchlistRepo;
    @Mock private WatchlistHitRepository hitRepo;
    @Mock private AccountRepository accountRepo;

    private WatchlistService watchlistService;

    @BeforeEach
    void setUp() {
        watchlistService = new WatchlistService(watchlistRepo, hitRepo, accountRepo);
        Account account = new Account();
        account.setAcctNo("ACC0000001");
        account.setCustFullName("John Smith");
        lenient().when(accountRepo.findById("ACC0000001")).thenReturn(Optional.of(account));
    }

    private static FraudCommArea commArea() {
        FraudCommArea ca = new FraudCommArea();
        ca.setTxnId("TXN0000000000001");
        ca.setAcctNo("ACC0000001");
        return ca;
    }

    @Test
    void accountNotFoundSkipsAllScreening() {
        when(accountRepo.findById("ACC9999999")).thenReturn(Optional.empty());

        FraudCommArea ca = commArea();
        ca.setAcctNo("ACC9999999");
        watchlistService.screenWatchlist(ca);

        assertThat(ca.isOfacHit()).isFalse();
        assertThat(ca.isPepHit()).isFalse();
        assertThat(ca.isInternalHit()).isFalse();
        assertThat(ca.getWatchlistScore()).isEqualByComparingTo(BigDecimal.ZERO);
        verify(watchlistRepo, never()).countOfacHits(anyString());
    }

    @Test
    void ofacHitIsMandatoryEscalationAndIsLogged() {
        when(watchlistRepo.countOfacHits(anyString())).thenReturn(1L);

        FraudCommArea ca = commArea();
        watchlistService.screenWatchlist(ca);

        assertThat(ca.isOfacHit()).isTrue();
        assertThat(ca.getWatchlistScore()).isEqualByComparingTo(BigDecimal.ONE);
        assertThat(ca.getWatchlistReason()).isEqualTo("OFAC sanctions hit - mandatory escalation");
        verify(hitRepo).save(argThatHitType("OFAC"));
        verify(watchlistRepo, never()).countPepHits(anyString());
    }

    @Test
    void pepHitIsMandatoryEscalationAndIsLogged() {
        when(watchlistRepo.countOfacHits(anyString())).thenReturn(0L);
        when(watchlistRepo.countPepHits(anyString())).thenReturn(1L);

        FraudCommArea ca = commArea();
        watchlistService.screenWatchlist(ca);

        assertThat(ca.isPepHit()).isTrue();
        assertThat(ca.getWatchlistScore()).isEqualByComparingTo(BigDecimal.ONE);
        assertThat(ca.getWatchlistReason()).isEqualTo("PEP list hit - mandatory escalation");
        verify(hitRepo).save(argThatHitType("PEP"));
    }

    @Test
    void internalHitScoresPointNineAndIsLogged() {
        when(watchlistRepo.countOfacHits(anyString())).thenReturn(0L);
        when(watchlistRepo.countPepHits(anyString())).thenReturn(0L);
        when(watchlistRepo.countInternalHits(anyString(), anyString())).thenReturn(1L);

        FraudCommArea ca = commArea();
        watchlistService.screenWatchlist(ca);

        assertThat(ca.isInternalHit()).isTrue();
        assertThat(ca.getWatchlistScore()).isEqualByComparingTo(new BigDecimal("0.9000"));
        assertThat(ca.getWatchlistReason()).isEqualTo("Internal watchlist hit");
        verify(hitRepo).save(argThatHitType("INTERNAL"));
    }

    @Test
    void noHitsMeansACleanScreenAndNothingIsLogged() {
        when(watchlistRepo.countOfacHits(anyString())).thenReturn(0L);
        when(watchlistRepo.countPepHits(anyString())).thenReturn(0L);
        when(watchlistRepo.countInternalHits(anyString(), anyString())).thenReturn(0L);

        FraudCommArea ca = commArea();
        watchlistService.screenWatchlist(ca);

        assertThat(ca.isOfacHit()).isFalse();
        assertThat(ca.isPepHit()).isFalse();
        assertThat(ca.isInternalHit()).isFalse();
        assertThat(ca.getWatchlistScore()).isEqualByComparingTo(BigDecimal.ZERO);
        verify(hitRepo, never()).save(any());
    }

    @Test
    void aHitIsStillReportedEvenIfAuditLoggingFails() {
        // WatchlistService.logHit() swallows persistence failures so a broken
        // audit trail never blocks the mandatory-escalation decision itself.
        when(watchlistRepo.countOfacHits(anyString())).thenReturn(1L);
        when(hitRepo.save(any())).thenThrow(new RuntimeException("H2 is down"));

        FraudCommArea ca = commArea();
        watchlistService.screenWatchlist(ca);

        assertThat(ca.isOfacHit()).isTrue();
        assertThat(ca.getWatchlistScore()).isEqualByComparingTo(BigDecimal.ONE);
    }

    private static WatchlistHit argThatHitType(String expectedType) {
        return org.mockito.ArgumentMatchers.argThat(hit -> hit != null && expectedType.equals(hit.getHitType()));
    }
}
