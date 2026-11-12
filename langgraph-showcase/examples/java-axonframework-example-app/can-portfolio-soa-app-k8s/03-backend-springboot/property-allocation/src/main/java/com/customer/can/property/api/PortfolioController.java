package com.customer.can.property.api;

import com.customer.can.common.commands.PortfolioCommands.AddPropertyToPortfolio;
import com.customer.can.common.commands.PortfolioCommands.AllocatePropertyToBroker;
import com.customer.can.common.commands.PortfolioCommands.ClosePortfolio;
import com.customer.can.common.commands.PortfolioCommands.CreatePortfolio;
import com.customer.can.common.commands.PortfolioCommands.SubmitValuation;
import com.customer.can.property.infrastructure.PortfolioReadRepository;
import com.customer.can.property.infrastructure.PropertyReadEntity;
import com.customer.can.property.infrastructure.PropertyReadRepository;

import jakarta.validation.Valid;
import org.axonframework.commandhandling.gateway.CommandGateway;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Optional;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;

/**
 * REST API for portfolio operations. Writes go through the Axon command
 * gateway; reads are served from the JPA-backed projection. A unique
 * correlation id is propagated by {@link CorrelationIdFilter}.
 */
@RestController
@RequestMapping("/api/v1/portfolios")
public class PortfolioController {

    private final CommandGateway commands;
    private final PortfolioReadRepository portfolios;
    private final PropertyReadRepository properties;

    public PortfolioController(CommandGateway commands,
                               PortfolioReadRepository portfolios,
                               PropertyReadRepository properties) {
        this.commands = commands;
        this.portfolios = portfolios;
        this.properties = properties;
    }

    @GetMapping
    @PreAuthorize("hasAuthority('SCOPE_portfolio.read')")
    public List<com.customer.can.property.infrastructure.PortfolioReadEntity> listPortfolios(
            @RequestParam Optional<String> status) {
        return status.map(portfolios::findByStatus).orElseGet(portfolios::findAll);
    }

    @GetMapping("/{id}")
    @PreAuthorize("hasAuthority('SCOPE_portfolio.read')")
    public ResponseEntity<com.customer.can.property.infrastructure.PortfolioReadEntity> getPortfolio(
            @PathVariable UUID id) {
        return portfolios.findById(id)
                .map(ResponseEntity::ok)
                .orElse(ResponseEntity.notFound().build());
    }

    @PostMapping
    @PreAuthorize("hasAuthority('SCOPE_portfolio.write')")
    public CompletableFuture<ResponseEntity<UUID>> create(@RequestBody @Valid CreatePortfolio cmd) {
        return commands.<UUID>send(cmd).thenApply(ResponseEntity::ok);
    }

    @PostMapping("/{id}/properties")
    @PreAuthorize("hasAuthority('SCOPE_portfolio.write')")
    public CompletableFuture<ResponseEntity<Void>> addProperty(
            @PathVariable UUID id,
            @RequestBody @Valid AddPropertyToPortfolio body) {
        // Axon routes on body.portfolioId() (its @TargetAggregateIdentifier), not the
        // URL — without this check a caller with a generic write scope could target a
        // different portfolio than the one named in the path by sending a mismatched
        // portfolioId in the body.
        if (!id.equals(body.portfolioId())) {
            return CompletableFuture.completedFuture(ResponseEntity.badRequest().build());
        }
        return commands.send(body).thenApply(v -> ResponseEntity.accepted().build());
    }

    @PostMapping("/{id}/allocations")
    @PreAuthorize("hasAuthority('SCOPE_portfolio.write')")
    public CompletableFuture<ResponseEntity<Void>> allocate(
            @PathVariable UUID id,
            @RequestBody @Valid AllocatePropertyToBroker body) {
        if (!id.equals(body.portfolioId())) {
            return CompletableFuture.completedFuture(ResponseEntity.badRequest().build());
        }
        return commands.send(body).thenApply(v -> ResponseEntity.accepted().build());
    }

    @PostMapping("/{id}/valuations")
    @PreAuthorize("hasAuthority('SCOPE_portfolio.write')")
    public CompletableFuture<ResponseEntity<Void>> submitValuation(
            @PathVariable UUID id,
            @RequestBody @Valid SubmitValuation body) {
        if (!id.equals(body.portfolioId())) {
            return CompletableFuture.completedFuture(ResponseEntity.badRequest().build());
        }
        return commands.send(body).thenApply(v -> ResponseEntity.accepted().build());
    }

    @DeleteMapping("/{id}")
    @PreAuthorize("hasAuthority('SCOPE_portfolio.write')")
    public CompletableFuture<ResponseEntity<Void>> close(
            @PathVariable UUID id,
            @RequestBody(required = false) String reason) {
        return commands.send(new ClosePortfolio(id, reason)).thenApply(v -> ResponseEntity.noContent().build());
    }

    @GetMapping("/{id}/properties")
    @PreAuthorize("hasAuthority('SCOPE_portfolio.read')")
    public List<PropertyReadEntity> listProperties(@PathVariable UUID id) {
        return properties.findByPortfolioId(id);
    }
}
