using System;
using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace BankXYZ.FraudDetection.Entities
{
    /// <summary>
    /// Records instances where real-time fraud scoring exceeded the SLA time limit.
    /// Per BRD-2009-FD-004, transactions are APPROVED when the SLA is breached
    /// to avoid blocking genuine customers.
    /// Maps to the SLA_BREACH_LOG table.
    /// </summary>
    [Table("SLA_BREACH_LOG")]
    public class SlaBreachLog
    {
        [Key]
        [DatabaseGenerated(DatabaseGeneratedOption.Identity)]
        [Column("BREACH_ID")]
        public int BreachId { get; set; }

        [Required]
        [Column("TXN_ID")]
        [StringLength(16)]
        public string TxnId { get; set; }

        [Required]
        [Column("ACCT_NO")]
        [StringLength(10)]
        public string AcctNo { get; set; }

        /// <summary>
        /// Actual elapsed time in milliseconds that triggered the SLA breach.
        /// </summary>
        [Required]
        [Column("ELAPSED_MS")]
        public long ElapsedMs { get; set; }

        [Required]
        [Column("BREACH_TS")]
        public DateTime BreachTs { get; set; }
    }
}
