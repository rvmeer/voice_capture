# Quick Build Guide - VoiceCapture App

## Stap 1: Vereisten installeren

```bash
# Installeer ffmpeg (als je dat nog niet hebt)
brew install ffmpeg

# Installeer PyInstaller
pip install pyinstaller
```

## Stap 2: Bouw de app

```bash
# Run het build script
./build_app.sh
```

## Stap 3: Test de app

```bash
# Optie 1: Open de app direct
open dist/VoiceCapture.app

# Optie 2: Test vanaf command line (om logs te zien)
./dist/VoiceCapture.app/Contents/MacOS/VoiceCapture
```

## Stap 4: Installeer (optioneel)

```bash
# Kopieer naar Applications folder
cp -r dist/VoiceCapture.app /Applications/
```

## Belangrijke wijzigingen

### ✅ ffmpeg Fix
De app bundelt nu ffmpeg automatisch, zodat audio transcriptie ook werkt in de gebouwde app.

### ✅ Logging
Alle logs worden opgeslagen in: `~/Documents/VoiceCapture/logs/`
- Console output: INFO level en hoger
- File output: Alle levels (DEBUG, INFO, WARNING, ERROR)

### ✅ MCP Server
De MCP server (`mcp_server.py`) schrijft **alleen naar logfiles**, niet naar stdout (om JSON-RPC communicatie niet te verstoren).

## Troubleshooting

### Problem: "ffmpeg not found" error

**Oplossing:**
1. Check of ffmpeg geïnstalleerd is: `which ffmpeg`
2. Als het ergens anders staat dan `/opt/homebrew/bin/ffmpeg`, pas `voice_capture.spec` aan
3. Herbouw de app: `./build_app.sh`

### Problem: App start niet

**Oplossing:**
1. Run vanaf command line om errors te zien:
   ```bash
   ./dist/VoiceCapture.app/Contents/MacOS/VoiceCapture
   ```
2. Check logs in: `~/Documents/VoiceCapture/logs/`

### Problem: Microfoon werkt niet

**Oplossing:**
1. System Preferences > Security & Privacy > Privacy > Microphone
2. Geef VoiceCapture toegang

## Meer informatie

Zie `BUILD_INSTRUCTIONS.md` voor uitgebreide documentatie over:
- Code signing
- Notarisatie
- DMG creatie
- Custom icons
- Menu bar only mode
