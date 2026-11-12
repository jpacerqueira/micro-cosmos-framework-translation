using System;

namespace BankXYZ.FraudDetection.Domain
{
    /// <summary>
    /// Categorical risk band for a merchant.
    /// Mirrors the Java RiskBand enum.
    /// </summary>
    public enum RiskBand
    {
        High,
        Med,
        Low,
        Unknown
    }

    /// <summary>
    /// Factory methods for the RiskBand enum.
    /// </summary>
    public static class RiskBandHelper
    {
        /// <summary>
        /// Parses the database string representation of a risk band.
        /// Case-insensitive. Unknown strings map to RiskBand.Unknown.
        /// </summary>
        public static RiskBand FromString(string value)
        {
            if (string.IsNullOrEmpty(value))
                return RiskBand.Unknown;

            switch (value.ToUpperInvariant().Trim())
            {
                case "HIGH": return RiskBand.High;
                case "MED":  return RiskBand.Med;
                case "LOW":  return RiskBand.Low;
                default:     return RiskBand.Unknown;
            }
        }
    }
}
