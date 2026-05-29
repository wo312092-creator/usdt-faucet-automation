@echo off
title USDT Faucet Bot - Local
cd /d "%~dp0"

echo ============================================
echo   USDT/TRX FAUCET AUTOMATION - LOCAL RUNNER
echo ============================================
echo.

REM ---- Step 1: Check Python ----
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Please install Python 3.10+ from python.org
    echo         Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)
echo [OK] Python found

REM ---- Step 2: Create virtual env if missing ----
if not exist "venv\" (
    echo [SETUP] Creating virtual environment...
    python -m venv venv
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to create virtual environment
        pause
        exit /b 1
    )
)

REM ---- Step 3: Activate venv and install deps ----
call venv\Scripts\activate.bat
if %errorlevel% neq 0 (
    echo [ERROR] Failed to activate virtual environment
    pause
    exit /b 1
)

echo [SETUP] Installing/updating dependencies...
pip install -q --upgrade pip
pip install -q playwright faster-whisper requests
if %errorlevel% neq 0 (
    echo [ERROR] pip install failed
    pause
    exit /b 1
)

REM ---- Step 4: Install Playwright browsers if missing ----
python -c "from playwright.sync_api import sync_playwright; print('[OK] Playwright already installed')" 2>nul
if %errorlevel% neq 0 (
    echo [SETUP] Installing Playwright browser...
    playwright install chromium
)

REM ---- Step 5: Run claimer ----
echo.
echo ============================================
echo   Starting claimer...
echo   Press Ctrl+C to stop after current run
echo ============================================
echo.

pushd "%~dp0"

:loop
echo.
echo [%date% %time%] ===== Starting claim cycle =====
python claimer_local.py

echo.
echo [%date% %time%] ===== Cycle complete. Waiting 60s before next run... =====
timeout /t 60 /nobreak >nul
goto loop
