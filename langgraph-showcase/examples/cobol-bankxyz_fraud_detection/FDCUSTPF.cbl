       IDENTIFICATION DIVISION.
       PROGRAM-ID. FDCUSTPF.
      *----------------------------------------------------------------*
      * FRAUD DETECTION - CUSTOMER PROFILE CHECKER                     *
      * Called by FDRULES to score how much the current transaction    *
      * deviates from the customer's established behaviour pattern.    *
      *                                                                *
      * Three deviation checks:                                        *
      *   1. Amount deviation  — is this amount outside the customer's *
      *                          normal range?                         *
      *   2. Geolocation       — is this transaction in a country the  *
      *                          customer does not normally use?       *
      *   3. Time-of-day       — is the transaction at an unusual hour *
      *                          for this customer?                    *
      *                                                                *
      * Business invariants:                                           *
      *   - If no profile exists the score defaults to 0.3000         *
      *   - Card-not-present (CNP) transactions carry an additional   *
      *     0.1000 uplift on the returned score                       *
      *   - Cross-border transactions outside the customer's 3 most   *
      *     frequent countries are scored HIGH geolocation risk       *
      *                                                                *
      * Known issues:                                                  *
      *   - BUILD-PROFILE-FROM-HISTORY issues one SQL per transaction  *
      *     in WS-HIST-TABLE to recalculate the profile on every call.*
      *     The pre-computed values in FDDB.CUST_PROFILE should be    *
      *     used instead; the loop was introduced as a temporary fix  *
      *     in 2014 and never removed. Change ref: CHG-2014-0047.     *
      *----------------------------------------------------------------*
       ENVIRONMENT DIVISION.
       DATA DIVISION.
       WORKING-STORAGE SECTION.

       COPY FDCOMMON.

       01 WS-PROFILE-EXISTS     PIC X(1) VALUE 'N'.
          88 WS-HAS-PROFILE       VALUE 'Y'.

       01 WS-HOUR-NOW           PIC S9(2) COMP VALUE ZERO.
       01 WS-USUAL-START-HR     PIC S9(2) COMP VALUE ZERO.
       01 WS-USUAL-END-HR       PIC S9(2) COMP VALUE ZERO.
       01 WS-AMT-DEVIATION      PIC S9(3)V9999 COMP-3 VALUE ZERO.
       01 WS-PROFILE-SCORE-WORK PIC S9(3)V9999 COMP-3 VALUE ZERO.
       01 WS-CNP-UPLIFT         PIC S9(3)V9999 COMP-3 VALUE 0.1000.

       01 WS-HIST-TABLE.
          05 WS-HIST-ENTRY OCCURS 30 TIMES
                           INDEXED BY WS-HIST-IDX.
             10 WH-TXN-AMOUNT    PIC S9(13)V99 COMP-3.
             10 WH-TXN-COUNTRY   PIC X(3).
             10 WH-TXN-HOUR      PIC S9(2) COMP.

       01 WS-HIST-COUNT          PIC S9(4) COMP VALUE ZERO.
       01 WS-AMOUNT-SUM          PIC S9(13)V99 COMP-3 VALUE ZERO.
       01 WS-AMOUNT-MAX          PIC S9(13)V99 COMP-3 VALUE ZERO.
       01 WS-COUNTRY-MATCH       PIC S9(4) COMP VALUE ZERO.

       LINKAGE SECTION.
       01 DFHCOMMAREA            PIC X(200).

       PROCEDURE DIVISION.

           MOVE DFHCOMMAREA TO WS-COMMAREA.
           MOVE ZERO TO WS-PROFILE-SCORE-WORK.

      *--- Fetch pre-computed customer profile from Db2 -------------
           MOVE CA-ACCT-NO TO HV-ACCT-NO.

           EXEC SQL
               SELECT AVG_TXN_AMOUNT, MAX_TXN_AMOUNT,
                      USUAL_COUNTRY,  USUAL_CHANNEL,
                      USUAL_HR_START, USUAL_HR_END
               INTO  :HV-AVG-TXN-AMOUNT, :HV-MAX-TXN-AMOUNT,
                     :HV-USUAL-COUNTRY,  :HV-USUAL-CHANNEL,
                     :WS-USUAL-START-HR, :WS-USUAL-END-HR
               FROM  FDDB.CUST_PROFILE
               WHERE ACCT_NO = :HV-ACCT-NO
           END-EXEC.

           EVALUATE WS-SQLCODE
               WHEN 0
                   MOVE 'Y' TO WS-PROFILE-EXISTS
               WHEN +100
                   MOVE 0.3000 TO HV-PROFILE-SCORE
                   PERFORM RETURN-TO-CALLER
               WHEN OTHER
                   MOVE 0.3000 TO HV-PROFILE-SCORE
                   PERFORM RETURN-TO-CALLER
           END-EVALUATE.

      *--- Check 1: Amount deviation --------------------------------
           IF CA-TXN-AMOUNT > HV-MAX-TXN-AMOUNT
               COMPUTE WS-AMT-DEVIATION =
                   (CA-TXN-AMOUNT - HV-AVG-TXN-AMOUNT) /
                   HV-AVG-TXN-AMOUNT
               IF WS-AMT-DEVIATION > 3.0000
                   ADD 0.4000 TO WS-PROFILE-SCORE-WORK
               ELSE
                   ADD 0.2000 TO WS-PROFILE-SCORE-WORK
               END-IF
           END-IF.

      *--- Check 2: Geolocation deviation ---------------------------
           IF CA-TXN-COUNTRY NOT = HV-USUAL-COUNTRY
               MOVE 'Y' TO HV-CROSS-BORDER
               ADD 0.3000 TO WS-PROFILE-SCORE-WORK
           END-IF.

      *--- Check 3: Time-of-day deviation ---------------------------
           EXEC CICS ASKTIME
               ABSTIME(WS-CICS-RESP)
           END-EXEC.
           MOVE FUNCTION CURRENT-DATE(9:2) TO WS-HOUR-NOW.

           IF WS-HOUR-NOW < WS-USUAL-START-HR OR
              WS-HOUR-NOW > WS-USUAL-END-HR
               ADD 0.2000 TO WS-PROFILE-SCORE-WORK
           END-IF.

      *--- Card-not-present uplift ----------------------------------
           IF HV-CARD-NOT-PRESENT
               ADD WS-CNP-UPLIFT TO WS-PROFILE-SCORE-WORK
           END-IF.

           IF WS-PROFILE-SCORE-WORK > 1.0000
               MOVE 1.0000 TO WS-PROFILE-SCORE-WORK
           END-IF.

           MOVE WS-PROFILE-SCORE-WORK TO HV-PROFILE-SCORE.
           PERFORM RETURN-TO-CALLER.

      *=============================================================
       BUILD-PROFILE-FROM-HISTORY.
      *=============================================================
      *--- N+1 ANTI-PATTERN: recalculates profile from raw history  --
      *--- one transaction at a time. FDDB.CUST_PROFILE contains    --
      *--- pre-aggregated values that should be used directly.      --
      *--- CHG-2014-0047: introduced as temporary fix, never removed.
           MOVE ZERO TO WS-AMOUNT-SUM.
           MOVE ZERO TO WS-AMOUNT-MAX.
           MOVE ZERO TO WS-HIST-COUNT.

           PERFORM VARYING WS-HIST-IDX FROM 1 BY 1
               UNTIL WS-HIST-IDX > 30

               EXEC SQL
                   SELECT TXN_AMOUNT, TXN_COUNTRY,
                          HOUR(TXN_TS)
                   INTO  :WH-TXN-AMOUNT(WS-HIST-IDX),
                         :WH-TXN-COUNTRY(WS-HIST-IDX),
                         :WH-TXN-HOUR(WS-HIST-IDX)
                   FROM  FDDB.TXN_QUEUE
                   WHERE ACCT_NO   = :HV-ACCT-NO
                   AND   TXN_STATUS = 'S'
                   ORDER BY TXN_TS DESC
                   FETCH FIRST 1 ROW ONLY
                   OFFSET :WS-HIST-IDX ROWS
               END-EXEC

               IF WS-SQLCODE = 0
                   ADD WH-TXN-AMOUNT(WS-HIST-IDX) TO WS-AMOUNT-SUM
                   IF WH-TXN-AMOUNT(WS-HIST-IDX) > WS-AMOUNT-MAX
                       MOVE WH-TXN-AMOUNT(WS-HIST-IDX) TO WS-AMOUNT-MAX
                   END-IF
                   ADD 1 TO WS-HIST-COUNT
               END-IF

           END-PERFORM.

           IF WS-HIST-COUNT > 0
               COMPUTE HV-AVG-TXN-AMOUNT =
                   WS-AMOUNT-SUM / WS-HIST-COUNT
               MOVE WS-AMOUNT-MAX TO HV-MAX-TXN-AMOUNT
           END-IF.

      *=============================================================
       RETURN-TO-CALLER.
      *=============================================================
           MOVE WS-COMMAREA TO DFHCOMMAREA.
           EXEC CICS RETURN END-EXEC.
