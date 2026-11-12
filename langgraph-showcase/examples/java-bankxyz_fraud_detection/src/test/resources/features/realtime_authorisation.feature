Feature: Real-time authorisation endpoint (RealtimeCheckController)

  POST /api/v1/authorise maps the composite fraud score to an authorisation
  decision within the 180ms SLA (ARCHITECTURE.md §3, §8, §12). The BDD suite
  raises the SLA limit to 5000ms for every scenario except the dedicated SLA
  breach scenario, so decision-mapping assertions aren't at the mercy of
  container scheduling jitter.

  Background:
    Given an active account "ACC0000006" for customer "Alice Brown" in country "GBR"

  Scenario: Low-risk transaction is approved
    When "ACC0000006" authorises a transaction of amount 50.00 on channel "ONLINE"
    Then the authorisation decision is "APPROVE" with return code "00"

  Scenario: Combined high-risk signals are reviewed and an alert is raised
    Given a blocked merchant "MCH00777"
    And a watchlist "INTERNAL" entry matching account "ACC0000006"
    And account "ACC0000006" made 5 prior transactions of 50.00 in the last 24 hours
    When "ACC0000006" authorises a transaction of amount 9999.00 on merchant "MCH00777" channel "ONLINE"
    Then the authorisation decision is "REVIEW" with return code "20"
    And a fraud alert exists for the authorised transaction

  Scenario: OFAC hit is declined and an alert is raised
    Given a watchlist "OFAC" entry matching name "Alice Brown"
    When "ACC0000006" authorises a transaction of amount 25.00 on channel "ONLINE"
    Then the authorisation decision is "DECLINE" with return code "10"
    And a fraud alert exists for the authorised transaction

  Scenario: Unknown account defaults to approve
    When "ACC0000999" authorises a transaction of amount 25.00 on channel "ONLINE"
    Then the authorisation decision is "APPROVE" with return code "00"

  Scenario: SLA breach defaults to approve even for a high-risk transaction
    Given the real-time SLA limit is breached
    And a watchlist "OFAC" entry matching name "Alice Brown"
    When "ACC0000006" authorises a transaction of amount 25.00 on channel "ONLINE"
    Then the authorisation decision is "APPROVE" with return code "00"
    And the authorisation message is "SLA exceeded - defaulting to approve"
    And an SLA breach has been logged

  Scenario: Manual batch trigger endpoint submits the nightly job
    When the batch job is triggered manually
    Then the batch trigger response is "Batch job submitted"
