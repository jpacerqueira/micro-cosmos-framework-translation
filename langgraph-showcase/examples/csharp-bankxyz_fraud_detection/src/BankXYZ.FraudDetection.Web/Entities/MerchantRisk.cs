using System;
using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace BankXYZ.FraudDetection.Entities
{
    /// <summary>
    /// Merchant-level risk information used in fraud scoring.
    /// Maps to the MERCHANT_RISK table.
    /// </summary>
    [Table("MERCHANT_RISK")]
    public class MerchantRisk
    {
        [Key]
        [Column("MERCHANT_CODE")]
        [StringLength(8)]
        public string MerchantCode { get; set; }

        /// <summary>
        /// 'Y' = merchant is blocked; all transactions are flagged at score 1.0.
        /// </summary>
        [Required]
        [Column("BLOCKED_FLAG")]
        [StringLength(1)]
        public string BlockedFlag { get; set; }

        /// <summary>
        /// Risk band string: 'HIGH', 'MED', or 'LOW'.
        /// </summary>
        [Required]
        [Column("RISK_BAND")]
        [StringLength(4)]
        public string RiskBand { get; set; }

        [Required]
        [Column("EFFECTIVE_FROM")]
        public DateTime EffectiveFrom { get; set; }

        [Column("EFFECTIVE_TO")]
        public DateTime? EffectiveTo { get; set; }

        /// <summary>
        /// Returns true if this merchant is currently blocked.
        /// </summary>
        public bool IsBlocked()
        {
            return string.Equals("Y", BlockedFlag, StringComparison.OrdinalIgnoreCase);
        }
    }
}
