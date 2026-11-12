Feature: Fraud alert writing and MQ notification (AlertWriterService, MqNotificationService)

  Writes a fraud alert row and notifies the case management queue in a single
  unit of work. A failed MQ put must be logged but must never roll back the
  alert DB write (ARCHITECTURE.md §8 invariant 9, §9).

  Scenario: Alert is written and the case management queue is notified
    When a fraud alert is written for transaction "TXN0000000001" account "ACC0000005" amount 2500.00 score 0.8250
    Then the alert is persisted with amount 2500.00 and score 0.8250
    And the return code is "00"
    And the message is "Fraud alert written successfully"
    And no MQ failure has been logged

  Scenario: A failed MQ put does not roll back the alert write
    Given the MQ broker is unavailable
    When a fraud alert is written for transaction "TXN0000000002" account "ACC0000005" amount 3000.00 score 0.9100
    Then the alert is persisted with amount 3000.00 and score 0.9100
    And the return code is "00"
    And an MQ failure has been logged for transaction "TXN0000000002" account "ACC0000005"
