using System;
using System.Collections.Generic;
using BankXYZ.FraudDetection.Config;
using BankXYZ.FraudDetection.Data.Repositories;
using BankXYZ.FraudDetection.Domain;
using BankXYZ.FraudDetection.Entities;

namespace BankXYZ.FraudDetection.Services
{
    /// <summary>
    /// Batch processor that drains the TXN_QUEUE of pending transactions.
    /// Called by the nightly FraudBatchScheduler or on-demand via POST /api/v1/batch/run.
    ///
    /// For each pending transaction:
    ///   1. Build a FraudCommArea from the transaction record.
    ///   2. Score using FraudRulesService (batch velocity limit applies).
    ///   3. If fraud-flagged, write a FraudAlert.
    ///   4. Stamp the transaction as processed (TXN_STATUS = 'S').
    /// </summary>
    public class TransactionMonitorService : ITransactionMonitorService
    {
        private readonly ITransactionRepository _txnRepo;
        private readonly IFraudRulesService     _fraudRulesService;
        private readonly IAlertWriterService    _alertWriterService;
        private readonly FraudScoringSettings   _settings;

        public TransactionMonitorService(
            ITransactionRepository txnRepo,
            IFraudRulesService     fraudRulesService,
            IAlertWriterService    alertWriterService,
            FraudScoringSettings   settings)
        {
            _txnRepo            = txnRepo;
            _fraudRulesService  = fraudRulesService;
            _alertWriterService = alertWriterService;
            _settings           = settings;
        }

        public string ProcessBatch(int maxTransactions)
        {
            DateTime batchStart = DateTime.UtcNow;

            IList<Transaction> pending = _txnRepo.FindPending(maxTransactions);
            int alertCount = 0;

            foreach (Transaction txn in pending)
            {
                FraudCommArea commArea = new FraudCommArea();
                commArea.TxnId        = txn.TxnId;
                commArea.AcctNo       = txn.AcctNo;
                commArea.TxnAmount    = txn.TxnAmount;
                commArea.MerchantCode = txn.MerchantCode;
                commArea.Channel      = ChannelHelper.FromString(txn.Channel);
                commArea.TxnCountry   = txn.TxnCountry;
                commArea.CardType     = txn.CardType;
                commArea.CnpFlag      = txn.IsCnp();

                _fraudRulesService.Score(commArea, _settings.VelocityLimitBatch);

                if (commArea.FraudFlag)
                {
                    _alertWriterService.WriteAlert(commArea);
                    alertCount++;
                }

                _txnRepo.StampProcessed(txn.TxnId, DateTime.UtcNow);
            }

            long elapsedMs = (long)(DateTime.UtcNow - batchStart).TotalMilliseconds;

            return string.Format(
                "Batch complete: {0} processed, {1} alerts raised in {2}ms",
                pending.Count,
                alertCount,
                elapsedMs);
        }
    }
}
