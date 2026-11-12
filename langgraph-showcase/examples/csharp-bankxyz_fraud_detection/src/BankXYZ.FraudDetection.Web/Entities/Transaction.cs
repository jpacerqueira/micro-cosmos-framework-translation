using System;
using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace BankXYZ.FraudDetection.Entities
{
    /// <summary>
    /// Represents a payment transaction awaiting or completed fraud screening.
    /// Maps to the TXN_QUEUE table.
    /// </summary>
    [Table("TXN_QUEUE")]
    public class Transaction
    {
        [Key]
        [Column("TXN_ID")]
        [StringLength(16)]
        public string TxnId { get; set; }

        [Required]
        [Column("ACCT_NO")]
        [StringLength(10)]
        public string AcctNo { get; set; }

        [Required]
        [Column("TXN_AMOUNT")]
        public decimal TxnAmount { get; set; }

        [Required]
        [Column("MERCHANT_CODE")]
        [StringLength(8)]
        public string MerchantCode { get; set; }

        [Required]
        [Column("CHANNEL")]
        [StringLength(8)]
        public string Channel { get; set; }

        [Required]
        [Column("TXN_COUNTRY")]
        [StringLength(3)]
        public string TxnCountry { get; set; }

        [Column("CARD_LAST4")]
        [StringLength(4)]
        public string CardLast4 { get; set; }

        [Column("CARD_TYPE")]
        [StringLength(2)]
        public string CardType { get; set; }

        /// <summary>
        /// Card-not-present flag. 'Y' = card not present. Defaults to 'N'.
        /// </summary>
        [Required]
        [Column("CNP_FLAG")]
        [StringLength(1)]
        public string CnpFlag { get; set; }

        /// <summary>
        /// Transaction status: 'P'=Pending, 'S'=Settled/Processed, 'E'=Error.
        /// </summary>
        [Required]
        [Column("TXN_STATUS")]
        [StringLength(1)]
        public string TxnStatus { get; set; }

        [Required]
        [Column("TXN_TS")]
        public DateTime TxnTs { get; set; }

        [Column("PROC_TS")]
        public DateTime? ProcTs { get; set; }

        [Column("BATCH_DATE")]
        public DateTime? BatchDate { get; set; }

        /// <summary>
        /// Returns true if this was a card-not-present (e-commerce / CNP) transaction.
        /// </summary>
        public bool IsCnp()
        {
            return string.Equals("Y", CnpFlag, StringComparison.OrdinalIgnoreCase);
        }
    }
}
