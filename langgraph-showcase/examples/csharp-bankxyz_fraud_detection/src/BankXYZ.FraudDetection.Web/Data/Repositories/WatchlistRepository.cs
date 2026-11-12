using System.Linq;
using BankXYZ.FraudDetection.Entities;

namespace BankXYZ.FraudDetection.Data.Repositories
{
    /// <summary>
    /// Entity Framework implementation of IWatchlistRepository.
    /// All name comparisons use ToUpper() to replicate the Oracle UPPER() convention.
    /// </summary>
    public class WatchlistRepository : IWatchlistRepository
    {
        private readonly FraudDbContext _db;

        public WatchlistRepository(FraudDbContext db)
        {
            _db = db;
        }

        public WatchlistEntry FindById(int watchlistId)
        {
            return _db.WatchlistEntries.Find(watchlistId);
        }

        public int CountOfacHits(string name)
        {
            if (string.IsNullOrEmpty(name))
                return 0;

            string upperName = name.ToUpperInvariant();
            return _db.WatchlistEntries
                .Where(w => w.ListType == "OFAC"
                    && w.ListStatus == "ACTIVE"
                    && w.MatchName != null
                    && w.MatchName.ToUpper() == upperName)
                .Count();
        }

        public int CountPepHits(string name)
        {
            if (string.IsNullOrEmpty(name))
                return 0;

            string upperName = name.ToUpperInvariant();
            return _db.WatchlistEntries
                .Where(w => w.ListType == "PEP"
                    && w.ListStatus == "ACTIVE"
                    && w.MatchName != null
                    && w.MatchName.ToUpper() == upperName)
                .Count();
        }

        public int CountInternalHits(string acctNo, string name)
        {
            string upperName = string.IsNullOrEmpty(name) ? string.Empty : name.ToUpperInvariant();

            return _db.WatchlistEntries
                .Where(w => w.ListType == "INTERNAL"
                    && w.ListStatus == "ACTIVE"
                    && (
                        (w.MatchAcct != null && w.MatchAcct == acctNo)
                        ||
                        (w.MatchName != null && w.MatchName.ToUpper() == upperName)
                    ))
                .Count();
        }

        public void Save(WatchlistEntry entry)
        {
            if (entry.WatchlistId == 0)
            {
                _db.WatchlistEntries.Add(entry);
            }
            else
            {
                WatchlistEntry existing = _db.WatchlistEntries.Find(entry.WatchlistId);
                if (existing == null)
                {
                    _db.WatchlistEntries.Add(entry);
                }
                else
                {
                    _db.Entry(existing).CurrentValues.SetValues(entry);
                }
            }
            _db.SaveChanges();
        }
    }
}
