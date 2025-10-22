# Audio Transcriptie Applicatie met Whisper

Een professionele desktop applicatie voor het opnemen, transcriberen en samenvatten van audio met OpenAI's Whisper model (geoptimaliseerd voor snelheid op CPU).

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

- **GUI Framework**: PyQt6 (tray-only mode)
- **API Server**: FastAPI + Uvicorn (automatisch gestart)
- **Audio Opname**: PyAudio (16kHz, mono)
- **Audio Playback**: macOS afplay (system command)
- **Transcriptie**: OpenAI Whisper (tiny/small/medium/large models)
- **Taal**: Nederlands (configureerbaar)
- **Threading**: Asynchrone verwerking voor soepele UX
- **Opslag**: JSON voor metadata (ISO 8601 duration), WAV voor audio

## Licentie

MIT License


