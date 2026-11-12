using BankXYZ.FraudDetection.Entities;

namespace BankXYZ.FraudDetection.Data.Repositories
{
    /// <summary>
    /// Repository contract for watchlist screening queries.
    /// </summary>
    public interface IWatchlistRepository
    {
        WatchlistEntry FindById(int watchlistId);

        /// <summary>
        /// Returns the count of active OFAC watchlist entries whose MATCH_NAME
        /// matches the given name (case-insensitive, upper-case comparison).
        /// </summary>
        int CountOfacHits(string name);

        /// <summary>
        /// Returns the count of active PEP watchlist entries whose MATCH_NAME
        /// matches the given name (case-insensitive, upper-case comparison).
        /// </summary>
        int CountPepHits(string name);

        /// <summary>
        /// Returns the count of active INTERNAL watchlist entries where
        /// MATCH_ACCT equals acctNo OR MATCH_NAME matches name.
        /// </summary>
        int CountInternalHits(string acctNo, string name);

        void Save(WatchlistEntry entry);
    }
}
