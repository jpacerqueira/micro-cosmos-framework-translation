package com.customer.can.workflow.service;

import com.customer.can.workflow.domain.AllocationWorkflow;
import com.customer.can.workflow.repository.AllocationWorkflowRepository;
import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.Logger;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.Optional;

@Service
public class AllocationWorkflowService {
    private static final Logger log = LogManager.getLogger(AllocationWorkflowService.class);

    // State machine: PENDING -> BROKER_ASSIGNED -> VALUER_ASSIGNED -> VALUED -> CLOSED
    private static final java.util.Map<String, String> TRANSITIONS = new java.util.HashMap<>();
    static {
        TRANSITIONS.put("PENDING", "BROKER_ASSIGNED");
        TRANSITIONS.put("BROKER_ASSIGNED", "VALUER_ASSIGNED");
        TRANSITIONS.put("VALUER_ASSIGNED", "VALUED");
        TRANSITIONS.put("VALUED", "CLOSED");
    }

    private final AllocationWorkflowRepository workflowRepository;

    public AllocationWorkflowService(AllocationWorkflowRepository workflowRepository) {
        this.workflowRepository = workflowRepository;
    }

    @Transactional
    public AllocationWorkflow createOrGet(String propertyId, String portfolioId) {
        return workflowRepository.findByPropertyId(propertyId).orElseGet(() -> {
            AllocationWorkflow wf = new AllocationWorkflow();
            wf.setPropertyId(propertyId);
            wf.setPortfolioId(portfolioId);
            wf.setState("PENDING");
            return workflowRepository.save(wf);
        });
    }

    @Transactional
    public AllocationWorkflow advance(String propertyId, String assigneeId) {
        AllocationWorkflow wf = workflowRepository.findByPropertyId(propertyId)
                .orElseThrow(() -> new RuntimeException("Workflow not found for property: " + propertyId));

        String nextState = TRANSITIONS.get(wf.getState());
        if (nextState == null) {
            throw new RuntimeException("Cannot advance from state: " + wf.getState());
        }

        if ("BROKER_ASSIGNED".equals(nextState)) {
            wf.setBrokerId(assigneeId);
        } else if ("VALUER_ASSIGNED".equals(nextState)) {
            wf.setValuerId(assigneeId);
        }

        wf.setState(nextState);
        AllocationWorkflow saved = workflowRepository.save(wf);
        log.info("action=workflow_advance propertyId={} newState={}", propertyId, nextState);
        return saved;
    }

    public List<AllocationWorkflow> findByPortfolio(String portfolioId) {
        return workflowRepository.findByPortfolioId(portfolioId);
    }

    public Optional<AllocationWorkflow> findByProperty(String propertyId) {
        return workflowRepository.findByPropertyId(propertyId);
    }

    public List<AllocationWorkflow> findByState(String state) {
        return workflowRepository.findByState(state);
    }
}
