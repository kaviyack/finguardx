package com.finguardx.model;

import jakarta.persistence.*;
import jakarta.validation.constraints.*;
import lombok.*;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.UUID;

/**
 * Transaction entity — SRS Feature 2: Transaction Data Ingestion
 * SRS §6.3: Stored in PostgreSQL with tenant_id isolation
 */
@Entity
@Table(name = "transactions",
       uniqueConstraints = @UniqueConstraint(columnNames = {"tenant_id","external_tx_id"}))
@Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
public class Transaction {

    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    private UUID id;

    @Column(name = "tenant_id", nullable = false)
    private UUID tenantId;

    @Column(name = "external_tx_id", nullable = false, length = 50)
    private String externalTxId;

    @Column(name = "customer_external_id", nullable = false, length = 50)
    private String customerExternalId;

    @Column(nullable = false, precision = 15, scale = 2)
    @DecimalMin(value = "0.01", message = "Amount must be greater than 0")
    private BigDecimal amount;

    @Column(name = "tx_type", nullable = false, length = 50)
    @NotBlank
    private String txType;

    @Column(name = "merchant_category", nullable = false, length = 50)
    @NotBlank
    private String merchantCategory;

    @Column(name = "location_flag", nullable = false, length = 50)
    @NotBlank
    private String locationFlag;

    @Column(name = "hour_of_day", nullable = false)
    @Min(0) @Max(23)
    private Integer hourOfDay;

    @Column(nullable = false, length = 20)
    @Builder.Default
    private String status = "PENDING";

    @Column(name = "is_duplicate", nullable = false)
    @Builder.Default
    private Boolean isDuplicate = false;

    @Column(name = "submitted_at", nullable = false, updatable = false)
    @Builder.Default
    private Instant submittedAt = Instant.now();
}
