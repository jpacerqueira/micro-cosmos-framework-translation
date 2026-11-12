# BankXYZ Fraud Detection — Architecture

Java 8 / Spring Boot real-time and batch fraud detection service for BankXYZ retail and commercial banking.

---

## 1. Technology stack

| Layer              | Technology                                        | Version    |
|--------------------|---------------------------------------------------|------------|
| Runtime            | Java 8 / JVM                                      | JDK 1.8+   |
| Web framework      | Spring Boot / Spring MVC                          | 2.7.x      |
| Persistence        | Spring Data JPA + Hibernate ORM                   | 5.6.x      |
| Database           | Oracle Database 10g                               | 10.2+      |
| JDBC driver        | Oracle JDBC (`ojdbc8` / `ojdbc14`)                | —          |
| ORM dialect        | `Oracle10gDialect`                                | —          |
| Messaging          | Spring JMS + ActiveMQ (IBM MQ-swappable)          | 5.x        |
| Batch              | Spring Batch                                      | 4.3.x      |
| Scheduler          | Spring `@Scheduled`                               | —          |
| JSON               | Jackson `MappingJackson2MessageConverter`         | 2.x        |
| Build              | Apache Maven                                      | 3.6+       |

---

## 2. Bounded contexts

| Context              | Classes                                                                                            | Responsibility                               |
|----------------------|----------------------------------------------------------------------------------------------------|----------------------------------------------|
| **TransactionEntry** | `RealtimeCheckController`, `TransactionMonitorService`, `FraudBatchJobConfig`                      | Entry points — real-time REST and nightly batch |
| **FraudScoring**     | `FraudRulesService`, `VelocityCheckService`, `CustomerProfileService`, `WatchlistService`          | Five-signal composite risk scoring           |
| **AlertManagement**  | `AlertWriterService`, `MqNotificationService`                                                      | Alert persistence and case team notification |

---

## 3. Call chains

### Real-time authorisation — `POST /api/v1/authorise`

```
RealtimeCheckController.authorise()      (180ms SLA enforced)
  │
  ├─ FraudRulesService.score()
  │    ├─ AccountRepository               validate account status
  │    ├─ MerchantRiskRepository          signal 2: merchant risk band
  │    ├─ VelocityCheckService            signal 3: 24-hour transaction count
  │    ├─ CustomerProfileService          signal 4: behaviour deviation
  │    │   └─ CustomerProfileRepository
  │    └─ WatchlistService               signal 5: OFAC / PEP / internal
  │        ├─ WatchlistRepository
  │        └─ WatchlistHitRepository     audit log every hit
  │
  ├─ SlaBreachLogRepository              (if elapsed > 180ms → APPROVE + log)
  │
  └─ AlertWriterService.writeAlert()     (if score ≥ 0.75)
       ├─ FraudAlertRepository           @Transactional DB write
       └─ MqNotificationService          JMS put to FRAUD.ALERT.QUEUE
            └─ MqFailureLogRepository    (on JMS failure — non-fatal)
```

### Nightly batch — `@Scheduled(cron="0 0 2 * * ?")`

```
FraudBatchJobConfig (Spring Batch Job: FRAUD-BATCH-JOB)
  └─ fraudScoringStep (Tasklet)
       └─ TransactionMonitorService.processBatch()
            ├─ TransactionRepository    reads TXN_STATUS='P' rows
            ├─ FraudRulesService.score()  (per transaction — same engine as real-time)
            ├─ AlertWriterService.writeAlert()  (if score ≥ 0.75)
            └─ TransactionRepository.stampProcessed()  sets status='S'
```

### Manual batch trigger — `POST /api/v1/batch/run`

```
RealtimeCheckController.triggerBatch()
  └─ JobLauncher.run(fraudBatchJob)
       └─ (same as nightly batch above)
```

---

## 4. Data flow

```
Card / ATM / Online
      │
      ▼
TXN_QUEUE (TXN_STATUS = 'P')
      │
      ├─── Real-time ──▶ POST /api/v1/authorise
      │                         │
      │                  FraudRulesService
      │                  (5 signals, composite score)
      │                         │
      │              score ≥ 0.90 ──▶ DECLINE
      │              score ≥ 0.75 ──▶ REVIEW  ──▶ FRAUD_ALERTS
      │              score < 0.75 ──▶ APPROVE       │
      │              SLA > 180ms  ──▶ APPROVE        │
      │                                              │
      └─── Batch (02:00) ──▶ TransactionMonitorService
                                   │
                            FraudRulesService
                            (5 signals)
                                   │
                             score ≥ 0.75 ──▶ FRAUD_ALERTS ──▶ FRAUD.ALERT.QUEUE
                                                                       │
                                                                  CASEDB consumer
```

---

## 5. Package structure

```
com.bankxyz.fraud
├── FraudDetectionApplication.java          Entry point (@SpringBootApplication)
│
├── config/
│   ├── FraudScoringProperties.java         Externalised scoring constants (@ConfigurationProperties)
│   └── JmsConfig.java                      JMS connection factory + message converter
│
├── domain/                                 Explicit state machine enums
│   ├── AccountStatus.java                  ACTIVE | FROZEN | CLOSED
│   ├── AlertStatus.java                    PENDING | REVIEWED | CLOSED | ESCALATED
│   ├── AuthDecision.java                   APPROVE | REVIEW | DECLINE
│   ├── Channel.java                        ATM | ONLINE | BRANCH | CHIPPIN
│   └── RiskBand.java                       HIGH | MED | LOW
│
├── entity/                                 JPA entities — 9 Oracle tables
│   ├── Account.java                        ACCOUNT_MASTER
│   ├── Transaction.java                    TXN_QUEUE
│   ├── MerchantRisk.java                   MERCHANT_RISK
│   ├── FraudAlert.java                     FRAUD_ALERTS  (FD_SEQ)
│   ├── CustomerProfile.java                CUST_PROFILE
│   ├── WatchlistEntry.java                 WATCHLIST
│   ├── WatchlistHit.java                   WATCHLIST_HITS
│   ├── MqFailureLog.java                   MQ_FAILURE_LOG
│   └── SlaBreachLog.java                   SLA_BREACH_LOG
│
├── repository/                             Spring Data JPA — 9 repositories
│   └── (one interface per entity)
│
├── service/
│   ├── FraudCommArea.java                  Shared data object passed between services (SOA RPC)
│   ├── FraudRulesService.java              5-signal composite scoring engine
│   ├── VelocityCheckService.java           Signal 3: 24-hour transaction velocity
│   ├── CustomerProfileService.java         Signal 4: customer behaviour deviation
│   ├── WatchlistService.java               Signal 5: OFAC / PEP / internal screening
│   ├── AlertWriterService.java             @Transactional alert DB write + MQ notification
│   ├── MqNotificationService.java          JMS put to FRAUD.ALERT.QUEUE
│   └── TransactionMonitorService.java      Batch driver — reads and scores pending transactions
│
├── batch/
│   └── FraudBatchJobConfig.java            Spring Batch Job + @Scheduled nightly trigger
│
└── web/
    ├── RealtimeCheckController.java        REST endpoint — real-time authorisation + batch trigger
    └── dto/
        ├── FraudCheckRequest.java          Inbound authorisation request
        └── FraudCheckResponse.java         Outbound authorisation response
```

---

## 6. SOA RPC service pattern

Each bounded service is a named, stateless Spring `@Service` bean with a well-defined interface. Services communicate by passing a mutable `FraudCommArea` object — a value object that holds all transaction data and scoring state for a single request lifecycle.

```java
// Caller builds the shared data object
FraudCommArea commArea = new FraudCommArea();
commArea.setTxnId("TXN0000000000001");
commArea.setAcctNo("ACC0000001");
commArea.setTxnAmount(new BigDecimal("2500.00"));
commArea.setChannel(Channel.ONLINE);

// Each service reads from and writes back to the same object
rulesService.score(commArea, velocityLimit);
// commArea.getFraudScore(), commArea.isFraudFlag() are now populated

if (commArea.isFraudFlag()) {
    alertService.writeAlert(commArea);
    // commArea.getAlertId() is now populated
}
```

`FraudCommArea` is not thread-shared — a new instance is created per request.

---

## 7. Fraud scoring model

### Composite score formula

```
composite = (amountScore    × weightAmount)
          + (merchantScore  × weightMerchant)
          + (velocityScore  × weightVelocity)
          + (profileScore   × weightProfile)
          + (watchlistScore × weightWatchlist)
```

All arithmetic uses `BigDecimal` with `HALF_UP` rounding. Score is capped at `1.0000`.

### Signal weights (configurable in `application.properties`)

| Signal              | Default weight | CHIPPIN weight | Service class              |
|---------------------|----------------|----------------|----------------------------|
| Transaction amount  | 0.25           | 0.25           | `FraudRulesService`        |
| Merchant risk band  | 0.25           | 0.25           | `FraudRulesService`        |
| 24-hour velocity    | 0.20           | 0.25           | `VelocityCheckService`     |
| Profile deviation   | 0.20           | **0.00**       | `CustomerProfileService`   |
| Watchlist hit       | 0.10           | 0.25           | `WatchlistService`         |
| **Total**           | **1.00**       | **1.00**       |                            |

CHIPPIN channel: profile weight zeroed, redistributed to other signals (BAU-2021-09).

### Amount signal bands

| Amount range | Score  | Property key                          |
|--------------|--------|---------------------------------------|
| ≥ £5,000     | 0.8000 | `fraud.scoring.high-amount-limit`     |
| ≥ £1,000     | 0.5000 | `fraud.scoring.med-amount-limit`      |
| ≥ £200       | 0.3000 | `fraud.scoring.low-amount-limit`      |
| < £200       | 0.1000 | —                                     |

### Merchant signal bands

| State       | Score  |
|-------------|--------|
| BLOCKED     | 1.0000 |
| HIGH        | 0.8000 |
| MED         | 0.4000 |
| LOW         | 0.1000 |
| Not found   | 0.0000 |

### Real-time decision thresholds

| Score range         | Decision | HTTP behaviour                             |
|---------------------|----------|--------------------------------------------|
| ≥ 0.90              | DECLINE  | Transaction blocked; alert written         |
| ≥ 0.75 and < 0.90   | REVIEW   | Transaction allowed; alert written         |
| < 0.75              | APPROVE  | Transaction allowed; no alert              |
| SLA > 180ms         | APPROVE  | Default — see business invariant §8.3      |

---

## 8. Business invariants

| # | Rule | Enforced in |
|---|------|-------------|
| 1 | OFAC or PEP watchlist hit → score = 1.0, immediate ESCALATE | `FraudRulesService.score()` |
| 2 | Account status FROZEN or CLOSED → score = 1.0, auto-flag | `FraudRulesService.score()` |
| 3 | Real-time response > 180ms → decision = APPROVE (BRD-2009-FD-004) | `RealtimeCheckController.authorise()` |
| 4 | CHIPPIN channel → profile signal weight = 0 (BAU-2021-09) | `FraudRulesService.initialiseWeights()` |
| 5 | Score ≥ 0.75 → fraud alert created | `TransactionMonitorService`, `RealtimeCheckController` |
| 6 | Score ≥ 0.90 → DECLINE in real-time path only | `RealtimeCheckController.mapDecision()` |
| 7 | All monetary values use `BigDecimal` — no `float` / `double` | Enforced throughout all entities and services |
| 8 | Alert DB write and MQ notification in one `@Transactional` scope | `AlertWriterService.writeAlert()` |
| 9 | MQ failure is non-fatal — logged to `MQ_FAILURE_LOG`, alert DB write stands | `MqNotificationService.notify()` |

---

## 9. Transactional model

```
AlertWriterService.writeAlert()  ← @Transactional

  1. FraudAlertRepository.save()   ← DB INSERT (Oracle, within transaction)
  2. MqNotificationService.notify() ← JMS send to FRAUD.ALERT.QUEUE

  On DB failure   → Spring rolls back the INSERT (alert not persisted)
  On JMS failure  → exception caught; MQ_FAILURE_LOG written; DB commit proceeds
```

For full XA atomicity (DB + JMS in a single distributed transaction), configure a JTA provider (Atomikos, Narayana) and replace `ActiveMQConnectionFactory` with an XA-capable factory. The service interfaces remain unchanged.

---

## 10. Oracle 10g database design

### Sequences and identity pattern

Oracle 10g does not support `IDENTITY` columns. All surrogate primary keys use a sequence + `BEFORE INSERT` trigger pattern.

| Table             | PK column      | Sequence         | Trigger                | JPA strategy               |
|-------------------|----------------|------------------|------------------------|----------------------------|
| `FRAUD_ALERTS`    | `ALERT_ID`     | `FD_SEQ`         | _(none — JPA direct)_  | `@SequenceGenerator`       |
| `WATCHLIST`       | `WATCHLIST_ID` | `WATCHLIST_SEQ`  | `TRG_WATCHLIST_ID`     | `@SequenceGenerator`       |
| `WATCHLIST_HITS`  | `HIT_ID`       | `WL_HITS_SEQ`    | `TRG_WL_HITS_ID`       | `@SequenceGenerator`       |
| `MQ_FAILURE_LOG`  | `FAIL_ID`      | `MQ_FAIL_SEQ`    | `TRG_MQ_FAIL_ID`       | `@SequenceGenerator`       |
| `SLA_BREACH_LOG`  | `BREACH_ID`    | `SLA_BREACH_SEQ` | `TRG_SLA_BREACH_ID`    | `@SequenceGenerator`       |

Tables with natural primary keys (`ACCOUNT_MASTER`, `TXN_QUEUE`, `MERCHANT_RISK`, `CUST_PROFILE`) require no sequence.

### Foreign key graph

```
ACCOUNT_MASTER
    └── TXN_QUEUE  (FK: ACCT_NO)
            └── FRAUD_ALERTS  (FK: TXN_ID)
```

`WATCHLIST`, `WATCHLIST_HITS`, `MQ_FAILURE_LOG`, `SLA_BREACH_LOG`, and `CUST_PROFILE` have no FK constraints (write-heavy or audit tables).

### Key indexes

| Index                  | Table             | Columns                          | Query it serves                          |
|------------------------|-------------------|----------------------------------|------------------------------------------|
| `IX_TXN_STATUS`        | `TXN_QUEUE`       | `TXN_STATUS, TXN_TS`             | Batch: fetch all `TXN_STATUS='P'` rows   |
| `IX_TXN_ACCT`          | `TXN_QUEUE`       | `ACCT_NO, TXN_TS`                | Velocity: 24-hour count per account      |
| `IX_WL_TYPE_NAME`      | `WATCHLIST`       | `LIST_TYPE, LIST_STATUS, MATCH_NAME` | OFAC / PEP name screening           |
| `IX_WL_ACCT`           | `WATCHLIST`       | `MATCH_ACCT, LIST_TYPE, LIST_STATUS` | Internal account-level screening    |
| `IX_ALERT_ACCT_STATUS` | `FRAUD_ALERTS`    | `ACCT_NO, ALERT_STATUS, CREATED_TS` | Case management: open alerts per account |
| `IX_SLA_BREACH_TS`     | `SLA_BREACH_LOG`  | `BREACH_TS`                      | SLA trend analysis by time range         |

---

## 11. Messaging — FRAUD.ALERT.QUEUE

### Queue configuration

| Property         | Value                   |
|------------------|-------------------------|
| Queue name       | `FRAUD.ALERT.QUEUE`     |
| Protocol (dev)   | ActiveMQ / `tcp://localhost:61616` |
| Protocol (prod)  | IBM MQ 9.x (see §11.2)  |
| Message format   | JSON (text message)     |
| Serialiser       | Jackson `MappingJackson2MessageConverter` |

### JSON message schema (`MqNotificationService.AlertMessage`)

```json
{
  "alert_id": 1001,
  "txn_id":   "TXN0000000000001",
  "acct_no":  "ACC0000001",
  "amount":   2500.00,
  "score":    0.8250,
  "channel":  "ONLINE",
  "country":  "GBR",
  "status":   "PENDING"
}
```

### Switch ActiveMQ → IBM MQ (production)

1. Replace in `pom.xml`:
   ```xml
   <dependency>
     <groupId>com.ibm.mq</groupId>
     <artifactId>mq-jms-spring-boot-starter</artifactId>
     <version>3.3.4</version>
   </dependency>
   ```
2. Replace `JmsConfig.connectionFactory()` with `MQConnectionFactory`.
3. Add to `application.properties`:
   ```properties
   ibm.mq.queueManager=FDQM01
   ibm.mq.channel=FRAUD.CHANNEL
   ibm.mq.connName=mq-host(1414)
   ibm.mq.user=mqadmin
   ibm.mq.password=changeme
   ```
`MqNotificationService` uses only `JmsTemplate` — no broker-specific code.

---

## 12. API reference

### `POST /api/v1/authorise`

Synchronous real-time fraud check. Must respond within 180ms.

**Request body**

```json
{
  "txnId":       "TXN0000000000001",
  "acctNo":      "ACC0000001",
  "txnAmount":   2500.00,
  "merchantCode":"MCH00001",
  "channel":     "ONLINE",
  "txnCountry":  "GBR",
  "cardType":    "DB",
  "cnpFlag":     false
}
```

**Response body**

```json
{
  "txnId":      "TXN0000000000001",
  "decision":   "APPROVE",
  "returnCode": "00",
  "fraudScore": 0.3250,
  "message":    "Transaction cleared",
  "elapsedMs":  45
}
```

`decision` values: `APPROVE` / `REVIEW` / `DECLINE`

### `POST /api/v1/batch/run`

Manually triggers the nightly batch job. Returns `200 OK` with `"Batch job submitted"` on success.

### `GET /actuator/health`

Spring Boot Actuator health endpoint. Includes DB and JMS connectivity status.

---

## 13. Configuration reference (`application.properties`)

| Property key                            | Default   | Description                                |
|-----------------------------------------|-----------|--------------------------------------------|
| `spring.datasource.url`                 | —         | Oracle JDBC URL `jdbc:oracle:thin:@host:1521:SID` |
| `spring.jpa.database-platform`         | —         | `org.hibernate.dialect.Oracle10gDialect`   |
| `fraud.scoring.score-threshold`         | `0.7500`  | Minimum score to create a fraud alert      |
| `fraud.scoring.decline-threshold`       | `0.9000`  | Minimum score to DECLINE in real-time      |
| `fraud.scoring.high-amount-limit`       | `5000.00` | Amount band — HIGH signal score (0.8)      |
| `fraud.scoring.med-amount-limit`        | `1000.00` | Amount band — MED signal score (0.5)       |
| `fraud.scoring.low-amount-limit`        | `200.00`  | Amount band — LOW signal score (0.3)       |
| `fraud.scoring.velocity-limit-batch`    | `10`      | Velocity limit for nightly batch           |
| `fraud.scoring.velocity-limit-realtime` | `5`       | Velocity limit for real-time (halved)      |
| `fraud.scoring.weight-amount`           | `0.2500`  | Signal 1 weight                            |
| `fraud.scoring.weight-merchant`         | `0.2500`  | Signal 2 weight                            |
| `fraud.scoring.weight-velocity`         | `0.2000`  | Signal 3 weight                            |
| `fraud.scoring.weight-profile`          | `0.2000`  | Signal 4 weight (0 for CHIPPIN)            |
| `fraud.scoring.weight-watchlist`        | `0.1000`  | Signal 5 weight                            |
| `fraud.scoring.sla-limit-ms`            | `180`     | Real-time SLA limit in milliseconds        |
| `fraud.batch.cron`                      | `0 0 2 * * ?` | Nightly batch schedule (02:00 daily)   |
| `fraud.batch.max-transactions`          | `500`     | Max transactions per batch run             |
| `fraud.mq.alert-queue`                  | `FRAUD.ALERT.QUEUE` | JMS destination name            |

---

## 14. Testing strategy

Two complementary layers, both run against the "test" Spring profile
(`src/test/resources/application-test.properties`): H2 in place of Oracle 10g
(schema generated from the JPA entity annotations, not from `oracle/*.sql`),
and an embedded in-VM ActiveMQ broker (`vm://test-broker`) in place of a real
one. Neither the Docker image build nor a plain `mvn test` needs the
`oracle` / `activemq` containers from `docker-compose.yml` to be running.

### 14.1 BDD / Cucumber — behaviour and invariants

One `.feature` file per bounded context, each traceable back to the
invariants in §7-§8 above:

| Feature file | Exercises |
|---|---|
| `fraud_scoring.feature` | `FraudRulesService` end to end — mandatory escalation (frozen/closed account, OFAC/PEP), amount-band composite arithmetic, CHIPPIN weight redistribution |
| `velocity_check.feature` | `VelocityCheckService` — 24h window, status filter (`P`/`S` only), cap at 1.0 |
| `customer_profile.feature` | `CustomerProfileService` — amount/geo/time-of-day deviation, CNP uplift |
| `watchlist_screening.feature` | `WatchlistService` — OFAC/PEP/internal hits, audit logging |
| `alert_management.feature` | `AlertWriterService` + `MqNotificationService` — the non-fatal MQ failure invariant (§8 rule 9), against the real embedded broker |
| `realtime_authorisation.feature` | `RealtimeCheckController` over real HTTP — decision mapping, SLA-breach default-to-approve, manual batch trigger |
| `batch_processing.feature` | `TransactionMonitorService` — empty window, mixed scoring/flagging, the max-transactions cap |

Step definitions (`src/test/java/com/bankxyz/fraud/steps/`) are wired as
Spring beans via `cucumber-spring` against one shared `@SpringBootTest`
context (`CucumberSpringConfiguration`); `Hooks` truncates every table and
resets test-only toggles before each scenario so scenarios stay independent
despite sharing that context and one H2 instance.

The `MqFailureSwitch` / `FailureInjectingJmsTemplate` pair in
`src/test/java/com/bankxyz/fraud/support/` lets a scenario say "the MQ broker
is unavailable" and get a real `JmsException` out of the real embedded
broker's `JmsTemplate`, without tearing down that broker for every other
scenario.

### 14.2 Unit tests — JUnit 5 + Mockito

Every service, the controller, and the domain enums also have an isolated
unit test class (`src/test/java/com/bankxyz/fraud/service|web|domain/`) with
every collaborator mocked. These cover branches that are impractical or
non-deterministic to reach through the BDD suite: `WatchlistService`'s
audit-log write failing, `MqNotificationService`'s own failure-log write
failing, the composite-score defensive cap (unreachable through real signal
scores, since the five weights sum to exactly 1.0 and every signal is itself
capped at 1.0), and `TransactionMonitorService` skipping a transaction that
throws mid-batch without aborting the rest.

Entities, DTOs, repository interfaces and `@Configuration` classes have no
dedicated unit tests — they carry no branching logic of their own, so a test
whose only assertion is "the getter returns what the setter set" doesn't pay
for its own upkeep. They still pick up incidental coverage from both test
layers above.

### 14.3 Coverage gate

`mvn verify` runs a Jacoco `check` (see `pom.xml`) that fails the build below
**90% line / 85% branch coverage** on `service`, `web` and `domain` — the
packages with actual logic to protect. The same `mvn clean verify` runs
inside the Docker image build stage (`Dockerfile`), so a regression fails
`docker build` / `docker compose up --build`, not just a separate CI step.

Run it locally with zero JDK/Maven install via
`docker compose run --rm tests` — see the [README](README.md#testing) for
report locations.
