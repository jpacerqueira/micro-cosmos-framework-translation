using System;
using BankXYZ.FraudDetection.Data.Repositories;
using BankXYZ.FraudDetection.Entities;

namespace BankXYZ.FraudDetection.Services
{
    /// <summary>
    /// Screens a transaction against regulatory and internal watchlists.
    ///
    /// Screening is short-circuiting: the first OFAC or PEP hit stops further
    /// checks and returns score 1.0000. An INTERNAL hit returns score 0.8000.
    /// All hits are persisted to WATCHLIST_HITS for audit purposes.
    /// </summary>
    public class WatchlistService : IWatchlistService
    {
        private readonly IWatchlistRepository     _watchlistRepo;
        private readonly IWatchlistHitRepository  _watchlistHitRepo;

        public WatchlistService(
            IWatchlistRepository    watchlistRepo,
            IWatchlistHitRepository watchlistHitRepo)
        {
            _watchlistRepo    = watchlistRepo;
            _watchlistHitRepo = watchlistHitRepo;
        }

        public void ScreenWatchlist(FraudCommArea commArea)
        {
            string name = commArea.CustFullName ?? string.Empty;

            // OFAC — sanctions list; immediate escalation
            if (_watchlistRepo.CountOfacHits(name) > 0)
            {
                LogHit(commArea, "OFAC", "Screening match: OFAC");
                commArea.WatchlistScore = 1.0000m;
                return;
            }

            // PEP — politically exposed persons; immediate escalation
            if (_watchlistRepo.CountPepHits(name) > 0)
            {
                LogHit(commArea, "PEP", "Screening match: PEP");
                commArea.WatchlistScore = 1.0000m;
                return;
            }

            // INTERNAL — bank-defined watchlist; elevated score but not escalated
            if (_watchlistRepo.CountInternalHits(commArea.AcctNo, name) > 0)
            {
                LogHit(commArea, "INTERNAL", "Screening match: INTERNAL");
                commArea.WatchlistScore = 0.8000m;
                return;
            }

            commArea.WatchlistScore = 0.0000m;
        }

        private void LogHit(FraudCommArea commArea, string hitType, string reason)
        {
            WatchlistHit hit = new WatchlistHit();
            hit.AcctNo    = commArea.AcctNo;
            hit.TxnId     = commArea.TxnId;
            hit.HitType   = hitType;
            hit.HitReason = reason;
            hit.HitTs     = DateTime.UtcNow;

            _watchlistHitRepo.Save(hit);
        }
    }
}
