using Newtonsoft.Json;
using BankXYZ.FraudDetection.Domain;

namespace BankXYZ.FraudDetection.Models
{
    /// <summary>
    /// JSON response body for POST /api/v1/authorise.
    /// Decision is returned as a string ("APPROVE", "REVIEW", "DECLINE") and
    /// ReturnCode is returned as an ISO 8583-style code ("00", "20", "10").
    /// </summary>
    public class FraudCheckResponse
    {
        [JsonProperty("txnId")]
        public string TxnId { get; set; }

        /// <summary>Decision as an uppercase string: "APPROVE", "REVIEW", or "DECLINE".</summary>
        [JsonProperty("decision")]
        public string Decision { get; set; }

        /// <summary>ISO 8583-style return code: "00"=Approve, "20"=Review, "10"=Decline.</summary>
        [JsonProperty("returnCode")]
        public string ReturnCode { get; set; }

        [JsonProperty("fraudScore")]
        public decimal FraudScore { get; set; }

        [JsonProperty("message")]
        public string Message { get; set; }

        [JsonProperty("elapsedMs")]
        public long ElapsedMs { get; set; }

        /// <summary>
        /// Sets both Decision (string) and ReturnCode from the typed AuthDecision enum value.
        /// Called by the controller after scoring.
        /// </summary>
        public void SetDecision(AuthDecision authDecision)
        {
            Decision   = authDecision.ToString().ToUpper();
            ReturnCode = authDecision.GetReturnCode();
        }
    }
}
