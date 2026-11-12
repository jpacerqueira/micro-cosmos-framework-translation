package com.bankxyz.fraud.service;

import com.bankxyz.fraud.entity.CustomerProfile;
import com.bankxyz.fraud.repository.CustomerProfileRepository;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalTime;
import java.util.Optional;

/**
 * Customer profile deviation scorer.
 *
 * Scores how much a transaction deviates from the customer's established behaviour.
 * Three deviation checks:
 *   1. Amount deviation — above customer's max historical amount?
 *   2. Geolocation — transaction country differs from usual country?
 *   3. Time-of-day — transaction outside customer's usual active hours?
 *
 * Business invariants:
 *   - No profile found → score defaults to 0.3000
 *   - Card-not-present (CNP) → 0.10 uplift on returned score
 *   - Score capped at 1.0
 *
 * Note on chip+PIN (BAU-2021-09):
 *   The profile weight is zeroed for chip+PIN transactions to skip this check
 *   and meet the 180ms SLA. This is implemented by passing weightProfile=0 in
 *   the commArea weights, which causes FraudRulesService to exclude this signal
 *   from the composite score. This service is still invoked, but its result
 *   contributes nothing to the score.
 */
@Service
public class CustomerProfileService {

    private static final BigDecimal DEFAULT_NO_PROFILE = new BigDecimal("0.3000");
    private static final BigDecimal AMT_HIGH_DEVIATION_THRESHOLD = new BigDecimal("3.0000");
    private static final BigDecimal AMT_HIGH_SCORE   = new BigDecimal("0.4000");
    private static final BigDecimal AMT_LOW_SCORE    = new BigDecimal("0.2000");
    private static final BigDecimal GEO_SCORE        = new BigDecimal("0.3000");
    private static final BigDecimal TOD_SCORE        = new BigDecimal("0.2000");
    private static final BigDecimal CNP_UPLIFT       = new BigDecimal("0.1000");

    private final CustomerProfileRepository profileRepo;

    public CustomerProfileService(CustomerProfileRepository profileRepo) {
        this.profileRepo = profileRepo;
    }

    /**
     * Score customer profile deviation and populate commArea.profileScore.
     */
    public void scoreProfile(FraudCommArea commArea) {
        Optional<CustomerProfile> profileOpt = profileRepo.findById(commArea.getAcctNo());

        if (!profileOpt.isPresent()) {
            commArea.setProfileScore(DEFAULT_NO_PROFILE);
            return;
        }

        CustomerProfile profile = profileOpt.get();
        BigDecimal score = BigDecimal.ZERO;

        // Check 1: Amount deviation
        BigDecimal txnAmt = commArea.getTxnAmount();
        if (txnAmt.compareTo(profile.getMaxTxnAmount()) > 0
                && profile.getAvgTxnAmount().compareTo(BigDecimal.ZERO) > 0) {
            BigDecimal deviation = txnAmt.subtract(profile.getAvgTxnAmount())
                    .divide(profile.getAvgTxnAmount(), 4, RoundingMode.HALF_UP);
            if (deviation.compareTo(AMT_HIGH_DEVIATION_THRESHOLD) > 0) {
                score = score.add(AMT_HIGH_SCORE);
            } else {
                score = score.add(AMT_LOW_SCORE);
            }
        }

        // Check 2: Geolocation deviation
        String usualCountry = profile.getUsualCountry() == null ? "GBR" : profile.getUsualCountry().trim();
        String txnCountry = commArea.getTxnCountry() == null ? "GBR" : commArea.getTxnCountry().trim();
        if (!txnCountry.equals(usualCountry)) {
            commArea.setCrossBorder(true);
            score = score.add(GEO_SCORE);
        }

        // Check 3: Time-of-day deviation
        int currentHour = LocalTime.now().getHour();
        if (currentHour < profile.getUsualHrStart() || currentHour > profile.getUsualHrEnd()) {
            score = score.add(TOD_SCORE);
        }

        // Card-not-present uplift
        if (commArea.isCnpFlag()) {
            score = score.add(CNP_UPLIFT);
        }

        // Cap at 1.0
        if (score.compareTo(BigDecimal.ONE) > 0) {
            score = BigDecimal.ONE;
        }

        commArea.setProfileScore(score);
    }
}
