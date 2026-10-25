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
echo.
echo SAM session ended. Press any key to close this window...
pause >nul
