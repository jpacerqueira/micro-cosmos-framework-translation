package com.customer.can.bff.config;

import graphql.scalars.ExtendedScalars;
import jakarta.servlet.FilterChain;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.slf4j.MDC;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.graphql.execution.RuntimeWiringConfigurer;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.method.configuration.EnableMethodSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationConverter;
import org.springframework.security.oauth2.server.resource.authentication.JwtGrantedAuthoritiesConverter;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.web.filter.OncePerRequestFilter;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.reactive.function.client.ExchangeFilterFunction;
import org.springframework.web.servlet.config.annotation.ViewControllerRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

import java.io.IOException;
import java.util.List;
import java.util.UUID;

import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;

/**
 * Cross-cutting BFF config: JWT validation, correlation-id propagation onto
 * outbound WebClient calls, stateless session, exposing /actuator health
 * unauthenticated for kubelet probes.
 */
@Configuration
@EnableWebSecurity
@EnableMethodSecurity
public class BffConfig {

    public static final String CID_HEADER = "X-Correlation-Id";
    public static final String CID_MDC    = "correlationId";

    /** Redirect / → /graphiql so opening the app in a browser lands on the playground. */
    @Bean
    public WebMvcConfigurer rootRedirect() {
        return new WebMvcConfigurer() {
            @Override
            public void addViewControllers(ViewControllerRegistry registry) {
                registry.addRedirectViewController("/", "/graphiql");
            }
        };
    }

    /** Registers UUID, Date, and BigDecimal scalar types for the GraphQL schema. */
    @Bean
    public RuntimeWiringConfigurer graphQlScalars() {
        return wiringBuilder -> wiringBuilder
                .scalar(ExtendedScalars.UUID)
                .scalar(ExtendedScalars.Date)
                .scalar(ExtendedScalars.GraphQLBigDecimal);
    }

    /** Local-dev profile: permit all and inject a superuser so @PreAuthorize passes. */
    @Bean
    @org.springframework.context.annotation.Profile("local")
    public SecurityFilterChain localSecurity(HttpSecurity http) throws Exception {
        http.csrf(c -> c.disable())
            .authorizeHttpRequests(a -> a.anyRequest().permitAll())
            .addFilterBefore(localSuperuserFilter(), org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter.class);
        return http.build();
    }

    private OncePerRequestFilter localSuperuserFilter() {
        return new OncePerRequestFilter() {
            @Override
            protected void doFilterInternal(HttpServletRequest req, HttpServletResponse resp, FilterChain chain)
                    throws IOException, jakarta.servlet.ServletException {
                if (SecurityContextHolder.getContext().getAuthentication() == null) {
                    var auth = new UsernamePasswordAuthenticationToken("local-dev", null, List.of(
                        new SimpleGrantedAuthority("SCOPE_portfolio.read"),
                        new SimpleGrantedAuthority("SCOPE_portfolio.write"),
                        new SimpleGrantedAuthority("SCOPE_actuator.read")
                    ));
                    SecurityContextHolder.getContext().setAuthentication(auth);
                }
                chain.doFilter(req, resp);
            }
        };
    }

    @Bean
    @org.springframework.context.annotation.Profile("!local")
    public SecurityFilterChain security(HttpSecurity http) throws Exception {
        var conv = new JwtGrantedAuthoritiesConverter();
        conv.setAuthorityPrefix("SCOPE_");
        conv.setAuthoritiesClaimName("scp");
        var auth = new JwtAuthenticationConverter();
        auth.setJwtGrantedAuthoritiesConverter(conv);

        http.csrf(c -> c.disable())
            .sessionManagement(s -> s.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
            .authorizeHttpRequests(a -> a
                .requestMatchers("/actuator/health/**", "/actuator/info").permitAll()
                // GraphiQL is a dev tool that discloses the full schema via introspection —
                // it must require the same JWT as any other endpoint outside "local"; only
                // the localSecurity() profile (permitAll entirely) is meant to expose it freely.
                .anyRequest().authenticated())
            .oauth2ResourceServer(o -> o.jwt(j -> j.jwtAuthenticationConverter(auth)));
        return http.build();
    }

    @Bean
    @Order(Ordered.HIGHEST_PRECEDENCE)
    public OncePerRequestFilter correlationIdFilter() {
        return new OncePerRequestFilter() {
            @Override
            protected void doFilterInternal(HttpServletRequest req, HttpServletResponse resp,
                                            FilterChain chain) throws java.io.IOException, jakarta.servlet.ServletException {
                String cid = req.getHeader(CID_HEADER);
                if (cid == null || cid.isBlank()) cid = UUID.randomUUID().toString();
                MDC.put(CID_MDC, cid);
                resp.setHeader(CID_HEADER, cid);
                try { chain.doFilter(req, resp); } finally { MDC.remove(CID_MDC); }
            }
        };
    }

    /**
     * WebClient.Builder that auto-propagates the inbound correlation id and
     * the JWT bearer token onto every outbound call. This is what makes the
     * BFF "trustworthy" to downstream services.
     */
    @Bean
    public WebClient.Builder webClientBuilder() {
        return WebClient.builder()
                .filter(propagateCorrelationId())
                .filter(propagateBearer());
    }

    private ExchangeFilterFunction propagateCorrelationId() {
        return (req, next) -> {
            String cid = MDC.get(CID_MDC);
            if (cid == null) return next.exchange(req);
            return next.exchange(org.springframework.web.reactive.function.client.ClientRequest
                    .from(req).header(CID_HEADER, cid).build());
        };
    }

    /**
     * Forwards the inbound request's own Authorization header onto the outbound
     * call. This was previously a no-op relying on "Istio mTLS + AuthZ" for the
     * internal hop — but mTLS + AuthorizationPolicy only establish service
     * *identity*, not a per-request JWT, and property-allocation's own
     * security() bean requires a valid JWT via oauth2ResourceServer() for
     * every non-local request. Without this, every outbound call from the BFF
     * was rejected with 401 outside the "local" profile.
     */
    private ExchangeFilterFunction propagateBearer() {
        return (req, next) -> {
            String authHeader = inboundAuthorizationHeader();
            if (authHeader == null || authHeader.isBlank()) {
                return next.exchange(req);
            }
            return next.exchange(org.springframework.web.reactive.function.client.ClientRequest
                    .from(req).header(org.springframework.http.HttpHeaders.AUTHORIZATION, authHeader).build());
        };
    }

    private String inboundAuthorizationHeader() {
        var attrs = org.springframework.web.context.request.RequestContextHolder.getRequestAttributes();
        if (attrs instanceof org.springframework.web.context.request.ServletRequestAttributes servletAttrs) {
            return servletAttrs.getRequest().getHeader(org.springframework.http.HttpHeaders.AUTHORIZATION);
        }
        return null;
    }
}
