# BankXYZ Fraud Detection — Architecture (C# .NET Framework 4.0)

## 1. Technology Stack

| Component | Technology | Version |
|---|---|---|
| Language | C# | 4.0 |
| Runtime | .NET Framework | 4.0 |
| Web framework | ASP.NET MVC | 3.0 |
| ORM | Entity Framework (DbContext API) | 4.1 |
| IoC container | Unity | 2.1 |
| JSON | Newtonsoft.Json | 4.0 |
| Messaging | System.Messaging (MSMQ) | Windows built-in |
| Transactions | System.Transactions.TransactionScope | .NET Framework |
| Scheduling | System.Threading.Timer | .NET Framework |
| Configuration | System.Configuration.ConfigurationManager | .NET Framework |
| Timing | System.Diagnostics.Stopwatch | .NET Framework |
| Database | SQL Server | 2008 R2 |
| Container (app) | Windows Server Core / IIS | LTSC 2019 |
| Container (DB) | Linux / SQL Server | 2019 |

---

## 2. Bounded Contexts

The system is decomposed into three bounded contexts, implemented as namespaces within the single Web project:

### Context 1: Fraud Scoring Engine (`Services/`)

Responsible for evaluating transaction risk. Orchestrated by `FraudRulesService`, which composes five sub-signals:

- **VelocityCheckService** — 24-hour transaction frequency (CICS-era velocity check)
- **CustomerProfileService** — behavioural anomaly detection (amount, country, time, CNP)
- **WatchlistService** — regulatory and internal screening (OFAC, PEP, INTERNAL)
- **AlertWriterService** — persistence of fraud alerts with TransactionScope
- **MqNotificationService** — async-style MSMQ notification for downstream systems

### Context 2: Batch Processing (`Batch/`, `Services/`)

`FraudBatchScheduler` uses `System.Threading.Timer` to invoke `TransactionMonitorService.ProcessBatch()` nightly at 02:00. The batch drains the TXN_QUEUE of pending transactions, scores each one, and writes alerts.

### Context 3: Real-time Authorisation (`Controllers/`)

`FraudController` exposes two endpoints:
- `POST /api/v1/authorise` — synchronous real-time scoring with SLA enforcement
- `POST /api/v1/batch/run` — on-demand batch trigger

---

## 3. Call Chains

### Real-time Authorisation

```
HTTP POST /api/v1/authorise (JSON body)
  FraudController.Authorise(FraudCheckRequest)
    Stopwatch.StartNew()
    FraudRulesService.Score(FraudCommArea, velocityLimitRealtime)
      FraudRulesService.InitialiseWeights()   // channel-specific weight overrides
      AccountRepository.FindById()            // validate account status
      FraudRulesService.ScoreAmount()         // amount signal
      MerchantRiskRepository.FindById()
      FraudRulesService.ScoreMerchant()       // merchant signal
      VelocityCheckService.CheckVelocity()    // velocity signal
        TransactionRepository.CountVelocity()
        TransactionRepository.SumVelocityAmount()
      CustomerProfileService.ScoreProfile()   // profile signal
        CustomerProfileRepository.FindById()
      WatchlistService.ScreenWatchlist()      // watchlist signal
        WatchlistRepository.CountOfacHits()
        WatchlistRepository.CountPepHits()
        WatchlistRepository.CountInternalHits()
        WatchlistHitRepository.Save()         // audit record if hit
      // composite score calculated
    Stopwatch.Stop()
    if (elapsedMs > slaLimitMs) -> SlaBreachLogRepository.Save(); return APPROVE
    if (score >= declineThreshold || >= scoreThreshold) ->
      AlertWriterService.WriteAlert(FraudCommArea)
        TransactionScope { FraudAlertRepository.Save() }
        MqNotificationService.Notify()        // MSMQ (non-fatal)
    return JsonResult(FraudCheckResponse)
```

### Batch Processing

```
FraudBatchScheduler (System.Threading.Timer, fires at 02:00 daily)
  TransactionMonitorService.ProcessBatch(maxTransactions)
    TransactionRepository.FindPending(maxRows)
    foreach pending Transaction:
      FraudRulesService.Score(FraudCommArea, velocityLimitBatch)
      if (FraudFlag) -> AlertWriterService.WriteAlert()
      TransactionRepository.StampProcessed()
```

---

## 4. Data Flow

```
Client
  |
  | HTTP POST (JSON)
  v
FraudController
  |
  | builds FraudCommArea
  v
FraudRulesService                          SQL Server
  |                                        ACCOUNT_MASTER
  |--AccountRepository.FindById()--------->MERCHANT_RISK
  |--MerchantRiskRepository.FindById()---->CUST_PROFILE
  |--VelocityCheckService                  TXN_QUEUE (count, sum)
  |--CustomerProfileService                WATCHLIST (screening)
  |--WatchlistService                      WATCHLIST_HITS (audit)
  |
  | composite score
  v
AlertWriterService
  |
  |--FraudAlertRepository.Save()---------> FRAUD_ALERTS (TransactionScope)
  |
  |--MqNotificationService.Notify()------> MSMQ .\Private$\FraudAlertQueue
                                            (on failure: MQ_FAILURE_LOG)
  |
  | SLA breach path only:
  |--SlaBreachLogRepository.Save()-------> SLA_BREACH_LOG
  |
  v
FraudCheckResponse (JSON)
```

---

## 5. Project Structure (Namespace Tree)

```
BankXYZ.FraudDetection                   (root namespace)
  .Domain
      AccountStatus                       enum + static helper (IsInactive, FromCode)
      AlertStatus                         enum
      AuthDecision                        enum + static helper (GetReturnCode)
      Channel                             enum + static helper (IsChipPin, FromString)
      RiskBand                            enum + static helper (FromString)
  .Entities                              (EF Code First, Data Annotations)
      Account                             -> ACCOUNT_MASTER
      Transaction                         -> TXN_QUEUE
      MerchantRisk                        -> MERCHANT_RISK
      FraudAlert                          -> FRAUD_ALERTS
      CustomerProfile                     -> CUST_PROFILE
      WatchlistEntry                      -> WATCHLIST
      WatchlistHit                        -> WATCHLIST_HITS
      MqFailureLog                        -> MQ_FAILURE_LOG
      SlaBreachLog                        -> SLA_BREACH_LOG
  .Data
      FraudDbContext                      EF 4.1 DbContext, name=FraudDb
      .Repositories
          I*Repository / *Repository      one interface + implementation per entity
  .Config
      FraudScoringSettings               ConfigurationManager.AppSettings wrapper
  .Services
      FraudCommArea                       COMMAREA-style request/response DTO
      IFraudRulesService / FraudRulesService
      IVelocityCheckService / VelocityCheckService
      ICustomerProfileService / CustomerProfileService
      IWatchlistService / WatchlistService
      IAlertWriterService / AlertWriterService
      IMqNotificationService / MqNotificationService
      ITransactionMonitorService / TransactionMonitorService
  .Batch
      FraudBatchScheduler                System.Threading.Timer wrapper
  .Controllers
      FraudController                    ASP.NET MVC 3 JsonResult endpoints
  .Models
      FraudCheckRequest                  JSON request DTO
      FraudCheckResponse                 JSON response DTO
```

---

## 6. SOA Service Pattern — FraudCommArea

The service chain uses a **COMMAREA** (Communications Area) pattern, taken from mainframe CICS programming. A single `FraudCommArea` object is created per transaction and passed between services:

```
FraudCommArea commArea = new FraudCommArea();
commArea.TxnId     = "TXN0000000000001";
commArea.AcctNo    = "ACC0000001";
commArea.TxnAmount = 249.99m;
// ... set other inputs

_fraudRulesService.Score(commArea, velocityLimit);

// After Score():
// commArea.FraudScore    = 0.3750 (composite)
// commArea.FraudFlag     = false
// commArea.VelocityScore = 0.2000
// commArea.ProfileScore  = 0.1500
// commArea.WatchlistScore = 0.0000
// commArea.AlertStatus   = "PENDING"
// commArea.CustFullName  = "John Smith"
```

This avoids method parameter explosion and mirrors how the Java version passes `FraudCommArea` between `@Service` beans. The object is not thread-safe and must not be shared across requests.

---

## 7. Fraud Scoring Model

### Composite Formula

```
score = (amountScore  × WeightAmount)
      + (merchantScore × WeightMerchant)
      + (velocityScore × WeightVelocity)
      + (profileScore  × WeightProfile)
      + (watchlistScore × WeightWatchlist)

score = min(score, 1.0)
score = Math.Round(score, 4, MidpointRounding.AwayFromZero)
```

### Default Weights (configurable via web.config)

| Signal | Weight | Notes |
|---|---|---|
| Amount | 0.25 | Overridden to 0.25 for ChipPin |
| Merchant | 0.25 | Overridden to 0.25 for ChipPin |
| Velocity | 0.20 | Overridden to 0.25 for ChipPin |
| Profile | 0.20 | Zeroed to 0.00 for ChipPin |
| Watchlist | 0.10 | Overridden to 0.25 for ChipPin |

### Short-circuit Conditions

1. **Inactive account** (Frozen/Closed): score = 1.0, ESCALATED, return immediately
2. **OFAC or PEP watchlist match**: score = 1.0, ESCALATED, return immediately
3. **Blocked merchant**: merchantScore = 1.0 (feeds into composite — may not max out alone)
4. **SLA breach** (elapsedMs > 180): APPROVE regardless of score (BRD-2009-FD-004)

---

## 8. Business Invariants

1. Frozen and Closed accounts are automatically fraud-flagged at score 1.0 — no scoring required.
2. A blocked merchant scores 1.0 on the merchant signal; with 0.25 weight, this alone caps at 0.25 unless other signals are also elevated.
3. OFAC and PEP watchlist matches always escalate — no composite calculation.
4. INTERNAL watchlist matches add 0.8 to the watchlist signal but do not skip composite scoring.
5. ChipPin transactions never use the profile signal (physically present card, chip-verified PIN).
6. The composite score is clamped to [0, 1] before decision mapping.
7. SLA breaches result in APPROVE — availability takes precedence over fraud detection (BRD-2009-FD-004).
8. MQ notification failures are non-fatal — logged to MQ_FAILURE_LOG, never thrown to the caller.
9. All monetary values use `decimal` (never `float` or `double`) with 4 decimal place precision.

---

## 9. Transactional Model

### Real-time Path

`AlertWriterService.WriteAlert()` wraps the `FraudAlertRepository.Save()` call in a `System.Transactions.TransactionScope` (equivalent of Spring's `@Transactional`):

```csharp
using (TransactionScope scope = new TransactionScope())
{
    _alertRepo.Save(alert);
    commArea.AlertId = alert.AlertId;
    scope.Complete();  // commits on scope exit
}
// MQ notification is OUTSIDE the scope — MQ failure does not roll back the DB write
_mqNotificationService.Notify(commArea);
```

### WatchlistHit Writes

`WatchlistService.LogHit()` writes audit records outside any transaction scope. Watchlist hit records are best-effort audit logs.

### Batch Path

Each transaction in the batch is processed in a separate unit of work — no outer transaction wraps the full batch. Alert writes use their own `TransactionScope`. If a single transaction fails, the batch continues.

### EF SaveChanges

Each repository `Save()` method calls `_db.SaveChanges()` immediately. The `FraudDbContext` is Unity-scoped per HTTP request (`HierarchicalLifetimeManager`), ensuring a single EF context per request with consistent identity-map tracking.

---

## 10. SQL Server Database Design

### Key Design Decisions vs Oracle

| Oracle (Java) | SQL Server (C#) |
|---|---|
| SEQUENCE + NEXTVAL | IDENTITY(1,1) |
| NUMBER(15,2) | DECIMAL(15,2) |
| VARCHAR2 | NVARCHAR (Unicode names), VARCHAR (codes) |
| CHAR | CHAR (fixed-length codes) |
| DATE | DATETIME |
| SYSDATE | GETDATE() |
| NLS_UPPER() | UPPER() / ToUpper() in LINQ |

### Table Structure

```
ACCOUNT_MASTER (ACCT_NO PK)
  CUST_PROFILE  (ACCT_NO PK)
  TXN_QUEUE     (TXN_ID PK, FK -> ACCOUNT_MASTER)
    FRAUD_ALERTS  (ALERT_ID IDENTITY PK, FK -> TXN_QUEUE)
    WATCHLIST_HITS (HIT_ID IDENTITY PK)
  WATCHLIST     (WATCHLIST_ID IDENTITY PK)
  MERCHANT_RISK (MERCHANT_CODE PK)
  MQ_FAILURE_LOG (FAIL_ID IDENTITY PK)
  SLA_BREACH_LOG (BREACH_ID IDENTITY PK)
```

### Indexes

| Table | Index | Columns |
|---|---|---|
| TXN_QUEUE | IX_TXN_STATUS | TXN_STATUS, TXN_TS |
| TXN_QUEUE | IX_TXN_ACCT | ACCT_NO, TXN_TS |
| WATCHLIST | IX_WL_TYPE_NAME | LIST_TYPE, LIST_STATUS INCLUDE(MATCH_NAME) |
| WATCHLIST | IX_WL_ACCT | MATCH_ACCT, LIST_TYPE, LIST_STATUS |
| WATCHLIST_HITS | IX_WL_HITS_ACCT | ACCT_NO, HIT_TS |
| WATCHLIST_HITS | IX_WL_HITS_TXN | TXN_ID |
| FRAUD_ALERTS | IX_ALERT_ACCT_STATUS | ACCT_NO, ALERT_STATUS, CREATED_TS |
| FRAUD_ALERTS | IX_ALERT_STATUS_TS | ALERT_STATUS, CREATED_TS |
| SLA_BREACH_LOG | IX_SLA_BREACH_TS | BREACH_TS |
| SLA_BREACH_LOG | IX_SLA_BREACH_ACCT | ACCT_NO, BREACH_TS |

---

## 11. Messaging — MSMQ (System.Messaging)

MSMQ (Microsoft Message Queuing) is the Windows equivalent of JMS/ActiveMQ used in the Java version.

### Queue

- Path: `.\Private$\FraudAlertQueue` (configurable via `fraud.mq.alertQueuePath`)
- Type: Private transactional queue
- Created automatically if it does not exist (`MessageQueue.Create(path)`)

### Message Format

JSON-serialised `AlertMessage` object (Newtonsoft.Json):

```json
{
  "alert_id": 42,
  "txn_id": "TXN0000000000001",
  "acct_no": "ACC0000001",
  "amount": 249.99,
  "score": 0.3750,
  "channel": "ONLINE",
  "country": "GBR",
  "status": "PENDING"
}
```

### Failure Handling

```
MqNotificationService.Notify()
  try {
    MessageQueue.Exists() / MessageQueue.Create()
    queue.Send(json)
  }
  catch (Exception ex) {
    MqFailureLog { TxnId, AcctNo, ReasonCode=ex.HResult, FailedTs }
    MqFailureLogRepository.Save()   // DB write — no exception propagated
  }
```

Consumers of the MSMQ queue are out-of-scope for this example. In production, a Windows Service would read the queue and trigger downstream actions (case management, notification emails, etc.).

---

## 12. API Reference

Both endpoints accept and return `application/json`.

### POST /api/v1/authorise

**Request:**

```json
{
  "txnId":        "TXN0000000000001",
  "acctNo":       "ACC0000001",
  "txnAmount":    249.99,
  "merchantCode": "MCH00001",
  "channel":      "ONLINE",
  "txnCountry":   "GBR",
  "cardType":     "VI",
  "cnpFlag":      false
}
```

**Response:**

```json
{
  "txnId":      "TXN0000000000001",
  "decision":   "APPROVE",
  "returnCode": "00",
  "fraudScore": 0.3000,
  "message":    "TRANSACTION APPROVED",
  "elapsedMs":  14
}
```

| Decision | Return Code | Condition |
|---|---|---|
| APPROVE | 00 | score < 0.75 |
| REVIEW | 20 | 0.75 <= score < 0.90 |
| DECLINE | 10 | score >= 0.90 |
| APPROVE | 00 | SLA breached (>180ms) — BRD-2009-FD-004 |

### POST /api/v1/batch/run

No request body. Triggers immediate batch processing of all pending TXN_QUEUE rows.

**Response:**

```json
{
  "message": "Batch complete: 47 processed, 3 alerts raised in 892ms"
}
```

---

## 13. Configuration Reference

All configuration is read at application startup by `FraudScoringSettings.FromConfiguration()`, which calls `ConfigurationManager.AppSettings`. The resulting `FraudScoringSettings` instance is registered as a Unity singleton.

Web.config `<appSettings>` keys:

```xml
<add key="fraud.scoring.scoreThreshold"       value="0.7500" />
<add key="fraud.scoring.declineThreshold"     value="0.9000" />
<add key="fraud.scoring.highAmountLimit"      value="5000.00" />
<add key="fraud.scoring.medAmountLimit"       value="1000.00" />
<add key="fraud.scoring.lowAmountLimit"       value="200.00" />
<add key="fraud.scoring.velocityLimitBatch"   value="10" />
<add key="fraud.scoring.velocityLimitRealtime" value="5" />
<add key="fraud.scoring.weightAmount"         value="0.2500" />
<add key="fraud.scoring.weightMerchant"       value="0.2500" />
<add key="fraud.scoring.weightVelocity"       value="0.2000" />
<add key="fraud.scoring.weightProfile"        value="0.2000" />
<add key="fraud.scoring.weightWatchlist"      value="0.1000" />
<add key="fraud.scoring.slaLimitMs"           value="180" />
<add key="fraud.batch.maxTransactions"        value="500" />
<add key="fraud.mq.alertQueuePath"            value=".\Private$\FraudAlertQueue" />
```

Connection string:

```xml
<add name="FraudDb"
     connectionString="Server=localhost,1433;Database=FraudDetectionDb;User Id=fdadmin;Password=changeme;MultipleActiveResultSets=False;"
     providerName="System.Data.SqlClient" />
```

The connection string can be overridden at runtime via the `FRAUD_DB_CONNECTION` environment variable (applied by the Docker entrypoint in the Dockerfile).
