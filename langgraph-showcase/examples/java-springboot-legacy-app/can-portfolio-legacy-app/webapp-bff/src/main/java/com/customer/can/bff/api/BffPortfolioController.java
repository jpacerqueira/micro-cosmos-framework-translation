package com.customer.can.bff.api;

import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.Logger;
import org.apache.logging.log4j.ThreadContext;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.client.RestTemplate;

import javax.servlet.http.HttpServletRequest;
import java.util.Map;

@RestController
@RequestMapping("/api/v1/portfolios")
@Api(tags = "Portfolio BFF")
public class BffPortfolioController {
    private static final Logger log = LogManager.getLogger(BffPortfolioController.class);

    private final RestTemplate restTemplate;

    @Value("${services.property-allocation.url:http://localhost:8002}")
    private String propertyAllocationUrl;

    @Value("${services.user-auth.url:http://localhost:8001}")
    private String userAuthUrl;

    public BffPortfolioController(RestTemplate restTemplate) {
        this.restTemplate = restTemplate;
    }

    private HttpHeaders forwardHeaders(HttpServletRequest request) {
        HttpHeaders headers = new HttpHeaders();
        String correlationId = ThreadContext.get("correlationId");
        if (correlationId != null) headers.set("X-Correlation-Id", correlationId);
        String auth = request.getHeader("Authorization");
        if (auth != null) headers.set("Authorization", auth);
        return headers;
    }

    @GetMapping
    @ApiOperation("List all portfolios")
    public ResponseEntity<Object> listPortfolios(HttpServletRequest request) {
        log.info("action=bff_list_portfolios correlationId={}", ThreadContext.get("correlationId"));
        String url = propertyAllocationUrl + "/api/v1/portfolios";
        return restTemplate.exchange(url, HttpMethod.GET, new HttpEntity<>(forwardHeaders(request)), Object.class);
    }

    @GetMapping("/{id}")
    @ApiOperation("Get portfolio by ID")
    public ResponseEntity<Object> getPortfolio(@PathVariable String id, HttpServletRequest request) {
        String url = propertyAllocationUrl + "/api/v1/portfolios/" + id;
        return restTemplate.exchange(url, HttpMethod.GET, new HttpEntity<>(forwardHeaders(request)), Object.class);
    }

    @PostMapping
    @ApiOperation("Create portfolio")
    public ResponseEntity<Object> createPortfolio(@RequestBody Object body, HttpServletRequest request) {
        String url = propertyAllocationUrl + "/api/v1/portfolios";
        return restTemplate.exchange(url, HttpMethod.POST, new HttpEntity<>(body, forwardHeaders(request)), Object.class);
    }

    @PutMapping("/{id}/close")
    @ApiOperation("Close portfolio")
    public ResponseEntity<Object> closePortfolio(@PathVariable String id, HttpServletRequest request) {
        String url = propertyAllocationUrl + "/api/v1/portfolios/" + id + "/close";
        return restTemplate.exchange(url, HttpMethod.PUT, new HttpEntity<>(forwardHeaders(request)), Object.class);
    }

    @GetMapping("/{portfolioId}/properties")
    @ApiOperation("List properties in portfolio")
    public ResponseEntity<Object> listProperties(@PathVariable String portfolioId, HttpServletRequest request) {
        String url = propertyAllocationUrl + "/api/v1/portfolios/" + portfolioId + "/properties";
        return restTemplate.exchange(url, HttpMethod.GET, new HttpEntity<>(forwardHeaders(request)), Object.class);
    }

    @PostMapping("/{portfolioId}/properties")
    @ApiOperation("Add property to portfolio")
    public ResponseEntity<Object> addProperty(@PathVariable String portfolioId,
                                               @RequestBody Object body,
                                               HttpServletRequest request) {
        String url = propertyAllocationUrl + "/api/v1/portfolios/" + portfolioId + "/properties";
        return restTemplate.exchange(url, HttpMethod.POST, new HttpEntity<>(body, forwardHeaders(request)), Object.class);
    }

    @PostMapping("/auth/login")
    @ApiOperation("User login")
    public ResponseEntity<Object> login(@RequestBody Object credentials) {
        String url = userAuthUrl + "/api/v1/auth/login";
        return restTemplate.postForEntity(url, credentials, Object.class);
    }

    @PostMapping("/auth/refresh")
    @ApiOperation("Refresh token")
    public ResponseEntity<Object> refresh(@RequestBody Object body) {
        String url = userAuthUrl + "/api/v1/auth/refresh";
        return restTemplate.postForEntity(url, body, Object.class);
    }
}
