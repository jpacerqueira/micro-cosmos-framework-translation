package com.bankxyz.fraud.service;

import com.bankxyz.fraud.config.FraudScoringProperties;
import com.bankxyz.fraud.domain.AccountStatus;
import com.bankxyz.fraud.domain.Channel;
import com.bankxyz.fraud.domain.RiskBand;
import com.bankxyz.fraud.entity.Account;
import com.bankxyz.fraud.entity.MerchantRisk;
import com.bankxyz.fraud.repository.AccountRepository;
import com.bankxyz.fraud.repository.MerchantRiskRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.Optional;

/**
 * Five-signal composite fraud scoring engine.
 *
 * Combines five independent signals into a composite score (0.0–1.0):
 *   Signal 1 — Transaction amount         (weight: 0.25)
 *   Signal 2 — Merchant risk band         (weight: 0.25)
 *   Signal 3 — 24-hour velocity           (weight: 0.20) → VelocityCheckService
 *   Signal 4 — Customer profile deviation (weight: 0.20) → CustomerProfileService
 *   Signal 5 — Watchlist / sanctions      (weight: 0.10) → WatchlistService
 *
 * Business invariants:
 *   - Frozen ('F') or Closed ('C') account → score forced to 1.0
 *   - OFAC or PEP watchlist hit → score forced to 1.0 (immediate escalation)
 *   - Score >= 0.75 → fraudFlag = true, returnCode = '10'
 *   - chip+PIN channel → profile weight = 0, redistributed to other signals (BAU-2021-09)
 *   - Composite score is capped at 1.0
 *   - All arithmetic uses BigDecimal — never float/double
 */
@Service
public class FraudRulesService {

    private static final Logger log = LoggerFactory.getLogger(FraudRulesService.class);

    private final AccountRepository accountRepo;
    private final MerchantRiskRepository merchantRepo;
    private final VelocityCheckService velocityService;
    private final CustomerProfileService profileService;
    private final WatchlistService watchlistService;
    private final FraudScoringProperties props;

    public FraudRulesService(AccountRepository accountRepo,
                              MerchantRiskRepository merchantRepo,
                              VelocityCheckService velocityService,
                              CustomerProfileService profileService,
                              WatchlistService watchlistService,
                              FraudScoringProperties props) {
        this.accountRepo = accountRepo;
        this.merchantRepo = merchantRepo;
        this.velocityService = velocityService;
        this.profileService = profileService;
        this.watchlistService = watchlistService;
        this.props = props;
    }

    /**
     * Run the full fraud scoring pipeline for a single transaction.
     *
     * @param commArea shared data object; txnId, acctNo, txnAmount, merchantCode,
     *                 channel, txnCountry, cnpFlag must be populated by the caller.
     * @param velocityLimit 10 for batch, 5 for real-time
     */
    public void score(FraudCommArea commArea, int velocityLimit) {
        initialiseWeights(commArea);

        // --- Validate account -----------------------------------------------
        Optional<Account> accountOpt = accountRepo.findById(commArea.getAcctNo());
        if (!accountOpt.isPresent()) {
            commArea.setReturnCode("05");
            commArea.setMessage("Account not found");
            return;
        }
        Account account = accountOpt.get();

        // Invariant: frozen or closed accounts are automatically high risk
        if (account.getStatus().isInactive()) {
            commArea.setFraudScore(BigDecimal.ONE);
            commArea.setFraudFlag(true);
            commArea.setReturnCode("10");
            commArea.setMessage("Account inactive - auto-flagged");
            log.info("Account {} is {} — auto-flagged score=1.0", commArea.getAcctNo(), account.getStatus());
            return;
        }

        // --- Signal 1: Amount scoring ----------------------------------------
        BigDecimal amountScore = scoreByAmount(commArea.getTxnAmount());

        // --- Signal 2: Merchant risk scoring ---------------------------------
        BigDecimal merchantScore = scoreByMerchant(commArea.getMerchantCode());

        // --- Signal 3: Velocity -----------------------------------
        velocityService.checkVelocity(commArea, velocityLimit);

        // --- Signal 4: Customer profile deviation -----------------
        // chip+PIN: profile weight is already zeroed in initialiseWeights().
        // The service runs but its score will contribute 0 to the composite.
        profileService.scoreProfile(commArea);

        // --- Signal 5: Watchlist / sanctions ----------------------
        watchlistService.screenWatchlist(commArea);

        // Invariant: OFAC or PEP hit → immediate mandatory escalation
        if (commArea.isOfacHit() || commArea.isPepHit()) {
            commArea.setFraudScore(BigDecimal.ONE);
            commArea.setFraudFlag(true);
            commArea.setReturnCode("10");
            commArea.setMessage(commArea.getWatchlistReason());
            return;
        }

        // --- Composite score -------------------------------------------------
        BigDecimal composite =
            amountScore.multiply(commArea.getWeightAmount())
            .add(merchantScore.multiply(commArea.getWeightMerchant()))
            .add(commArea.getVelocityScore().multiply(commArea.getWeightVelocity()))
            .add(commArea.getProfileScore().multiply(commArea.getWeightProfile()))
            .add(commArea.getWatchlistScore().multiply(commArea.getWeightWatchlist()))
            .setScale(4, RoundingMode.HALF_UP);

        if (composite.compareTo(BigDecimal.ONE) > 0) {
            composite = BigDecimal.ONE;
        }

        commArea.setFraudScore(composite);

        if (composite.compareTo(props.getScoreThreshold()) >= 0) {
            commArea.setFraudFlag(true);
            commArea.setReturnCode("10");
            commArea.setMessage("Transaction flagged as high risk");
        } else {
            commArea.setFraudFlag(false);
            commArea.setReturnCode("00");
            commArea.setMessage("Transaction cleared");
        }
    }

    /**
     * Scores transaction by amount band.
     * Thresholds from application properties.
     */
    private BigDecimal scoreByAmount(BigDecimal amount) {
        if (amount.compareTo(props.getHighAmountLimit()) >= 0) return new BigDecimal("0.8000");
        if (amount.compareTo(props.getMedAmountLimit())  >= 0) return new BigDecimal("0.5000");
        if (amount.compareTo(props.getLowAmountLimit())  >= 0) return new BigDecimal("0.3000");
        return new BigDecimal("0.1000");
    }

    /**
     * Scores transaction by merchant risk band.
     * Reads MERCHANT_RISK table; unknown merchant → 0.0 (no signal).
     */
    private BigDecimal scoreByMerchant(String merchantCode) {
        if (merchantCode == null || merchantCode.trim().isEmpty()) return BigDecimal.ZERO;

        Optional<MerchantRisk> merchantOpt = merchantRepo.findById(merchantCode.trim());
        if (!merchantOpt.isPresent()) return BigDecimal.ZERO;

        MerchantRisk merchant = merchantOpt.get();
        if (merchant.isBlocked())                                  return BigDecimal.ONE;
        if (RiskBand.HIGH == RiskBand.fromString(merchant.getRiskBand())) return new BigDecimal("0.8000");
        if (RiskBand.MED  == RiskBand.fromString(merchant.getRiskBand())) return new BigDecimal("0.4000");
        return new BigDecimal("0.1000");
    }

    /**
     * Initialises per-call scoring weights from config defaults.
     * For chip+PIN (BAU-2021-09): profile weight is zeroed and redistributed
     * across the remaining signals so weights still sum to 1.0.
     */
    private void initialiseWeights(FraudCommArea commArea) {
        if (commArea.getChannel() != null && commArea.getChannel().isChipPin()) {
            // BAU-2021-09: chip+PIN skips profile signal to meet 180ms SLA.
            // Profile weight (0.20) redistributed equally to the four remaining signals.
            commArea.setWeightAmount(new BigDecimal("0.2500"));
            commArea.setWeightMerchant(new BigDecimal("0.2500"));
            commArea.setWeightVelocity(new BigDecimal("0.2500"));
            commArea.setWeightProfile(BigDecimal.ZERO);
            commArea.setWeightWatchlist(new BigDecimal("0.2500"));
        } else {
            commArea.setWeightAmount(props.getWeightAmount());
            commArea.setWeightMerchant(props.getWeightMerchant());
            commArea.setWeightVelocity(props.getWeightVelocity());
            commArea.setWeightProfile(props.getWeightProfile());
            commArea.setWeightWatchlist(props.getWeightWatchlist());
        }
    }
}
