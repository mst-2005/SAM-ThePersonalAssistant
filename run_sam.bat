@echo off
title SAM - Personal AI Assistant
cd /d "%~dp0"
echo ========================================================
echo               SAM - Personal AI Assistant
echo ========================================================
echo.
echo Launching SAM core system, GUI HUD, and audio listener...
echo.
python main.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] SAM exited with error code %ERRORLEVEL%.
    pause
)
