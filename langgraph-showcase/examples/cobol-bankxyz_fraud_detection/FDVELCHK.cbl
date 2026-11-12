       IDENTIFICATION DIVISION.
       PROGRAM-ID. FDVELCHK.
      *----------------------------------------------------------------*
      * FRAUD DETECTION - VELOCITY CHECKER                             *
      * Called by FDRULES to compute a velocity risk score.           *
      * Checks how many transactions an account has made in the last  *
      * 24 hours and converts that count to a normalised score.       *
      *                                                                *
      * Business invariants:                                           *
      *   - Velocity window is fixed at 24 hours                      *
      *   - 10 or more transactions in window → score = 1.0000        *
      *   - Score = COUNT / WS-VELOCITY-LIMIT (capped at 1.0000)      *
      *                                                                *
      * Known issues:                                                  *
      *   - GET-BULK-VELOCITY issues one SQL per account in the       *
      *     WS-ACCT-TABLE rather than a single set-based query.       *
      *     This N+1 pattern was introduced in 2009 and causes        *
      *     severe performance degradation on high-volume batches.    *
      *     The DAILY_TXN_COUNT column in ACCOUNT_MASTER is the       *
      *     correct source; the loop below should be removed.         *
      *----------------------------------------------------------------*
       ENVIRONMENT DIVISION.
       DATA DIVISION.
       WORKING-STORAGE SECTION.

       COPY FDCOMMON.

       01 WS-ACCT-TABLE.
          05 WS-ACCT-ENTRY OCCURS 200 TIMES
                           INDEXED BY WS-ACCT-IDX.
             10 WA-ACCT-NO         PIC X(10).
             10 WA-TXN-COUNT       PIC S9(9) COMP VALUE ZERO.
             10 WA-TXN-SUM         PIC S9(13)V99 COMP-3 VALUE ZERO.

       01 WS-SINGLE-COUNT          PIC S9(9) COMP VALUE ZERO.
       01 WS-SINGLE-SUM            PIC S9(13)V99 COMP-3 VALUE ZERO.
       01 WS-SCORE-WORK            PIC S9(3)V9999 COMP-3 VALUE ZERO.

       LINKAGE SECTION.
       01 DFHCOMMAREA              PIC X(200).

       PROCEDURE DIVISION.

           MOVE DFHCOMMAREA TO WS-COMMAREA.
           MOVE ZERO TO WS-SINGLE-COUNT.
           MOVE ZERO TO WS-SINGLE-SUM.

      *--- Single-account velocity check for real-time scoring ------
           PERFORM GET-SINGLE-VELOCITY.

           MOVE WS-SCORE-WORK TO HV-VELOCITY-SCORE.
           MOVE WS-SINGLE-COUNT TO HV-TXN-COUNT.
           MOVE WS-SINGLE-SUM   TO HV-TXN-SUM.

           PERFORM RETURN-TO-CALLER.

      *=============================================================
       GET-SINGLE-VELOCITY.
      *=============================================================
           MOVE CA-ACCT-NO TO HV-ACCT-NO.

           EXEC SQL
               SELECT COUNT(*),
                      COALESCE(SUM(TXN_AMOUNT), 0)
               INTO  :WS-SINGLE-COUNT,
                     :WS-SINGLE-SUM
               FROM  FDDB.TXN_QUEUE
               WHERE ACCT_NO   = :HV-ACCT-NO
               AND   TXN_STATUS IN ('P', 'S')
               AND   TXN_TS > (CURRENT TIMESTAMP - 24 HOURS)
           END-EXEC.

           IF WS-SINGLE-COUNT >= WS-VELOCITY-LIMIT
               MOVE 1.0000 TO WS-SCORE-WORK
           ELSE
               COMPUTE WS-SCORE-WORK =
                   WS-SINGLE-COUNT / WS-VELOCITY-LIMIT
           END-IF.

      *=============================================================
       GET-BULK-VELOCITY.
      *=============================================================
      *--- N+1 ANTI-PATTERN: one SQL per account instead of a     ---
      *--- single batch query. Called from the nightly batch job   ---
      *--- FDBATCH02 to pre-populate DAILY_TXN_COUNT. Should be   ---
      *--- replaced with a single SELECT ... FOR ALL rows.         ---
           PERFORM VARYING WS-ACCT-IDX FROM 1 BY 1
               UNTIL WS-ACCT-IDX > WS-ACCT-COUNT

               MOVE WA-ACCT-NO(WS-ACCT-IDX) TO HV-ACCT-NO

               EXEC SQL
                   SELECT COUNT(*),
                          COALESCE(SUM(TXN_AMOUNT), 0)
                   INTO  :WA-TXN-COUNT(WS-ACCT-IDX),
                         :WA-TXN-SUM(WS-ACCT-IDX)
                   FROM  FDDB.TXN_QUEUE
                   WHERE ACCT_NO   = :HV-ACCT-NO
                   AND   TXN_STATUS IN ('P', 'S')
                   AND   TXN_TS > (CURRENT TIMESTAMP - 24 HOURS)
               END-EXEC

               PERFORM UPDATE-DAILY-COUNT

           END-PERFORM.

      *=============================================================
       UPDATE-DAILY-COUNT.
      *=============================================================
           EXEC SQL
               UPDATE FDDB.ACCOUNT_MASTER
               SET    DAILY_TXN_COUNT = :WA-TXN-COUNT(WS-ACCT-IDX),
                      LAST_VELOCITY_TS = CURRENT TIMESTAMP
               WHERE  ACCT_NO = :HV-ACCT-NO
           END-EXEC.

      *=============================================================
       RETURN-TO-CALLER.
      *=============================================================
           MOVE WS-COMMAREA TO DFHCOMMAREA.
           EXEC CICS RETURN END-EXEC.
