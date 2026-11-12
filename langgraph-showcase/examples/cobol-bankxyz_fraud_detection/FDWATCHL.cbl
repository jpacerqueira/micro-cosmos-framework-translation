       IDENTIFICATION DIVISION.
       PROGRAM-ID. FDWATCHL.
      *----------------------------------------------------------------*
      * FRAUD DETECTION - WATCHLIST AND SANCTIONS SCREENING            *
      * Called by FDRULES for every transaction.                      *
      * Screens the account holder and merchant against three lists:  *
      *                                                                *
      *   1. OFAC sanctions list (US Treasury)                        *
      *   2. PEP list (Politically Exposed Persons)                   *
      *   3. Internal BankXYZ fraud watchlist                         *
      *                                                                *
      * Business invariants:                                           *
      *   - Any OFAC or PEP hit must auto-escalate (score = 1.0000)  *
      *   - Watchlist tables are refreshed nightly via FDBATCH03      *
      *   - A hit must be logged to FDDB.WATCHLIST_HITS before return *
      *   - Screening covers both account holder and merchant         *
      *                                                                *
      * Dead code:                                                     *
      *   - SCREEN-VSAM-WATCHLIST paragraph used the original VSAM   *
      *     KSDS watchlist file (FDWTCHFL). Replaced by the Db2      *
      *     FDDB.WATCHLIST table in 2020 when the PEP list was added.*
      *     The FCT entry FDWTCHFL was removed; any EXEC CICS READ   *
      *     against it will FILENOTFOUND. Change ref: CHG-2020-0112. *
      *----------------------------------------------------------------*
       ENVIRONMENT DIVISION.
       DATA DIVISION.
       WORKING-STORAGE SECTION.

       COPY FDCOMMON.

       01 WS-SCREEN-SWITCH      PIC X(1) VALUE 'D'.
          88 WS-SCREEN-DB2       VALUE 'D'.
          88 WS-SCREEN-VSAM      VALUE 'V'.

       01 WS-HIT-COUNT          PIC S9(4) COMP VALUE ZERO.
       01 WS-LIST-TYPE          PIC X(10).
       01 WS-MATCH-NAME         PIC X(50).
       01 WS-MATCH-REF          PIC X(20).
       01 WS-CUST-FULL-NAME     PIC X(50).
       01 WS-VSAM-WL-REC.
          05 WV-KEY.
             10 WV-LIST-TYPE    PIC X(10).
             10 WV-REF          PIC X(20).
          05 WV-NAME            PIC X(50).
          05 WV-STATUS          PIC X(4).
       01 WS-VSAM-WL-LEN        PIC S9(4) COMP VALUE +84.
      *--- FCT entry FDWTCHFL was removed from CSD in 2020. --------
      *--- Any EXEC CICS READ FILE('FDWTCHFL') = FILENOTFOUND.  ----

       LINKAGE SECTION.
       01 DFHCOMMAREA           PIC X(200).

       PROCEDURE DIVISION.

           MOVE DFHCOMMAREA TO WS-COMMAREA.
           MOVE 'N' TO HV-OFAC-FLAG.
           MOVE 'N' TO HV-PEP-FLAG.
           MOVE 'N' TO HV-INTERNAL-FLAG.
           MOVE ZERO TO HV-WATCHLIST-SCORE.
           MOVE SPACES TO HV-WATCHLIST-REASON.

      *--- Fetch account holder name for screening ------------------
           MOVE CA-ACCT-NO TO HV-ACCT-NO.

           EXEC SQL
               SELECT CUST_FULL_NAME
               INTO  :WS-CUST-FULL-NAME
               FROM  FDDB.ACCOUNT_MASTER
               WHERE ACCT_NO = :HV-ACCT-NO
           END-EXEC.

           IF WS-SQLCODE NOT = 0
               PERFORM RETURN-TO-CALLER
           END-IF.

      *--- Screen 1: OFAC sanctions list ---------------------------
           EXEC SQL
               SELECT COUNT(*)
               INTO  :WS-HIT-COUNT
               FROM  FDDB.WATCHLIST
               WHERE LIST_TYPE   = 'OFAC'
               AND   MATCH_NAME  LIKE :WS-CUST-FULL-NAME
               AND   LIST_STATUS = 'ACTIVE'
           END-EXEC.

           IF WS-HIT-COUNT > 0
               MOVE 'Y' TO HV-OFAC-FLAG
               MOVE 1.0000 TO HV-WATCHLIST-SCORE
               MOVE 'OFAC SANCTIONS HIT - MANDATORY ESCALATION'
                   TO HV-WATCHLIST-REASON
               PERFORM LOG-WATCHLIST-HIT
               PERFORM RETURN-TO-CALLER
           END-IF.

      *--- Screen 2: PEP list (Politically Exposed Persons) --------
           EXEC SQL
               SELECT COUNT(*)
               INTO  :WS-HIT-COUNT
               FROM  FDDB.WATCHLIST
               WHERE LIST_TYPE   = 'PEP'
               AND   MATCH_NAME  LIKE :WS-CUST-FULL-NAME
               AND   LIST_STATUS = 'ACTIVE'
           END-EXEC.

           IF WS-HIT-COUNT > 0
               MOVE 'Y' TO HV-PEP-FLAG
               MOVE 1.0000 TO HV-WATCHLIST-SCORE
               MOVE 'PEP LIST HIT - MANDATORY ESCALATION'
                   TO HV-WATCHLIST-REASON
               PERFORM LOG-WATCHLIST-HIT
               PERFORM RETURN-TO-CALLER
           END-IF.

      *--- Screen 3: Internal BankXYZ fraud watchlist ---------------
           EXEC SQL
               SELECT COUNT(*)
               INTO  :WS-HIT-COUNT
               FROM  FDDB.WATCHLIST
               WHERE LIST_TYPE   = 'INTERNAL'
               AND   (MATCH_ACCT = :HV-ACCT-NO OR
                      MATCH_NAME LIKE :WS-CUST-FULL-NAME)
               AND   LIST_STATUS = 'ACTIVE'
           END-EXEC.

           IF WS-HIT-COUNT > 0
               MOVE 'Y'    TO HV-INTERNAL-FLAG
               MOVE 0.9000 TO HV-WATCHLIST-SCORE
               MOVE 'INTERNAL WATCHLIST HIT' TO HV-WATCHLIST-REASON
               PERFORM LOG-WATCHLIST-HIT
           END-IF.

      *--- Dead code: VSAM screening path (never executed) ---------
      *--- WS-SCREEN-SWITCH is always 'D'; VSAM path unreachable.  -
           IF WS-SCREEN-VSAM
               PERFORM SCREEN-VSAM-WATCHLIST
           END-IF.

           PERFORM RETURN-TO-CALLER.

      *=============================================================
       LOG-WATCHLIST-HIT.
      *=============================================================
           EXEC SQL
               INSERT INTO FDDB.WATCHLIST_HITS
                   (ACCT_NO, TXN_ID, HIT_TYPE,
                    HIT_REASON, HIT_TS)
               VALUES
                   (:HV-ACCT-NO, :HV-TXN-ID,
                    :HV-WATCHLIST-REASON,
                    :HV-WATCHLIST-REASON,
                    CURRENT TIMESTAMP)
           END-EXEC.

      *=============================================================
       SCREEN-VSAM-WATCHLIST.
      *=============================================================
      *--- DEAD CODE - FDWTCHFL FCT entry removed 2020 -------------
           INITIALIZE WS-VSAM-WL-REC.
           MOVE 'INTERNAL'       TO WV-LIST-TYPE.
           MOVE CA-ACCT-NO       TO WV-REF.

           EXEC CICS READ
               FILE('FDWTCHFL')
               INTO(WS-VSAM-WL-REC)
               LENGTH(WS-VSAM-WL-LEN)
               RIDFLD(WV-KEY)
               RESP(WS-CICS-RESP)
           END-EXEC.

           IF WS-CICS-RESP = DFHRESP(NORMAL)
               MOVE 'Y' TO HV-INTERNAL-FLAG
               MOVE 'VSAM WATCHLIST HIT' TO HV-WATCHLIST-REASON
           END-IF.

      *=============================================================
       RETURN-TO-CALLER.
      *=============================================================
           MOVE WS-COMMAREA TO DFHCOMMAREA.
           EXEC CICS RETURN END-EXEC.
