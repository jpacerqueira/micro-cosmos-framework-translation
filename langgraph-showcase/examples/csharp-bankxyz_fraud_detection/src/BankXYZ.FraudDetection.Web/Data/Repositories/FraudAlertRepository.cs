using BankXYZ.FraudDetection.Entities;

namespace BankXYZ.FraudDetection.Data.Repositories
{
    /// <summary>
    /// Entity Framework implementation of IFraudAlertRepository.
    /// After SaveChanges(), EF populates the identity AlertId back onto the entity.
    /// </summary>
    public class FraudAlertRepository : IFraudAlertRepository
    {
        private readonly FraudDbContext _db;

        public FraudAlertRepository(FraudDbContext db)
        {
            _db = db;
        }

        public FraudAlert FindById(int alertId)
        {
            return _db.FraudAlerts.Find(alertId);
        }

        public void Save(FraudAlert fraudAlert)
        {
            if (fraudAlert.AlertId == 0)
            {
                // New record — let IDENTITY assign the key.
                _db.FraudAlerts.Add(fraudAlert);
            }
            else
            {
                FraudAlert existing = _db.FraudAlerts.Find(fraudAlert.AlertId);
                if (existing == null)
                {
                    _db.FraudAlerts.Add(fraudAlert);
                }
                else
                {
                    _db.Entry(existing).CurrentValues.SetValues(fraudAlert);
                }
            }
            _db.SaveChanges();
            // After SaveChanges, fraudAlert.AlertId is populated by EF from the IDENTITY value.
        }
    }
}
