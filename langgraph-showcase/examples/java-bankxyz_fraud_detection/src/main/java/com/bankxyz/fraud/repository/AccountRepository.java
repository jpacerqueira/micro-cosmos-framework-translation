package com.bankxyz.fraud.repository;

import com.bankxyz.fraud.entity.Account;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

/**
 * Data access for ACCOUNT_MASTER.
 */
@Repository
public interface AccountRepository extends JpaRepository<Account, String> {
}
