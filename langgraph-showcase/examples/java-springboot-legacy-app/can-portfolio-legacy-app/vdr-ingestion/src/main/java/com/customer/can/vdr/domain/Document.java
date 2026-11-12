package com.customer.can.vdr.domain;

import javax.persistence.*;
import java.util.Date;

@Entity
@Table(name = "DOCUMENT")
public class Document {
    @Id
    @Column(name = "ID", length = 36)
    private String id;

    @Column(name = "PORTFOLIO_ID", length = 36)
    private String portfolioId;

    @Column(name = "PROPERTY_ID", length = 36)
    private String propertyId;

    @Column(name = "FILE_NAME", nullable = false, length = 500)
    private String fileName;

    @Column(name = "CONTENT_TYPE", length = 100)
    private String contentType;

    @Column(name = "FILE_SIZE")
    private Long fileSize;

    @Column(name = "EXTRACTED_TEXT", columnDefinition = "CLOB")
    private String extractedText;

    @Column(name = "UPLOADED_BY", length = 36)
    private String uploadedBy;

    @Column(name = "UPLOAD_DATE")
    @Temporal(TemporalType.TIMESTAMP)
    private Date uploadDate;

    @Column(name = "STATUS", length = 50)
    private String status = "PROCESSED";

    @PrePersist
    public void prePersist() {
        if (this.id == null) {
            this.id = java.util.UUID.randomUUID().toString();
        }
        this.uploadDate = new Date();
    }

    public String getId() { return id; }
    public void setId(String id) { this.id = id; }
    public String getPortfolioId() { return portfolioId; }
    public void setPortfolioId(String portfolioId) { this.portfolioId = portfolioId; }
    public String getPropertyId() { return propertyId; }
    public void setPropertyId(String propertyId) { this.propertyId = propertyId; }
    public String getFileName() { return fileName; }
    public void setFileName(String fileName) { this.fileName = fileName; }
    public String getContentType() { return contentType; }
    public void setContentType(String contentType) { this.contentType = contentType; }
    public Long getFileSize() { return fileSize; }
    public void setFileSize(Long fileSize) { this.fileSize = fileSize; }
    public String getExtractedText() { return extractedText; }
    public void setExtractedText(String extractedText) { this.extractedText = extractedText; }
    public String getUploadedBy() { return uploadedBy; }
    public void setUploadedBy(String uploadedBy) { this.uploadedBy = uploadedBy; }
    public Date getUploadDate() { return uploadDate; }
    public void setUploadDate(Date uploadDate) { this.uploadDate = uploadDate; }
    public String getStatus() { return status; }
    public void setStatus(String status) { this.status = status; }
}
