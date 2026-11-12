using BankXYZ.FraudDetection.Entities;

namespace BankXYZ.FraudDetection.Data.Repositories
{
    /// <summary>
    /// Entity Framework implementation of IMqFailureLogRepository.
    /// </summary>
    public class MqFailureLogRepository : IMqFailureLogRepository
    {
        private readonly FraudDbContext _db;

        public MqFailureLogRepository(FraudDbContext db)
        {
            _db = db;
        }

        public MqFailureLog FindById(int failId)
        {
            return _db.MqFailureLogs.Find(failId);
        }

        public void Save(MqFailureLog failureLog)
        {
            if (failureLog.FailId == 0)
            {
                _db.MqFailureLogs.Add(failureLog);
            }
            else
            {
                MqFailureLog existing = _db.MqFailureLogs.Find(failureLog.FailId);
                if (existing == null)
                {
                    _db.MqFailureLogs.Add(failureLog);
                }
                else
                {
                    _db.Entry(existing).CurrentValues.SetValues(failureLog);
                }
            }
            _db.SaveChanges();
        }
    }
}
