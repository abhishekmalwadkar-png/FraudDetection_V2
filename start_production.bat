@echo off
REM ============================================================================
REM Dummy Bank Portal - Production ASGI Server Launcher (FastAPI + Uvicorn)
REM High-Concurrency Async Gateway with PostgreSQL Connection Pooling & Swagger UI
REM ============================================================================

title Dummy Bank Portal - Fraud Detection Portal (FastAPI + Uvicorn)

echo ============================================================================
echo   DUMMY BANK PORTAL - FRAUD OPERATIONS SYSTEM
echo   Starting Production ASGI Server (FastAPI + Uvicorn + DBUtils PooledDB)
echo ============================================================================
echo.

REM Verify Python environment
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not found in system PATH. Please install Python 3.10+
    pause
    exit /b 1
)

REM Check if .env file exists
if not exist .env (
    echo [WARNING] .env file not found. Creating from .env.example...
    copy .env.example .env
    echo [!] Please update database credentials in .env and restart.
)

REM Pre-flight database check & dependency verify
echo [*] Checking FastAPI and database dependencies...
python -c "import pg8000, fastapi, uvicorn, pydantic, dbutils, dotenv; print('[OK] Core python dependencies verified.')"
if %errorlevel% neq 0 (
    echo [*] Installing required packages...
    pip install -r requirements.txt
)

echo.
echo [*] Launching Production FastAPI ASGI Server...
echo [*] Web Portal UI:   http://127.0.0.1:5050
echo [*] Swagger API Docs: http://127.0.0.1:5050/docs
echo [*] ReDoc Docs:       http://127.0.0.1:5050/redoc
echo [*] API Health:       http://127.0.0.1:5050/health
echo [*] API Metrics:      http://127.0.0.1:5050/api/metrics
echo.
echo Press Ctrl+C to stop the server.
echo ============================================================================
echo.

python server.py
pause
