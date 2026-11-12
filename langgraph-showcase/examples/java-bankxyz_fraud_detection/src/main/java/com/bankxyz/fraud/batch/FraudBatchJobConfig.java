package com.bankxyz.fraud.batch;

import com.bankxyz.fraud.config.FraudScoringProperties;
import com.bankxyz.fraud.service.TransactionMonitorService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.batch.core.Job;
import org.springframework.batch.core.Step;
import org.springframework.batch.core.configuration.annotation.JobBuilderFactory;
import org.springframework.batch.core.configuration.annotation.StepBuilderFactory;
import org.springframework.batch.core.launch.support.RunIdIncrementer;
import org.springframework.batch.repeat.RepeatStatus;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.batch.core.JobParameters;
import org.springframework.batch.core.JobParametersBuilder;
import org.springframework.batch.core.launch.JobLauncher;

/**
 * Spring Batch job configuration — nightly fraud scoring batch.
 *
 * Runs nightly at 02:00 via a @Scheduled cron.
 * Single step delegates to TransactionMonitorService.
 */
@Configuration
public class FraudBatchJobConfig {

    private static final Logger log = LoggerFactory.getLogger(FraudBatchJobConfig.class);

    private final JobBuilderFactory jobs;
    private final StepBuilderFactory steps;
    private final TransactionMonitorService monitorService;
    private final FraudScoringProperties props;
    private final JobLauncher jobLauncher;

    @Value("${fraud.batch.max-transactions:500}")
    private int maxTransactions;

    public FraudBatchJobConfig(JobBuilderFactory jobs,
                                StepBuilderFactory steps,
                                TransactionMonitorService monitorService,
                                FraudScoringProperties props,
                                JobLauncher jobLauncher) {
        this.jobs = jobs;
        this.steps = steps;
        this.monitorService = monitorService;
        this.props = props;
        this.jobLauncher = jobLauncher;
    }

    /**
     * Spring Batch Job: FRAUD-BATCH-JOB
     */
    @Bean
    public Job fraudBatchJob() {
        return jobs.get("FRAUD-BATCH-JOB")
                .incrementer(new RunIdIncrementer())
                .start(fraudScoringStep())
                .build();
    }

    /**
     * Single step — delegates all logic to TransactionMonitorService.
     */
    @Bean
    public Step fraudScoringStep() {
        return steps.get("FRAUD-SCORING-STEP")
                .tasklet((contribution, chunkContext) -> {
                    String result = monitorService.processBatch(maxTransactions);
                    chunkContext.getStepContext()
                            .getStepExecution()
                            .getJobExecution()
                            .getExecutionContext()
                            .put("batchSummary", result);
                    return RepeatStatus.FINISHED;
                })
                .build();
    }

    /**
     * Scheduled trigger — nightly 02:00.
     * Cron expression configurable via fraud.batch.cron in application.properties.
     */
    @Scheduled(cron = "${fraud.batch.cron:0 0 2 * * ?}")
    public void runScheduledBatch() {
        try {
            JobParameters params = new JobParametersBuilder()
                    .addLong("runTime", System.currentTimeMillis())
                    .toJobParameters();
            jobLauncher.run(fraudBatchJob(), params);
            log.info("Scheduled batch run complete");
        } catch (Exception e) {
            log.error("Scheduled batch run failed: {}", e.getMessage(), e);
        }
    }
}
