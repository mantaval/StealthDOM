@echo off
:: StealthDOM One-Click Uninstaller
:: Double-click this file to remove StealthDOM configuration.

title StealthDOM Uninstaller
cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0scripts\_uninstall.ps1"
if errorlevel 1 (
    echo.
    echo [ERROR] Uninstall script encountered an error.
    echo Press any key to exit...
    pause >nul
)
