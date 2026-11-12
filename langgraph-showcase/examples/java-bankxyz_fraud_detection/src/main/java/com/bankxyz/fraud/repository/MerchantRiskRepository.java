package com.bankxyz.fraud.repository;

import com.bankxyz.fraud.entity.MerchantRisk;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

/**
 * Data access for MERCHANT_RISK.
 */
@Repository
public interface MerchantRiskRepository extends JpaRepository<MerchantRisk, String> {
}
