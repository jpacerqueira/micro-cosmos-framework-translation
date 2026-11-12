namespace BankXYZ.FraudDetection.Services
{
    /// <summary>
    /// Contract for persisting fraud alerts and dispatching MQ notifications.
    /// The DB write is wrapped in a TransactionScope; MQ notification is non-fatal.
    /// </summary>
    public interface IAlertWriterService
    {
        /// <summary>
        /// Persists a FraudAlert record and sends an MQ notification.
        /// Populates commArea.AlertId with the generated IDENTITY value.
        /// </summary>
        void WriteAlert(FraudCommArea commArea);
    }
}
