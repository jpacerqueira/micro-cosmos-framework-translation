       IDENTIFICATION DIVISION.
       PROGRAM-ID. FDTXNMON.
      *----------------------------------------------------------------*
      * FRAUD DETECTION - TRANSACTION MONITOR                          *
      * Entry point for the batch fraud screening pipeline.           *
      * Reads pending transactions from FDDB.TXN_QUEUE, submits each  *
      * to the rules engine via CALL 'FDRULES', and routes flagged     *
      * transactions to the alert writer via CALL 'FDALERT'.          *
      *                                                                *
      * Business invariants:                                           *
      *   - Only transactions with STATUS = 'P' (pending) are scored  *
      *   - A score >= WS-SCORE-THRESHOLD triggers a fraud alert      *
      *   - Every processed transaction is stamped with PROC_TS       *
      *   - Batch runs daily at 02:00 via JCL job FDBATCH01           *
      *----------------------------------------------------------------*
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT TXN-BATCH-FILE
               ASSIGN TO 'FDTXNIN'
               ORGANIZATION IS SEQUENTIAL
               ACCESS MODE IS SEQUENTIAL
               FILE STATUS IS WS-FILE-STATUS.

       DATA DIVISION.
       FILE SECTION.
       FD  TXN-BATCH-FILE.
       01  TXN-BATCH-RECORD     PIC X(200).

       WORKING-STORAGE SECTION.

       COPY FDCOMMON.

       01 WS-FILE-STATUS        PIC X(2).
          88 WS-FILE-OK           VALUE '00'.
          88 WS-FILE-EOF          VALUE '10'.

       01 WS-BATCH-COUNTERS.
          05 WS-READ-COUNT       PIC S9(9) COMP VALUE ZERO.
          05 WS-SCORED-COUNT     PIC S9(9) COMP VALUE ZERO.
          05 WS-FLAGGED-COUNT    PIC S9(9) COMP VALUE ZERO.
          05 WS-ERROR-COUNT      PIC S9(9) COMP VALUE ZERO.

       01 WS-TXN-TABLE.
          05 WS-TXN-ENTRY OCCURS 500 TIMES
                          INDEXED BY WS-TXN-IDX.
             10 WT-TXN-ID        PIC X(16).
             10 WT-ACCT-NO       PIC X(10).
             10 WT-AMOUNT        PIC S9(13)V99 COMP-3.
             10 WT-MERCHANT      PIC X(8).
             10 WT-CHANNEL       PIC X(8).
             10 WT-COUNTRY       PIC X(3).

       01 WS-MAX-TXN             PIC S9(4) COMP VALUE ZERO.
       01 WS-RULES-COMMAREA      PIC X(200).
       01 WS-ALERT-COMMAREA      PIC X(200).

       LINKAGE SECTION.
       01 DFHCOMMAREA            PIC X(200).

       PROCEDURE DIVISION.

      *--- Load pending transactions into working table --------------
           PERFORM LOAD-TXN-BATCH.

           IF WS-MAX-TXN = ZERO
               MOVE '00' TO CA-RETURN-CODE
               MOVE 'NO PENDING TRANSACTIONS IN BATCH' TO CA-MESSAGE
               PERFORM RETURN-TO-CALLER
           END-IF.

      *--- Score each transaction through the rules engine -----------
           PERFORM VARYING WS-TXN-IDX FROM 1 BY 1
               UNTIL WS-TXN-IDX > WS-MAX-TXN

               MOVE WT-TXN-ID(WS-TXN-IDX)    TO CA-TXN-ID
               MOVE WT-ACCT-NO(WS-TXN-IDX)   TO CA-ACCT-NO
               MOVE WT-AMOUNT(WS-TXN-IDX)    TO CA-TXN-AMOUNT
               MOVE WT-MERCHANT(WS-TXN-IDX)  TO CA-MERCHANT-CODE
               MOVE WT-CHANNEL(WS-TXN-IDX)   TO CA-CHANNEL
               MOVE WT-COUNTRY(WS-TXN-IDX)   TO CA-TXN-COUNTRY

               MOVE WS-COMMAREA TO WS-RULES-COMMAREA
               CALL 'FDRULES' USING WS-RULES-COMMAREA
               MOVE WS-RULES-COMMAREA TO WS-COMMAREA

               ADD 1 TO WS-SCORED-COUNT

               IF CA-FRAUD-YES
                   MOVE WS-COMMAREA TO WS-ALERT-COMMAREA
                   CALL 'FDALERT' USING WS-ALERT-COMMAREA
                   ADD 1 TO WS-FLAGGED-COUNT
               END-IF

               PERFORM STAMP-TRANSACTION-PROCESSED

           END-PERFORM.

           MOVE '00' TO CA-RETURN-CODE.
           STRING 'BATCH COMPLETE: SCORED='
               DELIMITED SIZE
               WS-SCORED-COUNT DELIMITED SIZE
               ' FLAGGED=' DELIMITED SIZE
               WS-FLAGGED-COUNT DELIMITED SIZE
               INTO CA-MESSAGE.

           PERFORM RETURN-TO-CALLER.

      *=============================================================
       LOAD-TXN-BATCH.
      *=============================================================
           MOVE ZERO TO WS-MAX-TXN.

           EXEC SQL
               SELECT COUNT(*)
               INTO  :WS-MAX-TXN
               FROM  FDDB.TXN_QUEUE
               WHERE TXN_STATUS = 'P'
           END-EXEC.

           IF WS-SQLCODE NOT = 0 OR WS-MAX-TXN = ZERO
               EXIT PARAGRAPH
           END-IF.

           IF WS-MAX-TXN > 500
               MOVE 500 TO WS-MAX-TXN
           END-IF.

           EXEC SQL
               SELECT TXN_ID, ACCT_NO, TXN_AMOUNT,
                      MERCHANT_CODE, CHANNEL, TXN_COUNTRY
               INTO  :WT-TXN-ID(1), :WT-ACCT-NO(1),
                     :WT-AMOUNT(1),  :WT-MERCHANT(1),
                     :WT-CHANNEL(1), :WT-COUNTRY(1)
               FROM  FDDB.TXN_QUEUE
               WHERE TXN_STATUS = 'P'
               FETCH FIRST 500 ROWS ONLY
           END-EXEC.

      *=============================================================
       STAMP-TRANSACTION-PROCESSED.
      *=============================================================
           EXEC SQL
               UPDATE FDDB.TXN_QUEUE
               SET    TXN_STATUS = 'S',
                      PROC_TS    = CURRENT TIMESTAMP
               WHERE  TXN_ID     = :CA-TXN-ID
           END-EXEC.

      *=============================================================
       RETURN-TO-CALLER.
      *=============================================================
           MOVE WS-COMMAREA TO DFHCOMMAREA.
           EXEC CICS RETURN END-EXEC.
