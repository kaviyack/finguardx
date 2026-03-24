package com.finguardx;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * FinGuardX — Spring Boot Backend
 * Multi-Tenant SaaS Platform for Transaction Risk Assessment
 *
 * SRS §6.2: Spring Boot (Java) backend exposing RESTful APIs
 * consumed by the React frontend and Python analytics engine.
 */
@SpringBootApplication
public class FinGuardXApplication {
    public static void main(String[] args) {
        SpringApplication.run(FinGuardXApplication.class, args);
    }
}
