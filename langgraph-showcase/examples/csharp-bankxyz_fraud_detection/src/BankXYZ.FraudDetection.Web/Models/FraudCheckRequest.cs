using Newtonsoft.Json;

namespace BankXYZ.FraudDetection.Models
{
    /// <summary>
    /// JSON request body for POST /api/v1/authorise.
    /// Deserialised by ASP.NET MVC 3's JsonValueProviderFactory via Newtonsoft.Json.
    /// All property names use camelCase to match the OpenAPI contract.
    /// </summary>
    public class FraudCheckRequest
    {
        [JsonProperty("txnId")]
        public string TxnId { get; set; }

        [JsonProperty("acctNo")]
        public string AcctNo { get; set; }

        [JsonProperty("txnAmount")]
        public decimal TxnAmount { get; set; }

        [JsonProperty("merchantCode")]
        public string MerchantCode { get; set; }

        [JsonProperty("channel")]
        public string Channel { get; set; }

        [JsonProperty("txnCountry")]
        public string TxnCountry { get; set; }

        [JsonProperty("cardType")]
        public string CardType { get; set; }

        [JsonProperty("cnpFlag")]
        public bool CnpFlag { get; set; }
    }
}
