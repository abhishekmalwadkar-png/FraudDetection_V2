-- ==========================================================
-- DUMMY BANK PORTAL - FRAUD & SECURITY SCHEMA (V2)
-- Database: bank_fraud_portal
-- Includes: Full-Text Search (GIN), DB Audit Triggers, Table Partitioning
-- ==========================================================

-- Drop existing views and tables if they exist
DROP VIEW IF EXISTS v_customer_fraud_summary CASCADE;
DROP VIEW IF EXISTS v_fraud_tickets_full CASCADE;
DROP TABLE IF EXISTS audit_logs CASCADE;
DROP TABLE IF EXISTS transactions CASCADE;
DROP TABLE IF EXISTS fraud_tickets CASCADE;
DROP TABLE IF EXISTS customer_accounts CASCADE;
DROP TABLE IF EXISTS customers CASCADE;

-- 1. Customers Table (With Full-Text Search Vector)
CREATE TABLE customers (
    customer_id SERIAL PRIMARY KEY,
    customer_code VARCHAR(20) UNIQUE NOT NULL,
    customer_name VARCHAR(100) NOT NULL,
    full_name VARCHAR(100) NOT NULL,
    email VARCHAR(120) UNIQUE NOT NULL,
    phone VARCHAR(25) NOT NULL,
    address VARCHAR(200),
    city VARCHAR(80),
    state VARCHAR(80),
    country VARCHAR(60) DEFAULT 'India',
    kyc_status VARCHAR(20) DEFAULT 'VERIFIED',
    risk_tier VARCHAR(20) DEFAULT 'LOW', -- LOW, MEDIUM, HIGH, CRITICAL
    account_count INT DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    tsv_search tsvector GENERATED ALWAYS AS (
        to_tsvector('english', 
            coalesce(customer_name, '') || ' ' || 
            coalesce(customer_code, '') || ' ' || 
            coalesce(email, '') || ' ' || 
            coalesce(phone, '') || ' ' || 
            coalesce(city, '') || ' ' || 
            coalesce(state, '')
        )
    ) STORED
);

-- 2. Customer Accounts Table
CREATE TABLE customer_accounts (
    account_id SERIAL PRIMARY KEY,
    customer_id INT REFERENCES customers(customer_id) ON DELETE CASCADE,
    customer_name VARCHAR(100) NOT NULL,
    account_number VARCHAR(30) UNIQUE NOT NULL,
    account_type VARCHAR(40) NOT NULL, -- CHECKING, SAVINGS, BUSINESS, WEALTH_MANAGEMENT, CREDIT_CARD
    balance NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    currency VARCHAR(5) DEFAULT 'INR',
    status VARCHAR(20) DEFAULT 'ACTIVE', -- ACTIVE, FROZEN, RESTRICTED, CLOSED
    branch VARCHAR(100) NOT NULL,
    opened_date DATE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 3. Fraud Tickets Table (With FTS Column)
CREATE TABLE fraud_tickets (
    ticket_id SERIAL PRIMARY KEY,
    ticket_number VARCHAR(30) UNIQUE NOT NULL,
    customer_id INT REFERENCES customers(customer_id) ON DELETE CASCADE,
    customer_name VARCHAR(100) NOT NULL,
    account_number VARCHAR(30) NOT NULL,
    incident_type VARCHAR(80) NOT NULL,
    amount_involved NUMERIC(15, 2) NOT NULL,
    recovered_amount NUMERIC(15, 2) DEFAULT 0.00,
    incident_date TIMESTAMP NOT NULL,
    reported_channel VARCHAR(40) NOT NULL,
    severity VARCHAR(20) NOT NULL, -- CRITICAL, HIGH, MEDIUM, LOW
    status VARCHAR(30) NOT NULL DEFAULT 'UNDER_INVESTIGATION', -- OPEN, UNDER_INVESTIGATION, RESOLVED, ESCALATED, FROZEN, REJECTED
    assigned_investigator VARCHAR(80) NOT NULL,
    flagged_ip_or_location VARCHAR(120),
    suspect_entity VARCHAR(150),
    description TEXT NOT NULL,
    action_taken TEXT,
    resolution_notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    tsv_search tsvector GENERATED ALWAYS AS (
        to_tsvector('english', 
            coalesce(customer_name, '') || ' ' || 
            coalesce(account_number, '') || ' ' || 
            coalesce(incident_type, '') || ' ' || 
            coalesce(description, '') || ' ' || 
            coalesce(suspect_entity, '') || ' ' || 
            coalesce(flagged_ip_or_location, '')
        )
    ) STORED
);

-- 4. Transactions Table (Range Partitioned by txn_time)
CREATE TABLE transactions (
    txn_id SERIAL,
    txn_reference VARCHAR(40) NOT NULL,
    customer_id INT REFERENCES customers(customer_id) ON DELETE CASCADE,
    customer_name VARCHAR(100) NOT NULL,
    account_number VARCHAR(30) NOT NULL,
    amount NUMERIC(15, 2) NOT NULL,
    txn_type VARCHAR(40) NOT NULL,
    merchant_or_recipient VARCHAR(120) NOT NULL,
    channel VARCHAR(40) NOT NULL,
    ip_address VARCHAR(45),
    geo_location VARCHAR(100),
    is_fraud_flagged BOOLEAN DEFAULT FALSE,
    fraud_risk_score INT DEFAULT 15,
    status VARCHAR(30) DEFAULT 'COMPLETED',
    txn_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (txn_id, txn_time)
) PARTITION BY RANGE (txn_time);

-- Range Partitions
CREATE TABLE IF NOT EXISTS transactions_2025 PARTITION OF transactions
FOR VALUES FROM ('2025-01-01 00:00:00') TO ('2026-01-01 00:00:00');

CREATE TABLE IF NOT EXISTS transactions_2026_q1 PARTITION OF transactions
FOR VALUES FROM ('2026-01-01 00:00:00') TO ('2026-04-01 00:00:00');

CREATE TABLE IF NOT EXISTS transactions_2026_q2 PARTITION OF transactions
FOR VALUES FROM ('2026-04-01 00:00:00') TO ('2026-07-01 00:00:00');

CREATE TABLE IF NOT EXISTS transactions_2026_q3 PARTITION OF transactions
FOR VALUES FROM ('2026-07-01 00:00:00') TO ('2026-10-01 00:00:00');

CREATE TABLE IF NOT EXISTS transactions_2026_q4 PARTITION OF transactions
FOR VALUES FROM ('2026-10-01 00:00:00') TO ('2027-01-01 00:00:00');

CREATE TABLE IF NOT EXISTS transactions_default PARTITION OF transactions DEFAULT;

-- 5. Audit & Security Logs Table
CREATE TABLE audit_logs (
    log_id SERIAL PRIMARY KEY,
    ticket_number VARCHAR(30),
    customer_name VARCHAR(100),
    actor VARCHAR(80) NOT NULL,
    action VARCHAR(80) NOT NULL,
    details TEXT NOT NULL,
    ip_address VARCHAR(45),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ==========================================================
-- INDEXES FOR PERFORMANCE & FULL-TEXT SEARCH
-- ==========================================================
CREATE INDEX idx_fraud_tickets_customer ON fraud_tickets(customer_id);
CREATE INDEX idx_fraud_tickets_name ON fraud_tickets(customer_name);
CREATE INDEX idx_fraud_tickets_status ON fraud_tickets(status);
CREATE INDEX idx_fraud_tickets_severity ON fraud_tickets(severity);
CREATE INDEX idx_fraud_tickets_tsv ON fraud_tickets USING gin(tsv_search);

CREATE INDEX idx_customers_tsv ON customers USING gin(tsv_search);
CREATE INDEX idx_accounts_customer ON customer_accounts(customer_id);

CREATE INDEX idx_transactions_customer ON transactions(customer_id);
CREATE INDEX idx_transactions_time ON transactions(txn_time);
CREATE INDEX idx_transactions_flagged ON transactions(is_fraud_flagged);
CREATE INDEX idx_transactions_fts ON transactions 
USING gin(to_tsvector('english', coalesce(customer_name, '') || ' ' || coalesce(txn_reference, '') || ' ' || coalesce(account_number, '') || ' ' || coalesce(merchant_or_recipient, '') || ' ' || coalesce(ip_address, '')));

-- ==========================================================
-- AUTOMATED DATABASE AUDIT TRIGGER
-- ==========================================================
CREATE OR REPLACE FUNCTION fn_audit_fraud_tickets_log()
RETURNS TRIGGER AS $$
DECLARE
    v_actor VARCHAR(80);
    v_action VARCHAR(80);
    v_details TEXT;
BEGIN
    IF (TG_OP = 'INSERT') THEN
        v_actor := COALESCE(NEW.assigned_investigator, 'SYSTEM_INTAKE');
        v_action := 'TICKET_CREATED';
        v_details := 'New fraud complaint logged. Type: ' || NEW.incident_type || 
                     ', Amount: ₹' || NEW.amount_involved || 
                     ', Severity: ' || NEW.severity || 
                     ', Initial Status: ' || NEW.status;
        
        INSERT INTO audit_logs (ticket_number, customer_name, actor, action, details, ip_address, created_at)
        VALUES (NEW.ticket_number, NEW.customer_name, v_actor, v_action, v_details, COALESCE(NEW.flagged_ip_or_location, '10.0.0.1'), CURRENT_TIMESTAMP);
        
        RETURN NEW;
    ELSIF (TG_OP = 'UPDATE') THEN
        v_actor := COALESCE(NEW.assigned_investigator, OLD.assigned_investigator, 'STAFF_OPERATIONS');
        
        IF (OLD.status IS DISTINCT FROM NEW.status) THEN
            v_action := 'STATUS_CHANGED';
            v_details := 'Status updated from ' || OLD.status || ' to ' || NEW.status;
            IF (NEW.action_taken IS NOT NULL AND NEW.action_taken <> '') THEN
                v_details := v_details || '. Action: ' || NEW.action_taken;
            END IF;
        ELSIF (OLD.assigned_investigator IS DISTINCT FROM NEW.assigned_investigator) THEN
            v_action := 'INVESTIGATOR_REASSIGNED';
            v_details := 'Reassigned from ' || OLD.assigned_investigator || ' to ' || NEW.assigned_investigator;
        ELSIF (OLD.recovered_amount IS DISTINCT FROM NEW.recovered_amount) THEN
            v_action := 'FUNDS_RECOVERED';
            v_details := 'Recovered amount adjusted from ₹' || OLD.recovered_amount || ' to ₹' || NEW.recovered_amount;
        ELSE
            v_action := 'TICKET_MODIFIED';
            v_details := 'Complaint details updated. Severity: ' || NEW.severity;
        END IF;

        INSERT INTO audit_logs (ticket_number, customer_name, actor, action, details, ip_address, created_at)
        VALUES (NEW.ticket_number, NEW.customer_name, v_actor, v_action, v_details, COALESCE(NEW.flagged_ip_or_location, '10.0.0.1'), CURRENT_TIMESTAMP);
        
        RETURN NEW;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_fraud_tickets_audit ON fraud_tickets;
CREATE TRIGGER trg_fraud_tickets_audit
AFTER INSERT OR UPDATE ON fraud_tickets
FOR EACH ROW
EXECUTE FUNCTION fn_audit_fraud_tickets_log();

-- ==========================================================
-- CONVENIENT PGADMIN VIEWS
-- ==========================================================
CREATE VIEW v_fraud_tickets_full AS
SELECT 
    t.ticket_number,
    t.customer_name,
    c.customer_code,
    c.email,
    c.phone,
    t.account_number,
    t.incident_type,
    t.amount_involved,
    t.recovered_amount,
    t.severity,
    t.status,
    t.assigned_investigator,
    t.incident_date,
    t.description
FROM fraud_tickets t
JOIN customers c ON t.customer_id = c.customer_id;

CREATE VIEW v_customer_fraud_summary AS
SELECT 
    c.customer_id,
    c.customer_code,
    c.customer_name,
    c.email,
    c.phone,
    c.risk_tier,
    ca.account_number,
    ca.account_type,
    ca.balance,
    ca.status AS account_status,
    COUNT(ft.ticket_id) AS total_fraud_tickets,
    COALESCE(SUM(ft.amount_involved), 0) AS total_fraud_amount_flagged
FROM customers c
LEFT JOIN customer_accounts ca ON c.customer_id = ca.customer_id
LEFT JOIN fraud_tickets ft ON c.customer_id = ft.customer_id
GROUP BY c.customer_id, c.customer_code, c.customer_name, c.email, c.phone, c.risk_tier, ca.account_number, ca.account_type, ca.balance, ca.status;
