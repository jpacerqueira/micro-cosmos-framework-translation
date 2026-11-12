using BankXYZ.FraudDetection.Entities;

namespace BankXYZ.FraudDetection.Data.Repositories
{
    /// <summary>
    /// Repository contract for merchant risk reference data.
    /// </summary>
    public interface IMerchantRiskRepository
    {
        MerchantRisk FindById(string merchantCode);
        void Save(MerchantRisk merchantRisk);
    }
}
