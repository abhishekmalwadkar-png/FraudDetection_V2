"""
PostgreSQL Database Migration Script (V2 Upgrade)
Applies:
1. Full-Text Search tsvector generated columns & GIN indexes
2. Automated Database Audit Logging Trigger on fraud_tickets
3. Table Partitioning by Range on transactions (txn_time)
"""

import sys
import pg8000.dbapi
from config import DB_HOST, DB_PORT, DB_USER, DB_PASS, DB_NAME

def get_connection():
    return pg8000.dbapi.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASS,
        database=DB_NAME
    )

def run_migration():
    print("=" * 60)
    print("Starting PostgreSQL Database Engineering Migration (V2)")
    print(f"Target Database: {DB_NAME} on {DB_HOST}:{DB_PORT}")
    print("=" * 60)

    conn = get_connection()
    conn.autocommit = True
    cursor = conn.cursor()

    try:
        # -------------------------------------------------------------
        # 1. Full-Text Search (tsvector & GIN Indexes)
        # -------------------------------------------------------------
        print("\n[Step 1/3] Configuring Full-Text Search (tsvector & GIN indexes)...")
        
        # 1a. fraud_tickets FTS column & GIN index
        cursor.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns 
                    WHERE table_name = 'fraud_tickets' AND column_name = 'tsv_search'
                ) THEN
                    ALTER TABLE fraud_tickets ADD COLUMN tsv_search tsvector 
                    GENERATED ALWAYS AS (
                        to_tsvector('english', 
                            coalesce(customer_name, '') || ' ' || 
                            coalesce(account_number, '') || ' ' || 
                            coalesce(incident_type, '') || ' ' || 
                            coalesce(description, '') || ' ' || 
                            coalesce(suspect_entity, '') || ' ' || 
                            coalesce(flagged_ip_or_location, '')
                        )
                    ) STORED;
                END IF;
            END $$;
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_fraud_tickets_tsv ON fraud_tickets USING gin(tsv_search);")
        print("  [OK] fraud_tickets tsv_search column and GIN index ready.")

        # 1b. customers FTS column & GIN index
        cursor.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns 
                    WHERE table_name = 'customers' AND column_name = 'tsv_search'
                ) THEN
                    ALTER TABLE customers ADD COLUMN tsv_search tsvector 
                    GENERATED ALWAYS AS (
                        to_tsvector('english', 
                            coalesce(customer_name, '') || ' ' || 
                            coalesce(customer_code, '') || ' ' || 
                            coalesce(email, '') || ' ' || 
                            coalesce(phone, '') || ' ' || 
                            coalesce(city, '') || ' ' || 
                            coalesce(state, '')
                        )
                    ) STORED;
                END IF;
            END $$;
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_customers_tsv ON customers USING gin(tsv_search);")
        print("  [OK] customers tsv_search column and GIN index ready.")

        # -------------------------------------------------------------
        # 2. Database Trigger for Immutable Audit Logging
        # -------------------------------------------------------------
        print("\n[Step 2/3] Setting up Database Triggers for Automated Audit Logging...")
        
        cursor.execute("""
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
        """)

        cursor.execute("DROP TRIGGER IF EXISTS trg_fraud_tickets_audit ON fraud_tickets;")
        cursor.execute("""
            CREATE TRIGGER trg_fraud_tickets_audit
            AFTER INSERT OR UPDATE ON fraud_tickets
            FOR EACH ROW
            EXECUTE FUNCTION fn_audit_fraud_tickets_log();
        """)
        print("  [OK] Database Trigger trg_fraud_tickets_audit and fn_audit_fraud_tickets_log active.")

        # -------------------------------------------------------------
        # 3. Table Partitioning by Range for Transactions (txn_time)
        # -------------------------------------------------------------
        print("\n[Step 3/3] Setting up Partitioned Table for Transactions (PARTITION BY RANGE)...")
        
        # Check if transactions table is already partitioned
        cursor.execute("""
            SELECT relkind FROM pg_class c 
            JOIN pg_namespace n ON n.oid = c.relnamespace 
            WHERE c.relname = 'transactions' AND n.nspname = 'public';
        """)
        res = cursor.fetchone()
        is_partitioned = res and res[0] == 'p'

        if not is_partitioned:
            print("  - Migrating transactions table to range partitioned schema...")
            # Backup existing data
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS transactions_backup AS 
                SELECT * FROM transactions;
            """)
            
            cursor.execute("DROP TABLE IF EXISTS transactions CASCADE;")
            
            # Create master partitioned table
            cursor.execute("""
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
            """)

            # Create partitions
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS transactions_2025 PARTITION OF transactions
                FOR VALUES FROM ('2025-01-01 00:00:00') TO ('2026-01-01 00:00:00');
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS transactions_2026_q1 PARTITION OF transactions
                FOR VALUES FROM ('2026-01-01 00:00:00') TO ('2026-04-01 00:00:00');
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS transactions_2026_q2 PARTITION OF transactions
                FOR VALUES FROM ('2026-04-01 00:00:00') TO ('2026-07-01 00:00:00');
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS transactions_2026_q3 PARTITION OF transactions
                FOR VALUES FROM ('2026-07-01 00:00:00') TO ('2026-10-01 00:00:00');
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS transactions_2026_q4 PARTITION OF transactions
                FOR VALUES FROM ('2026-10-01 00:00:00') TO ('2027-01-01 00:00:00');
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS transactions_default PARTITION OF transactions DEFAULT;
            """)

            # Restore data from backup
            cursor.execute("""
                INSERT INTO transactions (
                    txn_id, txn_reference, customer_id, customer_name, account_number,
                    amount, txn_type, merchant_or_recipient, channel, ip_address,
                    geo_location, is_fraud_flagged, fraud_risk_score, status, txn_time
                )
                SELECT 
                    txn_id, txn_reference, customer_id, customer_name, account_number,
                    amount, txn_type, merchant_or_recipient, channel, ip_address,
                    geo_location, is_fraud_flagged, fraud_risk_score, status, 
                    COALESCE(txn_time, CURRENT_TIMESTAMP)
                FROM transactions_backup;
            """)

            # Sync serial sequence
            cursor.execute("""
                SELECT setval(pg_get_serial_sequence('transactions', 'txn_id'), 
                              COALESCE((SELECT MAX(txn_id) FROM transactions), 1));
            """)
            
            cursor.execute("DROP TABLE IF EXISTS transactions_backup;")
            print("  [OK] Range partitioned table transactions created and data restored.")
        else:
            print("  [OK] transactions table is already partitioned.")

        # Create indexes on partitioned table
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_transactions_customer ON transactions(customer_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_transactions_time ON transactions(txn_time);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_transactions_flagged ON transactions(is_fraud_flagged);")
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_transactions_fts ON transactions 
            USING gin(to_tsvector('english', coalesce(customer_name, '') || ' ' || coalesce(txn_reference, '') || ' ' || coalesce(account_number, '') || ' ' || coalesce(merchant_or_recipient, '') || ' ' || coalesce(ip_address, '')));
        """)
        print("  [OK] Partitioned indexes and FTS GIN index ready on transactions.")

        print("\n" + "=" * 60)
        print("All PostgreSQL database migrations completed successfully! [OK]")
        print("=" * 60)

    except Exception as e:
        print(f"\n[ERROR] Migration failed: {e}", file=sys.stderr)
        raise
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    run_migration()
