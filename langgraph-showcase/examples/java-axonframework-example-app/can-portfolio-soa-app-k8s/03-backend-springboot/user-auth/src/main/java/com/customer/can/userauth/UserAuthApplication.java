package com.customer.can.userauth;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * User Authentication / User Management service.
 *
 * <p>Per the SAD: internal users are synchronised from Customer-A AD into
 * Azure AD; external users are invited via Azure AD B2B (guest accounts).
 * This service wraps the Microsoft Graph API to handle invitations,
 * directory queries, role assignments, and exposes a thin REST API to
 * the BFF. It does NOT issue tokens - that is delegated to Azure AD.
 */
@SpringBootApplication
public class UserAuthApplication {
    public static void main(String[] args) {
        SpringApplication.run(UserAuthApplication.class, args);
    }
}
