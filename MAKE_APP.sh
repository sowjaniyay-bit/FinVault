#!/bin/bash
echo ""
echo " ================================================"
echo "  FinVault - Starting your Finance App..."
echo " ================================================"
echo ""
echo " [1/3] Checking Python..."
if ! command -v python3 &> /dev/null; then
    echo " ERROR: Python3 not found. Install it first."
    exit 1
fi
echo " Python found!"
echo " [2/3] Installing packages..."
pip3 install flask flask-cors PyJWT requests -q
echo " [3/3] Starting backend..."
cd backend && python3 app.py &
cd ..
sleep 2
echo " Opening app..."
open frontend/home_app.html 2>/dev/null || xdg-open frontend/home_app.html 2>/dev/null
echo " FinVault is running! Press Ctrl+C to stop."
wait
