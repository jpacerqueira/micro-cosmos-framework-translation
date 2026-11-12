package com.bankxyz.fraud.steps;

import com.bankxyz.fraud.service.FraudCommArea;
import com.bankxyz.fraud.service.VelocityCheckService;
import com.bankxyz.fraud.support.Fixtures;
import com.bankxyz.fraud.support.TestContext;
import io.cucumber.java.en.Given;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;

import java.math.BigDecimal;
import java.time.LocalDateTime;

import static org.assertj.core.api.Assertions.assertThat;

/** Step definitions for velocity_check.feature — exercises VelocityCheckService directly. */
public class VelocityCheckSteps {

    private final Fixtures fixtures;
    private final VelocityCheckService velocityService;
    private final TestContext testContext;

    public VelocityCheckSteps(Fixtures fixtures, VelocityCheckService velocityService, TestContext testContext) {
        this.fixtures = fixtures;
        this.velocityService = velocityService;
        this.testContext = testContext;
    }

    @Given("account {string} has no prior transactions")
    public void accountHasNoPriorTransactions(String acctNo) {
        // Hooks already truncate all tables before every scenario — nothing to seed.
    }

    @Given("account {string} made {int} transactions of {bigdecimal} in the last 24 hours with status {string}")
    public void madeTransactionsInLast24Hours(String acctNo, int count, BigDecimal amount, String status) {
        seedTransactions(acctNo, count, amount, status, LocalDateTime.now().minusHours(1));
    }

    @Given("account {string} made {int} transactions of {bigdecimal} 30 hours ago with status {string}")
    public void madeTransactions30HoursAgo(String acctNo, int count, BigDecimal amount, String status) {
        seedTransactions(acctNo, count, amount, status, LocalDateTime.now().minusHours(30));
    }

    private void seedTransactions(String acctNo, int count, BigDecimal amount, String status, LocalDateTime txnTs) {
        for (int i = 0; i < count; i++) {
            fixtures.transaction("VEL" + i + "-" + acctNo, acctNo, amount, "ONLINE", status, txnTs);
        }
    }

    @When("velocity is checked for account {string} with limit {int}")
    public void velocityIsChecked(String acctNo, int limit) {
        FraudCommArea commArea = new FraudCommArea();
        commArea.setAcctNo(acctNo);
        velocityService.checkVelocity(commArea, limit);
        testContext.setCommArea(commArea);
    }

    @Then("the velocity count is {long}")
    public void theVelocityCountIs(long expected) {
        assertThat(testContext.getCommArea().getTxnCount()).isEqualTo(expected);
    }

    @Then("the velocity sum is {bigdecimal}")
    public void theVelocitySumIs(BigDecimal expected) {
        assertThat(testContext.getCommArea().getTxnSum()).isEqualByComparingTo(expected);
    }

    @Then("the velocity score is {bigdecimal}")
    public void theVelocityScoreIs(BigDecimal expected) {
        assertThat(testContext.getCommArea().getVelocityScore()).isEqualByComparingTo(expected);
    }
}
