CREATE TABLE portfolio (
  id            VARCHAR2(36)  DEFAULT SYS_GUID() PRIMARY KEY,
  name          VARCHAR2(255) NOT NULL,
  description   CLOB,
  status        VARCHAR2(50)  DEFAULT 'OPEN' NOT NULL,
  cut_off_date  DATE,
  final_bid_date DATE,
  project_phase VARCHAR2(50),
  created_at    TIMESTAMP     DEFAULT SYSTIMESTAMP NOT NULL,
  created_by    VARCHAR2(36),
  updated_at    TIMESTAMP     DEFAULT SYSTIMESTAMP,
  correlation_id VARCHAR2(36)
);

CREATE TABLE property (
  id            VARCHAR2(36)  DEFAULT SYS_GUID() PRIMARY KEY,
  portfolio_id  VARCHAR2(36)  NOT NULL REFERENCES portfolio(id),
  name          VARCHAR2(255) NOT NULL,
  address       VARCHAR2(500),
  city          VARCHAR2(100),
  postcode      VARCHAR2(20),
  property_type VARCHAR2(50),
  status        VARCHAR2(50)  DEFAULT 'PENDING',
  created_at    TIMESTAMP     DEFAULT SYSTIMESTAMP NOT NULL
);

CREATE TABLE property_valuation (
  id                VARCHAR2(36)   DEFAULT SYS_GUID() PRIMARY KEY,
  property_id       VARCHAR2(36)   NOT NULL REFERENCES property(id),
  portfolio_id      VARCHAR2(36)   NOT NULL REFERENCES portfolio(id),
  valuation_amount  NUMBER(18,2),
  valuation_date    DATE,
  valuer_company_id VARCHAR2(36),
  status            VARCHAR2(50)   DEFAULT 'PENDING',
  created_at        TIMESTAMP      DEFAULT SYSTIMESTAMP NOT NULL
);

CREATE TABLE broker_allocation (
  id                VARCHAR2(36)  DEFAULT SYS_GUID() PRIMARY KEY,
  property_id       VARCHAR2(36)  NOT NULL REFERENCES property(id),
  portfolio_id      VARCHAR2(36)  NOT NULL REFERENCES portfolio(id),
  broker_company_id VARCHAR2(36),
  assigned_at       TIMESTAMP,
  status            VARCHAR2(50)  DEFAULT 'PENDING'
);

CREATE INDEX idx_property_portfolio ON property(portfolio_id);
CREATE INDEX idx_valuation_property ON property_valuation(property_id);
CREATE INDEX idx_broker_portfolio   ON broker_allocation(portfolio_id);
