@echo off
setlocal

:: Ga naar de folder waar dit script staat
cd /d "%~dp0"

:: Check of ffmpeg geinstalleerd is
where ffmpeg >nul 2>&1
if errorlevel 1 (
    echo ffmpeg niet gevonden, wordt geinstalleerd via winget...
    winget install ffmpeg --accept-package-agreements --accept-source-agreements
    if errorlevel 1 (
        echo FOUT: Kon ffmpeg niet installeren.
        echo Installeer ffmpeg handmatig of zorg dat winget beschikbaar is.
        pause
        exit /b 1
    )
    echo ffmpeg succesvol geinstalleerd!
    echo Herstart deze terminal om ffmpeg te kunnen gebruiken.
    pause
    exit /b 0
)

:: Check of desktop snelkoppeling bestaat, zo niet, maak aan
for /f "delims=" %%i in ('powershell -Command "[Environment]::GetFolderPath('Desktop')"') do set "DESKTOP=%%i"
if not exist "%DESKTOP%\VoiceCapture.lnk" (
    echo Desktop snelkoppeling wordt aangemaakt...
    powershell -ExecutionPolicy Bypass -Command "$WshShell = New-Object -ComObject WScript.Shell; $Shortcut = $WshShell.CreateShortcut('%DESKTOP%\VoiceCapture.lnk'); $Shortcut.TargetPath = '%~dp0VoiceCapture.bat'; $Shortcut.WorkingDirectory = '%~dp0'; $Shortcut.IconLocation = '%~dp0icon.ico'; $Shortcut.Description = 'VoiceCapture - Audio opname met transcriptie'; $Shortcut.Save()"
    echo Snelkoppeling aangemaakt op bureaublad!
)

:: Check of het python environment bestaat
if not exist "env\Scripts\python.exe" (
    echo Python environment niet gevonden, wordt aangemaakt...
    python -m venv env
    if errorlevel 1 (
        echo FOUT: Kon python environment niet aanmaken.
        echo Zorg dat Python is geinstalleerd en in je PATH staat.
        pause
        exit /b 1
    )
    echo Dependencies installeren...
    call env\Scripts\pip.exe install -r requirements.txt
    if errorlevel 1 (
        echo FOUT: Kon dependencies niet installeren.
        pause
        exit /b 1
    )
    echo PyTorch met CUDA ondersteuning installeren...
    call env\Scripts\pip.exe install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124
    if errorlevel 1 (
        echo FOUT: Kon PyTorch niet installeren.
        pause
        exit /b 1
    )
    echo Environment succesvol aangemaakt!
)

:: Start de applicatie
echo VoiceCapture starten...
call env\Scripts\python.exe main.py

endlocal
