using BankXYZ.FraudDetection.Entities;

namespace BankXYZ.FraudDetection.Data.Repositories
{
    /// <summary>
    /// Repository contract for SLA breach log records.
    /// </summary>
    public interface ISlaBreachLogRepository
    {
        SlaBreachLog FindById(int breachId);
        void Save(SlaBreachLog breachLog);
    }
}
