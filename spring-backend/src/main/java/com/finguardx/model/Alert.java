package com.finguardx.model;

import jakarta.persistence.*;
import lombok.*;
import java.time.Instant;
import java.util.UUID;

/**
 * Alert entity — SRS Feature 6: High-Risk Transaction Alerts
 * Auto-generated when risk score >= 70. SRS §4.3
 */
@Entity
@Table(name = "alerts")
@Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
public class Alert {

    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    private UUID id;

    @Column(name = "tenant_id", nullable = false)
    private UUID tenantId;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "transaction_id", nullable = false)
    private Transaction transaction;

    /** critical | high */
    @Column(nullable = false, length = 20)
    private String severity;

    /** ACTIVE | ACKNOWLEDGED | ESCALATED | RESOLVED | DISMISSED */
    @Column(nullable = false, length = 20)
    @Builder.Default
    private String status = "ACTIVE";

    @Column(name = "acknowledged_by")
    private UUID acknowledgedBy;

    @Column(name = "acknowledged_at")
    private Instant acknowledgedAt;

    @Column(columnDefinition = "TEXT")
    private String notes;

    @Column(name = "created_at", updatable = false)
    @Builder.Default
    private Instant createdAt = Instant.now();
}
