@echo off
REM Build VoiceCapture installer using Inno Setup
REM Requires Inno Setup to be installed: https://jrsoftware.org/isdl.php

echo ============================================================
echo Building VoiceCapture Installer
echo ============================================================
echo.

REM Check if the app has been built
if not exist "dist\VoiceCapture\VoiceCapture.exe" (
    echo ERROR: Application not built yet!
    echo Please run build_app.bat first
    exit /b 1
)

REM Try to find Inno Setup in common installation paths
set INNO_SETUP=""
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" (
    set INNO_SETUP="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
)
if exist "C:\Program Files\Inno Setup 6\ISCC.exe" (
    set INNO_SETUP="C:\Program Files\Inno Setup 6\ISCC.exe"
)

if %INNO_SETUP%=="" (
    echo ERROR: Inno Setup not found!
    echo Please install Inno Setup from: https://jrsoftware.org/isdl.php
    echo.
    echo Expected location: C:\Program Files (x86)\Inno Setup 6\
    exit /b 1
)

echo Found Inno Setup: %INNO_SETUP%
echo.

echo Building installer...
%INNO_SETUP% installer.iss
if %ERRORLEVEL% neq 0 (
    echo   [ERROR] Installer build failed!
    exit /b 1
)
echo   [OK] Installer created
echo.

echo ============================================================
echo Installer Build Complete
echo ============================================================
echo Installer location: installer_output\VoiceCapture-Setup-1.0.0.exe
echo.
echo You can now distribute this installer to Windows users!
echo ============================================================
