Feature: Customer profile deviation signal (CustomerProfileService)

  Scores how far a transaction deviates from the customer's established
  behaviour: amount, geolocation and time-of-day, plus a card-not-present
  uplift (ARCHITECTURE.md §7). Each scenario isolates one deviation so the
  expected score is unambiguous.

  Scenario: No profile on file defaults to the baseline deviation score
    Given account "ACC0000003" has no customer profile
    When a transaction of amount 500.00 in country "GBR" is profiled for account "ACC0000003"
    Then the profile score is 0.3000

  Scenario: Large amount deviation from the customer's average scores high
    Given account "ACC0000003" has a profile with average amount 10.00, max amount 10.00, usual country "GBR", active hours 0 to 23
    When a transaction of amount 50.00 in country "GBR" is profiled for account "ACC0000003"
    Then the profile score is 0.4000

  Scenario: Small amount deviation from the customer's average scores low
    Given account "ACC0000003" has a profile with average amount 100.00, max amount 100.00, usual country "GBR", active hours 0 to 23
    When a transaction of amount 150.00 in country "GBR" is profiled for account "ACC0000003"
    Then the profile score is 0.2000

  Scenario: Amount within the customer's historical maximum triggers no deviation
    Given account "ACC0000003" has a profile with average amount 500.00, max amount 1000.00, usual country "GBR", active hours 0 to 23
    When a transaction of amount 900.00 in country "GBR" is profiled for account "ACC0000003"
    Then the profile score is 0.0000

  Scenario: Cross-border transaction adds the geolocation deviation
    Given account "ACC0000003" has a profile with average amount 500.00, max amount 1000.00, usual country "GBR", active hours 0 to 23
    When a transaction of amount 100.00 in country "USA" is profiled for account "ACC0000003"
    Then the profile score is 0.3000
    And the transaction is marked cross-border

  Scenario: Transaction outside the customer's usual active hours adds the time-of-day deviation
    Given account "ACC0000003" has a profile with average amount 500.00, max amount 1000.00, usual country "GBR"
    And the usual active hours for account "ACC0000003" exclude the current hour
    When a transaction of amount 100.00 in country "GBR" is profiled for account "ACC0000003"
    Then the profile score is 0.2000

  Scenario: Card-not-present adds the CNP uplift
    Given account "ACC0000003" has a profile with average amount 500.00, max amount 1000.00, usual country "GBR", active hours 0 to 23
    When a card-not-present transaction of amount 100.00 in country "GBR" is profiled for account "ACC0000003"
    Then the profile score is 0.1000

  Scenario: All deviations combined reach the maximum profile score
    Given account "ACC0000003" has a profile with average amount 10.00, max amount 10.00, usual country "GBR"
    And the usual active hours for account "ACC0000003" exclude the current hour
    When a card-not-present transaction of amount 50.00 in country "USA" is profiled for account "ACC0000003"
    Then the profile score is 1.0000
