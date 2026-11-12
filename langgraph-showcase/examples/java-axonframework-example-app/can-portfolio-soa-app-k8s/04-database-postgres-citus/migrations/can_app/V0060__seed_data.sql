-- =====================================================================
-- V0060 -- Local-dev seed data: companies, users, portfolios, properties.
-- Safe to run on any environment: all UUIDs are pinned so re-runs are
-- idempotent via ON CONFLICT DO NOTHING.
-- =====================================================================

-- ── Companies ─────────────────────────────────────────────────────────
SET search_path TO user_mgmt, public;

INSERT INTO company (company_id, company_name, company_type) VALUES
  ('00000000-0000-0000-0000-000000000001', 'Beyond Capital',       'INTERNAL'),
  ('00000000-0000-0000-0000-000000000002', 'Summit Brokers Ltd',   'BROKER'),
  ('00000000-0000-0000-0000-000000000003', 'Apex Valuers Ltd',     'VALUER'),
  ('00000000-0000-0000-0000-000000000004', 'First National Lender','LENDER')
ON CONFLICT (company_id) DO NOTHING;

-- ── Users ─────────────────────────────────────────────────────────────
INSERT INTO app_user (user_id, user_name, user_email, company_id, is_external) VALUES
  ('10000000-0000-0000-0000-000000000001', 'Alice Admin',   'alice@beyondcapital.local',    '00000000-0000-0000-0000-000000000001', FALSE),
  ('10000000-0000-0000-0000-000000000002', 'Bob Broker',    'bob@summitbrokers.local',      '00000000-0000-0000-0000-000000000002', TRUE),
  ('10000000-0000-0000-0000-000000000003', 'Carol Valuer',  'carol@apexvaluers.local',      '00000000-0000-0000-0000-000000000003', TRUE),
  ('10000000-0000-0000-0000-000000000004', 'Dave Viewer',   'dave@beyondcapital.local',     '00000000-0000-0000-0000-000000000001', FALSE),
  ('10000000-0000-0000-0000-000000000005', 'Eva SysAdmin',  'eva@beyondcapital.local',      '00000000-0000-0000-0000-000000000001', FALSE)
ON CONFLICT (user_id) DO NOTHING;

-- ── User roles ────────────────────────────────────────────────────────
-- role_id: 1=PORTFOLIO_ADMIN 2=BROKER 3=VALUER 4=VIEWER 5=SYS_ADMIN
INSERT INTO user_role (user_id, role_id) VALUES
  ('10000000-0000-0000-0000-000000000001', 1),  -- Alice  → PORTFOLIO_ADMIN
  ('10000000-0000-0000-0000-000000000002', 2),  -- Bob    → BROKER
  ('10000000-0000-0000-0000-000000000003', 3),  -- Carol  → VALUER
  ('10000000-0000-0000-0000-000000000004', 4),  -- Dave   → VIEWER
  ('10000000-0000-0000-0000-000000000005', 5)   -- Eva    → SYS_ADMIN
ON CONFLICT (user_id, role_id) DO NOTHING;

-- ── Portfolio schema ───────────────────────────────────────────────────
SET search_path TO portfolio, public;

-- Template catalogue
INSERT INTO template_catalogue (template_id, template_name, template_type, property_sector) VALUES
  (1, 'Standard Commercial',   'COMMERCIAL', 'OFFICE'),
  (2, 'Retail Unit',           'COMMERCIAL', 'RETAIL'),
  (3, 'Industrial Shed',       'INDUSTRIAL', 'WAREHOUSE'),
  (4, 'Mixed-Use Block',       'MIXED',      'MIXED')
ON CONFLICT (template_id) DO NOTHING;

-- Portfolios
INSERT INTO portfolio (portfolio_id, portfolio_name, portfolio_description, cut_off_date, final_bid_date, project_phase, status) VALUES
  ('20000000-0000-0000-0000-000000000001',
   'London Commercial Portfolio 2025',
   'A mixed-use commercial portfolio in Central London comprising offices and retail units.',
   '2025-06-30', '2025-09-30', 'PHASE_1', 'OPEN'),
  ('20000000-0000-0000-0000-000000000002',
   'Manchester Industrial Portfolio',
   'Industrial and warehouse assets across Greater Manchester, suitable for last-mile logistics.',
   '2025-07-31', '2025-10-31', 'PHASE_1', 'BIDDING')
ON CONFLICT (portfolio_id) DO NOTHING;

-- portfolio_view (read-side projection pre-populated for BFF)
INSERT INTO portfolio_view (portfolio_id, name, description, cut_off_date, final_bid_date, project_phase, status) VALUES
  ('20000000-0000-0000-0000-000000000001',
   'London Commercial Portfolio 2025',
   'A mixed-use commercial portfolio in Central London comprising offices and retail units.',
   '2025-06-30', '2025-09-30', 'PHASE_1', 'OPEN'),
  ('20000000-0000-0000-0000-000000000002',
   'Manchester Industrial Portfolio',
   'Industrial and warehouse assets across Greater Manchester, suitable for last-mile logistics.',
   '2025-07-31', '2025-10-31', 'PHASE_1', 'BIDDING')
ON CONFLICT (portfolio_id) DO NOTHING;

-- Properties — London portfolio
INSERT INTO property (property_id, portfolio_id, property_name,
                      property_address_line_1, property_city, property_state_region,
                      property_address_postcode,
                      property_geolocation_lat, property_geolocation_long) VALUES
  ('30000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000001',
   'Canary Wharf Office Tower A',
   '1 Canada Square', 'London', 'Greater London', 'E14 5AB', 51.5050, -0.0200),
  ('30000000-0000-0000-0000-000000000002', '20000000-0000-0000-0000-000000000001',
   'Covent Garden Retail Unit 12',
   '12 Long Acre', 'London', 'Greater London', 'WC2E 9LP', 51.5130, -0.1220),
  ('30000000-0000-0000-0000-000000000003', '20000000-0000-0000-0000-000000000001',
   'Shoreditch Mixed-Use Block',
   '45 Old Street', 'London', 'Greater London', 'EC1V 9HX', 51.5257, -0.0927)
ON CONFLICT (property_id) DO NOTHING;

-- Properties — Manchester portfolio
INSERT INTO property (property_id, portfolio_id, property_name,
                      property_address_line_1, property_city, property_state_region,
                      property_address_postcode,
                      property_geolocation_lat, property_geolocation_long) VALUES
  ('30000000-0000-0000-0000-000000000004', '20000000-0000-0000-0000-000000000002',
   'Trafford Park Warehouse Unit 7',
   '7 Trafford Wharf Road', 'Manchester', 'Greater Manchester', 'M17 1EX', 53.4680, -2.3040),
  ('30000000-0000-0000-0000-000000000005', '20000000-0000-0000-0000-000000000002',
   'Salford Industrial Estate Block B',
   'Block B, Port Salford', 'Salford', 'Greater Manchester', 'M5 2RN', 53.4870, -2.3120)
ON CONFLICT (property_id) DO NOTHING;

-- property_view (read-side)
INSERT INTO property_view (property_id, portfolio_id, name,
                           address_line_1, city, postcode,
                           valuation, broker_company_id, allocation_status) VALUES
  ('30000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000001',
   'Canary Wharf Office Tower A',     '1 Canada Square',         'London',     'E14 5AB',  45000000.00, '00000000-0000-0000-0000-000000000002', 'ALLOCATED'),
  ('30000000-0000-0000-0000-000000000002', '20000000-0000-0000-0000-000000000001',
   'Covent Garden Retail Unit 12',    '12 Long Acre',            'London',     'WC2E 9LP', 12500000.00, '00000000-0000-0000-0000-000000000002', 'ALLOCATED'),
  ('30000000-0000-0000-0000-000000000003', '20000000-0000-0000-0000-000000000001',
   'Shoreditch Mixed-Use Block',      '45 Old Street',           'London',     'EC1V 9HX', 18750000.00, NULL,                                   'PENDING'),
  ('30000000-0000-0000-0000-000000000004', '20000000-0000-0000-0000-000000000002',
   'Trafford Park Warehouse Unit 7',  '7 Trafford Wharf Road',   'Manchester', 'M17 1EX',  8200000.00,  '00000000-0000-0000-0000-000000000002', 'ALLOCATED'),
  ('30000000-0000-0000-0000-000000000005', '20000000-0000-0000-0000-000000000002',
   'Salford Industrial Estate Block B','Block B, Port Salford',  'Salford',    'M5 2RN',   6900000.00,  NULL,                                   'PENDING')
ON CONFLICT (property_id) DO NOTHING;

-- Units under London properties
INSERT INTO unit (property_id, unit_address, unit_size, unit_area, unit_number, unit_type) VALUES
  ('30000000-0000-0000-0000-000000000001', 'Floor 12, Canary Wharf Tower A',  1200.00, 'sq ft', 12, 'OFFICE'),
  ('30000000-0000-0000-0000-000000000001', 'Floor 13, Canary Wharf Tower A',  1200.00, 'sq ft', 13, 'OFFICE'),
  ('30000000-0000-0000-0000-000000000002', 'Ground Floor, 12 Long Acre',       450.00, 'sq ft',  1, 'RETAIL'),
  ('30000000-0000-0000-0000-000000000003', 'Ground Floor Retail',              600.00, 'sq ft',  1, 'RETAIL'),
  ('30000000-0000-0000-0000-000000000003', 'Floors 1-3 Office',               2400.00, 'sq ft',  2, 'OFFICE');

-- Broker allocations
INSERT INTO broker_allocation (property_id, portfolio_id,
                                fcl_broker_company_name, fcl_broker_user_id, fcl_valuer_user_id,
                                company_id_1) VALUES
  ('30000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000001',
   'Summit Brokers Ltd', '10000000-0000-0000-0000-000000000002', '10000000-0000-0000-0000-000000000003',
   '00000000-0000-0000-0000-000000000002'),
  ('30000000-0000-0000-0000-000000000002', '20000000-0000-0000-0000-000000000001',
   'Summit Brokers Ltd', '10000000-0000-0000-0000-000000000002', '10000000-0000-0000-0000-000000000003',
   '00000000-0000-0000-0000-000000000002'),
  ('30000000-0000-0000-0000-000000000004', '20000000-0000-0000-0000-000000000002',
   'Summit Brokers Ltd', '10000000-0000-0000-0000-000000000002', NULL,
   '00000000-0000-0000-0000-000000000002');
