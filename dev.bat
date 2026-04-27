@echo off
title RE-AI Dev Server
cd /d "%~dp0"

echo ========================================
echo  RE-AI — Development Mode
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

:: ── Install frontend dependencies (no build) ──
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
cd ..

:: ── Start backend server ──
echo.
echo [..] Starting backend server (port 8000)...
start /B "" .venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

:: ── Wait for backend health ──
echo [..] Waiting for backend to be ready...
set MAX_RETRIES=30
set RETRY_COUNT=0

:waitloop_backend
timeout /t 2 /nobreak >nul
.venv\Scripts\python.exe -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')" >nul 2>&1
if not errorlevel 1 goto backend_ready
set /a RETRY_COUNT+=1
if %RETRY_COUNT% geq %MAX_RETRIES% (
    echo [ERROR] Backend did not start within %MAX_RETRIES% attempts.
    pause
    exit /b 1
)
goto waitloop_backend

:backend_ready
echo [OK] Backend is ready.

:: ── Start Vite dev server ──
echo [..] Starting Vite dev server (port 5173)...
cd frontend
start /B "" cmd /c "npm run dev"
cd ..

:: ── Open browser to Vite ──
echo.
echo Opening browser...
start http://127.0.0.1:5173

echo.
echo ============================================
echo  RE-AI Dev — running!
echo   Backend: http://127.0.0.1:8000
echo   Frontend: http://127.0.0.1:5173
echo  Close this window to stop both servers.
echo ============================================
echo.
pause
