package com.customer.can.vdr;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * VDR (Virtual Data Room) Ingestion service.
 *
 * <p>Watches the {@code vdr-raw} blob container, extracts text and metadata
 * with Apache Tika/POI/PDFBox, normalises the result, writes the cleansed
 * artefact to {@code vdr-clean}, persists structured records to PostgreSQL,
 * and publishes a {@code uli.events.vdr.DocumentIngested} on NATS so
 * downstream services (search, workflow) can react.
 */
@SpringBootApplication
public class VdrIngestionApplication {
    public static void main(String[] args) {
        SpringApplication.run(VdrIngestionApplication.class, args);
    }
}
