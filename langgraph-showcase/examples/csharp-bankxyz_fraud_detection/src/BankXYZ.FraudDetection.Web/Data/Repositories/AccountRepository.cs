using BankXYZ.FraudDetection.Entities;

namespace BankXYZ.FraudDetection.Data.Repositories
{
    /// <summary>
    /// Entity Framework implementation of IAccountRepository.
    /// FraudDbContext is injected by Unity and scoped per HTTP request.
    /// </summary>
    public class AccountRepository : IAccountRepository
    {
        private readonly FraudDbContext _db;

        public AccountRepository(FraudDbContext db)
        {
            _db = db;
        }

        public Account FindById(string acctNo)
        {
            return _db.Accounts.Find(acctNo);
        }

        public void Save(Account account)
        {
            Account existing = _db.Accounts.Find(account.AcctNo);
            if (existing == null)
            {
                _db.Accounts.Add(account);
            }
            else
            {
                _db.Entry(existing).CurrentValues.SetValues(account);
            }
            _db.SaveChanges();
        }
    }
}
