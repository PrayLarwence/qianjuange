@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv" (
    echo [error] No .venv yet. Run run.bat first to set up.
    pause
    exit /b 1
)

call ".venv\Scripts\activate.bat"
if errorlevel 1 (
    echo [error] Failed to activate virtual environment.
    pause
    exit /b 1
)

REM Install pytest only if it's missing (separate from runtime deps).
python -c "import pytest" 2>nul
if errorlevel 1 (
    echo [setup] Installing pytest...
    python -m pip install --quiet --disable-pip-version-check pytest
)

echo.
echo [test] Running test suite...
echo.
cd backend
python -m pytest %*
set EXITCODE=%errorlevel%
cd ..

echo.
if "%EXITCODE%"=="0" (
    echo [test] all green.
) else (
    echo [test] failed with exit code %EXITCODE%.
)
pause
exit /b %EXITCODE%
