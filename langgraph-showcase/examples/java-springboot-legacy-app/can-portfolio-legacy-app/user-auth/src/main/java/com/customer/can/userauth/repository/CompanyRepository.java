package com.customer.can.userauth.repository;

import com.customer.can.userauth.domain.Company;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;
import java.util.List;

@Repository
public interface CompanyRepository extends JpaRepository<Company, String> {
    List<Company> findByCompanyType(String companyType);
}
