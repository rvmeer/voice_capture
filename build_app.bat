@echo off
REM Build script for VoiceCapture Windows app
REM This script builds the Windows executable using PyInstaller

echo ============================================================
echo Building VoiceCapture Windows App
echo ============================================================
echo.

REM Check if virtual environment is activated
where python >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo ERROR: Python not found in PATH
    echo Please activate your virtual environment first:
    echo   env\Scripts\activate
    exit /b 1
)

REM Check if PyInstaller is installed
python -c "import PyInstaller" >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo ERROR: PyInstaller not found
    echo Installing PyInstaller...
    pip install pyinstaller
)

echo Step 1: Cleaning previous build...
if exist build rmdir /s /q build
if exist dist\VoiceCapture rmdir /s /q dist\VoiceCapture
echo   [OK] Cleaned build directories
echo.

echo Step 2: Building executable with PyInstaller...
pyinstaller --noconfirm voice_capture_windows.spec
if %ERRORLEVEL% neq 0 (
    echo   [ERROR] Build failed!
    exit /b 1
)
echo   [OK] Build completed
echo.

echo ============================================================
echo Build Summary
echo ============================================================
echo Executable location: dist\VoiceCapture\VoiceCapture.exe
echo.
echo To run the app:
echo   dist\VoiceCapture\VoiceCapture.exe
echo.
echo To create an installer:
echo   Run build_installer.bat (requires Inno Setup)
echo ============================================================
