using System;

namespace BankXYZ.FraudDetection.Domain
{
    /// <summary>
    /// Represents the lifecycle status of a bank account.
    /// Mirrors the Java AccountStatus enum.
    /// </summary>
    public enum AccountStatus
    {
        Active,
        Frozen,
        Closed
    }

    /// <summary>
    /// Extension and factory methods for AccountStatus.
    /// Kept as a separate static class for .NET 4.0 compatibility (no extension methods on enums directly).
    /// </summary>
    public static class AccountStatusHelper
    {
        /// <summary>
        /// Converts the single-character database code to an AccountStatus value.
        /// 'A' -> Active, 'F' -> Frozen, 'C' -> Closed.
        /// </summary>
        public static AccountStatus FromCode(string code)
        {
            if (string.IsNullOrEmpty(code))
                return AccountStatus.Closed;

            switch (code.ToUpperInvariant())
            {
                case "A": return AccountStatus.Active;
                case "F": return AccountStatus.Frozen;
                case "C": return AccountStatus.Closed;
                default:
                    throw new ArgumentException("Unknown account status code: " + code);
            }
        }

        /// <summary>
        /// Returns true if the account cannot be used for transactions.
        /// </summary>
        public static bool IsInactive(this AccountStatus status)
        {
            return status == AccountStatus.Frozen || status == AccountStatus.Closed;
        }
    }
}
