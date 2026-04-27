@echo off
title RE-AI Server
cd /d "%~dp0"

echo ========================================
echo  RE-AI — Reverse Engineering AI Assistant
echo ========================================
echo.

:: ── Python detection ──
python --version >nul 2>&1
if errorlevel 1 (
    py -3 --version >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Python not found. Please install Python 3.11+.
        pause
        exit /b 1
    )
    set PYTHON=py -3
) else (
    set PYTHON=python
)

%PYTHON% --version

:: ── Virtual environment ──
if not exist .venv\Scripts\python.exe (
    echo.
    echo [..] Creating virtual environment...
    %PYTHON% -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
) else (
    echo [OK] Virtual environment found.
)

:: ── Install Python dependencies ──
echo.
echo [..] Installing Python dependencies...
.venv\Scripts\python.exe -m pip install -q -r backend\requirements.txt
if errorlevel 1 (
    echo [ERROR] pip install failed.
    pause
    exit /b 1
)
echo [OK] Python dependencies installed.

:: ── Install and build frontend ──
echo.
echo [..] Installing frontend dependencies...
cd frontend
call npm install --silent
if errorlevel 1 (
    echo [ERROR] npm install failed.
    cd ..
    pause
    exit /b 1
)
echo [OK] Frontend dependencies installed.

echo.
echo [..] Building frontend...
call npm run build
if errorlevel 1 (
    echo [ERROR] Frontend build failed.
    cd ..
    pause
    exit /b 1
)
echo [OK] Frontend built.
cd ..

:: ── Start backend server ──
echo.
echo [..] Starting server...
start /B "" .venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

:: ── Wait for server health endpoint ──
echo [..] Waiting for server to be ready...
set MAX_RETRIES=30
set RETRY_COUNT=0

:waitloop
timeout /t 2 /nobreak >nul
.venv\Scripts\python.exe -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')" >nul 2>&1
if not errorlevel 1 goto server_ready
set /a RETRY_COUNT+=1
if %RETRY_COUNT% geq %MAX_RETRIES% (
    echo [ERROR] Server did not start within %MAX_RETRIES% attempts.
    echo        Check for errors above and try again.
    pause
    exit /b 1
)
goto waitloop

:server_ready
echo [OK] Server is ready at http://127.0.0.1:8000

:: ── Open browser ──
echo.
echo Opening browser...
start http://127.0.0.1:8000

echo.
echo ========================================
echo  RE-AI is running!
echo  Close this window to stop the server.
echo ========================================
echo.
pause
