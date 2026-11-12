namespace BankXYZ.FraudDetection.Domain
{
    /// <summary>
    /// Lifecycle status of a fraud alert record.
    /// Mirrors the Java AlertStatus enum.
    /// </summary>
    public enum AlertStatus
    {
        Pending,
        Reviewed,
        Closed,
        Escalated
    }
}
