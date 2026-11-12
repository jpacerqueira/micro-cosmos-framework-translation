using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace BankXYZ.FraudDetection.Entities
{
    /// <summary>
    /// An entry on one of the regulatory or internal screening watchlists.
    /// List types: OFAC (sanctions), PEP (politically exposed persons), INTERNAL (bank-defined).
    /// Maps to the WATCHLIST table.
    /// </summary>
    [Table("WATCHLIST")]
    public class WatchlistEntry
    {
        [Key]
        [DatabaseGenerated(DatabaseGeneratedOption.Identity)]
        [Column("WATCHLIST_ID")]
        public int WatchlistId { get; set; }

        /// <summary>
        /// Type of watchlist: "OFAC", "PEP", or "INTERNAL".
        /// </summary>
        [Required]
        [Column("LIST_TYPE")]
        [StringLength(10)]
        public string ListType { get; set; }

        [Column("MATCH_NAME")]
        [StringLength(100)]
        public string MatchName { get; set; }

        [Column("MATCH_ACCT")]
        [StringLength(10)]
        public string MatchAcct { get; set; }

        /// <summary>
        /// Status of this watchlist entry: "ACTIVE" or "EXPIRED".
        /// </summary>
        [Required]
        [Column("LIST_STATUS")]
        [StringLength(10)]
        public string ListStatus { get; set; }
    }
}
