using System;
using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace BankXYZ.FraudDetection.Entities
{
    /// <summary>
    /// Behavioural profile for a customer account, used for anomaly detection.
    /// Maps to the CUST_PROFILE table.
    /// </summary>
    [Table("CUST_PROFILE")]
    public class CustomerProfile
    {
        [Key]
        [Column("ACCT_NO")]
        [StringLength(10)]
        public string AcctNo { get; set; }

        [Required]
        [Column("AVG_TXN_AMOUNT")]
        public decimal AvgTxnAmount { get; set; }

        [Required]
        [Column("MAX_TXN_AMOUNT")]
        public decimal MaxTxnAmount { get; set; }

        [Column("USUAL_COUNTRY")]
        [StringLength(3)]
        public string UsualCountry { get; set; }

        [Column("USUAL_CHANNEL")]
        [StringLength(8)]
        public string UsualChannel { get; set; }

        /// <summary>
        /// Start of the customer's typical transaction hour window (0-23, UTC).
        /// </summary>
        [Column("USUAL_HR_START")]
        public int? UsualHrStart { get; set; }

        /// <summary>
        /// End of the customer's typical transaction hour window (0-23, UTC).
        /// </summary>
        [Column("USUAL_HR_END")]
        public int? UsualHrEnd { get; set; }

        [Required]
        [Column("PROFILE_DATE")]
        public DateTime ProfileDate { get; set; }
    }
}
