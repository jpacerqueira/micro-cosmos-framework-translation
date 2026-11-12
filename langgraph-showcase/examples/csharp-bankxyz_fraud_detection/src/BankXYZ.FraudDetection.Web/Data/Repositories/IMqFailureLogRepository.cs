using BankXYZ.FraudDetection.Entities;

namespace BankXYZ.FraudDetection.Data.Repositories
{
    /// <summary>
    /// Repository contract for MQ failure log records.
    /// </summary>
    public interface IMqFailureLogRepository
    {
        MqFailureLog FindById(int failId);
        void Save(MqFailureLog failureLog);
    }
}
