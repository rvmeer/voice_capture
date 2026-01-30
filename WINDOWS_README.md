# VoiceCapture for Windows

Real-time audio transcription using OpenAI Whisper - Windows Edition

## Quick Start

### For End Users (Pre-built Installer)

1. **Download** `VoiceCapture-Setup-1.0.0.exe`
2. **Run** the installer
3. **Launch** VoiceCapture from Start Menu or Desktop
4. **Look** for the icon in system tray (bottom-right, near clock)
5. **Right-click** the tray icon to start recording

### For Developers (Running from Source)

**Easiest: Use VoiceCapture.bat**

Simply double-click `VoiceCapture.bat` - it handles everything automatically:
1. Creates Python virtual environment (`env`) if needed
2. Installs dependencies from `requirements.txt`
3. Installs ffmpeg via winget if not present
4. Starts the application

You can copy `VoiceCapture.bat` to your Desktop for easy access.

**Manual setup:**

```cmd
# 1. Install ffmpeg (required for audio processing)
winget install ffmpeg

# 2. Create and activate Python environment
python -m venv env
env\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Create version.py (if missing)
echo __version__ = "1.0.0" > version.py
echo def get_version_string(): return __version__ >> version.py

# 5. Run the application
python main.py
```

**Building installer:**

See [BUILD_INSTRUCTIONS_WINDOWS.md](BUILD_INSTRUCTIONS_WINDOWS.md) for detailed instructions.

```cmd
build_app.bat
```

---

## First Time Setup

### 1. FFmpeg Installation

VoiceCapture requires FFmpeg for audio processing.

**Option A: Via winget (Recommended)**
```cmd
winget install ffmpeg
```
Herstart je terminal na installatie.

**Option B: Handmatig**
1. Download FFmpeg: https://www.gyan.dev/ffmpeg/builds/
2. Pak het ZIP bestand uit naar `C:\ffmpeg`
3. Voeg `C:\ffmpeg\bin` toe aan je Windows PATH
4. Herstart je terminal

**Verificatie:**
```cmd
ffmpeg -version
```

### 2. Microphone Permissions

Windows 10/11 require microphone permissions:

1. Go to **Settings** → **Privacy** → **Microphone**
2. Enable **"Allow desktop apps to access your microphone"**
3. If VoiceCapture doesn't appear, restart the app

### 3. Whisper Models

Whisper models download automatically on first use:

- **Tiny** (72 MB) - Fast, less accurate
- **Small** (461 MB) - Good balance
- **Medium** (1.4 GB) - Default, recommended
- **Large** (2.9 GB) - Most accurate, slower

**Download location**: `C:\Users\YourName\.cache\whisper`

Models only download once and are reused.

---

## Using VoiceCapture

### System Tray Icon

VoiceCapture runs in the system tray (bottom-right corner of taskbar):

- **White circle** = Ready, not recording
- **Red circle** = Recording in progress

**Can't find the icon?**
- Click the **^** (Show hidden icons) near the system clock
- Right-click taskbar → Taskbar settings → Select which icons appear

### Recording Controls

**Right-click** the tray icon to access:

- **Start Recording** - Begin capturing audio
- **Stop Recording** - End current recording
- **Select Model** - Choose Whisper model (tiny/small/medium/large)
- **Audio Input Device** - Choose microphone
- **View Recordings** - Open recordings folder
- **Quit** - Exit VoiceCapture

### Recordings Location

All recordings are saved to:
```
C:\Users\YourName\Documents\VoiceCapture\
```

Each recording includes:
- **Audio file** (.wav)
- **Transcription** (.txt)
- **Metadata** (.json)
- **Segments** (30-second chunks)

---

## Features

### Real-time Transcription
- Transcribes while recording (30-second segments)
- See results immediately
- No waiting for entire recording to finish

### Multiple Whisper Models
- Choose speed vs accuracy
- Switch models anytime
- Models cached locally

### Audio Device Selection
- Support for multiple microphones
- USB microphones
- Virtual audio cables
- Bluetooth devices

### API Access
- REST API on port 8000
- Access recordings programmatically
- Integrate with other tools
- See API_INTEGRATION.md for details

### MCP Server
- Model Context Protocol support
- Use with Claude Desktop and other AI tools
- See MCP_README.md for setup
- See [Claude Desktop MCP Setup](#claude-desktop-mcp-setup) below for Windows configuration

---

## Keyboard Shortcuts

Currently no global hotkeys (Windows limitation for tray apps).

**Feature request?** Open an issue on GitHub!

---

## Troubleshooting

### App Won't Start

**Check 1: Run from Command Prompt**
```cmd
cd "C:\Program Files\VoiceCapture"
VoiceCapture.exe
```
Look for error messages.

**Check 2: Dependencies**
- Ensure FFmpeg is installed/bundled
- Check Windows Event Viewer for errors

**Check 3: Antivirus**
- Some antivirus programs block PyInstaller apps
- Add exception for VoiceCapture.exe

### No Audio Recording

**Check 1: Microphone Permissions**
- Settings → Privacy → Microphone
- Enable for desktop apps

**Check 2: Audio Device**
- Right-click tray icon → Audio Input Device
- Select correct microphone
- Test microphone in Windows Sound settings

**Check 3: Windows Sound Settings**
- Right-click speaker icon in taskbar
- Open Sound settings
- Ensure microphone is not muted/disabled

### Transcription Not Working

**Check 1: Internet Connection**
- First use requires downloading Whisper models
- Check firewall settings

**Check 2: Model Download**
- Check: `C:\Users\YourName\.cache\whisper`
- Should contain .pt files

**Check 3: Logs**
- Check: `C:\Users\YourName\Documents\VoiceCapture\logs\`
- Look for error messages

### Poor Transcription Quality

**Try these:**
1. Use a higher quality model (medium or large)
2. Improve microphone quality/positioning
3. Reduce background noise
4. Speak clearly and at moderate pace
5. Check if correct language is set (currently hardcoded to Dutch)

### System Tray Icon Missing

**Find the icon:**
1. Click **^** (Show hidden icons) in taskbar
2. Drag VoiceCapture icon to always show
3. Or: Taskbar settings → Select which icons appear

**Icon stuck:**
- Close and restart VoiceCapture
- If multiple icons appear, check Task Manager for duplicate processes

### High CPU/Memory Usage

**During recording:**
- Normal - real-time transcription is CPU intensive
- Medium model uses ~2-4GB RAM
- Large model uses ~4-8GB RAM

**When idle:**
- Should use minimal resources (<50MB RAM)
- If high, check logs for errors

---

## Performance Tips

### For Best Performance:
- Use **Medium** model (good balance)
- Close unnecessary programs during recording
- Use wired microphone (USB) vs Bluetooth
- Ensure good internet for initial model download

### For Slower Computers:
- Use **Tiny** or **Small** model
- Close browser and heavy applications
- Consider upgrading RAM (8GB minimum)

### For Maximum Accuracy:
- Use **Large** model
- High-quality microphone
- Quiet environment
- Speak clearly at moderate pace

---

## API Usage

VoiceCapture includes a REST API on port 8000.

**Quick test:**
Open browser to: http://localhost:8000/docs

**Use cases:**
- Automate recording from scripts
- Integrate with other applications
- Build custom interfaces
- Export to other formats

See [API_INTEGRATION.md](API_INTEGRATION.md) for complete documentation.

---

## Claude Desktop MCP Setup

VoiceCapture includes an MCP (Model Context Protocol) server that allows Claude Desktop to access your recordings and transcriptions.

### Configuration

1. **Locate the Claude Desktop config file:**
   ```
   %APPDATA%\Claude\claude_desktop_config.json
   ```
   Full path example: `C:\Users\YourName\AppData\Roaming\Claude\claude_desktop_config.json`

2. **Create or edit the config file** with the following content:
   ```json
   {
     "mcpServers": {
       "voice-capture": {
         "command": "C:\\Users\\YourName\\git\\voice_capture\\env\\Scripts\\python.exe",
         "args": ["C:\\Users\\YourName\\git\\voice_capture\\mcp_server.py"]
       }
     }
   }
   ```

   **Important:** Replace `YourName` with your Windows username and adjust the path to match your installation location.

3. **Restart Claude Desktop** to load the MCP server.

### Verifying the Connection

After restarting Claude Desktop, you can ask Claude:
- "List my voice recordings"
- "Show me the transcription from my last recording"
- "Summarize my most recent voice note"

### Available MCP Tools

The VoiceCapture MCP server provides these tools to Claude:
- `list_recordings` - List all recordings with metadata
- `get_transcription` - Get full transcription of a recording
- `get_transcription_summary` - Get metadata and preview of a transcription
- `get_transcription_chunked` - Get transcription in chunks (for long recordings)
- `update_recording_title` - Update the title of a recording

See [MCP_README.md](MCP_README.md) for complete MCP documentation.

---

## Uninstalling

### If installed via installer:
1. Settings → Apps → Installed apps
2. Find "VoiceCapture"
3. Click ... → Uninstall

### If using portable version:
1. Delete the VoiceCapture folder
2. Optionally delete recordings:
   - `C:\Users\YourName\Documents\VoiceCapture`
3. Optionally delete Whisper models:
   - `C:\Users\YourName\.cache\whisper`

---

## Windows-Specific Notes

### Windows Defender
- May show SmartScreen warning for unsigned apps
- Click "More info" → "Run anyway"
- App is safe but not code-signed

### Startup on Boot
- Installer offers option to "Start at Windows startup"
- Or manually: Create shortcut in:
  ```
  C:\Users\YourName\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup
  ```

### Multiple Users
- Each Windows user has separate recordings
- Whisper models are shared (saved in .cache)

### Network Drives
- Can save recordings to network drives
- Edit code to change recordings location
- May impact performance

---

## Support & Feedback

**Documentation:**
- Full build instructions: BUILD_INSTRUCTIONS_WINDOWS.md
- API documentation: API_INTEGRATION.md
- MCP integration: MCP_README.md

**Issues:**
- Report bugs on GitHub
- Include log files from:
  `C:\Users\YourName\Documents\VoiceCapture\logs\`

**Feature Requests:**
- Open GitHub issue with "[Windows]" prefix
- Describe use case and expected behavior

---

## System Requirements

**Minimum:**
- Windows 10 (64-bit)
- 4GB RAM
- 2GB free disk space
- Internet connection (for model downloads)

**Recommended:**
- Windows 11 (64-bit)
- 8GB RAM
- 10GB free disk space (for all models)
- SSD for better performance

**Supported Audio:**
- Built-in microphones
- USB microphones
- Bluetooth headsets (may have latency)
- Virtual audio cables
- Line-in devices

---

## Privacy

**Data Collection:**
- No telemetry or analytics
- No data sent to external servers (except Whisper model downloads)
- All recordings stay on your computer

**API Server:**
- Runs locally only (localhost:8000)
- No external access by default
- Firewall may prompt for permissions (allow if you want API access)

---

## License

See LICENSE file for details.

---

## Credits

- **OpenAI Whisper** - Transcription engine
- **PyQt6** - User interface
- **FFmpeg** - Audio processing
- **PyInstaller** - Windows packaging

---

**Enjoy using VoiceCapture! 🎤**
