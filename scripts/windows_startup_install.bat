@echo off
:: StealthDOM - Install Windows Startup Task
:: Right-click this file → "Run as administrator"
::
:: Creates a Windows Task Scheduler task that starts the bridge
:: server automatically when you log in. Runs silently in the
:: background using pythonw (no terminal window).

set TASK_NAME=StealthDOM Bridge Server
set SCRIPT_DIR=%~dp0

echo [StealthDOM] Installing startup task...
schtasks /create /tn "%TASK_NAME%" /tr "pythonw \"%SCRIPT_DIR%bridge_server.py\"" /sc onlogon /rl highest /f
if errorlevel 1 (
    echo.
    echo [StealthDOM] Failed. Make sure you right-clicked and selected "Run as administrator".
    echo.
    pause
) else (
    echo.
    echo [StealthDOM] Installed! Bridge will start automatically on login.
    echo [StealthDOM] Task name: %TASK_NAME%
    echo.
    pause
)
