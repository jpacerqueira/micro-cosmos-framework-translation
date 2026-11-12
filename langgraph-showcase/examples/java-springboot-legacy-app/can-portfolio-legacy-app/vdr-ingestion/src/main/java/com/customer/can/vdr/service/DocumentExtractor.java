package com.customer.can.vdr.service;

import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.Logger;
import org.apache.tika.Tika;
import org.springframework.stereotype.Component;

import java.io.InputStream;

@Component
public class DocumentExtractor {
    private static final Logger log = LogManager.getLogger(DocumentExtractor.class);
    private final Tika tika = new Tika();

    public String extractText(InputStream inputStream, String fileName) {
        try {
            String text = tika.parseToString(inputStream);
            log.info("action=extract_text fileName={} length={}", fileName, text.length());
            return text;
        } catch (Exception e) {
            log.warn("action=extract_text_failed fileName={} error={}", fileName, e.getMessage());
            return "";
        }
    }

    public String detectContentType(InputStream inputStream) {
        try {
            return tika.detect(inputStream);
        } catch (Exception e) {
            return "application/octet-stream";
        }
    }
}
