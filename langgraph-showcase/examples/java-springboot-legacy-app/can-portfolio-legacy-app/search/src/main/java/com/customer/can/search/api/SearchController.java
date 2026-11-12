package com.customer.can.search.api;

import com.customer.can.search.service.SearchService;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/v1/search")
@Api(tags = "Search")
public class SearchController {
    private final SearchService searchService;

    public SearchController(SearchService searchService) {
        this.searchService = searchService;
    }

    @GetMapping("/portfolios")
    @ApiOperation("Search portfolios by name/description")
    public ResponseEntity<List<Map<String, Object>>> searchPortfolios(
            @RequestParam(required = false) String q,
            @RequestParam(required = false) String status) {
        return ResponseEntity.ok(searchService.searchPortfolios(q, status));
    }

    @GetMapping("/properties")
    @ApiOperation("Search properties")
    public ResponseEntity<List<Map<String, Object>>> searchProperties(
            @RequestParam(required = false) String q,
            @RequestParam(required = false) String portfolioId,
            @RequestParam(required = false) String propertyType,
            @RequestParam(required = false) String city) {
        return ResponseEntity.ok(searchService.searchProperties(q, portfolioId, propertyType, city));
    }

    @GetMapping("/documents")
    @ApiOperation("Search documents by filename or extracted text")
    public ResponseEntity<List<Map<String, Object>>> searchDocuments(
            @RequestParam(required = false) String q,
            @RequestParam(required = false) String portfolioId) {
        return ResponseEntity.ok(searchService.searchDocuments(q, portfolioId));
    }

    @GetMapping
    @ApiOperation("Global search across portfolios, properties and documents")
    public ResponseEntity<Map<String, Object>> globalSearch(@RequestParam String q) {
        return ResponseEntity.ok(searchService.globalSearch(q));
    }
}
