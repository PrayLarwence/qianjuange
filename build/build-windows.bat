@echo off
REM Build Qianjuange.exe (千卷阁 Windows 桌面 app).
REM
REM 前置:
REM   1) 已经装好 .venv-build (Python 3.13, 见 backend\requirements-packaging.txt)
REM   2) frontend-next 已经 npm install
REM
REM 用法: build\build-windows.bat
chcp 65001 >nul
setlocal
cd /d "%~dp0\.."

if not exist ".venv-build\Scripts\pyinstaller.exe" (
    echo [error] .venv-build not ready. 先用 Python 3.13 起 venv 并装 backend\requirements-packaging.txt.
    exit /b 1
)

echo [build] frontend-next: npm run build
pushd frontend-next
call npm run build
if errorlevel 1 (
    popd
    echo [error] frontend build failed.
    exit /b 1
)
popd

echo [build] PyInstaller
.venv-build\Scripts\pyinstaller --noconfirm --distpath build\dist --workpath build\build build\qianjuange.spec
if errorlevel 1 (
    echo [error] pyinstaller failed.
    exit /b 1
)

echo.
echo [done] 产物: build\dist\Qianjuange\Qianjuange.exe
endlocal
