using System;
using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace BankXYZ.FraudDetection.Entities
{
    /// <summary>
    /// Records MSMQ delivery failures for fraud alert notifications.
    /// Enables reconciliation and reprocessing of missed alerts.
    /// Maps to the MQ_FAILURE_LOG table.
    /// </summary>
    [Table("MQ_FAILURE_LOG")]
    public class MqFailureLog
    {
        [Key]
        [DatabaseGenerated(DatabaseGeneratedOption.Identity)]
        [Column("FAIL_ID")]
        public int FailId { get; set; }

        [Required]
        [Column("TXN_ID")]
        [StringLength(16)]
        public string TxnId { get; set; }

        [Required]
        [Column("ACCT_NO")]
        [StringLength(10)]
        public string AcctNo { get; set; }

        /// <summary>
        /// Win32 HRESULT or exception HResult code indicating the reason for failure.
        /// </summary>
        [Column("REASON_CODE")]
        public int? ReasonCode { get; set; }

        [Required]
        [Column("FAILED_TS")]
        public DateTime FailedTs { get; set; }
    }
}
