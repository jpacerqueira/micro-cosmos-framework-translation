       IDENTIFICATION DIVISION.
       PROGRAM-ID. FDNOTIFY.
      *----------------------------------------------------------------*
      * FRAUD DETECTION - REAL-TIME MQ NOTIFICATION                    *
      * Called by FDALERT after a fraud alert is written to Db2.      *
      * Puts a JSON message onto the IBM MQ queue FDCASEMQ so the     *
      * case management system can pick up the alert in real time.    *
      *                                                                *
      * Business invariants:                                           *
      *   - Message must be put before SYNCPOINT in the calling UOW   *
      *   - A failed MQ put is logged but does not fail the alert     *
      *   - Message format is JSON built by STRING concatenation      *
      *     (acknowledged tech debt — a proper serialiser was never   *
      *     introduced; see CHG-2019-0088)                            *
      *   - Queue manager: FDQM01, queue: FRAUD.ALERT.QUEUE           *
      *                                                                *
      * Dead code:                                                     *
      *   - WRITE-FALLBACK-QUEUE used a CICS TS queue as a fallback   *
      *     if MQ was unavailable. The TS queue consumer              *
      *     (FDBATCH04) was decommissioned in 2023 when the MQ        *
      *     cluster was made HA. The fallback branch is never taken   *
      *     because WS-MQ-FALLBACK is always 'N' at runtime.         *
      *----------------------------------------------------------------*
       ENVIRONMENT DIVISION.
       DATA DIVISION.
       WORKING-STORAGE SECTION.

       COPY FDCOMMON.

       01 WS-MQ-PARAMS.
          05 WS-MQ-QMGR         PIC X(48) VALUE 'FDQM01'.
          05 WS-MQ-QUEUE         PIC X(48) VALUE 'FRAUD.ALERT.QUEUE'.
          05 WS-MQ-HCONN         PIC S9(9) COMP VALUE ZERO.
          05 WS-MQ-HOBJ          PIC S9(9) COMP VALUE ZERO.
          05 WS-MQ-COMPCODE      PIC S9(9) COMP VALUE ZERO.
          05 WS-MQ-REASON        PIC S9(9) COMP VALUE ZERO.
          05 WS-MQ-MSGLEN        PIC S9(9) COMP VALUE ZERO.

      *--- JSON payload built by STRING concatenation ---------------
      *--- CHG-2019-0088: Should use a proper JSON serialiser.     --
      *--- Fixed-length buffer risks silent truncation on large    --
      *--- field values; introduced when the case management API   --
      *--- was first built and never refactored.                   --
       01 WS-JSON-BUFFER         PIC X(512) VALUE SPACES.
       01 WS-JSON-LEN            PIC S9(4) COMP VALUE ZERO.
       01 WS-SCORE-DISPLAY       PIC Z9.9999.
       01 WS-AMOUNT-DISPLAY      PIC ZZZ,ZZZ,ZZ9.99.

       01 WS-MQ-FALLBACK         PIC X(1) VALUE 'N'.
          88 WS-USE-FALLBACK      VALUE 'Y'.
          88 WS-NO-FALLBACK       VALUE 'N'.
      *--- TS queue consumer FDBATCH04 decommissioned 2023. --------
      *--- WS-MQ-FALLBACK is initialised to 'N' and never set 'Y'. -

       LINKAGE SECTION.
       01 DFHCOMMAREA            PIC X(200).

       PROCEDURE DIVISION.

           MOVE DFHCOMMAREA TO WS-COMMAREA.
           MOVE ZERO TO WS-MQ-COMPCODE.
           MOVE ZERO TO WS-MQ-REASON.

      *--- Build JSON payload by string concatenation ---------------
      *--- Known tech debt: fixed buffer, no escaping, no library. --
           MOVE CA-FRAUD-SCORE  TO WS-SCORE-DISPLAY.
           MOVE CA-TXN-AMOUNT   TO WS-AMOUNT-DISPLAY.
           MOVE SPACES TO WS-JSON-BUFFER.

           STRING
               '{"alert_id":"'   DELIMITED SIZE
               HV-ALERT-ID       DELIMITED SIZE
               '","txn_id":"'    DELIMITED SIZE
               CA-TXN-ID         DELIMITED SPACE
               '","acct_no":"'   DELIMITED SIZE
               CA-ACCT-NO        DELIMITED SPACE
               '","amount":'     DELIMITED SIZE
               WS-AMOUNT-DISPLAY DELIMITED SPACE
               ',"score":'       DELIMITED SIZE
               WS-SCORE-DISPLAY  DELIMITED SPACE
               ',"channel":"'    DELIMITED SIZE
               CA-CHANNEL        DELIMITED SPACE
               '","country":"'   DELIMITED SIZE
               CA-TXN-COUNTRY    DELIMITED SPACE
               '","status":"PENDING"}'
                                 DELIMITED SIZE
               INTO WS-JSON-BUFFER.

           INSPECT WS-JSON-BUFFER
               TALLYING WS-JSON-LEN FOR CHARACTERS
               BEFORE INITIAL SPACE.

      *--- Connect to MQ queue manager -----------------------------
           EXEC CICS LINK
               PROGRAM('CSQCMQP')
               COMMAREA(WS-MQ-PARAMS)
               LENGTH(WS-COMMAREA-LEN)
               RESP(WS-CICS-RESP)
           END-EXEC.

           IF WS-MQ-COMPCODE NOT = ZERO
               PERFORM LOG-MQ-FAILURE
               PERFORM RETURN-TO-CALLER
           END-IF.

      *--- Put message to FRAUD.ALERT.QUEUE ------------------------
           EXEC CICS LINK
               PROGRAM('CSQCPUTH')
               COMMAREA(WS-MQ-PARAMS)
               LENGTH(WS-COMMAREA-LEN)
               RESP(WS-CICS-RESP)
           END-EXEC.

           IF WS-MQ-COMPCODE NOT = ZERO
               PERFORM LOG-MQ-FAILURE
           END-IF.

      *--- Dead code: TS queue fallback (never executed) -----------
      *--- WS-MQ-FALLBACK is always 'N'; branch never taken.      --
           IF WS-USE-FALLBACK
               PERFORM WRITE-FALLBACK-QUEUE
           END-IF.

           PERFORM RETURN-TO-CALLER.

      *=============================================================
       LOG-MQ-FAILURE.
      *=============================================================
           EXEC SQL
               INSERT INTO FDDB.MQ_FAILURE_LOG
                   (TXN_ID, ACCT_NO, REASON_CODE, FAILED_TS)
               VALUES
                   (:CA-TXN-ID, :CA-ACCT-NO,
                    :WS-MQ-REASON, CURRENT TIMESTAMP)
           END-EXEC.

      *=============================================================
       WRITE-FALLBACK-QUEUE.
      *=============================================================
      *--- DEAD CODE - FDBATCH04 TS queue consumer removed 2023 ---
           EXEC CICS WRITEQ TS
               QUEUE('FDTSFALL')
               FROM(WS-JSON-BUFFER)
               LENGTH(WS-JSON-LEN)
               RESP(WS-CICS-RESP)
           END-EXEC.

           IF WS-CICS-RESP NOT = DFHRESP(NORMAL)
               MOVE '99' TO CA-RETURN-CODE
               MOVE 'TS FALLBACK QUEUE WRITE FAILED' TO CA-MESSAGE
           END-IF.

      *=============================================================
       RETURN-TO-CALLER.
      *=============================================================
           MOVE WS-COMMAREA TO DFHCOMMAREA.
           EXEC CICS RETURN END-EXEC.
