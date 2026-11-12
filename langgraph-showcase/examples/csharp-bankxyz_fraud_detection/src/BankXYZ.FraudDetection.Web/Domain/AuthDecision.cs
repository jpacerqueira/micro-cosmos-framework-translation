using System;

namespace BankXYZ.FraudDetection.Domain
{
    /// <summary>
    /// Authorisation decision for a real-time fraud check.
    /// Mirrors the Java AuthDecision enum.
    /// </summary>
    public enum AuthDecision
    {
        Approve,
        Review,
        Decline
    }

    /// <summary>
    /// Helper methods for AuthDecision.
    /// </summary>
    public static class AuthDecisionHelper
    {
        /// <summary>
        /// Returns the ISO 8583-style return code for a decision.
        /// Approve -> "00", Review -> "20", Decline -> "10"
        /// </summary>
        public static string GetReturnCode(this AuthDecision decision)
        {
            switch (decision)
            {
                case AuthDecision.Approve:  return "00";
                case AuthDecision.Review:   return "20";
                case AuthDecision.Decline:  return "10";
                default:
                    throw new ArgumentOutOfRangeException("decision", decision, "Unknown AuthDecision value.");
            }
        }
    }
}
