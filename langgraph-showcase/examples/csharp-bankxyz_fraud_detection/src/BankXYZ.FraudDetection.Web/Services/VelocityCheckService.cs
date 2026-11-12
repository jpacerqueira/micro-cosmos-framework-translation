using System;
using BankXYZ.FraudDetection.Data.Repositories;

namespace BankXYZ.FraudDetection.Services
{
    /// <summary>
    /// Calculates a velocity-based fraud signal.
    /// High transaction frequency within 24 hours is an indicator of card abuse.
    /// Score is normalised to [0, 1] against the configured velocity limit.
    /// </summary>
    public class VelocityCheckService : IVelocityCheckService
    {
        private readonly ITransactionRepository _txnRepo;

        public VelocityCheckService(ITransactionRepository txnRepo)
        {
            _txnRepo = txnRepo;
        }

        public void CheckVelocity(FraudCommArea commArea, int limit)
        {
            DateTime since = DateTime.UtcNow.AddHours(-24);

            int count = _txnRepo.CountVelocity(commArea.AcctNo, since);

            decimal score = Math.Min((decimal)count / limit, 1.0000m);
            score = Math.Round(score, 4, MidpointRounding.AwayFromZero);

            commArea.VelocityScore = score;
            commArea.TxnCount      = count;
            commArea.TxnSum        = _txnRepo.SumVelocityAmount(commArea.AcctNo, since);
        }
    }
}
