package com.bankxyz.fraud.domain;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class ChannelTest {

    @Test
    void resolvesByEnumNameOrPaddedValue() {
        assertThat(Channel.fromString("ONLINE")).isEqualTo(Channel.ONLINE);
        assertThat(Channel.fromString("CHIPPIN ")).isEqualTo(Channel.CHIPPIN);
        assertThat(Channel.fromString("atm")).isEqualTo(Channel.ATM);
    }

    @Test
    void nullOrUnrecognisedValueResolvesToUnknown() {
        assertThat(Channel.fromString(null)).isEqualTo(Channel.UNKNOWN);
        assertThat(Channel.fromString("CARRIER_PIGEON")).isEqualTo(Channel.UNKNOWN);
    }

    @Test
    void onlyChipPinSkipsTheProfileCheck() {
        assertThat(Channel.CHIPPIN.isChipPin()).isTrue();
        assertThat(Channel.ONLINE.isChipPin()).isFalse();
        assertThat(Channel.ATM.isChipPin()).isFalse();
        assertThat(Channel.BRANCH.isChipPin()).isFalse();
        assertThat(Channel.UNKNOWN.isChipPin()).isFalse();
    }
}
