CREATE TABLE property_journal (
  id            VARCHAR2(36)  DEFAULT SYS_GUID() PRIMARY KEY,
  portfolio_id  VARCHAR2(36)  NOT NULL REFERENCES portfolio(id),
  entity_type   VARCHAR2(100),
  entity_id     VARCHAR2(36),
  event_type    VARCHAR2(100),
  payload       CLOB,
  correlation_id VARCHAR2(36),
  created_at    TIMESTAMP     DEFAULT SYSTIMESTAMP NOT NULL,
  created_by    VARCHAR2(100)
);

CREATE INDEX idx_journal_portfolio ON property_journal(portfolio_id);
CREATE INDEX idx_journal_entity    ON property_journal(entity_id);
