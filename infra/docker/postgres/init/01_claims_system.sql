-- ============================================================================
-- Stage 2b: the "claims system" Polaris extracts from.
--
-- Plays the operational database the claims app writes to. Runs once, the
-- first time the polaris-postgres container starts with an empty volume.
--
-- Timestamps are TIMESTAMP (no time zone) and hold UTC. The extract compares
-- them to a watermark, and mixing zones would skip or repeat an hour at
-- every daylight-saving change.
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS claims_system;

CREATE TABLE IF NOT EXISTS claims_system.customers (
    customer_id     TEXT PRIMARY KEY,
    first_name      TEXT NOT NULL,
    last_name       TEXT NOT NULL,
    ssn             TEXT NOT NULL,
    dob             DATE NOT NULL,
    email           TEXT,
    phone           TEXT,
    address_line1   TEXT,
    city            TEXT,
    province        TEXT,
    postal_code     TEXT,
    created_at      TIMESTAMP NOT NULL,
    updated_at      TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS claims_system.policies (
    policy_id       TEXT PRIMARY KEY,
    customer_id     TEXT NOT NULL REFERENCES claims_system.customers,
    product_type    TEXT NOT NULL,
    effective_date  DATE NOT NULL,
    expiry_date     DATE NOT NULL,
    annual_premium  NUMERIC(18, 2) NOT NULL,
    coverage_limit  NUMERIC(18, 2) NOT NULL,
    status          TEXT NOT NULL,
    created_at      TIMESTAMP NOT NULL,
    updated_at      TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS claims_system.claims (
    claim_id        TEXT PRIMARY KEY,
    claim_number    TEXT NOT NULL,
    policy_id       TEXT NOT NULL REFERENCES claims_system.policies,
    customer_id     TEXT NOT NULL REFERENCES claims_system.customers,
    product_type    TEXT NOT NULL,
    claim_type      TEXT NOT NULL,
    loss_date       DATE NOT NULL,
    report_date     DATE NOT NULL,
    claim_amount    NUMERIC(18, 2) NOT NULL,
    status          TEXT NOT NULL,
    is_fraud        BOOLEAN NOT NULL,
    fraud_score     NUMERIC(5, 3) NOT NULL,
    adjuster_id     TEXT NOT NULL,
    created_at      TIMESTAMP NOT NULL,
    updated_at      TIMESTAMP NOT NULL
);

-- Payments are insert-only: a payment is never edited, so created_at is the
-- change column for this table.
CREATE TABLE IF NOT EXISTS claims_system.claim_payments (
    payment_id      TEXT PRIMARY KEY,
    claim_id        TEXT NOT NULL REFERENCES claims_system.claims,
    payment_date    DATE NOT NULL,
    payment_amount  NUMERIC(18, 2) NOT NULL,
    payment_type    TEXT NOT NULL,
    created_at      TIMESTAMP NOT NULL
);

-- The extract asks "rows changed after X" every run. Without these indexes
-- that question scans the whole table, on the database the business runs on.
CREATE INDEX IF NOT EXISTS ix_customers_updated_at  ON claims_system.customers (updated_at);
CREATE INDEX IF NOT EXISTS ix_policies_updated_at   ON claims_system.policies (updated_at);
CREATE INDEX IF NOT EXISTS ix_claims_updated_at     ON claims_system.claims (updated_at);
CREATE INDEX IF NOT EXISTS ix_payments_created_at   ON claims_system.claim_payments (created_at);
