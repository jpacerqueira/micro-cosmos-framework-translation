package com.bankxyz.fraud.service;

import com.bankxyz.fraud.entity.CustomerProfile;
import com.bankxyz.fraud.repository.CustomerProfileRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.time.LocalTime;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.when;

/** Unit tests for {@link CustomerProfileService}, with {@link CustomerProfileRepository} mocked. */
@ExtendWith(MockitoExtension.class)
class CustomerProfileServiceTest {

    @Mock private CustomerProfileRepository profileRepo;

    private CustomerProfileService profileService;

    @BeforeEach
    void setUp() {
        profileService = new CustomerProfileService(profileRepo);
    }

    private static CustomerProfile profile(BigDecimal avg, BigDecimal max, String country, int hrStart, int hrEnd) {
        CustomerProfile profile = new CustomerProfile();
        profile.setAcctNo("ACC0000001");
        profile.setAvgTxnAmount(avg);
        profile.setMaxTxnAmount(max);
        profile.setUsualCountry(country);
        profile.setUsualHrStart(hrStart);
        profile.setUsualHrEnd(hrEnd);
        return profile;
    }

    private static FraudCommArea commArea(BigDecimal amount, String country, boolean cnp) {
        FraudCommArea ca = new FraudCommArea();
        ca.setAcctNo("ACC0000001");
        ca.setTxnAmount(amount);
        ca.setTxnCountry(country);
        ca.setCnpFlag(cnp);
        return ca;
    }

    @Test
    void noProfileOnFileDefaultsToTheBaselineScore() {
        when(profileRepo.findById("ACC0000001")).thenReturn(Optional.empty());

        FraudCommArea ca = commArea(new BigDecimal("500.00"), "GBR", false);
        profileService.scoreProfile(ca);

        assertThat(ca.getProfileScore()).isEqualByComparingTo(new BigDecimal("0.3000"));
    }

    @Test
    void largeAmountDeviationScoresHigh() {
        when(profileRepo.findById("ACC0000001"))
                .thenReturn(Optional.of(profile(new BigDecimal("10.00"), new BigDecimal("10.00"), "GBR", 0, 23)));

        FraudCommArea ca = commArea(new BigDecimal("50.00"), "GBR", false);
        profileService.scoreProfile(ca);

        assertThat(ca.getProfileScore()).isEqualByComparingTo(new BigDecimal("0.4000"));
    }

    @Test
    void smallAmountDeviationScoresLow() {
        when(profileRepo.findById("ACC0000001"))
                .thenReturn(Optional.of(profile(new BigDecimal("100.00"), new BigDecimal("100.00"), "GBR", 0, 23)));

        FraudCommArea ca = commArea(new BigDecimal("150.00"), "GBR", false);
        profileService.scoreProfile(ca);

        assertThat(ca.getProfileScore()).isEqualByComparingTo(new BigDecimal("0.2000"));
    }

    @Test
    void amountWithinTheHistoricalMaximumTriggersNoDeviation() {
        when(profileRepo.findById("ACC0000001"))
                .thenReturn(Optional.of(profile(new BigDecimal("500.00"), new BigDecimal("1000.00"), "GBR", 0, 23)));

        FraudCommArea ca = commArea(new BigDecimal("900.00"), "GBR", false);
        profileService.scoreProfile(ca);

        assertThat(ca.getProfileScore()).isEqualByComparingTo(BigDecimal.ZERO);
    }

    @Test
    void zeroAverageAmountIsGuardedAgainstDivideByZero() {
        when(profileRepo.findById("ACC0000001"))
                .thenReturn(Optional.of(profile(BigDecimal.ZERO, new BigDecimal("10.00"), "GBR", 0, 23)));

        FraudCommArea ca = commArea(new BigDecimal("900.00"), "GBR", false);
        profileService.scoreProfile(ca);

        assertThat(ca.getProfileScore()).isEqualByComparingTo(BigDecimal.ZERO);
    }

    @Test
    void crossBorderTransactionAddsTheGeolocationDeviation() {
        when(profileRepo.findById("ACC0000001"))
                .thenReturn(Optional.of(profile(new BigDecimal("500.00"), new BigDecimal("1000.00"), "GBR", 0, 23)));

        FraudCommArea ca = commArea(new BigDecimal("100.00"), "USA", false);
        profileService.scoreProfile(ca);

        assertThat(ca.getProfileScore()).isEqualByComparingTo(new BigDecimal("0.3000"));
        assertThat(ca.isCrossBorder()).isTrue();
    }

    @Test
    void missingTransactionCountryDefaultsToGbrAndIsNotCrossBorder() {
        when(profileRepo.findById("ACC0000001"))
                .thenReturn(Optional.of(profile(new BigDecimal("500.00"), new BigDecimal("1000.00"), "GBR", 0, 23)));

        FraudCommArea ca = commArea(new BigDecimal("100.00"), null, false);
        profileService.scoreProfile(ca);

        assertThat(ca.getProfileScore()).isEqualByComparingTo(BigDecimal.ZERO);
        assertThat(ca.isCrossBorder()).isFalse();
    }

    @Test
    void missingUsualCountryDefaultsToGbr() {
        CustomerProfile profileWithoutCountry = profile(new BigDecimal("500.00"), new BigDecimal("1000.00"), null, 0, 23);
        when(profileRepo.findById("ACC0000001")).thenReturn(Optional.of(profileWithoutCountry));

        FraudCommArea ca = commArea(new BigDecimal("100.00"), "GBR", false);
        profileService.scoreProfile(ca);

        assertThat(ca.getProfileScore()).isEqualByComparingTo(BigDecimal.ZERO);
        assertThat(ca.isCrossBorder()).isFalse();
    }

    @Test
    void transactionOutsideUsualActiveHoursAddsTheTimeOfDayDeviation() {
        // usualHrStart/usualHrEnd is a plain linear range (no wraparound support in
        // CustomerProfileService), so the fixture is built relative to the real
        // clock to guarantee "now" falls outside it, whatever time this test runs.
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
        when(profileRepo.findById("ACC0000001"))
                .thenReturn(Optional.of(profile(new BigDecimal("500.00"), new BigDecimal("1000.00"), "GBR",
                        hrStart, hrEnd)));

        FraudCommArea ca = commArea(new BigDecimal("100.00"), "GBR", false);
        profileService.scoreProfile(ca);

        assertThat(ca.getProfileScore()).isEqualByComparingTo(new BigDecimal("0.2000"));
    }

    @Test
    void cardNotPresentAddsTheCnpUplift() {
        when(profileRepo.findById("ACC0000001"))
                .thenReturn(Optional.of(profile(new BigDecimal("500.00"), new BigDecimal("1000.00"), "GBR", 0, 23)));

        FraudCommArea ca = commArea(new BigDecimal("100.00"), "GBR", true);
        profileService.scoreProfile(ca);

        assertThat(ca.getProfileScore()).isEqualByComparingTo(new BigDecimal("0.1000"));
    }

    @Test
    void allDeviationsCombinedReachTheMaximumScore() {
        when(profileRepo.findById("ACC0000001"))
                .thenReturn(Optional.of(profile(new BigDecimal("10.00"), new BigDecimal("10.00"), "GBR", 0, 23)));

        // amount deviation (0.4) + cross-border (0.3) + CNP uplift (0.1) = 0.8;
        // time-of-day is exercised in its own dedicated test above.
        FraudCommArea ca = commArea(new BigDecimal("50.00"), "USA", true);
        profileService.scoreProfile(ca);

        assertThat(ca.getProfileScore()).isEqualByComparingTo(new BigDecimal("0.8000"));
    }
}
