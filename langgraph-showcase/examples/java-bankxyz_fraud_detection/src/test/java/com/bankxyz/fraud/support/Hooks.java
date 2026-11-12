package com.bankxyz.fraud.support;

import com.bankxyz.fraud.config.FraudScoringProperties;
import com.bankxyz.fraud.repository.AccountRepository;
import com.bankxyz.fraud.repository.CustomerProfileRepository;
import com.bankxyz.fraud.repository.FraudAlertRepository;
import com.bankxyz.fraud.repository.MerchantRiskRepository;
import com.bankxyz.fraud.repository.MqFailureLogRepository;
import com.bankxyz.fraud.repository.SlaBreachLogRepository;
import com.bankxyz.fraud.repository.TransactionRepository;
import com.bankxyz.fraud.repository.WatchlistHitRepository;
import com.bankxyz.fraud.repository.WatchlistRepository;
import io.cucumber.java.Before;

/**
 * Resets database state and test toggles before every scenario so scenarios
 * remain independent despite sharing one H2 instance and one Spring context
 * for the whole suite.
 */
public class Hooks {

    private final AccountRepository accountRepo;
    private final MerchantRiskRepository merchantRepo;
    private final CustomerProfileRepository profileRepo;
    private final WatchlistRepository watchlistRepo;
    private final WatchlistHitRepository watchlistHitRepo;
    private final TransactionRepository txnRepo;
    private final FraudAlertRepository alertRepo;
    private final MqFailureLogRepository mqFailureRepo;
    private final SlaBreachLogRepository slaBreachRepo;
    private final FraudScoringProperties props;
    private final TestContext testContext;

    public Hooks(AccountRepository accountRepo,
                 MerchantRiskRepository merchantRepo,
                 CustomerProfileRepository profileRepo,
                 WatchlistRepository watchlistRepo,
                 WatchlistHitRepository watchlistHitRepo,
                 TransactionRepository txnRepo,
                 FraudAlertRepository alertRepo,
                 MqFailureLogRepository mqFailureRepo,
                 SlaBreachLogRepository slaBreachRepo,
                 FraudScoringProperties props,
                 TestContext testContext) {
        this.accountRepo = accountRepo;
        this.merchantRepo = merchantRepo;
        this.profileRepo = profileRepo;
        this.watchlistRepo = watchlistRepo;
        this.watchlistHitRepo = watchlistHitRepo;
        this.txnRepo = txnRepo;
        this.alertRepo = alertRepo;
        this.mqFailureRepo = mqFailureRepo;
        this.slaBreachRepo = slaBreachRepo;
        this.props = props;
        this.testContext = testContext;
    }

    @Before
    public void resetState() {
        watchlistHitRepo.deleteAll();
        alertRepo.deleteAll();
        mqFailureRepo.deleteAll();
        slaBreachRepo.deleteAll();
        txnRepo.deleteAll();
        watchlistRepo.deleteAll();
        profileRepo.deleteAll();
        merchantRepo.deleteAll();
        accountRepo.deleteAll();

        MqFailureSwitch.reset();
        testContext.reset();
        props.setSlaLimitMs(5000);
    }
}
