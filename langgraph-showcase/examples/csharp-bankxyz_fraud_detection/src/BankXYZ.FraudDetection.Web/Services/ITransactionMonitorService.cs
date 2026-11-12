namespace BankXYZ.FraudDetection.Services
{
    /// <summary>
    /// Contract for the batch transaction monitoring service.
    /// Processes pending transactions in bulk, scoring each and raising alerts as needed.
    /// </summary>
    public interface ITransactionMonitorService
    {
        /// <summary>
        /// Fetches up to maxTransactions pending records from TXN_QUEUE,
        /// scores each one, writes alerts for fraud-flagged transactions,
        /// and stamps each transaction as processed.
        /// </summary>
        /// <returns>A human-readable summary string suitable for logging or API response.</returns>
        string ProcessBatch(int maxTransactions);
    }
}
