package com.bankxyz.fraud.steps;

import com.bankxyz.fraud.config.FraudScoringProperties;
import com.bankxyz.fraud.repository.FraudAlertRepository;
import com.bankxyz.fraud.repository.SlaBreachLogRepository;
import com.bankxyz.fraud.support.TestContext;
import com.bankxyz.fraud.support.TestIds;
import com.bankxyz.fraud.web.dto.FraudCheckRequest;
import io.cucumber.java.en.Given;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import org.springframework.boot.test.web.client.TestRestTemplate;
import org.springframework.boot.web.server.LocalServerPort;
import org.springframework.http.ResponseEntity;

import java.math.BigDecimal;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Step definitions for realtime_authorisation.feature — drives the real
 * RealtimeCheckController REST endpoints over HTTP (@SpringBootTest RANDOM_PORT).
 * Deserialises the response as a raw Map rather than FraudCheckResponse:
 * that DTO only has an all-args constructor (no default ctor/setters, no
 * @JsonCreator), which Jackson cannot use to deserialise on the client side
 * without changing production code.
 */
public class RealtimeAuthorisationSteps {

    @LocalServerPort
    private int port;

    private final TestRestTemplate restTemplate;
    private final FraudAlertRepository alertRepo;
    private final SlaBreachLogRepository slaBreachRepo;
    private final FraudScoringProperties props;
    private final TestContext testContext;

    public RealtimeAuthorisationSteps(TestRestTemplate restTemplate,
                                       FraudAlertRepository alertRepo,
                                       SlaBreachLogRepository slaBreachRepo,
                                       FraudScoringProperties props,
                                       TestContext testContext) {
        this.restTemplate = restTemplate;
        this.alertRepo = alertRepo;
        this.slaBreachRepo = slaBreachRepo;
        this.props = props;
        this.testContext = testContext;
    }

    @Given("the real-time SLA limit is breached")
    public void theRealTimeSlaLimitIsBreached() {
        // Guarantees elapsedMs > slaLimitMs regardless of how fast the call actually runs.
        props.setSlaLimitMs(-1);
    }

    @When("{string} authorises a transaction of amount {bigdecimal} on channel {string}")
    public void authorises(String acctNo, BigDecimal amount, String channel) {
        authorises(acctNo, amount, null, channel);
    }

    @When("{string} authorises a transaction of amount {bigdecimal} on merchant {string} channel {string}")
    public void authorises(String acctNo, BigDecimal amount, String merchantCode, String channel) {
        FraudCheckRequest request = new FraudCheckRequest();
        request.setTxnId(TestIds.nextTxnId());
        request.setAcctNo(acctNo);
        request.setTxnAmount(amount);
        request.setMerchantCode(merchantCode);
        request.setChannel(channel);
        request.setTxnCountry("GBR");

        ResponseEntity<Map> response = restTemplate.postForEntity(
                "http://localhost:" + port + "/api/v1/authorise", request, Map.class);
        testContext.setAuthoriseResponse(response);
    }

    @When("the batch job is triggered manually")
    public void theBatchJobIsTriggeredManually() {
        ResponseEntity<String> response = restTemplate.postForEntity(
                "http://localhost:" + port + "/api/v1/batch/run", null, String.class);
        testContext.setBatchTriggerResponse(response);
    }

    @Then("the authorisation decision is {string} with return code {string}")
    public void theAuthorisationDecisionIs(String decision, String returnCode) {
        Map body = testContext.getAuthoriseResponse().getBody();
        assertThat(body).containsEntry("decision", decision).containsEntry("returnCode", returnCode);
    }

    @Then("the authorisation message is {string}")
    public void theAuthorisationMessageIs(String expected) {
        assertThat(testContext.getAuthoriseResponse().getBody())
                .containsEntry("message", expected);
    }

    @Then("a fraud alert exists for the authorised transaction")
    public void aFraudAlertExistsForTheAuthorisedTransaction() {
        String txnId = (String) testContext.getAuthoriseResponse().getBody().get("txnId");
        assertThat(alertRepo.findAll())
                .as("FRAUD_ALERTS rows")
                .anySatisfy(alert -> assertThat(alert.getTxnId()).isEqualTo(txnId));
    }

    @Then("an SLA breach has been logged")
    public void anSlaBreachHasBeenLogged() {
        assertThat(slaBreachRepo.count()).isEqualTo(1);
    }

    @Then("the batch trigger response is {string}")
    public void theBatchTriggerResponseIs(String expected) {
        assertThat(testContext.getBatchTriggerResponse().getBody()).isEqualTo(expected);
    }
}
