package com.customer.can.vdr.api;

import com.customer.can.vdr.domain.Document;
import com.customer.can.vdr.service.DocumentService;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.Logger;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.util.List;

@RestController
@RequestMapping("/api/v1/documents")
@Api(tags = "Document Ingestion")
public class DocumentController {
    private static final Logger log = LogManager.getLogger(DocumentController.class);

    private final DocumentService documentService;

    public DocumentController(DocumentService documentService) {
        this.documentService = documentService;
    }

    @PostMapping("/upload")
    @ApiOperation("Upload and ingest a document")
    public ResponseEntity<Document> upload(
            @RequestParam("file") MultipartFile file,
            @RequestParam("portfolioId") String portfolioId,
            @RequestParam(value = "propertyId", required = false) String propertyId,
            @RequestParam(value = "uploadedBy", required = false, defaultValue = "system") String uploadedBy) {
        log.info("action=document_upload fileName={} portfolioId={}", file.getOriginalFilename(), portfolioId);
        Document doc = documentService.ingest(file, portfolioId, propertyId, uploadedBy);
        return ResponseEntity.status(201).body(doc);
    }

    @GetMapping
    @ApiOperation("List documents for a portfolio")
    public ResponseEntity<List<Document>> listByPortfolio(@RequestParam String portfolioId) {
        return ResponseEntity.ok(documentService.findByPortfolio(portfolioId));
    }

    @GetMapping("/{id}")
    @ApiOperation("Get document by ID")
    public ResponseEntity<Document> getDocument(@PathVariable String id) {
        return documentService.findById(id)
                .map(ResponseEntity::ok)
                .orElse(ResponseEntity.notFound().build());
    }
}
