package com.bankxyz.fraud.web;

import com.bankxyz.fraud.batch.FraudBatchJobConfig;
import com.bankxyz.fraud.config.FraudScoringProperties;
import com.bankxyz.fraud.domain.AuthDecision;
import com.bankxyz.fraud.domain.Channel;
import com.bankxyz.fraud.entity.SlaBreachLog;
import com.bankxyz.fraud.repository.SlaBreachLogRepository;
import com.bankxyz.fraud.service.AlertWriterService;
import com.bankxyz.fraud.service.FraudCommArea;
import com.bankxyz.fraud.service.FraudRulesService;
import com.bankxyz.fraud.web.dto.FraudCheckRequest;
import com.bankxyz.fraud.web.dto.FraudCheckResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.batch.core.JobParameters;
import org.springframework.batch.core.JobParametersBuilder;
import org.springframework.batch.core.launch.JobLauncher;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.math.BigDecimal;

/**
 * Real-time card authorisation check.
 *
 * Called synchronously during card authorisation.
 * Must respond within 180ms; if the SLA is breached the decision defaults to APPROVE.
 *
 * Business invariants:
 *   - APPROVE  '00': score < 0.75, or SLA breached (BRD-2009-FD-004)
 *   - REVIEW   '20': score >= 0.75 — alert created, transaction allowed through
 *   - DECLINE  '10': score >= 0.90 — transaction blocked
 *   - SLA breach logged to SLA_BREACH_LOG and decision defaults to APPROVE
 *   - chip+PIN (CHIPPIN channel) → profile weight zeroed (BAU-2021-09)
 *   - Velocity limit = 5 (halved vs batch limit of 10, shorter observation window)
 */
@RestController
@RequestMapping("/api/v1")
public class RealtimeCheckController {

    private static final Logger log = LoggerFactory.getLogger(RealtimeCheckController.class);

    private final FraudRulesService rulesService;
    private final AlertWriterService alertService;
    private final SlaBreachLogRepository slaBreachRepo;
    private final FraudScoringProperties props;
    private final JobLauncher jobLauncher;
    private final FraudBatchJobConfig batchJobConfig;

    public RealtimeCheckController(FraudRulesService rulesService,
                                    AlertWriterService alertService,
                                    SlaBreachLogRepository slaBreachRepo,
                                    FraudScoringProperties props,
                                    JobLauncher jobLauncher,
                                    FraudBatchJobConfig batchJobConfig) {
        this.rulesService = rulesService;
        this.alertService = alertService;
        this.slaBreachRepo = slaBreachRepo;
        this.props = props;
        this.jobLauncher = jobLauncher;
        this.batchJobConfig = batchJobConfig;
    }

    /**
     * POST /api/v1/authorise
     *
     * Synchronous fraud check. Returns within 180ms or defaults to APPROVE (BRD-2009-FD-004).
     */
    @PostMapping("/authorise")
    public ResponseEntity<FraudCheckResponse> authorise(@RequestBody FraudCheckRequest request) {
        long startMs = System.currentTimeMillis();

        FraudCommArea commArea = buildCommArea(request);

        rulesService.score(commArea, props.getVelocityLimitRealtime());

        long elapsedMs = System.currentTimeMillis() - startMs;

        // SLA check — log breach and default to APPROVE
        if (elapsedMs > props.getSlaLimitMs()) {
            logSlaBreach(commArea, (int) elapsedMs);
            log.warn("SLA breached: txn={} elapsed={}ms — defaulting to APPROVE (BRD-2009-FD-004)",
                    request.getTxnId(), elapsedMs);
            return ResponseEntity.ok(new FraudCheckResponse(
                    request.getTxnId(),
                    AuthDecision.APPROVE,
                    commArea.getFraudScore(),
                    "SLA exceeded - defaulting to approve",
                    elapsedMs));
        }

        // Map fraud score to authorisation decision
        AuthDecision decision = mapDecision(commArea.getFraudScore());

        if (decision == AuthDecision.REVIEW || decision == AuthDecision.DECLINE) {
            if (decision == AuthDecision.REVIEW) {
                alertService.writeAlert(commArea);
            }
            // DECLINE also gets an alert since score >= 0.90 is always >= 0.75
            if (decision == AuthDecision.DECLINE) {
                alertService.writeAlert(commArea);
            }
        }

        log.info("Authorise: txn={} decision={} score={} elapsed={}ms",
                request.getTxnId(), decision, commArea.getFraudScore(), elapsedMs);

        return ResponseEntity.ok(new FraudCheckResponse(
                request.getTxnId(),
                decision,
                commArea.getFraudScore(),
                commArea.getMessage(),
                elapsedMs));
    }

    /**
     * POST /api/v1/batch/run
     * Manually trigger the nightly batch job (for testing / operational recovery).
     */
    @PostMapping("/batch/run")
    public ResponseEntity<String> triggerBatch() {
        try {
            JobParameters params = new JobParametersBuilder()
                    .addLong("runTime", System.currentTimeMillis())
                    .toJobParameters();
            jobLauncher.run(batchJobConfig.fraudBatchJob(), params);
            return ResponseEntity.ok("Batch job submitted");
        } catch (Exception e) {
            log.error("Manual batch trigger failed: {}", e.getMessage(), e);
            return ResponseEntity.internalServerError().body("Batch trigger failed: " + e.getMessage());
        }
    }

    /**
     * Maps composite fraud score to APPROVE / REVIEW / DECLINE.
     */
    private AuthDecision mapDecision(BigDecimal score) {
        if (score.compareTo(props.getDeclineThreshold()) >= 0) {
            return AuthDecision.DECLINE;
        }
        if (score.compareTo(props.getScoreThreshold()) >= 0) {
            return AuthDecision.REVIEW;
        }
        return AuthDecision.APPROVE;
    }

    /** Records SLA breach to SLA_BREACH_LOG. */
    private void logSlaBreach(FraudCommArea commArea, int elapsedMs) {
        try {
            SlaBreachLog breach = new SlaBreachLog();
            breach.setTxnId(commArea.getTxnId());
            breach.setAcctNo(commArea.getAcctNo());
            breach.setElapsedMs(elapsedMs);
            slaBreachRepo.save(breach);
        } catch (Exception e) {
            log.error("Failed to log SLA breach for txn={}: {}", commArea.getTxnId(), e.getMessage());
        }
    }

    private FraudCommArea buildCommArea(FraudCheckRequest req) {
        FraudCommArea ca = new FraudCommArea();
        ca.setTxnId(req.getTxnId());
        ca.setAcctNo(req.getAcctNo());
        ca.setTxnAmount(req.getTxnAmount());
        ca.setMerchantCode(req.getMerchantCode());
        ca.setChannel(Channel.fromString(req.getChannel()));
        ca.setTxnCountry(req.getTxnCountry());
        ca.setCardType(req.getCardType());
        ca.setCnpFlag(req.isCnpFlag());
        return ca;
    }
}
