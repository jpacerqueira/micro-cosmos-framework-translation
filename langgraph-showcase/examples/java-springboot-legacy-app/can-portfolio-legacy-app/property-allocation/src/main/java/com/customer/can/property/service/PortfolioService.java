package com.customer.can.property.service;

import com.customer.can.property.domain.AuditEventLog;
import com.customer.can.property.domain.Portfolio;
import com.customer.can.property.messaging.JmsEventPublisher;
import com.customer.can.property.repository.AuditEventLogRepository;
import com.customer.can.property.repository.PortfolioRepository;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.Logger;
import org.apache.logging.log4j.ThreadContext;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.Optional;

@Service
public class PortfolioService {
    private static final Logger log = LogManager.getLogger(PortfolioService.class);

    private final PortfolioRepository portfolioRepository;
    private final AuditEventLogRepository auditEventLogRepository;
    private final JmsEventPublisher jmsEventPublisher;
    private final ObjectMapper objectMapper;

    public PortfolioService(PortfolioRepository portfolioRepository,
                            AuditEventLogRepository auditEventLogRepository,
                            JmsEventPublisher jmsEventPublisher,
                            ObjectMapper objectMapper) {
        this.portfolioRepository = portfolioRepository;
        this.auditEventLogRepository = auditEventLogRepository;
        this.jmsEventPublisher = jmsEventPublisher;
        this.objectMapper = objectMapper;
    }

    public List<Portfolio> findAll() {
        return portfolioRepository.findAll();
    }

    public Optional<Portfolio> findById(String id) {
        return portfolioRepository.findById(id);
    }

    @Transactional
    public Portfolio create(Portfolio portfolio) {
        Portfolio saved = portfolioRepository.save(portfolio);
        writeAuditLog(saved.getId(), "PORTFOLIO", saved.getId(), "PORTFOLIO_CREATED", toJson(saved));
        jmsEventPublisher.publishPortfolioEvent("PORTFOLIO_CREATED", saved.getId(), toJson(saved));
        log.info("Portfolio created: {}", saved.getId());
        return saved;
    }

    @Transactional
    public Portfolio close(String id) {
        Portfolio portfolio = portfolioRepository.findById(id)
                .orElseThrow(() -> new RuntimeException("Portfolio not found: " + id));
        portfolio.setStatus("CLOSED");
        Portfolio saved = portfolioRepository.save(portfolio);
        writeAuditLog(id, "PORTFOLIO", id, "PORTFOLIO_CLOSED", toJson(saved));
        jmsEventPublisher.publishPortfolioEvent("PORTFOLIO_CLOSED", id, toJson(saved));
        return saved;
    }

    @Transactional
    public Portfolio update(String id, Portfolio update) {
        Portfolio existing = portfolioRepository.findById(id)
                .orElseThrow(() -> new RuntimeException("Portfolio not found: " + id));
        if (update.getName() != null) existing.setName(update.getName());
        if (update.getDescription() != null) existing.setDescription(update.getDescription());
        if (update.getProjectPhase() != null) existing.setProjectPhase(update.getProjectPhase());
        if (update.getCutOffDate() != null) existing.setCutOffDate(update.getCutOffDate());
        if (update.getFinalBidDate() != null) existing.setFinalBidDate(update.getFinalBidDate());
        Portfolio saved = portfolioRepository.save(existing);
        writeAuditLog(id, "PORTFOLIO", id, "PORTFOLIO_UPDATED", toJson(saved));
        return saved;
    }

    private void writeAuditLog(String portfolioId, String entityType, String entityId, String eventType, String payload) {
        AuditEventLog log = new AuditEventLog();
        log.setPortfolioId(portfolioId);
        log.setEntityType(entityType);
        log.setEntityId(entityId);
        log.setEventType(eventType);
        log.setPayload(payload);
        log.setCorrelationId(ThreadContext.get("correlationId"));
        auditEventLogRepository.save(log);
    }

    private String toJson(Object obj) {
        try {
            return objectMapper.writeValueAsString(obj);
        } catch (JsonProcessingException e) {
            return "{}";
        }
    }
}
