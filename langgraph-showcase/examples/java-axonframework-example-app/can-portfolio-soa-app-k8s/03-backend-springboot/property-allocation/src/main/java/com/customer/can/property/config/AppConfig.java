package com.customer.can.property.config;

import com.customer.can.property.api.CorrelationIdFilter;
import io.nats.client.Connection;
import io.nats.client.Nats;
import io.nats.client.Options;
import jakarta.servlet.FilterChain;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.config.annotation.method.configuration.EnableMethodSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationConverter;
import org.springframework.security.oauth2.server.resource.authentication.JwtGrantedAuthoritiesConverter;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.web.cors.CorsConfiguration;
import org.springframework.web.cors.CorsConfigurationSource;
import org.springframework.web.cors.UrlBasedCorsConfigurationSource;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.time.Duration;
import java.util.List;

/**
 * Application configuration: OAuth2 resource server, NATS connection,
 * correlation-id filter wiring.
 */
@Configuration
@EnableWebSecurity
@EnableMethodSecurity
public class AppConfig {

    /** Local-dev profile: permit all and inject a superuser so @PreAuthorize passes. */
    @Bean
    @org.springframework.context.annotation.Profile("local")
    public SecurityFilterChain localSecurity(HttpSecurity http) throws Exception {
        http.csrf(c -> c.disable())
            .authorizeHttpRequests(a -> a.anyRequest().permitAll())
            .addFilterBefore(new OncePerRequestFilter() {
                @Override
                protected void doFilterInternal(HttpServletRequest req, HttpServletResponse resp, FilterChain chain)
                        throws IOException, jakarta.servlet.ServletException {
                    if (SecurityContextHolder.getContext().getAuthentication() == null) {
                        SecurityContextHolder.getContext().setAuthentication(
                            new UsernamePasswordAuthenticationToken("local-dev", null, List.of(
                                new SimpleGrantedAuthority("SCOPE_portfolio.read"),
                                new SimpleGrantedAuthority("SCOPE_portfolio.write"),
                                new SimpleGrantedAuthority("SCOPE_actuator.read")
                            )));
                    }
                    chain.doFilter(req, resp);
                }
            }, org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter.class);
        return http.build();
    }

    /**
     * OAuth2 resource server validates JWTs issued by Azure AD. Method-level
     * {@code @PreAuthorize} controls fine-grained access via SCOPE_* authorities.
     */
    @Bean
    @org.springframework.context.annotation.Profile("!local")
    public SecurityFilterChain security(HttpSecurity http, CorrelationIdFilter cidFilter) throws Exception {
        var jwtConv = new JwtGrantedAuthoritiesConverter();
        jwtConv.setAuthorityPrefix("SCOPE_");
        jwtConv.setAuthoritiesClaimName("scp"); // Azure AD v2 puts scopes in 'scp'
        var authConv = new JwtAuthenticationConverter();
        authConv.setJwtGrantedAuthoritiesConverter(jwtConv);

        http
            .csrf(c -> c.disable()) // stateless API
            .cors(c -> c.configurationSource(corsSource()))
            .sessionManagement(s -> s.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
            .authorizeHttpRequests(a -> a
                .requestMatchers("/actuator/health/**", "/actuator/info").permitAll()
                .requestMatchers("/actuator/**").hasAuthority("SCOPE_actuator.read")
                .anyRequest().authenticated())
            .oauth2ResourceServer(o -> o.jwt(j -> j.jwtAuthenticationConverter(authConv)))
            .addFilterBefore(cidFilter, org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter.class);
        return http.build();
    }

    private CorsConfigurationSource corsSource() {
        var cfg = new CorsConfiguration();
        cfg.setAllowedOriginPatterns(List.of("https://*.example.com"));
        cfg.setAllowedMethods(List.of("GET","POST","PUT","DELETE","OPTIONS"));
        cfg.setAllowedHeaders(List.of("*"));
        cfg.setExposedHeaders(List.of("X-Correlation-Id"));
        cfg.setAllowCredentials(true);
        var src = new UrlBasedCorsConfigurationSource();
        src.registerCorsConfiguration("/api/**", cfg);
        return src;
    }

    /**
     * Single shared NATS connection. JetStream contexts are derived from it.
     * Reconnect policy: keep retrying so transient NATS unavailability does
     * not crash the pod - readiness probe will surface real outages.
     */
    @Bean(destroyMethod = "close")
    public Connection natsConnection(@Value("${nats.url}") String url,
                                     @Value("${nats.user:}") String user,
                                     @Value("${nats.password:}") String password) throws Exception {
        Options.Builder b = new Options.Builder()
                .server(url)
                .connectionName("property-allocation")
                .maxReconnects(-1)
                .reconnectWait(Duration.ofSeconds(2))
                .pingInterval(Duration.ofSeconds(20));
        if (!user.isBlank()) {
            b.userInfo(user.toCharArray(), password.toCharArray());
        }
        return Nats.connect(b.build());
    }
}
