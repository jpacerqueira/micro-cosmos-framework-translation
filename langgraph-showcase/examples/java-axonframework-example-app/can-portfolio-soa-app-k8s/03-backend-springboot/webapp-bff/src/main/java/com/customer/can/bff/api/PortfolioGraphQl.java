package com.customer.can.bff.api;

import com.customer.can.common.commands.PortfolioCommands.AllocatePropertyToBroker;
import com.customer.can.common.commands.PortfolioCommands.ClosePortfolio;
import com.customer.can.common.commands.PortfolioCommands.CreatePortfolio;

import org.axonframework.commandhandling.gateway.CommandGateway;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.graphql.data.method.annotation.Argument;
import org.springframework.graphql.data.method.annotation.MutationMapping;
import org.springframework.graphql.data.method.annotation.QueryMapping;
import org.springframework.graphql.data.method.annotation.SchemaMapping;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.stereotype.Controller;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;

import java.time.LocalDate;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;

/**
 * GraphQL resolvers. Reads are served from the property-allocation read-side
 * over HTTP (in-cluster, mTLS via Istio). Writes go through Axon's
 * {@code CommandGateway} so the WebApp BFF participates as an Axon client and
 * does not need direct database access.
 */
@Controller
public class PortfolioGraphQl {

    private final CommandGateway commands;
    private final WebClient propertyService;

    public PortfolioGraphQl(CommandGateway commands, WebClient.Builder builder,
            @Value("${services.property-allocation}") String propertyAllocationUrl) {
        this.commands = commands;
        this.propertyService = builder.baseUrl(propertyAllocationUrl).build();
    }

    @QueryMapping
    @PreAuthorize("hasAuthority('SCOPE_portfolio.read')")
    public Mono<Map<String, Object>> portfolio(@Argument UUID id) {
        return propertyService.get()
                .uri("/api/v1/portfolios/{id}", id)
                .retrieve()
                .bodyToMono(new org.springframework.core.ParameterizedTypeReference<Map<String, Object>>(){});
    }

    @QueryMapping
    @PreAuthorize("hasAuthority('SCOPE_portfolio.read')")
    public Mono<List<Map<String, Object>>> portfolios(@Argument String status) {
        return propertyService.get()
                .uri(uri -> uri.path("/api/v1/portfolios").queryParamIfPresent("status",
                    java.util.Optional.ofNullable(status)).build())
                .retrieve()
                .bodyToMono(new org.springframework.core.ParameterizedTypeReference<List<Map<String, Object>>>(){})
                .defaultIfEmpty(Collections.emptyList());
    }

    @SchemaMapping(typeName = "Portfolio", field = "properties")
    public Mono<List<Map<String, Object>>> properties(Map<String, Object> portfolio) {
        // Defensive: portfolio is a generic Map deserialized from the upstream REST
        // response, not a typed DTO — a partial/error body or a future field rename
        // could omit portfolioId. Resolve to "no properties known" rather than an
        // uncaught NPE crashing the whole GraphQL query.
        Object rawId = portfolio.get("portfolioId");
        if (rawId == null) {
            return Mono.just(Collections.emptyList());
        }
        UUID id = UUID.fromString(rawId.toString());
        return propertyService.get()
                .uri("/api/v1/portfolios/{id}/properties", id)
                .retrieve()
                .bodyToMono(new org.springframework.core.ParameterizedTypeReference<List<Map<String, Object>>>(){})
                .defaultIfEmpty(Collections.emptyList());
    }

    @MutationMapping
    @PreAuthorize("hasAuthority('SCOPE_portfolio.write')")
    public CompletableFuture<UUID> createPortfolio(@Argument Map<String, Object> input) {
        UUID id = UUID.randomUUID();
        var cmd = new CreatePortfolio(
                id,
                (String) input.get("name"),
                (String) input.get("description"),
                (LocalDate) input.get("cutOffDate"),
                (LocalDate) input.get("finalBidDate"),
                (String) input.get("projectPhase"));
        return commands.<Object>send(cmd).thenApply(v -> id);
    }

    @MutationMapping
    @PreAuthorize("hasAuthority('SCOPE_portfolio.write')")
    public CompletableFuture<Boolean> allocateProperty(@Argument Map<String, Object> input) {
        var cmd = new AllocatePropertyToBroker(
                (UUID) input.get("portfolioId"),
                (UUID) input.get("propertyId"),
                (UUID) input.get("brokerCompanyId"),
                (LocalDate) input.get("allocationDate"),
                (String) input.get("allocationStatus"));
        return commands.send(cmd).thenApply(v -> true);
    }

    @MutationMapping
    @PreAuthorize("hasAuthority('SCOPE_portfolio.write')")
    public CompletableFuture<Boolean> closePortfolio(@Argument UUID portfolioId, @Argument String reason) {
        return commands.send(new ClosePortfolio(portfolioId, reason)).thenApply(v -> true);
    }
}
