using BankXYZ.FraudDetection.Entities;

namespace BankXYZ.FraudDetection.Data.Repositories
{
    /// <summary>
    /// Entity Framework implementation of IMerchantRiskRepository.
    /// </summary>
    public class MerchantRiskRepository : IMerchantRiskRepository
    {
        private readonly FraudDbContext _db;

        public MerchantRiskRepository(FraudDbContext db)
        {
            _db = db;
        }

        public MerchantRisk FindById(string merchantCode)
        {
            return _db.MerchantRisks.Find(merchantCode);
        }

        public void Save(MerchantRisk merchantRisk)
        {
            MerchantRisk existing = _db.MerchantRisks.Find(merchantRisk.MerchantCode);
            if (existing == null)
            {
                _db.MerchantRisks.Add(merchantRisk);
            }
            else
            {
                _db.Entry(existing).CurrentValues.SetValues(merchantRisk);
            }
            _db.SaveChanges();
        }
    }
}
