@echo off
title SAM - Personal AI Assistant
cd /d "%~dp0"
echo ========================================================
echo               SAM - Personal AI Assistant
echo ========================================================
echo.

set "PY_EXE="
if exist "C:\Users\comma\AppData\Local\Programs\Python\Python313\python.exe" (
    set "PY_EXE=C:\Users\comma\AppData\Local\Programs\Python\Python313\python.exe"
) else (
    where py.exe >nul 2>&1
    if not errorlevel 1 (
        set "PY_EXE=py -3"
    ) else (
        set "PY_EXE=python"
    )
)

echo Using Python runtime: %PY_EXE%
echo Starting SAM Desktop HUD and Neural Audio Matrix...
echo.

%PY_EXE% main.py
set EXIT_CODE=%ERRORLEVEL%

echo.
if %EXIT_CODE% NEQ 0 (
    echo [ERROR] SAM exited with status code: %EXIT_CODE%
) else (
    echo [INFO] SAM session concluded cleanly.
)
echo.
echo Press any key to close this terminal...
pause >nul
