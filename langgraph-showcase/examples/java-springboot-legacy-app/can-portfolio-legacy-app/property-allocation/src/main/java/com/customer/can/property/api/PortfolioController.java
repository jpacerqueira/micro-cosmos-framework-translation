package com.customer.can.property.api;

import com.customer.can.property.domain.Portfolio;
import com.customer.can.property.service.PortfolioService;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.Logger;
import org.apache.logging.log4j.ThreadContext;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/api/v1/portfolios")
@Api(tags = "Portfolio Management")
public class PortfolioController {
    private static final Logger log = LogManager.getLogger(PortfolioController.class);

    private final PortfolioService portfolioService;

    public PortfolioController(PortfolioService portfolioService) {
        this.portfolioService = portfolioService;
    }

    @GetMapping
    @ApiOperation("List all portfolios")
    public ResponseEntity<List<Portfolio>> listPortfolios() {
        log.info("action=list_portfolios correlationId={}", ThreadContext.get("correlationId"));
        return ResponseEntity.ok(portfolioService.findAll());
    }

    @GetMapping("/{id}")
    @ApiOperation("Get portfolio by ID")
    public ResponseEntity<Portfolio> getPortfolio(@PathVariable String id) {
        log.info("action=get_portfolio portfolioId={} correlationId={}", id, ThreadContext.get("correlationId"));
        return portfolioService.findById(id)
                .map(ResponseEntity::ok)
                .orElse(ResponseEntity.notFound().build());
    }

    @PostMapping
    @ApiOperation("Create a new portfolio")
    public ResponseEntity<Portfolio> createPortfolio(@RequestBody Portfolio portfolio) {
        log.info("action=create_portfolio name={} correlationId={}", portfolio.getName(), ThreadContext.get("correlationId"));
        Portfolio created = portfolioService.create(portfolio);
        return ResponseEntity.status(201).body(created);
    }

    @PutMapping("/{id}")
    @ApiOperation("Update portfolio")
    public ResponseEntity<Portfolio> updatePortfolio(@PathVariable String id, @RequestBody Portfolio portfolio) {
        return ResponseEntity.ok(portfolioService.update(id, portfolio));
    }

    @PutMapping("/{id}/close")
    @ApiOperation("Close a portfolio")
    public ResponseEntity<Portfolio> closePortfolio(@PathVariable String id) {
        log.info("action=close_portfolio portfolioId={} correlationId={}", id, ThreadContext.get("correlationId"));
        return ResponseEntity.ok(portfolioService.close(id));
    }
}
