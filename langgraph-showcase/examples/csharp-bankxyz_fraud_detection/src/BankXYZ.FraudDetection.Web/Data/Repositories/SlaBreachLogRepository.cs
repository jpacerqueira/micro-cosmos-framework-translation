using BankXYZ.FraudDetection.Entities;

namespace BankXYZ.FraudDetection.Data.Repositories
{
    /// <summary>
    /// Entity Framework implementation of ISlaBreachLogRepository.
    /// </summary>
    public class SlaBreachLogRepository : ISlaBreachLogRepository
    {
        private readonly FraudDbContext _db;

        public SlaBreachLogRepository(FraudDbContext db)
        {
            _db = db;
        }

        public SlaBreachLog FindById(int breachId)
        {
            return _db.SlaBreachLogs.Find(breachId);
        }

        public void Save(SlaBreachLog breachLog)
        {
            if (breachLog.BreachId == 0)
            {
                _db.SlaBreachLogs.Add(breachLog);
            }
            else
            {
                SlaBreachLog existing = _db.SlaBreachLogs.Find(breachLog.BreachId);
                if (existing == null)
                {
                    _db.SlaBreachLogs.Add(breachLog);
                }
                else
                {
                    _db.Entry(existing).CurrentValues.SetValues(breachLog);
                }
            }
            _db.SaveChanges();
        }
    }
}
