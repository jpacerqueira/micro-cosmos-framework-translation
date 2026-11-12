using System;
using System.Messaging;
using Newtonsoft.Json;
using BankXYZ.FraudDetection.Config;
using BankXYZ.FraudDetection.Data.Repositories;
using BankXYZ.FraudDetection.Entities;

namespace BankXYZ.FraudDetection.Services
{
    /// <summary>
    /// Sends fraud alert notifications to an MSMQ private queue.
    /// The message body is a JSON-serialised AlertMessage object.
    ///
    /// MSMQ is a Windows-only component. In Docker this runs on Windows Server Core.
    /// If MSMQ is not available (e.g. development on Linux), the catch block ensures
    /// the application continues running and logs the failure to MQ_FAILURE_LOG.
    /// </summary>
    public class MqNotificationService : IMqNotificationService
    {
        private readonly FraudScoringSettings   _settings;
        private readonly IMqFailureLogRepository _mqFailureLogRepo;

        public MqNotificationService(
            FraudScoringSettings    settings,
            IMqFailureLogRepository mqFailureLogRepo)
        {
            _settings         = settings;
            _mqFailureLogRepo = mqFailureLogRepo;
        }

        public void Notify(FraudCommArea commArea)
        {
            try
            {
                string queuePath = _settings.AlertQueuePath;

                if (!MessageQueue.Exists(queuePath))
                    MessageQueue.Create(queuePath);

                MessageQueue queue = new MessageQueue(queuePath);
                queue.Formatter = new XmlMessageFormatter(new Type[] { typeof(string) });

                AlertMessage alertMessage = new AlertMessage();
                alertMessage.AlertId = commArea.AlertId;
                alertMessage.TxnId   = commArea.TxnId;
                alertMessage.AcctNo  = commArea.AcctNo;
                alertMessage.Amount  = commArea.TxnAmount;
                alertMessage.Score   = commArea.FraudScore;
                alertMessage.Channel = commArea.Channel.ToString().ToUpper();
                alertMessage.Country = commArea.TxnCountry;
                alertMessage.Status  = commArea.AlertStatus ?? "PENDING";

                string json = JsonConvert.SerializeObject(alertMessage);
                queue.Send(json);
            }
            catch (Exception ex)
            {
                MqFailureLog failure = new MqFailureLog();
                failure.TxnId      = commArea.TxnId;
                failure.AcctNo     = commArea.AcctNo;
                failure.ReasonCode = ex.HResult;
                failure.FailedTs   = DateTime.UtcNow;

                _mqFailureLogRepo.Save(failure);
            }
        }

        /// <summary>
        /// Internal DTO serialised to JSON for the MSMQ message body.
        /// </summary>
        private class AlertMessage
        {
            [JsonProperty("alert_id")] public int     AlertId { get; set; }
            [JsonProperty("txn_id")]   public string  TxnId   { get; set; }
            [JsonProperty("acct_no")]  public string  AcctNo  { get; set; }
            [JsonProperty("amount")]   public decimal Amount  { get; set; }
            [JsonProperty("score")]    public decimal Score   { get; set; }
            [JsonProperty("channel")]  public string  Channel { get; set; }
            [JsonProperty("country")]  public string  Country { get; set; }
            [JsonProperty("status")]   public string  Status  { get; set; }
        }
    }
}
