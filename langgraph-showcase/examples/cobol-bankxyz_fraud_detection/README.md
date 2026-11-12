# BankXYZ Fraud Detection — Legacy COBOL Estate

A COBOL/CICS/Db2 fraud detection system running on IBM z/OS. Handles both
real-time card authorisation screening and nightly batch transaction review
for BankXYZ retail and commercial banking.

## Quick start (Micro-Cosmos pipeline)

```bash
source-run run examples/bankxyz_fraud_detection \
  --source-lang cobol --target-lang java21
```

## Programs

| Program      | Type       | Role                                                    |
|--------------|------------|---------------------------------------------------------|
| `FDTXNMON`   | Batch      | Nightly batch driver — reads TXN_QUEUE, drives scoring |
| `FDRTCHK`    | Real-time  | Synchronous card authorisation check (180ms SLA)        |
| `FDRULES`    | Sub-program| Five-signal composite fraud scoring engine              |
| `FDVELCHK`   | Sub-program| 24-hour transaction velocity checker                    |
| `FDCUSTPF`   | Sub-program| Customer behaviour profile deviation scorer             |
| `FDWATCHL`   | Sub-program| OFAC / PEP / internal watchlist screener                |
| `FDALERT`    | Sub-program| Fraud alert writer — Db2 + MQ notification              |
| `FDNOTIFY`   | Sub-program| IBM MQ put to FRAUD.ALERT.QUEUE                         |
| `FDARCHIVE`  | Dead code  | Flat-file case archiver — replaced 2021, never removed  |
| `FDCOMMON`   | Copybook   | Shared working-storage included by all programs         |

## Fraud scoring signals

`FDRULES` combines five independent signals into a composite score (0.0–1.0):

| Signal             | Weight | Source program |
|--------------------|--------|----------------|
| Transaction amount | 25 %   | `FDRULES`      |
| Merchant risk band | 25 %   | `FDRULES`      |
| 24-hour velocity   | 20 %   | `FDVELCHK`     |
| Profile deviation  | 20 %   | `FDCUSTPF`     |
| Watchlist hit      | 10 %   | `FDWATCHL`     |

Score >= 0.75 → FRAUD_ALERTS row created + MQ notification sent.
Any OFAC or PEP watchlist hit → immediate escalation regardless of score.

## Two operating modes

**Batch (FDTXNMON):** Runs nightly at 02:00 via JCL job FDBATCH01. Processes
all transactions with status 'P' in FDDB.TXN_QUEUE. Catches fraud after the
fact — money may have already moved.

**Real-time (FDRTCHK):** Called synchronously during card authorisation via
EXEC CICS LINK from CAAUTH. Must respond within 180ms. If the SLA is
breached the decision defaults to APPROVE (BRD-2009-FD-004). Blocks fraud
at the point of transaction.

## Known modernisation challenges

- `FDVELCHK` — `GET-BULK-VELOCITY` issues one SQL per account instead of a
  single batch query (N+1). Causes SLA breaches during peak hours.
  Incident: INC-2023-4471.

- `FDCUSTPF` — `BUILD-PROFILE-FROM-HISTORY` recalculates the customer
  profile from raw history on every call instead of reading the
  pre-computed `FDDB.CUST_PROFILE` row. Change ref: CHG-2014-0047.

- `FDNOTIFY` — JSON payload is built by STRING concatenation into a
  fixed 512-byte buffer. No escaping. Silent truncation risk on long
  field values. Change ref: CHG-2019-0088.

- `FDRTCHK` — chip+PIN transactions skip the customer-profile check to
  meet the 180ms SLA. Profile deviation goes undetected for chip+PIN
  fraud. Risk accepted: BAU-2021-09.

- `FDARCHIVE` — no longer called by any program. Retained because the
  change-freeze approval to remove it was never filed.

- Business invariants (daily limits, velocity thresholds, scoring weights)
  are scattered across `FDRULES`, `FDVELCHK`, `FDRTCHK`, and `FDCOMMON`.
  No single source of truth for fraud policy parameters.

## Technical stack

- **Runtime:** IBM z/OS 2.5, CICS Transaction Server 6.1
- **Database:** IBM Db2 for z/OS 13 (embedded SQL, bind plan `FDPLAN01`)
- **Messaging:** IBM MQ 9.3 (queue manager `FDQM01`)
- **Language:** COBOL/370 fixed-format, shared copybook via `COPY FDCOMMON`
- **Schema:** `FDDB.sql` — DDL for all tables and sequences
