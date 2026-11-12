package com.customer.can.search.service;

import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.Logger;
import org.apache.logging.log4j.ThreadContext;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

@Service
public class SearchService {
    private static final Logger log = LogManager.getLogger(SearchService.class);

    private final JdbcTemplate jdbcTemplate;

    public SearchService(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    public List<Map<String, Object>> searchPortfolios(String query, String status) {
        log.info("action=search_portfolios query={} status={} correlationId={}", query, status, ThreadContext.get("correlationId"));
        StringBuilder sql = new StringBuilder(
            "SELECT p.id, p.name, p.description, p.status, p.project_phase, p.created_at, " +
            "       COUNT(pr.id) AS property_count " +
            "FROM portfolio p " +
            "LEFT JOIN property pr ON pr.portfolio_id = p.id ");

        List<Object> params = new ArrayList<>();
        List<String> conditions = new ArrayList<>();

        if (query != null && !query.trim().isEmpty()) {
            conditions.add("(UPPER(p.name) LIKE UPPER(?) OR UPPER(p.description) LIKE UPPER(?))");
            params.add("%" + query + "%");
            params.add("%" + query + "%");
        }
        if (status != null && !status.trim().isEmpty()) {
            conditions.add("p.status = ?");
            params.add(status);
        }
        if (!conditions.isEmpty()) {
            sql.append("WHERE ").append(String.join(" AND ", conditions)).append(" ");
        }
        sql.append("GROUP BY p.id, p.name, p.description, p.status, p.project_phase, p.created_at ");
        sql.append("ORDER BY p.created_at DESC");

        return jdbcTemplate.queryForList(sql.toString(), params.toArray());
    }

    public List<Map<String, Object>> searchProperties(String query, String portfolioId, String propertyType, String city) {
        log.info("action=search_properties query={} portfolioId={} correlationId={}", query, portfolioId, ThreadContext.get("correlationId"));
        StringBuilder sql = new StringBuilder(
            "SELECT pr.id, pr.name, pr.address, pr.city, pr.postcode, pr.property_type, pr.status, " +
            "       pr.portfolio_id, p.name AS portfolio_name " +
            "FROM property pr " +
            "JOIN portfolio p ON p.id = pr.portfolio_id ");

        List<Object> params = new ArrayList<>();
        List<String> conditions = new ArrayList<>();

        if (query != null && !query.trim().isEmpty()) {
            conditions.add("(UPPER(pr.name) LIKE UPPER(?) OR UPPER(pr.address) LIKE UPPER(?) OR UPPER(pr.city) LIKE UPPER(?))");
            params.add("%" + query + "%");
            params.add("%" + query + "%");
            params.add("%" + query + "%");
        }
        if (portfolioId != null && !portfolioId.trim().isEmpty()) {
            conditions.add("pr.portfolio_id = ?");
            params.add(portfolioId);
        }
        if (propertyType != null && !propertyType.trim().isEmpty()) {
            conditions.add("pr.property_type = ?");
            params.add(propertyType);
        }
        if (city != null && !city.trim().isEmpty()) {
            conditions.add("UPPER(pr.city) = UPPER(?)");
            params.add(city);
        }
        if (!conditions.isEmpty()) {
            sql.append("WHERE ").append(String.join(" AND ", conditions)).append(" ");
        }
        sql.append("ORDER BY pr.created_at DESC");

        return jdbcTemplate.queryForList(sql.toString(), params.toArray());
    }

    public List<Map<String, Object>> searchDocuments(String query, String portfolioId) {
        log.info("action=search_documents query={} portfolioId={} correlationId={}", query, portfolioId, ThreadContext.get("correlationId"));
        StringBuilder sql = new StringBuilder(
            "SELECT d.id, d.file_name, d.content_type, d.file_size, d.status, d.upload_date, " +
            "       d.portfolio_id, d.property_id " +
            "FROM document d WHERE 1=1 ");

        List<Object> params = new ArrayList<>();

        if (query != null && !query.trim().isEmpty()) {
            sql.append("AND (UPPER(d.file_name) LIKE UPPER(?) OR UPPER(d.extracted_text) LIKE UPPER(?)) ");
            params.add("%" + query + "%");
            params.add("%" + query + "%");
        }
        if (portfolioId != null && !portfolioId.trim().isEmpty()) {
            sql.append("AND d.portfolio_id = ? ");
            params.add(portfolioId);
        }
        sql.append("ORDER BY d.upload_date DESC");

        return jdbcTemplate.queryForList(sql.toString(), params.toArray());
    }

    public Map<String, Object> globalSearch(String query) {
        Map<String, Object> result = new HashMap<>();
        result.put("portfolios", searchPortfolios(query, null));
        result.put("properties", searchProperties(query, null, null, null));
        result.put("documents", searchDocuments(query, null));
        return result;
    }
}
