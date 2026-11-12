using System;
using BankXYZ.FraudDetection.Data.Repositories;
using BankXYZ.FraudDetection.Entities;

namespace BankXYZ.FraudDetection.Services
{
    /// <summary>
    /// Scores a transaction against the customer's behavioural profile.
    ///
    /// Anomaly signals:
    ///   +0.30 — amount is more than 3x the customer average
    ///   +0.15 — amount is between 1.5x and 3x the customer average
    ///   +0.20 — amount exceeds the customer's historical maximum
    ///   +0.20 — transaction country differs from the customer's usual country
    ///   +0.15 — transaction falls outside the customer's usual hour window
    ///   +0.10 — card-not-present (CNP/e-commerce) uplift
    ///
    /// If no profile exists, a default score of 0.30 is returned
    /// (low-risk assumption for new accounts).
    /// </summary>
    public class CustomerProfileService : ICustomerProfileService
    {
        private readonly ICustomerProfileRepository _profileRepo;

        public CustomerProfileService(ICustomerProfileRepository profileRepo)
        {
            _profileRepo = profileRepo;
        }

        public void ScoreProfile(FraudCommArea commArea)
        {
            CustomerProfile profile = _profileRepo.FindById(commArea.AcctNo);

            if (profile == null)
            {
                // No profile on record — apply conservative default.
                commArea.ProfileScore = 0.3000m;
                return;
            }

            decimal score = 0.0000m;

            // Amount deviation signal
            if (profile.AvgTxnAmount > 0)
            {
                decimal deviation = commArea.TxnAmount / profile.AvgTxnAmount;
                if (deviation > 3.0m)
                    score += 0.3000m;
                else if (deviation > 1.5m)
                    score += 0.1500m;
            }

            // Maximum amount exceeded signal
            if (commArea.TxnAmount > profile.MaxTxnAmount)
                score += 0.2000m;

            // Geolocation anomaly signal
            if (!string.IsNullOrEmpty(profile.UsualCountry) &&
                !string.Equals(profile.UsualCountry, commArea.TxnCountry, StringComparison.OrdinalIgnoreCase))
            {
                score += 0.2000m;
            }

            // Time-of-day anomaly signal
            int hourNow = DateTime.UtcNow.Hour;
            int hrStart = profile.UsualHrStart.HasValue ? profile.UsualHrStart.Value : 0;
            int hrEnd   = profile.UsualHrEnd.HasValue   ? profile.UsualHrEnd.Value   : 23;

            if (hourNow < hrStart || hourNow > hrEnd)
                score += 0.1500m;

            // Card-not-present uplift
            if (commArea.CnpFlag)
                score += 0.1000m;

            score = Math.Min(score, 1.0000m);
            score = Math.Round(score, 4, MidpointRounding.AwayFromZero);
            commArea.ProfileScore = score;
        }
    }
}
