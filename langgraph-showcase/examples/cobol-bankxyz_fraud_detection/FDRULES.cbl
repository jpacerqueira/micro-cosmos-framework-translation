       IDENTIFICATION DIVISION.
       PROGRAM-ID. FDRULES.
      *----------------------------------------------------------------*
      * FRAUD DETECTION - RULES ENGINE                                 *
      * Called by FDTXNMON for every pending transaction.             *
      * Combines three independent signals into a composite fraud     *
      * score between 0.0000 and 1.0000:                              *
      *                                                                *
      *   1. Amount score  (40%) - transaction size vs thresholds     *
      *   2. Merchant score (40%) - blocked merchant / risk band      *
      *   3. Velocity score (20%) - recent transaction count via      *
      *                             CALL 'FDVELCHK'                   *
      *                                                                *
      * Business invariants:                                           *
      *   - Score >= 0.7500 → CA-FRAUD-FLAG set to 'Y'               *
      *   - Frozen or closed accounts are auto-flagged (score = 1.0)  *
      *   - Amount is stored as COMP-3 packed decimal; never FLOAT    *
      *   - Merchant risk ratings are read from FDDB.MERCHANT_RISK    *
      *----------------------------------------------------------------*
       ENVIRONMENT DIVISION.
       DATA DIVISION.
       WORKING-STORAGE SECTION.

       COPY FDCOMMON.

       01 WS-ACCT-STATUS        PIC X(1).
          88 WS-ACCT-ACTIVE       VALUE 'A'.
          88 WS-ACCT-FROZEN       VALUE 'F'.
          88 WS-ACCT-CLOSED       VALUE 'C'.

       01 WS-VELOCITY-COMMAREA  PIC X(200).
       01 WS-PROFILE-COMMAREA   PIC X(200).
       01 WS-WATCHLIST-COMMAREA PIC X(200).
       01 WS-SCORE-WORK         PIC S9(3)V9999 COMP-3 VALUE ZERO.

       LINKAGE SECTION.
       01 DFHCOMMAREA           PIC X(200).

       PROCEDURE DIVISION.

           MOVE DFHCOMMAREA TO WS-COMMAREA.

      *--- Validate account is active --------------------------------
           MOVE CA-ACCT-NO TO HV-ACCT-NO.

           EXEC SQL
               SELECT ACCT_STATUS
               INTO  :WS-ACCT-STATUS
               FROM  FDDB.ACCOUNT_MASTER
               WHERE ACCT_NO = :HV-ACCT-NO
           END-EXEC.

           EVALUATE WS-SQLCODE
               WHEN 0    CONTINUE
               WHEN +100
                   MOVE '05' TO CA-RETURN-CODE
                   MOVE 'ACCOUNT NOT FOUND' TO CA-MESSAGE
                   PERFORM RETURN-TO-CALLER
               WHEN OTHER
                   MOVE '99' TO CA-RETURN-CODE
                   MOVE 'DB ERROR READING ACCOUNT' TO CA-MESSAGE
                   PERFORM RETURN-TO-CALLER
           END-EVALUATE.

      *--- Frozen or closed accounts are automatically high risk -----
           IF WS-ACCT-FROZEN OR WS-ACCT-CLOSED
               MOVE 1.0000 TO CA-FRAUD-SCORE
               MOVE 'Y' TO CA-FRAUD-FLAG
               MOVE '10' TO CA-RETURN-CODE
               MOVE 'ACCOUNT INACTIVE - AUTO FLAGGED' TO CA-MESSAGE
               PERFORM RETURN-TO-CALLER
           END-IF.

      *--- Signal 1: Amount scoring ----------------------------------
           PERFORM SCORE-BY-AMOUNT.

      *--- Signal 2: Merchant risk scoring --------------------------
           PERFORM SCORE-BY-MERCHANT.

      *--- Signal 3: Velocity scoring via FDVELCHK ------------------
           MOVE WS-COMMAREA TO WS-VELOCITY-COMMAREA.
           CALL 'FDVELCHK' USING WS-VELOCITY-COMMAREA.
           MOVE WS-VELOCITY-COMMAREA TO WS-COMMAREA.

      *--- Signal 4: Customer profile deviation via FDCUSTPF --------
           MOVE WS-COMMAREA TO WS-PROFILE-COMMAREA.
           CALL 'FDCUSTPF' USING WS-PROFILE-COMMAREA.
           MOVE WS-PROFILE-COMMAREA TO WS-COMMAREA.

      *--- Signal 5: Watchlist and sanctions via FDWATCHL -----------
           MOVE WS-COMMAREA TO WS-WATCHLIST-COMMAREA.
           CALL 'FDWATCHL' USING WS-WATCHLIST-COMMAREA.
           MOVE WS-WATCHLIST-COMMAREA TO WS-COMMAREA.

      *--- Auto-flag any sanctions hit regardless of score ----------
           IF HV-OFAC-HIT OR HV-PEP-HIT
               MOVE 1.0000 TO CA-FRAUD-SCORE
               MOVE 'Y'    TO CA-FRAUD-FLAG
               MOVE '10'   TO CA-RETURN-CODE
               MOVE HV-WATCHLIST-REASON TO CA-MESSAGE
               PERFORM RETURN-TO-CALLER
           END-IF.

      *--- Composite score (5 signals) ------------------------------
           COMPUTE WS-COMPOSITE-SCORE =
               (WS-AMOUNT-SCORE        * WS-WEIGHT-AMOUNT)    +
               (WS-MERCHANT-SCORE      * WS-WEIGHT-MERCHANT)  +
               (HV-VELOCITY-SCORE      * WS-WEIGHT-VELOCITY)  +
               (HV-PROFILE-SCORE       * WS-WEIGHT-PROFILE)   +
               (HV-WATCHLIST-SCORE     * WS-WEIGHT-WATCHLIST).

           IF WS-COMPOSITE-SCORE > 1.0000
               MOVE 1.0000 TO WS-COMPOSITE-SCORE
           END-IF.

           MOVE WS-COMPOSITE-SCORE TO CA-FRAUD-SCORE.

           IF WS-COMPOSITE-SCORE >= WS-SCORE-THRESHOLD
               MOVE 'Y'  TO CA-FRAUD-FLAG
               MOVE '10' TO CA-RETURN-CODE
               MOVE 'TRANSACTION FLAGGED AS HIGH RISK' TO CA-MESSAGE
           ELSE
               MOVE 'N'  TO CA-FRAUD-FLAG
               MOVE '00' TO CA-RETURN-CODE
               MOVE 'TRANSACTION CLEARED' TO CA-MESSAGE
           END-IF.

           PERFORM RETURN-TO-CALLER.

      *=============================================================
       SCORE-BY-AMOUNT.
      *=============================================================
           EVALUATE TRUE
               WHEN CA-TXN-AMOUNT >= WS-HIGH-AMT-LIMIT
                   MOVE 0.8000 TO WS-AMOUNT-SCORE
               WHEN CA-TXN-AMOUNT >= WS-MED-AMT-LIMIT
                   MOVE 0.5000 TO WS-AMOUNT-SCORE
               WHEN CA-TXN-AMOUNT >= WS-LOW-AMT-LIMIT
                   MOVE 0.3000 TO WS-AMOUNT-SCORE
               WHEN OTHER
                   MOVE 0.1000 TO WS-AMOUNT-SCORE
           END-EVALUATE.

      *=============================================================
       SCORE-BY-MERCHANT.
      *=============================================================
           MOVE CA-MERCHANT-CODE TO HV-MERCHANT-CODE.

           EXEC SQL
               SELECT BLOCKED_FLAG, RISK_BAND
               INTO  :HV-BLOCKED-FLAG, :HV-MERCHANT-RISK
               FROM  FDDB.MERCHANT_RISK
               WHERE MERCHANT_CODE = :HV-MERCHANT-CODE
           END-EXEC.

           EVALUATE WS-SQLCODE
               WHEN 0
                   EVALUATE TRUE
                       WHEN HV-MERCHANT-BLOCKED
                           MOVE 1.0000 TO WS-MERCHANT-SCORE
                       WHEN HV-RISK-HIGH
                           MOVE 0.8000 TO WS-MERCHANT-SCORE
                       WHEN HV-RISK-MED
                           MOVE 0.4000 TO WS-MERCHANT-SCORE
                       WHEN OTHER
                           MOVE 0.1000 TO WS-MERCHANT-SCORE
                   END-EVALUATE
               WHEN OTHER
                   MOVE 0.0000 TO WS-MERCHANT-SCORE
           END-EVALUATE.

      *=============================================================
       RETURN-TO-CALLER.
      *=============================================================
           MOVE WS-COMMAREA TO DFHCOMMAREA.
           EXEC CICS RETURN END-EXEC.
