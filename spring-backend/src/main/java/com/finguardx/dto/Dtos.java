package com.finguardx.dto;

import jakarta.validation.constraints.*;
import lombok.*;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;

// ─── Auth DTOs ────────────────────────────────────────────────────────────────

/** POST /api/auth/login request body */
@Data public class LoginRequest {
    @NotBlank @Email
    private String email;
    @NotBlank @Size(min = 6)
    private String password;
}

/** POST /api/auth/login response */
@Data @Builder @NoArgsConstructor @AllArgsConstructor
public class LoginResponse {
    private String accessToken;
    private String refreshToken;
    private String tokenType = "Bearer";
    private int expiresIn;
    private UserInfo user;

    @Data @Builder @NoArgsConstructor @AllArgsConstructor
    public static class UserInfo {
        private String id;
        private String email;
        private String name;
        private String role;
        private String tenantId;
        private String tenant;
    }
}

/** POST /api/auth/refresh request body */
@Data public class RefreshRequest {
    @NotBlank private String refreshToken;
}

// ─── Transaction DTOs ─────────────────────────────────────────────────────────

/** POST /api/transactions request body */
@Data public class TransactionRequest {
    @NotBlank
    private String customerExternalId;

    @NotNull @DecimalMin("0.01")
    private BigDecimal amount;

    @NotBlank
    private String txType;

    @NotBlank
    private String merchantCategory;

    @NotBlank
    private String locationFlag;

    @Min(0) @Max(23)
    private Integer hourOfDay;

    /** Optional: caller-supplied external ID; auto-generated if absent */
    private String externalTxId;
}

/** Transaction response DTO (enriched with risk score if available) */
@Data @Builder @NoArgsConstructor @AllArgsConstructor
public class TransactionResponse {
    private UUID id;
    private String externalTxId;
    private String customerExternalId;
    private BigDecimal amount;
    private String txType;
    private String merchantCategory;
    private String locationFlag;
    private Integer hourOfDay;
    private String status;
    private Instant submittedAt;
    // Enriched from risk_scores if scored
    private Integer riskScore;
    private String riskLevel;
    private Instant scoredAt;
}

/** Paginated transaction list response */
@Data @Builder @NoArgsConstructor @AllArgsConstructor
public class TransactionListResponse {
    private int total;
    private int limit;
    private int offset;
    private List<TransactionResponse> transactions;
}

// ─── Risk Score DTOs ──────────────────────────────────────────────────────────

/** POST /api/risk-score/evaluate request body */
@Data public class RiskEvaluateRequest {
    /** Evaluate existing transaction by ID */
    private UUID transactionId;

    /** Or provide raw fields for ad-hoc scoring */
    private BigDecimal amount;
    private Integer hourOfDay;
    private String txType;
    private String merchantCategory;
    private String locationFlag;
    private String customerExternalId;
}

/** Risk evaluation response */
@Data @Builder @NoArgsConstructor @AllArgsConstructor
public class RiskScoreResponse {
    private UUID transactionId;
    private int score;
    private String riskLevel;
    private Map<String, Integer> factors;
    private int responseMs;
    private String modelVersion;
}

// ─── Credit Analysis DTOs ─────────────────────────────────────────────────────

/** GET /api/credit-analysis/{userId} response */
@Data @Builder @NoArgsConstructor @AllArgsConstructor
public class CreditAnalysisResponse {
    private String customerId;
    private String name;
    private int confidenceScore;
    private double repaymentRate;
    private BigDecimal avgTransaction;
    private int totalTransactions;
    private int anomalyCount;
    private String activityPattern;
    private String status;
    private String recommendation;
    private List<Integer> scoreHistory;
    private Instant analysedAt;
}

// ─── Alert DTOs ───────────────────────────────────────────────────────────────

/** Alert response */
@Data @Builder @NoArgsConstructor @AllArgsConstructor
public class AlertResponse {
    private UUID id;
    private UUID transactionId;
    private int riskScore;
    private String severity;
    private String status;
    private Instant createdAt;
    private Instant acknowledgedAt;
    private String notes;
    private TransactionResponse transaction;
}

/** POST /api/alerts/{id}/acknowledge request body */
@Data public class AcknowledgeRequest {
    @NotBlank private String action;
    private String notes;
}

/** Paginated alert list */
@Data @Builder @NoArgsConstructor @AllArgsConstructor
public class AlertListResponse {
    private int total;
    private List<AlertResponse> alerts;
}

// ─── Dashboard DTOs ───────────────────────────────────────────────────────────

/** GET /api/dashboard/stats response */
@Data @Builder @NoArgsConstructor @AllArgsConstructor
public class DashboardStatsResponse {
    private long totalTransactions;
    private long highRiskCount;
    private long mediumRiskCount;
    private long lowRiskCount;
    private double avgRiskScore;
    private long activeAlerts;
    private double accuracyPct;
    private Distribution distribution;

    @Data @Builder @NoArgsConstructor @AllArgsConstructor
    public static class Distribution {
        private double highPct;
        private double mediumPct;
        private double lowPct;
    }
}

// ─── Tenant DTO ───────────────────────────────────────────────────────────────

@Data @Builder @NoArgsConstructor @AllArgsConstructor
public class TenantResponse {
    private String id;
    private String name;
    private String type;
    private String code;
}

// ─── Error DTO ────────────────────────────────────────────────────────────────

@Data @Builder @NoArgsConstructor @AllArgsConstructor
public class ErrorResponse {
    private String error;
    private int status;
    private Instant timestamp = Instant.now();

    public ErrorResponse(String error, int status) {
        this.error = error;
        this.status = status;
    }
}
