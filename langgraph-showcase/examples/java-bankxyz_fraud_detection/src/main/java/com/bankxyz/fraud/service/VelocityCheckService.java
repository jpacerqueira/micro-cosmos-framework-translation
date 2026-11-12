package com.bankxyz.fraud.service;

import com.bankxyz.fraud.config.FraudScoringProperties;
import com.bankxyz.fraud.repository.TransactionRepository;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDateTime;

/**
 * Velocity checker.
 *
 * Counts how many transactions an account has made in the last 24 hours
 * and converts that count to a normalised score (0.0–1.0).
 *
 * Business invariants:
 *   - Velocity window is fixed at 24 hours
 *   - 10+ transactions (batch) or 5+ (real-time) → score = 1.0
 *   - Score = COUNT / velocityLimit, capped at 1.0
 */
@Service
public class VelocityCheckService {

    private final TransactionRepository txnRepo;
    private final FraudScoringProperties props;

    public VelocityCheckService(TransactionRepository txnRepo, FraudScoringProperties props) {
        this.txnRepo = txnRepo;
        this.props = props;
    }

    /**
     * Checks velocity for both batch and real-time scoring.
     * Populates velocityScore, txnCount, txnSum on the commArea.
     *
     * @param commArea      shared data object
     * @param velocityLimit 10 for batch, 5 for real-time
     */
    public void checkVelocity(FraudCommArea commArea, int velocityLimit) {
        LocalDateTime since = LocalDateTime.now().minusHours(24);
        String acctNo = commArea.getAcctNo();

        long count = txnRepo.countVelocity(acctNo, since);
        BigDecimal sum = txnRepo.sumVelocityAmount(acctNo, since);
        if (sum == null) sum = BigDecimal.ZERO;

        BigDecimal score;
        if (count >= velocityLimit) {
            score = BigDecimal.ONE;
        } else {
            score = BigDecimal.valueOf(count)
                    .divide(BigDecimal.valueOf(velocityLimit), 4, RoundingMode.HALF_UP);
        }

        commArea.setTxnCount(count);
        commArea.setTxnSum(sum);
        commArea.setVelocityScore(score);
    }
}
