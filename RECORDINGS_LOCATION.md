# VoiceCapture - Waar worden mijn opnames bewaard?

## Opslag Locatie

VoiceCapture bewaart **alle opnames** in je Documents folder:

```
~/Documents/VoiceCapture/
```

Of het volledige pad:
```
/Users/[jouw-gebruikersnaam]/Documents/VoiceCapture/
```

## Waarom deze locatie?

Deze locatie is gekozen omdat:
- ✅ Het is een standaard macOS locatie voor gebruikersdata
- ✅ Je hebt altijd toegang tot je opnames via Finder
- ✅ De opnames blijven behouden bij updates van de app
- ✅ Je kunt makkelijk backups maken via Time Machine
- ✅ De opnames gaan niet verloren als je de app verwijdert

## Map Structuur

Elke opname krijgt een eigen folder met een timestamp:

```
~/Documents/VoiceCapture/
├── recording_20251024_120000/
│   ├── recording_20251024_120000.wav       # Volledige audio opname
│   ├── recording_20251024_120000.json      # Metadata (naam, datum, model, etc.)
│   ├── transcription_20251024_120000.txt   # Transcriptie als platte tekst
│   └── segments/                           # Audio segmenten (voor real-time transcriptie)
│       ├── segment_000.wav
│       ├── segment_001.wav
│       └── segment_002.wav
```

## Toegang tot je Opnames

### Via Finder

1. Open Finder
2. Druk op `⌘+Shift+H` (ga naar Home folder)
3. Open de folder "Documents"
4. Open de folder "VoiceCapture"

### Via Terminal

```bash
cd ~/Documents/VoiceCapture
ls -l
```

### Snel openen vanuit Finder

Druk op `⌘+Shift+G` in Finder en typ:
```
~/Documents/VoiceCapture
```

## Bestandsformaten

### WAV bestanden
De audio opnames worden opgeslagen als `.wav` bestanden:
- 16kHz sample rate
- 16-bit PCM
- Mono (1 kanaal)
- Ongecomprimeerd

Je kunt deze bestanden afspelen met:
- QuickTime Player (standaard op macOS)
- VLC Media Player
- Elke andere audio speler

### JSON bestanden
Metadata over elke opname:
```json
{
  "id": "20251024_120000",
  "name": "Opname 2025-10-24 12:00",
  "date": "2025-10-24 12:00:00",
  "duration": "PT2M30S",
  "model": "medium",
  "transcription": "De transcriptie tekst...",
  "segment_duration": 10,
  "overlap_duration": 5
}
```

### TXT bestanden
De transcriptie als platte tekst, makkelijk te openen in:
- TextEdit (standaard op macOS)
- VS Code
- Sublime Text
- Elke andere teksteditor

## Opslag Beheer

### Hoe veel ruimte nemen opnames in?

Een grove schatting:
- 1 minuut audio ≈ 1.9 MB (16kHz mono WAV)
- 10 minuten audio ≈ 19 MB
- 1 uur audio ≈ 115 MB

### Opnames Verwijderen

Je kunt opnames handmatig verwijderen:
1. Open de `~/Documents/VoiceCapture/` folder in Finder
2. Selecteer de opname folders die je wilt verwijderen
3. Sleep naar de Prullenbak (of druk `⌘+Delete`)

**Let op:** Verwijderde opnames kunnen niet worden hersteld (tenzij je een Time Machine backup hebt).

### Opnames Archiveren

Voor lange-termijn opslag:
1. Kopieer de VoiceCapture folder naar een externe schijf
2. Of gebruik Time Machine voor automatische backups
3. Of kopieer naar iCloud Drive / Dropbox voor cloud backup

### Opslag Ruimte Vrijmaken

Als je weinig schijfruimte hebt:
1. Verwijder oude opnames die je niet meer nodig hebt
2. Beweeg oude opnames naar een externe schijf
3. Comprimeer opnames die je wilt bewaren maar niet vaak gebruikt:
   ```bash
   # Comprimeer een opname folder
   zip -r recording_20251024_120000.zip recording_20251024_120000/
   # Verwijder de originele folder na verificatie
   rm -rf recording_20251024_120000/
   ```

## Backup Aanbevelingen

### Time Machine
- VoiceCapture opnames worden automatisch gebackupt met Time Machine
- Herstellen: ga naar de folder in Finder en gebruik "Enter Time Machine"

### Cloud Backup
Je kunt de VoiceCapture folder handmatig synchroniseren met:
- iCloud Drive: kopieer naar `~/Library/Mobile Documents/com~apple~CloudDocs/`
- Dropbox: kopieer naar `~/Dropbox/`
- Google Drive: kopieer naar `~/Google Drive/`

### Handmatige Backup
```bash
# Backup naar externe schijf
cp -r ~/Documents/VoiceCapture /Volumes/ExterneDisk/Backup/

# Of als ZIP archief
cd ~/Documents
zip -r VoiceCapture-backup-$(date +%Y%m%d).zip VoiceCapture/
```

## Privacy en Beveiliging

- Opnames worden **lokaal** opgeslagen op je Mac
- **Geen** data wordt naar de cloud gestuurd (behalve als je handmatig synchroniseert)
- De Whisper AI transcriptie werkt **volledig lokaal** op je Mac
- Zorg dat FileVault is ingeschakeld voor encryptie van je schijf (System Preferences > Security & Privacy > FileVault)

## Problemen?

### Kan VoiceCapture folder niet vinden
```bash
# Check of de folder bestaat
ls -la ~/Documents/VoiceCapture

# Maak de folder handmatig aan als nodig
mkdir -p ~/Documents/VoiceCapture
```

### Geen toegangsrechten
```bash
# Fix toegangsrechten
chmod -R 755 ~/Documents/VoiceCapture
```

### App schrijft niet naar Documents
- Check dat de app toestemming heeft voor toegang tot Documents
- Ga naar System Preferences > Security & Privacy > Privacy > Files and Folders
- Zorg dat VoiceCapture toegang heeft tot Documents folder
