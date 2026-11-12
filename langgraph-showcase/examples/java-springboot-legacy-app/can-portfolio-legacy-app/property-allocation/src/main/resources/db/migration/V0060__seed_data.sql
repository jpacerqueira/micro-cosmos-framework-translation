-- Seed Companies
INSERT INTO company (id, name, company_type, created_at)
VALUES ('c1000000-0000-0000-0000-000000000001', 'Beyond Capital', 'INTERNAL', SYSTIMESTAMP);

INSERT INTO company (id, name, company_type, created_at)
VALUES ('c1000000-0000-0000-0000-000000000002', 'Summit Brokers Ltd', 'BROKER', SYSTIMESTAMP);

INSERT INTO company (id, name, company_type, created_at)
VALUES ('c1000000-0000-0000-0000-000000000003', 'Apex Valuers Ltd', 'VALUER', SYSTIMESTAMP);

INSERT INTO company (id, name, company_type, created_at)
VALUES ('c1000000-0000-0000-0000-000000000004', 'First National Lender', 'LENDER', SYSTIMESTAMP);

-- Seed Users (BCrypt hash of 'password123')
INSERT INTO app_user (id, email, full_name, password_hash, role, company_id, active, created_at)
VALUES ('u1000000-0000-0000-0000-000000000001', 'alice@beyondcapital.local', 'Alice Admin',
        '$2a$10$N9qo8uLOickgx2ZMRZoMyeIjZAgcfl7p92ldGxad68LJZdL17lhWy',
        'PORTFOLIO_ADMIN', 'c1000000-0000-0000-0000-000000000001', 1, SYSTIMESTAMP);

INSERT INTO app_user (id, email, full_name, password_hash, role, company_id, active, created_at)
VALUES ('u1000000-0000-0000-0000-000000000002', 'bob@summitbrokers.local', 'Bob Broker',
        '$2a$10$N9qo8uLOickgx2ZMRZoMyeIjZAgcfl7p92ldGxad68LJZdL17lhWy',
        'BROKER', 'c1000000-0000-0000-0000-000000000002', 1, SYSTIMESTAMP);

INSERT INTO app_user (id, email, full_name, password_hash, role, company_id, active, created_at)
VALUES ('u1000000-0000-0000-0000-000000000003', 'carol@apexvaluers.local', 'Carol Valuer',
        '$2a$10$N9qo8uLOickgx2ZMRZoMyeIjZAgcfl7p92ldGxad68LJZdL17lhWy',
        'VALUER', 'c1000000-0000-0000-0000-000000000003', 1, SYSTIMESTAMP);

INSERT INTO app_user (id, email, full_name, password_hash, role, company_id, active, created_at)
VALUES ('u1000000-0000-0000-0000-000000000004', 'dave@beyondcapital.local', 'Dave Viewer',
        '$2a$10$N9qo8uLOickgx2ZMRZoMyeIjZAgcfl7p92ldGxad68LJZdL17lhWy',
        'VIEWER', 'c1000000-0000-0000-0000-000000000001', 1, SYSTIMESTAMP);

INSERT INTO app_user (id, email, full_name, password_hash, role, company_id, active, created_at)
VALUES ('u1000000-0000-0000-0000-000000000005', 'eva@beyondcapital.local', 'Eva SysAdmin',
        '$2a$10$N9qo8uLOickgx2ZMRZoMyeIjZAgcfl7p92ldGxad68LJZdL17lhWy',
        'SYS_ADMIN', 'c1000000-0000-0000-0000-000000000001', 1, SYSTIMESTAMP);

-- Seed Portfolios
INSERT INTO portfolio (id, name, description, status, project_phase, created_at, created_by)
VALUES ('p1000000-0000-0000-0000-000000000001',
        'London Commercial Portfolio 2025',
        'Prime commercial properties in central London available for acquisition',
        'OPEN', 'INITIAL_REVIEW', SYSTIMESTAMP,
        'u1000000-0000-0000-0000-000000000001');

INSERT INTO portfolio (id, name, description, status, project_phase, created_at, created_by)
VALUES ('p1000000-0000-0000-0000-000000000002',
        'Manchester Industrial Portfolio',
        'Industrial and logistics properties in Greater Manchester',
        'BIDDING', 'BROKER_ASSIGNED', SYSTIMESTAMP,
        'u1000000-0000-0000-0000-000000000001');

-- Seed Properties for London portfolio (3 properties)
INSERT INTO property (id, portfolio_id, name, address, city, postcode, property_type, status, created_at)
VALUES ('pr100000-0000-0000-0000-000000000001',
        'p1000000-0000-0000-0000-000000000001',
        'Canary Wharf Office Tower', '1 Canada Square', 'London', 'E14 5AB', 'OFFICE', 'BROKER_ASSIGNED', SYSTIMESTAMP);

INSERT INTO property (id, portfolio_id, name, address, city, postcode, property_type, status, created_at)
VALUES ('pr100000-0000-0000-0000-000000000002',
        'p1000000-0000-0000-0000-000000000001',
        'Shoreditch Retail Unit', '45 Old Street', 'London', 'EC1V 9HX', 'RETAIL', 'PENDING', SYSTIMESTAMP);

INSERT INTO property (id, portfolio_id, name, address, city, postcode, property_type, status, created_at)
VALUES ('pr100000-0000-0000-0000-000000000003',
        'p1000000-0000-0000-0000-000000000001',
        'City Warehouse Complex', '12 Bermondsey Street', 'London', 'SE1 3UW', 'INDUSTRIAL', 'VALUED', SYSTIMESTAMP);

-- Seed Properties for Manchester portfolio (2 properties)
INSERT INTO property (id, portfolio_id, name, address, city, postcode, property_type, status, created_at)
VALUES ('pr100000-0000-0000-0000-000000000004',
        'p1000000-0000-0000-0000-000000000002',
        'Trafford Park Logistics Hub', '5 Trafford Park Road', 'Manchester', 'M17 1PQ', 'INDUSTRIAL', 'BROKER_ASSIGNED', SYSTIMESTAMP);

INSERT INTO property (id, portfolio_id, name, address, city, postcode, property_type, status, created_at)
VALUES ('pr100000-0000-0000-0000-000000000005',
        'p1000000-0000-0000-0000-000000000002',
        'Salford Quays Office', '3 Salford Quays', 'Manchester', 'M50 3SP', 'OFFICE', 'VALUER_ASSIGNED', SYSTIMESTAMP);

COMMIT;
