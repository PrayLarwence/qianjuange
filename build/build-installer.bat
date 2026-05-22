@echo off
REM Build Qianjuange installer (.exe). 端到端: 前端 + PyInstaller + Inno Setup.
REM
REM 用法: build\build-installer.bat
chcp 65001 >nul
setlocal
cd /d "%~dp0\.."

REM ---- 1) PyInstaller (含前端构建 + spec 编译) ----
call build\build-windows.bat
if errorlevel 1 (
    echo [error] build-windows.bat 失败.
    exit /b 1
)

REM ---- 2) 找 ISCC ----
set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=C:\Program Files\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
    echo [error] 没找到 ISCC.exe. 装一下 Inno Setup 6:
    echo         winget install --id JRSoftware.InnoSetup -e
    exit /b 1
)

REM ---- 3) 编译安装包 ----
echo [installer] 编译 build\qianjuange.iss
"%ISCC%" build\qianjuange.iss
if errorlevel 1 (
    echo [error] Inno Setup 编译失败.
    exit /b 1
)

echo.
echo [done] 安装包: build\installer\Qianjuange-Setup-*.exe
endlocal
