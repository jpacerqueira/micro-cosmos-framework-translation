namespace BankXYZ.FraudDetection.Services
{
    /// <summary>
    /// Contract for the core fraud scoring rules engine.
    /// Orchestrates all sub-signals and computes the composite fraud score.
    /// </summary>
    public interface IFraudRulesService
    {
        /// <summary>
        /// Scores the transaction described by commArea.
        /// On return, commArea.FraudScore, commArea.FraudFlag, and commArea.AlertStatus
        /// are populated. Sub-service scores (velocity, profile, watchlist) are also available.
        /// </summary>
        /// <param name="commArea">The shared communications area for this request.</param>
        /// <param name="velocityLimit">The velocity normaliser for this call context (batch vs real-time).</param>
        void Score(FraudCommArea commArea, int velocityLimit);
    }
}
