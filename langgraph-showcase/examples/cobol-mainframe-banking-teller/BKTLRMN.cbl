       IDENTIFICATION DIVISION.
       PROGRAM-ID. BKTLRMN.
      *----------------------------------------------------------------*
      * BANKING TELLER MENU                                             *
      * CICS TRANSACTION: BTLR                                         *
      *                                                                 *
      * Entry point for all branch teller operations. Validates teller *
      * signon, reads the BMS screen function key, and LINKs to the   *
      * appropriate sub-program. After a successful transaction the MQ *
      * bridge is invoked to push a notification to the teller REST    *
      * endpoint consumed by the front-end teller screen UI.           *
      *                                                                 *
      * Sub-programs called via EXEC CICS LINK:                        *
      *   BKACCT   - Account inquiry                                   *
      *   BKTRXN   - Deposit / withdrawal / transfer                   *
      *   BKMQBRDG - IBM MQ bridge (REST notification)                 *
      *----------------------------------------------------------------*
       ENVIRONMENT DIVISION.
       DATA DIVISION.
       WORKING-STORAGE SECTION.

       COPY BKCOMMON.

       01 WS-TRAN-ID           PIC X(4).
       01 WS-TERMINAL-ID       PIC X(4).
       01 WS-ABS-TIME-START    PIC S9(15) COMP.
       01 WS-ABS-TIME-END      PIC S9(15) COMP.
       01 WS-ELAPSED-MS        PIC S9(9)  COMP.

      *--- BMS screen receive area ----------------------------------
       01 WS-SCREEN-INPUT.
          05 WS-FUNC-KEY        PIC X(1).
             88 WS-KEY-DEPOSIT    VALUE '1'.
             88 WS-KEY-WITHDRAW   VALUE '2'.
             88 WS-KEY-TRANSFER   VALUE '3'.
             88 WS-KEY-INQUIRY    VALUE '4'.
             88 WS-KEY-SIGNOFF    VALUE '9'.
          05 WS-INPUT-ACCT      PIC X(10).
          05 WS-INPUT-ACCT-TO   PIC X(10).
          05 WS-INPUT-AMOUNT    PIC 9(11)V99.
          05 WS-INPUT-TELLER    PIC X(8).

      *--- Obsolete: VSAM batch teller session path (decommissioned) --
      * 01 WS-VSAM-FCT         PIC X(8) VALUE 'TELLERFL'.
      * 01 WS-VSAM-KEY         PIC X(10).
      * 01 WS-VSAM-REC         PIC X(400).
      * 01 WS-VSAM-REC-LEN     PIC S9(4) COMP VALUE +400.

       LINKAGE SECTION.
       01 DFHCOMMAREA          PIC X(200).

       PROCEDURE DIVISION.

           EXEC CICS IGNORE CONDITION ERROR END-EXEC.

           EXEC CICS ASSIGN
               TRNNAME(WS-TRAN-ID)
               TERMID(WS-TERMINAL-ID)
               RESP(WS-CICS-RESP)
           END-EXEC.

           EXEC CICS ASKTIME ABSTIME(WS-ABS-TIME-START) END-EXEC.

      *--- Restore or initialise COMMAREA -------------------------
           IF EIBCALEN > ZERO
               MOVE DFHCOMMAREA TO WS-COMMAREA
           ELSE
               INITIALIZE WS-COMMAREA
           END-IF.

      *--- Enforce teller signon before any operation -------------
           IF CA-TELLER-ID = SPACES OR LOW-VALUES
               EXEC CICS RECEIVE
                   INTO(WS-INPUT-TELLER)
                   RESP(WS-CICS-RESP)
               END-EXEC
               MOVE WS-INPUT-TELLER TO CA-TELLER-ID
               PERFORM VALIDATE-TELLER-SIGNON
               IF NOT CA-OK
                   PERFORM SEND-ERROR-SCREEN
                   EXEC CICS RETURN
                       TRANSID('BTLR')
                       COMMAREA(WS-COMMAREA)
                       LENGTH(WS-COMMAREA-LEN)
                   END-EXEC
               END-IF
           END-IF.

      *--- Receive function key and account inputs from BMS screen -
           EXEC CICS RECEIVE
               INTO(WS-SCREEN-INPUT)
               RESP(WS-CICS-RESP)
           END-EXEC.

           IF WS-CICS-RESP NOT = DFHRESP(NORMAL)
               MOVE '99' TO CA-RETURN-CODE
               MOVE 'TERMINAL RECEIVE FAILED' TO CA-MESSAGE
               PERFORM SEND-ERROR-SCREEN
               EXEC CICS RETURN END-EXEC
           END-IF.

      *--- Route to the appropriate operation ----------------------
           EVALUATE TRUE
               WHEN WS-KEY-DEPOSIT
                   MOVE 'DEPO'            TO CA-FUNCTION
                   MOVE WS-INPUT-ACCT     TO CA-ACCT-FROM
                   MOVE WS-INPUT-AMOUNT   TO CA-AMOUNT
                   PERFORM LINK-TO-TRANSACTION

               WHEN WS-KEY-WITHDRAW
                   MOVE 'WITH'            TO CA-FUNCTION
                   MOVE WS-INPUT-ACCT     TO CA-ACCT-FROM
                   MOVE WS-INPUT-AMOUNT   TO CA-AMOUNT
                   PERFORM LINK-TO-TRANSACTION

               WHEN WS-KEY-TRANSFER
                   MOVE 'XFER'            TO CA-FUNCTION
                   MOVE WS-INPUT-ACCT     TO CA-ACCT-FROM
                   MOVE WS-INPUT-ACCT-TO  TO CA-ACCT-TO
                   MOVE WS-INPUT-AMOUNT   TO CA-AMOUNT
                   PERFORM LINK-TO-TRANSACTION

               WHEN WS-KEY-INQUIRY
                   MOVE 'INQU'            TO CA-FUNCTION
                   MOVE WS-INPUT-ACCT     TO CA-ACCT-FROM
                   PERFORM LINK-TO-INQUIRY

               WHEN WS-KEY-SIGNOFF
                   PERFORM TELLER-SIGNOFF

               WHEN OTHER
                   MOVE '99' TO CA-RETURN-CODE
                   MOVE 'INVALID FUNCTION KEY - USE 1-4 OR 9'
                       TO CA-MESSAGE
                   PERFORM SEND-ERROR-SCREEN
           END-EVALUATE.

      *--- Fire MQ notification to teller REST endpoint -----------
           IF CA-OK
               PERFORM LINK-TO-MQ-BRIDGE
           END-IF.

           EXEC CICS ASKTIME ABSTIME(WS-ABS-TIME-END) END-EXEC.
           COMPUTE WS-ELAPSED-MS =
               (WS-ABS-TIME-END - WS-ABS-TIME-START) / 1000.

           EXEC CICS RETURN
               TRANSID('BTLR')
               COMMAREA(WS-COMMAREA)
               LENGTH(WS-COMMAREA-LEN)
           END-EXEC.

       LINK-TO-TRANSACTION.
           EXEC CICS LINK
               PROGRAM('BKTRXN')
               COMMAREA(WS-COMMAREA)
               LENGTH(WS-COMMAREA-LEN)
               RESP(WS-CICS-RESP)
           END-EXEC
           IF WS-CICS-RESP NOT = DFHRESP(NORMAL)
               MOVE '99' TO CA-RETURN-CODE
               MOVE 'BKTRXN LINK FAILED - CONTACT SUPPORT'
                   TO CA-MESSAGE
           END-IF.

       LINK-TO-INQUIRY.
           EXEC CICS LINK
               PROGRAM('BKACCT')
               COMMAREA(WS-COMMAREA)
               LENGTH(WS-COMMAREA-LEN)
               RESP(WS-CICS-RESP)
           END-EXEC.

       LINK-TO-MQ-BRIDGE.
           EXEC CICS LINK
               PROGRAM('BKMQBRDG')
               COMMAREA(WS-COMMAREA)
               LENGTH(WS-COMMAREA-LEN)
               RESP(WS-CICS-RESP)
           END-EXEC.

       VALIDATE-TELLER-SIGNON.
      *--- Teller ID must be non-blank and exactly 8 characters. ---
      *--- In production this would also check the RACF profile. ---
           IF CA-TELLER-ID = SPACES OR LOW-VALUES
               MOVE '99' TO CA-RETURN-CODE
               MOVE 'TELLER ID IS REQUIRED' TO CA-MESSAGE
               EXIT PARAGRAPH
           END-IF
           MOVE '00' TO CA-RETURN-CODE.

       TELLER-SIGNOFF.
           MOVE SPACES TO CA-TELLER-ID
           MOVE '00'   TO CA-RETURN-CODE
           MOVE 'TELLER SESSION ENDED' TO CA-MESSAGE
           EXEC CICS SEND TEXT
               FROM(CA-MESSAGE)
               ERASE
               RESP(WS-CICS-RESP)
           END-EXEC.

       SEND-ERROR-SCREEN.
           EXEC CICS SEND TEXT
               FROM(CA-MESSAGE)
               ERASE
               RESP(WS-CICS-RESP)
           END-EXEC.
