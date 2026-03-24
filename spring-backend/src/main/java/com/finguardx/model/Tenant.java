package com.finguardx.model;

import jakarta.persistence.*;
import lombok.*;
import java.time.Instant;
import java.util.UUID;

/**
 * Tenant entity — SRS §2.3: Multi-tenant support (min 5 organisations)
 */
@Entity
@Table(name = "tenants")
@Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
public class Tenant {

    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    private UUID id;

    @Column(nullable = false, unique = true, length = 100)
    private String name;

    @Column(nullable = false, length = 50)
    private String type;

    @Column(nullable = false, unique = true, length = 10)
    private String code;

    @Column(name = "is_active", nullable = false)
    @Builder.Default
    private Boolean isActive = true;

    @Column(name = "created_at", updatable = false)
    @Builder.Default
    private Instant createdAt = Instant.now();
}
