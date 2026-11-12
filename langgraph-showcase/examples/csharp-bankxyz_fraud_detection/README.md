# BankXYZ Fraud Detection — C# .NET Framework 4.0

A contemporary **2010-era enterprise .NET application** implementing a real-time and batch fraud detection system for BankXYZ payment transactions. This is a direct C# equivalent of the Java 8 Spring Boot implementation, using the technology stack that a large UK bank would have deployed on Windows Server in 2010.

---

## Technology Stack

| Layer | Java (original) | C# (this project) |
|---|---|---|
| Language | Java 8 | C# 4.0 |
| Runtime | JVM 8 | .NET Framework 4.0 |
| Web framework | Spring Boot 2 / Spring MVC | ASP.NET MVC 3 |
| Persistence | Spring Data JPA / Hibernate | Entity Framework 4.1 (DbContext API, Code First) |
| IoC container | Spring IoC | Unity 2.1 |
| JSON | Jackson | Newtonsoft.Json 4.0 |
| Messaging | Spring JMS / ActiveMQ | System.Messaging (MSMQ) |
| Transactions | @Transactional | System.Transactions.TransactionScope |
| Scheduling | @Scheduled(cron) | System.Threading.Timer |
| Config | application.properties | web.config appSettings |
| Database | Oracle 12c | SQL Server 2008 R2 |
| DDL idioms | SEQUENCE / NUMBER | IDENTITY(1,1) / DECIMAL |
| Timing | System.currentTimeMillis | System.Diagnostics.Stopwatch |
| Container | Linux / OpenJDK Docker | Windows Server Core / IIS Docker |

---

## Quick Start

### Prerequisites

- **For SQL Server only (recommended for development):** Docker Desktop (any platform)
- **For full Docker deployment:** Windows host with Docker Desktop in Windows containers mode
- **For running the application:** Visual Studio 2010 or later / MSBuild

### 1. Start SQL Server

```bash
# Start SQL Server (Linux container — runs on all platforms)
docker compose up sqlserver

# Wait for the health check to pass (about 30 seconds)
docker compose ps
```

### 2. Create the database and schema

Connect to SQL Server and run the setup scripts:

```bash
# From the mssql/ directory:
docker exec -i <sqlserver_container_id> /opt/mssql-tools/bin/sqlcmd \
  -S localhost -U SA -P "Welcome1!Strong" \
  -Q "CREATE DATABASE FraudDetectionDb"

docker exec -i <sqlserver_container_id> /opt/mssql-tools/bin/sqlcmd \
  -S localhost -U SA -P "Welcome1!Strong" \
  -Q "CREATE LOGIN fdadmin WITH PASSWORD='changeme'; USE FraudDetectionDb; CREATE USER fdadmin FOR LOGIN fdadmin; EXEC sp_addrolemember 'db_owner', 'fdadmin'"

# Apply DDL and seed data
docker exec -i <sqlserver_container_id> /opt/mssql-tools/bin/sqlcmd \
  -S localhost -U fdadmin -P "changeme" \
  -d FraudDetectionDb \
  -i /path/to/mssql/install_all.sql
```

### 3. Run the application

Open `BankXYZ.FraudDetection.sln` in Visual Studio and press F5 (IIS Express), or:

```powershell
nuget restore BankXYZ.FraudDetection.sln
msbuild BankXYZ.FraudDetection.sln /p:Configuration=Debug
```

The application starts at `http://localhost:8080/` (or the IIS Express port).

### 4. Full Docker (Windows containers only)

```powershell
# Switch Docker Desktop to Windows containers mode, then:
docker compose up --build
```

> **Note:** Mixed-OS compose (Linux SQL Server + Windows app) is only supported on Windows hosts. On macOS/Linux, run SQL Server via Docker and the application from Visual Studio.

---

## Database Setup

All DDL is in the `mssql/` folder. Scripts must be run in order (01 through 10) as foreign keys depend on earlier tables. Use `install_all.sql` to run everything in sequence.

| Script | Creates |
|---|---|
| 01_account_master.sql | ACCOUNT_MASTER |
| 02_txn_queue.sql | TXN_QUEUE |
| 03_merchant_risk.sql | MERCHANT_RISK |
| 04_cust_profile.sql | CUST_PROFILE |
| 05_watchlist.sql | WATCHLIST |
| 06_watchlist_hits.sql | WATCHLIST_HITS |
| 07_fraud_alerts.sql | FRAUD_ALERTS |
| 08_mq_failure_log.sql | MQ_FAILURE_LOG |
| 09_sla_breach_log.sql | SLA_BREACH_LOG |
| 10_seed_data.sql | Reference and test data |

---

## Configuration

All parameters are in `Web.config` under `<appSettings>`:

| Key | Default | Description |
|---|---|---|
| fraud.scoring.scoreThreshold | 0.75 | Minimum score to raise a review alert |
| fraud.scoring.declineThreshold | 0.90 | Minimum score to decline the transaction |
| fraud.scoring.highAmountLimit | 5000.00 | Amount (GBP) triggering HIGH amount signal |
| fraud.scoring.medAmountLimit | 1000.00 | Amount (GBP) triggering MED amount signal |
| fraud.scoring.lowAmountLimit | 200.00 | Amount (GBP) triggering LOW amount signal |
| fraud.scoring.velocityLimitBatch | 10 | Expected max 24h transactions (batch) |
| fraud.scoring.velocityLimitRealtime | 5 | Expected max 24h transactions (real-time) |
| fraud.scoring.weightAmount | 0.25 | Weight of amount signal |
| fraud.scoring.weightMerchant | 0.25 | Weight of merchant signal |
| fraud.scoring.weightVelocity | 0.20 | Weight of velocity signal |
| fraud.scoring.weightProfile | 0.20 | Weight of profile signal |
| fraud.scoring.weightWatchlist | 0.10 | Weight of watchlist signal |
| fraud.scoring.slaLimitMs | 180 | SLA limit in milliseconds |
| fraud.batch.maxTransactions | 500 | Max transactions per batch run |
| fraud.mq.alertQueuePath | .\Private$\FraudAlertQueue | MSMQ queue path |

---

## API Examples

### Scenario 1 — Low-risk ChipPin (APPROVE)

```bash
curl -s -X POST http://localhost:8080/api/v1/authorise \
  -H "Content-Type: application/json" \
  -d '{
    "txnId": "TXN0000000000001",
    "acctNo": "ACC0000001",
    "txnAmount": 49.99,
    "merchantCode": "MCH00001",
    "channel": "CHIPPIN",
    "txnCountry": "GBR",
    "cardType": "VI",
    "cnpFlag": false
  }'
```

Response: `{"decision":"APPROVE","returnCode":"00","fraudScore":0.1000,...}`

### Scenario 2 — High-value CNP in unusual country (DECLINE)

```bash
curl -s -X POST http://localhost:8080/api/v1/authorise \
  -H "Content-Type: application/json" \
  -d '{
    "txnId": "TXN0000000000002",
    "acctNo": "ACC0000002",
    "txnAmount": 7500.00,
    "merchantCode": "MCH00002",
    "channel": "ONLINE",
    "txnCountry": "USA",
    "cardType": "MC",
    "cnpFlag": true
  }'
```

Response: `{"decision":"DECLINE","returnCode":"10","fraudScore":0.9500,...}`

### Scenario 3 — Frozen account (score 1.0)

```bash
curl -s -X POST http://localhost:8080/api/v1/authorise \
  -H "Content-Type: application/json" \
  -d '{
    "txnId": "TXN0000000000003",
    "acctNo": "FROZENACCT",
    "txnAmount": 10.00,
    "merchantCode": "MCH00001",
    "channel": "ATM",
    "txnCountry": "GBR",
    "cardType": "VI",
    "cnpFlag": false
  }'
```

Response: `{"decision":"DECLINE","returnCode":"10","fraudScore":1.0000,...}`

### Scenario 4 — Blocked merchant (score 1.0)

```bash
curl -s -X POST http://localhost:8080/api/v1/authorise \
  -H "Content-Type: application/json" \
  -d '{
    "txnId": "TXN0000000000004",
    "acctNo": "ACC0000001",
    "txnAmount": 50.00,
    "merchantCode": "MCH00003",
    "channel": "ONLINE",
    "txnCountry": "GBR",
    "cardType": "VI",
    "cnpFlag": false
  }'
```

Response: `{"decision":"DECLINE","returnCode":"10","fraudScore":1.0000,...}`

### Scenario 5 — Internal watchlist hit (Bob Wilson, REVIEW)

```bash
curl -s -X POST http://localhost:8080/api/v1/authorise \
  -H "Content-Type: application/json" \
  -d '{
    "txnId": "TXN0000000000005",
    "acctNo": "ACC0000003",
    "txnAmount": 80.00,
    "merchantCode": "MCH00001",
    "channel": "ATM",
    "txnCountry": "GBR",
    "cardType": "MC",
    "cnpFlag": false
  }'
```

Response: `{"decision":"REVIEW","returnCode":"20","fraudScore":0.8000,...}`

### Scenario 6 — Run batch manually

```bash
curl -s -X POST http://localhost:8080/api/v1/batch/run
```

Response: `{"message":"Batch complete: 0 processed, 0 alerts raised in 3ms"}`

---

## Running the Batch Manually

The batch processor normally fires at **02:00 local time** daily via `System.Threading.Timer` (configured in `FraudBatchScheduler`). To trigger it on-demand:

```bash
curl -X POST http://localhost:8080/api/v1/batch/run
```

Or from SSMS, insert a pending transaction then call the endpoint:

```sql
INSERT INTO dbo.TXN_QUEUE (TXN_ID, ACCT_NO, TXN_AMOUNT, MERCHANT_CODE, CHANNEL, TXN_COUNTRY, CNP_FLAG, TXN_STATUS, TXN_TS)
VALUES ('TESTBATCH00001', 'ACC0000001', 250.00, 'MCH00002', 'ONLINE', 'GBR', 'N', 'P', GETDATE());
```

---

## Fraud Scoring Model

```
composite = (amountScore  * weightAmount)
          + (merchantScore * weightMerchant)
          + (velocityScore * weightVelocity)
          + (profileScore  * weightProfile)
          + (watchlistScore * weightWatchlist)
```

Score is clamped to [0, 1] and rounded to 4 decimal places (MidpointRounding.AwayFromZero).

### Amount Signal

| Transaction Amount | Signal |
|---|---|
| >= £5,000 | 0.80 |
| >= £1,000 | 0.50 |
| >= £200 | 0.30 |
| < £200 | 0.10 |

### Merchant Risk Signal

| Merchant Status | Signal |
|---|---|
| BLOCKED | 1.00 |
| HIGH risk band | 0.80 |
| MED risk band | 0.40 |
| LOW risk band | 0.10 |
| Unknown | 0.00 |

### Velocity Signal

`min(txn_count_24h / velocityLimit, 1.0)`

### Profile Deviation Signal

| Anomaly | Score |
|---|---|
| Amount > 3x customer average | +0.30 |
| Amount 1.5–3x customer average | +0.15 |
| Amount exceeds customer maximum | +0.20 |
| Different country from usual | +0.20 |
| Outside usual hour window | +0.15 |
| Card-not-present | +0.10 |

### Watchlist Signal

| List | Score |
|---|---|
| OFAC match | 1.00 (ESCALATED) |
| PEP match | 1.00 (ESCALATED) |
| INTERNAL match | 0.80 |
| No match | 0.00 |

### ChipPin Override

For CHIPPIN channel transactions, the profile weight is zeroed and redistributed:

| Factor | Default | ChipPin |
|---|---|---|
| Amount | 0.25 | 0.25 |
| Merchant | 0.25 | 0.25 |
| Velocity | 0.20 | 0.25 |
| Profile | 0.20 | 0.00 |
| Watchlist | 0.10 | 0.25 |

---

## Key .NET vs Java Differences

| Concern | Java | C# (.NET 4.0) |
|---|---|---|
| Money type | BigDecimal | decimal |
| Rounding | RoundingMode.HALF_UP | MidpointRounding.AwayFromZero |
| DB transactions | @Transactional | TransactionScope |
| Scheduling | @Scheduled(cron) | System.Threading.Timer |
| Messaging | Spring JMS / ActiveMQ | System.Messaging (MSMQ) |
| IoC | Spring ApplicationContext | Unity 2.1 IUnityContainer |
| ORM | Spring Data JPA / Hibernate | EF 4.1 DbContext / Code First |
| Config | application.properties | web.config appSettings / ConfigurationManager |
| JSON | Jackson + @JsonProperty | Newtonsoft.Json + [JsonProperty] |
| HTTP | @RestController | Controller + JsonResult |
| Timing | System.currentTimeMillis | Stopwatch.ElapsedMilliseconds |
| DB sequences | Oracle SEQUENCE | SQL Server IDENTITY(1,1) |
| Annotations | @Entity, @Column | [Table], [Column] EF Data Annotations |

---

## MSMQ Note

MSMQ (`System.Messaging`) is a Windows-only component installed as a Windows Feature. In the Docker container this is available on Windows Server Core. On a development machine you may need to enable it:

```powershell
# Windows 10/11
Enable-WindowsOptionalFeature -Online -FeatureName MSMQ-Container

# Windows Server
Install-WindowsFeature MSMQ-Server
```

If MSMQ is unavailable (e.g. development on non-Windows), the `MqNotificationService.Notify()` method catches the `MessageQueueException` and writes a record to `MQ_FAILURE_LOG`. The application continues normally — MQ delivery is non-fatal by design.
