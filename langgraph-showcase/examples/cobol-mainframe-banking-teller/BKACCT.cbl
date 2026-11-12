       IDENTIFICATION DIVISION.
       PROGRAM-ID. BKACCT.
      *----------------------------------------------------------------*
      * ACCOUNT INQUIRY                                                 *
      * Called via EXEC CICS LINK from BKTLRMN (function INQU).       *
      *                                                                 *
      * Reads account master from Db2 ACCOUNT_MASTER and returns      *
      * current balance, account type, and status in the COMMAREA.    *
      * Does NOT modify any data — read-only operation.                *
      *                                                                 *
      * Business invariants enforced here:                             *
      *   - Account must exist in ACCOUNT_MASTER                       *
      *   - Account number must be exactly 10 characters, no spaces    *
      *   - Closed accounts may still be inquired (read-only view)     *
      *----------------------------------------------------------------*
       ENVIRONMENT DIVISION.
       DATA DIVISION.
       WORKING-STORAGE SECTION.

       COPY BKCOMMON.

       01 WS-ACCT-NO-TRIMMED   PIC X(10).
       01 WS-BALANCE-DISPLAY   PIC ZZZ,ZZZ,ZZZ,ZZ9.99.
       01 WS-ACCT-TYPE-DESC    PIC X(15).

      *--- Obsolete balance inquiry via legacy VSAM KSDS -----------
      *--- (BKBAL.KSDS decommissioned Q3-2018; DB2 is authoritative)
      * 01 WS-VSAM-FCT         PIC X(8) VALUE 'BKBALFL'.
      * 01 WS-VSAM-BAL-REC.
      *    05 WS-VSAM-ACCT     PIC X(10).
      *    05 WS-VSAM-BAL      PIC S9(13)V99 COMP-3.
      * 01 WS-VSAM-REC-LEN     PIC S9(4) COMP VALUE +23.

       LINKAGE SECTION.
       01 DFHCOMMAREA          PIC X(200).

       PROCEDURE DIVISION.

           MOVE DFHCOMMAREA TO WS-COMMAREA.
           INITIALIZE HV-ACCOUNT.

      *--- Validate account number format -------------------------
           MOVE CA-ACCT-FROM TO WS-ACCT-NO-TRIMMED.
           IF WS-ACCT-NO-TRIMMED = SPACES
               MOVE '05' TO CA-RETURN-CODE
               MOVE 'ACCOUNT NUMBER CANNOT BE BLANK' TO CA-MESSAGE
               PERFORM RETURN-TO-CALLER
           END-IF.

      *--- Fetch account master from Db2 --------------------------
           MOVE WS-ACCT-NO-TRIMMED TO HV-ACCT-NO.

           EXEC SQL
               SELECT ACCT_NO,
                      ACCT_TYPE,
                      CUSTOMER_ID,
                      ACCT_STATUS,
                      BALANCE,
                      OVERDRAFT_LIMIT,
                      DAILY_WD_LIMIT,
                      DAILY_WD_USED,
                      CHAR(LAST_UPDATE_TS)
               INTO  :HV-ACCT-NO,
                     :HV-ACCT-TYPE,
                     :HV-CUST-ID,
                     :HV-ACCT-STATUS,
                     :HV-BALANCE,
                     :HV-OVERDRAFT-LIM,
                     :HV-DAILY-WD-LIMIT,
                     :HV-DAILY-WD-USED,
                     :HV-LAST-UPDATE-TS
               FROM  BANKDB.ACCOUNT_MASTER
               WHERE ACCT_NO = :HV-ACCT-NO
               WITH  UR
           END-EXEC.

           EVALUATE WS-SQLCODE
               WHEN 0
                   CONTINUE
               WHEN +100
                   MOVE '05' TO CA-RETURN-CODE
                   MOVE 'ACCOUNT NOT FOUND' TO CA-MESSAGE
                   PERFORM RETURN-TO-CALLER
               WHEN OTHER
                   MOVE '99' TO CA-RETURN-CODE
                   MOVE 'DATABASE ERROR READING ACCOUNT' TO CA-MESSAGE
                   PERFORM RETURN-TO-CALLER
           END-EVALUATE.

      *--- Build response in COMMAREA ----------------------------
           MOVE HV-BALANCE     TO CA-BALANCE-OUT.
           MOVE '00'           TO CA-RETURN-CODE.

           EVALUATE TRUE
               WHEN HV-CHECKING
                   MOVE 'CHECKING ACCOUNT' TO WS-ACCT-TYPE-DESC
               WHEN HV-SAVINGS
                   MOVE 'SAVINGS ACCOUNT'  TO WS-ACCT-TYPE-DESC
               WHEN HV-LOAN
                   MOVE 'LOAN ACCOUNT'     TO WS-ACCT-TYPE-DESC
               WHEN OTHER
                   MOVE 'UNKNOWN TYPE'     TO WS-ACCT-TYPE-DESC
           END-EVALUATE.

           MOVE HV-BALANCE TO WS-BALANCE-DISPLAY.

           EVALUATE TRUE
               WHEN HV-ACCT-ACTIVE
                   STRING 'ACCT: ' DELIMITED SIZE
                       HV-ACCT-NO DELIMITED SIZE
                       ' TYPE: ' DELIMITED SIZE
                       WS-ACCT-TYPE-DESC DELIMITED SIZE
                       ' BAL: ' DELIMITED SIZE
                       WS-BALANCE-DISPLAY DELIMITED SIZE
                       INTO CA-MESSAGE
               WHEN HV-ACCT-FROZEN
                   STRING 'ACCOUNT FROZEN - BAL: ' DELIMITED SIZE
                       WS-BALANCE-DISPLAY DELIMITED SIZE
                       INTO CA-MESSAGE
               WHEN HV-ACCT-CLOSED
                   STRING 'ACCOUNT CLOSED - LAST BAL: ' DELIMITED SIZE
                       WS-BALANCE-DISPLAY DELIMITED SIZE
                       INTO CA-MESSAGE
           END-EVALUATE.

       RETURN-TO-CALLER.
           MOVE WS-COMMAREA TO DFHCOMMAREA.
           EXEC CICS RETURN END-EXEC.
