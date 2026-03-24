package com.finguardx.controller;

import com.finguardx.dto.*;
import com.finguardx.service.*;
import com.finguardx.security.JwtUtil;
import io.jsonwebtoken.Claims;
import jakarta.validation.Valid;
import org.springframework.data.domain.*;
import org.springframework.http.*;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.util.UUID;

// ─── Auth Controller ──────────────────────────────────────────────────────────
/**
 * SRS Feature 1: User Authentication and Tenant Access Management
 * Endpoints: POST /api/auth/login, /logout, /refresh, GET /api/auth/me
 */
@RestController
@RequestMapping("/api/auth")
class AuthController {

    private final AuthService authService;
    AuthController(AuthService authService) { this.authService = authService; }

    /** POST /api/auth/login — authenticate and return JWT tokens */
    @PostMapping("/login")
    public ResponseEntity<?> login(@Valid @RequestBody LoginRequest req) {
        try {
            return ResponseEntity.ok(authService.login(req.getEmail(), req.getPassword()));
        } catch (Exception e) {
            return ResponseEntity.status(401).body(new ErrorResponse(e.getMessage(), 401));
        }
    }

    /** POST /api/auth/logout — revoke access token */
    @PostMapping("/logout")
    public ResponseEntity<?> logout(
            @RequestHeader("Authorization") String authHeader) {
        authService.logout(authHeader.substring(7));
        return ResponseEntity.ok().body("{\"message\":\"Logged out successfully\"}");
    }

    /** POST /api/auth/refresh — exchange refresh token for new access token */
    @PostMapping("/refresh")
    public ResponseEntity<?> refresh(@Valid @RequestBody RefreshRequest req) {
        try {
            return ResponseEntity.ok(authService.refresh(req.getRefreshToken()));
        } catch (Exception e) {
            return ResponseEntity.status(401).body(new ErrorResponse(e.getMessage(), 401));
        }
    }

    /** GET /api/auth/me — current user profile */
    @GetMapping("/me")
    public ResponseEntity<?> me(@AuthenticationPrincipal Claims claims) {
        return ResponseEntity.ok(authService.getCurrentUser(claims));
    }
}

// ─── Transaction Controller ───────────────────────────────────────────────────
/**
 * SRS Feature 2: Transaction Data Ingestion
 * Endpoints: POST /api/transactions, GET /api/transactions, GET /api/transactions/{id}
 */
@RestController
@RequestMapping("/api/transactions")
class TransactionController {

    private final TransactionService txService;
    TransactionController(TransactionService txService) { this.txService = txService; }

    /** POST /api/transactions — ingest and validate transaction */
    @PostMapping
    public ResponseEntity<?> ingest(
            @Valid @RequestBody TransactionRequest req,
            @AuthenticationPrincipal Claims claims) {
        try {
            var tx = txService.ingest(req, tenantId(claims));
            return ResponseEntity.status(201).body(tx);
        } catch (DuplicateTransactionException e) {
            return ResponseEntity.status(409).body(new ErrorResponse(e.getMessage(), 409));
        } catch (Exception e) {
            return ResponseEntity.badRequest().body(new ErrorResponse(e.getMessage(), 400));
        }
    }

    /** GET /api/transactions — list with optional filters */
    @GetMapping
    public ResponseEntity<TransactionListResponse> list(
            @RequestParam(defaultValue = "") String riskLevel,
            @RequestParam(defaultValue = "") String status,
            @RequestParam(defaultValue = "100") int limit,
            @RequestParam(defaultValue = "0")   int offset,
            @AuthenticationPrincipal Claims claims) {
        var pageable = PageRequest.of(offset / Math.max(limit,1), Math.min(limit, 500));
        return ResponseEntity.ok(txService.list(tenantId(claims), riskLevel, status, pageable));
    }

    /** GET /api/transactions/{id} — retrieve single transaction */
    @GetMapping("/{id}")
    public ResponseEntity<?> get(
            @PathVariable UUID id,
            @AuthenticationPrincipal Claims claims) {
        return txService.findById(id, tenantId(claims))
                .map(ResponseEntity::ok)
                .orElse(ResponseEntity.notFound().build());
    }

    private UUID tenantId(Claims claims) {
        return UUID.fromString(claims.get("tenantId", String.class));
    }
}

// ─── Risk Score Controller ────────────────────────────────────────────────────
/**
 * SRS Feature 3: Transaction Risk Scoring Engine
 * SRS §5: ≤ 2 second response time
 */
@RestController
@RequestMapping("/api/risk-score")
class RiskScoreController {

    private final RiskScoringService scoringService;
    RiskScoreController(RiskScoringService scoringService) { this.scoringService = scoringService; }

    /** POST /api/risk-score/evaluate — score a transaction */
    @PostMapping("/evaluate")
    public ResponseEntity<?> evaluate(
            @RequestBody RiskEvaluateRequest req,
            @AuthenticationPrincipal Claims claims) {
        try {
            return ResponseEntity.ok(scoringService.evaluate(req, tenantId(claims)));
        } catch (Exception e) {
            return ResponseEntity.badRequest().body(new ErrorResponse(e.getMessage(), 400));
        }
    }

    /** GET /api/risk-score/{transactionId} — retrieve stored score */
    @GetMapping("/{transactionId}")
    public ResponseEntity<?> get(
            @PathVariable UUID transactionId,
            @AuthenticationPrincipal Claims claims) {
        return scoringService.findByTransactionId(transactionId, tenantId(claims))
                .map(ResponseEntity::ok)
                .orElse(ResponseEntity.notFound().build());
    }

    private UUID tenantId(Claims claims) {
        return UUID.fromString(claims.get("tenantId", String.class));
    }
}

// ─── Credit Analysis Controller ───────────────────────────────────────────────
/**
 * SRS Feature 5: Credit Behavior Analysis
 * Endpoint: GET /api/credit-analysis/{userId}
 */
@RestController
@RequestMapping("/api/credit-analysis")
class CreditAnalysisController {

    private final CreditAnalysisService creditService;
    CreditAnalysisController(CreditAnalysisService creditService) { this.creditService = creditService; }

    /** GET /api/credit-analysis/{userId} — credit confidence score + behavioral insights */
    @GetMapping("/{userId}")
    public ResponseEntity<CreditAnalysisResponse> analyse(
            @PathVariable String userId,
            @AuthenticationPrincipal Claims claims) {
        UUID tenantId = UUID.fromString(claims.get("tenantId", String.class));
        return ResponseEntity.ok(creditService.analyse(userId, tenantId));
    }
}

// ─── Alerts Controller ────────────────────────────────────────────────────────
/**
 * SRS Feature 6: High-Risk Transaction Alerts
 */
@RestController
@RequestMapping("/api/alerts")
class AlertController {

    private final AlertService alertService;
    AlertController(AlertService alertService) { this.alertService = alertService; }

    /** GET /api/alerts — list alerts (filter: status=ACTIVE) */
    @GetMapping
    public ResponseEntity<AlertListResponse> list(
            @RequestParam(defaultValue = "") String status,
            @AuthenticationPrincipal Claims claims) {
        UUID tenantId = UUID.fromString(claims.get("tenantId", String.class));
        return ResponseEntity.ok(alertService.list(tenantId, status));
    }

    /** POST /api/alerts/{id}/acknowledge — update alert status */
    @PostMapping("/{id}/acknowledge")
    public ResponseEntity<?> acknowledge(
            @PathVariable UUID id,
            @Valid @RequestBody AcknowledgeRequest req,
            @AuthenticationPrincipal Claims claims) {
        UUID tenantId = UUID.fromString(claims.get("tenantId", String.class));
        UUID userId   = UUID.fromString(claims.getSubject());
        return alertService.acknowledge(id, tenantId, userId, req.getAction(), req.getNotes())
                .map(ResponseEntity::ok)
                .orElse(ResponseEntity.notFound().build());
    }
}

// ─── Dashboard Controller ─────────────────────────────────────────────────────
/**
 * SRS Feature 4: Transaction Monitoring Dashboard
 */
@RestController
@RequestMapping("/api/dashboard")
class DashboardController {

    private final DashboardService dashboardService;
    DashboardController(DashboardService dashboardService) { this.dashboardService = dashboardService; }

    /** GET /api/dashboard/stats — summary stats */
    @GetMapping("/stats")
    public ResponseEntity<DashboardStatsResponse> stats(
            @AuthenticationPrincipal Claims claims) {
        UUID tenantId = UUID.fromString(claims.get("tenantId", String.class));
        return ResponseEntity.ok(dashboardService.stats(tenantId));
    }
}

// ─── Tenant Controller ────────────────────────────────────────────────────────
@RestController
@RequestMapping("/api/tenants")
class TenantController {

    private final TenantService tenantService;
    TenantController(TenantService tenantService) { this.tenantService = tenantService; }

    /** GET /api/tenants — public tenant list for login selector */
    @GetMapping
    public ResponseEntity<?> list() {
        return ResponseEntity.ok(java.util.Map.of("tenants", tenantService.listAll()));
    }
}

// ─── Health Controller ────────────────────────────────────────────────────────
@RestController
@RequestMapping("/api")
class HealthController {

    /** GET /api/health */
    @GetMapping("/health")
    public ResponseEntity<?> health() {
        return ResponseEntity.ok(java.util.Map.of(
            "status",  "ok",
            "version", "1.0.0",
            "tenants", 3,
            "timestamp", java.time.Instant.now().toString()
        ));
    }
}

// ─── Exception types ──────────────────────────────────────────────────────────
class DuplicateTransactionException extends RuntimeException {
    public DuplicateTransactionException(String msg) { super(msg); }
}
