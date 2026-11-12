package com.customer.can.vdr.repository;

import com.customer.can.vdr.domain.Document;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;
import java.util.List;

@Repository
public interface DocumentRepository extends JpaRepository<Document, String> {
    List<Document> findByPortfolioId(String portfolioId);
    List<Document> findByPropertyId(String propertyId);
}
