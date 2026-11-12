package com.customer.can.bff;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * WebApp BFF (Backend-for-Frontend) - the only service the WebApp UI talks to.
 *
 * <p>It exposes a GraphQL endpoint plus a small REST surface, fans out to the
 * downstream microservices via the Axon command/query gateway (in-cluster) or
 * via WebClient over Istio mTLS, and aggregates the results. Per the SAD it
 * sits behind the Istio ingress gateway which validates Azure AD JWTs.
 */
@SpringBootApplication
public class WebAppBffApplication {
    public static void main(String[] args) {
        SpringApplication.run(WebAppBffApplication.class, args);
    }
}
