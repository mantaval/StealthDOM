@echo off
:: StealthDOM - Remove Windows Startup Task
:: Right-click this file → "Run as administrator"
::
:: Removes the scheduled task so the bridge no longer starts on login.

set TASK_NAME=StealthDOM Bridge Server

echo [StealthDOM] Removing startup task...
schtasks /delete /tn "%TASK_NAME%" /f
if errorlevel 1 (
    echo.
    echo [StealthDOM] Failed. Make sure you right-clicked and selected "Run as administrator".
    echo.
    pause
) else (
    echo.
    echo [StealthDOM] Removed from startup. Bridge will no longer start on login.
    echo.
    pause
)
