      *----------------------------------------------------------------*
      * BKCOMMON.CPY  -  SHARED WORKING-STORAGE FOR BANKING TELLER    *
      * Included via COPY BKCOMMON in every program of this estate.   *
      *----------------------------------------------------------------*

      *--- Db2 host variables: Account Master -----------------------
       01 HV-ACCOUNT.
          05 HV-ACCT-NO          PIC X(10).
          05 HV-ACCT-TYPE        PIC X(2).
             88 HV-CHECKING        VALUE 'CH'.
             88 HV-SAVINGS         VALUE 'SV'.
             88 HV-LOAN            VALUE 'LN'.
          05 HV-CUST-ID          PIC X(9).
          05 HV-ACCT-STATUS      PIC X(1).
             88 HV-ACCT-ACTIVE     VALUE 'A'.
             88 HV-ACCT-FROZEN     VALUE 'F'.
             88 HV-ACCT-CLOSED     VALUE 'C'.
          05 HV-BALANCE          PIC S9(13)V99 COMP-3.
          05 HV-BALANCE-X        REDEFINES HV-BALANCE PIC X(8).
          05 HV-OVERDRAFT-LIM    PIC S9(7)V99  COMP-3.
          05 HV-DAILY-WD-LIMIT   PIC S9(7)V99  COMP-3.
          05 HV-DAILY-WD-USED    PIC S9(7)V99  COMP-3.
          05 HV-LAST-UPDATE-TS   PIC X(26).

      *--- Db2 host variables: Transaction Register -----------------
       01 HV-TRANSACTION.
          05 HV-TXN-ID           PIC S9(9)     COMP.
          05 HV-TXN-DATE         PIC X(10).
          05 HV-TXN-TIME         PIC X(8).
          05 HV-TXN-TYPE         PIC X(4).
             88 HV-TXN-DEP         VALUE 'DEPO'.
             88 HV-TXN-WTH         VALUE 'WITH'.
             88 HV-TXN-TRF         VALUE 'XFER'.
             88 HV-TXN-INQ         VALUE 'INQU'.
          05 HV-TXN-ACCT-FROM    PIC X(10).
          05 HV-TXN-ACCT-TO      PIC X(10).
          05 HV-TXN-AMOUNT       PIC S9(13)V99 COMP-3.
          05 HV-TXN-REF          PIC X(16).
          05 HV-TXN-TELLER-ID    PIC X(8).
          05 HV-TXN-BRANCH-ID    PIC X(6).
          05 HV-TXN-CHANNEL      PIC X(10).
          05 HV-TXN-STATUS       PIC X(1).
             88 HV-TXN-COMMITTED   VALUE 'C'.
             88 HV-TXN-FAILED      VALUE 'F'.
             88 HV-TXN-REVERSED    VALUE 'R'.

      *--- Db2 host variables: Audit Log ----------------------------
       01 HV-AUDIT.
          05 HV-AUD-ID           PIC S9(9)     COMP.
          05 HV-AUD-TXN-REF      PIC X(16).
          05 HV-AUD-EVENT-TYPE   PIC X(20).
          05 HV-AUD-EVENT-TS     PIC X(26).
          05 HV-AUD-TELLER-ID    PIC X(8).
          05 HV-AUD-BEFORE-BAL   PIC S9(13)V99 COMP-3.
          05 HV-AUD-AFTER-BAL    PIC S9(13)V99 COMP-3.
          05 HV-AUD-DETAILS      PIC X(255).

      *--- CICS Communication Area (COMMAREA) -----------------------
       01 WS-COMMAREA.
          05 CA-FUNCTION         PIC X(4).
             88 CA-DEPOSIT         VALUE 'DEPO'.
             88 CA-WITHDRAW        VALUE 'WITH'.
             88 CA-TRANSFER        VALUE 'XFER'.
             88 CA-INQUIRY         VALUE 'INQU'.
          05 CA-ACCT-FROM        PIC X(10).
          05 CA-ACCT-TO          PIC X(10).
          05 CA-AMOUNT           PIC S9(13)V99 COMP-3.
          05 CA-TELLER-ID        PIC X(8).
          05 CA-BRANCH-ID        PIC X(6).
          05 CA-TXN-REF          PIC X(16).
          05 CA-RETURN-CODE      PIC X(2).
             88 CA-OK               VALUE '00'.
             88 CA-INSUFF-FUNDS     VALUE '01'.
             88 CA-ACCT-CLOSED      VALUE '02'.
             88 CA-ACCT-FROZEN      VALUE '03'.
             88 CA-DAILY-LIMIT      VALUE '04'.
             88 CA-ACCT-NOT-FOUND   VALUE '05'.
             88 CA-SYSTEM-ERR       VALUE '99'.
          05 CA-MESSAGE          PIC X(79).
          05 CA-BALANCE-OUT      PIC S9(13)V99 COMP-3.
          05 CA-NEW-BALANCE      PIC S9(13)V99 COMP-3.

      *--- Business constants ---------------------------------------
       01 WS-CONSTANTS.
          05 WS-MAX-SINGLE-WD    PIC S9(7)V99  COMP-3 VALUE 50000.00.
          05 WS-MIN-BALANCE      PIC S9(7)V99  COMP-3 VALUE     0.00.
          05 WS-COMMAREA-LEN     PIC S9(4)     COMP   VALUE   +200.

      *--- MQ connection parameters ---------------------------------
       01 WS-MQ-PARAMS.
          05 WS-MQ-QUEUE-MGR     PIC X(48) VALUE 'BKQM01'.
          05 WS-REQUEST-QUEUE    PIC X(48)
                                 VALUE 'TELLER.REQUEST.QUEUE'.
          05 WS-RESPONSE-QUEUE   PIC X(48)
                                 VALUE 'TELLER.RESPONSE.QUEUE'.
          05 WS-MQ-HCONN         PIC S9(9) COMP VALUE ZERO.
          05 WS-MQ-HOBJ          PIC S9(9) COMP VALUE ZERO.
          05 WS-MQ-COMPCODE      PIC S9(9) COMP VALUE ZERO.
          05 WS-MQ-REASON        PIC S9(9) COMP VALUE ZERO.

      *--- CICS response codes ------------------------------------
       01 WS-CICS-RESP          PIC S9(8) COMP VALUE ZERO.
       01 WS-CICS-RESP2         PIC S9(8) COMP VALUE ZERO.
       01 WS-SQLCODE            PIC S9(9) COMP VALUE ZERO.
