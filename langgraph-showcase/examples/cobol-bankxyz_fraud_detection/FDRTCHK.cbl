       IDENTIFICATION DIVISION.
       PROGRAM-ID. FDRTCHK.
      *----------------------------------------------------------------*
      * FRAUD DETECTION - REAL-TIME AUTHORISATION CHECK                *
      * Called synchronously via EXEC CICS LINK from the card         *
      * authorisation program (CAAUTH) during every card-present and  *
      * card-not-present transaction. Must return within 180ms or     *
      * CICS will timeout and the authorisation defaults to APPROVE.  *
      *                                                                *
      * This is the online counterpart to the batch pipeline driven   *
      * by FDTXNMON. Where FDTXNMON processes yesterday's backlog,   *
      * FDRTCHK blocks the transaction in real time.                  *
      *                                                                *
      * Business invariants:                                           *
      *   - Response code APPROVE  ('00') = transaction proceeds      *
      *   - Response code DECLINE  ('10') = transaction blocked       *
      *   - Response code REVIEW   ('20') = flag for manual review    *
      *     but allow through (customer impact too high to block)     *
      *   - TIMEOUT default is APPROVE: a slow fraud check must never *
      *     prevent a legitimate transaction from completing. This is  *
      *     an explicit business decision accepted in 2009 (ref:      *
      *     BRD-2009-FD-004). It means a sufficiently slow attack     *
      *     can bypass real-time screening.                           *
      *   - Velocity limit for real-time is halved vs batch           *
      *     (5 vs 10) to account for the shorter observation window   *
      *   - CNP transactions are always scored; CP transactions with  *
      *     chip+PIN skip the customer-profile check to meet SLA      *
      *                                                                *
      * Known issues:                                                  *
      *   - The 180ms SLA is routinely breached on FDVELCHK calls     *
      *     during peak hours (08:00-09:30, 12:00-13:00) due to the  *
      *     SQL_IN_LOOP in GET-BULK-VELOCITY. Incident: INC-2023-4471 *
      *   - FDCUSTPF is skipped for chip+PIN (CA-CHIP-PIN = 'Y') to  *
      *     meet the 180ms SLA. This means profile deviation goes     *
      *     undetected for chip+PIN fraud. Risk accepted: BAU-2021-09 *
      *----------------------------------------------------------------*
       ENVIRONMENT DIVISION.
       DATA DIVISION.
       WORKING-STORAGE SECTION.

       COPY FDCOMMON.

       01 WS-RULES-COMMAREA     PIC X(200).
       01 WS-ALERT-COMMAREA     PIC X(200).
       01 WS-START-TIME         PIC S9(15) COMP-3.
       01 WS-END-TIME           PIC S9(15) COMP-3.
       01 WS-ELAPSED-MS         PIC S9(9) COMP VALUE ZERO.
       01 WS-SLA-LIMIT-MS       PIC S9(9) COMP VALUE 180.

       01 WS-AUTH-DECISION      PIC X(2).
          88 WS-APPROVE          VALUE '00'.
          88 WS-DECLINE          VALUE '10'.
          88 WS-REVIEW           VALUE '20'.

       01 WS-CHIP-PIN           PIC X(1).
          88 WS-IS-CHIP-PIN      VALUE 'Y'.

       LINKAGE SECTION.
       01 DFHCOMMAREA           PIC X(200).

       PROCEDURE DIVISION.

           MOVE DFHCOMMAREA TO WS-COMMAREA.

      *--- Capture start time for SLA monitoring -------------------
           EXEC CICS ASKTIME
               ABSTIME(WS-START-TIME)
           END-EXEC.

      *--- Set real-time velocity limit (halved vs batch) ----------
           MOVE 5 TO WS-VELOCITY-LIMIT.

      *--- Run rules engine ----------------------------------------
           MOVE WS-COMMAREA TO WS-RULES-COMMAREA.

      *--- Skip customer profile check for chip+PIN to meet SLA ----
      *--- Risk accepted: BAU-2021-09. Profile deviation undetected -
      *--- for chip+PIN fraud. Flagged for remediation in 2024.    --
           MOVE CA-CHANNEL TO WS-CHIP-PIN.
           IF WS-IS-CHIP-PIN
               MOVE 0.0000 TO WS-WEIGHT-PROFILE
               MOVE 0.2500 TO WS-WEIGHT-AMOUNT
               MOVE 0.2500 TO WS-WEIGHT-MERCHANT
               MOVE 0.2500 TO WS-WEIGHT-VELOCITY
               MOVE 0.2500 TO WS-WEIGHT-WATCHLIST
           END-IF.

           CALL 'FDRULES' USING WS-RULES-COMMAREA.
           MOVE WS-RULES-COMMAREA TO WS-COMMAREA.

      *--- Check SLA compliance ------------------------------------
           EXEC CICS ASKTIME
               ABSTIME(WS-END-TIME)
           END-EXEC.
           COMPUTE WS-ELAPSED-MS =
               (WS-END-TIME - WS-START-TIME) / 1000.

           IF WS-ELAPSED-MS > WS-SLA-LIMIT-MS
               PERFORM LOG-SLA-BREACH
               MOVE '00' TO CA-RETURN-CODE
               MOVE 'SLA EXCEEDED - DEFAULTING TO APPROVE'
                   TO CA-MESSAGE
               PERFORM RETURN-TO-CALLER
           END-IF.

      *--- Map fraud score to authorisation decision ----------------
           EVALUATE TRUE
               WHEN CA-FRAUD-SCORE >= 0.9000
                   MOVE '10' TO WS-AUTH-DECISION
                   MOVE 'TRANSACTION DECLINED - HIGH FRAUD RISK'
                       TO CA-MESSAGE
               WHEN CA-FRAUD-SCORE >= WS-SCORE-THRESHOLD
                   MOVE '20' TO WS-AUTH-DECISION
                   MOVE 'TRANSACTION FLAGGED FOR REVIEW - ALLOWED'
                       TO CA-MESSAGE
                   MOVE WS-COMMAREA TO WS-ALERT-COMMAREA
                   CALL 'FDALERT' USING WS-ALERT-COMMAREA
               WHEN OTHER
                   MOVE '00' TO WS-AUTH-DECISION
                   MOVE 'TRANSACTION APPROVED' TO CA-MESSAGE
           END-EVALUATE.

           MOVE WS-AUTH-DECISION TO CA-RETURN-CODE.
           PERFORM RETURN-TO-CALLER.

      *=============================================================
       LOG-SLA-BREACH.
      *=============================================================
           EXEC SQL
               INSERT INTO FDDB.SLA_BREACH_LOG
                   (TXN_ID, ACCT_NO, ELAPSED_MS, BREACH_TS)
               VALUES
                   (:CA-TXN-ID, :CA-ACCT-NO,
                    :WS-ELAPSED-MS, CURRENT TIMESTAMP)
           END-EXEC.

      *=============================================================
       RETURN-TO-CALLER.
      *=============================================================
           MOVE WS-COMMAREA TO DFHCOMMAREA.
           EXEC CICS RETURN END-EXEC.
