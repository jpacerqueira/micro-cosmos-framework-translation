package com.bankxyz.fraud.steps;

import com.bankxyz.fraud.domain.Channel;
import com.bankxyz.fraud.repository.AccountRepository;
import com.bankxyz.fraud.service.FraudCommArea;
import com.bankxyz.fraud.service.FraudRulesService;
import com.bankxyz.fraud.support.Fixtures;
import com.bankxyz.fraud.support.TestContext;
import com.bankxyz.fraud.support.TestIds;
import io.cucumber.java.en.Given;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;

import java.math.BigDecimal;
import java.time.LocalDateTime;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Step definitions for fraud_scoring.feature — exercises
 * FraudRulesService.score() end to end, including every mandatory-escalation
 * invariant and the CHIPPIN weight-redistribution rule (BAU-2021-09).
 */
public class FraudScoringSteps {

    /** Real-time velocity limit used by every scenario in this feature (see FraudScoringProperties). */
    private static final int VELOCITY_LIMIT_REALTIME = 5;

    private final Fixtures fixtures;
    private final AccountRepository accountRepo;
    private final FraudRulesService rulesService;
    private final TestContext testContext;

    public FraudScoringSteps(Fixtures fixtures,
                              AccountRepository accountRepo,
                              FraudRulesService rulesService,
                              TestContext testContext) {
        this.fixtures = fixtures;
        this.accountRepo = accountRepo;
        this.rulesService = rulesService;
        this.testContext = testContext;
    }

    @Given("an active account {string} for customer {string} in country {string}")
    public void anActiveAccount(String acctNo, String custName, String country) {
        fixtures.account(acctNo, custName, country, "A");
    }

    @Given("account {string} has status {string}")
    public void accountHasStatus(String acctNo, String statusName) {
        String code;
        switch (statusName) {
            case "FROZEN": code = "F"; break;
            case "CLOSED": code = "C"; break;
            default: code = "A";
        }
        com.bankxyz.fraud.entity.Account account = accountRepo.findById(acctNo)
                .orElseThrow(() -> new IllegalStateException("Fixture account not found: " + acctNo));
        account.setAcctStatus(code);
        accountRepo.save(account);
    }

    @Given("a watchlist {string} entry matching name {string}")
    public void watchlistEntryMatchingName(String listType, String matchName) {
        fixtures.watchlistEntry(listType, matchName, null);
    }

    @Given("a watchlist {string} entry matching account {string}")
    public void watchlistEntryMatchingAccount(String listType, String matchAcct) {
        fixtures.watchlistEntry(listType, null, matchAcct);
    }

    @Given("a blocked merchant {string}")
    public void blockedMerchant(String code) {
        fixtures.merchant(code, "HIGH", true);
    }

    @Given("account {string} made {int} prior transactions of {bigdecimal} in the last 24 hours")
    public void priorTransactions(String acctNo, int count, BigDecimal amount) {
        for (int i = 0; i < count; i++) {
            fixtures.transaction("VEL" + i + acctNo, acctNo, amount, "ONLINE", "S",
                    LocalDateTime.now().minusHours(1));
        }
    }

    @Given("a customer profile for {string} with average amount {bigdecimal}, max amount {bigdecimal}, "
            + "country {string}, active hours {int} to {int}")
    public void customerProfile(String acctNo, BigDecimal avg, BigDecimal max, String country,
                                 int hrStart, int hrEnd) {
        fixtures.profile(acctNo, avg, max, country, hrStart, hrEnd);
    }

    @When("account {string} is scored for a transaction of amount {bigdecimal} on channel {string}")
    public void scoreTransaction(String acctNo, BigDecimal amount, String channel) {
        scoreTransaction(acctNo, amount, null, channel);
    }

    @When("account {string} is scored for a transaction of amount {bigdecimal} on merchant {string} channel {string}")
    public void scoreTransaction(String acctNo, BigDecimal amount, String merchantCode, String channel) {
        FraudCommArea commArea = new FraudCommArea();
        commArea.setTxnId(TestIds.nextTxnId());
        commArea.setAcctNo(acctNo);
        commArea.setTxnAmount(amount);
        commArea.setMerchantCode(merchantCode);
        commArea.setChannel(Channel.fromString(channel));
        rulesService.score(commArea, VELOCITY_LIMIT_REALTIME);
        testContext.setCommArea(commArea);
    }

    @Then("the fraud score is {bigdecimal}")
    public void theFraudScoreIs(BigDecimal expected) {
        assertThat(testContext.getCommArea().getFraudScore()).isEqualByComparingTo(expected);
    }

    @Then("the transaction is flagged as fraud")
    public void theTransactionIsFlagged() {
        assertThat(testContext.getCommArea().isFraudFlag()).isTrue();
    }

    @Then("the transaction is not flagged as fraud")
    public void theTransactionIsNotFlagged() {
        assertThat(testContext.getCommArea().isFraudFlag()).isFalse();
    }

    @Then("the return code is {string}")
    public void theReturnCodeIs(String expected) {
        assertThat(testContext.getCommArea().getReturnCode()).isEqualTo(expected);
    }

    @Then("the message is {string}")
    public void theMessageIs(String expected) {
        assertThat(testContext.getCommArea().getMessage()).isEqualTo(expected);
    }
}
