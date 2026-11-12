       IDENTIFICATION DIVISION.
       PROGRAM-ID. FDALERT.
      *----------------------------------------------------------------*
      * FRAUD DETECTION - ALERT WRITER                                 *
      * Called by FDTXNMON for every transaction that scores above     *
      * WS-SCORE-THRESHOLD. Writes an alert row to FDDB.FRAUD_ALERTS  *
      * and notifies the case management team via CICS queue.         *
      *                                                                *
      * Business invariants:                                           *
      *   - Every alert must have a unique ALERT_ID from FDDB.FD_SEQ  *
      *   - Alert status is set to PENDING on creation                *
      *   - DB2 write and CICS WRITEQ are wrapped in one SYNCPOINT    *
      *   - Any DB2 failure triggers SYNCPOINT ROLLBACK               *
      *                                                                *
      * Dead code:                                                     *
      *   - WRITE-VSAM-ALERT paragraph was the original flat-file     *
      *     alert log. FDALTFL was decommissioned in 2022 when the    *
      *     central case management system (CASEDB) became the single *
      *     store. The PERFORM WRITE-VSAM-ALERT branch is never taken *
      *     because WS-WRITE-SWITCH is always 'D' at runtime.        *
      *----------------------------------------------------------------*
       ENVIRONMENT DIVISION.
       DATA DIVISION.
       WORKING-STORAGE SECTION.

       COPY FDCOMMON.

       01 WS-ALERT-SEQ          PIC S9(9) COMP VALUE ZERO.
       01 WS-WRITE-SWITCH       PIC X(1) VALUE 'D'.
          88 WS-WRITE-DB2        VALUE 'D'.
          88 WS-WRITE-VSAM       VALUE 'V'.
       01 WS-QUEUE-DATA         PIC X(80).
       01 WS-QUEUE-LEN          PIC S9(4) COMP VALUE +80.
       01 WS-ALERT-TIMESTAMP    PIC X(26).
       01 WS-NOTIFY-COMMAREA    PIC X(200).

       LINKAGE SECTION.
       01 DFHCOMMAREA           PIC X(200).

       PROCEDURE DIVISION.

           MOVE DFHCOMMAREA TO WS-COMMAREA.

      *--- Obtain next alert sequence number -----------------------
           EXEC SQL
               SELECT NEXT VALUE FOR FDDB.FD_SEQ
               INTO :WS-ALERT-SEQ
               FROM SYSIBM.SYSDUMMY1
           END-EXEC.

           IF WS-SQLCODE NOT = 0
               MOVE '99' TO CA-RETURN-CODE
               MOVE 'ALERT SEQ FETCH FAILED' TO CA-MESSAGE
               PERFORM RETURN-TO-CALLER
           END-IF.

      *--- Timestamp for this alert --------------------------------
           EXEC SQL
               VALUES(CHAR(CURRENT TIMESTAMP))
               INTO :WS-ALERT-TIMESTAMP
               FROM SYSIBM.SYSDUMMY1
           END-EXEC.

      *--- Write alert to Db2 FRAUD_ALERTS -------------------------
           MOVE WS-ALERT-SEQ      TO HV-ALERT-ID.
           MOVE CA-TXN-ID         TO HV-TXN-ID.
           MOVE CA-ACCT-NO        TO HV-ACCT-NO.
           MOVE CA-TXN-AMOUNT     TO HV-TXN-AMOUNT.
           MOVE CA-FRAUD-SCORE    TO HV-FRAUD-SCORE.
           MOVE 'PENDING   '      TO HV-ALERT-STATUS.

           EXEC SQL
               INSERT INTO FDDB.FRAUD_ALERTS
                   (ALERT_ID, TXN_ID, ACCT_NO, TXN_AMOUNT,
                    FRAUD_SCORE, ALERT_STATUS, CREATED_TS)
               VALUES
                   (:HV-ALERT-ID, :HV-TXN-ID, :HV-ACCT-NO,
                    :HV-TXN-AMOUNT, :HV-FRAUD-SCORE,
                    :HV-ALERT-STATUS, CURRENT TIMESTAMP)
           END-EXEC.

           IF WS-SQLCODE NOT = 0
               MOVE '99' TO CA-RETURN-CODE
               MOVE 'FRAUD ALERT INSERT FAILED' TO CA-MESSAGE
               PERFORM ROLLBACK-AND-RETURN
           END-IF.

      *--- Notify case management team via CICS queue ---------------
           STRING 'ALERT:' DELIMITED SIZE
               WS-ALERT-SEQ DELIMITED SIZE
               ' TXN:' DELIMITED SIZE
               CA-TXN-ID DELIMITED SPACE
               ' SCORE:' DELIMITED SIZE
               CA-FRAUD-SCORE DELIMITED SIZE
               INTO WS-QUEUE-DATA.

           EXEC CICS WRITEQ TS
               QUEUE('FDCASEMQ')
               FROM(WS-QUEUE-DATA)
               LENGTH(WS-QUEUE-LEN)
               RESP(WS-CICS-RESP)
           END-EXEC.

      *--- Notify case management via MQ ----------------------------
           MOVE WS-COMMAREA TO WS-NOTIFY-COMMAREA.
           CALL 'FDNOTIFY' USING WS-NOTIFY-COMMAREA.

      *--- Dead code: VSAM dual-write path (never executed) ---------
      *--- WS-WRITE-SWITCH is initialised to 'D' and never set     --
      *--- to 'V'; this paragraph is unreachable at runtime.       --
           IF WS-WRITE-VSAM
               PERFORM WRITE-VSAM-ALERT
           END-IF.

           EXEC CICS SYNCPOINT
               RESP(WS-CICS-RESP)
           END-EXEC.

           MOVE WS-ALERT-SEQ TO HV-ALERT-ID.
           MOVE '00' TO CA-RETURN-CODE.
           MOVE 'FRAUD ALERT WRITTEN SUCCESSFULLY' TO CA-MESSAGE.
           PERFORM RETURN-TO-CALLER.

      *=============================================================
       WRITE-VSAM-ALERT.
      *=============================================================
      *--- DEAD CODE - FDALTFL FCT entry removed 2022 --------------
           INITIALIZE WS-VSAM-ALERT-REC.
           MOVE WS-ALERT-TIMESTAMP(1:10)  TO VA-DATE.
           MOVE WS-ALERT-SEQ              TO VA-SEQ.
           MOVE CA-TXN-ID                 TO VA-TXN-ID.
           MOVE CA-ACCT-NO                TO VA-ACCT-NO.
           MOVE CA-FRAUD-SCORE            TO VA-FRAUD-SCORE.
           MOVE 'PENDING   '              TO VA-STATUS.

           EXEC CICS WRITE
               FILE('FDALTFL')
               FROM(WS-VSAM-ALERT-REC)
               LENGTH(WS-VSAM-REC-LEN)
               RIDFLD(VA-KEY)
               RESP(WS-CICS-RESP)
           END-EXEC.

           IF WS-CICS-RESP NOT = DFHRESP(NORMAL)
               MOVE '99' TO CA-RETURN-CODE
               MOVE 'VSAM ALERT WRITE FAILED' TO CA-MESSAGE
           END-IF.

      *=============================================================
       ROLLBACK-AND-RETURN.
      *=============================================================
           EXEC CICS SYNCPOINT ROLLBACK
               RESP(WS-CICS-RESP)
           END-EXEC.
           PERFORM RETURN-TO-CALLER.

      *=============================================================
       RETURN-TO-CALLER.
      *=============================================================
           MOVE WS-COMMAREA TO DFHCOMMAREA.
           EXEC CICS RETURN END-EXEC.
