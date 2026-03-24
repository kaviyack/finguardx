package com.finguardx.repository;

import com.finguardx.model.*;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

// ─── Tenant Repository ────────────────────────────────────────────────────────
@Repository
interface TenantRepository extends JpaRepository<Tenant, UUID> {
    Optional<Tenant> findByCode(String code);
    Optional<Tenant> findByName(String name);
}

// ─── User Repository ──────────────────────────────────────────────────────────
@Repository
interface UserRepository extends JpaRepository<User, UUID> {
    /**
     * SRS Feature 1: Authenticate user within their tenant scope.
     * Tenant isolation enforced at query level.
     */
    Optional<User> findByEmailAndTenantId(String email, UUID tenantId);
    Optional<User> findByEmail(String email);
    boolean existsByEmailAndTenantId(String email, UUID tenantId);
}

// ─── Transaction Repository ───────────────────────────────────────────────────
@Repository
interface TransactionRepository extends JpaRepository<Transaction, UUID> {

    /**
     * SRS Feature 2: List transactions for a tenant (tenant isolation).
     * SRS §6.3: Indexed on tenant_id and submitted_at.
     */
    Page<Transaction> findByTenantIdOrderBySubmittedAtDesc(UUID tenantId, Pageable pageable);

    /**
     * SRS Feature 2: Filter by risk level (via join to risk_scores).
     */
    @Query("""
        SELECT t FROM Transaction t
        JOIN RiskScore r ON r.transaction.id = t.id
        WHERE t.tenantId = :tenantId AND r.riskLevel = :riskLevel
        ORDER BY t.submittedAt DESC
        """)
    Page<Transaction> findByTenantIdAndRiskLevel(
        @Param("tenantId") UUID tenantId,
        @Param("riskLevel") String riskLevel,
        Pageable pageable
    );

    /**
     * SRS Feature 2: Duplicate detection — reject if same externalTxId exists for tenant.
     */
    boolean existsByTenantIdAndExternalTxId(UUID tenantId, String externalTxId);

    Optional<Transaction> findByIdAndTenantId(UUID id, UUID tenantId);

    /** For credit analysis — get all transactions for a customer in a tenant */
    List<Transaction> findByTenantIdAndCustomerExternalId(UUID tenantId, String customerExternalId);

    /** Dashboard stats */
    long countByTenantId(UUID tenantId);

    @Query("SELECT COUNT(t) FROM Transaction t WHERE t.tenantId = :tenantId AND t.status = 'FLAGGED'")
    long countHighRiskByTenantId(@Param("tenantId") UUID tenantId);
}

// ─── RiskScore Repository ─────────────────────────────────────────────────────
@Repository
interface RiskScoreRepository extends JpaRepository<RiskScore, UUID> {

    Optional<RiskScore> findByTransactionId(UUID transactionId);

    /**
     * SRS §6.3: Indexed on risk_level for dashboard filtering.
     */
    @Query("""
        SELECT COUNT(r) FROM RiskScore r
        WHERE r.tenantId = :tenantId AND r.riskLevel = :level
        """)
    long countByTenantIdAndRiskLevel(@Param("tenantId") UUID tenantId, @Param("level") String level);

    @Query("SELECT AVG(r.score) FROM RiskScore r WHERE r.tenantId = :tenantId")
    Double avgScoreByTenantId(@Param("tenantId") UUID tenantId);

    /** For tenant isolation check */
    Optional<RiskScore> findByTransactionIdAndTenantId(UUID transactionId, UUID tenantId);
}

// ─── Alert Repository ─────────────────────────────────────────────────────────
@Repository
interface AlertRepository extends JpaRepository<Alert, UUID> {

    /**
     * SRS Feature 6: Real-time alerts for high-risk transactions.
     */
    List<Alert> findByTenantIdOrderByCreatedAtDesc(UUID tenantId);

    List<Alert> findByTenantIdAndStatusOrderByCreatedAtDesc(UUID tenantId, String status);

    long countByTenantIdAndStatus(UUID tenantId, String status);

    boolean existsByTransactionId(UUID transactionId);
}
