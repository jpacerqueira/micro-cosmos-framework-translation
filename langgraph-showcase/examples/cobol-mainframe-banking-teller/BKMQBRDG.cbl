       IDENTIFICATION DIVISION.
       PROGRAM-ID. BKMQBRDG.
      *----------------------------------------------------------------*
      * IBM WEBSPHERE MQ BRIDGE - TELLER REST API NOTIFICATION         *
      * Called via EXEC CICS LINK from BKTLRMN after a successful      *
      * transaction. Puts a JSON-formatted notification message to     *
      * TELLER.REQUEST.QUEUE on queue manager BKQM01. The MQ message  *
      * is consumed by an IBM z/OS Connect EE API that forwards it to  *
      * the teller screen REST endpoint.                                *
      *                                                                 *
      * Failure here is non-fatal: BKTLRMN ignores a non-zero CICS   *
      * RESP from this LINK so the transaction is never rolled back     *
      * due to a notification delivery failure.                         *
      *                                                                 *
      * MQ API used: MQPUT (CICS-MQ bridge via EXEC CICS PUT CONTAINER)*
      * Queue manager: BKQM01                                          *
      * Request queue: TELLER.REQUEST.QUEUE                            *
      *----------------------------------------------------------------*
       ENVIRONMENT DIVISION.
       DATA DIVISION.
       WORKING-STORAGE SECTION.

       COPY BKCOMMON.

      *--- MQ Object Descriptor (MQOD) ----------------------------
       01 WS-MQOD.
          05 WS-MQOD-STRUCID   PIC X(4)  VALUE 'MQOD'.
          05 WS-MQOD-VERSION   PIC S9(9) COMP VALUE 1.
          05 WS-MQOD-OBJTYPE   PIC S9(9) COMP VALUE 1.
          05 WS-MQOD-OBJNAME   PIC X(48).
          05 WS-MQOD-QMNAME    PIC X(48).

      *--- MQ Message Descriptor (MQMD) ---------------------------
       01 WS-MQMD.
          05 WS-MQMD-STRUCID   PIC X(4)  VALUE 'MQMD'.
          05 WS-MQMD-VERSION   PIC S9(9) COMP VALUE 2.
          05 WS-MQMD-REPORT    PIC S9(9) COMP VALUE 0.
          05 WS-MQMD-MSGTYPE   PIC S9(9) COMP VALUE 8.
          05 WS-MQMD-EXPIRY    PIC S9(9) COMP VALUE -1.
          05 WS-MQMD-FEEDBACK  PIC S9(9) COMP VALUE 0.
          05 WS-MQMD-ENCODING  PIC S9(9) COMP VALUE 273.
          05 WS-MQMD-CODEDCSI  PIC S9(9) COMP VALUE 1208.
          05 WS-MQMD-FORMAT    PIC X(8)  VALUE 'MQSTR   '.
          05 WS-MQMD-PRIORITY  PIC S9(9) COMP VALUE 0.
          05 WS-MQMD-PERSIST   PIC S9(9) COMP VALUE 1.
          05 WS-MQMD-MSGID     PIC X(24) VALUE LOW-VALUES.
          05 WS-MQMD-CORRELID  PIC X(24) VALUE LOW-VALUES.
          05 WS-MQMD-REPLYTOQ  PIC X(48)
                               VALUE 'TELLER.RESPONSE.QUEUE'.
          05 WS-MQMD-REPLYTQM  PIC X(48) VALUE SPACES.

      *--- MQ Put Options (MQPMO) ----------------------------------
       01 WS-MQPMO.
          05 WS-MQPMO-STRUCID  PIC X(4)  VALUE 'MQPMO'.
          05 WS-MQPMO-VERSION  PIC S9(9) COMP VALUE 1.
          05 WS-MQPMO-OPTIONS  PIC S9(9) COMP VALUE 8192.
          05 WS-MQPMO-TIMEOUT  PIC S9(9) COMP VALUE 30.

      *--- JSON message buffer (fixed 2 KB) -----------------------
      *--- String concatenation into a fixed buffer is a known    ---
      *--- anti-pattern; a proper serialiser should replace this. ---
       01 WS-MSG-BUFFER        PIC X(2048) VALUE SPACES.
       01 WS-MSG-LEN           PIC S9(9) COMP VALUE ZERO.
       01 WS-AMOUNT-DISPLAY    PIC ZZZ,ZZZ,ZZZ,ZZ9.99.
       01 WS-TIMESTAMP-OUT     PIC X(26).

       LINKAGE SECTION.
       01 DFHCOMMAREA          PIC X(200).

       PROCEDURE DIVISION.

           MOVE DFHCOMMAREA TO WS-COMMAREA.

      *--- Build ISO-8601 timestamp -------------------------------
           EXEC SQL
               VALUES(CHAR(CURRENT TIMESTAMP))
               INTO :WS-TIMESTAMP-OUT
               FROM SYSIBM.SYSDUMMY1
           END-EXEC.

           MOVE CA-AMOUNT TO WS-AMOUNT-DISPLAY.

      *--- Assemble JSON payload by string concatenation ----------
      *--- (brittle: special characters in CA-MESSAGE not escaped) -
           STRING
               '{"event":"TELLER_TXN"'         DELIMITED SIZE
               ',"txnRef":"'                    DELIMITED SIZE
               CA-TXN-REF                       DELIMITED SPACE
               '"'                              DELIMITED SIZE
               ',"function":"'                  DELIMITED SIZE
               CA-FUNCTION                      DELIMITED SPACE
               '"'                              DELIMITED SIZE
               ',"acctFrom":"'                  DELIMITED SIZE
               CA-ACCT-FROM                     DELIMITED SPACE
               '"'                              DELIMITED SIZE
               ',"acctTo":"'                    DELIMITED SIZE
               CA-ACCT-TO                       DELIMITED SPACE
               '"'                              DELIMITED SIZE
               ',"amount":'                     DELIMITED SIZE
               WS-AMOUNT-DISPLAY                DELIMITED SPACE
               ','                              DELIMITED SIZE
               '"newBalance":'                  DELIMITED SIZE
               CA-NEW-BALANCE                   DELIMITED SIZE
               ','                              DELIMITED SIZE
               '"tellerId":"'                   DELIMITED SIZE
               CA-TELLER-ID                     DELIMITED SPACE
               '"'                              DELIMITED SIZE
               ',"branchId":"'                  DELIMITED SIZE
               CA-BRANCH-ID                     DELIMITED SPACE
               '"'                              DELIMITED SIZE
               ',"returnCode":"'                DELIMITED SIZE
               CA-RETURN-CODE                   DELIMITED SIZE
               '"'                              DELIMITED SIZE
               ',"timestamp":"'                 DELIMITED SIZE
               WS-TIMESTAMP-OUT                 DELIMITED SPACE
               '"}'                             DELIMITED SIZE
               INTO WS-MSG-BUFFER
           END-STRING.

           INSPECT WS-MSG-BUFFER
               TALLYING WS-MSG-LEN FOR CHARACTERS BEFORE INITIAL SPACES.

           IF WS-MSG-LEN = ZERO
               MOVE 2 TO WS-MSG-LEN
           END-IF.

      *--- Open queue and put message via CICS-MQ bridge ----------
           MOVE WS-REQUEST-QUEUE TO WS-MQOD-OBJNAME.
           MOVE WS-MQ-QUEUE-MGR  TO WS-MQOD-QMNAME.

           EXEC CICS PUT CONTAINER('MQMESSAGE')
               FROM(WS-MSG-BUFFER)
               FLENGTH(WS-MSG-LEN)
               RESP(WS-CICS-RESP)
               RESP2(WS-CICS-RESP2)
           END-EXEC.

           IF WS-CICS-RESP NOT = DFHRESP(NORMAL)
               MOVE '99' TO CA-RETURN-CODE
               MOVE 'MQ PUT FAILED - NOTIFICATION NOT SENT'
                   TO CA-MESSAGE
           END-IF.

      *--- Log MQ delivery failure to Db2 audit (best effort) ----
           IF CA-RETURN-CODE = '99'
               MOVE CA-TXN-REF     TO HV-AUD-TXN-REF
               MOVE 'MQ_PUT_FAILED' TO HV-AUD-EVENT-TYPE
               MOVE WS-TIMESTAMP-OUT TO HV-AUD-EVENT-TS
               MOVE CA-TELLER-ID   TO HV-AUD-TELLER-ID
               MOVE CA-MESSAGE     TO HV-AUD-DETAILS
               EXEC SQL
                   INSERT INTO BANKDB.AUDIT_LOG
                       (AUD_TXN_REF, EVENT_TYPE, EVENT_TS,
                        TELLER_ID, BEFORE_BAL, AFTER_BAL, DETAILS)
                   VALUES
                       (:HV-AUD-TXN-REF, :HV-AUD-EVENT-TYPE,
                        :HV-AUD-EVENT-TS, :HV-AUD-TELLER-ID,
                        0, 0, :HV-AUD-DETAILS)
               END-EXEC
           END-IF.

           MOVE WS-COMMAREA TO DFHCOMMAREA.
           EXEC CICS RETURN END-EXEC.
