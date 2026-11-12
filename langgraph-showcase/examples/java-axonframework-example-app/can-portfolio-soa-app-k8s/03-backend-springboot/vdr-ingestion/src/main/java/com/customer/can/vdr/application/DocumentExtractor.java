package com.customer.can.vdr.application;

import org.apache.tika.Tika;
import org.apache.tika.exception.TikaException;
import org.apache.tika.metadata.Metadata;
import org.apache.tika.parser.AutoDetectParser;
import org.apache.tika.parser.ParseContext;
import org.apache.tika.sax.BodyContentHandler;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.xml.sax.SAXException;

import java.io.IOException;
import java.io.InputStream;
import java.util.HashMap;
import java.util.Map;

/**
 * Wraps Apache Tika to extract text and metadata from arbitrary VDR documents
 * (PDF, DOCX, XLSX, images-with-OCR, etc). The handler is bounded to avoid
 * memory blow-ups on huge documents.
 */
@Service
public class DocumentExtractor {

    private static final Logger log = LoggerFactory.getLogger(DocumentExtractor.class);
    private static final int MAX_CHARS = 10_000_000;

    private final AutoDetectParser parser = new AutoDetectParser();
    private final Tika tika = new Tika();

    public ExtractedDocument extract(String filename, InputStream input) throws IOException {
        var handler = new BodyContentHandler(MAX_CHARS);
        var metadata = new Metadata();
        metadata.set(Metadata.CONTENT_LOCATION, filename);

        try {
            parser.parse(input, handler, metadata, new ParseContext());
        } catch (SAXException | TikaException e) {
            log.error("Tika parse failed for {}", filename, e);
            throw new IOException("extraction failed", e);
        }

        Map<String, String> meta = new HashMap<>();
        for (String name : metadata.names()) {
            meta.put(name, metadata.get(name));
        }
        String mime = metadata.get(Metadata.CONTENT_TYPE);
        return new ExtractedDocument(filename, mime, handler.toString(), meta);
    }

    public String detectMimeType(InputStream in) throws IOException {
        return tika.detect(in);
    }

    public record ExtractedDocument(String filename, String mimeType, String text, Map<String, String> metadata) {}
}
