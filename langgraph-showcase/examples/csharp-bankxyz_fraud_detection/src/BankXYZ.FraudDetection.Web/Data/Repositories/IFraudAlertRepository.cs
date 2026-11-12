using BankXYZ.FraudDetection.Entities;

namespace BankXYZ.FraudDetection.Data.Repositories
{
    /// <summary>
    /// Repository contract for fraud alert records.
    /// </summary>
    public interface IFraudAlertRepository
    {
        FraudAlert FindById(int alertId);
        void Save(FraudAlert fraudAlert);
    }
}
