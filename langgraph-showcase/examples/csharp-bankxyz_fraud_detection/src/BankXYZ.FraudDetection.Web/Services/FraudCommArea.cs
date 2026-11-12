using BankXYZ.FraudDetection.Domain;

namespace BankXYZ.FraudDetection.Services
{
    /// <summary>
    /// Communications area passed between fraud scoring services.
    /// Inspired by the CICS COMMAREA pattern — a flat data-passing structure
    /// used in mainframe-style SOA chains.
    ///
    /// One instance is created per authorisation request or batch transaction.
    /// It is not thread-safe and must never be shared across requests.
    /// </summary>
    public class FraudCommArea
    {
        // -----------------------------------------------------------------------
        // Input fields — set by the controller or batch processor before calling Score()
        // -----------------------------------------------------------------------

        public string  TxnId        { get; set; }
        public string  AcctNo       { get; set; }
        public decimal TxnAmount    { get; set; }
        public string  MerchantCode { get; set; }
        public Channel Channel      { get; set; }
        public string  TxnCountry   { get; set; }
        public string  CardType     { get; set; }
        public bool    CnpFlag      { get; set; }

        // -----------------------------------------------------------------------
        // Scoring outputs — populated by FraudRulesService and its delegates
        // -----------------------------------------------------------------------

        public decimal FraudScore     { get; set; }
        public bool    FraudFlag      { get; set; }
        public decimal VelocityScore  { get; set; }
        public decimal ProfileScore   { get; set; }
        public decimal WatchlistScore { get; set; }

        /// <summary>Count of transactions for this account in the last 24h.</summary>
        public int     TxnCount { get; set; }

        /// <summary>Sum of transaction amounts for this account in the last 24h.</summary>
        public decimal TxnSum   { get; set; }

        // -----------------------------------------------------------------------
        // Per-call weights — initialised by FraudRulesService.InitialiseWeights()
        // -----------------------------------------------------------------------

        public decimal WeightAmount    { get; set; }
        public decimal WeightMerchant  { get; set; }
        public decimal WeightVelocity  { get; set; }
        public decimal WeightProfile   { get; set; }
        public decimal WeightWatchlist { get; set; }

        // -----------------------------------------------------------------------
        // Output — populated during or after scoring
        // -----------------------------------------------------------------------

        /// <summary>IDENTITY value of the persisted FraudAlert record, if one was written.</summary>
        public int AlertId { get; set; }

        /// <summary>Customer full name, populated from ACCOUNT_MASTER after account lookup.</summary>
        public string CustFullName { get; set; }

        /// <summary>
        /// Alert status to persist. Defaults to "PENDING".
        /// Set to "ESCALATED" by FraudRulesService when an OFAC or PEP watchlist hit is found.
        /// </summary>
        public string AlertStatus { get; set; }

        public FraudCommArea()
        {
            AlertStatus = "PENDING";
        }
    }
}
