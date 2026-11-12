package com.bankxyz.fraud.domain;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Locks down the APPROVE/REVIEW/DECLINE -> returnCode mapping (ARCHITECTURE.md
 * §12) — a typo here silently breaks the case management system's contract.
 */
class AuthDecisionTest {

    @Test
    void returnCodesMatchTheDocumentedContract() {
        assertThat(AuthDecision.APPROVE.getReturnCode()).isEqualTo("00");
        assertThat(AuthDecision.REVIEW.getReturnCode()).isEqualTo("20");
        assertThat(AuthDecision.DECLINE.getReturnCode()).isEqualTo("10");
    }
}
