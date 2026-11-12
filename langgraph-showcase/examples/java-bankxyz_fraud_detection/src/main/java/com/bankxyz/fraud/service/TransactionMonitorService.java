package com.bankxyz.fraud.service;

import com.bankxyz.fraud.config.FraudScoringProperties;
import com.bankxyz.fraud.domain.Channel;
import com.bankxyz.fraud.entity.Transaction;
import com.bankxyz.fraud.repository.TransactionRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.domain.PageRequest;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.List;

/**
 * Batch transaction monitor.
 *
 * Entry point for the batch fraud screening pipeline.
 * Reads pending transactions from TXN_QUEUE, scores each via FraudRulesService,
 * and routes flagged transactions to AlertWriterService.
 *
 * Called by: FraudBatchJobConfig (Spring Batch nightly job).
 *
 * Business invariants:
 *   - Only transactions with TXN_STATUS = 'P' (pending) are scored
 *   - Score >= 0.75 triggers a fraud alert
 *   - Every processed transaction is stamped with PROC_TS and status='S'
 *   - Batch processes up to max-transactions per run
 */
@Service
public class TransactionMonitorService {

    private static final Logger log = LoggerFactory.getLogger(TransactionMonitorService.class);

    private final TransactionRepository txnRepo;
    private final FraudRulesService rulesService;
    private final AlertWriterService alertService;
    private final FraudScoringProperties props;

    public TransactionMonitorService(TransactionRepository txnRepo,
                                      FraudRulesService rulesService,
                                      AlertWriterService alertService,
                                      FraudScoringProperties props) {
        this.txnRepo = txnRepo;
        this.rulesService = rulesService;
        this.alertService = alertService;
        this.props = props;
    }

    /**
     * Process all pending transactions in the batch window.
     * Returns a summary string: "BATCH COMPLETE: SCORED=n FLAGGED=n".
     *
     * @param maxTransactions cap from application.properties
     */
    @Transactional
    public String processBatch(int maxTransactions) {
        List<Transaction> pending = txnRepo.findByTxnStatusOrderByTxnTs(
                "P", PageRequest.of(0, maxTransactions));

        if (pending.isEmpty()) {
            log.info("No pending transactions in batch");
            return "NO PENDING TRANSACTIONS IN BATCH";
        }

        int scored  = 0;
        int flagged = 0;
        int errors  = 0;

        for (Transaction txn : pending) {
            try {
                FraudCommArea commArea = buildCommArea(txn);
                rulesService.score(commArea, props.getVelocityLimitBatch());
                scored++;

                if (commArea.isFraudFlag()) {
                    alertService.writeAlert(commArea);
                    flagged++;
                }

                txnRepo.stampProcessed(txn.getTxnId(), LocalDateTime.now());

            } catch (Exception e) {
                log.error("Error processing txn={}: {}", txn.getTxnId(), e.getMessage(), e);
                errors++;
            }
        }

        String summary = String.format("BATCH COMPLETE: SCORED=%d FLAGGED=%d ERRORS=%d",
                scored, flagged, errors);
        log.info("{}", summary);
        return summary;
    }

    private FraudCommArea buildCommArea(Transaction txn) {
        FraudCommArea ca = new FraudCommArea();
        ca.setTxnId(txn.getTxnId());
        ca.setAcctNo(txn.getAcctNo());
        ca.setTxnAmount(txn.getTxnAmount());
        ca.setMerchantCode(txn.getMerchantCode());
        ca.setChannel(Channel.fromString(txn.getChannel()));
        ca.setTxnCountry(txn.getTxnCountry());
        ca.setCardType(txn.getCardType());
        ca.setCnpFlag(txn.isCnp());
        return ca;
    }
}
