using System;
using System.Transactions;
using BankXYZ.FraudDetection.Data.Repositories;
using BankXYZ.FraudDetection.Entities;

namespace BankXYZ.FraudDetection.Services
{
    /// <summary>
    /// Writes a FraudAlert record inside a TransactionScope (equivalent of Spring's @Transactional).
    /// MQ notification is dispatched after the DB transaction commits and is non-fatal —
    /// MQ failures are caught by MqNotificationService and logged to MQ_FAILURE_LOG.
    /// </summary>
    public class AlertWriterService : IAlertWriterService
    {
        private readonly IFraudAlertRepository  _alertRepo;
        private readonly IMqNotificationService _mqNotificationService;

        public AlertWriterService(
            IFraudAlertRepository  alertRepo,
            IMqNotificationService mqNotificationService)
        {
            _alertRepo             = alertRepo;
            _mqNotificationService = mqNotificationService;
        }

        public void WriteAlert(FraudCommArea commArea)
        {
            FraudAlert alert = new FraudAlert();
            alert.TxnId       = commArea.TxnId;
            alert.AcctNo      = commArea.AcctNo;
            alert.FraudScore  = commArea.FraudScore;
            alert.AlertStatus = commArea.AlertStatus ?? "PENDING";
            alert.ArchivedFlag = "N";
            alert.CreatedTs   = DateTime.UtcNow;
            alert.UpdatedTs   = DateTime.UtcNow;

            using (TransactionScope scope = new TransactionScope())
            {
                _alertRepo.Save(alert);
                commArea.AlertId = alert.AlertId;
                scope.Complete();
            }

            // MQ notification is outside the DB transaction scope.
            // If it fails, MqNotificationService logs to MQ_FAILURE_LOG.
            _mqNotificationService.Notify(commArea);
        }
    }
}
