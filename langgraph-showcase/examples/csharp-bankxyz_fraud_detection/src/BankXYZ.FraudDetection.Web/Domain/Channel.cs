using System;

namespace BankXYZ.FraudDetection.Domain
{
    /// <summary>
    /// The channel through which a transaction was initiated.
    /// Mirrors the Java Channel enum.
    /// </summary>
    public enum Channel
    {
        Atm,
        Online,
        Branch,
        ChipPin,
        Unknown
    }

    /// <summary>
    /// Helper and factory methods for the Channel enum.
    /// </summary>
    public static class ChannelHelper
    {
        /// <summary>
        /// Returns true if this channel is chip-and-PIN, which modifies weight distribution
        /// in the fraud scoring model (profile weight redistributed to other factors).
        /// </summary>
        public static bool IsChipPin(this Channel channel)
        {
            return channel == Channel.ChipPin;
        }

        /// <summary>
        /// Parses a string representation of a channel to the Channel enum value.
        /// Case-insensitive. Unknown strings map to Channel.Unknown.
        /// </summary>
        public static Channel FromString(string value)
        {
            if (string.IsNullOrEmpty(value))
                return Channel.Unknown;

            switch (value.ToUpperInvariant().Trim())
            {
                case "ATM":      return Channel.Atm;
                case "ONLINE":   return Channel.Online;
                case "BRANCH":   return Channel.Branch;
                case "CHIPPIN":
                case "CHIP_PIN":
                case "CHIP-PIN": return Channel.ChipPin;
                default:         return Channel.Unknown;
            }
        }
    }
}
