package com.bankxyz.fraud.repository;

import com.bankxyz.fraud.entity.CustomerProfile;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

/**
 * Data access for CUST_PROFILE.
 */
@Repository
public interface CustomerProfileRepository extends JpaRepository<CustomerProfile, String> {
}
