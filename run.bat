@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv" (
    echo [setup] Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo.
        echo [error] Python not found or venv creation failed.
        echo Please install Python 3.10+ from https://www.python.org and ensure it is on PATH.
        pause
        exit /b 1
    )
)

call ".venv\Scripts\activate.bat"
if errorlevel 1 (
    echo [error] Failed to activate virtual environment.
    pause
    exit /b 1
)

REM Only run pip install if requirements.txt changed since last install.
REM We compare the file's timestamp marker stored in .venv\.req_stamp.
set REQ=backend\requirements.txt
set STAMP=.venv\.req_stamp
set NEED_INSTALL=0
if not exist "%STAMP%" set NEED_INSTALL=1
if exist "%STAMP%" (
    for /f %%i in ('xcopy /DHYL "%REQ%" "%STAMP%" /L ^| find /c ":\"') do if %%i gtr 0 set NEED_INSTALL=1
)
if "%NEED_INSTALL%"=="1" (
    echo [setup] Installing/updating dependencies...
    python -m pip install --quiet --disable-pip-version-check -r "%REQ%"
    if errorlevel 1 (
        echo [error] Dependency install failed.
        pause
        exit /b 1
    )
    copy /Y "%REQ%" "%STAMP%" >nul
) else (
    echo [setup] Dependencies up to date, skipping install.
)

if not exist ".env" (
    copy ".env.example" ".env" >nul
    echo [setup] .env created. You can fill API keys here, or use the in-app gear icon after launch.
)

REM Set RELOAD=0 to disable auto-reload for faster startup.
if not defined RELOAD set RELOAD=1
set RELOAD_FLAG=
if "%RELOAD%"=="1" set RELOAD_FLAG=--reload

echo.
echo [run] Starting Narrative Sandbox at http://localhost:8000
echo [run] Press CTRL+C to stop.  (set RELOAD=0 to start without --reload)
echo.
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --app-dir backend %RELOAD_FLAG%
echo.
echo [run] server exited (code %errorlevel%). Press any key to close.
pause >nul
