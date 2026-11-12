using System;
using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;
using BankXYZ.FraudDetection.Domain;

namespace BankXYZ.FraudDetection.Entities
{
    /// <summary>
    /// Represents a customer bank account.
    /// Maps to the ACCOUNT_MASTER table.
    /// </summary>
    [Table("ACCOUNT_MASTER")]
    public class Account
    {
        [Key]
        [Column("ACCT_NO")]
        [StringLength(10)]
        public string AcctNo { get; set; }

        [Required]
        [Column("CUST_ID")]
        [StringLength(20)]
        public string CustId { get; set; }

        [Required]
        [Column("CUST_FULL_NAME")]
        [StringLength(100)]
        public string CustFullName { get; set; }

        /// <summary>
        /// Single character: 'A'=Active, 'F'=Frozen, 'C'=Closed.
        /// </summary>
        [Required]
        [Column("ACCT_STATUS")]
        [StringLength(1)]
        public string AcctStatus { get; set; }

        /// <summary>
        /// Two-character account type: 'CH'=Current, 'SV'=Savings, 'CR'=Credit.
        /// </summary>
        [Required]
        [Column("ACCT_TYPE")]
        [StringLength(2)]
        public string AcctType { get; set; }

        [Required]
        [Column("HOME_COUNTRY")]
        [StringLength(3)]
        public string HomeCountry { get; set; }

        [Column("DAILY_TXN_COUNT")]
        public int DailyTxnCount { get; set; }

        [Column("LAST_VELOCITY_TS")]
        public DateTime? LastVelocityTs { get; set; }

        [Required]
        [Column("LAST_UPDATE_TS")]
        public DateTime LastUpdateTs { get; set; }

        /// <summary>
        /// Converts the single-character status code to the typed enum.
        /// </summary>
        public AccountStatus GetStatus()
        {
            return AccountStatusHelper.FromCode(AcctStatus);
        }
    }
}
