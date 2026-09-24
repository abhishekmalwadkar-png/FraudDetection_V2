"""
Central Configuration Loader
Loads environment parameters from .env file for PostgreSQL, pgAdmin, and server settings.
"""

import os
from pathlib import Path

# Load .env using dotenv if available, otherwise manual fallback
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent / ".env"
    load_dotenv(dotenv_path=env_path)
except ImportError:
    # Manual fallback parser
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    os.environ.setdefault(key.strip(), val.strip())

# Application Environment
APP_ENV = os.getenv("APP_ENV", "production").lower()
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# Database Parameters & Connection Pooling
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASS", "")
DB_NAME = os.getenv("DB_NAME", "bank_fraud_portal")
DB_POOL_MIN_CACHED = int(os.getenv("DB_POOL_MIN_CACHED", "5"))
DB_POOL_MAX_CACHED = int(os.getenv("DB_POOL_MAX_CACHED", "25"))
DB_POOL_MAX_CONNECTIONS = int(os.getenv("DB_POOL_MAX_CONNECTIONS", "50"))

# pgAdmin Credentials
PGADMIN_HOST = os.getenv("PGADMIN_HOST", "localhost")
PGADMIN_PORT = int(os.getenv("PGADMIN_PORT", "5432"))
PGADMIN_USER = os.getenv("PGADMIN_USER", "postgres")
PGADMIN_PASSWORD = os.getenv("PGADMIN_PASSWORD", "")
PGADMIN_DEFAULT_DATABASE = os.getenv("PGADMIN_DEFAULT_DATABASE", "bank_fraud_portal")

# Portal Web Server Configuration
PORTAL_HOST = os.getenv("PORTAL_HOST", "127.0.0.1")
PORTAL_PORT = int(os.getenv("PORTAL_PORT", "5050"))
SERVER_THREADS = int(os.getenv("SERVER_THREADS", "16"))
SERVER_CONNECTION_LIMIT = int(os.getenv("SERVER_CONNECTION_LIMIT", "200"))

# Security & Governance
API_SECRET_KEY = os.getenv("API_SECRET_KEY", "").strip()
ENABLE_SQL_CONSOLE = os.getenv("ENABLE_SQL_CONSOLE", "true").lower() in ("true", "1", "yes")
