package com.bankxyz.fraud.repository;

import com.bankxyz.fraud.entity.WatchlistEntry;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

/**
 * Data access for watchlist screening queries.
 */
@Repository
public interface WatchlistRepository extends JpaRepository<WatchlistEntry, Long> {

    /**
     * Screen 1: OFAC sanctions list check.
     */
    @Query("SELECT COUNT(w) FROM WatchlistEntry w " +
           "WHERE w.listType = 'OFAC' " +
           "AND w.listStatus = 'ACTIVE' " +
           "AND UPPER(w.matchName) LIKE UPPER(:name)")
    long countOfacHits(@Param("name") String name);

    /**
     * Screen 2: PEP list check.
     */
    @Query("SELECT COUNT(w) FROM WatchlistEntry w " +
           "WHERE w.listType = 'PEP' " +
           "AND w.listStatus = 'ACTIVE' " +
           "AND UPPER(w.matchName) LIKE UPPER(:name)")
    long countPepHits(@Param("name") String name);

    /**
     * Screen 3: Internal BankXYZ watchlist check.
     * Screens by account number OR name.
     */
    @Query("SELECT COUNT(w) FROM WatchlistEntry w " +
           "WHERE w.listType = 'INTERNAL' " +
           "AND w.listStatus = 'ACTIVE' " +
           "AND (w.matchAcct = :acctNo OR UPPER(w.matchName) LIKE UPPER(:name))")
    long countInternalHits(@Param("acctNo") String acctNo, @Param("name") String name);
}
