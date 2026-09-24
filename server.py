"""
Dummy Bank Portal - Production Fraud Portal Backend & API Gateway
Powered by FastAPI & Uvicorn (High-Concurrency ASGI Server)
Connected live to PostgreSQL (bank_fraud_portal) via PooledDB.
Interactive Swagger Documentation available at: /docs & /redoc
"""

import os
import io
import time
import json
import uuid
import asyncio
import logging
from decimal import Decimal
from datetime import datetime, date, timezone
from typing import Optional, Any, Dict, List, Union

from fastapi import FastAPI, Request, Response, HTTPException, status, Depends
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
import pg8000.dbapi
import uvicorn

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False


from config import (
    APP_ENV, LOG_LEVEL,
    PORTAL_HOST, PORTAL_PORT,
    DB_HOST, DB_PORT, DB_USER, DB_PASS, DB_NAME,
    DB_POOL_MIN_CACHED, DB_POOL_MAX_CACHED, DB_POOL_MAX_CONNECTIONS,
    SERVER_THREADS, SERVER_CONNECTION_LIMIT,
    API_SECRET_KEY, ENABLE_SQL_CONSOLE,
    DEFAULT_INVESTIGATOR, DEFAULT_BRANCH, DEFAULT_CHANNEL,
    DEFAULT_INCIDENT_TYPE, DEFAULT_ACCOUNT_TYPE, DEFAULT_SEVERITY
)
from dbutils.pooled_db import PooledDB

# -------------------------------------------------------------
# Production Logging Configuration
# -------------------------------------------------------------
numeric_level = getattr(logging, LOG_LEVEL, logging.INFO)
logging.basicConfig(
    level=numeric_level,
    format='%(asctime)s [%(levelname)s] [Worker-%(process)d] %(message)s'
)
logger = logging.getLogger("BankPortalServer")

# Metrics & Observability Collector
START_TIME = time.time()
METRICS = {
    "total_requests": 0,
    "total_errors": 0,
    "total_fraud_tickets_created": 0,
    "endpoints_hit": {},
    "status_codes": {}
}

# -------------------------------------------------------------
# Custom JSON Encoder helper
# -------------------------------------------------------------
def clean_db_record(obj: Any) -> Any:
    """Helper to convert Decimals to float and datetimes to ISO strings recursively."""
    if isinstance(obj, Decimal):
        return float(obj)
    elif isinstance(obj, (datetime, date)):
        return obj.isoformat()
    elif isinstance(obj, dict):
        return {k: clean_db_record(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [clean_db_record(item) for item in obj]
    return obj

# -------------------------------------------------------------
# FastAPI Application Initialization
# -------------------------------------------------------------
app = FastAPI(
    title="Dummy Bank Portal - Fraud Detection & RPA Intake API",
    description="Enterprise API Gateway for automated Robotic Process Automation (AutomationEdge) and Banking SOC Fraud Management with AsyncIO Non-Blocking High-Concurrency Engine.",
    version="3.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

# Global Cross-Origin Resource Sharing (CORS) Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"]
)

# -------------------------------------------------------------
# Database Connection Pooling (Thread-Safe Warm Pool)
# -------------------------------------------------------------
logger.info(
    f"Initializing PostgreSQL Connection Pool (min={DB_POOL_MIN_CACHED}, max={DB_POOL_MAX_CONNECTIONS}) to {DB_NAME}..."
)

def create_db_pool():
    return PooledDB(
        creator=pg8000.dbapi,
        maxconnections=DB_POOL_MAX_CONNECTIONS,
        mincached=DB_POOL_MIN_CACHED,
        maxcached=DB_POOL_MAX_CACHED,
        maxshared=0,
        blocking=True,
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASS,
        database=DB_NAME
    )

db_pool = create_db_pool()
logger.info("[+] PostgreSQL Connection Pool is ready and active.")

def get_db_connection(max_retries=2):
    """Retrieve an active, pre-connected PostgreSQL socket with automatic reconnection resilience."""
    last_err = None
    for attempt in range(max_retries):
        try:
            return db_pool.connection()
        except Exception as e:
            last_err = e
            logger.warning(f"Connection pool acquisition retry {attempt+1}/{max_retries}: {e}")
            time.sleep(0.1)
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=f"Database connection pool exhausted or unreachable: {last_err}"
    )

# -------------------------------------------------------------
# Middleware: Request Tracing, Latency & Access Logging
# -------------------------------------------------------------
@app.middleware("http")
async def request_metrics_and_tracing_middleware(request: Request, call_next):
    t0 = time.time()
    req_id = request.headers.get("X-Request-ID") or f"REQ-{uuid.uuid4().hex[:12].upper()}"
    request.state.request_id = req_id
    
    # Update telemetry counters
    METRICS["total_requests"] += 1
    endpoint = request.url.path
    METRICS["endpoints_hit"][endpoint] = METRICS["endpoints_hit"].get(endpoint, 0) + 1
    
    try:
        response = await call_next(request)
    except Exception as exc:
        METRICS["total_errors"] += 1
        duration_ms = (time.time() - t0) * 1000.0
        logger.error(f"{request.method} {request.url.path} 500 - {duration_ms:.2f}ms - Unhandled Exception: {exc}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal Server Error",
                "message": "An unexpected server error occurred. Please contact the SOC operations team.",
                "request_id": req_id,
                "timestamp": datetime.now(timezone.utc).isoformat()
            },
            headers={"X-Request-ID": req_id}
        )

    duration_ms = (time.time() - t0) * 1000.0
    status_code = response.status_code
    METRICS["status_codes"][status_code] = METRICS["status_codes"].get(status_code, 0) + 1
    
    response.headers["X-Request-ID"] = req_id
    
    client_ip = request.client.host if request.client else "unknown"
    if status_code >= 400:
        METRICS["total_errors"] += 1
        logger.warning(f"{request.method} {request.url.path} {status_code} - {duration_ms:.2f}ms - IP: {client_ip}")
    else:
        logger.info(f"{request.method} {request.url.path} {status_code} - {duration_ms:.2f}ms - IP: {client_ip}")

    return response

# -------------------------------------------------------------
# Security & Auth Validation
# -------------------------------------------------------------
def verify_api_authorization(request: Request) -> bool:
    """Verify API authentication if API_SECRET_KEY is configured in .env."""
    if not API_SECRET_KEY:
        return True  # Open local dev mode
    
    auth_header = request.headers.get("Authorization", "")
    api_key_header = request.headers.get("X-API-Key", "")
    
    if api_key_header and api_key_header == API_SECRET_KEY:
        return True
    if auth_header.startswith("Bearer ") and auth_header.split(" ", 1)[1].strip() == API_SECRET_KEY:
        return True
    return False

# -------------------------------------------------------------
# Pydantic Schemas for Request Validation
# -------------------------------------------------------------
class FraudTicketCreateSchema(BaseModel):
    full_name: Optional[str] = Field(None, description="Full Name of the Customer", examples=["Rajesh Sharma"])
    customer_name: Optional[str] = Field(None, description="Alias for full_name", examples=["Rajesh Sharma"])
    email: Optional[str] = Field(None, description="Customer Email Address", examples=["rajesh@example.com"])
    phone: Optional[str] = Field(None, description="Customer Contact Number", examples=["+91 98201 44521"])
    account_number: Optional[str] = Field(None, description="Bank Account Number", examples=["ACT-10029"])
    account_no: Optional[str] = Field(None, description="Alias for account_number", examples=["ACT-10029"])
    account_type: Optional[str] = Field("SAVINGS", description="Account Type (SAVINGS, CHECKING, etc.)", examples=["SAVINGS"])
    amount_involved: Optional[Union[float, int, str]] = Field(25000.0, description="Fraud Amount Involved in INR", examples=[45000.00])
    amount: Optional[Union[float, int, str]] = Field(None, description="Alias for amount_involved")
    incident_type: Optional[str] = Field("Fake QR Code Scam", description="Categorization of the fraud incident", examples=["UPI Impersonation Fraud"])
    reported_channel: Optional[str] = Field("Customer Help Desk", description="Source/Intake Channel (e.g. RPA_AUTOMATIONEDGE, Mobile App, Web Portal)", examples=["RPA_AUTOMATIONEDGE"])
    severity: Optional[str] = Field("HIGH", description="Severity (LOW, MEDIUM, HIGH, CRITICAL)", examples=["HIGH"])
    description: Optional[str] = Field("Customer reported suspicious transaction.", description="Incident narrative and details")
    suspect_entity: Optional[str] = Field("Unknown Merchant UPI", description="Suspect recipient or beneficiary")
    flagged_ip_or_location: Optional[str] = Field("Web Client Terminal", description="Originating IP address or geographical location")

    model_config = {
        "extra": "allow"
    }

class FraudTicketUpdateSchema(BaseModel):
    status: Optional[str] = Field(None, description="New ticket status (UNDER_INVESTIGATION, FROZEN, RESOLVED, CLOSED, REJECTED, ESCALATED)", examples=["RESOLVED"])
    assigned_investigator: Optional[str] = Field(None, description="Staff investigator assigned to handle the complaint", examples=["Shreya Deshmukh (Support Lead)"])
    action_taken: Optional[str] = Field("", description="Resolution note or investigation comments", examples=["Card cancelled and funds blocked."])

class BulkTicketUpdateSchema(BaseModel):
    ticket_ids: List[Union[int, str]] = Field(..., description="List of ticket IDs or ticket numbers to update", examples=[[101, 102, 103]])
    status: Optional[str] = Field(None, description="New status to set across selected tickets", examples=["RESOLVED"])
    assigned_investigator: Optional[str] = Field(None, description="Staff member to assign across selected tickets", examples=["Rajesh Nair (Fraud Forensics)"])
    action_taken: Optional[str] = Field("", description="Optional action note for the audit log")

class FreezeAccountSchema(BaseModel):
    account_number: str = Field(..., description="Target bank account number to lock", examples=["ACT-10029"])
    ticket_number: Optional[str] = Field(None, description="Optional linked fraud ticket number", examples=["FRD-2026-A1B2C3D4"])

class SqlExecuteSchema(BaseModel):
    query: str = Field(..., description="SQL Query string to execute against PostgreSQL", examples=["SELECT * FROM fraud_tickets LIMIT 5;"])

# -------------------------------------------------------------
# Static Frontend Routes
# -------------------------------------------------------------
@app.get("/", include_in_schema=False)
async def serve_index():
    if os.path.exists("index.html"):
        return FileResponse("index.html", media_type="text/html")
    return HTMLResponse("<h2>Dummy Bank Portal is Running</h2>", status_code=200)

@app.get("/styles.css", include_in_schema=False)
async def serve_css():
    if os.path.exists("styles.css"):
        return FileResponse("styles.css", media_type="text/css")
    raise HTTPException(status_code=404, detail="styles.css not found")

@app.get("/app.js", include_in_schema=False)
async def serve_js():
    if os.path.exists("app.js"):
        return FileResponse("app.js", media_type="application/javascript")
    raise HTTPException(status_code=404, detail="app.js not found")

# -------------------------------------------------------------
# Health & Observability Endpoints
# -------------------------------------------------------------
@app.get("/health", tags=["System Observability"])
def health_check(request: Request):
    """Enterprise Health Check with Live PostgreSQL Ping & Connection Pool Diagnostics."""
    t0 = time.time()
    db_ok = False
    db_latency_ms = 0.0
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT 1;")
        cur.fetchone()
        cur.close()
        conn.close()
        db_ok = True
        db_latency_ms = round((time.time() - t0) * 1000.0, 2)
    except Exception as e:
        logger.error(f"Health check DB ping failed: {e}")

    return {
        "status": "UP" if db_ok else "DEGRADED",
        "environment": APP_ENV,
        "server": "FastAPI + Uvicorn (Production ASGI)",
        "worker_threads": SERVER_THREADS,
        "database": {
            "status": "CONNECTED" if db_ok else "DISCONNECTED",
            "ping_latency_ms": db_latency_ms,
            "pool": {
                "type": "DBUtils.PooledDB",
                "min_cached": DB_POOL_MIN_CACHED,
                "max_cached": DB_POOL_MAX_CACHED,
                "max_connections": DB_POOL_MAX_CONNECTIONS,
                "database": DB_NAME
            }
        },
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@app.get("/api/metrics", tags=["System Observability"])
def api_metrics():
    """Observability & Telemetry Endpoint for Monitoring Dashboards."""
    uptime = time.time() - START_TIME
    return {
        "uptime_seconds": round(uptime, 2),
        "total_requests": METRICS["total_requests"],
        "total_errors": METRICS["total_errors"],
        "error_rate": round(METRICS["total_errors"] / max(1, METRICS["total_requests"]), 4),
        "total_fraud_tickets_created": METRICS["total_fraud_tickets_created"],
        "endpoints_hit": METRICS["endpoints_hit"],
        "status_codes": METRICS["status_codes"],
        "server": {
            "threads": SERVER_THREADS,
            "max_connections": SERVER_CONNECTION_LIMIT,
            "framework": "FastAPI / Uvicorn"
        },
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

# -------------------------------------------------------------
# REST API Endpoints
# -------------------------------------------------------------
@app.get("/api/overview", tags=["Analytics & Overview"])
def api_overview():
    """Returns top-level metric counters for the Bank Fraud Operations Dashboard."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT COUNT(*) FROM fraud_tickets;")
        total_tickets = cursor.fetchone()[0]

        cursor.execute("SELECT COALESCE(SUM(amount_involved), 0) FROM fraud_tickets;")
        total_amount = cursor.fetchone()[0]

        cursor.execute("SELECT COALESCE(SUM(recovered_amount), 0) FROM fraud_tickets;")
        recovered_amount = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM fraud_tickets WHERE status = 'UNDER_INVESTIGATION';")
        under_investigation = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM fraud_tickets WHERE status = 'FROZEN';")
        frozen_accounts = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM fraud_tickets WHERE status = 'RESOLVED';")
        resolved_cases = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM fraud_tickets WHERE status NOT IN ('RESOLVED', 'CLOSED', 'REJECTED');")
        active_tickets = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM customers WHERE risk_tier = 'CRITICAL';")
        critical_customers = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM customers;")
        total_customers = cursor.fetchone()[0]

        return clean_db_record({
            "total_tickets": total_tickets,
            "active_tickets": active_tickets,
            "total_amount": float(total_amount),
            "recovered_amount": float(recovered_amount),
            "under_investigation": under_investigation,
            "frozen_accounts": frozen_accounts,
            "resolved_cases": resolved_cases,
            "critical_customers": critical_customers,
            "total_customers": total_customers
        })
    finally:
        cursor.close()
        conn.close()

@app.get("/api/fraud-tickets", tags=["Fraud Operations"])
def api_get_fraud_tickets(
    page: Optional[int] = None,
    page_size: Optional[int] = None,
    q: Optional[str] = None,
    status: Optional[str] = None,
    severity: Optional[str] = None,
    assigned_to: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None
):
    """List recorded fraud incidents with optional FTS search, filtering, and server-side pagination."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        where_clauses = []
        params = []

        if q and q.strip():
            where_clauses.append("t.tsv_search @@ plainto_tsquery('english', %s)")
            params.append(q.strip())
        
        if status and status.strip() and status.upper() != "ALL":
            where_clauses.append("t.status = %s")
            params.append(status.strip().upper())
            
        if severity and severity.strip() and severity.upper() != "ALL":
            where_clauses.append("t.severity = %s")
            params.append(severity.strip().upper())
            
        if assigned_to and assigned_to.strip() and assigned_to != "ALL":
            where_clauses.append("t.assigned_investigator = %s")
            params.append(assigned_to.strip())

        if date_from and date_from.strip():
            where_clauses.append("t.incident_date >= %s")
            params.append(date_from.strip())

        if date_to and date_to.strip():
            where_clauses.append("t.incident_date <= %s")
            params.append(date_to.strip() + " 23:59:59")

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        is_paginated = page is not None or page_size is not None
        total_count = None
        
        if is_paginated:
            count_sql = f"""
                SELECT COUNT(*) 
                FROM fraud_tickets t
                JOIN customers c ON t.customer_id = c.customer_id
                {where_sql};
            """
            cursor.execute(count_sql, tuple(params))
            total_count = cursor.fetchone()[0]

        order_sql = "ORDER BY ts_rank(t.tsv_search, plainto_tsquery('english', %s)) DESC, t.ticket_id DESC" if (q and q.strip()) else "ORDER BY t.ticket_id DESC"
        query_params = [q.strip()] + params if (q and q.strip()) else params

        limit_sql = ""
        if is_paginated:
            p = max(1, page or 1)
            ps = max(1, min(200, page_size or 10))
            offset = (p - 1) * ps
            limit_sql = f"LIMIT {ps} OFFSET {offset}"

        sql = f"""
            SELECT 
                t.ticket_id, t.ticket_number, t.customer_id, c.customer_code, c.full_name, c.email, c.phone, c.risk_tier,
                t.account_number, ca.account_type, ca.balance, ca.status as account_status,
                t.incident_type, t.amount_involved, t.recovered_amount, t.incident_date,
                t.reported_channel, t.severity, t.status, t.assigned_investigator,
                t.flagged_ip_or_location, t.suspect_entity, t.description, t.action_taken,
                t.created_at
            FROM fraud_tickets t
            JOIN customers c ON t.customer_id = c.customer_id
            LEFT JOIN customer_accounts ca ON (t.customer_id = ca.customer_id AND t.account_number = ca.account_number)
            {where_sql}
            {order_sql}
            {limit_sql};
        """
        cursor.execute(sql, tuple(query_params))
        rows = cursor.fetchall()
        
        tickets = []
        for r in rows:
            tickets.append({
                "ticket_id": r[0],
                "ticket_number": r[1],
                "customer_id": r[2],
                "customer_code": r[3],
                "customer_name": r[4],
                "full_name": r[4],
                "email": r[5],
                "phone": r[6],
                "risk_tier": r[7],
                "account_number": r[8],
                "account_type": r[9],
                "balance": float(r[10]) if r[10] is not None else 0.0,
                "account_status": r[11] or 'ACTIVE',
                "incident_type": r[12],
                "amount_involved": float(r[13]),
                "recovered_amount": float(r[14]),
                "incident_date": r[15],
                "reported_channel": r[16],
                "severity": r[17],
                "status": r[18],
                "assigned_investigator": r[19],
                "flagged_ip_or_location": r[20],
                "suspect_entity": r[21],
                "description": r[22],
                "action_taken": r[23],
                "created_at": r[24]
            })
        cleaned_tickets = clean_db_record(tickets)
        if is_paginated:
            import math
            p = max(1, page or 1)
            ps = max(1, min(200, page_size or 10))
            return {
                "items": cleaned_tickets,
                "total": total_count,
                "page": p,
                "page_size": ps,
                "total_pages": math.ceil(total_count / ps) if total_count else 1,
                "has_next": (p * ps) < total_count if total_count else False,
                "has_prev": p > 1
            }
        return cleaned_tickets
    finally:
        cursor.close()
        conn.close()


@app.get("/api/fraud-tickets/{ticket_id}", tags=["Fraud Operations"])
def api_get_single_ticket(ticket_id: str):
    """Retrieve full forensic details, linked transactions, and audit logs for a single ticket."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT 
                t.ticket_id, t.ticket_number, t.customer_id, c.customer_code, c.full_name, c.email, c.phone, c.risk_tier,
                c.address, c.city, c.state,
                t.account_number, ca.account_type, ca.balance, ca.status as account_status, ca.branch,
                t.incident_type, t.amount_involved, t.recovered_amount, t.incident_date,
                t.reported_channel, t.severity, t.status, t.assigned_investigator,
                t.flagged_ip_or_location, t.suspect_entity, t.description, t.action_taken,
                t.created_at
            FROM fraud_tickets t
            JOIN customers c ON t.customer_id = c.customer_id
            LEFT JOIN customer_accounts ca ON (t.customer_id = ca.customer_id AND t.account_number = ca.account_number)
            WHERE t.ticket_id = %s OR t.ticket_number = %s;
        """, (int(ticket_id) if ticket_id.isdigit() else -1, ticket_id))
        r = cursor.fetchone()

        if not r:
            raise HTTPException(status_code=404, detail="Ticket not found")

        ticket = {
            "ticket_id": r[0],
            "ticket_number": r[1],
            "customer_id": r[2],
            "customer_code": r[3],
            "full_name": r[4],
            "customer_name": r[4],
            "email": r[5],
            "phone": r[6],
            "risk_tier": r[7],
            "address": r[8],
            "city": r[9],
            "state": r[10],
            "account_number": r[11],
            "account_type": r[12],
            "balance": float(r[13]) if r[13] is not None else 0.0,
            "account_status": r[14] or 'ACTIVE',
            "branch": r[15],
            "incident_type": r[16],
            "amount_involved": float(r[17]),
            "recovered_amount": float(r[18]),
            "incident_date": r[19],
            "reported_channel": r[20],
            "severity": r[21],
            "status": r[22],
            "assigned_investigator": r[23],
            "flagged_ip_or_location": r[24],
            "suspect_entity": r[25],
            "description": r[26],
            "action_taken": r[27],
            "created_at": r[28]
        }

        # Get linked transactions
        cursor.execute("""
            SELECT txn_id, txn_reference, amount, txn_type, merchant_or_recipient, channel, ip_address, is_fraud_flagged, fraud_risk_score, status, txn_time
            FROM transactions
            WHERE customer_id = %s
            ORDER BY txn_id DESC;
        """, (ticket["customer_id"],))
        txns = []
        for t in cursor.fetchall():
            txns.append({
                "txn_id": t[0], "txn_reference": t[1], "amount": float(t[2]), "txn_type": t[3],
                "merchant_or_recipient": t[4], "channel": t[5], "ip_address": t[6],
                "is_fraud_flagged": t[7], "fraud_risk_score": t[8], "status": t[9], "txn_time": t[10]
            })
        ticket["transactions"] = txns

        # Get audit logs
        cursor.execute("""
            SELECT log_id, actor, action, details, ip_address, created_at
            FROM audit_logs
            WHERE ticket_number = %s
            ORDER BY log_id DESC;
        """, (ticket["ticket_number"],))
        logs = []
        for l in cursor.fetchall():
            logs.append({
                "log_id": l[0], "actor": l[1], "action": l[2], "details": l[3], "ip_address": l[4], "created_at": l[5]
            })
        ticket["audit_logs"] = logs

        return clean_db_record(ticket)
    finally:
        cursor.close()
        conn.close()

def _sync_insert_single_ticket(payload: Dict[str, Any], client_ip: str) -> Dict[str, Any]:
    """Synchronous thread-safe database insertion routine for a single fraud ticket."""
    def _get_val(*keys, default=None):
        if not isinstance(payload, dict):
            return default
        for k in keys:
            if k in payload and payload[k] not in (None, "", "null", "<null>"):
                return payload[k]
        norm_map = {str(k).lower().replace("_", "").replace("-", "").replace(" ", ""): v for k, v in payload.items()}
        for k in keys:
            norm_k = k.lower().replace("_", "").replace("-", "").replace(" ", "")
            if norm_k in norm_map and norm_map[norm_k] not in (None, "", "null", "<null>"):
                return norm_map[norm_k]
        return default

    cust_name = str(_get_val("full_name", "customer_name", "fullname", "name", "cust_name", default=f"Customer {uuid.uuid4().hex[:5].upper()}")).strip()
    if not cust_name:
        raise ValueError("Customer full_name cannot be blank.")

    email = str(_get_val("email", "mail", default=f"user_{uuid.uuid4().hex[:6]}@bankdomain.internal")).strip()
    phone = str(_get_val("phone", "mobile", "contact", default=f"+91 {uuid.uuid4().int % 9000000000 + 1000000000}")).strip()
    cust_code = f"CUST-{uuid.uuid4().hex[:6].upper()}"
    acc_num = str(_get_val("account_number", "account_no", "accountnumber", "acc_num", default=f"ACT-{uuid.uuid4().hex[:6].upper()}")).strip()
    acc_type = str(_get_val("account_type", "accounttype", default=DEFAULT_ACCOUNT_TYPE)).upper().strip()

    raw_amount = _get_val("amount_involved", "amount", "amountinvolved", default=25000.0)
    try:
        amount = float(str(raw_amount).replace(",", "").replace("₹", "").strip())
        if amount <= 0:
            raise ValueError("amount_involved must be greater than zero.")
    except ValueError:
        raise ValueError(f"Invalid numerical amount_involved: '{raw_amount}'")

    if amount >= 100000.0:
        severity = "CRITICAL"
    elif amount >= 50000.0:
        severity = "HIGH"
    elif amount >= 10000.0:
        severity = "MEDIUM"
    else:
        severity = "LOW"
    risk_tier = severity

    incident_type = str(_get_val("incident_type", "incidenttype", "fraud_type", default=DEFAULT_INCIDENT_TYPE)).strip()
    channel = str(_get_val("reported_channel", "channel", default=DEFAULT_CHANNEL)).strip()
    desc = str(_get_val("description", "desc", "details", default=f"Suspicious activity reported via {channel}.")).strip()
    suspect = str(_get_val("suspect_entity", "suspect", "merchant", default="Flagged Merchant / Beneficiary")).strip()
    flagged_ip = str(_get_val("flagged_ip_or_location", "location", "ip_address", default=client_ip)).strip()
    staff_assignee = str(_get_val("assigned_investigator", "staff", "assigned_to", default=DEFAULT_INVESTIGATOR)).strip()
    ticket_num = f"FRD-{date.today().year}-{uuid.uuid4().hex[:8].upper()}"

    conn = get_db_connection()
    conn.autocommit = True
    cursor = conn.cursor()
    try:
        # 1. Check if customer already exists
        cursor.execute("""
            SELECT customer_id, full_name, risk_tier 
            FROM customers 
            WHERE email = %s OR phone = %s OR full_name = %s 
            ORDER BY customer_id ASC 
            LIMIT 1;
        """, (email, phone, cust_name))
        existing_cust = cursor.fetchone()

        if existing_cust:
            cust_id = existing_cust[0]
            cursor.execute("""
                UPDATE customers 
                SET full_name = %s, customer_name = %s, email = %s, phone = %s, risk_tier = %s 
                WHERE customer_id = %s;
            """, (cust_name, cust_name, email, phone, risk_tier, cust_id))
            cursor.execute("""
                UPDATE customer_accounts
                SET customer_name = %s
                WHERE customer_id = %s;
            """, (cust_name, cust_id))
        else:
            cursor.execute("""
                INSERT INTO customers (customer_code, customer_name, full_name, email, phone, risk_tier)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING customer_id;
            """, (cust_code, cust_name, cust_name, email, phone, risk_tier))
            cust_id = cursor.fetchone()[0]

        # 2. Check if account already exists
        cursor.execute("SELECT account_id FROM customer_accounts WHERE account_number = %s LIMIT 1;", (acc_num,))
        existing_acc = cursor.fetchone()
        if not existing_acc:
            cursor.execute("""
                INSERT INTO customer_accounts (customer_id, customer_name, account_number, account_type, balance, branch, opened_date)
                VALUES (%s, %s, %s, %s, %s, %s, %s);
            """, (cust_id, cust_name, acc_num, acc_type, amount, DEFAULT_BRANCH, date.today().isoformat()))

        # 3. Insert fraud ticket
        cursor.execute("""
            INSERT INTO fraud_tickets (
                ticket_number, customer_id, customer_name, account_number, incident_type,
                amount_involved, recovered_amount, incident_date, reported_channel,
                severity, status, assigned_investigator, flagged_ip_or_location,
                suspect_entity, description, action_taken
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING ticket_id;
        """, (
            ticket_num, cust_id, cust_name, acc_num, incident_type,
            amount, 0.0, datetime.now(), channel,
            severity, "UNDER_INVESTIGATION", staff_assignee,
            flagged_ip, suspect,
            desc, f"Complaint logged into PostgreSQL database; Assigned to {staff_assignee}."
        ))
        new_ticket_id = cursor.fetchone()[0]

        # 4. Audit log
        cursor.execute("""
            INSERT INTO audit_logs (ticket_number, customer_name, actor, action, details, ip_address)
            VALUES (%s, %s, %s, %s, %s, %s);
        """, (ticket_num, cust_name, "Process Studio RPA Intake", "NEW_INCIDENT_REGISTERED", f"Created fraud ticket {ticket_num} for {cust_name} ({incident_type} - ₹{amount:,.2f})", client_ip))

        METRICS["total_fraud_tickets_created"] += 1

        return {
            "success": True, 
            "ticket_id": new_ticket_id, 
            "ticket_number": ticket_num, 
            "customer_name": cust_name, 
            "account_number": acc_num,
            "incident_type": incident_type,
            "amount_involved": amount
        }
    finally:
        cursor.close()
        conn.close()


def _sync_bulk_dummy_intake(target_count: int, client_ip: str) -> List[Dict[str, Any]]:
    """Synchronous thread-safe database insertion routine for bulk dummy fraud tickets."""
    import random
    first_names = ["Aarav", "Pooja", "Vikram", "Neha", "Rahul", "Sneha", "Anand", "Divya", "Suresh", "Kavita", "Rohan", "Meera", "Amit", "Priyanka", "Sanjay", "Ananya", "Deepak", "Swati", "Manoj", "Shilpa", "Kiran", "Aditya"]
    last_names = ["Sharma", "Patel", "Verma", "Iyer", "Nair", "Kulkarni", "Deshmukh", "Gupta", "Reddy", "Mehta", "Singh", "Joshi", "Choudhury", "Bose", "Menon", "Agarwal"]
    
    incident_types = [
        "Fake QR Code Scam",
        "UPI Impersonation Fraud",
        "Phishing Link via SMS / WhatsApp",
        "SIM Swap Fraud",
        "Unauthorized ATM Withdrawal",
        "Fake KYC Update Call",
        "Investment / Crypto Scam",
        "Net Banking Credential Theft",
        "Fake Loan Approval Fee Scam",
        "International Card Cloning"
    ]
    
    merchants = [
        "QuickPay Store QR #994",
        "FastCash Loan Portal",
        "CryptoPay Desk Singapore",
        "LuckyDraw UPI Merchant",
        "Unknown POS Terminal Bangalore",
        "PhishDesk KYC Support",
        "GlobalFX Trading Ltd",
        "EasyLoan Mobile App Hub"
    ]

    staff_list = [
        "Shreya Deshmukh (Support Lead)",
        "Rajesh Nair (Fraud Forensics)",
        "Pooja Mehta (Compliance Officer)",
        "Amitabh Sen (Senior Analyst)"
    ]

    created_tickets = []
    conn = get_db_connection()
    conn.autocommit = True
    cursor = conn.cursor()

    try:
        for i in range(1, target_count + 1):
            fname = random.choice(first_names)
            lname = random.choice(last_names)
            cust_name = f"{fname} {lname}"
            email = f"{fname.lower()}.{lname.lower()}{random.randint(100, 999)}@example.com"
            phone = f"+91 {random.randint(98000, 99999)} {random.randint(10000, 99999)}"
            acc_num = f"ACT-BATCH-{random.randint(10000, 99999)}"
            acc_type = random.choice(["SAVINGS", "CURRENT"])
            incident_type = random.choice(incident_types)
            amount = round(random.uniform(5000, 95000), 2)
            suspect = random.choice(merchants)
            staff_assignee = random.choice(staff_list)
            
            if amount >= 75000.0:
                severity = "CRITICAL"
            elif amount >= 40000.0:
                severity = "HIGH"
            elif amount >= 15000.0:
                severity = "MEDIUM"
            else:
                severity = "LOW"
            risk_tier = severity

            cust_code = f"CUST-{uuid.uuid4().hex[:6].upper()}"
            ticket_num = f"FRD-2026-{uuid.uuid4().hex[:8].upper()}"
            desc = f"Automated batch intake test incident #{i}: Customer noticed unauthorized transaction of ₹{amount:,.2f} via {suspect}."

            cursor.execute("""
                INSERT INTO customers (customer_code, customer_name, full_name, email, phone, risk_tier)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING customer_id;
            """, (cust_code, cust_name, cust_name, email, phone, risk_tier))
            cust_id = cursor.fetchone()[0]

            cursor.execute("""
                INSERT INTO customer_accounts (customer_id, customer_name, account_number, account_type, balance, branch, opened_date)
                VALUES (%s, %s, %s, %s, %s, %s, %s);
            """, (cust_id, cust_name, acc_num, acc_type, amount * 1.5, "Mumbai Central Branch", "2024-01-15"))

            cursor.execute("""
                INSERT INTO fraud_tickets (
                    ticket_number, customer_id, customer_name, account_number, incident_type,
                    amount_involved, recovered_amount, incident_date, reported_channel,
                    severity, status, assigned_investigator, flagged_ip_or_location,
                    suspect_entity, description, action_taken
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING ticket_id;
            """, (
                ticket_num, cust_id, cust_name, acc_num, incident_type,
                amount, 0.0, datetime.now(), "Process Studio Batch RPA",
                severity, "UNDER_INVESTIGATION", staff_assignee,
                "Process Studio RPA Terminal", suspect,
                desc, f"Batch intake registered in PostgreSQL; Assigned to {staff_assignee}."
            ))
            new_ticket_id = cursor.fetchone()[0]

            cursor.execute("""
                INSERT INTO audit_logs (ticket_number, customer_name, actor, action, details, ip_address)
                VALUES (%s, %s, %s, %s, %s, %s);
            """, (ticket_num, cust_name, "Process Studio Batch Intake", "BULK_INCIDENT_REGISTERED", f"Batch generated ticket {ticket_num} for {cust_name} ({incident_type} - ₹{amount:,.2f})", client_ip))

            created_tickets.append({
                "ticket_id": new_ticket_id,
                "ticket_number": ticket_num,
                "customer_name": cust_name,
                "account_number": acc_num,
                "incident_type": incident_type,
                "amount_involved": amount,
                "severity": severity
            })

        METRICS["total_fraud_tickets_created"] += len(created_tickets)
        return created_tickets
    finally:
        cursor.close()
        conn.close()


@app.post("/api/fraud-tickets", status_code=201, tags=["Fraud Operations"])
async def api_create_fraud_ticket(request: Request):
    """
    Asynchronous Non-Blocking Intake endpoint for logging fraud cases into PostgreSQL.
    Accepts single JSON object or JSON array for concurrent batch ingestion.
    """
    if not verify_api_authorization(request):
        raise HTTPException(status_code=401, detail="Valid API Key or Bearer token is required.")

    raw_body = await request.body()
    raw_text = raw_body.decode("utf-8", errors="ignore")
    
    payload: Union[Dict[str, Any], List[Dict[str, Any]]] = {}
    content_type = request.headers.get("content-type", "").lower()
    
    if "application/json" in content_type or (raw_text.strip().startswith(("{", "[")) and raw_text.strip().endswith(("}", "]"))):
        try:
            payload = json.loads(raw_text)
        except Exception:
            payload = {}
    elif "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
        form_data = await request.form()
        payload = dict(form_data)

    if not payload and "[object Object]" in raw_text:
        raise HTTPException(
            status_code=400,
            detail="Received '[object Object]' as request body. In Process Studio, please use 'JSON.stringify(data)' to format your body field as a valid JSON string before sending."
        )

    client_ip = request.client.host if request.client else "127.0.0.1"

    try:
        # Handle Batch List of tickets asynchronously
        if isinstance(payload, list):
            tasks = [asyncio.to_thread(_sync_insert_single_ticket, item, client_ip) for item in payload if isinstance(item, dict)]
            results = await asyncio.gather(*tasks)
            return {
                "success": True,
                "count": len(results),
                "message": f"Successfully processed {len(results)} fraud complaints asynchronously.",
                "tickets": results
            }
        elif isinstance(payload, dict):
            # Run blocking database I/O asynchronously in threadpool
            result = await asyncio.to_thread(_sync_insert_single_ticket, payload, client_ip)
            return result
        else:
            raise HTTPException(status_code=400, detail="Invalid payload format. Expected JSON object or array.")
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as ex:
        logger.error(f"Error creating fraud ticket: {ex}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(ex))


@app.api_route("/api/bulk-dummy-intake", methods=["GET", "POST"], status_code=201, tags=["Fraud Operations"])
async def api_bulk_dummy_intake(request: Request, count: Optional[int] = 20):
    """
    Asynchronous Non-Blocking endpoint to inject 20 (or custom count) realistic dummy fraud tickets into PostgreSQL.
    """
    if request.method == "POST":
        try:
            body = await request.json()
            if isinstance(body, dict) and "count" in body:
                count = int(body["count"])
        except Exception:
            pass

    target_count = max(1, min(100, count or 20))
    client_ip = request.client.host if request.client else "127.0.0.1"

    try:
        # Run bulk insertion asynchronously on threadpool to prevent event loop starvation
        created_tickets = await asyncio.to_thread(_sync_bulk_dummy_intake, target_count, client_ip)
        return {
            "success": True,
            "count": len(created_tickets),
            "message": f"Successfully generated and inserted {len(created_tickets)} dummy fraud tickets asynchronously into PostgreSQL.",
            "tickets": created_tickets
        }
    except Exception as ex:
        logger.error(f"Error generating bulk dummy tickets: {ex}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(ex))


@app.patch("/api/fraud-tickets/{ticket_id}", tags=["Fraud Operations"])
def api_update_ticket(ticket_id: str, payload: FraudTicketUpdateSchema, request: Request):
    """Update ticket status, assigned investigator, and resolution notes."""
    conn = get_db_connection()
    conn.autocommit = True
    cursor = conn.cursor()
    try:
        status_val = payload.status
        if status_val and status_val not in ["UNDER_INVESTIGATION", "FROZEN", "RESOLVED", "CLOSED", "REJECTED", "ESCALATED"]:
            raise HTTPException(status_code=400, detail=f"Invalid status: '{status_val}'")

        assigned_val = payload.assigned_investigator
        action_note = payload.action_taken or ""

        cursor.execute("""
            UPDATE fraud_tickets
            SET status = COALESCE(%s, status),
                assigned_investigator = COALESCE(%s, assigned_investigator),
                action_taken = CASE WHEN %s != '' THEN %s ELSE action_taken END,
                updated_at = CURRENT_TIMESTAMP
            WHERE ticket_id = %s OR ticket_number = %s
            RETURNING ticket_number, customer_id, account_number, assigned_investigator;
        """, (status_val, assigned_val, action_note, action_note, int(ticket_id) if ticket_id.isdigit() else -1, ticket_id))
        res = cursor.fetchone()

        if not res:
            raise HTTPException(status_code=404, detail="Ticket not found")

        ticket_num, cust_id, acc_num, new_assigned = res

        # If status was updated to FROZEN, freeze the account too
        if status_val == "FROZEN":
            cursor.execute("UPDATE customer_accounts SET status = 'FROZEN' WHERE customer_id = %s;", (cust_id,))

        client_ip = request.client.host if request.client else "127.0.0.1"
        actor = request.headers.get("X-User-Name") or DEFAULT_INVESTIGATOR

        # Audit log
        log_action = f"STATUS_{status_val}" if status_val else "ASSIGNED_STAFF_UPDATE"
        log_detail = f"Updated by Officer. Status: {status_val or 'Unchanged'}, Assigned: {new_assigned}. Note: {action_note}"
        cursor.execute("""
            INSERT INTO audit_logs (ticket_number, actor, action, details, ip_address)
            VALUES (%s, %s, %s, %s, %s);
        """, (ticket_num, actor, log_action, log_detail, client_ip))

        conn.commit()
        return {"success": True, "ticket_number": ticket_num, "status": status_val, "assigned_investigator": new_assigned}
    finally:
        cursor.close()
        conn.close()

@app.post("/api/fraud-tickets/bulk-update", tags=["Fraud Operations"])
def api_bulk_update_tickets(payload: BulkTicketUpdateSchema, request: Request):
    """Bulk update status or assigned staff across multiple selected tickets."""
    if not payload.ticket_ids:
        raise HTTPException(status_code=400, detail="No ticket IDs provided")

    conn = get_db_connection()
    conn.autocommit = True
    cursor = conn.cursor()
    try:
        status_val = payload.status
        assigned_val = payload.assigned_investigator
        action_note = payload.action_taken or "Bulk action applied"

        int_ids = [int(i) for i in payload.ticket_ids if str(i).isdigit()]
        str_ids = [str(i) for i in payload.ticket_ids if not str(i).isdigit()]

        cursor.execute("""
            UPDATE fraud_tickets
            SET status = COALESCE(%s, status),
                assigned_investigator = COALESCE(%s, assigned_investigator),
                action_taken = CASE WHEN %s != '' THEN %s ELSE action_taken END,
                recovered_amount = CASE WHEN %s = 'RESOLVED' THEN amount_involved ELSE recovered_amount END,
                updated_at = CURRENT_TIMESTAMP
            WHERE ticket_id = ANY(%s) OR ticket_number = ANY(%s)
            RETURNING ticket_number, customer_id;
        """, (status_val, assigned_val, action_note, action_note, status_val, int_ids or [-1], str_ids or ['__NONE__']))
        
        rows = cursor.fetchall()
        updated_count = len(rows)

        if status_val == "FROZEN":
            cust_ids = [r[1] for r in rows if r[1]]
            if cust_ids:
                cursor.execute("UPDATE customer_accounts SET status = 'FROZEN' WHERE customer_id = ANY(%s);", (cust_ids,))

        client_ip = request.client.host if request.client else "127.0.0.1"
        actor = request.headers.get("X-User-Name") or DEFAULT_INVESTIGATOR
        for r in rows:
            t_num = r[0]
            cursor.execute("""
                INSERT INTO audit_logs (ticket_number, actor, action, details, ip_address)
                VALUES (%s, %s, %s, %s, %s);
            """, (t_num, actor, f"BULK_UPDATE_{status_val or 'STAFF_ASSIGN'}", action_note, client_ip))

        conn.commit()
        return {"success": True, "updated_count": updated_count}
    finally:
        cursor.close()
        conn.close()

@app.post("/api/freeze-account", tags=["Account Actions"])
def api_freeze_account(payload: FreezeAccountSchema, request: Request):
    """Emergency lock an account and linked fraud case."""
    conn = get_db_connection()
    conn.autocommit = True
    cursor = conn.cursor()
    try:
        acc_num = payload.account_number
        ticket_num = payload.ticket_number

        cursor.execute("UPDATE customer_accounts SET status = 'FROZEN' WHERE account_number = %s;", (acc_num,))
        if ticket_num:
            cursor.execute("UPDATE fraud_tickets SET status = 'FROZEN' WHERE ticket_number = %s;", (ticket_num,))

        client_ip = request.client.host if request.client else "127.0.0.1"
        actor = request.headers.get("X-User-Name") or DEFAULT_INVESTIGATOR
        cursor.execute("""
            INSERT INTO audit_logs (ticket_number, actor, action, details, ip_address)
            VALUES (%s, %s, %s, %s, %s);
        """, (ticket_num or "MANUAL_LOCK", actor, "ACCOUNT_EMERGENCY_FREEZE", f"Account {acc_num} frozen due to fraud risk", client_ip))

        conn.commit()
        return {"success": True, "account_number": acc_num, "status": "FROZEN"}
    finally:
        cursor.close()
        conn.close()

@app.get("/api/customers", tags=["Banking Core"])
def api_get_customers(
    page: Optional[int] = None,
    page_size: Optional[int] = None,
    q: Optional[str] = None,
    risk_tier: Optional[str] = None
):
    """List customer profiles with optional FTS search, risk tier filter, and pagination."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        where_clauses = []
        params = []
        if q and q.strip():
            where_clauses.append("c.tsv_search @@ plainto_tsquery('english', %s)")
            params.append(q.strip())
        if risk_tier and risk_tier.strip() and risk_tier.upper() != "ALL":
            where_clauses.append("c.risk_tier = %s")
            params.append(risk_tier.strip().upper())
            
        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
        
        is_paginated = page is not None or page_size is not None
        total_count = None
        if is_paginated:
            count_sql = f"SELECT COUNT(DISTINCT c.customer_id) FROM customers c {where_sql};"
            cursor.execute(count_sql, tuple(params))
            total_count = cursor.fetchone()[0]

        limit_sql = ""
        if is_paginated:
            p = max(1, page or 1)
            ps = max(1, min(200, page_size or 50))
            offset = (p - 1) * ps
            limit_sql = f"LIMIT {ps} OFFSET {offset}"

        sql = f"""
            SELECT 
                c.customer_id, c.customer_code, c.full_name, c.email, c.phone, c.city, c.state, c.risk_tier,
                ca.account_number, ca.account_type, ca.balance, ca.status as account_status, ca.branch,
                COUNT(ft.ticket_id) as fraud_reports_count
            FROM customers c
            LEFT JOIN customer_accounts ca ON c.customer_id = ca.customer_id
            LEFT JOIN fraud_tickets ft ON c.customer_id = ft.customer_id
            {where_sql}
            GROUP BY c.customer_id, c.customer_code, c.full_name, c.email, c.phone, c.city, c.state, c.risk_tier,
                     ca.account_number, ca.account_type, ca.balance, ca.status, ca.branch
            ORDER BY c.customer_id ASC
            {limit_sql};
        """
        cursor.execute(sql, tuple(params))
        rows = cursor.fetchall()
        customers = []
        for r in rows:
            customers.append({
                "customer_id": r[0], "customer_code": r[1], "full_name": r[2], "email": r[3],
                "phone": r[4], "city": r[5], "state": r[6], "risk_tier": r[7],
                "account_number": r[8], "account_type": r[9],
                "balance": float(r[10]) if r[10] is not None else 0.0,
                "account_status": r[11] or 'ACTIVE', "branch": r[12],
                "fraud_reports_count": r[13]
            })
        cleaned_cust = clean_db_record(customers)
        if is_paginated:
            import math
            p = max(1, page or 1)
            ps = max(1, min(200, page_size or 50))
            return {
                "items": cleaned_cust,
                "total": total_count,
                "page": p,
                "page_size": ps,
                "total_pages": math.ceil(total_count / ps) if total_count else 1,
                "has_next": (p * ps) < total_count if total_count else False,
                "has_prev": p > 1
            }
        return cleaned_cust
    finally:
        cursor.close()
        conn.close()

@app.get("/api/reports/audit-pdf", tags=["Audit & Compliance"])
def api_download_audit_pdf(request: Request):
    """Generate and stream an official, authenticated PDF Audit & SAR Compliance Report."""
    if not HAS_REPORTLAB:
        raise HTTPException(status_code=500, detail="ReportLab is not installed on server.")

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Fetch overview stats
        cursor.execute("SELECT COUNT(*), COALESCE(SUM(amount_involved), 0), COALESCE(SUM(recovered_amount), 0) FROM fraud_tickets;")
        tot_row = cursor.fetchone()
        tot_cases = tot_row[0] or 0
        tot_amount = float(tot_row[1] or 0)
        tot_recovered = float(tot_row[2] or 0)

        cursor.execute("SELECT COUNT(*) FROM fraud_tickets WHERE status = 'RESOLVED';")
        solved_count = cursor.fetchone()[0] or 0

        cursor.execute("SELECT COUNT(*) FROM fraud_tickets WHERE status = 'FROZEN';")
        frozen_count = cursor.fetchone()[0] or 0

        # Fetch recent 35 audit logs
        cursor.execute("""
            SELECT log_id, ticket_number, actor, action, details, created_at, ip_address
            FROM audit_logs
            ORDER BY created_at DESC
            LIMIT 35;
        """)
        logs = cursor.fetchall()

        # Build PDF with ReportLab
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=36,
            rightMargin=36,
            topMargin=36,
            bottomMargin=36
        )

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'DocTitle',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=16,
            leading=20,
            textColor=colors.HexColor('#0052cc')
        )
        subtitle_style = ParagraphStyle(
            'DocSubtitle',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=9,
            leading=12,
            textColor=colors.HexColor('#475569')
        )
        section_style = ParagraphStyle(
            'SectionTitle',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=11,
            leading=15,
            textColor=colors.HexColor('#0f172a')
        )
        cell_style = ParagraphStyle(
            'CellText',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=8,
            leading=10,
            textColor=colors.HexColor('#1e293b')
        )
        cell_bold = ParagraphStyle(
            'CellBold',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=8,
            leading=10,
            textColor=colors.HexColor('#0f172a')
        )

        story = []

        # Header Title
        story.append(Paragraph("DUMMY BANK OF INDIA", title_style))
        story.append(Paragraph("Official Fraud Audit & SAR Compliance Report | SOC Operations", subtitle_style))
        story.append(Spacer(1, 6))
        story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor('#0052cc'), spaceBefore=2, spaceAfter=10))

        # Metadata Row
        now_str = datetime.now().strftime("%d %b %Y, %I:%M %p")
        report_id = f"SAR-AUD-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
        meta_data = [
            [
                Paragraph(f"<b>Report ID:</b> {report_id}", cell_style),
                Paragraph(f"<b>Generated At:</b> {now_str}", cell_style)
            ],
            [
                Paragraph("<b>Classification:</b> CONFIDENTIAL / AUDIT GRADE", cell_style),
                Paragraph("<b>Authorizing Unit:</b> Fraud Intelligence & SOC", cell_style)
            ]
        ]
        meta_table = Table(meta_data, colWidths=[260, 260])
        meta_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f8fafc')),
            ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
            ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e2e8f0')),
            ('PADDING', (0,0), (-1,-1), 5),
        ]))
        story.append(meta_table)
        story.append(Spacer(1, 12))

        # Executive Summary Metrics
        story.append(Paragraph("Executive Fraud Metrics Summary", section_style))
        story.append(Spacer(1, 5))

        recovery_rate = round((tot_recovered / tot_amount * 100), 1) if tot_amount > 0 else 0
        summary_headers = [
            Paragraph("<font color='white'><b>Total Cases</b></font>", cell_style),
            Paragraph("<font color='white'><b>Total Exposure</b></font>", cell_style),
            Paragraph("<font color='white'><b>Recovered Funds</b></font>", cell_style),
            Paragraph("<font color='white'><b>Solved Cases</b></font>", cell_style),
            Paragraph("<font color='white'><b>Recovery Rate</b></font>", cell_style)
        ]
        summary_values = [
            Paragraph(f"<b>{tot_cases}</b>", cell_bold),
            Paragraph(f"<b>INR {tot_amount:,.2f}</b>", cell_bold),
            Paragraph(f"<b>INR {tot_recovered:,.2f}</b>", cell_bold),
            Paragraph(f"<b>{solved_count} Cases</b>", cell_bold),
            Paragraph(f"<b>{recovery_rate}%</b>", cell_bold)
        ]
        summary_table = Table([summary_headers, summary_values], colWidths=[104, 110, 110, 100, 96])
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#0052cc')),
            ('BACKGROUND', (0,1), (-1,1), colors.HexColor('#f1f5f9')),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
            ('PADDING', (0,0), (-1,-1), 5),
        ]))
        story.append(summary_table)
        story.append(Spacer(1, 14))

        # Audit Logs Activity Table
        story.append(Paragraph("Staff Forensic Activity & Action Trail (Recent 35 Events)", section_style))
        story.append(Spacer(1, 5))

        audit_headers = [
            Paragraph("<font color='white'><b>Log #</b></font>", cell_style),
            Paragraph("<font color='white'><b>Complaint #</b></font>", cell_style),
            Paragraph("<font color='white'><b>Actor / Staff</b></font>", cell_style),
            Paragraph("<font color='white'><b>Action Taken</b></font>", cell_style),
            Paragraph("<font color='white'><b>Details / Notes</b></font>", cell_style),
            Paragraph("<font color='white'><b>Timestamp</b></font>", cell_style)
        ]
        audit_rows = [audit_headers]
        for log in logs:
            log_id, t_num, actor, action, details, created_at, ip_addr = log
            time_str = created_at.strftime("%d-%m-%Y %H:%M") if hasattr(created_at, 'strftime') else str(created_at)[:16]
            audit_rows.append([
                Paragraph(f"#{log_id}", cell_style),
                Paragraph(f"<b>{t_num}</b>", cell_bold),
                Paragraph(str(actor or 'System Officer')[:22], cell_style),
                Paragraph(str(action or 'UPDATED')[:24], cell_style),
                Paragraph(str(details or 'Staff action executed')[:50], cell_style),
                Paragraph(time_str, cell_style)
            ])

        if len(audit_rows) == 1:
            audit_rows.append([Paragraph("No audit logs recorded yet", cell_style)] * 6)

        audit_table = Table(audit_rows, colWidths=[40, 85, 95, 95, 130, 75])
        audit_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1e293b')),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e2e8f0')),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#f8fafc')]),
            ('PADDING', (0,0), (-1,-1), 4),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ]))
        story.append(audit_table)

        # Footer Notice
        story.append(Spacer(1, 14))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor('#94a3b8'), spaceBefore=4, spaceAfter=6))
        story.append(Paragraph("This document contains confidential banking information generated automatically by Dummy Bank Portal. Any unauthorized distribution, reproduction, or alteration is strictly prohibited under banking regulatory laws.", subtitle_style))

        doc.build(story)
        buffer.seek(0)
        
        pdf_filename = f"Official_Fraud_Audit_Report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        return StreamingResponse(
            buffer,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{pdf_filename}"'}
        )
    finally:
        cursor.close()
        conn.close()

@app.get("/api/transactions", tags=["Banking Core"])
def api_get_transactions(
    page: Optional[int] = None,
    page_size: Optional[int] = None,
    q: Optional[str] = None,
    flagged_only: Optional[bool] = False,
    min_risk: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None
):
    """Retrieve forensic ledger of transactions with partition pruning, FTS, and server-side pagination."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        where_clauses = []
        params = []
        
        if q and q.strip():
            where_clauses.append("to_tsvector('english', coalesce(t.customer_name, '') || ' ' || coalesce(t.txn_reference, '') || ' ' || coalesce(t.account_number, '') || ' ' || coalesce(t.merchant_or_recipient, '') || ' ' || coalesce(t.ip_address, '')) @@ plainto_tsquery('english', %s)")
            params.append(q.strip())
            
        if flagged_only:
            where_clauses.append("t.is_fraud_flagged = TRUE")
            
        if min_risk is not None:
            where_clauses.append("t.fraud_risk_score >= %s")
            params.append(min_risk)
            
        if date_from and date_from.strip():
            where_clauses.append("t.txn_time >= %s")
            params.append(date_from.strip())
            
        if date_to and date_to.strip():
            where_clauses.append("t.txn_time <= %s")
            params.append(date_to.strip() + " 23:59:59")
            
        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
        
        is_paginated = page is not None or page_size is not None
        total_count = None
        
        if is_paginated:
            count_sql = f"SELECT COUNT(*) FROM transactions t JOIN customers c ON t.customer_id = c.customer_id {where_sql};"
            cursor.execute(count_sql, tuple(params))
            total_count = cursor.fetchone()[0]
            
        limit_sql = ""
        if is_paginated:
            p = max(1, page or 1)
            ps = max(1, min(200, page_size or 50))
            offset = (p - 1) * ps
            limit_sql = f"LIMIT {ps} OFFSET {offset}"
            
        sql = f"""
            SELECT 
                t.txn_id, t.txn_reference, t.customer_id, c.full_name, t.account_number,
                t.amount, t.txn_type, t.merchant_or_recipient, t.channel, t.ip_address,
                t.is_fraud_flagged, t.fraud_risk_score, t.status, t.txn_time
            FROM transactions t
            JOIN customers c ON t.customer_id = c.customer_id
            {where_sql}
            ORDER BY t.txn_time DESC, t.txn_id DESC
            {limit_sql};
        """
        cursor.execute(sql, tuple(params))
        rows = cursor.fetchall()
        txns = []
        for r in rows:
            txns.append({
                "txn_id": r[0], "txn_reference": r[1], "customer_id": r[2], "full_name": r[3],
                "account_number": r[4], "amount": float(r[5]), "txn_type": r[6],
                "merchant_or_recipient": r[7], "channel": r[8], "ip_address": r[9],
                "is_fraud_flagged": r[10], "fraud_risk_score": r[11], "status": r[12],
                "txn_time": r[13]
            })
        cleaned_txns = clean_db_record(txns)
        if is_paginated:
            import math
            p = max(1, page or 1)
            ps = max(1, min(200, page_size or 50))
            return {
                "items": cleaned_txns,
                "total": total_count,
                "page": p,
                "page_size": ps,
                "total_pages": math.ceil(total_count / ps) if total_count else 1,
                "has_next": (p * ps) < total_count if total_count else False,
                "has_prev": p > 1
            }
        return cleaned_txns
    finally:
        cursor.close()
        conn.close()

@app.get("/api/analytics", tags=["Analytics & Overview"])
def api_get_analytics():
    """Get multidimensional aggregated metrics by channel, incident type, and severity."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT incident_type, COUNT(*), SUM(amount_involved)
            FROM fraud_tickets
            GROUP BY incident_type
            ORDER BY COUNT(*) DESC;
        """)
        by_type = [{"type": r[0], "count": r[1], "amount": float(r[2])} for r in cursor.fetchall()]

        cursor.execute("""
            SELECT reported_channel, COUNT(*), SUM(amount_involved)
            FROM fraud_tickets
            GROUP BY reported_channel
            ORDER BY COUNT(*) DESC;
        """)
        by_channel = [{"channel": r[0], "count": r[1], "amount": float(r[2])} for r in cursor.fetchall()]

        cursor.execute("""
            SELECT severity, COUNT(*)
            FROM fraud_tickets
            GROUP BY severity;
        """)
        by_severity = {r[0]: r[1] for r in cursor.fetchall()}

        cursor.execute("""
            SELECT status, COUNT(*)
            FROM fraud_tickets
            GROUP BY status;
        """)
        by_status = {r[0]: r[1] for r in cursor.fetchall()}

        return clean_db_record({
            "by_type": by_type,
            "by_channel": by_channel,
            "by_severity": by_severity,
            "by_status": by_status
        })
    finally:
        cursor.close()
        conn.close()

@app.get("/api/audit-logs", tags=["Auditing & Forensics"])
def api_get_audit_logs(
    page: Optional[int] = None,
    page_size: Optional[int] = None,
    q: Optional[str] = None,
    ticket_number: Optional[str] = None
):
    """Retrieve immutable audit log history with optional FTS and pagination."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        where_clauses = []
        params = []
        if q and q.strip():
            where_clauses.append("(actor ILIKE %s OR action ILIKE %s OR details ILIKE %s OR customer_name ILIKE %s)")
            kw = f"%{q.strip()}%"
            params.extend([kw, kw, kw, kw])
        if ticket_number and ticket_number.strip():
            where_clauses.append("ticket_number = %s")
            params.append(ticket_number.strip())
            
        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
        
        is_paginated = page is not None or page_size is not None
        total_count = None
        if is_paginated:
            count_sql = f"SELECT COUNT(*) FROM audit_logs {where_sql};"
            cursor.execute(count_sql, tuple(params))
            total_count = cursor.fetchone()[0]

        limit_sql = "LIMIT 100"
        if is_paginated:
            p = max(1, page or 1)
            ps = max(1, min(200, page_size or 50))
            offset = (p - 1) * ps
            limit_sql = f"LIMIT {ps} OFFSET {offset}"

        sql = f"""
            SELECT log_id, ticket_number, customer_name, actor, action, details, ip_address, created_at
            FROM audit_logs
            {where_sql}
            ORDER BY log_id DESC
            {limit_sql};
        """
        cursor.execute(sql, tuple(params))
        logs = []
        for r in cursor.fetchall():
            logs.append({
                "log_id": r[0], "ticket_number": r[1], "customer_name": r[2], "actor": r[3], "action": r[4],
                "details": r[5], "ip_address": r[6], "created_at": r[7]
            })
        cleaned_logs = clean_db_record(logs)
        if is_paginated:
            import math
            p = max(1, page or 1)
            ps = max(1, min(200, page_size or 50))
            return {
                "items": cleaned_logs,
                "total": total_count,
                "page": p,
                "page_size": ps,
                "total_pages": math.ceil(total_count / ps) if total_count else 1,
                "has_next": (p * ps) < total_count if total_count else False,
                "has_prev": p > 1
            }
        return cleaned_logs
    finally:
        cursor.close()
        conn.close()

@app.get("/api/db-status", tags=["Database Management"])
def api_get_db_status():
    """Direct PostgreSQL schema inspection endpoint (visible in pgAdmin 4)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT version();")
        pg_ver = cursor.fetchone()[0]

        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            ORDER BY table_name;
        """)
        tables = [r[0] for r in cursor.fetchall()]

        table_counts = {}
        for tbl in tables:
            cursor.execute(f"SELECT COUNT(*) FROM {tbl};")
            table_counts[tbl] = cursor.fetchone()[0]

        return clean_db_record({
            "connected": True,
            "database": DB_NAME,
            "host": DB_HOST,
            "port": DB_PORT,
            "user": DB_USER,
            "pgAdmin_info": f"Connected to PostgreSQL on port {DB_PORT} as {DB_USER}. Visible in pgAdmin 4 under Databases > {DB_NAME}.",
            "version": pg_ver,
            "tables": tables,
            "counts": table_counts
        })
    finally:
        cursor.close()
        conn.close()

@app.post("/api/execute-sql", tags=["Database Management"])
def api_execute_sql(payload: SqlExecuteSchema, request: Request):
    """Direct SQL Execution Console for Administrator Queries."""
    if not ENABLE_SQL_CONSOLE:
        raise HTTPException(status_code=403, detail="SQL Console is disabled in this environment.")

    query = payload.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Empty SQL query")

    # In production mode, guard against accidental DROP / TRUNCATE unless authorized
    if APP_ENV == "production" and not verify_api_authorization(request):
        upper_q = query.upper()
        if any(keyword in upper_q for keyword in ["DROP DATABASE", "DROP TABLE", "TRUNCATE"]):
            raise HTTPException(status_code=403, detail="Destructive DDL statements are blocked in production mode.")

    conn = get_db_connection()
    conn.autocommit = True
    cursor = conn.cursor()
    try:
        cursor.execute(query)
        if cursor.description:
            columns = [col[0] for col in cursor.description]
            rows = cursor.fetchall()
            formatted_rows = []
            for row in rows:
                formatted_rows.append([float(c) if isinstance(c, Decimal) else (c.isoformat() if isinstance(c, (datetime, date)) else c) for c in row])
            return clean_db_record({
                "success": True,
                "columns": columns,
                "rows": formatted_rows,
                "row_count": len(rows)
            })
        else:
            return {
                "success": True,
                "message": "Query executed successfully. (No returning rows)",
                "row_count": cursor.rowcount
            }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        cursor.close()
        conn.close()

# -------------------------------------------------------------
# Production Server Entry Point
# -------------------------------------------------------------
def run_production_server():
    print("=" * 75)
    print("  DUMMY BANK PORTAL - ENTERPRISE FRAUD SYSTEM")
    print("  Production ASGI Server: FastAPI + Uvicorn")
    print(f"  Environment: {APP_ENV.upper()}")
    print(f"  Host: http://{PORTAL_HOST}:{PORTAL_PORT}")
    print(f"  Swagger UI Docs: http://{PORTAL_HOST}:{PORTAL_PORT}/docs")
    print(f"  ReDoc Docs:      http://{PORTAL_HOST}:{PORTAL_PORT}/redoc")
    print(f"  Database: PostgreSQL ({DB_NAME}) on port {DB_PORT}")
    print("=" * 75)
    
    uvicorn.run(
        "server:app",
        host=PORTAL_HOST,
        port=PORTAL_PORT,
        log_level=LOG_LEVEL.lower(),
        access_log=True,
        workers=1
    )

if __name__ == "__main__":
    run_production_server()
