package com.customer.can.property.api;

import com.customer.can.property.domain.Property;
import com.customer.can.property.service.PropertyService;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.Logger;
import org.apache.logging.log4j.ThreadContext;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/api/v1/portfolios/{portfolioId}/properties")
@Api(tags = "Property Management")
public class PropertyController {
    private static final Logger log = LogManager.getLogger(PropertyController.class);

    private final PropertyService propertyService;

    public PropertyController(PropertyService propertyService) {
        this.propertyService = propertyService;
    }

    @GetMapping
    @ApiOperation("List properties in a portfolio")
    public ResponseEntity<List<Property>> listProperties(@PathVariable String portfolioId) {
        log.info("action=list_properties portfolioId={} correlationId={}", portfolioId, ThreadContext.get("correlationId"));
        return ResponseEntity.ok(propertyService.findByPortfolioId(portfolioId));
    }

    @GetMapping("/{id}")
    @ApiOperation("Get property by ID")
    public ResponseEntity<Property> getProperty(@PathVariable String portfolioId, @PathVariable String id) {
        return propertyService.findById(id)
                .map(ResponseEntity::ok)
                .orElse(ResponseEntity.notFound().build());
    }

    @PostMapping
    @ApiOperation("Add property to portfolio")
    public ResponseEntity<Property> createProperty(@PathVariable String portfolioId, @RequestBody Property property) {
        log.info("action=create_property portfolioId={} correlationId={}", portfolioId, ThreadContext.get("correlationId"));
        Property created = propertyService.create(portfolioId, property);
        return ResponseEntity.status(201).body(created);
    }

    @PutMapping("/{id}/status")
    @ApiOperation("Update property status")
    public ResponseEntity<Property> updateStatus(@PathVariable String portfolioId,
                                                  @PathVariable String id,
                                                  @RequestParam String status) {
        return ResponseEntity.ok(propertyService.updateStatus(id, status));
    }
}
