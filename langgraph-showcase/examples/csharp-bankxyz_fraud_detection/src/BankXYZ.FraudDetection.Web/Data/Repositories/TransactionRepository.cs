using System;
using System.Collections.Generic;
using System.Linq;
using BankXYZ.FraudDetection.Entities;

namespace BankXYZ.FraudDetection.Data.Repositories
{
    /// <summary>
    /// Entity Framework implementation of ITransactionRepository.
    /// </summary>
    public class TransactionRepository : ITransactionRepository
    {
        private readonly FraudDbContext _db;

        public TransactionRepository(FraudDbContext db)
        {
            _db = db;
        }

        public Transaction FindById(string txnId)
        {
            return _db.Transactions.Find(txnId);
        }

        public IList<Transaction> FindPending(int maxRows)
        {
            return _db.Transactions
                .Where(t => t.TxnStatus == "P")
                .OrderBy(t => t.TxnTs)
                .Take(maxRows)
                .ToList();
        }

        public int CountVelocity(string acctNo, DateTime since)
        {
            return _db.Transactions
                .Where(t => t.AcctNo == acctNo
                    && (t.TxnStatus == "P" || t.TxnStatus == "S")
                    && t.TxnTs >= since)
                .Count();
        }

        public decimal SumVelocityAmount(string acctNo, DateTime since)
        {
            // LINQ Sum returns 0 when there are no rows (non-nullable decimal).
            // We need to handle the case where there are genuinely no rows.
            IQueryable<decimal> query = _db.Transactions
                .Where(t => t.AcctNo == acctNo
                    && (t.TxnStatus == "P" || t.TxnStatus == "S")
                    && t.TxnTs >= since)
                .Select(t => t.TxnAmount);

            if (!query.Any())
                return 0.00m;

            return query.Sum();
        }

        public void StampProcessed(string txnId, DateTime procTs)
        {
            Transaction txn = _db.Transactions.Find(txnId);
            if (txn != null)
            {
                txn.TxnStatus = "S";
                txn.ProcTs = procTs;
                _db.SaveChanges();
            }
        }

        public void Save(Transaction transaction)
        {
            Transaction existing = _db.Transactions.Find(transaction.TxnId);
            if (existing == null)
            {
                _db.Transactions.Add(transaction);
            }
            else
            {
                _db.Entry(existing).CurrentValues.SetValues(transaction);
            }
            _db.SaveChanges();
        }
    }
}
