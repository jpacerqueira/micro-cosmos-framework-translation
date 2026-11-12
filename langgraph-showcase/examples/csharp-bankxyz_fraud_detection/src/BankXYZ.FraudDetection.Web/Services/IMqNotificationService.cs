namespace BankXYZ.FraudDetection.Services
{
    /// <summary>
    /// Contract for sending fraud alert notifications via MSMQ.
    /// Failures are non-fatal and are logged to MQ_FAILURE_LOG.
    /// </summary>
    public interface IMqNotificationService
    {
        /// <summary>
        /// Sends a JSON-encoded alert message to the configured MSMQ queue.
        /// On failure, logs to MQ_FAILURE_LOG and returns silently.
        /// </summary>
        void Notify(FraudCommArea commArea);
    }
}
