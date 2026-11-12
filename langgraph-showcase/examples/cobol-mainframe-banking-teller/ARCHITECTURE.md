# Architecture — COBOL Mainframe Banking Estate

## What this application is

This is the **core banking backend** of a retail bank, running on IBM z/OS mainframe
hardware. It processes every transaction a branch teller initiates: deposits,
withdrawals, funds transfers, and account inquiries.

The system runs inside **CICS** (Customer Information Control System), IBM's
online transaction processing engine. CICS manages thousands of concurrent
teller sessions, enforces security, and schedules workloads across the mainframe.
Every operation is wrapped in a **Unit of Work (UOW)** and committed or rolled back
atomically using `EXEC CICS SYNCPOINT` — this is what guarantees that money is
never debited without being credited, and that the ledger is always consistent
even if the system crashes mid-transaction.

Account data and the transaction ledger live in **IBM Db2 for z/OS**, a relational
database accessed via embedded SQL (`EXEC SQL`) compiled into a static bind plan
(`BKPLAN01`). The bind plan pre-compiles every SQL statement at deploy time,
eliminating query-parse overhead at runtime and enabling Db2 to validate
access privileges without touching the SQL engine per transaction.

After a transaction commits, the system publishes a JSON notification to an
**IBM WebSphere MQ** queue (`TELLER.REQUEST.QUEUE`). An IBM z/OS Connect EE
process consumes that message and forwards it to a REST API served by the
teller screen front-end, so the browser UI refreshes the account balance in
near-real-time without polling.

---

## Runtime transaction flow

```
Branch teller presses a key on the BMS screen (deposit / withdraw / transfer / inquiry)
        │
        ▼
CICS receives the 4-byte TRANSID "BTLR" and loads BKTLRMN
        │
        ├─ validates teller signon
        ├─ reads BMS screen input (function key + account numbers + amount)
        │
        ├─[INQU]──────────► EXEC CICS LINK BKACCT  ──► Db2 SELECT (read-only)
        │
        ├─[DEPO/WITH/XFER]► EXEC CICS LINK BKTRXN  ──► Db2 SELECT FOR UPDATE
        │                                               Db2 UPDATE ACCOUNT_MASTER
        │                                               Db2 INSERT TRANSACTION_REGISTER
        │                                               EXEC CICS SYNCPOINT (commit)
        │                                               EXEC CICS LINK BKAUDIT
        │                                                   └──► Db2 INSERT AUDIT_LOG
        │
        └─[on success]────► EXEC CICS LINK BKMQBRDG ──► MQ PUT TELLER.REQUEST.QUEUE
                                                              │
                                                    IBM z/OS Connect EE
                                                              │
                                                    REST API (teller screen UI)
```

---

## Source files

### `BKCOMMON.cpy` — Shared copybook

Included via `COPY BKCOMMON` in every COBOL program. Defines:

- **`HV-ACCOUNT`** — Db2 host variable group for `ACCOUNT_MASTER`. Contains account
  number, type (CH/SV/LN), status (A/F/C), balance as `DECIMAL(15,2)` mapped to
  `PIC S9(13)V99 COMP-3`, overdraft limit, and daily withdrawal counters.
  The `HV-BALANCE-X REDEFINES HV-BALANCE` overlay exposes the raw packed-decimal
  bytes for legacy byte-copy operations — a modernisation risk noted by the reviewer.
- **`HV-TRANSACTION`** — Db2 host variables for `TRANSACTION_REGISTER`. Maps every
  column of an audit-quality transaction record including type codes with 88-level
  condition names (`HV-TXN-DEP`, `HV-TXN-WTH`, `HV-TXN-TRF`).
- **`HV-AUDIT`** — Db2 host variables for `AUDIT_LOG`.
- **`WS-COMMAREA`** — The CICS communication area passed between every LINK call.
  Carries function code, account numbers, amount, teller/branch IDs, return code
  (two-digit, with 88-levels for each business error), message text, and balance
  out/in fields. This is the only data bus between programs.
- **`WS-CONSTANTS`** — `WS-MAX-SINGLE-WD` (50 000.00 single withdrawal cap) and
  `WS-MIN-BALANCE` (0.00 floor without overdraft facility).
- **`WS-MQ-PARAMS`** — Queue manager name (`BKQM01`), request queue, and response
  queue names. Also holds the raw MQ connection and object handles.

---

### `BKTLRMN.cbl` — Teller Menu (CICS transaction `BTLR`)

**Role:** Front door. The only CICS transaction ID in the system. Every teller
session starts here and returns here after each operation.

**What it does:**
1. Assigns the terminal ID and captures a start timestamp via `EXEC CICS ASKTIME`.
2. Restores the COMMAREA from the previous invocation (stateful teller session)
   or initialises it from scratch on first entry.
3. Enforces teller signon: if `CA-TELLER-ID` is blank, it reads the teller badge
   ID from the terminal and validates it. In production this calls RACF; the
   example simplifies to a non-blank check.
4. Receives BMS screen input (function key 1–4 or 9, account numbers, amount).
5. Sets `CA-FUNCTION` in the COMMAREA and dispatches via `EXEC CICS LINK`:
   - Key `1` → `BKTRXN` with `CA-FUNCTION = DEPO`
   - Key `2` → `BKTRXN` with `CA-FUNCTION = WITH`
   - Key `3` → `BKTRXN` with `CA-FUNCTION = XFER`
   - Key `4` → `BKACCT` with `CA-FUNCTION = INQU`
   - Key `9` → clears `CA-TELLER-ID` and sends sign-off message
6. On success (`CA-OK`), links to `BKMQBRDG` for REST notification.
7. Issues `EXEC CICS RETURN TRANSID('BTLR')` to hand control back to the terminal,
   passing the COMMAREA so the next keypress resumes with full context.

**Dead code:** A VSAM KSDS teller-session log (`TELLERFL`) was commented out
when CICS was upgraded. The working-storage fields are still declared but
unreachable.

---

### `BKACCT.cbl` — Account Inquiry

**Role:** Read-only account lookup. Returns current balance, type, and status.

**What it does:**
1. Validates that `CA-ACCT-FROM` is not blank.
2. Issues a `SELECT … WITH UR` (uncommitted read) against `BANKDB.ACCOUNT_MASTER`.
   `WITH UR` avoids lock contention on a busy ledger table during inquiry.
3. Maps `SQLCODE` — `+100` (not found) returns `CA-RETURN-CODE = '05'`; any
   other non-zero code returns `'99'` (system error).
4. Formats a human-readable message into `CA-MESSAGE` describing account type,
   status, and the formatted balance (`ZZZ,ZZZ,ZZZ,ZZ9.99`).
5. Handles all three statuses: `ACTIVE` shows normal balance, `FROZEN` shows
   balance with frozen notice, `CLOSED` shows last-known balance.

**Modernisation note:** The `REDEFINES` overlay (`HV-BALANCE-X`) on the balance
host variable exposes the packed-decimal bytes as a raw string. Any target
language using a proper `BigDecimal` or `Decimal` type must not replicate this
pattern — it exists only because older batch jobs byte-copy the field directly.

---

### `BKTRXN.cbl` — Transaction Processor

**Role:** The transactional heart of the system. Handles all money movement.

**Business invariants enforced:**

| # | Invariant | Error code |
|---|-----------|------------|
| 1 | Amount must be > 0 | `99` |
| 2 | From-account must be provided | `05` |
| 3 | Account must be ACTIVE (`A`) | `02` (closed) / `03` (frozen) |
| 4 | Withdrawal ≤ `WS-MAX-SINGLE-WD` (50 000.00) | `04` |
| 5 | Withdrawal: today's total + amount ≤ `DAILY_WD_LIMIT` | `04` |
| 6 | Withdrawal: `BALANCE + OVERDRAFT_LIMIT ≥ amount` | `01` |
| 7 | Transfer: both accounts must be ACTIVE | `03` / `05` |
| 8 | Transfer: from ≠ to account | `99` |
| 9 | Transfer: `BALANCE ≥ amount` (no overdraft on transfers) | `01` |

**What it does — deposit:**
- Credits `BALANCE` in `ACCOUNT_MASTER` via `UPDATE`.
- Inserts a `DEPO` row into `TRANSACTION_REGISTER`.
- Issues `EXEC CICS SYNCPOINT` to commit both writes atomically.

**What it does — withdrawal:**
- Checks single-transaction and daily limits.
- Re-derives today's withdrawal total by querying `TRANSACTION_REGISTER`
  (`COUNT(*) / SUM(TXN_AMOUNT)`) — an **N+1 anti-pattern**; the `DAILY_WD_USED`
  column in `ACCOUNT_MASTER` is the correct authoritative value and should replace
  this loop during modernisation.
- Debits `BALANCE` and updates `DAILY_WD_USED` in a single `UPDATE`.
- Inserts a `WITH` row into `TRANSACTION_REGISTER`.
- Commits via `EXEC CICS SYNCPOINT`.

**What it does — transfer:**
- Locks both rows with `SELECT … FOR UPDATE`.
- Debits the source account, credits the destination account (two `UPDATE` calls).
- Both updates are in the same UOW — if the credit `UPDATE` fails the whole unit
  rolls back via `EXEC CICS SYNCPOINT ROLLBACK`, leaving neither account changed.
- Inserts a single `XFER` row referencing both accounts.
- Commits via `EXEC CICS SYNCPOINT`.

**On any Db2 error:** calls `ROLLBACK-AND-RETURN`, which issues
`EXEC CICS SYNCPOINT ROLLBACK` before returning to the caller.

---

### `BKMQBRDG.cbl` — IBM WebSphere MQ Bridge

**Role:** Fire-and-forget REST notification adapter. Decouples the core transaction
from the teller screen UI refresh.

**What it does:**
1. Fetches the current timestamp from Db2 (`VALUES(CHAR(CURRENT TIMESTAMP))`).
2. Builds a JSON payload using `STRING … INTO WS-MSG-BUFFER` — a fixed 2 048-byte
   character buffer. The message carries `txnRef`, `function`, `acctFrom`, `acctTo`,
   `amount`, `newBalance`, `tellerId`, `branchId`, `returnCode`, and `timestamp`.
3. Calls `EXEC CICS PUT CONTAINER('MQMESSAGE')` to hand the message to the
   CICS-MQ bridge, which puts it onto `TELLER.REQUEST.QUEUE` on queue manager
   `BKQM01`. The message is persistent (`MQPMO-OPTIONS = 8192`) and has
   `TELLER.RESPONSE.QUEUE` as the reply-to queue.
4. If the MQ put fails, writes a `MQ_PUT_FAILED` row to `AUDIT_LOG` and sets
   `CA-RETURN-CODE = '99'` — but `BKTLRMN` ignores a non-zero RESP from this
   LINK so the transaction already committed is never rolled back.

**Known anti-pattern:** JSON assembled by `STRING` concatenation into a fixed
buffer has two problems: special characters in `CA-MESSAGE` are not escaped
(JSON injection risk), and the buffer silently truncates messages longer than
2 048 bytes. A proper JSON serialiser must replace this.

---

### `BKAUDIT.cbl` — Audit Trail Writer

**Role:** Append-only audit record for every committed transaction.

**What it does:**
1. Captures `CA-BALANCE-OUT` (before) and `CA-NEW-BALANCE` (after) from the COMMAREA.
2. Fetches the current Db2 timestamp.
3. Obtains the next audit sequence number from `BANKDB.AUDIT_SEQ`.
4. Assembles a details string (`FUNC= FROM= TO= AMT= RC=`) via `STRING`.
5. Inserts one row into `BANKDB.AUDIT_LOG` with before/after balances, teller ID,
   event type (`TELLER_TXN`), and the full details string.
6. Runs inside the same CICS UOW as `BKTRXN` — an audit insert failure causes
   `BKTRXN` to roll back the entire transaction.

**Dead code — VSAM dual-write path:**
A second write path to a VSAM KSDS file (`BKAUDFL`) was the original audit store.
In Q3-2019 the bank migrated to Db2 as the single audit store and removed the
FCT entry for `BKAUDFL` from the CICS CSD. The paragraph `WRITE-VSAM-AUDIT` and
its associated working-storage (`WS-VSAM-AUDIT-REC`) were never deleted.
The `IF WS-WRITE-VSAM` guard can never be true because `WS-WRITE-SWITCH` is
always initialised to `'D'` and never modified — the paragraph is completely
unreachable. The Observer agent will flag it as dead code and the Writer agent
must not generate a VSAM adapter in the target language.

---

### `BANKDB.sql` — Db2 DDL

Defines the four tables, two sequences, and all indexes in schema `BANKDB`.

| Table | Purpose |
|---|---|
| `ACCOUNT_MASTER` | Single source of truth for every account — balance, limits, status |
| `TRANSACTION_REGISTER` | Immutable ledger row per committed transaction |
| `TELLER_SESSION` | Active and historical teller signon records |
| `AUDIT_LOG` | Append-only audit trail written by `BKAUDIT` |

Key design decisions visible in the DDL:

- `BALANCE DECIMAL(15,2)` — all monetary columns use exact decimal, never `FLOAT`.
  The `CHECK (BALANCE >= (OVERDRAFT_LIMIT * -1))` constraint enforces the overdraft
  floor at the database level as a backstop to the application-level guard in `BKTRXN`.
- `TRANSACTION_REGISTER.TXN_AMOUNT` has `CHECK (TXN_AMOUNT > 0)` — matches the
  application invariant that amount must be greater than zero.
- `TXN_SEQ` and `AUDIT_SEQ` are Db2 sequences with `CACHE 20`, avoiding a row-lock
  per sequence fetch under high concurrency.
- Seed data includes six accounts across three customers covering all account types
  (CH/SV/LN), all statuses (A/F/C), and an account with a non-zero overdraft limit —
  giving the pipeline enough variety to test all code paths.

---

## What the Alchemy pipeline produces

When you run `micro-cosmos run examples/cobol-mainframe-banking --target-lang java`
the pipeline executes five agents in sequence:

| Agent | Output |
|---|---|
| **Observer** | IR property graph of all COBOL programs — nodes for paragraphs, performs, SQL statements, copy members, dead code regions |
| **Cartographer** | Bounded context map: `TellerMenu`, `Account`, `Transaction`, `MqBridge`, `Audit` |
| **Pattern** | Domain model: `Account` aggregate with invariants, `Transaction` aggregate, `TellerSession` entity, ports for Db2 and MQ |
| **Architect** | TNAS (Target-language Node Architecture Specification): package layout, hexagonal ports, Db2 → Spring JDBC mapping, MQ → `JmsTemplate` mapping, `BigDecimal` for all monetary fields |
| **Code Writer + Reviewers** | Per-seam Java source files, unit tests, and a README — one seam at a time through the TDD loop |

The TDD loop (Code Writer → Skeptical Review → Test Review → Functional Review)
iterates per seam until all three reviewers pass or the run escalates to Gate 5
for human review.

Gate 5 presents the final PR diff — generated Java alongside the original COBOL —
for engagement-director sign-off before the output is written to disk.
