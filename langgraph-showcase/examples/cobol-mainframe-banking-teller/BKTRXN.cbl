       IDENTIFICATION DIVISION.
       PROGRAM-ID. BKTRXN.
      *----------------------------------------------------------------*
      * BANKING TRANSACTION PROCESSOR                                   *
      * Called via EXEC CICS LINK from BKTLRMN.                       *
      * Handles: DEPO (deposit), WITH (withdrawal), XFER (transfer).  *
      *                                                                 *
      * Business invariants:                                            *
      *   - Transaction amount must be > 0.00                          *
      *   - Account must be ACTIVE ('A') for any debit or credit      *
      *   - Withdrawal: resulting balance must be >= 0 (no overdraft   *
      *     unless overdraft_limit covers the shortfall)               *
      *   - Withdrawal: single transaction <= WS-MAX-SINGLE-WD        *
      *   - Withdrawal: daily total (DAILY_WD_USED + amount)          *
      *     must not exceed DAILY_WD_LIMIT                             *
      *   - Transfer: both accounts must be ACTIVE; debit and credit  *
      *     are wrapped in a single CICS SYNCPOINT                     *
      *   - All operations write to TRANSACTION_REGISTER before        *
      *     SYNCPOINT; any Db2 error triggers SYNCPOINT ROLLBACK       *
      *----------------------------------------------------------------*
       ENVIRONMENT DIVISION.
       DATA DIVISION.
       WORKING-STORAGE SECTION.

       COPY BKCOMMON.

       01 WS-ACCT-FROM-REC.
          05 WS-FROM-STATUS     PIC X(1).
          05 WS-FROM-BALANCE    PIC S9(13)V99 COMP-3.
          05 WS-FROM-OD-LIM     PIC S9(7)V99  COMP-3.
          05 WS-FROM-DWD-LIMIT  PIC S9(7)V99  COMP-3.
          05 WS-FROM-DWD-USED   PIC S9(7)V99  COMP-3.

       01 WS-ACCT-TO-REC.
          05 WS-TO-STATUS       PIC X(1).
          05 WS-TO-BALANCE      PIC S9(13)V99 COMP-3.

       01 WS-NEW-FROM-BALANCE   PIC S9(13)V99 COMP-3.
       01 WS-NEW-TO-BALANCE     PIC S9(13)V99 COMP-3.
       01 WS-NEW-DWD-USED       PIC S9(7)V99  COMP-3.
       01 WS-AVAILABLE-BALANCE  PIC S9(13)V99 COMP-3.

       01 WS-TIMESTAMP          PIC X(26).
       01 WS-DATE-ONLY          PIC X(10).
       01 WS-TIME-ONLY          PIC X(8).
       01 WS-TXN-SEQ            PIC S9(9)     COMP VALUE ZERO.
       01 WS-TXN-REF-BUILD      PIC X(16).

      *--- Cursor for daily withdrawal total (N+1 anti-pattern) ---
      *--- TODO: replace with the scalar DAILY_WD_USED column    ---
       01 WS-CURSOR-SUM         PIC S9(13)V99 COMP-3.
       01 WS-CURSOR-CNT         PIC S9(4)     COMP VALUE ZERO.

       LINKAGE SECTION.
       01 DFHCOMMAREA           PIC X(200).

       PROCEDURE DIVISION.

           MOVE DFHCOMMAREA TO WS-COMMAREA.

      *--- Basic input validation ---------------------------------
           IF CA-AMOUNT <= ZERO
               MOVE '99' TO CA-RETURN-CODE
               MOVE 'AMOUNT MUST BE GREATER THAN ZERO' TO CA-MESSAGE
               PERFORM RETURN-TO-CALLER
           END-IF.

           IF CA-ACCT-FROM = SPACES
               MOVE '05' TO CA-RETURN-CODE
               MOVE 'FROM ACCOUNT NUMBER IS REQUIRED' TO CA-MESSAGE
               PERFORM RETURN-TO-CALLER
           END-IF.

      *--- Fetch and lock the FROM account for update -------------
           MOVE CA-ACCT-FROM TO HV-ACCT-NO.

           EXEC SQL
               SELECT ACCT_STATUS,
                      BALANCE,
                      OVERDRAFT_LIMIT,
                      DAILY_WD_LIMIT,
                      DAILY_WD_USED
               INTO  :WS-FROM-STATUS,
                     :WS-FROM-BALANCE,
                     :WS-FROM-OD-LIM,
                     :WS-FROM-DWD-LIMIT,
                     :WS-FROM-DWD-USED
               FROM  BANKDB.ACCOUNT_MASTER
               WHERE ACCT_NO = :HV-ACCT-NO
               FOR UPDATE OF BALANCE, DAILY_WD_USED
           END-EXEC.

           EVALUATE WS-SQLCODE
               WHEN 0    CONTINUE
               WHEN +100
                   MOVE '05' TO CA-RETURN-CODE
                   MOVE 'FROM ACCOUNT NOT FOUND' TO CA-MESSAGE
                   PERFORM RETURN-TO-CALLER
               WHEN OTHER
                   MOVE '99' TO CA-RETURN-CODE
                   MOVE 'DATABASE ERROR - FROM ACCOUNT READ'
                       TO CA-MESSAGE
                   PERFORM RETURN-TO-CALLER
           END-EVALUATE.

      *--- Account status guard -----------------------------------
           IF WS-FROM-STATUS NOT = 'A'
               EVALUATE WS-FROM-STATUS
                   WHEN 'F'
                       MOVE '03' TO CA-RETURN-CODE
                       MOVE 'ACCOUNT IS FROZEN' TO CA-MESSAGE
                   WHEN 'C'
                       MOVE '02' TO CA-RETURN-CODE
                       MOVE 'ACCOUNT IS CLOSED' TO CA-MESSAGE
                   WHEN OTHER
                       MOVE '99' TO CA-RETURN-CODE
                       MOVE 'ACCOUNT STATUS INVALID' TO CA-MESSAGE
               END-EVALUATE
               PERFORM RETURN-TO-CALLER
           END-IF.

      *--- Route by function --------------------------------------
           EVALUATE TRUE
               WHEN CA-DEPOSIT
                   PERFORM PROCESS-DEPOSIT
               WHEN CA-WITHDRAW
                   PERFORM PROCESS-WITHDRAWAL
               WHEN CA-TRANSFER
                   PERFORM PROCESS-TRANSFER
               WHEN OTHER
                   MOVE '99' TO CA-RETURN-CODE
                   MOVE 'UNKNOWN TRANSACTION FUNCTION' TO CA-MESSAGE
                   PERFORM RETURN-TO-CALLER
           END-EVALUATE.

           PERFORM RETURN-TO-CALLER.

      *=============================================================
       PROCESS-DEPOSIT.
      *=============================================================
      *--- Credit the account and persist -------------------------
           COMPUTE WS-NEW-FROM-BALANCE =
               WS-FROM-BALANCE + CA-AMOUNT.

           EXEC SQL
               UPDATE BANKDB.ACCOUNT_MASTER
               SET    BALANCE          = :WS-NEW-FROM-BALANCE,
                      LAST_UPDATE_TS   = CURRENT TIMESTAMP
               WHERE  ACCT_NO          = :HV-ACCT-NO
           END-EXEC.

           IF WS-SQLCODE NOT = 0
               MOVE '99' TO CA-RETURN-CODE
               MOVE 'DEPOSIT UPDATE FAILED' TO CA-MESSAGE
               PERFORM ROLLBACK-AND-RETURN
           END-IF.

           PERFORM WRITE-TRANSACTION-REGISTER.
           PERFORM SYNCPOINT-COMMIT.

           MOVE WS-NEW-FROM-BALANCE TO CA-NEW-BALANCE.
           MOVE '00' TO CA-RETURN-CODE.
           MOVE 'DEPOSIT SUCCESSFUL' TO CA-MESSAGE.

      *=============================================================
       PROCESS-WITHDRAWAL.
      *=============================================================
      *--- Single-transaction amount limit ------------------------
           IF CA-AMOUNT > WS-MAX-SINGLE-WD
               MOVE '04' TO CA-RETURN-CODE
               MOVE 'WITHDRAWAL EXCEEDS SINGLE TRANSACTION LIMIT'
                   TO CA-MESSAGE
               PERFORM RETURN-TO-CALLER
           END-IF.

      *--- Daily withdrawal limit check ---------------------------
      *--- NOTE: this loop recalculates today's total from        ---
      *--- TRANSACTION_REGISTER instead of using DAILY_WD_USED.  ---
      *--- This N+1 pattern was introduced in 2011 and never      ---
      *--- replaced. The DAILY_WD_USED column in ACCOUNT_MASTER   ---
      *--- is the correct source; the loop below should be removed.
           MOVE ZERO TO WS-CURSOR-SUM.
           MOVE ZERO TO WS-CURSOR-CNT.
           EXEC SQL
               SELECT COUNT(*), COALESCE(SUM(TXN_AMOUNT), 0)
               INTO  :WS-CURSOR-CNT, :WS-CURSOR-SUM
               FROM  BANKDB.TRANSACTION_REGISTER
               WHERE ACCT_FROM  = :HV-ACCT-NO
               AND   TXN_TYPE   = 'WITH'
               AND   TXN_STATUS = 'C'
               AND   DATE(TXN_TIMESTAMP) = CURRENT DATE
           END-EXEC.

           COMPUTE WS-NEW-DWD-USED =
               WS-CURSOR-SUM + CA-AMOUNT.

           IF WS-NEW-DWD-USED > WS-FROM-DWD-LIMIT
               MOVE '04' TO CA-RETURN-CODE
               MOVE 'DAILY WITHDRAWAL LIMIT EXCEEDED' TO CA-MESSAGE
               PERFORM RETURN-TO-CALLER
           END-IF.

      *--- Sufficient balance check (overdraft not permitted) -----
           COMPUTE WS-AVAILABLE-BALANCE =
               WS-FROM-BALANCE + WS-FROM-OD-LIM.

           IF CA-AMOUNT > WS-AVAILABLE-BALANCE
               MOVE '01' TO CA-RETURN-CODE
               MOVE 'INSUFFICIENT FUNDS' TO CA-MESSAGE
               PERFORM RETURN-TO-CALLER
           END-IF.

           COMPUTE WS-NEW-FROM-BALANCE =
               WS-FROM-BALANCE - CA-AMOUNT.

           EXEC SQL
               UPDATE BANKDB.ACCOUNT_MASTER
               SET    BALANCE        = :WS-NEW-FROM-BALANCE,
                      DAILY_WD_USED  = :WS-NEW-DWD-USED,
                      LAST_UPDATE_TS = CURRENT TIMESTAMP
               WHERE  ACCT_NO        = :HV-ACCT-NO
           END-EXEC.

           IF WS-SQLCODE NOT = 0
               MOVE '99' TO CA-RETURN-CODE
               MOVE 'WITHDRAWAL UPDATE FAILED' TO CA-MESSAGE
               PERFORM ROLLBACK-AND-RETURN
           END-IF.

           PERFORM WRITE-TRANSACTION-REGISTER.
           PERFORM SYNCPOINT-COMMIT.

           MOVE WS-NEW-FROM-BALANCE TO CA-NEW-BALANCE.
           MOVE '00' TO CA-RETURN-CODE.
           MOVE 'WITHDRAWAL SUCCESSFUL' TO CA-MESSAGE.

      *=============================================================
       PROCESS-TRANSFER.
      *=============================================================
      *--- TO account must be provided ----------------------------
           IF CA-ACCT-TO = SPACES
               MOVE '05' TO CA-RETURN-CODE
               MOVE 'TO ACCOUNT NUMBER IS REQUIRED FOR TRANSFER'
                   TO CA-MESSAGE
               PERFORM RETURN-TO-CALLER
           END-IF.

           IF CA-ACCT-FROM = CA-ACCT-TO
               MOVE '99' TO CA-RETURN-CODE
               MOVE 'FROM AND TO ACCOUNTS MUST DIFFER' TO CA-MESSAGE
               PERFORM RETURN-TO-CALLER
           END-IF.

      *--- Fetch and lock the TO account --------------------------
           MOVE CA-ACCT-TO TO HV-ACCT-NO.

           EXEC SQL
               SELECT ACCT_STATUS, BALANCE
               INTO  :WS-TO-STATUS, :WS-TO-BALANCE
               FROM  BANKDB.ACCOUNT_MASTER
               WHERE  ACCT_NO = :HV-ACCT-NO
               FOR UPDATE OF BALANCE
           END-EXEC.

           EVALUATE WS-SQLCODE
               WHEN 0    CONTINUE
               WHEN +100
                   MOVE '05' TO CA-RETURN-CODE
                   MOVE 'TO ACCOUNT NOT FOUND' TO CA-MESSAGE
                   PERFORM RETURN-TO-CALLER
               WHEN OTHER
                   MOVE '99' TO CA-RETURN-CODE
                   MOVE 'DATABASE ERROR - TO ACCOUNT READ'
                       TO CA-MESSAGE
                   PERFORM RETURN-TO-CALLER
           END-EVALUATE.

           IF WS-TO-STATUS NOT = 'A'
               MOVE '03' TO CA-RETURN-CODE
               MOVE 'DESTINATION ACCOUNT IS NOT ACTIVE' TO CA-MESSAGE
               PERFORM RETURN-TO-CALLER
           END-IF.

      *--- Sufficient balance guard for the debit leg -------------
           IF CA-AMOUNT > WS-FROM-BALANCE
               MOVE '01' TO CA-RETURN-CODE
               MOVE 'INSUFFICIENT FUNDS FOR TRANSFER' TO CA-MESSAGE
               PERFORM RETURN-TO-CALLER
           END-IF.

           COMPUTE WS-NEW-FROM-BALANCE = WS-FROM-BALANCE - CA-AMOUNT.
           COMPUTE WS-NEW-TO-BALANCE   = WS-TO-BALANCE   + CA-AMOUNT.

      *--- Debit FROM account -------------------------------------
           MOVE CA-ACCT-FROM TO HV-ACCT-NO.
           EXEC SQL
               UPDATE BANKDB.ACCOUNT_MASTER
               SET    BALANCE        = :WS-NEW-FROM-BALANCE,
                      LAST_UPDATE_TS = CURRENT TIMESTAMP
               WHERE  ACCT_NO        = :HV-ACCT-NO
           END-EXEC.

           IF WS-SQLCODE NOT = 0
               MOVE '99' TO CA-RETURN-CODE
               MOVE 'TRANSFER DEBIT FAILED' TO CA-MESSAGE
               PERFORM ROLLBACK-AND-RETURN
           END-IF.

      *--- Credit TO account --------------------------------------
           MOVE CA-ACCT-TO TO HV-ACCT-NO.
           EXEC SQL
               UPDATE BANKDB.ACCOUNT_MASTER
               SET    BALANCE        = :WS-NEW-TO-BALANCE,
                      LAST_UPDATE_TS = CURRENT TIMESTAMP
               WHERE  ACCT_NO        = :HV-ACCT-NO
           END-EXEC.

           IF WS-SQLCODE NOT = 0
               MOVE '99' TO CA-RETURN-CODE
               MOVE 'TRANSFER CREDIT FAILED - ROLLING BACK'
                   TO CA-MESSAGE
               PERFORM ROLLBACK-AND-RETURN
           END-IF.

           PERFORM WRITE-TRANSACTION-REGISTER.
           PERFORM SYNCPOINT-COMMIT.

           MOVE WS-NEW-FROM-BALANCE TO CA-NEW-BALANCE.
           MOVE '00' TO CA-RETURN-CODE.
           MOVE 'TRANSFER SUCCESSFUL' TO CA-MESSAGE.

      *=============================================================
       WRITE-TRANSACTION-REGISTER.
      *=============================================================
           EXEC CICS ASKTIME ABSTIME(WS-ABS-TIME-START) END-EXEC.
           EXEC SQL
               VALUES(CURRENT TIMESTAMP)
               INTO :WS-TIMESTAMP
           END-EXEC.
           MOVE WS-TIMESTAMP(1:10) TO WS-DATE-ONLY.
           MOVE WS-TIMESTAMP(12:8) TO WS-TIME-ONLY.

           EXEC SQL
               SELECT NEXT VALUE FOR BANKDB.TXN_SEQ
               INTO :WS-TXN-SEQ
               FROM SYSIBM.SYSDUMMY1
           END-EXEC.

           STRING CA-ACCT-FROM DELIMITED SIZE
               '-' DELIMITED SIZE
               WS-TXN-SEQ DELIMITED SIZE
               INTO WS-TXN-REF-BUILD.
           MOVE WS-TXN-REF-BUILD TO CA-TXN-REF.

           MOVE CA-ACCT-FROM   TO HV-TXN-ACCT-FROM.
           MOVE CA-ACCT-TO     TO HV-TXN-ACCT-TO.
           MOVE CA-AMOUNT      TO HV-TXN-AMOUNT.
           MOVE CA-FUNCTION    TO HV-TXN-TYPE.
           MOVE CA-TELLER-ID   TO HV-TXN-TELLER-ID.
           MOVE CA-BRANCH-ID   TO HV-TXN-BRANCH-ID.
           MOVE 'TELLER'       TO HV-TXN-CHANNEL.
           MOVE 'C'            TO HV-TXN-STATUS.
           MOVE WS-TXN-SEQ     TO HV-TXN-ID.
           MOVE CA-TXN-REF     TO HV-TXN-REF.
           MOVE WS-DATE-ONLY   TO HV-TXN-DATE.
           MOVE WS-TIME-ONLY   TO HV-TXN-TIME.

           EXEC SQL
               INSERT INTO BANKDB.TRANSACTION_REGISTER
                   (TXN_ID, TXN_DATE, TXN_TIME, TXN_TYPE,
                    ACCT_FROM, ACCT_TO, TXN_AMOUNT, TXN_REF,
                    TELLER_ID, BRANCH_ID, CHANNEL, TXN_STATUS,
                    TXN_TIMESTAMP)
               VALUES
                   (:HV-TXN-ID, :HV-TXN-DATE, :HV-TXN-TIME,
                    :HV-TXN-TYPE, :HV-TXN-ACCT-FROM,
                    :HV-TXN-ACCT-TO, :HV-TXN-AMOUNT, :HV-TXN-REF,
                    :HV-TXN-TELLER-ID, :HV-TXN-BRANCH-ID,
                    :HV-TXN-CHANNEL, :HV-TXN-STATUS,
                    CURRENT TIMESTAMP)
           END-EXEC.

           IF WS-SQLCODE NOT = 0
               MOVE '99' TO CA-RETURN-CODE
               MOVE 'FAILED TO WRITE TRANSACTION REGISTER'
                   TO CA-MESSAGE
               PERFORM ROLLBACK-AND-RETURN
           END-IF.

      *=============================================================
       SYNCPOINT-COMMIT.
      *=============================================================
           EXEC CICS SYNCPOINT
               RESP(WS-CICS-RESP)
           END-EXEC.
           IF WS-CICS-RESP NOT = DFHRESP(NORMAL)
               MOVE '99' TO CA-RETURN-CODE
               MOVE 'SYNCPOINT FAILED - TRANSACTION INCOMPLETE'
                   TO CA-MESSAGE
           END-IF.

      *=============================================================
       ROLLBACK-AND-RETURN.
      *=============================================================
           EXEC CICS SYNCPOINT ROLLBACK
               RESP(WS-CICS-RESP)
           END-EXEC.
           PERFORM RETURN-TO-CALLER.

       RETURN-TO-CALLER.
           MOVE WS-COMMAREA TO DFHCOMMAREA.
           EXEC CICS RETURN END-EXEC.
