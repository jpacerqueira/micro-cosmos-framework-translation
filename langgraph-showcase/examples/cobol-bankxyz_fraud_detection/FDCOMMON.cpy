      *----------------------------------------------------------------*
      * FDCOMMON.CPY  -  SHARED WORKING-STORAGE FOR FRAUD DETECTION  *
      * Included via COPY FDCOMMON in every program of this estate.  *
      *----------------------------------------------------------------*

      *--- Db2 host variables: Transaction input ---------------------
       01 HV-TRANSACTION.
          05 HV-TXN-ID           PIC X(16).
          05 HV-ACCT-NO          PIC X(10).
          05 HV-MERCHANT-CODE    PIC X(8).
          05 HV-CHANNEL          PIC X(8).
             88 HV-CHANNEL-ATM     VALUE 'ATM     '.
             88 HV-CHANNEL-ONLINE  VALUE 'ONLINE  '.
             88 HV-CHANNEL-BRANCH  VALUE 'BRANCH  '.
          05 HV-TXN-AMOUNT       PIC S9(13)V99 COMP-3.
          05 HV-TXN-TIMESTAMP    PIC X(26).
          05 HV-TXN-COUNTRY      PIC X(3).

      *--- Db2 host variables: Fraud scoring ------------------------
       01 HV-FRAUD-RESULT.
          05 HV-FRAUD-SCORE      PIC S9(3)V9999 COMP-3.
          05 HV-FRAUD-FLAG       PIC X(1).
             88 HV-IS-FRAUD        VALUE 'Y'.
             88 HV-NOT-FRAUD       VALUE 'N'.
          05 HV-ALERT-ID         PIC S9(9) COMP.
          05 HV-ALERT-STATUS     PIC X(10).
             88 HV-ALERT-PENDING   VALUE 'PENDING   '.
             88 HV-ALERT-REVIEWED  VALUE 'REVIEWED  '.
             88 HV-ALERT-CLOSED    VALUE 'CLOSED    '.

      *--- Db2 host variables: Velocity query -----------------------
       01 HV-VELOCITY.
          05 HV-TXN-COUNT        PIC S9(9)     COMP.
          05 HV-TXN-SUM          PIC S9(13)V99 COMP-3.
          05 HV-VELOCITY-SCORE   PIC S9(3)V9999 COMP-3.

      *--- Db2 host variables: Blocked merchant check ---------------
       01 HV-MERCHANT.
          05 HV-BLOCKED-FLAG     PIC X(1).
             88 HV-MERCHANT-BLOCKED VALUE 'Y'.
          05 HV-MERCHANT-RISK    PIC X(4).
             88 HV-RISK-HIGH       VALUE 'HIGH'.
             88 HV-RISK-MED        VALUE 'MED '.
             88 HV-RISK-LOW        VALUE 'LOW '.

      *--- CICS Communication Area (COMMAREA) -----------------------
       01 WS-COMMAREA.
          05 CA-TXN-ID           PIC X(16).
          05 CA-ACCT-NO          PIC X(10).
          05 CA-TXN-AMOUNT       PIC S9(13)V99 COMP-3.
          05 CA-MERCHANT-CODE    PIC X(8).
          05 CA-CHANNEL          PIC X(8).
          05 CA-TXN-COUNTRY      PIC X(3).
          05 CA-FRAUD-SCORE      PIC S9(3)V9999 COMP-3.
          05 CA-FRAUD-FLAG       PIC X(1).
             88 CA-FRAUD-YES       VALUE 'Y'.
             88 CA-FRAUD-NO        VALUE 'N'.
          05 CA-RETURN-CODE      PIC X(2).
             88 CA-RC-OK           VALUE '00'.
             88 CA-RC-FRAUD        VALUE '10'.
             88 CA-RC-NO-ACCT      VALUE '05'.
             88 CA-RC-ERROR        VALUE '99'.
          05 CA-MESSAGE          PIC X(80).

      *--- Card and channel data ------------------------------------
       01 HV-CARD.
          05 HV-CARD-LAST4       PIC X(4).
          05 HV-CARD-TYPE        PIC X(2).
             88 HV-CARD-DEBIT     VALUE 'DB'.
             88 HV-CARD-CREDIT    VALUE 'CR'.
             88 HV-CARD-PREPAID   VALUE 'PP'.
          05 HV-CARD-EXPIRY      PIC X(4).
          05 HV-CNP-FLAG         PIC X(1).
             88 HV-CARD-NOT-PRESENT VALUE 'Y'.
             88 HV-CARD-PRESENT     VALUE 'N'.

      *--- Geolocation data -----------------------------------------
       01 HV-GEO.
          05 HV-HOME-COUNTRY     PIC X(3).
          05 HV-TXN-COUNTRY-GEO  PIC X(3).
          05 HV-CROSS-BORDER     PIC X(1).
             88 HV-IS-CROSS-BORDER VALUE 'Y'.
          05 HV-GEO-RISK-SCORE   PIC S9(3)V9999 COMP-3.

      *--- Customer profile data ------------------------------------
       01 HV-CUST-PROFILE.
          05 HV-AVG-TXN-AMOUNT   PIC S9(13)V99 COMP-3.
          05 HV-MAX-TXN-AMOUNT   PIC S9(13)V99 COMP-3.
          05 HV-USUAL-COUNTRY    PIC X(3).
          05 HV-USUAL-CHANNEL    PIC X(8).
          05 HV-PROFILE-SCORE    PIC S9(3)V9999 COMP-3.

      *--- Watchlist screening result -------------------------------
       01 HV-WATCHLIST.
          05 HV-OFAC-FLAG        PIC X(1).
             88 HV-OFAC-HIT       VALUE 'Y'.
          05 HV-PEP-FLAG         PIC X(1).
             88 HV-PEP-HIT        VALUE 'Y'.
          05 HV-INTERNAL-FLAG    PIC X(1).
             88 HV-INTERNAL-HIT   VALUE 'Y'.
          05 HV-WATCHLIST-REASON PIC X(40).
          05 HV-WATCHLIST-SCORE  PIC S9(3)V9999 COMP-3.

      *--- Fraud thresholds and scoring weights (5 signals) ---------
       01 WS-FD-CONSTANTS.
          05 WS-SCORE-THRESHOLD  PIC S9(3)V9999 COMP-3 VALUE 0.7500.
          05 WS-HIGH-AMT-LIMIT   PIC S9(13)V99  COMP-3 VALUE 5000.00.
          05 WS-MED-AMT-LIMIT    PIC S9(13)V99  COMP-3 VALUE 1000.00.
          05 WS-LOW-AMT-LIMIT    PIC S9(13)V99  COMP-3 VALUE  200.00.
          05 WS-VELOCITY-LIMIT   PIC S9(4)      COMP   VALUE 10.
          05 WS-WEIGHT-AMOUNT    PIC S9(3)V9999 COMP-3 VALUE 0.2500.
          05 WS-WEIGHT-MERCHANT  PIC S9(3)V9999 COMP-3 VALUE 0.2500.
          05 WS-WEIGHT-VELOCITY  PIC S9(3)V9999 COMP-3 VALUE 0.2000.
          05 WS-WEIGHT-PROFILE   PIC S9(3)V9999 COMP-3 VALUE 0.2000.
          05 WS-WEIGHT-WATCHLIST PIC S9(3)V9999 COMP-3 VALUE 0.1000.

      *--- Working counters and index fields ------------------------
       01 WS-FD-WORK.
          05 WS-IDX              PIC S9(4)     COMP VALUE ZERO.
          05 WS-ACCT-COUNT       PIC S9(4)     COMP VALUE ZERO.
          05 WS-PENDING-COUNT    PIC S9(4)     COMP VALUE ZERO.
          05 WS-AMOUNT-SCORE     PIC S9(3)V9999 COMP-3 VALUE ZERO.
          05 WS-MERCHANT-SCORE   PIC S9(3)V9999 COMP-3 VALUE ZERO.
          05 WS-COMPOSITE-SCORE  PIC S9(3)V9999 COMP-3 VALUE ZERO.

      *--- VSAM flat-file definitions for alert log (obsolete) ------
       01 WS-VSAM-ALERT-REC.
          05 VA-KEY.
             10 VA-DATE          PIC X(10).
             10 VA-SEQ           PIC X(6).
          05 VA-TXN-ID           PIC X(16).
          05 VA-ACCT-NO          PIC X(10).
          05 VA-FRAUD-SCORE      PIC X(8).
          05 VA-STATUS           PIC X(10).
       01 WS-VSAM-REC-LEN        PIC S9(4) COMP VALUE +50.
      *--- FCT entry FDALTFL was removed from the CSD in 2022. ------
      *--- Any EXEC CICS WRITE FILE('FDALTFL') will FILENOTFOUND. ---

      *--- CICS and DB2 response fields -----------------------------
       01 WS-CICS-RESP           PIC S9(8) COMP VALUE ZERO.
       01 WS-CICS-RESP2          PIC S9(8) COMP VALUE ZERO.
       01 WS-SQLCODE             PIC S9(9) COMP VALUE ZERO.
       01 WS-TIMESTAMP           PIC X(26).
       01 WS-COMMAREA-LEN        PIC S9(4) COMP VALUE +200.
