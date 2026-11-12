namespace BankXYZ.FraudDetection.Services
{
    /// <summary>
    /// Contract for the regulatory and internal watchlist screening service.
    /// Screening order: OFAC -> PEP -> INTERNAL.
    /// OFAC and PEP hits result in score 1.0 and ESCALATED status.
    /// INTERNAL hits result in score 0.8 and remain PENDING.
    /// </summary>
    public interface IWatchlistService
    {
        /// <summary>
        /// Screens the transaction against OFAC, PEP, and INTERNAL watchlists.
        /// Populates commArea.WatchlistScore. May also set commArea.AlertStatus to "ESCALATED".
        /// Writes a WatchlistHit record for each match found.
        /// </summary>
        void ScreenWatchlist(FraudCommArea commArea);
    }
}
