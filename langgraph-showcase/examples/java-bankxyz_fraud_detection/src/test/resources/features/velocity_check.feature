Feature: 24-hour velocity signal (VelocityCheckService)

  Counts how many transactions an account made in the last 24 hours and
  converts that count to a normalised 0.0-1.0 score (ARCHITECTURE.md §7).

  Scenario: No prior transactions gives a zero velocity score
    Given account "ACC0000002" has no prior transactions
    When velocity is checked for account "ACC0000002" with limit 5
    Then the velocity count is 0
    And the velocity score is 0.0000

  Scenario: Transaction count below the limit is normalised to count / limit
    Given account "ACC0000002" made 2 transactions of 100.00 in the last 24 hours with status "S"
    When velocity is checked for account "ACC0000002" with limit 5
    Then the velocity count is 2
    And the velocity sum is 200.00
    And the velocity score is 0.4000

  Scenario: Transaction count at or above the limit is capped at 1.0
    Given account "ACC0000002" made 6 transactions of 100.00 in the last 24 hours with status "S"
    When velocity is checked for account "ACC0000002" with limit 5
    Then the velocity count is 6
    And the velocity score is 1.0000

  Scenario: Transactions older than 24 hours are excluded from velocity
    Given account "ACC0000002" made 3 transactions of 100.00 30 hours ago with status "S"
    When velocity is checked for account "ACC0000002" with limit 5
    Then the velocity count is 0

  Scenario: Errored transactions are excluded from velocity
    Given account "ACC0000002" made 3 transactions of 100.00 in the last 24 hours with status "E"
    When velocity is checked for account "ACC0000002" with limit 5
    Then the velocity count is 0
