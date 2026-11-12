using BankXYZ.FraudDetection.Entities;

namespace BankXYZ.FraudDetection.Data.Repositories
{
    /// <summary>
    /// Repository contract for customer behavioural profiles.
    /// </summary>
    public interface ICustomerProfileRepository
    {
        CustomerProfile FindById(string acctNo);
        void Save(CustomerProfile profile);
    }
}
