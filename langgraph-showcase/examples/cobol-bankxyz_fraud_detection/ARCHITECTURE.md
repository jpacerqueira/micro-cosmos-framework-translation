# BankXYZ Fraud Detection — Architecture

## Bounded contexts

| Context              | Programs                                      | Responsibility                              |
|----------------------|-----------------------------------------------|---------------------------------------------|
| **TransactionEntry** | `FDTXNMON`, `FDRTCHK`                         | Entry points — batch and real-time          |
| **FraudScoring**     | `FDRULES`, `FDVELCHK`, `FDCUSTPF`, `FDWATCHL` | Five-signal composite risk scoring          |
| **AlertManagement**  | `FDALERT`, `FDNOTIFY`                         | Alert persistence and case team notification|
| **DeadCode**         | `FDARCHIVE`                                   | Isolated — no inbound calls                 |

## Call chains

### Batch flow (nightly)
```
JCL FDBATCH01
  └─ FDTXNMON
       ├─ FDRULES
       │    ├─ FDVELCHK   (velocity — SQL_IN_LOOP anti-pattern)
       │    ├─ FDCUSTPF   (profile — SQL_IN_LOOP anti-pattern)
       │    └─ FDWATCHL   (sanctions — dead VSAM path)
       └─ FDALERT
            └─ FDNOTIFY   (MQ put — JSON string concatenation)
```

### Real-time flow (per card authorisation)
```
CAAUTH (card authorisation)
  └─ FDRTCHK
       ├─ FDRULES          (same scoring engine as batch)
       │    ├─ FDVELCHK
       │    ├─ FDCUSTPF    (skipped for chip+PIN — BAU-2021-09)
       │    └─ FDWATCHL
       └─ FDALERT          (only if score >= REVIEW threshold 0.75)
            └─ FDNOTIFY
```

## Data flow

```
Card / ATM / Online
      │
      ▼
FDDB.TXN_QUEUE (status='P')
      │
      ├──── Real-time ────▶ FDRTCHK ──▶ APPROVE / DECLINE / REVIEW
      │                                         │
      └──── Batch (02:00) ▶ FDTXNMON            │
                                │               ▼
                                ▼         FDDB.FRAUD_ALERTS
                           FDRULES              │
                           (5 signals)          ▼
                                │         FRAUD.ALERT.QUEUE (IBM MQ)
                                ▼               │
                          score >= 0.75         ▼
                                │         CASEDB (case management)
                                ▼
                           FDALERT
```

## Key business invariants

1. Any OFAC or PEP hit → score forced to 1.0000, immediate escalation
2. Frozen or closed accounts → score forced to 1.0000
3. Real-time SLA breach (>180ms) → default to APPROVE (BRD-2009-FD-004)
4. Chip+PIN skips customer-profile check to meet 180ms SLA (BAU-2021-09)
5. Fraud score threshold: 0.7500 (REVIEW/ALERT), 0.9000 (DECLINE in real-time)
6. All SYNCPOINT and ROLLBACK pairs must be symmetrical

## Migration challenges for the target platform

### High risk
- **Decimal precision:** All monetary fields use COMP-3 packed decimal.
  Target must use `BigDecimal` (Java) or `decimal.Decimal` (Python).
  IEEE-754 float is not acceptable.
- **State machine:** Account status (`A`, `F`, `C`) and alert status
  (`PENDING`, `REVIEWED`, `CLOSED`, `ESCALATED`) must be preserved as
  explicit state machines in the target — not plain strings.
- **SYNCPOINT semantics:** Db2 + MQ writes in `FDALERT` are wrapped in
  a single CICS UOW. Target must replicate this with a distributed
  transaction or outbox pattern.

### Medium risk
- **SLA contract:** The 180ms real-time SLA is a hard business constraint.
  The N+1 patterns in `FDVELCHK` and `FDCUSTPF` must be resolved before
  migration or the SLA will be worse on the target platform.
- **Watchlist screening:** OFAC/PEP feeds are delivered as Db2 batch loads.
  Target integration with the feed mechanism must be agreed with Compliance.
- **MQ message format:** `FDNOTIFY` builds JSON by string concatenation.
  Target must use a proper serialiser but the field names must remain
  identical — CASEDB parses the existing format.

### Low risk
- **Scoring weights:** All five weights are constants in `FDCOMMON.cpy`.
  Externalise to configuration in the target rather than recompiling.
- **Batch scheduling:** FDBATCH01/02/03 JCL can be replaced with any
  scheduler (Cloud Scheduler, Airflow, etc.) with equivalent dependencies.
