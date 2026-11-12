using BankXYZ.FraudDetection.Entities;

namespace BankXYZ.FraudDetection.Data.Repositories
{
    /// <summary>
    /// Entity Framework implementation of IWatchlistHitRepository.
    /// </summary>
    public class WatchlistHitRepository : IWatchlistHitRepository
    {
        private readonly FraudDbContext _db;

        public WatchlistHitRepository(FraudDbContext db)
        {
            _db = db;
        }

        public WatchlistHit FindById(int hitId)
        {
            return _db.WatchlistHits.Find(hitId);
        }

        public void Save(WatchlistHit hit)
        {
            if (hit.HitId == 0)
            {
                _db.WatchlistHits.Add(hit);
            }
            else
            {
                WatchlistHit existing = _db.WatchlistHits.Find(hit.HitId);
                if (existing == null)
                {
                    _db.WatchlistHits.Add(hit);
                }
                else
                {
                    _db.Entry(existing).CurrentValues.SetValues(hit);
                }
            }
            _db.SaveChanges();
        }
    }
}
