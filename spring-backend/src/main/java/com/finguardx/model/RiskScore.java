package com.finguardx.model;

import jakarta.persistence.*;
import lombok.*;
import java.time.Instant;
import java.util.UUID;

/**
 * RiskScore entity — SRS Feature 3: Transaction Risk Scoring Engine
 * Score range: 0–100. Levels: Low (0–39), Medium (40–69), High (70–100)
 */
@Entity
@Table(name = "risk_scores")
@Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
public class RiskScore {

    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    private UUID id;

    @OneToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "transaction_id", nullable = false, unique = true)
    private Transaction transaction;

    @Column(name = "tenant_id", nullable = false)
    private UUID tenantId;

    /** 0–100 risk score */
    @Column(nullable = false)
    private Integer score;

    /** Low | Medium | High */
    @Column(name = "risk_level", nullable = false, length = 10)
    private String riskLevel;

    @Column(name = "model_version", length = 20)
    @Builder.Default
    private String modelVersion = "v1.0";

    @Column(name = "factor_amount")
    private Integer factorAmount;

    @Column(name = "factor_category")
    private Integer factorCategory;

    @Column(name = "factor_location")
    private Integer factorLocation;

    @Column(name = "factor_time")
    private Integer factorTime;

    @Column(name = "factor_type")
    private Integer factorType;

    @Column(name = "scored_at", nullable = false)
    @Builder.Default
    private Instant scoredAt = Instant.now();

    @Column(name = "response_ms")
    private Integer responseMs;

    public static String levelFromScore(int score) {
        if (score >= 70) return "High";
        if (score >= 40) return "Medium";
        return "Low";
    }
}
