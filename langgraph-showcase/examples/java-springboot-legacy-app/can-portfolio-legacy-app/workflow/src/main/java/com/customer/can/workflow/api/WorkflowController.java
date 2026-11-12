package com.customer.can.workflow.api;

import com.customer.can.workflow.domain.AllocationWorkflow;
import com.customer.can.workflow.service.AllocationWorkflowService;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/v1/workflows")
@Api(tags = "Allocation Workflow")
public class WorkflowController {
    private final AllocationWorkflowService workflowService;

    public WorkflowController(AllocationWorkflowService workflowService) {
        this.workflowService = workflowService;
    }

    @GetMapping("/portfolio/{portfolioId}")
    @ApiOperation("List workflows for a portfolio")
    public ResponseEntity<List<AllocationWorkflow>> listByPortfolio(@PathVariable String portfolioId) {
        return ResponseEntity.ok(workflowService.findByPortfolio(portfolioId));
    }

    @GetMapping("/property/{propertyId}")
    @ApiOperation("Get workflow for a property")
    public ResponseEntity<AllocationWorkflow> getByProperty(@PathVariable String propertyId) {
        return workflowService.findByProperty(propertyId)
                .map(ResponseEntity::ok)
                .orElse(ResponseEntity.notFound().build());
    }

    @PostMapping("/property/{propertyId}/init")
    @ApiOperation("Initialize workflow for a property")
    public ResponseEntity<AllocationWorkflow> init(@PathVariable String propertyId,
                                                    @RequestParam String portfolioId) {
        return ResponseEntity.status(201).body(workflowService.createOrGet(propertyId, portfolioId));
    }

    @PostMapping("/property/{propertyId}/advance")
    @ApiOperation("Advance workflow to next state")
    public ResponseEntity<AllocationWorkflow> advance(@PathVariable String propertyId,
                                                       @RequestBody Map<String, String> body) {
        String assigneeId = body.getOrDefault("assigneeId", "");
        return ResponseEntity.ok(workflowService.advance(propertyId, assigneeId));
    }
}
