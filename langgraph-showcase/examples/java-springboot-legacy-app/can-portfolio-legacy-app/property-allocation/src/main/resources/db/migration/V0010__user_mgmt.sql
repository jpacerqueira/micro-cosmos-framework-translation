CREATE TABLE company (
  id          VARCHAR2(36)  DEFAULT SYS_GUID() PRIMARY KEY,
  name        VARCHAR2(255) NOT NULL,
  company_type VARCHAR2(50) NOT NULL,
  created_at  TIMESTAMP     DEFAULT SYSTIMESTAMP NOT NULL
);

CREATE TABLE app_user (
  id           VARCHAR2(36)  DEFAULT SYS_GUID() PRIMARY KEY,
  email        VARCHAR2(255) NOT NULL UNIQUE,
  full_name    VARCHAR2(255) NOT NULL,
  password_hash VARCHAR2(255) NOT NULL,
  role         VARCHAR2(50)  NOT NULL,
  company_id   VARCHAR2(36)  REFERENCES company(id),
  active       NUMBER(1)     DEFAULT 1 NOT NULL,
  created_at   TIMESTAMP     DEFAULT SYSTIMESTAMP NOT NULL,
  last_login   TIMESTAMP
);

CREATE INDEX idx_app_user_email ON app_user(email);
CREATE INDEX idx_app_user_company ON app_user(company_id);
