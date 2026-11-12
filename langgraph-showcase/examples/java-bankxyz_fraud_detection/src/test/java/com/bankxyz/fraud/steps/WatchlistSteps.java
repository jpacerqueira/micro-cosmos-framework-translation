package com.bankxyz.fraud.steps;

import com.bankxyz.fraud.repository.WatchlistHitRepository;
import com.bankxyz.fraud.service.FraudCommArea;
import com.bankxyz.fraud.service.WatchlistService;
import com.bankxyz.fraud.support.TestContext;
import com.bankxyz.fraud.support.TestIds;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;

import java.math.BigDecimal;

import static org.assertj.core.api.Assertions.assertThat;

/** Step definitions for watchlist_screening.feature — exercises WatchlistService directly. */
public class WatchlistSteps {

    private final WatchlistService watchlistService;
    private final WatchlistHitRepository watchlistHitRepo;
    private final TestContext testContext;

    public WatchlistSteps(WatchlistService watchlistService,
                           WatchlistHitRepository watchlistHitRepo,
                           TestContext testContext) {
        this.watchlistService = watchlistService;
        this.watchlistHitRepo = watchlistHitRepo;
        this.testContext = testContext;
    }

    @When("account {string} is screened against the watchlist")
    public void accountIsScreened(String acctNo) {
        FraudCommArea commArea = new FraudCommArea();
        commArea.setTxnId(TestIds.nextTxnId());
        commArea.setAcctNo(acctNo);
        watchlistService.screenWatchlist(commArea);
        testContext.setCommArea(commArea);
    }

    @Then("the account has an OFAC hit")
    public void theAccountHasAnOfacHit() {
        assertThat(testContext.getCommArea().isOfacHit()).isTrue();
    }

    @Then("the account has a PEP hit")
    public void theAccountHasAPepHit() {
        assertThat(testContext.getCommArea().isPepHit()).isTrue();
    }

    @Then("the account has an internal watchlist hit")
    public void theAccountHasAnInternalHit() {
        assertThat(testContext.getCommArea().isInternalHit()).isTrue();
    }

    @Then("the account has no watchlist hit")
    public void theAccountHasNoWatchlistHit() {
        FraudCommArea commArea = testContext.getCommArea();
        assertThat(commArea.isOfacHit()).isFalse();
        assertThat(commArea.isPepHit()).isFalse();
        assertThat(commArea.isInternalHit()).isFalse();
    }

    @Then("the watchlist score is {bigdecimal}")
    public void theWatchlistScoreIs(BigDecimal expected) {
        assertThat(testContext.getCommArea().getWatchlistScore()).isEqualByComparingTo(expected);
    }

    @Then("the watchlist reason is {string}")
    public void theWatchlistReasonIs(String expected) {
        assertThat(testContext.getCommArea().getWatchlistReason()).isEqualTo(expected);
    }

    @Then("{int} watchlist hit has been logged with type {string}")
    public void watchlistHitLoggedWithType(int expectedCount, String hitType) {
        assertThat(watchlistHitRepo.count()).isEqualTo(expectedCount);
        assertThat(watchlistHitRepo.findAll()).first()
                .extracting("hitType").isEqualTo(hitType);
    }

    @Then("{int} watchlist hits have been logged")
    public void watchlistHitsLogged(int expectedCount) {
        assertThat(watchlistHitRepo.count()).isEqualTo(expectedCount);
    }
}
