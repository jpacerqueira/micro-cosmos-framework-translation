# COBOL Mainframe Banking (example)

A COBOL/DB2/CICS mainframe banking backend used as a legacy source estate for
modernisation demos. It models the teller-facing core of a retail bank: account
inquiry, deposit, withdrawal, and funds transfer, with an IBM WebSphere MQ bridge
that emits events to downstream REST API consumers (teller screen UIs).

```bash
micro-cosmos run examples/cobol-mainframe-banking --source-lang cobol --target-lang java
# or
micro-cosmos run examples/cobol-mainframe-banking --source-lang cobol --target-lang kotlin
micro-cosmos run examples/cobol-mainframe-banking --source-lang cobol --target-lang python
```

## Bounded contexts the Cartographer will identify

| Context         | Source file    | Responsibility                                        |
|-----------------|----------------|-------------------------------------------------------|
| TellerMenu      | BKTLRMN.cbl    | CICS entry point, BMS screen routing, teller signon   |
| Account         | BKACCT.cbl     | Account inquiry and balance reads from DB2            |
| Transaction     | BKTRXN.cbl     | Deposit / withdrawal / transfer with SYNCPOINT        |
| MqBridge        | BKMQBRDG.cbl   | IBM MQ put/get adapter for REST teller notification   |
| Audit           | BKAUDIT.cbl    | Audit trail writes to DB2 and legacy VSAM KSDS        |

## Technical stack

- **Runtime** — IBM z/OS, CICS Transaction Server 5.6
- **Database** — IBM Db2 for z/OS (embedded SQL, static bind plan `BKPLAN01`)
- **Messaging** — IBM WebSphere MQ 9.3 (`BKQM01` queue manager)
- **Language** — COBOL/370 fixed-format, copybooks via `COPY BKCOMMON`
- **Schema** — `BANKDB.sql` contains DDL for all four Db2 tables

## Known modernisation challenges for the pipeline

- `BKTRXN.cbl` contains an SQL query inside a `PERFORM UNTIL` loop (N+1 pattern)
- `BKACCT.cbl` uses a `REDEFINES` overlay for the balance field — precision must be
  preserved in the target language's decimal type
- `BKMQBRDG.cbl` builds JSON by string concatenation into a fixed-length buffer
- `BKAUDIT.cbl` writes to both DB2 and a VSAM KSDS flat file; the VSAM path is
  dead code that was never removed after the 2019 DB2 audit-log migration
- Business invariants are scattered across three programs — the Architect agent
  must consolidate them into a single domain-model layer
