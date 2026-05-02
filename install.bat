@echo off
:: StealthDOM One-Click Installer
:: Double-click this file to install StealthDOM automatically.

title StealthDOM Installer
cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0scripts\_install.ps1"
if errorlevel 1 (
    echo.
    echo [ERROR] Installation script encountered an error.
    echo Press any key to exit...
    pause >nul
)
