Feature: Nightly batch transaction scoring (TransactionMonitorService)

  Reads TXN_STATUS='P' rows from TXN_QUEUE, scores each via the same
  FraudRulesService engine as the real-time path, writes alerts for anything
  scoring >= 0.75, and stamps every processed row 'S' (ARCHITECTURE.md §3).

  Background:
    Given an active account "ACC0000007" for customer "Clean Customer" in country "GBR"
    And an active account "ACC0000008" for customer "Risky Customer" in country "GBR"

  Scenario: An empty batch window reports no pending transactions
    When the batch job runs with a maximum of 500 transactions
    Then the batch summary is "NO PENDING TRANSACTIONS IN BATCH"

  Scenario: Pending transactions are scored and high-risk ones are flagged
    Given a watchlist "OFAC" entry matching name "Risky Customer"
    And a pending transaction "TXN-B001" for account "ACC0000007" of amount 50.00
    And a pending transaction "TXN-B002" for account "ACC0000008" of amount 50.00
    When the batch job runs with a maximum of 500 transactions
    Then the batch summary is "BATCH COMPLETE: SCORED=2 FLAGGED=1 ERRORS=0"
    And transaction "TXN-B001" has status "S"
    And transaction "TXN-B002" has status "S"
    And a fraud alert exists for transaction "TXN-B002"
    And no fraud alert exists for transaction "TXN-B001"

  Scenario: The batch respects the maximum-transactions cap
    Given a pending transaction "TXN-C001" for account "ACC0000007" of amount 50.00
    And a pending transaction "TXN-C002" for account "ACC0000007" of amount 50.00
    And a pending transaction "TXN-C003" for account "ACC0000007" of amount 50.00
    When the batch job runs with a maximum of 2 transactions
    Then the batch summary is "BATCH COMPLETE: SCORED=2 FLAGGED=0 ERRORS=0"
    And 1 transaction still has status "P"
