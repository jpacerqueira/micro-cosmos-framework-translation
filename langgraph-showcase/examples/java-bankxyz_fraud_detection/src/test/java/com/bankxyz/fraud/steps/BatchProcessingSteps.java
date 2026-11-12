package com.bankxyz.fraud.steps;

import com.bankxyz.fraud.repository.FraudAlertRepository;
import com.bankxyz.fraud.repository.TransactionRepository;
import com.bankxyz.fraud.service.TransactionMonitorService;
import com.bankxyz.fraud.support.Fixtures;
import com.bankxyz.fraud.support.TestContext;
import io.cucumber.java.en.Given;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;

import java.math.BigDecimal;
import java.time.LocalDateTime;

import static org.assertj.core.api.Assertions.assertThat;

/** Step definitions for batch_processing.feature — exercises TransactionMonitorService directly. */
public class BatchProcessingSteps {

    private final Fixtures fixtures;
    private final TransactionRepository txnRepo;
    private final FraudAlertRepository alertRepo;
    private final TransactionMonitorService monitorService;
    private final TestContext testContext;

    /** Increasing offset so pending transactions are created in a deterministic txnTs order. */
    private int seq = 0;

    public BatchProcessingSteps(Fixtures fixtures,
                                 TransactionRepository txnRepo,
                                 FraudAlertRepository alertRepo,
                                 TransactionMonitorService monitorService,
                                 TestContext testContext) {
        this.fixtures = fixtures;
        this.txnRepo = txnRepo;
        this.alertRepo = alertRepo;
        this.monitorService = monitorService;
        this.testContext = testContext;
    }

    @Given("a pending transaction {string} for account {string} of amount {bigdecimal}")
    public void pendingTransaction(String txnId, String acctNo, BigDecimal amount) {
        LocalDateTime txnTs = LocalDateTime.now().plusNanos(1_000_000L * seq++);
        fixtures.transaction(txnId, acctNo, amount, "ONLINE", "P", txnTs);
    }

    @When("the batch job runs with a maximum of {int} transactions")
    public void theBatchJobRuns(int maxTransactions) {
        testContext.setBatchSummary(monitorService.processBatch(maxTransactions));
    }

    @Then("the batch summary is {string}")
    public void theBatchSummaryIs(String expected) {
        assertThat(testContext.getBatchSummary()).isEqualTo(expected);
    }

    @Then("transaction {string} has status {string}")
    public void transactionHasStatus(String txnId, String expectedStatus) {
        assertThat(txnRepo.findById(txnId))
                .as("transaction " + txnId)
                .isPresent()
                .get()
                .extracting("txnStatus")
                .isEqualTo(expectedStatus);
    }

    @Then("{int} transaction still has status {string}")
    public void transactionCountHasStatus(int expectedCount, String status) {
        assertThat(txnRepo.findAll())
                .filteredOn(t -> t.getTxnStatus().equals(status))
                .hasSize(expectedCount);
    }

    @Then("a fraud alert exists for transaction {string}")
    public void aFraudAlertExistsForTransaction(String txnId) {
        assertThat(alertRepo.findAll())
                .as("FRAUD_ALERTS rows")
                .anySatisfy(alert -> assertThat(alert.getTxnId()).isEqualTo(txnId));
    }

    @Then("no fraud alert exists for transaction {string}")
    public void noFraudAlertExistsForTransaction(String txnId) {
        assertThat(alertRepo.findAll())
                .as("FRAUD_ALERTS rows")
                .noneMatch(a -> a.getTxnId().equals(txnId));
    }
}
