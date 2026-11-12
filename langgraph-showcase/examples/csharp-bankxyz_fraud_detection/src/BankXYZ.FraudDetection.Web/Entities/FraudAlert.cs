using System;
using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace BankXYZ.FraudDetection.Entities
{
    /// <summary>
    /// A fraud alert raised when a transaction score exceeds the review or decline threshold.
    /// Maps to the FRAUD_ALERTS table.
    /// </summary>
    [Table("FRAUD_ALERTS")]
    public class FraudAlert
    {
        [Key]
        [DatabaseGenerated(DatabaseGeneratedOption.Identity)]
        [Column("ALERT_ID")]
        public int AlertId { get; set; }

        [Required]
        [Column("TXN_ID")]
        [StringLength(16)]
        public string TxnId { get; set; }

        [Required]
        [Column("ACCT_NO")]
        [StringLength(10)]
        public string AcctNo { get; set; }

        [Required]
        [Column("FRAUD_SCORE")]
        public decimal FraudScore { get; set; }

        /// <summary>
        /// Alert status string: "PENDING", "REVIEWED", "CLOSED", "ESCALATED".
        /// </summary>
        [Required]
        [Column("ALERT_STATUS")]
        [StringLength(10)]
        public string AlertStatus { get; set; }

        [Column("ANALYST_ID")]
        [StringLength(20)]
        public string AnalystId { get; set; }

        [Column("RESOLUTION_NOTES")]
        [StringLength(500)]
        public string ResolutionNotes { get; set; }

        /// <summary>
        /// Soft-delete / archive flag. 'N' = active, 'Y' = archived.
        /// </summary>
        [Required]
        [Column("ARCHIVED_FLAG")]
        [StringLength(1)]
        public string ArchivedFlag { get; set; }

        [Required]
        [Column("CREATED_TS")]
        public DateTime CreatedTs { get; set; }

        [Required]
        [Column("UPDATED_TS")]
        public DateTime UpdatedTs { get; set; }
    }
}
