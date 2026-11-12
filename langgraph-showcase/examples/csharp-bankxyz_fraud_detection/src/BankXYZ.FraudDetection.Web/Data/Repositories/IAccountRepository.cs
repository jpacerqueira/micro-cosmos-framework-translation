using BankXYZ.FraudDetection.Entities;

namespace BankXYZ.FraudDetection.Data.Repositories
{
    /// <summary>
    /// Repository contract for account master data access.
    /// </summary>
    public interface IAccountRepository
    {
        Account FindById(string acctNo);
        void Save(Account account);
    }
}
