@echo off
setlocal
title AURORA v1.02 Control Center
cd /d "%~dp0"

echo ===============================================
echo AURORA v1.02 - one-click research control center
echo ===============================================
echo.
echo This window checks Python/config/database/API status, starts Aurora,
echo and keeps a live terminal dashboard open with current status, ETA,
echo keyword stack, worker activity, and last OpenRouter/API error.
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\aurora-control.ps1" start -Headless

echo.
echo AURORA terminal closed. Review the status above.
echo Press any key to close this window.
pause >nul
