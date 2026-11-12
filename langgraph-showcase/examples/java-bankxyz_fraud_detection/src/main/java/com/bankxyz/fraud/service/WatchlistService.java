package com.bankxyz.fraud.service;

import com.bankxyz.fraud.entity.Account;
import com.bankxyz.fraud.entity.WatchlistHit;
import com.bankxyz.fraud.repository.AccountRepository;
import com.bankxyz.fraud.repository.WatchlistHitRepository;
import com.bankxyz.fraud.repository.WatchlistRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.util.Optional;

/**
 * Watchlist and sanctions screener.
 *
 * Screens the account holder against three lists:
 *   1. OFAC sanctions list (US Treasury) — mandatory escalation
 *   2. PEP list (Politically Exposed Persons) — mandatory escalation
 *   3. Internal BankXYZ fraud watchlist — score = 0.9000
 *
 * Business invariants:
 *   - Any OFAC or PEP hit must auto-escalate (score forced to 1.0 in FraudRulesService)
 *   - A hit must be logged to WATCHLIST_HITS before return
 *   - Screening covers both account holder name and account number
 */
@Service
public class WatchlistService {

    private static final Logger log = LoggerFactory.getLogger(WatchlistService.class);

    private static final BigDecimal SCORE_OFAC_PEP  = BigDecimal.ONE;
    private static final BigDecimal SCORE_INTERNAL  = new BigDecimal("0.9000");

    private final WatchlistRepository watchlistRepo;
    private final WatchlistHitRepository hitRepo;
    private final AccountRepository accountRepo;

    public WatchlistService(WatchlistRepository watchlistRepo,
                            WatchlistHitRepository hitRepo,
                            AccountRepository accountRepo) {
        this.watchlistRepo = watchlistRepo;
        this.hitRepo = hitRepo;
        this.accountRepo = accountRepo;
    }

    /**
     * Screen account against all watchlists and populate watchlist fields on commArea.
     */
    public void screenWatchlist(FraudCommArea commArea) {
        commArea.setOfacHit(false);
        commArea.setPepHit(false);
        commArea.setInternalHit(false);
        commArea.setWatchlistScore(BigDecimal.ZERO);
        commArea.setWatchlistReason("");

        Optional<Account> accountOpt = accountRepo.findById(commArea.getAcctNo());
        if (!accountOpt.isPresent()) {
            return;
        }
        String custFullName = accountOpt.get().getCustFullName();
        String nameLike = "%" + custFullName.trim() + "%";

        // Screen 1: OFAC
        if (watchlistRepo.countOfacHits(nameLike) > 0) {
            commArea.setOfacHit(true);
            commArea.setWatchlistScore(SCORE_OFAC_PEP);
            commArea.setWatchlistReason("OFAC sanctions hit - mandatory escalation");
            logHit(commArea, "OFAC", commArea.getWatchlistReason());
            return;
        }

        // Screen 2: PEP
        if (watchlistRepo.countPepHits(nameLike) > 0) {
            commArea.setPepHit(true);
            commArea.setWatchlistScore(SCORE_OFAC_PEP);
            commArea.setWatchlistReason("PEP list hit - mandatory escalation");
            logHit(commArea, "PEP", commArea.getWatchlistReason());
            return;
        }

        // Screen 3: Internal
        if (watchlistRepo.countInternalHits(commArea.getAcctNo(), nameLike) > 0) {
            commArea.setInternalHit(true);
            commArea.setWatchlistScore(SCORE_INTERNAL);
            commArea.setWatchlistReason("Internal watchlist hit");
            logHit(commArea, "INTERNAL", commArea.getWatchlistReason());
        }
    }

    private void logHit(FraudCommArea commArea, String hitType, String reason) {
        try {
            WatchlistHit hit = new WatchlistHit();
            hit.setAcctNo(commArea.getAcctNo());
            hit.setTxnId(commArea.getTxnId());
            hit.setHitType(hitType);
            hit.setHitReason(reason);
            hitRepo.save(hit);
        } catch (Exception e) {
            log.error("Failed to log watchlist hit for txn={} acct={}: {}",
                    commArea.getTxnId(), commArea.getAcctNo(), e.getMessage());
        }
    }
}
