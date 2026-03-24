package com.finguardx;

import com.finguardx.dto.*;
import com.finguardx.model.*;
import com.finguardx.security.JwtUtil;
import com.finguardx.service.*;
import org.junit.jupiter.api.*;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.math.BigDecimal;
import java.util.UUID;

import static org.hamcrest.Matchers.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

/**
 * FinGuardX — Spring Boot Integration Tests
 * SRS §9: Testing phase — Weeks 9–10
 *
 * Uses H2 in-memory DB for isolated test runs.
 * Run: mvn test
 */
@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
@TestMethodOrder(MethodOrderer.OrderAnnotation.class)
class FinGuardXApplicationTests {

    @Autowired MockMvc mvc;
    @Autowired ObjectMapper mapper;
    @Autowired JwtUtil jwtUtil;

    private static String accessToken;
    private static String refreshToken;
    private static String lastTxId;

    // ── Helper ──────────────────────────────────────────────────────────────
    private String json(Object obj) throws Exception { return mapper.writeValueAsString(obj); }

    private String login() throws Exception {
        var req = new LoginRequest();
        req.setEmail("analyst@axiombank.com");
        req.setPassword("password123");
        var res = mvc.perform(post("/api/auth/login")
                .contentType(MediaType.APPLICATION_JSON)
                .content(json(req)))
                .andReturn().getResponse().getContentAsString();
        var node = mapper.readTree(res);
        return node.get("access_token").asText();
    }

    // ── Auth tests ──────────────────────────────────────────────────────────

    @Test @Order(1)
    @DisplayName("POST /api/auth/login — valid credentials → 200 + tokens")
    void loginValid() throws Exception {
        var req = new LoginRequest();
        req.setEmail("analyst@axiombank.com");
        req.setPassword("password123");

        var result = mvc.perform(post("/api/auth/login")
                .contentType(MediaType.APPLICATION_JSON)
                .content(json(req)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.access_token").isString())
                .andExpect(jsonPath("$.refresh_token").isString())
                .andExpect(jsonPath("$.token_type").value("Bearer"))
                .andExpect(jsonPath("$.user.role").isString())
                .andReturn();

        var node = mapper.readTree(result.getResponse().getContentAsString());
        accessToken  = node.get("access_token").asText();
        refreshToken = node.get("refresh_token").asText();
    }

    @Test @Order(2)
    @DisplayName("POST /api/auth/login — wrong password → 401")
    void loginInvalid() throws Exception {
        var req = new LoginRequest();
        req.setEmail("analyst@axiombank.com");
        req.setPassword("wrongpassword");

        mvc.perform(post("/api/auth/login")
                .contentType(MediaType.APPLICATION_JSON)
                .content(json(req)))
                .andExpect(status().isUnauthorized());
    }

    @Test @Order(3)
    @DisplayName("POST /api/auth/login — missing fields → 400")
    void loginMissingFields() throws Exception {
        mvc.perform(post("/api/auth/login")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{}"))
                .andExpect(status().isBadRequest());
    }

    @Test @Order(4)
    @DisplayName("GET /api/auth/me — valid token → 200")
    void meValid() throws Exception {
        if (accessToken == null) accessToken = login();
        mvc.perform(get("/api/auth/me")
                .header("Authorization", "Bearer " + accessToken))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.role").isString());
    }

    @Test @Order(5)
    @DisplayName("GET /api/auth/me — no token → 401")
    void meUnauthorized() throws Exception {
        mvc.perform(get("/api/auth/me"))
                .andExpect(status().isUnauthorized());
    }

    // ── Transaction tests ────────────────────────────────────────────────────

    @Test @Order(10)
    @DisplayName("POST /api/transactions — valid → 201")
    void ingestValid() throws Exception {
        if (accessToken == null) accessToken = login();
        var body = """
            {"customerExternalId":"USR-TEST-001","amount":5200,
             "txType":"Card Payment","merchantCategory":"Retail",
             "locationFlag":"Same country","hourOfDay":14}""";

        var result = mvc.perform(post("/api/transactions")
                .header("Authorization", "Bearer " + accessToken)
                .contentType(MediaType.APPLICATION_JSON).content(body))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.transaction.id").isString())
                .andReturn();

        lastTxId = mapper.readTree(result.getResponse().getContentAsString())
                         .path("transaction").path("id").asText();
    }

    @Test @Order(11)
    @DisplayName("POST /api/transactions — negative amount → 400")
    void ingestNegativeAmount() throws Exception {
        var body = """
            {"customerExternalId":"USR-TEST","amount":-100,
             "txType":"Card Payment","merchantCategory":"Retail",
             "locationFlag":"Same country","hourOfDay":12}""";
        mvc.perform(post("/api/transactions")
                .header("Authorization", "Bearer " + accessToken)
                .contentType(MediaType.APPLICATION_JSON).content(body))
                .andExpect(status().isBadRequest());
    }

    @Test @Order(12)
    @DisplayName("POST /api/transactions — no auth → 401")
    void ingestNoAuth() throws Exception {
        mvc.perform(post("/api/transactions")
                .contentType(MediaType.APPLICATION_JSON).content("{}"))
                .andExpect(status().isUnauthorized());
    }

    @Test @Order(13)
    @DisplayName("GET /api/transactions — list → 200 with pagination")
    void listTransactions() throws Exception {
        mvc.perform(get("/api/transactions")
                .header("Authorization", "Bearer " + accessToken))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.transactions").isArray())
                .andExpect(jsonPath("$.total").isNumber())
                .andExpect(jsonPath("$.limit").isNumber());
    }

    @Test @Order(14)
    @DisplayName("GET /api/transactions/{id} — existing → 200")
    void getTransaction() throws Exception {
        if (lastTxId == null) return;
        mvc.perform(get("/api/transactions/" + lastTxId)
                .header("Authorization", "Bearer " + accessToken))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.id").value(lastTxId));
    }

    @Test @Order(15)
    @DisplayName("GET /api/transactions/fake-id → 404")
    void getTransactionNotFound() throws Exception {
        mvc.perform(get("/api/transactions/" + UUID.randomUUID())
                .header("Authorization", "Bearer " + accessToken))
                .andExpect(status().isNotFound());
    }

    // ── Risk scoring tests ───────────────────────────────────────────────────

    @Test @Order(20)
    @DisplayName("POST /api/risk-score/evaluate — high risk → score in range")
    void evaluateHighRisk() throws Exception {
        var body = """
            {"amount":48200,"txType":"Wire Transfer",
             "merchantCategory":"Crypto Exchange",
             "locationFlag":"High-risk jurisdiction",
             "hourOfDay":2,"customerExternalId":"USR-HR"}""";

        mvc.perform(post("/api/risk-score/evaluate")
                .header("Authorization", "Bearer " + accessToken)
                .contentType(MediaType.APPLICATION_JSON).content(body))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.score").value(greaterThanOrEqualTo(0)))
                .andExpect(jsonPath("$.score").value(lessThanOrEqualTo(100)))
                .andExpect(jsonPath("$.risk_level").isString())
                .andExpect(jsonPath("$.factors").isMap())
                .andExpect(jsonPath("$.response_ms").isNumber());
    }

    @Test @Order(21)
    @DisplayName("SRS §5: Risk score response time ≤ 2s")
    void evaluateSla() throws Exception {
        var body = """
            {"amount":1000,"txType":"Card Payment",
             "merchantCategory":"Retail",
             "locationFlag":"Same country","hourOfDay":14}""";
        long start = System.currentTimeMillis();
        mvc.perform(post("/api/risk-score/evaluate")
                .header("Authorization", "Bearer " + accessToken)
                .contentType(MediaType.APPLICATION_JSON).content(body))
                .andExpect(status().isOk());
        Assertions.assertTrue(System.currentTimeMillis() - start < 2000,
            "Scoring SLA exceeded 2000ms");
    }

    @Test @Order(22)
    @DisplayName("GET /api/risk-score/fake → 404")
    void getRiskScoreNotFound() throws Exception {
        mvc.perform(get("/api/risk-score/" + UUID.randomUUID())
                .header("Authorization", "Bearer " + accessToken))
                .andExpect(status().isNotFound());
    }

    // ── Credit analysis tests ────────────────────────────────────────────────

    @Test @Order(30)
    @DisplayName("GET /api/credit-analysis/{userId} → 200 with all fields")
    void creditAnalysis() throws Exception {
        mvc.perform(get("/api/credit-analysis/USR-4821")
                .header("Authorization", "Bearer " + accessToken))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.confidence_score").isNumber())
                .andExpect(jsonPath("$.repayment_rate").isNumber())
                .andExpect(jsonPath("$.recommendation").isString())
                .andExpect(jsonPath("$.status").isString())
                .andExpect(jsonPath("$.score_history").isArray());
    }

    @Test @Order(31)
    @DisplayName("GET /api/credit-analysis — no auth → 401")
    void creditAnalysisNoAuth() throws Exception {
        mvc.perform(get("/api/credit-analysis/USR-4821"))
                .andExpect(status().isUnauthorized());
    }

    // ── Dashboard tests ──────────────────────────────────────────────────────

    @Test @Order(40)
    @DisplayName("GET /api/dashboard/stats → 200 with required fields")
    void dashboardStats() throws Exception {
        mvc.perform(get("/api/dashboard/stats")
                .header("Authorization", "Bearer " + accessToken))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.total_transactions").isNumber())
                .andExpect(jsonPath("$.high_risk_count").isNumber())
                .andExpect(jsonPath("$.avg_risk_score").isNumber())
                .andExpect(jsonPath("$.distribution").isMap());
    }

    // ── Alerts tests ─────────────────────────────────────────────────────────

    @Test @Order(50)
    @DisplayName("GET /api/alerts → 200 with alerts array")
    void listAlerts() throws Exception {
        mvc.perform(get("/api/alerts")
                .header("Authorization", "Bearer " + accessToken))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.alerts").isArray())
                .andExpect(jsonPath("$.total").isNumber());
    }

    @Test @Order(51)
    @DisplayName("GET /api/alerts — no auth → 401")
    void alertsNoAuth() throws Exception {
        mvc.perform(get("/api/alerts"))
                .andExpect(status().isUnauthorized());
    }

    // ── Health + infrastructure ───────────────────────────────────────────────

    @Test @Order(60)
    @DisplayName("GET /api/health → 200")
    void health() throws Exception {
        mvc.perform(get("/api/health"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("ok"));
    }

    @Test @Order(61)
    @DisplayName("GET /api/tenants → public, 200")
    void tenants() throws Exception {
        mvc.perform(get("/api/tenants"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.tenants").isArray());
    }
}
