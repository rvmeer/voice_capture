# VoiceCapture - Windows Build Instructions

Complete guide for building VoiceCapture on Windows, including creating an installer.

## Table of Contents
- [Prerequisites](#prerequisites)
- [Quick Build](#quick-build)
- [Detailed Build Steps](#detailed-build-steps)
- [Creating an Installer](#creating-an-installer)
- [Distribution](#distribution)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Required Software

1. **Python 3.11 or 3.12**
   - Download from: https://www.python.org/downloads/windows/
   - ⚠️ During installation, check "Add Python to PATH"

2. **Git** (optional, for cloning)
   - Download from: https://git-scm.com/download/win

3. **FFmpeg**
   - Download from: https://www.gyan.dev/ffmpeg/builds/
   - Choose "ffmpeg-release-essentials.zip"
   - Extract and note the location of `ffmpeg.exe`

4. **Inno Setup** (for creating installer)
   - Download from: https://jrsoftware.org/isdl.php
   - Install to default location

### System Requirements
- Windows 10 or 11 (64-bit)
- 8GB RAM minimum (16GB recommended for large models)
- 5GB free disk space (for Whisper models)

---

## Quick Build

For experienced users, here's the quick version:

```cmd
# 1. Create virtual environment
python -m venv env
env\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Build application
build_app.bat

# 4. (Optional) Create installer
build_installer.bat
```

---

## Detailed Build Steps

### Step 1: Setup Virtual Environment

Open **Command Prompt** or **PowerShell** in the project directory:

```cmd
# Create virtual environment
python -m venv env

# Activate virtual environment
env\Scripts\activate

# Your prompt should now show (env) at the beginning
```

### Step 2: Install Dependencies

```cmd
# Upgrade pip first
python -m pip install --upgrade pip

# Install all required packages
pip install -r requirements.txt
```

This will install:
- PyQt6 (GUI framework)
- openai-whisper (transcription)
- PyInstaller (for building executable)
- All other dependencies

**Note**: Installation may take 5-10 minutes depending on your internet speed.

### Step 3: Configure FFmpeg Path

You have two options:

**Option A: Bundle ffmpeg with the app**

1. Edit `voice_capture_windows.spec`
2. Find the `binaries` section (around line 10)
3. Uncomment and update the ffmpeg path:

```python
binaries=[
    ('C:\\path\\to\\ffmpeg\\bin\\ffmpeg.exe', '.'),
],
```

**Option B: Require users to install ffmpeg separately**

- Keep the `binaries` section empty
- Users will need to place `ffmpeg.exe` in the same folder as `VoiceCapture.exe`

### Step 4: Update Whisper Assets Path

Edit `voice_capture_windows.spec` around line 24:

```python
# Find your Python site-packages location
# Usually: env\Lib\site-packages\whisper\assets
('env\\Lib\\site-packages\\whisper\\assets', 'whisper\\assets'),
```

To find the exact path:
```cmd
python -c "import whisper; import os; print(os.path.dirname(whisper.__file__))"
```

### Step 5: Build the Application

```cmd
build_app.bat
```

This will:
1. Clean previous builds
2. Install PyInstaller (if needed)
3. Build the executable
4. Output to: `dist\VoiceCapture\VoiceCapture.exe`

**Build time**: 2-5 minutes

### Step 6: Test the Application

```cmd
dist\VoiceCapture\VoiceCapture.exe
```

The app should start and appear in the system tray (bottom-right corner of Windows taskbar).

**First run notes**:
- Windows Defender may scan the app (this is normal)
- You may need to allow microphone access
- Whisper models will download on first use (stored in `%USERPROFILE%\.cache\whisper`)

---

## Creating an Installer

An installer makes distribution easier for end users.

### Step 1: Install Inno Setup

Download and install from: https://jrsoftware.org/isdl.php

Default installation location: `C:\Program Files (x86)\Inno Setup 6\`

### Step 2: Build the Installer

```cmd
build_installer.bat
```

This creates: `installer_output\VoiceCapture-Setup-1.0.0.exe`

### Step 3: Test the Installer

1. Run the installer on a clean Windows VM (recommended)
2. Or test on your machine (it will install to `C:\Program Files\VoiceCapture`)
3. Verify the app runs correctly after installation

---

## Distribution

### What to Distribute

**Option 1: Installer (Recommended)**
- File: `VoiceCapture-Setup-1.0.0.exe`
- Size: ~100-300MB (depending on bundled dependencies)
- Users just run the installer

**Option 2: Portable ZIP**
- Zip the entire `dist\VoiceCapture` folder
- Users extract and run `VoiceCapture.exe`
- No installation required

### User Requirements

Users need:
- Windows 10/11 (64-bit)
- 4GB RAM minimum
- FFmpeg (if not bundled)
- Internet connection (for downloading Whisper models)

### Distribution Checklist

- [ ] Test on clean Windows 10 machine
- [ ] Test on clean Windows 11 machine
- [ ] Verify microphone access works
- [ ] Verify transcription works
- [ ] Test with different audio devices
- [ ] Create README for end users
- [ ] Consider code signing (optional, prevents warnings)

---

## Troubleshooting

### Build Issues

**Error: PyInstaller not found**
```cmd
pip install pyinstaller
```

**Error: Module not found during build**
- Check `hiddenimports` in `voice_capture_windows.spec`
- Add missing module to the list

**Error: Whisper assets not found**
- Verify the path in `datas` section of spec file
- Run: `python -c "import whisper; import os; print(os.path.dirname(whisper.__file__))"`

### Runtime Issues

**App doesn't start**
- Run from command prompt to see error messages:
  ```cmd
  cd dist\VoiceCapture
  VoiceCapture.exe
  ```

**FFmpeg not found**
- Place `ffmpeg.exe` in the same folder as `VoiceCapture.exe`
- Or bundle it in the spec file

**Microphone not working**
- Check Windows privacy settings: Settings → Privacy → Microphone
- Allow desktop apps to access microphone

**Whisper models won't download**
- Check internet connection
- Check firewall settings
- Models download to: `C:\Users\YourName\.cache\whisper`

**System tray icon not visible**
- Check taskbar overflow area (click ^ near system clock)
- Enable "Show VoiceCapture icon" in taskbar settings

### Installer Issues

**Inno Setup not found**
- Install from: https://jrsoftware.org/isdl.php
- Or edit `build_installer.bat` with correct path

**Installer fails to create**
- Ensure `dist\VoiceCapture\VoiceCapture.exe` exists
- Run `build_app.bat` first

---

## Advanced Topics

### Code Signing

To avoid Windows SmartScreen warnings:

1. Get a code signing certificate
2. Use `signtool.exe` to sign the executable:
   ```cmd
   signtool sign /f certificate.pfx /p password /t http://timestamp.digicert.com dist\VoiceCapture\VoiceCapture.exe
   ```

### Optimizing Build Size

Edit `voice_capture_windows.spec`:

```python
# Exclude unnecessary packages
excludes=[
    'matplotlib',
    'scipy',
    'IPython',
],
```

### Adding Auto-Update

Consider implementing:
- GitHub Releases for hosting updates
- Update checker in the app
- Silent update mechanism

---

## File Structure After Build

```
project/
├── dist/
│   └── VoiceCapture/
│       ├── VoiceCapture.exe          # Main executable
│       ├── ffmpeg.exe                # (if bundled)
│       ├── _internal/                # Dependencies
│       │   ├── whisper/
│       │   ├── PyQt6/
│       │   └── ...
│       └── ...
├── installer_output/
│   └── VoiceCapture-Setup-1.0.0.exe  # Installer
└── build/                             # Temporary build files
```

---

## Resources

- **PyInstaller Documentation**: https://pyinstaller.org/
- **Inno Setup Documentation**: https://jrsoftware.org/ishelp/
- **FFmpeg Downloads**: https://ffmpeg.org/download.html#build-windows
- **Whisper Documentation**: https://github.com/openai/whisper

---

## Support

For issues specific to Windows:
- Check the project's GitHub issues
- Verify all prerequisites are installed
- Test on a clean Windows VM
- Check Windows Event Viewer for error details

**Windows-specific logs location**:
```
%USERPROFILE%\Documents\VoiceCapture\logs\
```
