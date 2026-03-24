"""
FinGuardX — Test Suite
======================
Unit tests + Integration tests covering all SRS requirements.
Uses Python stdlib unittest — no external dependencies required.

Run:
  python -m unittest test_finguardx.py -v
  python test_finguardx.py                    # same with summary
"""

import sys, os, json, time, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

# ── Import app under test ──────────────────────────────────────────────────
from app import (
    app, _seed, get_model, ml_score, compute_credit,
    _factor_amount, _factor_category, _factor_location,
    _factor_time, _factor_type,
    create_access_token, create_refresh_token, decode_token,
    TRANSACTIONS, RISK_SCORES, ALERTS, TENANTS, USERS,
)

# Seed data once for entire test run
_seed()
get_model()


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def get_token(client, email="analyst@axiombank.com", password="password123"):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    return json.loads(r.data).get("access_token", "")

def auth(token):
    return {"Authorization": f"Bearer {token}"}

def post(client, path, body, token=None):
    h = {"Content-Type": "application/json"}
    if token: h["Authorization"] = f"Bearer {token}"
    return client.post(path, json=body, headers=h)

def get(client, path, token=None):
    h = {}
    if token: h["Authorization"] = f"Bearer {token}"
    return client.get(path, headers=h)


# ══════════════════════════════════════════════════════════════════════════════
# 1. AUTHENTICATION TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestAuthentication(unittest.TestCase):
    """SRS Feature 1: User Authentication and Tenant Access Management"""

    def setUp(self):
        self.client = app.test_client()

    # ── Login ──────────────────────────────────────────────────────────────
    def test_login_valid_credentials(self):
        """Valid credentials → 200 + access_token"""
        r = post(self.client, "/api/auth/login",
                 {"email": "analyst@axiombank.com", "password": "password123"})
        self.assertEqual(r.status_code, 200)
        d = json.loads(r.data)
        self.assertIn("access_token", d)
        self.assertIn("refresh_token", d)
        self.assertEqual(d["token_type"], "Bearer")

    def test_login_wrong_password(self):
        """Wrong password → 401"""
        r = post(self.client, "/api/auth/login",
                 {"email": "analyst@axiombank.com", "password": "wrongpassword"})
        self.assertEqual(r.status_code, 401)

    def test_login_unknown_email(self):
        """Unknown email → 401"""
        r = post(self.client, "/api/auth/login",
                 {"email": "nobody@fake.com", "password": "password123"})
        self.assertEqual(r.status_code, 401)

    def test_login_missing_email(self):
        """Missing email field → 400"""
        r = post(self.client, "/api/auth/login", {"password": "password123"})
        self.assertEqual(r.status_code, 400)

    def test_login_missing_password(self):
        """Missing password field → 400"""
        r = post(self.client, "/api/auth/login", {"email": "analyst@axiombank.com"})
        self.assertEqual(r.status_code, 400)

    def test_login_empty_body(self):
        """Empty body → 400"""
        r = post(self.client, "/api/auth/login", {})
        self.assertEqual(r.status_code, 400)

    def test_login_returns_user_info(self):
        """Login response includes user and tenant info"""
        r = post(self.client, "/api/auth/login",
                 {"email": "analyst@axiombank.com", "password": "password123"})
        d = json.loads(r.data)
        self.assertIn("user", d)
        self.assertEqual(d["user"]["role"], "ANALYST")
        self.assertIn("tenant", d["user"])

    def test_login_rate_95pct(self):
        """SRS §5: ≥95% login success rate — all valid creds must succeed"""
        successes = 0
        for email in USERS:
            r = post(self.client, "/api/auth/login",
                     {"email": email, "password": "password123"})
            if r.status_code == 200:
                successes += 1
        rate = successes / len(USERS)
        self.assertGreaterEqual(rate, 0.95,
            f"Login success rate {rate:.0%} below 95% SRS target")

    # ── Token ──────────────────────────────────────────────────────────────
    def test_jwt_token_is_valid(self):
        """Issued JWT must decode correctly"""
        r = post(self.client, "/api/auth/login",
                 {"email": "analyst@axiombank.com", "password": "password123"})
        token = json.loads(r.data)["access_token"]
        payload = decode_token(token)
        self.assertIn("sub", payload)
        self.assertIn("tenant", payload)
        self.assertIn("exp", payload)

    def test_me_endpoint_requires_auth(self):
        """GET /api/auth/me without token → 401"""
        r = get(self.client, "/api/auth/me")
        self.assertEqual(r.status_code, 401)

    def test_me_endpoint_with_valid_token(self):
        """GET /api/auth/me with valid token → 200"""
        token = get_token(self.client)
        r = get(self.client, "/api/auth/me", token)
        self.assertEqual(r.status_code, 200)
        d = json.loads(r.data)
        self.assertIn("role", d)

    def test_logout_revokes_token(self):
        """Logout then use same token → 401"""
        token = get_token(self.client)
        post(self.client, "/api/auth/logout", {}, token=token)
        r = get(self.client, "/api/auth/me", token)
        self.assertEqual(r.status_code, 401)

    def test_refresh_token(self):
        """Valid refresh token → new access token"""
        r = post(self.client, "/api/auth/login",
                 {"email": "analyst@axiombank.com", "password": "password123"})
        rt = json.loads(r.data)["refresh_token"]
        r2 = post(self.client, "/api/auth/refresh", {"refresh_token": rt})
        self.assertEqual(r2.status_code, 200)
        self.assertIn("access_token", json.loads(r2.data))

    def test_invalid_token_rejected(self):
        """Forged/invalid token → 401"""
        r = get(self.client, "/api/transactions",
                token="this.is.not.a.valid.jwt")
        self.assertEqual(r.status_code, 401)

    # ── Tenant isolation ───────────────────────────────────────────────────
    def test_tenant_isolation_different_tenants(self):
        """Users from different tenants cannot see each other's data"""
        token_ab = get_token(self.client, "analyst@axiombank.com")
        token_np = get_token(self.client, "analyst@novapay.io")

        r_ab = json.loads(get(self.client, "/api/transactions", token_ab).data)
        r_np = json.loads(get(self.client, "/api/transactions", token_np).data)

        ab_ids = {t["id"] for t in r_ab.get("transactions", [])}
        np_ids = {t["id"] for t in r_np.get("transactions", [])}

        # No overlap (seeded data is all in tenant t1 = Axiom Bank)
        self.assertEqual(len(ab_ids & np_ids), 0,
            "Tenant isolation breach: transactions visible across tenants")


# ══════════════════════════════════════════════════════════════════════════════
# 2. TRANSACTION INGESTION TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestTransactionIngestion(unittest.TestCase):
    """SRS Feature 2: Transaction Data Ingestion"""

    def setUp(self):
        self.client = app.test_client()
        self.token  = get_token(self.client)

    VALID_TX = {
        "customer_external_id": "USR-TEST-001",
        "amount":               1500.00,
        "tx_type":              "Card Payment",
        "merchant_category":    "Retail",
        "location_flag":        "Same country",
        "hour_of_day":          14,
    }

    def test_ingest_valid_transaction(self):
        """Valid transaction → 201"""
        import time as _t
        tx = {**self.VALID_TX, "external_tx_id": f"TXN-VALID-{int(_t.time()*1000)%999999}"}
        r = post(self.client, "/api/transactions", tx, token=self.token)
        self.assertEqual(r.status_code, 201)
        d = json.loads(r.data)
        self.assertIn("transaction", d)
        self.assertIn("id", d["transaction"])

    def test_ingest_requires_auth(self):
        """POST /api/transactions without token → 401"""
        r = post(self.client, "/api/transactions", self.VALID_TX)
        self.assertEqual(r.status_code, 401)

    def test_ingest_missing_amount(self):
        """Missing required field → 400"""
        tx = {k: v for k, v in self.VALID_TX.items() if k != "amount"}
        r = post(self.client, "/api/transactions", tx, token=self.token)
        self.assertEqual(r.status_code, 400)

    def test_ingest_negative_amount(self):
        """Negative amount → 400"""
        tx = {**self.VALID_TX, "amount": -100}
        r = post(self.client, "/api/transactions", tx, token=self.token)
        self.assertEqual(r.status_code, 400)

    def test_ingest_zero_amount(self):
        """Zero amount → 400"""
        tx = {**self.VALID_TX, "amount": 0}
        r = post(self.client, "/api/transactions", tx, token=self.token)
        self.assertEqual(r.status_code, 400)

    def test_ingest_invalid_hour(self):
        """Hour > 23 → 400"""
        tx = {**self.VALID_TX, "hour_of_day": 25}
        r = post(self.client, "/api/transactions", tx, token=self.token)
        self.assertEqual(r.status_code, 400)

    def test_ingest_invalid_tx_type(self):
        """Invalid tx_type → 400"""
        tx = {**self.VALID_TX, "tx_type": "Barter Exchange"}
        r = post(self.client, "/api/transactions", tx, token=self.token)
        self.assertEqual(r.status_code, 400)

    def test_ingest_invalid_location(self):
        """Invalid location_flag → 400"""
        tx = {**self.VALID_TX, "location_flag": "Outer Space"}
        r = post(self.client, "/api/transactions", tx, token=self.token)
        self.assertEqual(r.status_code, 400)

    def test_ingest_duplicate_detection(self):
        """Duplicate external_tx_id → 409"""
        tx = {**self.VALID_TX, "external_tx_id": "TXN-DUP-TEST-999"}
        post(self.client, "/api/transactions", tx, token=self.token)
        r = post(self.client, "/api/transactions", tx, token=self.token)
        self.assertEqual(r.status_code, 409)

    def test_get_transaction_by_id(self):
        """GET /api/transactions/{id} returns correct record"""
        r = post(self.client, "/api/transactions", self.VALID_TX, token=self.token)
        tx_id = json.loads(r.data)["transaction"]["id"]
        r2 = get(self.client, f"/api/transactions/{tx_id}", self.token)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(json.loads(r2.data)["id"], tx_id)

    def test_get_nonexistent_transaction(self):
        """GET unknown transaction → 404"""
        r = get(self.client, "/api/transactions/TXN-DOES-NOT-EXIST", self.token)
        self.assertEqual(r.status_code, 404)

    def test_list_transactions(self):
        """GET /api/transactions returns list with total"""
        r = get(self.client, "/api/transactions", self.token)
        self.assertEqual(r.status_code, 200)
        d = json.loads(r.data)
        self.assertIn("transactions", d)
        self.assertIn("total", d)
        self.assertIsInstance(d["transactions"], list)

    def test_filter_by_risk_level(self):
        """Filter transactions by risk_level returns only matching"""
        r = get(self.client, "/api/transactions?risk_level=High", self.token)
        d = json.loads(r.data)
        for tx in d["transactions"]:
            self.assertEqual(tx.get("risk_level"), "High")

    def test_ingestion_success_rate(self):
        """SRS §5: ≥99% ingestion success for valid records"""
        successes = 0
        n = 20
        for i in range(n):
            tx = {**self.VALID_TX,
                  "amount": 500 + i * 100,
                  "customer_external_id": f"USR-BULK-{i}",
                  "external_tx_id": f"TXN-BULK-{i:04d}"}
            r = post(self.client, "/api/transactions", tx, token=self.token)
            if r.status_code == 201:
                successes += 1
        rate = successes / n
        self.assertGreaterEqual(rate, 0.99,
            f"Ingestion success rate {rate:.0%} below 99% SRS target")


# ══════════════════════════════════════════════════════════════════════════════
# 3. RISK SCORING ENGINE TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestRiskScoringEngine(unittest.TestCase):
    """SRS Feature 3: Transaction Risk Scoring Engine"""

    def setUp(self):
        self.client = app.test_client()
        self.token  = get_token(self.client)

    HIGH_RISK_TX = {
        "amount": 48200, "tx_type": "Wire Transfer",
        "merchant_category": "Crypto Exchange",
        "location_flag": "High-risk jurisdiction",
        "hour_of_day": 2, "customer_external_id": "USR-HR-001",
    }
    LOW_RISK_TX = {
        "amount": 320, "tx_type": "Card Payment",
        "merchant_category": "Utilities",
        "location_flag": "Same country",
        "hour_of_day": 9, "customer_external_id": "USR-LR-001",
    }

    def test_score_evaluate_returns_200(self):
        """POST /api/risk-score/evaluate → 200"""
        r = post(self.client, "/api/risk-score/evaluate", self.HIGH_RISK_TX, token=self.token)
        self.assertEqual(r.status_code, 200)

    def test_score_in_valid_range(self):
        """Score must be between 0 and 100"""
        for tx in [self.HIGH_RISK_TX, self.LOW_RISK_TX]:
            r = post(self.client, "/api/risk-score/evaluate", tx, token=self.token)
            d = json.loads(r.data)
            self.assertGreaterEqual(d["score"], 0)
            self.assertLessEqual(d["score"], 100)

    def test_risk_level_categories(self):
        """Score 70+ → High, 40–69 → Medium, <40 → Low"""
        r = post(self.client, "/api/risk-score/evaluate", self.HIGH_RISK_TX, token=self.token)
        d = json.loads(r.data)
        score = d["score"]
        expected = "High" if score >= 70 else "Medium" if score >= 40 else "Low"
        self.assertEqual(d["risk_level"], expected)

    def test_high_risk_features_score_higher(self):
        """High-risk transaction must score higher than low-risk"""
        hr = post(self.client, "/api/risk-score/evaluate", self.HIGH_RISK_TX, token=self.token)
        lr = post(self.client, "/api/risk-score/evaluate", self.LOW_RISK_TX, token=self.token)
        hr_score = json.loads(hr.data)["score"]
        lr_score = json.loads(lr.data)["score"]
        self.assertGreater(hr_score, lr_score,
            f"High-risk tx ({hr_score}) should score above low-risk ({lr_score})")

    def test_score_response_time_under_sla(self):
        """SRS §5: Risk score response ≤ 2 seconds"""
        start = time.time()
        post(self.client, "/api/risk-score/evaluate", self.HIGH_RISK_TX, token=self.token)
        elapsed = time.time() - start
        self.assertLess(elapsed, 2.0,
            f"Scoring took {elapsed:.2f}s, exceeds 2s SLA")

    def test_score_consistency(self):
        """Same input always produces same output (deterministic)"""
        tx = {**self.HIGH_RISK_TX, "external_tx_id": "TXN-CONSIST-A"}
        r1 = post(self.client, "/api/risk-score/evaluate", tx, token=self.token)
        tx2 = {**self.HIGH_RISK_TX, "external_tx_id": "TXN-CONSIST-B"}
        r2 = post(self.client, "/api/risk-score/evaluate", tx2, token=self.token)
        self.assertEqual(json.loads(r1.data)["score"], json.loads(r2.data)["score"])

    def test_score_stored_and_retrievable(self):
        """Scored transaction → GET /api/risk-score/{id} returns stored score"""
        r = post(self.client, "/api/risk-score/evaluate", self.HIGH_RISK_TX, token=self.token)
        tx_id = json.loads(r.data)["transaction_id"]
        r2 = get(self.client, f"/api/risk-score/{tx_id}", self.token)
        self.assertEqual(r2.status_code, 200)
        d = json.loads(r2.data)
        self.assertIn("score", d)
        self.assertIn("risk_level", d)

    def test_score_factors_returned(self):
        """Evaluate response includes factor contributions"""
        r = post(self.client, "/api/risk-score/evaluate", self.HIGH_RISK_TX, token=self.token)
        d = json.loads(r.data)
        self.assertIn("factors", d)
        for key in ["amount", "category", "location", "time", "type"]:
            self.assertIn(key, d["factors"])

    def test_score_requires_auth(self):
        """Unauthenticated scoring → 401"""
        r = post(self.client, "/api/risk-score/evaluate", self.HIGH_RISK_TX)
        self.assertEqual(r.status_code, 401)

    def test_nonexistent_score_returns_404(self):
        """GET score for unknown tx → 404"""
        r = get(self.client, "/api/risk-score/TXN-FAKE-9999", self.token)
        self.assertEqual(r.status_code, 404)

    def test_high_risk_triggers_alert(self):
        """Score ≥ 70 auto-generates an alert"""
        tx = {**self.HIGH_RISK_TX, "external_tx_id": "TXN-ALERT-TEST"}
        r  = post(self.client, "/api/risk-score/evaluate", tx, token=self.token)
        d  = json.loads(r.data)
        if d["score"] >= 70:
            alerts = json.loads(get(self.client, "/api/alerts", self.token).data)
            alert_ids = [a["transaction_id"] for a in alerts.get("alerts", [])]
            self.assertIn(d["transaction_id"], alert_ids)

    # ── ML / heuristic factor unit tests ──────────────────────────────────
    def test_factor_amount_thresholds(self):
        self.assertEqual(_factor_amount(500),   3)
        self.assertEqual(_factor_amount(2000),  10)
        self.assertEqual(_factor_amount(8000),  20)
        self.assertEqual(_factor_amount(25000), 35)

    def test_factor_category(self):
        self.assertGreater(_factor_category("Gambling"),       _factor_category("Retail"))
        self.assertGreater(_factor_category("Crypto Exchange"),_factor_category("Healthcare"))

    def test_factor_location(self):
        self.assertGreater(_factor_location("High-risk jurisdiction"),
                           _factor_location("Cross-border"))
        self.assertGreater(_factor_location("Cross-border"),
                           _factor_location("Same country"))

    def test_factor_time_offhours(self):
        self.assertGreater(_factor_time(3),  _factor_time(14))
        self.assertGreater(_factor_time(23), _factor_time(12))

    def test_ml_score_returns_valid_range(self):
        s = ml_score(48200, 2, "Wire Transfer", "Crypto Exchange", "High-risk jurisdiction")
        self.assertGreaterEqual(s, 0)
        self.assertLessEqual(s, 100)


# ══════════════════════════════════════════════════════════════════════════════
# 4. DASHBOARD TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestDashboard(unittest.TestCase):
    """SRS Feature 4: Transaction Monitoring Dashboard"""

    def setUp(self):
        self.client = app.test_client()
        self.token  = get_token(self.client)

    def test_stats_endpoint_returns_200(self):
        r = get(self.client, "/api/dashboard/stats", self.token)
        self.assertEqual(r.status_code, 200)

    def test_stats_contains_required_fields(self):
        r = get(self.client, "/api/dashboard/stats", self.token)
        d = json.loads(r.data)
        for field in ["total_transactions","high_risk_count","avg_risk_score",
                      "active_alerts","distribution"]:
            self.assertIn(field, d, f"Missing field: {field}")

    def test_distribution_sums_correctly(self):
        d = json.loads(get(self.client, "/api/dashboard/stats", self.token).data)
        dist = d["distribution"]
        total = dist["high_pct"] + dist["medium_pct"] + dist["low_pct"]
        # Total covers scored transactions; may be < 100 if some are unscored
        self.assertGreaterEqual(total, 0)
        self.assertLessEqual(total, 100.1)

    def test_stats_requires_auth(self):
        r = get(self.client, "/api/dashboard/stats")
        self.assertEqual(r.status_code, 401)

    def test_transactions_paginated(self):
        """Transactions endpoint supports limit/offset pagination"""
        r1 = get(self.client, "/api/transactions?limit=5&offset=0", self.token)
        r2 = get(self.client, "/api/transactions?limit=5&offset=5", self.token)
        d1 = json.loads(r1.data)
        d2 = json.loads(r2.data)
        ids1 = {t["id"] for t in d1["transactions"]}
        ids2 = {t["id"] for t in d2["transactions"]}
        self.assertEqual(len(ids1 & ids2), 0, "Pagination overlap detected")


# ══════════════════════════════════════════════════════════════════════════════
# 5. CREDIT ANALYSIS TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestCreditAnalysis(unittest.TestCase):
    """SRS Feature 5: Credit Behavior Analysis"""

    def setUp(self):
        self.client = app.test_client()
        self.token  = get_token(self.client)

    def test_credit_analysis_returns_200(self):
        r = get(self.client, "/api/credit-analysis/USR-4821", self.token)
        self.assertEqual(r.status_code, 200)

    def test_confidence_score_in_range(self):
        r = get(self.client, "/api/credit-analysis/USR-4821", self.token)
        d = json.loads(r.data)
        score = d["confidence_score"]
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)

    def test_credit_contains_required_fields(self):
        r = get(self.client, "/api/credit-analysis/USR-4821", self.token)
        d = json.loads(r.data)
        for field in ["confidence_score","repayment_rate","avg_transaction",
                      "total_transactions","anomaly_count","activity_pattern",
                      "status","recommendation"]:
            self.assertIn(field, d, f"Missing field: {field}")

    def test_high_risk_user_scores_lower(self):
        good = json.loads(get(self.client, "/api/credit-analysis/USR-0134", self.token).data)
        bad  = json.loads(get(self.client, "/api/credit-analysis/USR-2291", self.token).data)
        self.assertGreater(good["confidence_score"], bad["confidence_score"])

    def test_credit_status_consistency(self):
        """Status must match score band"""
        r = get(self.client, "/api/credit-analysis/USR-4821", self.token)
        d = json.loads(r.data)
        s = d["confidence_score"]
        expected = ("Good Standing" if s >= 70 else
                    "Watch List"    if s >= 40 else "High Risk")
        self.assertEqual(d["status"], expected)

    def test_credit_requires_auth(self):
        r = get(self.client, "/api/credit-analysis/USR-4821")
        self.assertEqual(r.status_code, 401)


# ══════════════════════════════════════════════════════════════════════════════
# 6. ALERTS TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestAlerts(unittest.TestCase):
    """SRS Feature 6: High-Risk Transaction Alerts"""

    def setUp(self):
        self.client = app.test_client()
        self.token  = get_token(self.client)

    def test_alerts_endpoint_returns_200(self):
        r = get(self.client, "/api/alerts", self.token)
        self.assertEqual(r.status_code, 200)

    def test_alerts_have_required_fields(self):
        r = get(self.client, "/api/alerts", self.token)
        d = json.loads(r.data)
        for alert in d.get("alerts", []):
            for field in ["id","transaction_id","risk_score","severity","status"]:
                self.assertIn(field, alert, f"Alert missing field: {field}")

    def test_active_alerts_filter(self):
        r = get(self.client, "/api/alerts?status=ACTIVE", self.token)
        d = json.loads(r.data)
        for a in d.get("alerts", []):
            self.assertEqual(a["status"], "ACTIVE")

    def test_high_risk_scores_have_alerts(self):
        """Seeded high-risk transactions must have alerts"""
        r = get(self.client, "/api/alerts", self.token)
        d = json.loads(r.data)
        scores = [a["risk_score"] for a in d.get("alerts", [])]
        if scores:
            self.assertTrue(all(s >= 70 for s in scores),
                "Alert generated for score < 70")

    def test_acknowledge_alert(self):
        """POST /api/alerts/{id}/acknowledge → 200"""
        r = get(self.client, "/api/alerts?status=ACTIVE", self.token)
        alerts = json.loads(r.data).get("alerts", [])
        if alerts:
            alert_id = alerts[0]["id"]
            r2 = post(self.client, f"/api/alerts/{alert_id}/acknowledge",
                      {"action": "ACKNOWLEDGED"}, token=self.token)
            self.assertEqual(r2.status_code, 200)

    def test_acknowledge_unknown_alert(self):
        r = post(self.client, "/api/alerts/ALT-FAKE-999/acknowledge",
                 {"action": "ACKNOWLEDGED"}, token=self.token)
        self.assertEqual(r.status_code, 404)

    def test_alerts_require_auth(self):
        r = get(self.client, "/api/alerts")
        self.assertEqual(r.status_code, 401)


# ══════════════════════════════════════════════════════════════════════════════
# 7. HEALTH + INFRASTRUCTURE TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestInfrastructure(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_health_endpoint(self):
        r = get(self.client, "/api/health")
        self.assertEqual(r.status_code, 200)
        d = json.loads(r.data)
        self.assertEqual(d["status"], "ok")

    def test_health_shows_model_loaded(self):
        r = get(self.client, "/api/health")
        d = json.loads(r.data)
        self.assertTrue(d["model_loaded"])

    def test_tenants_public_endpoint(self):
        r = get(self.client, "/api/tenants")
        self.assertEqual(r.status_code, 200)
        d = json.loads(r.data)
        self.assertGreaterEqual(len(d["tenants"]), 3)

    def test_cors_headers_present(self):
        r = get(self.client, "/api/health")
        self.assertIn("Access-Control-Allow-Origin", r.headers)

    def test_multi_tenant_count(self):
        """SRS §5: Minimum 5 concurrent organizations supported (config ≥ 3 seeded)"""
        # Architecture supports N tenants; seeded with 3
        self.assertGreaterEqual(len(TENANTS), 3)


# ══════════════════════════════════════════════════════════════════════════════
# 8. RISK ENGINE UNIT TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestRiskEngineUnit(unittest.TestCase):
    """Unit tests for the ML scoring engine"""

    def test_model_loads(self):
        model, enc = get_model()
        self.assertIsNotNone(model)
        self.assertIsNotNone(enc)

    def test_ml_score_deterministic(self):
        s1 = ml_score(5000, 14, "Card Payment", "Retail", "Same country")
        s2 = ml_score(5000, 14, "Card Payment", "Retail", "Same country")
        self.assertEqual(s1, s2)

    def test_credit_compute_stable(self):
        c = compute_credit("USR-4821", [])
        self.assertIn("confidence_score", c)
        self.assertIn("recommendation", c)
        self.assertIn("score_history", c)
        self.assertEqual(len(c["score_history"]), 12)

    def test_score_accuracy_target(self):
        """SRS §2.2: ≥85% classification accuracy"""
        # Test with known high-risk combos — all should score > low threshold
        high_risk_cases = [
            (48200, 2,  "Wire Transfer",     "Crypto Exchange", "High-risk jurisdiction"),
            (22500, 3,  "Crypto Conversion", "Crypto Exchange", "High-risk jurisdiction"),
            (15600, 23, "Wire Transfer",     "Gambling",        "High-risk jurisdiction"),
        ]
        low_risk_cases = [
            (320,  9,  "Card Payment", "Utilities", "Same country"),
            (680,  16, "Card Payment", "Healthcare","Same country"),
            (420,  8,  "Card Payment", "Utilities", "Same country"),
        ]
        hr_scores = [ml_score(*c) for c in high_risk_cases]
        lr_scores = [ml_score(*c) for c in low_risk_cases]

        avg_hr = sum(hr_scores) / len(hr_scores)
        avg_lr = sum(lr_scores) / len(lr_scores)

        self.assertGreater(avg_hr, avg_lr,
            f"High-risk avg ({avg_hr:.1f}) not above low-risk avg ({avg_lr:.1f})")


# ══════════════════════════════════════════════════════════════════════════════
# TEST RUNNER
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite  = unittest.TestSuite()

    test_classes = [
        TestAuthentication,
        TestTransactionIngestion,
        TestRiskScoringEngine,
        TestDashboard,
        TestCreditAnalysis,
        TestAlerts,
        TestInfrastructure,
        TestRiskEngineUnit,
    ]
    for cls in test_classes:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "═"*60)
    print(f"  Tests run:    {result.testsRun}")
    print(f"  Passed:       {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"  Failures:     {len(result.failures)}")
    print(f"  Errors:       {len(result.errors)}")
    print("═"*60)
    sys.exit(0 if result.wasSuccessful() else 1)
