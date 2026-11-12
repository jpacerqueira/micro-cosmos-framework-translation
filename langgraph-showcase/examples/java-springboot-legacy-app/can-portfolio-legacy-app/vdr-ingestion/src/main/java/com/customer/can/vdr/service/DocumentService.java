package com.customer.can.vdr.service;

import com.customer.can.vdr.domain.Document;
import com.customer.can.vdr.messaging.DocumentEventPublisher;
import com.customer.can.vdr.repository.DocumentRepository;
import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.Logger;
import org.apache.logging.log4j.ThreadContext;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.multipart.MultipartFile;

import java.util.List;
import java.util.Optional;

@Service
public class DocumentService {
    private static final Logger log = LogManager.getLogger(DocumentService.class);

    private final DocumentRepository documentRepository;
    private final DocumentExtractor documentExtractor;
    private final DocumentEventPublisher eventPublisher;

    public DocumentService(DocumentRepository documentRepository,
                           DocumentExtractor documentExtractor,
                           DocumentEventPublisher eventPublisher) {
        this.documentRepository = documentRepository;
        this.documentExtractor = documentExtractor;
        this.eventPublisher = eventPublisher;
    }

    @Transactional
    public Document ingest(MultipartFile file, String portfolioId, String propertyId, String uploadedBy) {
        Document doc = new Document();
        doc.setPortfolioId(portfolioId);
        doc.setPropertyId(propertyId);
        doc.setFileName(file.getOriginalFilename());
        doc.setContentType(file.getContentType());
        doc.setFileSize(file.getSize());
        doc.setUploadedBy(uploadedBy);

        try {
            String extractedText = documentExtractor.extractText(file.getInputStream(), file.getOriginalFilename());
            doc.setExtractedText(extractedText);
            doc.setStatus("PROCESSED");
        } catch (Exception e) {
            log.warn("action=text_extraction_failed fileName={}", file.getOriginalFilename());
            doc.setStatus("EXTRACTION_FAILED");
        }

        Document saved = documentRepository.save(doc);
        eventPublisher.publishDocumentEvent("DOCUMENT_INGESTED", saved.getId(), portfolioId);
        log.info("action=document_ingested docId={} portfolioId={} correlationId={}",
                saved.getId(), portfolioId, ThreadContext.get("correlationId"));
        return saved;
    }

    public List<Document> findByPortfolio(String portfolioId) {
        return documentRepository.findByPortfolioId(portfolioId);
    }

    public Optional<Document> findById(String id) {
        return documentRepository.findById(id);
    }
}
