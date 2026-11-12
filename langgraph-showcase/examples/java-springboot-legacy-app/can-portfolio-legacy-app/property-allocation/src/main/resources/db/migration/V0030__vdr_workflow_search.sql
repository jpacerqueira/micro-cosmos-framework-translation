CREATE TABLE document (
  id              VARCHAR2(36)  DEFAULT SYS_GUID() PRIMARY KEY,
  portfolio_id    VARCHAR2(36)  REFERENCES portfolio(id),
  property_id     VARCHAR2(36)  REFERENCES property(id),
  file_name       VARCHAR2(500) NOT NULL,
  content_type    VARCHAR2(100),
  file_size       NUMBER(18),
  extracted_text  CLOB,
  uploaded_by     VARCHAR2(36),
  upload_date     TIMESTAMP     DEFAULT SYSTIMESTAMP NOT NULL,
  status          VARCHAR2(50)  DEFAULT 'PROCESSED'
);

CREATE TABLE allocation_workflow (
  id           VARCHAR2(36)  DEFAULT SYS_GUID() PRIMARY KEY,
  property_id  VARCHAR2(36)  NOT NULL REFERENCES property(id),
  portfolio_id VARCHAR2(36)  NOT NULL REFERENCES portfolio(id),
  state        VARCHAR2(50)  DEFAULT 'PENDING' NOT NULL,
  broker_id    VARCHAR2(36),
  valuer_id    VARCHAR2(36),
  updated_at   TIMESTAMP     DEFAULT SYSTIMESTAMP NOT NULL,
  created_at   TIMESTAMP     DEFAULT SYSTIMESTAMP NOT NULL
);

CREATE INDEX idx_document_portfolio   ON document(portfolio_id);
CREATE INDEX idx_workflow_property    ON allocation_workflow(property_id);
