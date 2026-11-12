       IDENTIFICATION DIVISION.
       PROGRAM-ID. FDARCHIVE.
      *----------------------------------------------------------------*
      * FRAUD DETECTION - CASE ARCHIVER (DEAD CODE)                    *
      * Originally wrote closed fraud cases to a flat-file archive on  *
      * the z/OS HFS. Replaced by the central CASEDB case management  *
      * system in 2021. No program in this estate calls FDARCHIVE.    *
      * It was retained because removing COBOL programs from the JCL  *
      * library required a change-freeze approval that was never filed.*
      *                                                                *
      * DO NOT USE - this program will be removed in the next         *
      * planned maintenance window (originally scheduled Q1-2022,     *
      * repeatedly deferred due to change freeze).                    *
      *----------------------------------------------------------------*
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT ARCHIVE-FILE
               ASSIGN TO 'FDARC001'
               ORGANIZATION IS SEQUENTIAL
               ACCESS MODE IS SEQUENTIAL
               FILE STATUS IS WS-ARC-STATUS.

       DATA DIVISION.
       FILE SECTION.
       FD  ARCHIVE-FILE.
       01  ARCHIVE-RECORD       PIC X(200).

       WORKING-STORAGE SECTION.

       COPY FDCOMMON.

       01 WS-ARC-STATUS         PIC X(2).
          88 WS-ARC-OK           VALUE '00'.

       01 WS-ARCHIVE-REC.
          05 AR-CASE-ID          PIC X(16).
          05 AR-TXN-ID           PIC X(16).
          05 AR-ACCT-NO          PIC X(10).
          05 AR-FRAUD-SCORE      PIC X(8).
          05 AR-DECISION         PIC X(10).
          05 AR-ANALYST-ID       PIC X(8).
          05 AR-CLOSED-TS        PIC X(26).
          05 AR-NOTES            PIC X(100).
          05 FILLER              PIC X(6).

       01 WS-CASE-COUNT          PIC S9(9) COMP VALUE ZERO.
       01 WS-ARCHIVE-TS          PIC X(26).

       LINKAGE SECTION.
       01 DFHCOMMAREA            PIC X(200).

       PROCEDURE DIVISION.

           MOVE DFHCOMMAREA TO WS-COMMAREA.

      *--- Fetch closed cases pending archive ----------------------
           EXEC SQL
               SELECT COUNT(*)
               INTO  :WS-CASE-COUNT
               FROM  FDDB.FRAUD_ALERTS
               WHERE ALERT_STATUS = 'CLOSED   '
               AND   ARCHIVED_FLAG = 'N'
           END-EXEC.

           IF WS-CASE-COUNT = ZERO
               MOVE '00' TO CA-RETURN-CODE
               MOVE 'NO CASES TO ARCHIVE' TO CA-MESSAGE
               PERFORM RETURN-TO-CALLER
           END-IF.

      *--- Open archive output file and write one record per case ---
           PERFORM VARYING WS-IDX FROM 1 BY 1
               UNTIL WS-IDX > WS-CASE-COUNT

               OPEN OUTPUT ARCHIVE-FILE

               EXEC SQL
                   SELECT ALERT_ID, TXN_ID, ACCT_NO,
                          FRAUD_SCORE, ALERT_STATUS
                   INTO  :HV-ALERT-ID, :HV-TXN-ID, :HV-ACCT-NO,
                         :HV-FRAUD-SCORE, :HV-ALERT-STATUS
                   FROM  FDDB.FRAUD_ALERTS
                   WHERE ARCHIVED_FLAG = 'N'
                   AND   ALERT_STATUS  = 'CLOSED   '
                   FETCH FIRST 1 ROW ONLY
               END-EXEC

               MOVE HV-TXN-ID         TO AR-TXN-ID
               MOVE HV-ACCT-NO        TO AR-ACCT-NO
               MOVE HV-FRAUD-SCORE    TO AR-FRAUD-SCORE
               MOVE HV-ALERT-STATUS   TO AR-DECISION

               WRITE ARCHIVE-RECORD FROM WS-ARCHIVE-REC

               CLOSE ARCHIVE-FILE

               EXEC SQL
                   UPDATE FDDB.FRAUD_ALERTS
                   SET    ARCHIVED_FLAG = 'Y',
                          ARCHIVE_TS    = CURRENT TIMESTAMP
                   WHERE  ALERT_ID      = :HV-ALERT-ID
               END-EXEC

           END-PERFORM.

           MOVE '00' TO CA-RETURN-CODE.
           PERFORM RETURN-TO-CALLER.

      *=============================================================
       RETURN-TO-CALLER.
      *=============================================================
           MOVE WS-COMMAREA TO DFHCOMMAREA.
           EXEC CICS RETURN END-EXEC.
