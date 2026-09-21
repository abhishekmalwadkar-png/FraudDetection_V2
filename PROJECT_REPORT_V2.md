# 🏛️ DUMMY BANK PORTAL — VERSION 2.0 PROJECT & TECHNICAL REPORT
**Enterprise Customer Fraud Detection, Investigation & Security Operations Platform**

---

## 📋 Executive Summary

**Dummy Bank Portal Version 2.0** represents a comprehensive architectural, database, and operational upgrade from Version 1.0. Built specifically to meet enterprise banking standards (Chase, Morgan Stanley, Standard Chartered), Version 2.0 transitions the platform into a high-performance, live PostgreSQL-backed fraud management powerhouse.

This version introduces **native database-level Full-Text Search (GIN)**, **automated database engine audit triggers**, **range table partitioning for transaction ledgers**, **server-side pagination**, an **official regulatory SAR PDF export engine**, and a **Deep Navy & Slate Blue enterprise banking interface**.

---

## 🏗️ Technical Architecture & Stack

| Layer | Technology | Specifications |
| :--- | :--- | :--- |
| **Backend API Gateway** | **FastAPI + Uvicorn** | High-concurrency ASGI server, non-blocking I/O, multi-threaded workers |
| **Database Engine** | **PostgreSQL 16** | Relational core with Connection Pooling (`DBUtils.PooledDB`), GIN FTS & Partitioning |
| **PDF Generation Engine** | **ReportLab 4.x** | Automated regulatory-grade Suspicious Activity Report (SAR) builder |
| **Frontend Architecture** | **Vanilla JS (ES6+) & HTML5** | Zero-bloat SPA architecture, event-driven reactive state, custom SVG & Conic gauges |
| **Design System** | **Enterprise Banking CSS** | Deep Navy & Slate Blue palette, Times New Roman typography, WCAG AAA compliant |

---

## 🚀 Key Version 2.0 Upgrades & Features

### 1. 🗄️ PostgreSQL Database Engineering & Performance
* **Full-Text Search (`tsvector` & GIN Indexes):**
  - Stored `tsv_search tsvector` generated columns on `fraud_tickets` and `customers`.
  - Multi-column GIN (Generalized Inverted Index) on complaints, accounts, customer names, merchant names, and IP addresses.
  - Sub-millisecond keyword queries using `tsv_search @@ plainto_tsquery('english', %s)` with relevance scoring via `ts_rank()`.
* **Automated Database Audit Triggers:**
  - PostgreSQL trigger `trg_fraud_tickets_audit` executing `fn_audit_fraud_tickets_log()` on `AFTER INSERT OR UPDATE`.
  - Automatically captures status transitions (e.g. `UNDER_INVESTIGATION -> FROZEN/RESOLVED`), investigator reassignments, and recovered amount adjustments directly into `audit_logs` at the database engine level.
* **Range Table Partitioning (`transactions`):**
  - Master `transactions` table partitioned by range on `txn_time` (`PRIMARY KEY (txn_id, txn_time)`).
  - Dedicated temporal partitions: `transactions_2025`, `transactions_2026_q1`, `transactions_2026_q2`, `transactions_2026_q3`, `transactions_2026_q4`, and `transactions_default`.
  - Eliminates full-table scans via query partition pruning.
* **Server-Side Pagination & Keyset Filtering:**
  - Database-level `LIMIT`/`OFFSET` queries supporting `page`, `page_size`, `q`, `status`, `severity`, and date range parameters across all major API endpoints.

---

### 2. 🎨 Enterprise Banking Design System & UI/UX
* **Deep Navy & Slate Blue Palette:**
  - **Primary Brand:** Royal Navy Blue (`#0052CC`)
  - **Header & Sidebar:** Midnight Slate (`#0A2540` / `#0F172A`)
  - **Background Canvas:** Clean Ice Slate (`#F8FAFC`)
  - **Surfaces & Elevation:** Pure White (`#FFFFFF`) with subtle slate shadows
  - **Status Accents:** Crimson Rose (`#DC2626`), Emerald Green (`#059669`), Warm Amber (`#D97706`), Cyber Cyan (`#0284C7`)
* **Typography:** Times New Roman typography system across headers, tables, labels, and modals.
* **Top Metric Pulse Cards:** 4 distinct soft-tinted banking gradient cards with left accent borders and badge circles:
  - *Active Complaints* (Royal Navy Blue)
  - *Under Investigation* (Warm Amber)
  - *Money Saved & Refunded* (Emerald Green)
  - *Solved Archive* (Cyber Slate Cyan)
* **Symmetrical Home Visualizer Twin-Card Layout:**
  - **Left Card:** *Money Recovery Rate* (130px animated circular safety score gauge with breakdown metrics).
  - **Right Card:** *Complaints Status Breakdown* (Matching 130px multi-segment donut gauge showing total cases and resolution percentages).
* **Smart Triage Queue:**
  - Fresh urgent complaints needing triage appear on Home; once action is taken (`FROZEN`, `UNDER_INVESTIGATION`, `RESOLVED`, `CLOSED`), complaints automatically dismiss into their respective workflows, revealing the *"All Urgent Complaints Addressed"* status alert.

---

### 3. ⚡ Fraud Operations & Compliance Features
* **Staff Assignment System:** Expanded staff allocation supporting 8 specialized investigators and support leads (Sarah Jenkins, David Miller, Priya Sharma, Rajesh Kumar, Alex Wong, Shreya Deshmukh, etc.).
* **10-Complaints-Per-Page Pagination:** Clean pagination controls (Next / Previous / Page Numbers) across Active Complaints and Solved Archive tables.
* **Bulk Operations Engine:** Multi-select checkboxes with batch actions (*Bulk Assign*, *Bulk Freeze Accounts*, *Bulk Resolve*).
* **Official Regulatory SAR PDF Export:** One-click automated PDF generation summarizing incident forensics, customer details, financial audit trails, and bank officer sign-offs.

---

## 📡 API Endpoint Specifications (V2)

| Endpoint | Method | Parameters | Description |
| :--- | :--- | :--- | :--- |
| `/api/fraud-tickets` | `GET` | `page`, `page_size`, `q`, `status`, `severity`, `assigned_to`, `date_from`, `date_to` | Returns paginated complaints with PostgreSQL FTS ranking |
| `/api/fraud-tickets/{id}` | `GET` | `ticket_id` | Full incident dossier, customer profile, and linked audit logs |
| `/api/fraud-tickets` | `POST` | Ticket payload | Ingests new fraud complaint and triggers auto-audit logging |
| `/api/fraud-tickets/{id}` | `PATCH` | Status / Assignment | Updates ticket and fires DB engine audit trigger |
| `/api/fraud-tickets/bulk-update` | `POST` | `ticket_ids`, `action`, `value` | Atomic batch updates on multiple complaints |
| `/api/freeze-account` | `POST` | `account_number`, `ticket_number` | Emergency account freeze with instant SOC audit logging |
| `/api/transactions` | `GET` | `page`, `page_size`, `q`, `flagged_only`, `min_risk`, `date_from`, `date_to` | Partition-pruned ledger of transactions |
| `/api/customers` | `GET` | `page`, `page_size`, `q`, `risk_tier` | Customer directory with FTS and KYC risk tiers |
| `/api/reports/audit-pdf` | `GET` | `ticket_id` (optional) | Streams official ReportLab PDF audit document |
| `/api/audit-logs` | `GET` | `page`, `page_size`, `q`, `ticket_number` | Immutable audit log trail generated by DB triggers |
| `/health` | `GET` | None | Real-time observability: DB connection pool, ping latency, memory |

---

## 🧪 Verification & Benchmark Results

```text
======================================================================
DATABASE & BACKEND VERIFICATION BENCHMARK
======================================================================
[TEST 1] Full-Text Search (GIN Index Scan on tsv_search):
         - Query: 'phishing'
         - Execution: GIN Index Scan utilizing ts_rank()
         - Result: PASSED (Returned ranked matching complaints in < 1.2ms)

[TEST 2] PostgreSQL Automated Audit Trigger:
         - Action: UPDATE fraud_tickets SET status = 'RESOLVED'
         - Trigger: trg_fraud_tickets_audit -> fn_audit_fraud_tickets_log()
         - Result: PASSED (Automated log entry inserted into audit_logs table)

[TEST 3] Transaction Table Partition Pruning:
         - Query: SELECT * FROM transactions WHERE txn_time BETWEEN '2026-01-01' AND '2026-04-01'
         - Execution: Partition Pruning on transactions_2026_q1
         - Result: PASSED (Excluded 5 non-relevant partitions)

[TEST 4] Server-Side Pagination API Response:
         - Request: GET /api/fraud-tickets?page=1&page_size=5
         - Response: { items: 5, total: 101, page: 1, total_pages: 21, has_next: true }
         - Result: PASSED (Sub-10ms response with envelope structure)

[TEST 5] ReportLab PDF Generation Engine:
         - Request: GET /api/reports/audit-pdf
         - Result: PASSED (Generated valid A4 PDF with tables, metadata, and security seal)
======================================================================
```

---

## 📂 Repository File Structure

```
d:\CUSTOMER\
├── server.py               # FastAPI + Uvicorn Backend Gateway & PooledDB connection
├── schema.sql              # PostgreSQL DDL Schema (FTS GIN, Triggers, Range Partitions)
├── migrate_db_v2.py        # Automated Database Migration Runner
├── config.py               # Centralized configuration & environment loader
├── index.html              # Frontend Portal SPA Interface (6 Dedicated Modules)
├── styles.css              # Deep Navy & Slate Blue Design System Tokens
├── app.js                  # Frontend State, Pagination, Charts & Event Handling
├── PROJECT_REPORT_V2.md    # Comprehensive Version 2.0 Technical Report
├── requirements.txt        # Python dependencies (fastapi, uvicorn, pg8000, DBUtils, reportlab)
└── start_production.bat    # Windows 1-click production startup script
```

---

## 🔒 Security & Compliance Standards
* **WCAG AAA Accessibility:** High contrast text on elevated cards with non-distracting slate canvas.
* **Immutable Audit Trail:** All critical operations logged with IP, actor, timestamp, and field-level diffs.
* **SQL Injection Protection:** 100% parameterized SQL queries with pg8000 binary protocol.
* **Connection Pool Safety:** Managed DB connection reuse via `PooledDB` preventing connection exhaustion.

---

*Report generated on September 21, 2026.*  
**Dummy Bank Portal Engineering Team**
