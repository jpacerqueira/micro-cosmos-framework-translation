package com.bankxyz.fraud.steps;

import com.bankxyz.fraud.entity.CustomerProfile;
import com.bankxyz.fraud.repository.CustomerProfileRepository;
import com.bankxyz.fraud.service.CustomerProfileService;
import com.bankxyz.fraud.service.FraudCommArea;
import com.bankxyz.fraud.support.Fixtures;
import com.bankxyz.fraud.support.TestContext;
import io.cucumber.java.en.Given;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;

import java.math.BigDecimal;
import java.time.LocalTime;

import static org.assertj.core.api.Assertions.assertThat;

/** Step definitions for customer_profile.feature — exercises CustomerProfileService directly. */
public class CustomerProfileSteps {

    private final Fixtures fixtures;
    private final CustomerProfileRepository profileRepo;
    private final CustomerProfileService profileService;
    private final TestContext testContext;

    public CustomerProfileSteps(Fixtures fixtures,
                                 CustomerProfileRepository profileRepo,
                                 CustomerProfileService profileService,
                                 TestContext testContext) {
        this.fixtures = fixtures;
        this.profileRepo = profileRepo;
        this.profileService = profileService;
        this.testContext = testContext;
    }

    @Given("account {string} has no customer profile")
    public void accountHasNoCustomerProfile(String acctNo) {
        // Hooks already truncate all tables before every scenario — nothing to seed.
    }

    @Given("account {string} has a profile with average amount {bigdecimal}, max amount {bigdecimal}, "
            + "usual country {string}, active hours {int} to {int}")
    public void profileWithExplicitHours(String acctNo, BigDecimal avg, BigDecimal max, String country,
                                          int hrStart, int hrEnd) {
        fixtures.profile(acctNo, avg, max, country, hrStart, hrEnd);
    }

    @Given("account {string} has a profile with average amount {bigdecimal}, max amount {bigdecimal}, "
            + "usual country {string}")
    public void profileWithDefaultHours(String acctNo, BigDecimal avg, BigDecimal max, String country) {
        fixtures.profile(acctNo, avg, max, country, 0, 23);
    }

    @Given("the usual active hours for account {string} exclude the current hour")
    public void usualActiveHoursExcludeCurrentHour(String acctNo) {
        int currentHour = LocalTime.now().getHour();
        int hrStart;
        int hrEnd;
        if (currentHour <= 20) {
            hrStart = currentHour + 2;
            hrEnd = currentHour + 3;
        } else {
            hrStart = 0;
            hrEnd = currentHour - 2;
        }
        CustomerProfile profile = profileRepo.findById(acctNo)
                .orElseThrow(() -> new IllegalStateException("Fixture profile not found: " + acctNo));
        profile.setUsualHrStart(hrStart);
        profile.setUsualHrEnd(hrEnd);
        profileRepo.save(profile);
    }

    @When("a transaction of amount {bigdecimal} in country {string} is profiled for account {string}")
    public void profileTransaction(BigDecimal amount, String country, String acctNo) {
        profileTransaction(amount, country, acctNo, false);
    }

    @When("a card-not-present transaction of amount {bigdecimal} in country {string} is profiled for account {string}")
    public void profileCnpTransaction(BigDecimal amount, String country, String acctNo) {
        profileTransaction(amount, country, acctNo, true);
    }

    private void profileTransaction(BigDecimal amount, String country, String acctNo, boolean cnpFlag) {
        FraudCommArea commArea = new FraudCommArea();
        commArea.setAcctNo(acctNo);
        commArea.setTxnAmount(amount);
        commArea.setTxnCountry(country);
        commArea.setCnpFlag(cnpFlag);
        profileService.scoreProfile(commArea);
        testContext.setCommArea(commArea);
    }

    @Then("the profile score is {bigdecimal}")
    public void theProfileScoreIs(BigDecimal expected) {
        assertThat(testContext.getCommArea().getProfileScore()).isEqualByComparingTo(expected);
    }

    @Then("the transaction is marked cross-border")
    public void theTransactionIsMarkedCrossBorder() {
        assertThat(testContext.getCommArea().isCrossBorder()).isTrue();
    }
}
