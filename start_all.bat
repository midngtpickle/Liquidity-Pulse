@echo off
TITLE Liquidity-Pulse - Autonomous Launcher
echo ================================================================
echo      LIQUIDITY-PULSE - WINDOWS STANDALONE LAUNCHER
echo ================================================================
echo.

:: Check Python installation
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH!
    echo Please install Python 3.10+ and check "Add Python to PATH".
    pause
    exit /b 1
)

:: Create virtual environment if it doesn't exist
if not exist "venv" (
    echo [1/4] Creating virtual environment...
    python -m venv venv
)

:: Activate virtual environment
echo [2/4] Activating virtual environment & checking dependencies...
call venv\Scripts\activate.bat
pip install -q -r requirements.txt

:: Run Initial Telemetry & Sentinel Pipeline
echo [3/4] Running Quant Engine & Sentinel Orchestrator...
python src/sentinel.py

:: Launch Web Server & WebSocket Listener in parallel
echo [4/4] Starting Dashboard Server & WebSocket Feed...
echo.
echo ================================================================
echo  - Dashboard Terminal: http://localhost:8080
echo  - Telemetry API:       http://localhost:8080/api/telemetry
echo ================================================================
echo.

start "Liquidity Pulse WebSocket Feed" cmd /k "venv\Scripts\activate.bat && python src/ws_feed.py"
start "Liquidity Pulse Dashboard Server" cmd /k "venv\Scripts\activate.bat && python src/server.py --port 8080"

:: Open browser automatically
timeout /t 2 >nul
start http://localhost:8080

echo Press any key to stop all background processes...
pause
