@echo off
title FinVault - Finance App
color 0D
echo.
echo  ====================================================
echo    💜  FinVault - Personal Finance App
echo  ====================================================
echo.

echo  Step 1: Checking Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo  ❌ Python is not installed!
    echo  Please download and install Python from:
    echo  https://python.org/downloads
    echo.
    echo  IMPORTANT: During install, check the box that says
    echo  "Add Python to PATH"
    echo.
    start https://python.org/downloads
    pause
    exit
)
for /f "tokens=*" %%i in ('python --version') do echo  ✅ %%i found!

echo.
echo  Step 2: Installing required packages (first time may take 1 min)...
cd /d "%~dp0backend"
pip install flask flask-cors PyJWT requests --quiet --disable-pip-version-check
if %errorlevel% neq 0 (
    echo  ❌ Package install failed. Try running as Administrator.
    pause
    exit
)
echo  ✅ All packages ready!

echo.
echo  Step 3: Starting FinVault...
start /min "" python app.py
timeout /t 2 /nobreak >nul

echo.
echo  ====================================================
echo    ✅  FinVault is running!
echo    
echo    Opening in your browser now...
echo.
echo    📱 To install on PHONE:
echo    1. Make sure phone is on same WiFi
echo    2. Find your IP: run ipconfig in cmd
echo    3. Open in phone Chrome/Safari:
echo       http://YOUR_IP:5500/frontend/home_app.html
echo    4. Tap "Add to Home Screen"
echo  ====================================================
echo.
cd /d "%~dp0"
start "" "frontend\home_app.html"
echo  Press any key to STOP FinVault...
pause >nul
taskkill /f /im python.exe >nul 2>&1
echo  FinVault stopped. Goodbye!
