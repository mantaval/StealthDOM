@echo off
:: StealthDOM Bridge Server - Windows Startup Script
:: This script starts the bridge server in a hidden window.
:: Add to Windows Startup folder or Task Scheduler to auto-start on boot.
::
:: To install to Startup folder, run:
::   copy start_bridge.bat "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\"
::
:: To remove from Startup:
::   del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\start_bridge.bat"

title StealthDOM Bridge
cd /d "%~dp0"

echo [StealthDOM] Starting bridge server...
echo [StealthDOM] Press Ctrl+C to stop.
echo.

python bridge_server.py

if errorlevel 1 (
    echo.
    echo [StealthDOM] Bridge server crashed. Press any key to restart...
    pause >nul
    goto :0
)
