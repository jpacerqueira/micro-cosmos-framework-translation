using System.Configuration;

namespace BankXYZ.FraudDetection.Config
{
    /// <summary>
    /// Typed configuration wrapper for fraud scoring parameters.
    /// All values are read from web.config appSettings.
    /// Use FraudScoringSettings.FromConfiguration() to obtain an instance;
    /// Unity registers the result as a singleton so the config is read once on startup.
    /// </summary>
    public class FraudScoringSettings
    {
        /// <summary>Minimum score to raise a review alert (default 0.75).</summary>
        public decimal ScoreThreshold { get; set; }

        /// <summary>Minimum score to decline the transaction outright (default 0.90).</summary>
        public decimal DeclineThreshold { get; set; }

        /// <summary>Transaction amount (GBP) above which the HIGH amount signal fires (default 5000.00).</summary>
        public decimal HighAmountLimit { get; set; }

        /// <summary>Transaction amount (GBP) above which the MED amount signal fires (default 1000.00).</summary>
        public decimal MedAmountLimit { get; set; }

        /// <summary>Transaction amount (GBP) above which the LOW amount signal fires (default 200.00).</summary>
        public decimal LowAmountLimit { get; set; }

        /// <summary>Maximum expected transactions per account per 24h for batch processing velocity normalisation.</summary>
        public int VelocityLimitBatch { get; set; }

        /// <summary>Maximum expected transactions per account per 24h for real-time velocity normalisation.</summary>
        public int VelocityLimitRealtime { get; set; }

        /// <summary>Weight of the transaction amount signal in the composite score (default 0.25).</summary>
        public decimal WeightAmount { get; set; }

        /// <summary>Weight of the merchant risk signal in the composite score (default 0.25).</summary>
        public decimal WeightMerchant { get; set; }

        /// <summary>Weight of the velocity signal in the composite score (default 0.20).</summary>
        public decimal WeightVelocity { get; set; }

        /// <summary>Weight of the customer profile signal in the composite score (default 0.20).</summary>
        public decimal WeightProfile { get; set; }

        /// <summary>Weight of the watchlist signal in the composite score (default 0.10).</summary>
        public decimal WeightWatchlist { get; set; }

        /// <summary>Real-time SLA limit in milliseconds; breaches result in APPROVE per BRD-2009-FD-004 (default 180ms).</summary>
        public long SlaLimitMs { get; set; }

        /// <summary>Maximum number of pending transactions processed in a single batch run (default 500).</summary>
        public int MaxTransactions { get; set; }

        /// <summary>MSMQ path for fraud alert notifications (default .\Private$\FraudAlertQueue).</summary>
        public string AlertQueuePath { get; set; }

        /// <summary>
        /// Reads all settings from ConfigurationManager.AppSettings.
        /// Missing keys fall back to the documented defaults.
        /// </summary>
        public static FraudScoringSettings FromConfiguration()
        {
            FraudScoringSettings settings = new FraudScoringSettings();

            settings.ScoreThreshold   = decimal.Parse(ConfigurationManager.AppSettings["fraud.scoring.scoreThreshold"]   ?? "0.75");
            settings.DeclineThreshold = decimal.Parse(ConfigurationManager.AppSettings["fraud.scoring.declineThreshold"] ?? "0.90");
            settings.HighAmountLimit  = decimal.Parse(ConfigurationManager.AppSettings["fraud.scoring.highAmountLimit"]  ?? "5000.00");
            settings.MedAmountLimit   = decimal.Parse(ConfigurationManager.AppSettings["fraud.scoring.medAmountLimit"]   ?? "1000.00");
            settings.LowAmountLimit   = decimal.Parse(ConfigurationManager.AppSettings["fraud.scoring.lowAmountLimit"]   ?? "200.00");

            settings.VelocityLimitBatch    = int.Parse(ConfigurationManager.AppSettings["fraud.scoring.velocityLimitBatch"]    ?? "10");
            settings.VelocityLimitRealtime = int.Parse(ConfigurationManager.AppSettings["fraud.scoring.velocityLimitRealtime"] ?? "5");

            settings.WeightAmount    = decimal.Parse(ConfigurationManager.AppSettings["fraud.scoring.weightAmount"]    ?? "0.25");
            settings.WeightMerchant  = decimal.Parse(ConfigurationManager.AppSettings["fraud.scoring.weightMerchant"]  ?? "0.25");
            settings.WeightVelocity  = decimal.Parse(ConfigurationManager.AppSettings["fraud.scoring.weightVelocity"]  ?? "0.20");
            settings.WeightProfile   = decimal.Parse(ConfigurationManager.AppSettings["fraud.scoring.weightProfile"]   ?? "0.20");
            settings.WeightWatchlist = decimal.Parse(ConfigurationManager.AppSettings["fraud.scoring.weightWatchlist"] ?? "0.10");

            settings.SlaLimitMs      = long.Parse(ConfigurationManager.AppSettings["fraud.scoring.slaLimitMs"]      ?? "180");
            settings.MaxTransactions = int.Parse(ConfigurationManager.AppSettings["fraud.batch.maxTransactions"]    ?? "500");
            settings.AlertQueuePath  = ConfigurationManager.AppSettings["fraud.mq.alertQueuePath"] ?? @".\Private$\FraudAlertQueue";

            return settings;
        }
    }
}
