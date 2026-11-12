namespace BankXYZ.FraudDetection.Services
{
    /// <summary>
    /// Contract for the velocity check service.
    /// Velocity measures how many transactions an account has processed in the past 24 hours.
    /// </summary>
    public interface IVelocityCheckService
    {
        /// <summary>
        /// Populates commArea.VelocityScore, commArea.TxnCount, and commArea.TxnSum
        /// based on the account's 24-hour transaction history.
        /// </summary>
        /// <param name="commArea">The shared communications area for this request.</param>
        /// <param name="limit">The expected maximum transaction count (normaliser).</param>
        void CheckVelocity(FraudCommArea commArea, int limit);
    }
}
