using System;
using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace BankXYZ.FraudDetection.Entities
{
    /// <summary>
    /// Audit record of a watchlist match for a specific transaction.
    /// Maps to the WATCHLIST_HITS table.
    /// </summary>
    [Table("WATCHLIST_HITS")]
    public class WatchlistHit
    {
        [Key]
        [DatabaseGenerated(DatabaseGeneratedOption.Identity)]
        [Column("HIT_ID")]
        public int HitId { get; set; }

        [Required]
        [Column("ACCT_NO")]
        [StringLength(10)]
        public string AcctNo { get; set; }

        [Required]
        [Column("TXN_ID")]
        [StringLength(16)]
        public string TxnId { get; set; }

        /// <summary>
        /// Type of list that triggered the hit: "OFAC", "PEP", or "INTERNAL".
        /// </summary>
        [Required]
        [Column("HIT_TYPE")]
        [StringLength(10)]
        public string HitType { get; set; }

        [Column("HIT_REASON")]
        [StringLength(200)]
        public string HitReason { get; set; }

        [Required]
        [Column("HIT_TS")]
        public DateTime HitTs { get; set; }
    }
}
