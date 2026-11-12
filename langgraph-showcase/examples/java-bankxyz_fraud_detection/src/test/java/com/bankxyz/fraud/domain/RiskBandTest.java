package com.bankxyz.fraud.domain;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class RiskBandTest {

    @Test
    void resolvesByEnumNameOrPaddedValue() {
        assertThat(RiskBand.fromString("HIGH")).isEqualTo(RiskBand.HIGH);
        assertThat(RiskBand.fromString("MED ")).isEqualTo(RiskBand.MED);
        assertThat(RiskBand.fromString("low")).isEqualTo(RiskBand.LOW);
    }

    @Test
    void nullOrUnrecognisedValueResolvesToUnknown() {
        assertThat(RiskBand.fromString(null)).isEqualTo(RiskBand.UNKNOWN);
        assertThat(RiskBand.fromString("EXTREME")).isEqualTo(RiskBand.UNKNOWN);
    }
}
