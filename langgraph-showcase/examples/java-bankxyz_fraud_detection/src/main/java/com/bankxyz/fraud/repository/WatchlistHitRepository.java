package com.bankxyz.fraud.repository;

import com.bankxyz.fraud.entity.WatchlistHit;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

/**
 * Data access for WATCHLIST_HITS.
 */
@Repository
public interface WatchlistHitRepository extends JpaRepository<WatchlistHit, Long> {
}
