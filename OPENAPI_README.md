# Whisper Recordings OpenAPI Server

OpenAPI/FastAPI server voor toegang tot Whisper demo opnames, metadata en transcripties. Compatible met Open-WebUI tool integratie.

## Installatie

Installeer de benodigde dependencies:

```bash
pip install fastapi uvicorn[standard] pydantic
```

Of gebruik het requirements bestand:

```bash
pip install -r requirements.txt
```

## Server Starten

Start de OpenAPI server:

```bash
python openapi_server.py
```

De server draait standaard op `http://localhost:8000`

## API Endpoints

### 1. **GET /** - Root informatie
Geeft basis informatie over de API

```bash
curl http://localhost:8000/
```

### 2. **GET /recordings** - Alle opnames
Lijst van alle opnames met basis metadata

```bash
curl http://localhost:8000/recordings
```

Response:
```json
[
  {
    "id": "20251022_171823",
    "date": "2025-10-22 17:18:23",
    "name": "Opname 2025-10-22 17:20",
    "duration": "PT1M36S"
  }
]
```

### 3. **GET /recordings/{recording_id}** - Specifieke opname
Volledige metadata voor een specifieke opname

```bash
curl http://localhost:8000/recordings/20251022_171823
```

Response:
```json
{
  "id": "20251022_171823",
  "audio_file": "recordings/recording_20251022_171823/recording_20251022_171823.wav",
  "name": "Opname 2025-10-22 17:20",
  "date": "2025-10-22 17:18:23",
  "transcription": "...",
  "summary": "",
  "duration": "PT1M36S",
  "model": "small",
  "segment_duration": 10,
  "overlap_duration": 5
}
```

### 4. **GET /recordings/{recording_id}/transcription** - Transcriptie
Volledige transcriptie tekst voor een opname

```bash
curl http://localhost:8000/recordings/20251022_171823/transcription
```

Response:
```json
{
  "recording_id": "20251022_171823",
  "transcription": "De volledige transcriptie tekst..."
}
```

### 5. **PUT /recordings/{recording_id}/title** - Update titel
Update de titel/naam van een opname

```bash
curl -X PUT http://localhost:8000/recordings/20251022_171823/title \
  -H "Content-Type: application/json" \
  -d '{"new_title": "Nieuwe Titel voor Opname"}'
```

Response:
```json
{
  "success": true,
  "message": "Successfully updated title for recording '20251022_171823'",
  "recording_id": "20251022_171823",
  "new_title": "Nieuwe Titel voor Opname"
}
```

### 6. **GET /health** - Health check
Server status check

```bash
curl http://localhost:8000/health
```

## API Documentatie

De server biedt automatische API documentatie:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **OpenAPI Schema**: http://localhost:8000/openapi.json

## Open-WebUI Integratie

### Tool Configuratie

Om deze API als tool in Open-WebUI te gebruiken:

1. **Open-WebUI Tools Settings**
   - Ga naar Settings → Tools
   - Klik op "Add Tool"

2. **Configureer de tool met het OpenAPI schema**
   - URL: `http://localhost:8000/openapi.json`
   - Of upload het schema handmatig

3. **Beschikbare functies in Open-WebUI:**
   - `get_recordings()` - Lijst alle opnames
   - `get_recording(recording_id)` - Haal specifieke opname op
   - `get_transcription(recording_id)` - Haal transcriptie op
   - `update_recording_title(recording_id, new_title)` - Update opname titel

### Voorbeeld gebruik in Open-WebUI chat

```
Gebruiker: Laat me alle opnames zien
AI: [gebruikt get_recordings tool]

Gebruiker: Geef me de transcriptie van opname 20251022_171823
AI: [gebruikt get_transcription tool]

Gebruiker: Wat zijn de details van de meest recente opname?
AI: [gebruikt get_recordings en dan get_recording tools]

Gebruiker: Hernoem opname 20251022_171823 naar "Meeting Notes"
AI: [gebruikt update_recording_title tool]
```

## Server Configuratie

De server kan worden geconfigureerd door de parameters in `uvicorn.run()` aan te passen:

```python
uvicorn.run(
    app,
    host="0.0.0.0",  # Toegankelijk vanaf elk IP
    port=8000,       # Poort nummer
    log_level="info" # Log niveau
)
```

## CORS

De server heeft CORS ingeschakeld voor alle origins, waardoor toegang mogelijk is vanuit browser-gebaseerde applicaties zoals Open-WebUI.

## Development

Voor development met auto-reload:

```bash
uvicorn openapi_server:app --reload --host 0.0.0.0 --port 8000
```

## Verschillen met MCP Server

| Feature | MCP Server | OpenAPI Server |
|---------|-----------|----------------|
| Protocol | MCP (stdio) | HTTP REST API |
| Client | Claude Desktop, MCP clients | Any HTTP client, Open-WebUI |
| Documentation | N/A | Auto-generated Swagger/ReDoc |
| Testing | Via MCP client | Via browser/curl/Postman |
| Integration | Claude Desktop config | Open-WebUI tool config |

## Troubleshooting

### Server start niet
- Check of port 8000 vrij is: `lsof -i :8000`
- Probeer een andere port in de configuratie

### CORS errors
- CORS is standaard ingeschakeld voor alle origins
- Check browser console voor specifieke CORS errors

### Opnames niet zichtbaar
- Controleer of de `recordings` directory bestaat
- Controleer of JSON bestanden correct zijn geformatteerd
- Check server logs voor error messages

## API Response Formats

### Success Response
Alle succesvolle responses gebruiken de gedocumenteerde Pydantic models met proper JSON formatting.

### Error Response
```json
{
  "detail": "Error message here"
}
```

HTTP status codes:
- `200` - Success
- `404` - Recording niet gevonden
- `500` - Server error
