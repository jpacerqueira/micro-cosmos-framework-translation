Feature: Watchlist and sanctions screening (WatchlistService)

  Screens the account holder against OFAC, PEP and the internal BankXYZ
  fraud watchlist, and audit-logs every hit regardless of outcome
  (ARCHITECTURE.md §7-8).

  Scenario: OFAC sanctions hit is mandatory escalation and gets logged
    Given an active account "ACC0000004" for customer "John Smith" in country "GBR"
    And a watchlist "OFAC" entry matching name "John Smith"
    When account "ACC0000004" is screened against the watchlist
    Then the account has an OFAC hit
    And the watchlist score is 1.0000
    And the watchlist reason is "OFAC sanctions hit - mandatory escalation"
    And 1 watchlist hit has been logged with type "OFAC"

  Scenario: PEP list hit is mandatory escalation and gets logged
    Given an active account "ACC0000004" for customer "John Smith" in country "GBR"
    And a watchlist "PEP" entry matching name "John Smith"
    When account "ACC0000004" is screened against the watchlist
    Then the account has a PEP hit
    And the watchlist score is 1.0000
    And the watchlist reason is "PEP list hit - mandatory escalation"
    And 1 watchlist hit has been logged with type "PEP"

  Scenario: Internal watchlist hit by account number
    Given an active account "ACC0000004" for customer "John Smith" in country "GBR"
    And a watchlist "INTERNAL" entry matching account "ACC0000004"
    When account "ACC0000004" is screened against the watchlist
    Then the account has an internal watchlist hit
    And the watchlist score is 0.9000
    And the watchlist reason is "Internal watchlist hit"
    And 1 watchlist hit has been logged with type "INTERNAL"

  Scenario: Internal watchlist hit by customer name
    Given an active account "ACC0000004" for customer "John Smith" in country "GBR"
    And a watchlist "INTERNAL" entry matching name "John Smith"
    When account "ACC0000004" is screened against the watchlist
    Then the account has an internal watchlist hit
    And the watchlist score is 0.9000

  Scenario: No watchlist entries means a clean screen
    Given an active account "ACC0000004" for customer "John Smith" in country "GBR"
    When account "ACC0000004" is screened against the watchlist
    Then the account has no watchlist hit
    And the watchlist score is 0.0000
    And 0 watchlist hits have been logged

  Scenario: Screening an unknown account performs no checks
    When account "ACC0000999" is screened against the watchlist
    Then the account has no watchlist hit
    And the watchlist score is 0.0000
    And 0 watchlist hits have been logged
