using System;
using BankXYZ.FraudDetection.Config;
using BankXYZ.FraudDetection.Data.Repositories;
using BankXYZ.FraudDetection.Domain;
using BankXYZ.FraudDetection.Entities;

namespace BankXYZ.FraudDetection.Services
{
    /// <summary>
    /// Core fraud scoring rules engine.
    ///
    /// Scoring model (weighted composite):
    ///   composite = (amountScore * weightAmount)
    ///             + (merchantScore * weightMerchant)
    ///             + (velocityScore * weightVelocity)
    ///             + (profileScore  * weightProfile)
    ///             + (watchlistScore * weightWatchlist)
    ///
    /// ChipPin override: profile weight is zeroed and redistributed 0.25/0.25/0.25/0.25.
    /// OFAC/PEP watchlist match: score is immediately set to 1.0 and status is ESCALATED.
    ///
    /// Score is clamped to [0, 1] and rounded to 4 decimal places (HALF_UP equivalent).
    /// </summary>
    public class FraudRulesService : IFraudRulesService
    {
        private readonly IAccountRepository      _accountRepo;
        private readonly IMerchantRiskRepository _merchantRepo;
        private readonly IVelocityCheckService   _velocityService;
        private readonly ICustomerProfileService _profileService;
        private readonly IWatchlistService       _watchlistService;
        private readonly FraudScoringSettings    _settings;

        public FraudRulesService(
            IAccountRepository      accountRepo,
            IMerchantRiskRepository merchantRepo,
            IVelocityCheckService   velocityService,
            ICustomerProfileService profileService,
            IWatchlistService       watchlistService,
            FraudScoringSettings    settings)
        {
            _accountRepo      = accountRepo;
            _merchantRepo     = merchantRepo;
            _velocityService  = velocityService;
            _profileService   = profileService;
            _watchlistService = watchlistService;
            _settings         = settings;
        }

        public void Score(FraudCommArea commArea, int velocityLimit)
        {
            // 1. Initialise per-channel weights
            InitialiseWeights(commArea);

            // 2. Validate account — inactive accounts are automatically fraudulent
            Account account = _accountRepo.FindById(commArea.AcctNo);
            if (account == null || account.GetStatus().IsInactive())
            {
                commArea.FraudScore  = 1.0000m;
                commArea.FraudFlag   = true;
                commArea.AlertStatus = "ESCALATED";
                return;
            }
            commArea.CustFullName = account.CustFullName;

            // 3. Amount signal
            decimal amountScore = ScoreAmount(commArea.TxnAmount);

            // 4. Merchant risk signal
            MerchantRisk merchant     = _merchantRepo.FindById(commArea.MerchantCode);
            decimal      merchantScore = ScoreMerchant(merchant);

            // 5. Velocity signal — populates commArea.VelocityScore, TxnCount, TxnSum
            _velocityService.CheckVelocity(commArea, velocityLimit);

            // 6. Customer profile signal — populates commArea.ProfileScore
            _profileService.ScoreProfile(commArea);

            // 7. Watchlist screening — populates commArea.WatchlistScore
            _watchlistService.ScreenWatchlist(commArea);

            // OFAC/PEP escalation: short-circuit with maximum score
            if (commArea.WatchlistScore >= 1.0000m)
            {
                commArea.FraudScore  = 1.0000m;
                commArea.FraudFlag   = true;
                commArea.AlertStatus = "ESCALATED";
                return;
            }

            // 8. Composite weighted score
            decimal composite =
                  (amountScore           * commArea.WeightAmount)
                + (merchantScore         * commArea.WeightMerchant)
                + (commArea.VelocityScore * commArea.WeightVelocity)
                + (commArea.ProfileScore  * commArea.WeightProfile)
                + (commArea.WatchlistScore * commArea.WeightWatchlist);

            composite = Math.Min(composite, 1.0000m);
            composite = Math.Round(composite, 4, MidpointRounding.AwayFromZero);

            commArea.FraudScore = composite;
            commArea.FraudFlag  = (composite >= _settings.ScoreThreshold);
        }

        /// <summary>
        /// Sets per-call scoring weights.
        /// ChipPin transactions remove the profile signal (not meaningful for in-person chip),
        /// redistributing its weight equally across the other four factors.
        /// </summary>
        private void InitialiseWeights(FraudCommArea commArea)
        {
            if (commArea.Channel.IsChipPin())
            {
                commArea.WeightAmount    = 0.25m;
                commArea.WeightMerchant  = 0.25m;
                commArea.WeightVelocity  = 0.25m;
                commArea.WeightProfile   = 0.00m;
                commArea.WeightWatchlist = 0.25m;
            }
            else
            {
                commArea.WeightAmount    = _settings.WeightAmount;
                commArea.WeightMerchant  = _settings.WeightMerchant;
                commArea.WeightVelocity  = _settings.WeightVelocity;
                commArea.WeightProfile   = _settings.WeightProfile;
                commArea.WeightWatchlist = _settings.WeightWatchlist;
            }
        }

        /// <summary>
        /// Converts transaction amount into a risk signal in [0.1, 0.8].
        /// </summary>
        private decimal ScoreAmount(decimal amount)
        {
            if (amount >= _settings.HighAmountLimit) return 0.8000m;
            if (amount >= _settings.MedAmountLimit)  return 0.5000m;
            if (amount >= _settings.LowAmountLimit)  return 0.3000m;
            return 0.1000m;
        }

        /// <summary>
        /// Converts merchant risk status into a risk signal in [0.0, 1.0].
        /// Blocked merchants score 1.0 immediately.
        /// </summary>
        private decimal ScoreMerchant(MerchantRisk merchant)
        {
            if (merchant == null)        return 0.0000m;
            if (merchant.IsBlocked())    return 1.0000m;

            RiskBand band = RiskBandHelper.FromString(merchant.RiskBand);

            switch (band)
            {
                case RiskBand.High: return 0.8000m;
                case RiskBand.Med:  return 0.4000m;
                case RiskBand.Low:  return 0.1000m;
                default:            return 0.0000m;
            }
        }
    }
}
