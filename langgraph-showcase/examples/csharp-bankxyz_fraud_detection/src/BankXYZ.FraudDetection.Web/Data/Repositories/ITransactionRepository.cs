using System;
using System.Collections.Generic;
using BankXYZ.FraudDetection.Entities;

namespace BankXYZ.FraudDetection.Data.Repositories
{
    /// <summary>
    /// Repository contract for transaction queue data access.
    /// </summary>
    public interface ITransactionRepository
    {
        Transaction FindById(string txnId);

        /// <summary>
        /// Returns pending transactions (TXN_STATUS = 'P') ordered by TXN_TS ascending,
        /// up to maxRows rows.
        /// </summary>
        IList<Transaction> FindPending(int maxRows);

        /// <summary>
        /// Counts transactions for an account in the last 24 hours with status P or S.
        /// Used for velocity scoring.
        /// </summary>
        int CountVelocity(string acctNo, DateTime since);

        /// <summary>
        /// Sums transaction amounts for an account in the last 24 hours with status P or S.
        /// </summary>
        decimal SumVelocityAmount(string acctNo, DateTime since);

        /// <summary>
        /// Updates TXN_STATUS to 'S' and sets PROC_TS for a transaction.
        /// </summary>
        void StampProcessed(string txnId, DateTime procTs);

        void Save(Transaction transaction);
    }
}
