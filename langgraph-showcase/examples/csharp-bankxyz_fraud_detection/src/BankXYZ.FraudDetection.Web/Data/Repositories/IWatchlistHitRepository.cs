using BankXYZ.FraudDetection.Entities;

namespace BankXYZ.FraudDetection.Data.Repositories
{
    /// <summary>
    /// Repository contract for watchlist hit audit records.
    /// </summary>
    public interface IWatchlistHitRepository
    {
        WatchlistHit FindById(int hitId);
        void Save(WatchlistHit hit);
    }
}
