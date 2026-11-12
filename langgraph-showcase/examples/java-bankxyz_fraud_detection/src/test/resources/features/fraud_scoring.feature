Feature: Composite fraud scoring (FraudRulesService)

  BankXYZ scores every transaction on five weighted signals and applies the
  mandatory-escalation invariants documented in ARCHITECTURE.md sections 7-8.
  Unless a scenario seeds a merchant, profile, watchlist entry or prior
  transaction, those signals contribute their "no data" default so the
  composite score stays hand-calculable.

  Background:
    Given an active account "ACC0000001" for customer "Jane Doe" in country "GBR"

  Scenario: Unknown account is rejected before scoring
    When account "ACC0000999" is scored for a transaction of amount 100.00 on channel "ONLINE"
    Then the return code is "05"
    And the message is "Account not found"

  Scenario: Frozen account is auto-flagged regardless of amount
    Given account "ACC0000001" has status "FROZEN"
    When account "ACC0000001" is scored for a transaction of amount 10.00 on channel "ONLINE"
    Then the fraud score is 1.0000
    And the transaction is flagged as fraud
    And the return code is "10"

  Scenario: Closed account is auto-flagged regardless of amount
    Given account "ACC0000001" has status "CLOSED"
    When account "ACC0000001" is scored for a transaction of amount 10.00 on channel "ONLINE"
    Then the fraud score is 1.0000
    And the transaction is flagged as fraud

  Scenario Outline: Amount signal bands drive the composite score when no other signal fires
    When account "ACC0000001" is scored for a transaction of amount <amount> on channel "ONLINE"
    Then the fraud score is <score>
    And the transaction is not flagged as fraud

    Examples:
      | amount  | score  |
      | 9999.00 | 0.2600 |
      | 2500.00 | 0.1850 |
      | 500.00  | 0.1350 |
      | 50.00   | 0.0850 |

  Scenario: An OFAC sanctions hit forces mandatory escalation regardless of amount
    Given a watchlist "OFAC" entry matching name "Jane Doe"
    When account "ACC0000001" is scored for a transaction of amount 10.00 on channel "ONLINE"
    Then the fraud score is 1.0000
    And the transaction is flagged as fraud
    And the return code is "10"
    And the message is "OFAC sanctions hit - mandatory escalation"

  Scenario: A PEP list hit forces mandatory escalation regardless of amount
    Given a watchlist "PEP" entry matching name "Jane Doe"
    When account "ACC0000001" is scored for a transaction of amount 10.00 on channel "ONLINE"
    Then the fraud score is 1.0000
    And the transaction is flagged as fraud
    And the message is "PEP list hit - mandatory escalation"

  Scenario: Combined signals push the composite score into high-risk territory
    Given a blocked merchant "MCH00666"
    And a watchlist "INTERNAL" entry matching account "ACC0000001"
    And account "ACC0000001" made 5 prior transactions of 50.00 in the last 24 hours
    When account "ACC0000001" is scored for a transaction of amount 9999.00 on merchant "MCH00666" channel "ONLINE"
    Then the fraud score is 0.8000
    And the transaction is flagged as fraud
    And the return code is "10"
    And the message is "Transaction flagged as high risk"

  Scenario Outline: CHIPPIN channel zeroes and redistributes the profile signal weight (BAU-2021-09)
    Given a customer profile for "ACC0000001" with average amount 10.00, max amount 10.00, country "GBR", active hours 0 to 23
    When account "ACC0000001" is scored for a transaction of amount 50.00 on channel "<channel>"
    Then the fraud score is <score>

    Examples:
      | channel | score  |
      | ONLINE  | 0.1050 |
      | CHIPPIN | 0.0250 |
