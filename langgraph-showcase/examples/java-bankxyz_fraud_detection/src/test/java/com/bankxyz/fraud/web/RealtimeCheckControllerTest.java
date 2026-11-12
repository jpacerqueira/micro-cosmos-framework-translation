package com.bankxyz.fraud.web;

import com.bankxyz.fraud.batch.FraudBatchJobConfig;
import com.bankxyz.fraud.config.FraudScoringProperties;
import com.bankxyz.fraud.domain.AuthDecision;
import com.bankxyz.fraud.repository.SlaBreachLogRepository;
import com.bankxyz.fraud.service.AlertWriterService;
import com.bankxyz.fraud.service.FraudCommArea;
import com.bankxyz.fraud.service.FraudRulesService;
import com.bankxyz.fraud.web.dto.FraudCheckRequest;
import com.bankxyz.fraud.web.dto.FraudCheckResponse;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.batch.core.Job;
import org.springframework.batch.core.JobParameters;
import org.springframework.batch.core.JobParametersInvalidException;
import org.springframework.batch.core.launch.JobLauncher;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;

import java.math.BigDecimal;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * Unit tests for {@link RealtimeCheckController}, with every collaborator
 * mocked — a plain unit test rather than a Spring MockMvc slice, since the
 * decision-mapping logic under test has no framework wiring to verify.
 * The real HTTP contract is covered end to end by realtime_authorisation.feature.
 */
@ExtendWith(MockitoExtension.class)
class RealtimeCheckControllerTest {

    @Mock private FraudRulesService rulesService;
    @Mock private AlertWriterService alertService;
    @Mock private SlaBreachLogRepository slaBreachRepo;
    @Mock private JobLauncher jobLauncher;
    @Mock private FraudBatchJobConfig batchJobConfig;

    private FraudScoringProperties props;
    private RealtimeCheckController controller;

    @BeforeEach
    void setUp() {
        props = new FraudScoringProperties();
        controller = new RealtimeCheckController(rulesService, alertService, slaBreachRepo, props,
                jobLauncher, batchJobConfig);
    }

    private static FraudCheckRequest request(String acctNo, BigDecimal amount, String channel) {
        FraudCheckRequest request = new FraudCheckRequest();
        request.setTxnId("TXN0000000000001");
        request.setAcctNo(acctNo);
        request.setTxnAmount(amount);
        request.setChannel(channel);
        request.setTxnCountry("GBR");
        return request;
    }

    private void stubScore(BigDecimal score) {
        doAnswer(invocation -> {
            FraudCommArea ca = invocation.getArgument(0);
            ca.setFraudScore(score);
            ca.setMessage("Transaction cleared");
            return null;
        }).when(rulesService).score(any(), anyInt());
    }

    @Test
    void lowScoreIsApprovedAndNoAlertIsRaised() {
        stubScore(new BigDecimal("0.2000"));

        ResponseEntity<FraudCheckResponse> response = controller.authorise(request("ACC0000001",
                new BigDecimal("50.00"), "ONLINE"));

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
        assertThat(response.getBody().getDecision()).isEqualTo(AuthDecision.APPROVE);
        assertThat(response.getBody().getReturnCode()).isEqualTo("00");
        verify(alertService, never()).writeAlert(any());
    }

    @Test
    void reviewRangeScoreIsReviewedAndAnAlertIsRaised() {
        stubScore(new BigDecimal("0.8000"));

        ResponseEntity<FraudCheckResponse> response = controller.authorise(request("ACC0000001",
                new BigDecimal("9999.00"), "ONLINE"));

        assertThat(response.getBody().getDecision()).isEqualTo(AuthDecision.REVIEW);
        assertThat(response.getBody().getReturnCode()).isEqualTo("20");
        verify(alertService).writeAlert(any());
    }

    @Test
    void declineRangeScoreIsDeclinedAndAnAlertIsRaised() {
        stubScore(new BigDecimal("0.9500"));

        ResponseEntity<FraudCheckResponse> response = controller.authorise(request("ACC0000001",
                new BigDecimal("9999.00"), "ONLINE"));

        assertThat(response.getBody().getDecision()).isEqualTo(AuthDecision.DECLINE);
        assertThat(response.getBody().getReturnCode()).isEqualTo("10");
        verify(alertService).writeAlert(any());
    }

    @Test
    void slaBreachDefaultsToApproveAndIsLoggedEvenForAHighRiskScore() {
        props.setSlaLimitMs(-1); // guarantees elapsedMs > slaLimitMs deterministically
        stubScore(new BigDecimal("0.9500"));

        ResponseEntity<FraudCheckResponse> response = controller.authorise(request("ACC0000001",
                new BigDecimal("9999.00"), "ONLINE"));

        assertThat(response.getBody().getDecision()).isEqualTo(AuthDecision.APPROVE);
        assertThat(response.getBody().getMessage()).isEqualTo("SLA exceeded - defaulting to approve");
        verify(slaBreachRepo).save(any());
        // The SLA-breach short-circuit returns before the alert-writing branch is reached.
        verify(alertService, never()).writeAlert(any());
    }

    @Test
    void slaBreachLoggingFailureIsSwallowed() {
        props.setSlaLimitMs(-1);
        stubScore(new BigDecimal("0.2000"));
        doThrow(new RuntimeException("H2 is down")).when(slaBreachRepo).save(any());

        ResponseEntity<FraudCheckResponse> response = controller.authorise(request("ACC0000001",
                new BigDecimal("50.00"), "ONLINE"));

        assertThat(response.getBody().getDecision()).isEqualTo(AuthDecision.APPROVE);
    }

    @Test
    void manualBatchTriggerSubmitsTheJobSuccessfully() {
        Job job = mock(Job.class);
        when(batchJobConfig.fraudBatchJob()).thenReturn(job);

        ResponseEntity<String> response = controller.triggerBatch();

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
        assertThat(response.getBody()).isEqualTo("Batch job submitted");
    }

    @Test
    void manualBatchTriggerReportsAFailureFromTheJobLauncher() throws Exception {
        Job job = mock(Job.class);
        when(batchJobConfig.fraudBatchJob()).thenReturn(job);
        when(jobLauncher.run(any(Job.class), any(JobParameters.class)))
                .thenThrow(new JobParametersInvalidException("bad params"));

        ResponseEntity<String> response = controller.triggerBatch();

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.INTERNAL_SERVER_ERROR);
        assertThat(response.getBody()).contains("Batch trigger failed");
    }
}
