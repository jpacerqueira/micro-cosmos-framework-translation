package com.bankxyz.fraud.domain;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class AccountStatusTest {

    @Test
    void resolvesEachKnownCode() {
        assertThat(AccountStatus.fromCode("A")).isEqualTo(AccountStatus.ACTIVE);
        assertThat(AccountStatus.fromCode("F")).isEqualTo(AccountStatus.FROZEN);
        assertThat(AccountStatus.fromCode("C")).isEqualTo(AccountStatus.CLOSED);
    }

    @Test
    void trimsWhitespaceBeforeMatching() {
        assertThat(AccountStatus.fromCode(" F ")).isEqualTo(AccountStatus.FROZEN);
    }

    @Test
    void nullOrEmptyCodeDefaultsToActive() {
        assertThat(AccountStatus.fromCode(null)).isEqualTo(AccountStatus.ACTIVE);
        assertThat(AccountStatus.fromCode("")).isEqualTo(AccountStatus.ACTIVE);
    }

    @Test
    void unknownCodeThrows() {
        assertThatThrownBy(() -> AccountStatus.fromCode("Z"))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("Z");
    }

    @Test
    void onlyFrozenAndClosedAreInactive() {
        assertThat(AccountStatus.ACTIVE.isInactive()).isFalse();
        assertThat(AccountStatus.FROZEN.isInactive()).isTrue();
        assertThat(AccountStatus.CLOSED.isInactive()).isTrue();
    }

    @Test
    void exposesItsSingleCharacterCode() {
        assertThat(AccountStatus.ACTIVE.getCode()).isEqualTo('A');
        assertThat(AccountStatus.FROZEN.getCode()).isEqualTo('F');
        assertThat(AccountStatus.CLOSED.getCode()).isEqualTo('C');
    }
}
