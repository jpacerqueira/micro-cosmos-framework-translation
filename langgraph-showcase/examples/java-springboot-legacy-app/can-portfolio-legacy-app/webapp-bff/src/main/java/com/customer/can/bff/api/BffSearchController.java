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
import org.springframework.web.util.UriComponentsBuilder;

import javax.servlet.http.HttpServletRequest;

@RestController
@RequestMapping("/api/v1/search")
@Api(tags = "Search BFF")
public class BffSearchController {
    private static final Logger log = LogManager.getLogger(BffSearchController.class);

    private final RestTemplate restTemplate;

    @Value("${services.search.url:http://localhost:8005}")
    private String searchUrl;

    public BffSearchController(RestTemplate restTemplate) {
        this.restTemplate = restTemplate;
    }

    private HttpHeaders forwardHeaders(HttpServletRequest request) {
        HttpHeaders headers = new HttpHeaders();
        String correlationId = ThreadContext.get("correlationId");
        if (correlationId != null) headers.set("X-Correlation-Id", correlationId);
        return headers;
    }

    @GetMapping
    @ApiOperation("Global search")
    public ResponseEntity<Object> globalSearch(@RequestParam String q, HttpServletRequest request) {
        log.info("action=bff_global_search q={} correlationId={}", q, ThreadContext.get("correlationId"));
        String url = UriComponentsBuilder.fromHttpUrl(searchUrl + "/api/v1/search")
                .queryParam("q", q).toUriString();
        return restTemplate.exchange(url, HttpMethod.GET, new HttpEntity<>(forwardHeaders(request)), Object.class);
    }

    @GetMapping("/portfolios")
    @ApiOperation("Search portfolios")
    public ResponseEntity<Object> searchPortfolios(
            @RequestParam(required = false) String q,
            @RequestParam(required = false) String status,
            HttpServletRequest request) {
        UriComponentsBuilder builder = UriComponentsBuilder.fromHttpUrl(searchUrl + "/api/v1/search/portfolios");
        if (q != null) builder.queryParam("q", q);
        if (status != null) builder.queryParam("status", status);
        return restTemplate.exchange(builder.toUriString(), HttpMethod.GET, new HttpEntity<>(forwardHeaders(request)), Object.class);
    }

    @GetMapping("/properties")
    @ApiOperation("Search properties")
    public ResponseEntity<Object> searchProperties(
            @RequestParam(required = false) String q,
            @RequestParam(required = false) String portfolioId,
            @RequestParam(required = false) String city,
            HttpServletRequest request) {
        UriComponentsBuilder builder = UriComponentsBuilder.fromHttpUrl(searchUrl + "/api/v1/search/properties");
        if (q != null) builder.queryParam("q", q);
        if (portfolioId != null) builder.queryParam("portfolioId", portfolioId);
        if (city != null) builder.queryParam("city", city);
        return restTemplate.exchange(builder.toUriString(), HttpMethod.GET, new HttpEntity<>(forwardHeaders(request)), Object.class);
    }
}
