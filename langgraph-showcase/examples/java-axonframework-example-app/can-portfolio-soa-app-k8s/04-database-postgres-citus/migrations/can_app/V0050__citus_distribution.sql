-- =====================================================================
-- V0050 -- Citus distribution. Run only after the Citus extension is
-- enabled (it is on Azure Cosmos DB for PostgreSQL / Hyperscale Citus, and
-- on Azure Database for PostgreSQL Flexible Server when the extension is
-- in `azure.extensions`). On plain PG this script is a no-op.
--
-- Sharding strategy:
--   - portfolio_id is the natural co-location key for the property
--     domain - all per-portfolio joins (property, valuations, journal,
--     allocations) stay on a single worker.
--   - User/role/company tables are reference tables (replicated to every
--     worker) because they are small and joined from everywhere.
-- =====================================================================

DO $$
DECLARE has_citus BOOLEAN;
BEGIN
    SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname='citus') INTO has_citus;
    IF NOT has_citus THEN
        RAISE NOTICE 'Citus not present - skipping distribution';
        RETURN;
    END IF;

    -- Reference tables (small, joined-from-everywhere).
    PERFORM create_reference_table('user_mgmt.company');
    PERFORM create_reference_table('user_mgmt.role');
    PERFORM create_reference_table('user_mgmt.app_user');
    PERFORM create_reference_table('user_mgmt.user_role');

    -- Distributed tables - all keyed on portfolio_id for co-location.
    PERFORM create_distributed_table('portfolio.portfolio',           'portfolio_id');
    PERFORM create_distributed_table('portfolio.portfolio_view',      'portfolio_id', colocate_with => 'portfolio.portfolio');
    PERFORM create_distributed_table('portfolio.connection',          'portfolio_id', colocate_with => 'portfolio.portfolio');
    PERFORM create_distributed_table('portfolio.loan_facility',       'portfolio_id', colocate_with => 'portfolio.portfolio');
    PERFORM create_distributed_table('portfolio.property',            'portfolio_id', colocate_with => 'portfolio.portfolio');
    PERFORM create_distributed_table('portfolio.property_view',       'portfolio_id', colocate_with => 'portfolio.portfolio');
    PERFORM create_distributed_table('portfolio.property_valuation',  'portfolio_id', colocate_with => 'portfolio.portfolio');
    PERFORM create_distributed_table('portfolio.broker_allocation',   'portfolio_id', colocate_with => 'portfolio.portfolio');
    PERFORM create_distributed_table('portfolio.property_journal',    'portfolio_id', colocate_with => 'portfolio.portfolio');

    -- Unit/tenancy_schedule co-locate via property.property_id by passing
    -- the parent's distribution key. Use add_constraint workaround:
    -- we keep these as reference tables because they are typically small
    -- per-portfolio and cleaner to join.
    PERFORM create_reference_table('portfolio.unit');
    PERFORM create_reference_table('portfolio.tenancy_schedule');
    PERFORM create_reference_table('portfolio.template_catalogue');
    PERFORM create_reference_table('portfolio.template_allocation');
    PERFORM create_reference_table('portfolio.valuation_question');

    -- VDR raw documents follow the portfolio.
    PERFORM create_distributed_table('vdr.vdr_raw',            'portfolio_id');
    PERFORM create_distributed_table('vdr.document_extracted', 'document_id');

    -- Workflow process instances - by portfolio.
    PERFORM create_distributed_table('workflow.process_instance', 'portfolio_id');

    -- Search index - by portfolio so co-location works for filtered search.
    PERFORM create_distributed_table('search.search_index', 'portfolio_id');

    -- Audit is append-heavy, distributed by correlation_id so all events
    -- of one logical request land on the same shard.
    PERFORM create_distributed_table('audit.event_log', 'correlation_id');
END $$;
