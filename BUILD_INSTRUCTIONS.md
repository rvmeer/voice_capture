# VoiceCapture - macOS App Build Instructies

## Over deze Applicatie

VoiceCapture is een audio transcriptie applicatie die gebruik maakt van OpenAI's Whisper model om audio opnames te transcriberen naar tekst. De applicatie draait als een system tray icoon op macOS.

### Opslag Locatie

Alle opnames worden opgeslagen in:
```
~/Documents/VoiceCapture/
```

Elke opname wordt opgeslagen in een eigen folder met de volgende structuur:
```
~/Documents/VoiceCapture/
├── recording_20251024_120000/
│   ├── recording_20251024_120000.wav    # Volledige audio opname
│   ├── recording_20251024_120000.json   # Metadata en transcriptie
│   ├── transcription_20251024_120000.txt # Transcriptie tekst
│   └── segments/                        # Audio segmenten (voor incrementele transcriptie)
│       ├── segment_000.wav
│       ├── segment_001.wav
│       └── ...
```

## Vereisten

- macOS 10.13 of hoger
- Python 3.13
- PyInstaller (geïnstalleerd via pip)
- ffmpeg (geïnstalleerd via Homebrew: `brew install ffmpeg`)

## Installatie van de App

De gecompileerde app bevindt zich in de `dist/` directory:

```
dist/VoiceCapture.app
```

### Optie 1: Direct uitvoeren vanuit dist/

Je kunt de app direct starten vanuit de `dist/` directory:

```bash
open dist/VoiceCapture.app
```

### Optie 2: Kopiëren naar Applications folder

Voor permanente installatie, kopieer de app naar je Applications folder:

```bash
cp -r dist/VoiceCapture.app /Applications/
```

Vervolgens kun je de app starten vanuit Finder of via Spotlight (⌘+Space, typ "VoiceCapture").

## De App Opnieuw Bouwen

Als je wijzigingen hebt aangebracht aan de broncode, kun je de app opnieuw bouwen:

### Optie 1: Met build script (aanbevolen)

```bash
./build_app.sh
```

Dit script:
- Controleert of alle vereisten geïnstalleerd zijn (PyInstaller, ffmpeg)
- Maakt oude builds schoon
- Bouwt een nieuwe app
- Toont installatie instructies

### Optie 2: Handmatig

```bash
# Zorg dat PyInstaller geïnstalleerd is
pip install pyinstaller

# Zorg dat ffmpeg geïnstalleerd is
brew install ffmpeg

# Bouw de app
pyinstaller voice_capture.spec --clean
```

De nieuwe app wordt gegenereerd in de `dist/` directory.

## Aanpassen van de Build

Je kunt de build aanpassen door het `voice_capture.spec` bestand te bewerken:

### App Icoon Toevoegen

1. Maak een `.icns` bestand aan (macOS icon formaat)
2. Pas de `icon` parameter aan in het spec bestand:
   ```python
   app = BUNDLE(
       ...
       icon='path/to/your/icon.icns',
       ...
   )
   ```

### Menu Bar Only App (Geen Dock Icoon)

Om de app alleen in de menu bar te tonen zonder dock icoon, wijzig in het spec bestand:

```python
info_plist={
    ...
    'LSUIElement': '1',  # 1 = menu bar only, 0 = normale app
    ...
}
```

### Bundle Identifier Wijzigen

Wijzig de `bundle_identifier` in het spec bestand:

```python
app = BUNDLE(
    ...
    bundle_identifier='com.jouwbedrijf.voicecapture',
    ...
)
```

## Code Signing (Optioneel)

Voor distributie buiten de Mac App Store kun je de app code signen:

```bash
# Toon beschikbare certificaten
security find-identity -v -p codesigning

# Sign de app met je Developer ID
codesign --deep --force --verify --verbose --sign "Developer ID Application: Your Name" dist/VoiceCapture.app

# Verifieer de signature
codesign --verify --deep --strict --verbose=2 dist/VoiceCapture.app
```

## Distributie

### Optie 1: DMG maken

Maak een DMG bestand voor eenvoudige distributie:

```bash
hdiutil create -volname VoiceCapture -srcfolder dist/VoiceCapture.app -ov -format UDZO VoiceCapture.dmg
```

### Optie 2: ZIP bestand

Maak een ZIP bestand:

```bash
cd dist
zip -r VoiceCapture.zip VoiceCapture.app
cd ..
```

## Notarisatie (Voor distributie buiten Mac App Store)

Voor distributie buiten de Mac App Store is notarisatie door Apple vereist:

1. Sign de app met je Developer ID
2. Upload naar Apple voor notarisatie:
   ```bash
   xcrun notarytool submit VoiceCapture.zip --apple-id your@email.com --team-id TEAMID --wait
   ```
3. Staple het notarisatie ticket aan de app:
   ```bash
   xcrun stapler staple dist/VoiceCapture.app
   ```

## Problemen Oplossen

### ffmpeg niet gevonden

Als je de error `FileNotFoundError: [Errno 2] No such file or directory: 'ffmpeg'` krijgt:

1. Zorg dat ffmpeg geïnstalleerd is:
   ```bash
   brew install ffmpeg
   ```

2. De app bundelt ffmpeg automatisch vanaf `/opt/homebrew/bin/ffmpeg` (Apple Silicon) of `/usr/local/bin/ffmpeg` (Intel)

3. Als ffmpeg op een andere locatie staat, pas `voice_capture.spec` aan:
   ```python
   binaries=[
       ('/path/to/your/ffmpeg', '.'),
   ],
   ```

4. Herbouw de app met `./build_app.sh`

### App start niet

1. Check de Console app (Applications > Utilities > Console) voor foutmeldingen
2. Run de app vanuit Terminal om debug output te zien:
   ```bash
   ./dist/VoiceCapture.app/Contents/MacOS/VoiceCapture
   ```
3. Check de log files in `~/Documents/VoiceCapture/logs/`

### Microfoon toegang

De app vraagt automatisch om microfoon toegang. Als dit niet werkt:

1. Ga naar System Preferences > Security & Privacy > Privacy > Microphone
2. Voeg VoiceCapture toe aan de lijst van toegestane apps

### Gatekeeper waarschuwing

Bij eerste keer openen kan macOS Gatekeeper een waarschuwing geven:

1. Rechtsklik op VoiceCapture.app
2. Kies "Open"
3. Bevestig dat je de app wilt openen

## App Structuur

```
VoiceCapture.app/
├── Contents/
│   ├── MacOS/
│   │   └── VoiceCapture          # Executable
│   ├── Resources/                # Data files
│   ├── Frameworks/               # Python en dependencies
│   ├── Info.plist                # App metadata
│   └── _CodeSignature/           # Code signature (indien gesigned)
```

## Licentie en Credits

- OpenAI Whisper voor audio transcriptie
- PyQt6 voor de GUI
- PyInstaller voor het bouwen van de macOS app
