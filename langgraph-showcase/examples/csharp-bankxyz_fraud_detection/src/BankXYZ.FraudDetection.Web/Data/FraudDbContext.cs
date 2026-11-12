using System.Data.Entity;
using System.Data.Entity.ModelConfiguration.Conventions;
using BankXYZ.FraudDetection.Entities;

namespace BankXYZ.FraudDetection.Data
{
    /// <summary>
    /// Entity Framework 4.1 DbContext for the BankXYZ Fraud Detection system.
    ///
    /// Connection string name "FraudDb" is resolved from web.config connectionStrings.
    /// Schema creation is disabled — DDL is managed exclusively by the mssql/ scripts.
    /// Unity IoC manages context lifetime (HierarchicalLifetimeManager = one per web request).
    /// </summary>
    public class FraudDbContext : DbContext
    {
        public FraudDbContext()
            : base("name=FraudDb")
        {
        }

        public DbSet<Account>         Accounts         { get; set; }
        public DbSet<Transaction>     Transactions     { get; set; }
        public DbSet<MerchantRisk>    MerchantRisks    { get; set; }
        public DbSet<FraudAlert>      FraudAlerts      { get; set; }
        public DbSet<CustomerProfile> CustomerProfiles { get; set; }
        public DbSet<WatchlistEntry>  WatchlistEntries { get; set; }
        public DbSet<WatchlistHit>    WatchlistHits    { get; set; }
        public DbSet<MqFailureLog>    MqFailureLogs    { get; set; }
        public DbSet<SlaBreachLog>    SlaBreachLogs    { get; set; }

        protected override void OnModelCreating(DbModelBuilder modelBuilder)
        {
            // Disable EF's automatic pluralisation convention —
            // Data Annotations on each entity class control the table names.
            modelBuilder.Conventions.Remove<PluralizingTableNameConvention>();

            // Explicit decimal precision configuration for SQL Server.
            // Data Annotations alone do not configure SQL Server column precision.
            modelBuilder.Entity<Transaction>()
                .Property(t => t.TxnAmount)
                .HasPrecision(15, 2);

            modelBuilder.Entity<CustomerProfile>()
                .Property(p => p.AvgTxnAmount)
                .HasPrecision(15, 2);

            modelBuilder.Entity<CustomerProfile>()
                .Property(p => p.MaxTxnAmount)
                .HasPrecision(15, 2);

            modelBuilder.Entity<FraudAlert>()
                .Property(a => a.FraudScore)
                .HasPrecision(7, 4);
        }
    }
}
