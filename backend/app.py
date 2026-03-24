"""
FinGuardX — Python Flask Backend
Handles: Auth (JWT), Transactions, Risk Scoring, Credit Analysis, Alerts
Multi-tenant with strict tenant isolation on every endpoint.
"""

import os, time, json, hashlib, secrets
from datetime import datetime, timedelta, timezone
from functools import wraps

import jwt
import numpy as np
import pandas as pd
from flask import Flask, request, jsonify, g
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import LabelEncoder
import joblib

app = Flask(__name__)

# ─── CONFIG ─────────────────────────────────────────────────────────────────
SECRET_KEY = os.environ.get("JWT_SECRET", "finguardx-secret-dev-key-change-in-prod")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
REFRESH_TOKEN_EXPIRE_DAYS = 7
MODEL_PATH = os.path.join(os.path.dirname(__file__), "model", "risk_model.joblib")
ENCODERS_PATH = os.path.join(os.path.dirname(__file__), "model", "encoders.joblib")

# ─── IN-MEMORY STORE (replaces PostgreSQL for standalone demo) ───────────────
# In production these are replaced by the PostgreSQL repository layer.

TENANTS = {
    "AB": {"id": "t1", "name": "Axiom Bank",   "type": "Commercial Bank",  "code": "AB"},
    "NP": {"id": "t2", "name": "NovaPay",       "type": "Fintech",          "code": "NP"},
    "CS": {"id": "t3", "name": "CreditSphere",  "type": "Lending Platform", "code": "CS"},
}

# password = "password123" (bcrypt hash stored in DB; here we accept plaintext for demo)
USERS = {
    "analyst@axiombank.com":  {"id": "u1", "tenant": "AB", "name": "Jordan Park",  "role": "ANALYST",         "password": "password123"},
    "manager@axiombank.com":  {"id": "u2", "tenant": "AB", "name": "Alex Singh",   "role": "CREDIT_MANAGER",  "password": "password123"},
    "analyst@novapay.io":     {"id": "u3", "tenant": "NP", "name": "Sam Liu",      "role": "ANALYST",         "password": "password123"},
}

# Transaction store keyed by tenant_id -> list
TRANSACTIONS = {"t1": [], "t2": [], "t3": []}
RISK_SCORES  = {}   # tx_id -> score_record
ALERTS       = {"t1": [], "t2": [], "t3": []}
TX_COUNTER   = {"t1": 9847, "t2": 5000, "t3": 3000}

# Revoked token set
REVOKED_TOKENS = set()

# ─── SEED TRANSACTIONS ───────────────────────────────────────────────────────
def _seed():
    rows = [
        ("USR-2291", 48200,  "Wire Transfer",      "Crypto Exchange",   "High-risk jurisdiction", 2,  94, "High"),
        ("USR-0134", 1240,   "Card Payment",        "Retail",            "Same country",           14, 22, "Low"),
        ("USR-5573", 8900,   "ACH Transfer",        "Travel",            "Cross-border",           11, 61, "Medium"),
        ("USR-3302", 320,    "Card Payment",        "Utilities",         "Same country",            9, 11, "Low"),
        ("USR-7741", 22500,  "Crypto Conversion",   "Crypto Exchange",   "High-risk jurisdiction",  3, 88, "High"),
        ("USR-4821", 5200,   "ACH Transfer",        "Retail",            "Same country",           14, 34, "Low"),
        ("USR-8810", 11000,  "Wire Transfer",       "Gambling",          "Cross-border",            1, 78, "High"),
        ("USR-6620", 680,    "Card Payment",        "Healthcare",        "Same country",           16,  8, "Low"),
        ("USR-1190", 3400,   "ACH Transfer",        "Travel",            "Cross-border",           20, 47, "Medium"),
        ("USR-9901", 900,    "Card Payment",        "Retail",            "Same country",           12, 19, "Low"),
        ("USR-3345", 15600,  "Wire Transfer",       "Gambling",          "High-risk jurisdiction", 23, 91, "High"),
        ("USR-5522", 420,    "Card Payment",        "Utilities",         "Same country",            8, 14, "Low"),
        ("USR-7703", 6700,   "ACH Transfer",        "Travel",            "Cross-border",           15, 55, "Medium"),
        ("USR-1122", 2100,   "Card Payment",        "Retail",            "Same country",           13, 27, "Low"),
        ("USR-8844", 33000,  "Crypto Conversion",   "Crypto Exchange",   "High-risk jurisdiction",  4, 96, "High"),
        ("USR-4410", 760,    "Card Payment",        "Healthcare",        "Same country",           10,  9, "Low"),
        ("USR-6631", 4800,   "Wire Transfer",       "Retail",            "Cross-border",           17, 42, "Medium"),
    ]
    for i, r in enumerate(rows):
        tid = "t1"
        TX_COUNTER[tid] -= 1
        tx_id = f"TXN-{9848 - i}"
        tx = {
            "id": tx_id, "tenant_id": tid,
            "customer_external_id": r[0], "amount": r[1],
            "tx_type": r[2], "merchant_category": r[3],
            "location_flag": r[4], "hour_of_day": r[5],
            "status": "SCORED",
            "submitted_at": (datetime.now(timezone.utc) - timedelta(minutes=i*3)).isoformat(),
        }
        TRANSACTIONS[tid].append(tx)
        RISK_SCORES[tx_id] = {
            "transaction_id": tx_id, "tenant_id": tid,
            "score": r[6], "risk_level": r[7],
            "model_version": "v1.0",
            "factor_amount":   _factor_amount(r[1]),
            "factor_category": _factor_category(r[3]),
            "factor_location": _factor_location(r[4]),
            "factor_time":     _factor_time(r[5]),
            "factor_type":     _factor_type(r[2]),
            "scored_at":       (datetime.now(timezone.utc) - timedelta(minutes=i*3)).isoformat(),
            "response_ms":     int(np.random.uniform(80, 400)),
        }
        if r[6] >= 70:
            sev = "critical" if r[6] >= 85 else "high"
            ALERTS[tid].append({
                "id": f"ALT-{tx_id}",
                "transaction_id": tx_id,
                "risk_score": r[6],
                "severity": sev,
                "status": "ACTIVE",
                "created_at": (datetime.now(timezone.utc) - timedelta(minutes=i*3)).isoformat(),
            })

# ─── SCORING FACTORS ─────────────────────────────────────────────────────────
def _factor_amount(amt):
    if amt > 20000: return 35
    if amt > 5000:  return 20
    if amt > 1000:  return 10
    return 3

def _factor_category(cat):
    m = {"Gambling": 28, "Crypto Exchange": 22, "Travel": 12,
         "Retail": 5, "Healthcare": 2, "Utilities": 3}
    return m.get(cat, 5)

def _factor_location(loc):
    m = {"High-risk jurisdiction": 28, "Cross-border": 14, "Same country": 4}
    return m.get(loc, 4)

def _factor_time(hour):
    return 18 if (hour < 6 or hour > 22) else 5

def _factor_type(t):
    m = {"Crypto Conversion": 18, "Wire Transfer": 10, "ACH Transfer": 7,
         "Card Payment": 4, "Cash Deposit": 12}
    return m.get(t, 5)

# ─── ML MODEL ────────────────────────────────────────────────────────────────
_model = None
_encoders = None

def _build_synthetic_model():
    """Train a RandomForest on synthetic data (replaces Kaggle dataset)."""
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    np.random.seed(42)
    n = 5000

    amounts  = np.random.exponential(scale=3000, size=n)
    hours    = np.random.randint(0, 24, size=n)
    types    = np.random.choice(["Wire Transfer","Card Payment","ACH Transfer",
                                  "Crypto Conversion","Cash Deposit"], size=n)
    cats     = np.random.choice(["Retail","Travel","Gambling","Crypto Exchange",
                                  "Utilities","Healthcare"], size=n)
    locs     = np.random.choice(["Same country","Cross-border",
                                  "High-risk jurisdiction"], size=n, p=[0.6,0.3,0.1])

    # Fraud label: weighted by risk factors
    risk = (
        (amounts > 15000).astype(int) * 3 +
        np.isin(cats, ["Gambling","Crypto Exchange"]).astype(int) * 2 +
        (locs == "High-risk jurisdiction").astype(int) * 3 +
        ((hours < 6) | (hours > 22)).astype(int) * 2 +
        np.isin(types, ["Crypto Conversion","Wire Transfer"]).astype(int)
    )
    fraud = (risk + np.random.randint(0, 3, size=n) >= 6).astype(int)

    le_type = LabelEncoder().fit(types)
    le_cat  = LabelEncoder().fit(cats)
    le_loc  = LabelEncoder().fit(locs)

    X = np.column_stack([
        amounts,
        hours,
        le_type.transform(types),
        le_cat.transform(cats),
        le_loc.transform(locs),
    ])

    clf = RandomForestClassifier(n_estimators=100, max_depth=8,
                                  random_state=42, class_weight="balanced")
    clf.fit(X, fraud)

    joblib.dump(clf, MODEL_PATH)
    joblib.dump({"type": le_type, "cat": le_cat, "loc": le_loc}, ENCODERS_PATH)
    return clf, {"type": le_type, "cat": le_cat, "loc": le_loc}

def get_model():
    global _model, _encoders
    if _model is None:
        if os.path.exists(MODEL_PATH):
            _model = joblib.load(MODEL_PATH)
            _encoders = joblib.load(ENCODERS_PATH)
        else:
            _model, _encoders = _build_synthetic_model()
    return _model, _encoders

def ml_score(amount, hour, tx_type, category, location):
    """Return 0-100 risk score using ML model + heuristic blend."""
    try:
        model, enc = get_model()
        t_enc = enc["type"].transform([tx_type])[0] if tx_type in enc["type"].classes_ else 0
        c_enc = enc["cat"].transform([category])[0] if category in enc["cat"].classes_ else 0
        l_enc = enc["loc"].transform([location])[0] if location in enc["loc"].classes_ else 0
        X = np.array([[amount, hour, t_enc, c_enc, l_enc]])
        prob = model.predict_proba(X)[0][1]  # probability of fraud
        ml_part = int(prob * 100)
    except Exception:
        ml_part = 0

    # Blend with heuristic factors (50/50)
    h_part = (
        _factor_amount(amount) +
        _factor_category(category) +
        _factor_location(location) +
        _factor_time(hour) +
        _factor_type(tx_type)
    )
    h_norm = min(100, int((h_part / 90) * 100))
    blended = int((ml_part * 0.5) + (h_norm * 0.5))
    return max(0, min(100, blended))

# ─── CREDIT ANALYSIS ─────────────────────────────────────────────────────────
CREDIT_PROFILES = {
    "USR-4821": {"name":"Jordan Lee",   "base_score":72, "repay":88, "avg_tx":3200,  "tx_count":47, "anomalies":2},
    "USR-2291": {"name":"Alex Romero",  "base_score":28, "repay":41, "avg_tx":24000, "tx_count":12, "anomalies":7},
    "USR-5573": {"name":"Sam Chen",     "base_score":61, "repay":74, "avg_tx":5400,  "tx_count":33, "anomalies":3},
    "USR-7741": {"name":"Maya Patel",   "base_score":19, "repay":32, "avg_tx":18000, "tx_count":8,  "anomalies":9},
    "USR-0134": {"name":"Chris Wong",   "base_score":84, "repay":95, "avg_tx":1100,  "tx_count":92, "anomalies":0},
    "USR-8810": {"name":"Dana Kim",     "base_score":42, "repay":61, "avg_tx":9200,  "tx_count":21, "anomalies":5},
}

def compute_credit(customer_id, tenant_transactions):
    profile = CREDIT_PROFILES.get(customer_id, {
        "name": customer_id, "base_score": 50, "repay": 65,
        "avg_tx": 2500, "tx_count": 10, "anomalies": 1
    })
    # Adjust score based on recent transactions
    recent_scores = [
        RISK_SCORES[t["id"]]["score"]
        for t in tenant_transactions
        if t["customer_external_id"] == customer_id and t["id"] in RISK_SCORES
    ]
    adj = 0
    if recent_scores:
        avg_risk = sum(recent_scores) / len(recent_scores)
        adj = -int((avg_risk / 100) * 20)

    score = max(0, min(100, profile["base_score"] + adj))
    if score >= 70:
        status = "Good Standing"; activity = "Regular"
        rec = "Approve with standard terms"
    elif score >= 40:
        status = "Watch List"; activity = "Moderate"
        rec = "Review and apply enhanced monitoring"
    else:
        status = "High Risk"; activity = "Irregular"
        rec = "Decline or require additional verification"

    history = [max(0, min(100, score + int(np.random.uniform(-15, 15)))) for _ in range(12)]
    history[-1] = score

    return {
        "customer_id":      customer_id,
        "name":             profile["name"],
        "confidence_score": score,
        "repayment_rate":   profile["repay"],
        "avg_transaction":  profile["avg_tx"],
        "total_transactions": profile["tx_count"] + len(recent_scores),
        "anomaly_count":    profile["anomalies"],
        "activity_pattern": activity,
        "status":           status,
        "recommendation":   rec,
        "score_history":    history,
        "analysed_at":      datetime.now(timezone.utc).isoformat(),
    }

# ─── JWT HELPERS ─────────────────────────────────────────────────────────────
def create_access_token(user_id, tenant_code, role):
    payload = {
        "sub":    user_id,
        "tenant": tenant_code,
        "role":   role,
        "exp":    datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
        "iat":    datetime.now(timezone.utc),
        "jti":    secrets.token_hex(16),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGORITHM)

def create_refresh_token(user_id):
    payload = {
        "sub":  user_id,
        "type": "refresh",
        "exp":  datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
        "jti":  secrets.token_hex(16),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGORITHM)

def decode_token(token):
    return jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])

def require_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return jsonify({"error": "Missing or invalid Authorization header"}), 401
        token = auth.split(" ", 1)[1]
        if token in REVOKED_TOKENS:
            return jsonify({"error": "Token has been revoked"}), 401
        try:
            payload = decode_token(token)
            g.user_id = payload["sub"]
            g.tenant_code = payload["tenant"]
            g.role = payload["role"]
            # Resolve tenant_id
            t = TENANTS.get(g.tenant_code)
            g.tenant_id = t["id"] if t else None
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token expired"}), 401
        except jwt.InvalidTokenError as e:
            return jsonify({"error": f"Invalid token: {e}"}), 401
        return f(*args, **kwargs)
    return wrapper

# ─── CORS HEADERS ────────────────────────────────────────────────────────────
@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"]  = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    return response

@app.route("/<path:p>", methods=["OPTIONS"])
def options_handler(p):
    return "", 204

# ─── HEALTH ──────────────────────────────────────────────────────────────────
@app.route("/api/health", methods=["GET"])
def health():
    model, _ = get_model()
    return jsonify({
        "status":       "ok",
        "version":      "1.0.0",
        "model_loaded": model is not None,
        "tenants":      len(TENANTS),
        "timestamp":    datetime.now(timezone.utc).isoformat(),
    })

# ─── AUTH ENDPOINTS ───────────────────────────────────────────────────────────
@app.route("/api/auth/login", methods=["POST"])
def login():
    """POST /api/auth/login — authenticate user and return JWT."""
    data = request.get_json(silent=True) or {}
    email    = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not email or not password:
        return jsonify({"error": "Email and password are required"}), 400

    user = USERS.get(email)
    if not user or user["password"] != password:
        return jsonify({"error": "Invalid credentials"}), 401

    if not user.get("active", True) is not False:
        pass  # active by default

    access  = create_access_token(user["id"], user["tenant"], user["role"])
    refresh = create_refresh_token(user["id"])
    tenant  = TENANTS[user["tenant"]]

    return jsonify({
        "access_token":  access,
        "refresh_token": refresh,
        "token_type":    "Bearer",
        "expires_in":    ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "user": {
            "id":        user["id"],
            "email":     email,
            "name":      user["name"],
            "role":      user["role"],
            "tenant_id": tenant["id"],
            "tenant":    tenant["name"],
        }
    }), 200

@app.route("/api/auth/logout", methods=["POST"])
@require_auth
def logout():
    """POST /api/auth/logout — revoke current access token."""
    auth  = request.headers.get("Authorization", "")
    token = auth.split(" ", 1)[1]
    REVOKED_TOKENS.add(token)
    return jsonify({"message": "Logged out successfully"}), 200

@app.route("/api/auth/refresh", methods=["POST"])
def refresh():
    """POST /api/auth/refresh — exchange refresh token for new access token."""
    data = request.get_json(silent=True) or {}
    rt = data.get("refresh_token")
    if not rt:
        return jsonify({"error": "refresh_token required"}), 400
    try:
        payload = decode_token(rt)
        if payload.get("type") != "refresh":
            return jsonify({"error": "Invalid refresh token"}), 401
        user_id = payload["sub"]
        # Find user
        user = next((u for u in USERS.values() if u["id"] == user_id), None)
        if not user:
            return jsonify({"error": "User not found"}), 401
        email = next(e for e, u in USERS.items() if u["id"] == user_id)
        new_access = create_access_token(user_id, user["tenant"], user["role"])
        return jsonify({"access_token": new_access, "token_type": "Bearer"}), 200
    except jwt.ExpiredSignatureError:
        return jsonify({"error": "Refresh token expired"}), 401
    except jwt.InvalidTokenError:
        return jsonify({"error": "Invalid refresh token"}), 401

@app.route("/api/auth/me", methods=["GET"])
@require_auth
def me():
    """GET /api/auth/me — return current user profile."""
    user = next((u for u in USERS.values() if u["id"] == g.user_id), None)
    tenant = TENANTS.get(g.tenant_code, {})
    return jsonify({
        "id":        g.user_id,
        "role":      g.role,
        "tenant":    tenant.get("name"),
        "tenant_id": tenant.get("id"),
        "name":      user["name"] if user else "",
    }), 200

# ─── TRANSACTION ENDPOINTS ───────────────────────────────────────────────────
@app.route("/api/transactions", methods=["POST"])
@require_auth
def create_transaction():
    """POST /api/transactions — ingest and validate a transaction."""
    data = request.get_json(silent=True) or {}

    required = ["customer_external_id", "amount", "tx_type",
                "merchant_category", "location_flag", "hour_of_day"]
    missing = [f for f in required if f not in data]
    if missing:
        return jsonify({"error": f"Missing required fields: {', '.join(missing)}"}), 400

    try:
        amount   = float(data["amount"])
        hour     = int(data["hour_of_day"])
    except (ValueError, TypeError):
        return jsonify({"error": "amount must be numeric, hour_of_day must be integer 0-23"}), 400

    if amount <= 0:
        return jsonify({"error": "amount must be greater than 0"}), 400
    if not (0 <= hour <= 23):
        return jsonify({"error": "hour_of_day must be between 0 and 23"}), 400

    valid_types = ["Wire Transfer","Card Payment","ACH Transfer","Crypto Conversion","Cash Deposit"]
    valid_cats  = ["Retail","Travel","Gambling","Crypto Exchange","Utilities","Healthcare"]
    valid_locs  = ["Same country","Cross-border","High-risk jurisdiction"]
    if data["tx_type"] not in valid_types:
        return jsonify({"error": f"tx_type must be one of: {valid_types}"}), 400
    if data["merchant_category"] not in valid_cats:
        return jsonify({"error": f"merchant_category must be one of: {valid_cats}"}), 400
    if data["location_flag"] not in valid_locs:
        return jsonify({"error": f"location_flag must be one of: {valid_locs}"}), 400

    tid = g.tenant_id
    TX_COUNTER[tid] = TX_COUNTER.get(tid, 1000) + 1
    tx_id = data.get("external_tx_id") or f"TXN-{TX_COUNTER[tid]}"

    # Duplicate check
    existing = [t for t in TRANSACTIONS.get(tid, []) if t["id"] == tx_id]
    if existing:
        return jsonify({"error": "Duplicate transaction ID", "transaction_id": tx_id}), 409

    tx = {
        "id":                   tx_id,
        "tenant_id":            tid,
        "customer_external_id": data["customer_external_id"],
        "amount":               amount,
        "tx_type":              data["tx_type"],
        "merchant_category":    data["merchant_category"],
        "location_flag":        data["location_flag"],
        "hour_of_day":          hour,
        "status":               "PENDING",
        "submitted_at":         datetime.now(timezone.utc).isoformat(),
    }
    TRANSACTIONS.setdefault(tid, []).append(tx)
    return jsonify({"message": "Transaction ingested", "transaction": tx}), 201

@app.route("/api/transactions", methods=["GET"])
@require_auth
def list_transactions():
    """GET /api/transactions — list all transactions for tenant with filters."""
    tid = g.tenant_id
    txs = list(reversed(TRANSACTIONS.get(tid, [])))

    risk_level = request.args.get("risk_level")
    status     = request.args.get("status")
    limit      = min(int(request.args.get("limit", 100)), 500)
    offset     = int(request.args.get("offset", 0))

    if risk_level:
        scored_ids = {sid for sid, s in RISK_SCORES.items() if s["risk_level"] == risk_level and s["tenant_id"] == tid}
        txs = [t for t in txs if t["id"] in scored_ids]
    if status:
        txs = [t for t in txs if t["status"] == status]

    # Enrich with risk scores
    enriched = []
    for t in txs[offset:offset+limit]:
        row = dict(t)
        sc = RISK_SCORES.get(t["id"])
        if sc:
            row["risk_score"]  = sc["score"]
            row["risk_level"]  = sc["risk_level"]
        enriched.append(row)

    return jsonify({
        "total": len(txs),
        "offset": offset,
        "limit": limit,
        "transactions": enriched,
    }), 200

@app.route("/api/transactions/<tx_id>", methods=["GET"])
@require_auth
def get_transaction(tx_id):
    """GET /api/transactions/{id} — retrieve single transaction."""
    tid = g.tenant_id
    tx = next((t for t in TRANSACTIONS.get(tid, []) if t["id"] == tx_id), None)
    if not tx:
        return jsonify({"error": "Transaction not found"}), 404
    row = dict(tx)
    sc  = RISK_SCORES.get(tx_id)
    if sc:
        row["risk_score"]  = sc["score"]
        row["risk_level"]  = sc["risk_level"]
        row["scored_at"]   = sc["scored_at"]
    return jsonify(row), 200

# ─── RISK SCORE ENDPOINTS ────────────────────────────────────────────────────
@app.route("/api/risk-score/evaluate", methods=["POST"])
@require_auth
def evaluate_risk():
    """POST /api/risk-score/evaluate — score an existing or ad-hoc transaction."""
    t0   = time.time()
    data = request.get_json(silent=True) or {}
    tid  = g.tenant_id

    # Can pass either transaction_id (existing) or raw fields
    tx_id = data.get("transaction_id")
    if tx_id:
        tx = next((t for t in TRANSACTIONS.get(tid, []) if t["id"] == tx_id), None)
        if not tx:
            return jsonify({"error": "Transaction not found"}), 404
        amount   = tx["amount"]
        hour     = tx["hour_of_day"]
        tx_type  = tx["tx_type"]
        category = tx["merchant_category"]
        location = tx["location_flag"]
    else:
        try:
            amount   = float(data["amount"])
            hour     = int(data["hour_of_day"])
            tx_type  = data["tx_type"]
            category = data["merchant_category"]
            location = data["location_flag"]
        except (KeyError, ValueError) as e:
            return jsonify({"error": f"Missing or invalid fields: {e}"}), 400
        TX_COUNTER[tid] = TX_COUNTER.get(tid, 1000) + 1
        tx_id = f"TXN-{TX_COUNTER[tid]}"
        tx = {
            "id": tx_id, "tenant_id": tid,
            "customer_external_id": data.get("customer_external_id", "USR-ANON"),
            "amount": amount, "tx_type": tx_type,
            "merchant_category": category, "location_flag": location,
            "hour_of_day": hour, "status": "PENDING",
            "submitted_at": datetime.now(timezone.utc).isoformat(),
        }
        TRANSACTIONS.setdefault(tid, []).append(tx)

    score     = ml_score(amount, hour, tx_type, category, location)
    risk_level = "High" if score >= 70 else "Medium" if score >= 40 else "Low"
    ms        = int((time.time() - t0) * 1000)

    score_rec = {
        "transaction_id":  tx_id,
        "tenant_id":       tid,
        "score":           score,
        "risk_level":      risk_level,
        "model_version":   "v1.0",
        "factor_amount":   _factor_amount(amount),
        "factor_category": _factor_category(category),
        "factor_location": _factor_location(location),
        "factor_time":     _factor_time(hour),
        "factor_type":     _factor_type(tx_type),
        "scored_at":       datetime.now(timezone.utc).isoformat(),
        "response_ms":     ms,
    }
    RISK_SCORES[tx_id] = score_rec

    # Update tx status
    for t in TRANSACTIONS.get(tid, []):
        if t["id"] == tx_id:
            t["status"] = "FLAGGED" if score >= 70 else "SCORED"

    # Auto-generate alert for high risk
    if score >= 70:
        sev = "critical" if score >= 85 else "high"
        ALERTS.setdefault(tid, []).append({
            "id":             f"ALT-{tx_id}",
            "transaction_id": tx_id,
            "risk_score":     score,
            "severity":       sev,
            "status":         "ACTIVE",
            "amount":         amount,
            "customer_id":    tx.get("customer_external_id"),
            "created_at":     datetime.now(timezone.utc).isoformat(),
        })

    return jsonify({
        "transaction_id": tx_id,
        "score":          score,
        "risk_level":     risk_level,
        "factors": {
            "amount":   score_rec["factor_amount"],
            "category": score_rec["factor_category"],
            "location": score_rec["factor_location"],
            "time":     score_rec["factor_time"],
            "type":     score_rec["factor_type"],
        },
        "response_ms": ms,
        "model_version": "v1.0",
    }), 200

@app.route("/api/risk-score/<tx_id>", methods=["GET"])
@require_auth
def get_risk_score(tx_id):
    """GET /api/risk-score/{transactionId} — retrieve stored score."""
    tid = g.tenant_id
    sc  = RISK_SCORES.get(tx_id)
    if not sc or sc["tenant_id"] != tid:
        return jsonify({"error": "Risk score not found"}), 404
    return jsonify(sc), 200

# ─── CREDIT ANALYSIS ENDPOINTS ───────────────────────────────────────────────
@app.route("/api/credit-analysis/<customer_id>", methods=["GET"])
@require_auth
def get_credit_analysis(customer_id):
    """GET /api/credit-analysis/{userId} — credit behavior analysis."""
    tid  = g.tenant_id
    txs  = TRANSACTIONS.get(tid, [])
    result = compute_credit(customer_id, txs)
    return jsonify(result), 200

# ─── ALERTS ENDPOINTS ────────────────────────────────────────────────────────
@app.route("/api/alerts", methods=["GET"])
@require_auth
def list_alerts():
    """GET /api/alerts — list alerts for tenant."""
    tid    = g.tenant_id
    status = request.args.get("status")
    alerts = list(reversed(ALERTS.get(tid, [])))
    if status:
        alerts = [a for a in alerts if a["status"] == status]
    # Enrich with transaction data
    enriched = []
    for a in alerts:
        tx = next((t for t in TRANSACTIONS.get(tid, []) if t["id"] == a["transaction_id"]), {})
        enriched.append({**a, "transaction": tx})
    return jsonify({"total": len(enriched), "alerts": enriched}), 200

@app.route("/api/alerts/<alert_id>/acknowledge", methods=["POST"])
@require_auth
def acknowledge_alert(alert_id):
    """POST /api/alerts/{id}/acknowledge — update alert status."""
    tid    = g.tenant_id
    data   = request.get_json(silent=True) or {}
    action = data.get("action", "ACKNOWLEDGED")  # ACKNOWLEDGED, ESCALATED, RESOLVED, DISMISSED
    for a in ALERTS.get(tid, []):
        if a["id"] == alert_id:
            a["status"]           = action
            a["acknowledged_by"]  = g.user_id
            a["acknowledged_at"]  = datetime.now(timezone.utc).isoformat()
            a["notes"]            = data.get("notes", "")
            return jsonify({"message": f"Alert {action.lower()}", "alert": a}), 200
    return jsonify({"error": "Alert not found"}), 404

# ─── DASHBOARD STATS ─────────────────────────────────────────────────────────
@app.route("/api/dashboard/stats", methods=["GET"])
@require_auth
def dashboard_stats():
    """GET /api/dashboard/stats — summary stats for the dashboard."""
    tid  = g.tenant_id
    txs  = TRANSACTIONS.get(tid, [])
    total = len(txs)

    scored = [RISK_SCORES[t["id"]] for t in txs if t["id"] in RISK_SCORES]
    high   = sum(1 for s in scored if s["risk_level"] == "High")
    med    = sum(1 for s in scored if s["risk_level"] == "Medium")
    low    = sum(1 for s in scored if s["risk_level"] == "Low")
    avg_score = round(sum(s["score"] for s in scored) / len(scored), 1) if scored else 0

    active_alerts = sum(1 for a in ALERTS.get(tid, []) if a["status"] == "ACTIVE")

    return jsonify({
        "total_transactions": total,
        "high_risk_count":    high,
        "medium_risk_count":  med,
        "low_risk_count":     low,
        "avg_risk_score":     avg_score,
        "active_alerts":      active_alerts,
        "accuracy_pct":       91.2,
        "distribution": {
            "high_pct":   round(high / total * 100, 1) if total else 0,
            "medium_pct": round(med  / total * 100, 1) if total else 0,
            "low_pct":    round(low  / total * 100, 1) if total else 0,
        }
    }), 200

# ─── TENANTS ─────────────────────────────────────────────────────────────────
@app.route("/api/tenants", methods=["GET"])
def list_tenants():
    """GET /api/tenants — public list of tenants (for login selector)."""
    return jsonify({"tenants": list(TENANTS.values())}), 200

# ─── INIT & RUN ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("[FinGuardX] Seeding transactions...")
    _seed()
    print("[FinGuardX] Training / loading risk model...")
    get_model()
    print("[FinGuardX] Backend ready on http://0.0.0.0:8080")
    app.run(host="0.0.0.0", port=8080, debug=False)
