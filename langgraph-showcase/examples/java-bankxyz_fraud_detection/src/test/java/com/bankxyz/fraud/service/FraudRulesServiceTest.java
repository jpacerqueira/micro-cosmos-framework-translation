package com.bankxyz.fraud.service;

import com.bankxyz.fraud.config.FraudScoringProperties;
import com.bankxyz.fraud.domain.Channel;
import com.bankxyz.fraud.entity.Account;
import com.bankxyz.fraud.entity.MerchantRisk;
import com.bankxyz.fraud.repository.AccountRepository;
import com.bankxyz.fraud.repository.MerchantRiskRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * Unit tests for {@link FraudRulesService} with every collaborator mocked, so
 * each test isolates exactly one branch of the composite scoring engine.
 * End-to-end behaviour against a real database is covered separately by
 * fraud_scoring.feature.
 */
@ExtendWith(MockitoExtension.class)
class FraudRulesServiceTest {

    private static final int VELOCITY_LIMIT = 5;

    @Mock private AccountRepository accountRepo;
    @Mock private MerchantRiskRepository merchantRepo;
    @Mock private VelocityCheckService velocityService;
    @Mock private CustomerProfileService profileService;
    @Mock private WatchlistService watchlistService;

    private FraudScoringProperties props;
    private FraudRulesService rulesService;

    @BeforeEach
    void setUp() {
        props = new FraudScoringProperties();
        rulesService = new FraudRulesService(accountRepo, merchantRepo, velocityService, profileService,
                watchlistService, props);
    }

    private static Account activeAccount(String acctNo) {
        Account account = new Account();
        account.setAcctNo(acctNo);
        account.setCustFullName("Test Customer");
        account.setAcctStatus("A");
        return account;
    }

    private FraudCommArea commArea(String acctNo, BigDecimal amount, String merchantCode, Channel channel) {
        FraudCommArea ca = new FraudCommArea();
        ca.setTxnId("TXN0000000000001");
        ca.setAcctNo(acctNo);
        ca.setTxnAmount(amount);
        ca.setMerchantCode(merchantCode);
        ca.setChannel(channel);
        return ca;
    }

    @Test
    void unknownAccountIsRejectedBeforeAnyScoringSignalRuns() {
        when(accountRepo.findById("ACC9999999")).thenReturn(Optional.empty());

        FraudCommArea ca = commArea("ACC9999999", new BigDecimal("10.00"), null, Channel.ONLINE);
        rulesService.score(ca, VELOCITY_LIMIT);

        assertThat(ca.getReturnCode()).isEqualTo("05");
        assertThat(ca.getMessage()).isEqualTo("Account not found");
        verifyNoSignalServiceWasInvoked();
    }

    @Test
    void frozenAccountIsAutoFlaggedWithoutRunningTheRemainingSignals() {
        Account frozen = activeAccount("ACC0000001");
        frozen.setAcctStatus("F");
        when(accountRepo.findById("ACC0000001")).thenReturn(Optional.of(frozen));

        FraudCommArea ca = commArea("ACC0000001", new BigDecimal("10.00"), null, Channel.ONLINE);
        rulesService.score(ca, VELOCITY_LIMIT);

        assertThat(ca.getFraudScore()).isEqualByComparingTo(BigDecimal.ONE);
        assertThat(ca.isFraudFlag()).isTrue();
        assertThat(ca.getReturnCode()).isEqualTo("10");
        assertThat(ca.getMessage()).isEqualTo("Account inactive - auto-flagged");
        verifyNoSignalServiceWasInvoked();
    }

    @Test
    void closedAccountIsAutoFlaggedWithoutRunningTheRemainingSignals() {
        Account closed = activeAccount("ACC0000001");
        closed.setAcctStatus("C");
        when(accountRepo.findById("ACC0000001")).thenReturn(Optional.of(closed));

        FraudCommArea ca = commArea("ACC0000001", new BigDecimal("10.00"), null, Channel.ONLINE);
        rulesService.score(ca, VELOCITY_LIMIT);

        assertThat(ca.getFraudScore()).isEqualByComparingTo(BigDecimal.ONE);
        assertThat(ca.isFraudFlag()).isTrue();
        verifyNoSignalServiceWasInvoked();
    }

    private void verifyNoSignalServiceWasInvoked() {
        verify(velocityService, never()).checkVelocity(any(), anyInt());
        verify(profileService, never()).scoreProfile(any());
        verify(watchlistService, never()).screenWatchlist(any());
    }

    @Test
    void ofacHitForcesScoreToOneRegardlessOfOtherSignals() {
        stubNeutralAccountAndSignals("ACC0000001");
        stubWatchlistHit(true, false, "OFAC sanctions hit - mandatory escalation");

        FraudCommArea ca = commArea("ACC0000001", new BigDecimal("10.00"), null, Channel.ONLINE);
        rulesService.score(ca, VELOCITY_LIMIT);

        assertThat(ca.getFraudScore()).isEqualByComparingTo(BigDecimal.ONE);
        assertThat(ca.isFraudFlag()).isTrue();
        assertThat(ca.getReturnCode()).isEqualTo("10");
        assertThat(ca.getMessage()).isEqualTo("OFAC sanctions hit - mandatory escalation");
    }

    @Test
    void pepHitForcesScoreToOneRegardlessOfOtherSignals() {
        stubNeutralAccountAndSignals("ACC0000001");
        stubWatchlistHit(false, true, "PEP list hit - mandatory escalation");

        FraudCommArea ca = commArea("ACC0000001", new BigDecimal("10.00"), null, Channel.ONLINE);
        rulesService.score(ca, VELOCITY_LIMIT);

        assertThat(ca.getFraudScore()).isEqualByComparingTo(BigDecimal.ONE);
        assertThat(ca.getMessage()).isEqualTo("PEP list hit - mandatory escalation");
    }

    @Test
    void compositeBelowThresholdClearsTheTransaction() {
        stubNeutralAccountAndSignals("ACC0000001");
        stubSignalScores(new BigDecimal("0.2000"), new BigDecimal("0.3000"), BigDecimal.ZERO);

        // amount 50.00 -> low band (< 200) -> amountScore 0.1000
        FraudCommArea ca = commArea("ACC0000001", new BigDecimal("50.00"), null, Channel.ONLINE);
        rulesService.score(ca, VELOCITY_LIMIT);

        // composite = 0.1*0.25 + 0*0.25(no merchant) + 0.2*0.20 + 0.3*0.20 + 0*0.10 = 0.1250
        assertThat(ca.getFraudScore()).isEqualByComparingTo(new BigDecimal("0.1250"));
        assertThat(ca.isFraudFlag()).isFalse();
        assertThat(ca.getReturnCode()).isEqualTo("00");
        assertThat(ca.getMessage()).isEqualTo("Transaction cleared");
    }

    @Test
    void compositeAtOrAboveThresholdFlagsHighRisk() {
        stubNeutralAccountAndSignals("ACC0000001");
        stubSignalScores(BigDecimal.ONE, new BigDecimal("0.3000"), new BigDecimal("0.9000"));
        when(merchantRepo.findById("MCH00001")).thenReturn(Optional.of(blockedMerchant("MCH00001")));

        // amount 9999.00 -> high band -> 0.8000
        FraudCommArea ca = commArea("ACC0000001", new BigDecimal("9999.00"), "MCH00001", Channel.ONLINE);
        rulesService.score(ca, VELOCITY_LIMIT);

        // composite = 0.8*0.25 + 1.0*0.25 + 1.0*0.20 + 0.3*0.20 + 0.9*0.10 = 0.8000
        assertThat(ca.getFraudScore()).isEqualByComparingTo(new BigDecimal("0.8000"));
        assertThat(ca.isFraudFlag()).isTrue();
        assertThat(ca.getReturnCode()).isEqualTo("10");
        assertThat(ca.getMessage()).isEqualTo("Transaction flagged as high risk");
    }

    @Test
    void chipPinChannelZeroesTheProfileWeightAndRedistributesIt() {
        stubNeutralAccountAndSignals("ACC0000001");
        stubSignalScores(BigDecimal.ZERO, new BigDecimal("0.4000"), BigDecimal.ZERO);

        FraudCommArea ca = commArea("ACC0000001", new BigDecimal("50.00"), null, Channel.CHIPPIN);
        rulesService.score(ca, VELOCITY_LIMIT);

        assertThat(ca.getWeightProfile()).isEqualByComparingTo(BigDecimal.ZERO);
        assertThat(ca.getWeightAmount()).isEqualByComparingTo(new BigDecimal("0.2500"));
        assertThat(ca.getWeightVelocity()).isEqualByComparingTo(new BigDecimal("0.2500"));
        assertThat(ca.getWeightWatchlist()).isEqualByComparingTo(new BigDecimal("0.2500"));
        // profile score (0.4) contributes nothing: composite = 0.1*0.25 (low amount band) = 0.025
        assertThat(ca.getFraudScore()).isEqualByComparingTo(new BigDecimal("0.0250"));
    }

    @Test
    void unknownMerchantContributesNoMerchantSignal() {
        stubNeutralAccountAndSignals("ACC0000001");
        stubSignalScores(BigDecimal.ZERO, BigDecimal.ZERO, BigDecimal.ZERO);
        when(merchantRepo.findById("MCHABSENT")).thenReturn(Optional.empty());

        FraudCommArea ca = commArea("ACC0000001", new BigDecimal("50.00"), "MCHABSENT", Channel.ONLINE);
        rulesService.score(ca, VELOCITY_LIMIT);

        assertThat(ca.getFraudScore()).isEqualByComparingTo(new BigDecimal("0.0250"));
    }

    @Test
    void mediumRiskMerchantScoresPointFour() {
        stubNeutralAccountAndSignals("ACC0000001");
        stubSignalScores(BigDecimal.ZERO, BigDecimal.ZERO, BigDecimal.ZERO);
        MerchantRisk medRisk = new MerchantRisk();
        medRisk.setMerchantCode("MCHMED001");
        medRisk.setBlockedFlag("N");
        medRisk.setRiskBand("MED ");
        when(merchantRepo.findById("MCHMED001")).thenReturn(Optional.of(medRisk));

        FraudCommArea ca = commArea("ACC0000001", new BigDecimal("50.00"), "MCHMED001", Channel.ONLINE);
        rulesService.score(ca, VELOCITY_LIMIT);

        // composite = amount(0.1*.25=.025) + merchant(0.4*.25=.10) = 0.125
        assertThat(ca.getFraudScore()).isEqualByComparingTo(new BigDecimal("0.1250"));
    }

    @Test
    void blankMerchantCodeContributesNoMerchantSignal() {
        stubNeutralAccountAndSignals("ACC0000001");
        stubSignalScores(BigDecimal.ZERO, BigDecimal.ZERO, BigDecimal.ZERO);

        FraudCommArea ca = commArea("ACC0000001", new BigDecimal("50.00"), "   ", Channel.ONLINE);
        rulesService.score(ca, VELOCITY_LIMIT);

        assertThat(ca.getFraudScore()).isEqualByComparingTo(new BigDecimal("0.0250"));
    }

    @Test
    void compositeIsCappedAtOneEvenIfASignalMisbehaves() {
        stubNeutralAccountAndSignals("ACC0000001");
        // A well-behaved sub-service can never return > 1.0, but the composite
        // arithmetic still defends against it — exercise that safety net directly.
        stubSignalScores(new BigDecimal("2.0000"), new BigDecimal("2.0000"), new BigDecimal("2.0000"));
        when(merchantRepo.findById("MCH00001")).thenReturn(Optional.of(blockedMerchant("MCH00001")));

        FraudCommArea ca = commArea("ACC0000001", new BigDecimal("9999.00"), "MCH00001", Channel.ONLINE);
        rulesService.score(ca, VELOCITY_LIMIT);

        assertThat(ca.getFraudScore()).isEqualByComparingTo(BigDecimal.ONE);
    }

    // ----- fixture helpers -----

    private void stubNeutralAccountAndSignals(String acctNo) {
        when(accountRepo.findById(acctNo)).thenReturn(Optional.of(activeAccount(acctNo)));
    }

    private void stubSignalScores(BigDecimal velocity, BigDecimal profile, BigDecimal watchlist) {
        doAnswer(invocation -> {
            FraudCommArea ca = invocation.getArgument(0);
            ca.setVelocityScore(velocity);
            return null;
        }).when(velocityService).checkVelocity(any(), anyInt());

        doAnswer(invocation -> {
            FraudCommArea ca = invocation.getArgument(0);
            ca.setProfileScore(profile);
            return null;
        }).when(profileService).scoreProfile(any());

        doAnswer(invocation -> {
            FraudCommArea ca = invocation.getArgument(0);
            ca.setWatchlistScore(watchlist);
            return null;
        }).when(watchlistService).screenWatchlist(any());
    }

    private void stubWatchlistHit(boolean ofac, boolean pep, String reason) {
        // Stub velocity/profile directly rather than via stubSignalScores(): that
        // helper also stubs watchlistService.screenWatchlist(), which we then
        // immediately override below — Mockito's strict stubs checker flags an
        // overridden-before-first-use stub as unnecessary.
        doAnswer(invocation -> {
            FraudCommArea ca = invocation.getArgument(0);
            ca.setVelocityScore(BigDecimal.ZERO);
            return null;
        }).when(velocityService).checkVelocity(any(), anyInt());
        doAnswer(invocation -> {
            FraudCommArea ca = invocation.getArgument(0);
            ca.setProfileScore(BigDecimal.ZERO);
            return null;
        }).when(profileService).scoreProfile(any());

        doAnswer(invocation -> {
            FraudCommArea ca = invocation.getArgument(0);
            ca.setOfacHit(ofac);
            ca.setPepHit(pep);
            ca.setWatchlistScore(BigDecimal.ONE);
            ca.setWatchlistReason(reason);
            return null;
        }).when(watchlistService).screenWatchlist(any());
    }

    private static MerchantRisk blockedMerchant(String code) {
        MerchantRisk merchant = new MerchantRisk();
        merchant.setMerchantCode(code);
        merchant.setBlockedFlag("Y");
        merchant.setRiskBand("HIGH");
        return merchant;
    }
}
