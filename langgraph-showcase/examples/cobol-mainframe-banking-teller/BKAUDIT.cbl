       IDENTIFICATION DIVISION.
       PROGRAM-ID. BKAUDIT.
      *----------------------------------------------------------------*
      * AUDIT TRAIL WRITER                                              *
      * Writes a structured audit record to BANKDB.AUDIT_LOG (Db2).   *
      * Retained dual-write path to VSAM KSDS (BKAUDFL) is dead code: *
      * the VSAM file was decommissioned in Q3-2019 when Db2 became    *
      * the single audit store. The PERFORM WRITE-VSAM-AUDIT paragraph *
      * is never reached but was not removed during the cutover.       *
      *                                                                 *
      * Called via EXEC CICS LINK from BKTRXN after SYNCPOINT.        *
      * Runs in the same UOW as the calling transaction so that an    *
      * audit write failure causes the whole transaction to roll back. *
      *----------------------------------------------------------------*
       ENVIRONMENT DIVISION.
       DATA DIVISION.
       WORKING-STORAGE SECTION.

       COPY BKCOMMON.

       01 WS-AUDIT-DETAILS     PIC X(255).
       01 WS-BEFORE-BAL        PIC S9(13)V99 COMP-3 VALUE ZERO.
       01 WS-AFTER-BAL         PIC S9(13)V99 COMP-3 VALUE ZERO.
       01 WS-TIMESTAMP-OUT     PIC X(26).
       01 WS-AUDIT-SEQ         PIC S9(9) COMP VALUE ZERO.
       01 WS-WRITE-SWITCH      PIC X(1) VALUE 'D'.
          88 WS-WRITE-DB2       VALUE 'D'.
          88 WS-WRITE-VSAM      VALUE 'V'.

      *--- VSAM KSDS record layout (obsolete - BKAUDFL removed) ----
       01 WS-VSAM-AUDIT-REC.
          05 VA-KEY.
             10 VA-DATE         PIC X(10).
             10 VA-SEQ          PIC X(6).
          05 VA-TXN-REF         PIC X(16).
          05 VA-EVENT-TYPE      PIC X(20).
          05 VA-TELLER-ID       PIC X(8).
          05 VA-BEFORE-BAL      PIC S9(13)V99 COMP-3.
          05 VA-AFTER-BAL       PIC S9(13)V99 COMP-3.
          05 VA-DETAILS         PIC X(200).
       01 WS-VSAM-REC-LEN       PIC S9(4) COMP VALUE +271.
      *--- FCT entry BKAUDFL was removed from the CSD in 2019.  ----
      *--- Any attempt to EXEC CICS WRITE FILE('BKAUDFL') would ----
      *--- receive FILENOTFOUND and abend the transaction.       ----

       LINKAGE SECTION.
       01 DFHCOMMAREA           PIC X(200).

       PROCEDURE DIVISION.

           MOVE DFHCOMMAREA TO WS-COMMAREA.

      *--- Capture balances passed through COMMAREA ---------------
           MOVE CA-BALANCE-OUT  TO WS-BEFORE-BAL.
           MOVE CA-NEW-BALANCE  TO WS-AFTER-BAL.

      *--- Timestamp for audit record ----------------------------
           EXEC SQL
               VALUES(CHAR(CURRENT TIMESTAMP))
               INTO :WS-TIMESTAMP-OUT
               FROM SYSIBM.SYSDUMMY1
           END-EXEC.

      *--- Obtain next audit sequence number ---------------------
           EXEC SQL
               SELECT NEXT VALUE FOR BANKDB.AUDIT_SEQ
               INTO :WS-AUDIT-SEQ
               FROM SYSIBM.SYSDUMMY1
           END-EXEC.

           IF WS-SQLCODE NOT = 0
               MOVE '99' TO CA-RETURN-CODE
               MOVE 'AUDIT SEQ FETCH FAILED' TO CA-MESSAGE
               PERFORM RETURN-TO-CALLER
           END-IF.

      *--- Assemble details string --------------------------------
           STRING
               'FUNC=' DELIMITED SIZE
               CA-FUNCTION DELIMITED SPACE
               ' FROM=' DELIMITED SIZE
               CA-ACCT-FROM DELIMITED SPACE
               ' TO=' DELIMITED SIZE
               CA-ACCT-TO DELIMITED SPACE
               ' AMT=' DELIMITED SIZE
               CA-AMOUNT DELIMITED SIZE
               ' RC=' DELIMITED SIZE
               CA-RETURN-CODE DELIMITED SIZE
               INTO WS-AUDIT-DETAILS.

      *--- Write to Db2 AUDIT_LOG --------------------------------
           MOVE CA-TXN-REF       TO HV-AUD-TXN-REF.
           MOVE 'TELLER_TXN'     TO HV-AUD-EVENT-TYPE.
           MOVE WS-TIMESTAMP-OUT TO HV-AUD-EVENT-TS.
           MOVE CA-TELLER-ID     TO HV-AUD-TELLER-ID.
           MOVE WS-BEFORE-BAL    TO HV-AUD-BEFORE-BAL.
           MOVE WS-AFTER-BAL     TO HV-AUD-AFTER-BAL.
           MOVE WS-AUDIT-DETAILS TO HV-AUD-DETAILS.
           MOVE WS-AUDIT-SEQ     TO HV-AUD-ID.

           EXEC SQL
               INSERT INTO BANKDB.AUDIT_LOG
                   (AUD_ID, AUD_TXN_REF, EVENT_TYPE, EVENT_TS,
                    TELLER_ID, BEFORE_BAL, AFTER_BAL, DETAILS)
               VALUES
                   (:HV-AUD-ID, :HV-AUD-TXN-REF,
                    :HV-AUD-EVENT-TYPE, :HV-AUD-EVENT-TS,
                    :HV-AUD-TELLER-ID, :HV-AUD-BEFORE-BAL,
                    :HV-AUD-AFTER-BAL, :HV-AUD-DETAILS)
           END-EXEC.

           IF WS-SQLCODE NOT = 0
               MOVE '99' TO CA-RETURN-CODE
               MOVE 'AUDIT LOG INSERT FAILED' TO CA-MESSAGE
               PERFORM RETURN-TO-CALLER
           END-IF.

      *--- Dead code: VSAM dual-write path (never executed) ------
      *--- WS-WRITE-SWITCH is initialised to 'D' and never set   -
      *--- to 'V'; this paragraph is unreachable.                -
           IF WS-WRITE-VSAM
               PERFORM WRITE-VSAM-AUDIT
           END-IF.

           MOVE '00' TO CA-RETURN-CODE.
           PERFORM RETURN-TO-CALLER.

      *=============================================================
       WRITE-VSAM-AUDIT.
      *=============================================================
      *--- DEAD CODE - BKAUDFL FCT entry removed Q3-2019 ----------
           INITIALIZE WS-VSAM-AUDIT-REC.
           MOVE WS-TIMESTAMP-OUT(1:10) TO VA-DATE.
           MOVE WS-AUDIT-SEQ           TO VA-SEQ.
           MOVE CA-TXN-REF             TO VA-TXN-REF.
           MOVE 'TELLER_TXN'           TO VA-EVENT-TYPE.
           MOVE CA-TELLER-ID           TO VA-TELLER-ID.
           MOVE WS-BEFORE-BAL          TO VA-BEFORE-BAL.
           MOVE WS-AFTER-BAL           TO VA-AFTER-BAL.
           MOVE WS-AUDIT-DETAILS       TO VA-DETAILS.

           EXEC CICS WRITE
               FILE('BKAUDFL')
               FROM(WS-VSAM-AUDIT-REC)
               LENGTH(WS-VSAM-REC-LEN)
               RIDFLD(VA-KEY)
               RESP(WS-CICS-RESP)
           END-EXEC.

           IF WS-CICS-RESP NOT = DFHRESP(NORMAL)
               MOVE '99' TO CA-RETURN-CODE
               MOVE 'VSAM AUDIT WRITE FAILED' TO CA-MESSAGE
           END-IF.

       RETURN-TO-CALLER.
           MOVE WS-COMMAREA TO DFHCOMMAREA.
           EXEC CICS RETURN END-EXEC.
