using BankXYZ.FraudDetection.Entities;

namespace BankXYZ.FraudDetection.Data.Repositories
{
    /// <summary>
    /// Entity Framework implementation of ICustomerProfileRepository.
    /// </summary>
    public class CustomerProfileRepository : ICustomerProfileRepository
    {
        private readonly FraudDbContext _db;

        public CustomerProfileRepository(FraudDbContext db)
        {
            _db = db;
        }

        public CustomerProfile FindById(string acctNo)
        {
            return _db.CustomerProfiles.Find(acctNo);
        }

        public void Save(CustomerProfile profile)
        {
            CustomerProfile existing = _db.CustomerProfiles.Find(profile.AcctNo);
            if (existing == null)
            {
                _db.CustomerProfiles.Add(profile);
            }
            else
            {
                _db.Entry(existing).CurrentValues.SetValues(profile);
            }
            _db.SaveChanges();
        }
    }
}
