package com.bankxyz.fraud.repository;

import com.bankxyz.fraud.entity.Transaction;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.time.LocalDateTime;
import java.util.List;

/**
 * Data access for transaction processing and velocity queries.
 */
@Repository
public interface TransactionRepository extends JpaRepository<Transaction, String> {

    /**
     * Fetch pending transactions for batch processing (TXN_STATUS = 'P').
     */
    List<Transaction> findByTxnStatusOrderByTxnTs(String txnStatus, Pageable pageable);

    /**
     * Count transactions in last 24 hours for velocity scoring.
     * Used for both batch and real-time scoring paths.
     */
    @Query("SELECT COUNT(t) FROM Transaction t " +
           "WHERE t.acctNo = :acctNo " +
           "AND t.txnStatus IN ('P','S') " +
           "AND t.txnTs > :since")
    long countVelocity(@Param("acctNo") String acctNo,
                       @Param("since") LocalDateTime since);

    @Query("SELECT COALESCE(SUM(t.txnAmount), 0) FROM Transaction t " +
           "WHERE t.acctNo = :acctNo " +
           "AND t.txnStatus IN ('P','S') " +
           "AND t.txnTs > :since")
    java.math.BigDecimal sumVelocityAmount(@Param("acctNo") String acctNo,
                                           @Param("since") LocalDateTime since);

    /**
     * Mark a transaction as processed: set TXN_STATUS = 'S' and stamp PROC_TS.
     */
    @Modifying
    @Query("UPDATE Transaction t SET t.txnStatus = 'S', t.procTs = :procTs WHERE t.txnId = :txnId")
    void stampProcessed(@Param("txnId") String txnId, @Param("procTs") LocalDateTime procTs);
}
