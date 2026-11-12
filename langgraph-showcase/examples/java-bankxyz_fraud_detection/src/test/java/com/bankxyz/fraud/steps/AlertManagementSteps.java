package com.bankxyz.fraud.steps;

import com.bankxyz.fraud.entity.FraudAlert;
import com.bankxyz.fraud.repository.FraudAlertRepository;
import com.bankxyz.fraud.repository.MqFailureLogRepository;
import com.bankxyz.fraud.service.AlertWriterService;
import com.bankxyz.fraud.service.FraudCommArea;
import com.bankxyz.fraud.support.MqFailureSwitch;
import com.bankxyz.fraud.support.TestContext;
import io.cucumber.java.en.Given;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;

import java.math.BigDecimal;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Step definitions for alert_management.feature — exercises AlertWriterService
 * and, through it, MqNotificationService (both the happy path and the
 * non-fatal MQ failure path via the embedded broker + FailureInjectingJmsTemplate).
 */
public class AlertManagementSteps {

    private final AlertWriterService alertWriterService;
    private final FraudAlertRepository alertRepo;
    private final MqFailureLogRepository mqFailureRepo;
    private final TestContext testContext;

    public AlertManagementSteps(AlertWriterService alertWriterService,
                                 FraudAlertRepository alertRepo,
                                 MqFailureLogRepository mqFailureRepo,
                                 TestContext testContext) {
        this.alertWriterService = alertWriterService;
        this.alertRepo = alertRepo;
        this.mqFailureRepo = mqFailureRepo;
        this.testContext = testContext;
    }

    @Given("the MQ broker is unavailable")
    public void theMqBrokerIsUnavailable() {
        MqFailureSwitch.simulateFailure();
    }

    @When("a fraud alert is written for transaction {string} account {string} amount {bigdecimal} score {bigdecimal}")
    public void aFraudAlertIsWritten(String txnId, String acctNo, BigDecimal amount, BigDecimal score) {
        FraudCommArea commArea = new FraudCommArea();
        commArea.setTxnId(txnId);
        commArea.setAcctNo(acctNo);
        commArea.setTxnAmount(amount);
        commArea.setFraudScore(score);
        alertWriterService.writeAlert(commArea);
        testContext.setCommArea(commArea);
    }

    @Then("the alert is persisted with amount {bigdecimal} and score {bigdecimal}")
    public void theAlertIsPersisted(BigDecimal amount, BigDecimal score) {
        assertThat(testContext.getCommArea().getAlertId()).isNotNull();
        FraudAlert alert = alertRepo.findById(testContext.getCommArea().getAlertId())
                .orElseThrow(() -> new IllegalStateException("Alert was not persisted"));
        assertThat(alert.getTxnAmount()).isEqualByComparingTo(amount);
        assertThat(alert.getFraudScore()).isEqualByComparingTo(score);
    }

    // "the return code is {string}" and "the message is {string}" are defined
    // once in FraudScoringSteps and reused here — TestContext is shared per scenario.

    @Then("no MQ failure has been logged")
    public void noMqFailureHasBeenLogged() {
        assertThat(mqFailureRepo.count()).isZero();
    }

    @Then("an MQ failure has been logged for transaction {string} account {string}")
    public void anMqFailureHasBeenLogged(String txnId, String acctNo) {
        assertThat(mqFailureRepo.findAll())
                .as("MQ_FAILURE_LOG rows")
                .hasSize(1)
                .first()
                .satisfies(failure -> {
                    assertThat(failure.getTxnId()).isEqualTo(txnId);
                    assertThat(failure.getAcctNo()).isEqualTo(acctNo);
                });
    }
}
