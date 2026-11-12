namespace BankXYZ.FraudDetection.Services
{
    /// <summary>
    /// Contract for the customer behavioural profile scoring service.
    /// Detects anomalies against the customer's established transaction patterns.
    /// </summary>
    public interface ICustomerProfileService
    {
        /// <summary>
        /// Populates commArea.ProfileScore based on deviations from the
        /// customer's historical transaction profile.
        /// </summary>
        void ScoreProfile(FraudCommArea commArea);
    }
}
