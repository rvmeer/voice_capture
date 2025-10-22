# Audio Transcriptie Applicatie met Whisper

Een professionele desktop applicatie voor het opnemen, transcriberen en samenvatten van audio met OpenAI's Whisper tiny model (geoptimaliseerd voor snelheid op CPU).

## Features

✅ **Intuïtieve GUI** - Moderne, gebruiksvriendelijke interface met PyQt6
✅ **Audio Opname** - Opname van microfoon audio (macOS optimized)
✅ **Whisper Transcriptie** - Snelle transcriptie met Whisper tiny model (5-10 sec)
✅ **Nederlandse Taal** - Geoptimaliseerd voor Nederlands
✅ **Samenvatting** - Automatische generatie van samenvattingen met kernwoorden
✅ **Recording Timer** - Real-time weergave van opnameduur
✅ **Tab Interface** - Gescheiden weergave van transcriptie en samenvatting
✅ **Opname Historie** - Volledige lijst van alle opnames met metadata
✅ **Audio Playback** - Luister opnames terug binnen de app
✅ **Hernoemen** - Geef opnames betekenisvolle namen
✅ **JSON Opslag** - Alle transcripties en samenvattingen worden opgeslagen

## Installatie

### 1. Installeer systeem dependencies (macOS)

```bash
brew install portaudio ffmpeg
```

### 2. Installeer Python packages

```bash
pip install -r requirements.txt
```

## Gebruik

Start de applicatie:

```bash
python main.py
```

De applicatie start automatisch:
- 🎤 **Tray Icon** - Voor opnames via systeem tray
- 🌐 **OpenAPI Server** - Op http://localhost:8000
  - API documentatie: http://localhost:8000/docs
  - ReDoc: http://localhost:8000/redoc
  - OpenAPI schema: http://localhost:8000/openapi.json

### Nieuwe Opname:

1. **Wacht** tot het Whisper model is geladen
2. **Klik** op "Opname Starten" om audio op te nemen
3. **Spreek** in je microfoon
4. **Klik** op "Opname Stoppen" wanneer je klaar bent
5. **Geef een naam** aan je opname
6. **Bekijk** de transcriptie en samenvatting in de tabs

### Opnames Beheren:

- **Klik op een opname** in de lijst om deze te laden
- **▶ Afspelen** - Luister de audio terug
- **✏️ Hernoemen** - Geef de opname een nieuwe naam
- Alle data wordt automatisch opgeslagen in `recordings/recordings.json`

## Systeemvereisten

- Python 3.8+
- macOS (geoptimaliseerd voor MacBook microfoon)
- ~500MB vrij geheugen voor Whisper tiny model
- Microfoon toegang

## Projectstructuur

```
whisper_demo/
├── main.py                    # Hoofdapplicatie
├── requirements.txt           # Python afhankelijkheden
├── recordings/                # Opgeslagen bestanden (auto-aangemaakt)
│   ├── recording_*.wav       # Audio bestanden
│   └── recordings.json       # Metadata, transcripties, samenvattingen
└── README.md                 # Deze file
```

## Technische Details

- **GUI Framework**: PyQt6
- **Audio Opname**: PyAudio (16kHz, mono)
- **Audio Playback**: macOS afplay (system command)
- **Transcriptie**: OpenAI Whisper (tiny model voor snelheid)
- **Taal**: Nederlands (configureerbaar)
- **Threading**: Asynchrone verwerking voor soepele UX
- **Opslag**: JSON voor metadata, WAV voor audio

## Licentie

MIT License

### Instellingen macbook

Aggregate device op macbook mic en blackhole
Multi output device op minstens blackhole

Nu stel je bij de macbook (option click) in:
  output -> Multi output device
  input -> Aggregate device
