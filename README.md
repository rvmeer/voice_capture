# Audio Transcriptie Applicatie met Whisper

Een professionele tray-only desktop applicatie voor het opnemen en transcriberen van audio met OpenAI's Whisper model. Draait volledig in de macOS menubalk met API toegang via FastAPI.

## Features

✅ **System Tray Interface** - Volledige bediening via macOS menubalk icoon
✅ **Click-to-Record** - Eén klik om opname te starten/stoppen
✅ **Multiple Whisper Models** - Keuze uit tiny/small/medium/large modellen
✅ **Live Transcriptie** - Incrementele transcriptie tijdens opname (segmented)
✅ **Audio Input Selection** - Kies je microfoon/audio input via tray menu
✅ **Nederlandse Taal** - Geoptimaliseerd voor Nederlands
✅ **Auto-save** - Automatisch opslaan zonder dialogen
✅ **Empty Recording Detection** - Automatisch verwijderen van lege opnames
✅ **Model Caching** - Gekozen modellen blijven in geheugen voor snelheid
✅ **Configurable Segments** - Instelbare segment lengte en overlap
✅ **FastAPI Server** - Volledige API toegang tot opnames
✅ **MCP Server** - Claude Desktop integratie

## Installatie

### 1. Installeer systeem dependencies (macOS)

```bash
brew install portaudio ffmpeg
```

### 2. Installeer Python packages

```bash
pip install -r requirements.txt
```

**Let op**: Er is geen `.env` bestand of configuratie nodig. Alle instellingen worden gedaan via het tray menu.

## Gebruik

Start de applicatie:

```bash
python main.py
```

De applicatie start automatisch:
- 🎤 **Tray Icon** - Wit cirkel icoon verschijnt in de macOS menubalk
- 🌐 **OpenAPI Server** - Op http://localhost:8000
  - API documentatie: http://localhost:8000/docs
  - ReDoc: http://localhost:8000/redoc
  - OpenAPI schema: http://localhost:8000/openapi.json

### Nieuwe Opname via Tray Icon:

1. **Klik** op het witte cirkel icoon in de menubalk om opname te starten
   - Icoon verandert naar wit-met-rood (opname actief)
   - Notificatie bevestigt opname start
2. **Spreek** in je microfoon
3. **Klik nogmaals** op het icoon om te stoppen
   - Opname wordt automatisch opgeslagen met timestamp
   - Live transcriptie start tijdens opname
4. **Transcriptie** wordt incrementeel gegenereerd en opgeslagen

### Instellingen via Tray Menu:

**Rechtermuisklik** (of Control+klik) op het tray icoon voor:
- **Transcription Model** - Kies tussen tiny/small/medium/large
- **Input Selection** - Selecteer je audio invoer apparaat
- **Afsluiten** - Sluit de applicatie

### Opname Structuur:

Elke opname wordt opgeslagen in een eigen folder:
```
recordings/
└── recording_YYYYMMDD_HHMMSS/
    ├── recording_YYYYMMDD_HHMMSS.json        # Metadata
    ├── recording_YYYYMMDD_HHMMSS.wav         # Audio bestand
    ├── transcription_YYYYMMDD_HHMMSS.txt     # Transcriptie
    └── segments/                              # Audio segmenten
        ├── segment_000.wav
        ├── segment_001.wav
        └── ...
```

## Systeemvereisten

- Python 3.8+
- macOS (geoptimaliseerd voor macOS menubalk)
- Minimaal geheugen:
  - Tiny model: ~1GB RAM
  - Small model: ~2GB RAM
  - Medium model: ~5GB RAM
  - Large model: ~10GB RAM
- Microfoon toegang
- Portaudio en FFmpeg (via Homebrew)

## Projectstructuur

```
voice_capture/
├── main.py                    # Hoofdapplicatie (tray + FastAPI server)
├── audio_recorder.py          # Audio opname met segmentatie
├── recording_manager.py       # Opslag beheer (JSON per opname)
├── openapi_server.py          # FastAPI server voor API toegang
├── mcp_server.py              # MCP server voor Claude Desktop
├── requirements.txt           # Python afhankelijkheden
├── recordings/                # Opgeslagen opnames (auto-aangemaakt)
│   └── recording_YYYYMMDD_HHMMSS/
│       ├── *.json            # Metadata per opname
│       ├── *.wav             # Audio bestand
│       ├── *.txt             # Transcriptie
│       └── segments/         # Audio segmenten
├── README.md                  # Deze file
├── OPENAPI_README.md          # OpenAPI server documentatie
└── MCP_README.md              # MCP server documentatie
```

## API Toegang

De applicatie start automatisch een OpenAPI server voor programmatische toegang tot opnames:

### Beschikbare Endpoints:
- `GET /recordings` - Lijst van alle opnames
- `GET /recordings/{id}` - Specifieke opname details
- `GET /recordings/{id}/transcription` - Transcriptie tekst
- `PUT /recordings/{id}/title` - Update opname titel

### Documentatie:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
- OpenAPI Schema: http://localhost:8000/openapi.json

### Gebruik met Open-WebUI:
Configureer in Open-WebUI Settings → Tools met URL: `http://localhost:8000/openapi.json`

Zie [OPENAPI_README.md](OPENAPI_README.md) voor meer details.

### MCP Server:
Voor gebruik met Claude Desktop, zie [MCP_README.md](MCP_README.md).

## Technische Details

- **GUI Framework**: PyQt6 (tray-only mode, geen venster)
- **API Server**: FastAPI + Uvicorn (automatisch gestart op port 8000)
- **Audio Opname**: PyAudio (16kHz, mono)
- **Segmentatie**: Configureerbare segment lengte (10-120s) met overlap (5-60s)
- **Transcriptie**: OpenAI Whisper (tiny/small/medium/large models)
  - CPU-only uitvoering
  - Model caching voor snelheid
  - Incrementele transcriptie tijdens opname
  - Automatische overlap detectie en verwijdering
- **Taal**: Nederlands (hardcoded in transcriptie)
- **Threading**:
  - Audio opname in aparte thread
  - Transcriptie in worker threads
  - FastAPI server in daemon thread
- **Opslag**:
  - JSON per opname (ISO 8601 duration format)
  - WAV voor audio (16bit PCM)
  - TXT voor transcriptie
  - Automatische folder structuur per opname
- **Empty Recording Detection**: Automatisch verwijderen van opnames zonder transcriptie

## Licentie

MIT License


