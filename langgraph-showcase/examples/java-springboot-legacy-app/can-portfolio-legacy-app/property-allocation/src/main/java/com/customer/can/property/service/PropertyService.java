package com.customer.can.property.service;

import com.customer.can.property.domain.Property;
import com.customer.can.property.domain.Portfolio;
import com.customer.can.property.messaging.JmsEventPublisher;
import com.customer.can.property.repository.PropertyRepository;
import com.customer.can.property.repository.PortfolioRepository;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.Logger;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.Optional;

@Service
public class PropertyService {
    private static final Logger log = LogManager.getLogger(PropertyService.class);

    private final PropertyRepository propertyRepository;
    private final PortfolioRepository portfolioRepository;
    private final JmsEventPublisher jmsEventPublisher;
    private final ObjectMapper objectMapper;

    public PropertyService(PropertyRepository propertyRepository,
                           PortfolioRepository portfolioRepository,
                           JmsEventPublisher jmsEventPublisher,
                           ObjectMapper objectMapper) {
        this.propertyRepository = propertyRepository;
        this.portfolioRepository = portfolioRepository;
        this.jmsEventPublisher = jmsEventPublisher;
        this.objectMapper = objectMapper;
    }

    public List<Property> findByPortfolioId(String portfolioId) {
        return propertyRepository.findByPortfolioId(portfolioId);
    }

    public Optional<Property> findById(String id) {
        return propertyRepository.findById(id);
    }

    @Transactional
    public Property create(String portfolioId, Property property) {
        Portfolio portfolio = portfolioRepository.findById(portfolioId)
                .orElseThrow(() -> new RuntimeException("Portfolio not found: " + portfolioId));
        property.setPortfolio(portfolio);
        Property saved = propertyRepository.save(property);
        jmsEventPublisher.publishPortfolioEvent("PROPERTY_ADDED", portfolioId, toJson(saved));
        return saved;
    }

    @Transactional
    public Property updateStatus(String id, String status) {
        Property property = propertyRepository.findById(id)
                .orElseThrow(() -> new RuntimeException("Property not found: " + id));
        property.setStatus(status);
        return propertyRepository.save(property);
    }

    private String toJson(Object obj) {
        try {
            return objectMapper.writeValueAsString(obj);
        } catch (JsonProcessingException e) {
            return "{}";
        }
    }
}
