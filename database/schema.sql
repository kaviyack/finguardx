-- FinGuardX Database Schema
-- PostgreSQL 14+
-- Multi-tenant SaaS platform for transaction risk assessment

-- ─────────────────────────────────────────────
-- EXTENSIONS
-- ─────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ─────────────────────────────────────────────
-- TENANTS
-- ─────────────────────────────────────────────
CREATE TABLE tenants (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name        VARCHAR(100) NOT NULL UNIQUE,
    type        VARCHAR(50)  NOT NULL,  -- 'Bank', 'Fintech', 'Lending'
    code        VARCHAR(10)  NOT NULL UNIQUE,
    is_active   BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- ─────────────────────────────────────────────
-- USERS
-- ─────────────────────────────────────────────
CREATE TABLE users (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id       UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    email           VARCHAR(255) NOT NULL,
    password_hash   TEXT        NOT NULL,
    full_name       VARCHAR(100) NOT NULL,
    role            VARCHAR(30)  NOT NULL DEFAULT 'ANALYST', -- ANALYST, CREDIT_MANAGER, ADMIN
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    last_login      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, email)
);

-- ─────────────────────────────────────────────
-- CUSTOMER PROFILES (end-customers being scored)
-- ─────────────────────────────────────────────
CREATE TABLE customer_profiles (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id       UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    external_id     VARCHAR(50) NOT NULL,  -- USR-XXXX from client systems
    full_name       VARCHAR(100),
    email           VARCHAR(255),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, external_id)
);

-- ─────────────────────────────────────────────
-- TRANSACTIONS
-- ─────────────────────────────────────────────
CREATE TABLE transactions (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id           UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    external_tx_id      VARCHAR(50) NOT NULL,   -- TXN-XXXX
    customer_id         UUID        REFERENCES customer_profiles(id),
    customer_external_id VARCHAR(50) NOT NULL,
    amount              NUMERIC(15,2) NOT NULL CHECK (amount > 0),
    tx_type             VARCHAR(50)  NOT NULL,  -- Wire Transfer, Card Payment, etc.
    merchant_category   VARCHAR(50)  NOT NULL,
    location_flag       VARCHAR(50)  NOT NULL,  -- Same country, Cross-border, High-risk jurisdiction
    hour_of_day         SMALLINT     NOT NULL CHECK (hour_of_day BETWEEN 0 AND 23),
    status              VARCHAR(20)  NOT NULL DEFAULT 'PENDING', -- PENDING, SCORED, FLAGGED, REVIEWED
    is_duplicate        BOOLEAN      NOT NULL DEFAULT FALSE,
    submitted_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, external_tx_id)
);

-- ─────────────────────────────────────────────
-- RISK SCORES
-- ─────────────────────────────────────────────
CREATE TABLE risk_scores (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    transaction_id      UUID        NOT NULL UNIQUE REFERENCES transactions(id) ON DELETE CASCADE,
    tenant_id           UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    score               SMALLINT    NOT NULL CHECK (score BETWEEN 0 AND 100),
    risk_level          VARCHAR(10) NOT NULL, -- Low, Medium, High
    model_version       VARCHAR(20) NOT NULL DEFAULT 'v1.0',
    factor_amount       SMALLINT,
    factor_category     SMALLINT,
    factor_location     SMALLINT,
    factor_time         SMALLINT,
    factor_type         SMALLINT,
    scored_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    response_ms         INTEGER
);

-- ─────────────────────────────────────────────
-- ALERTS
-- ─────────────────────────────────────────────
CREATE TABLE alerts (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id       UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    transaction_id  UUID        NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
    risk_score_id   UUID        REFERENCES risk_scores(id),
    severity        VARCHAR(20) NOT NULL, -- critical, high
    status          VARCHAR(20) NOT NULL DEFAULT 'ACTIVE', -- ACTIVE, ACKNOWLEDGED, ESCALATED, RESOLVED, DISMISSED
    acknowledged_by UUID        REFERENCES users(id),
    acknowledged_at TIMESTAMPTZ,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─────────────────────────────────────────────
-- CREDIT ANALYSES
-- ─────────────────────────────────────────────
CREATE TABLE credit_analyses (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id           UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    customer_id         UUID        NOT NULL REFERENCES customer_profiles(id),
    confidence_score    SMALLINT    NOT NULL CHECK (confidence_score BETWEEN 0 AND 100),
    repayment_rate      NUMERIC(5,2),
    avg_transaction     NUMERIC(15,2),
    total_transactions  INTEGER,
    anomaly_count       INTEGER,
    activity_pattern    VARCHAR(20), -- Regular, Moderate, Irregular
    status              VARCHAR(20), -- Good Standing, Watch List, High Risk
    recommendation      TEXT,
    analysed_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- ─────────────────────────────────────────────
-- REFRESH TOKENS
-- ─────────────────────────────────────────────
CREATE TABLE refresh_tokens (
    id          UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id     UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash  TEXT        NOT NULL UNIQUE,
    expires_at  TIMESTAMPTZ NOT NULL,
    revoked     BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─────────────────────────────────────────────
-- INDEXES
-- ─────────────────────────────────────────────
CREATE INDEX idx_transactions_tenant     ON transactions(tenant_id);
CREATE INDEX idx_transactions_customer   ON transactions(customer_external_id);
CREATE INDEX idx_transactions_submitted  ON transactions(submitted_at DESC);
CREATE INDEX idx_transactions_status     ON transactions(status);
CREATE INDEX idx_risk_scores_tenant      ON risk_scores(tenant_id);
CREATE INDEX idx_risk_scores_level       ON risk_scores(risk_level);
CREATE INDEX idx_risk_scores_scored_at   ON risk_scores(scored_at DESC);
CREATE INDEX idx_alerts_tenant_status    ON alerts(tenant_id, status);
CREATE INDEX idx_users_tenant            ON users(tenant_id);

-- ─────────────────────────────────────────────
-- SEED DATA
-- ─────────────────────────────────────────────
INSERT INTO tenants (id, name, type, code) VALUES
  ('11111111-1111-1111-1111-111111111111', 'Axiom Bank',    'Commercial Bank',  'AB'),
  ('22222222-2222-2222-2222-222222222222', 'NovaPay',        'Fintech',          'NP'),
  ('33333333-3333-3333-3333-333333333333', 'CreditSphere',   'Lending Platform', 'CS');

-- Users (passwords are bcrypt of 'password123')
INSERT INTO users (tenant_id, email, password_hash, full_name, role) VALUES
  ('11111111-1111-1111-1111-111111111111', 'analyst@axiombank.com',
   '$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW', 'Jordan Park', 'ANALYST'),
  ('11111111-1111-1111-1111-111111111111', 'manager@axiombank.com',
   '$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW', 'Alex Singh', 'CREDIT_MANAGER'),
  ('22222222-2222-2222-2222-222222222222', 'analyst@novapay.io',
   '$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW', 'Sam Liu', 'ANALYST');
