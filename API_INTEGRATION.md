# VoiceCapture - API & MCP Integratie

## Overzicht

VoiceCapture heeft een ingebouwde **OpenAPI server** en **MCP (Model Context Protocol) server** die toegang geven tot alle opnames, transcripties en metadata via gestandaardiseerde API's.

Beide servers gebruiken dezelfde opslag locatie als de hoofdapplicatie:
```
~/Documents/VoiceCapture/
```

## OpenAPI Server

De OpenAPI server draait automatisch wanneer je VoiceCapture start.

### Server Details

- **URL**: `http://localhost:8000`
- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`
- **OpenAPI Schema**: `http://localhost:8000/openapi.json`

### Beschikbare Endpoints

#### 1. Lijst van alle opnames
```http
GET /recordings
```

**Response:**
```json
[
  {
    "id": "20251024_120000",
    "date": "2025-10-24 12:00:00",
    "name": "Opname 2025-10-24 12:00",
    "duration": "PT2M30S"
  }
]
```

#### 2. Details van specifieke opname
```http
GET /recordings/{recording_id}
```

**Response:**
```json
{
  "id": "20251024_120000",
  "audio_file": "/Users/.../recording_20251024_120000.wav",
  "name": "Opname 2025-10-24 12:00",
  "date": "2025-10-24 12:00:00",
  "transcription": "De volledige transcriptie tekst...",
  "summary": "",
  "duration": "PT2M30S",
  "model": "medium",
  "segment_duration": 10,
  "overlap_duration": 5
}
```

#### 3. Transcriptie ophalen
```http
GET /recordings/{recording_id}/transcription
```

**Response:**
```json
{
  "recording_id": "20251024_120000",
  "transcription": "De volledige transcriptie tekst..."
}
```

#### 4. Titel updaten
```http
PUT /recordings/{recording_id}/title
Content-Type: application/json

{
  "new_title": "Nieuwe titel"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Successfully updated title...",
  "recording_id": "20251024_120000",
  "new_title": "Nieuwe titel"
}
```

#### 5. Health check
```http
GET /health
```

**Response:**
```json
{
  "status": "healthy"
}
```

### Gebruik met cURL

```bash
# Lijst van alle opnames
curl http://localhost:8000/recordings

# Specifieke opname
curl http://localhost:8000/recordings/20251024_120000

# Transcriptie
curl http://localhost:8000/recordings/20251024_120000/transcription

# Titel updaten
curl -X PUT http://localhost:8000/recordings/20251024_120000/title \
  -H "Content-Type: application/json" \
  -d '{"new_title": "Nieuwe titel"}'
```

### Gebruik met Python

```python
import requests

# Alle opnames ophalen
response = requests.get("http://localhost:8000/recordings")
recordings = response.json()
print(f"Aantal opnames: {len(recordings)}")

# Specifieke opname
recording_id = "20251024_120000"
response = requests.get(f"http://localhost:8000/recordings/{recording_id}")
recording = response.json()
print(f"Transcriptie: {recording['transcription']}")

# Titel updaten
response = requests.put(
    f"http://localhost:8000/recordings/{recording_id}/title",
    json={"new_title": "Mijn nieuwe titel"}
)
result = response.json()
print(f"Success: {result['success']}")
```

### Gebruik met JavaScript/TypeScript

```javascript
// Alle opnames ophalen
const response = await fetch('http://localhost:8000/recordings');
const recordings = await response.json();
console.log(`Aantal opnames: ${recordings.length}`);

// Specifieke opname
const recordingId = '20251024_120000';
const recording = await fetch(`http://localhost:8000/recordings/${recordingId}`)
  .then(res => res.json());
console.log(`Transcriptie: ${recording.transcription}`);

// Titel updaten
const updateResponse = await fetch(
  `http://localhost:8000/recordings/${recordingId}/title`,
  {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ new_title: 'Mijn nieuwe titel' })
  }
);
const result = await updateResponse.json();
console.log(`Success: ${result.success}`);
```

## MCP Server

De MCP (Model Context Protocol) server maakt de VoiceCapture opnames toegankelijk voor AI assistenten zoals Claude Desktop.

### Server Opstarten

```bash
# Via Python
python mcp_server.py

# Of direct als executable (na build)
./mcp_server.py
```

### Beschikbare Tools

#### 1. get_recordings
Haal een lijst op van alle opnames.

**Input:** Geen parameters

**Output:**
```json
[
  {
    "id": "20251024_120000",
    "date": "2025-10-24 12:00:00",
    "name": "Opname 2025-10-24 12:00",
    "duration": "PT2M30S"
  }
]
```

#### 2. get_recording
Haal complete metadata op van een specifieke opname.

**Input:**
```json
{
  "recording_id": "20251024_120000"
}
```

**Output:** Complete recording JSON met alle metadata

#### 3. get_transcription
Haal de transcriptie tekst op van een specifieke opname.

**Input:**
```json
{
  "recording_id": "20251024_120000"
}
```

**Output:** Transcriptie tekst (plain text)

#### 4. update_recording_title
Update de titel van een opname.

**Input:**
```json
{
  "recording_id": "20251024_120000",
  "new_title": "Nieuwe titel"
}
```

**Output:**
```json
{
  "success": true,
  "message": "Successfully updated title..."
}
```

### Configuratie voor Claude Desktop

Voeg het volgende toe aan je Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "voicecapture": {
      "command": "python",
      "args": ["/Users/[jouw-gebruikersnaam]/git/voice_capture/mcp_server.py"]
    }
  }
}
```

Of als je een Python virtual environment gebruikt:

```json
{
  "mcpServers": {
    "voicecapture": {
      "command": "/Users/[jouw-gebruikersnaam]/git/voice_capture/env/bin/python",
      "args": ["/Users/[jouw-gebruikersnaam]/git/voice_capture/mcp_server.py"]
    }
  }
}
```

### Gebruik in Claude Desktop

Na configuratie kun je in Claude vragen:

```
"Haal mijn laatste opname op"
"Toon de transcriptie van opname 20251024_120000"
"Update de titel van mijn laatste opname naar 'Meeting Notes'"
```

Claude kan dan automatisch de MCP tools gebruiken om toegang te krijgen tot je VoiceCapture opnames.

## Data Locatie

**Belangrijk:** Beide servers (OpenAPI en MCP) lezen data uit:

```
~/Documents/VoiceCapture/
```

Dit is dezelfde locatie waar de VoiceCapture app alle opnames opslaat. Dit betekent:

- ✅ **Real-time toegang** - API's hebben direct toegang tot nieuwe opnames
- ✅ **Geen synchronisatie** - Alle componenten gebruiken dezelfde data
- ✅ **Consistent** - Wijzigingen via API zijn direct zichtbaar in de app
- ✅ **Betrouwbaar** - Geen dubbele data of sync issues

## CORS (Cross-Origin Resource Sharing)

De OpenAPI server heeft CORS ingeschakeld voor alle origins (`*`). Dit betekent dat je de API kunt gebruiken vanuit:
- Web applicaties
- Browser extensions
- Electron apps
- En andere cross-origin contexts

## Beveiliging

### Lokale Toegang

Standaard draaien beide servers **lokaal** op je Mac:
- OpenAPI: `http://localhost:8000`
- MCP: stdio (standaard input/output)

### Externe Toegang

Als je de OpenAPI server toegankelijk wilt maken vanaf andere devices op je netwerk:

1. **Vind je lokale IP:**
   ```bash
   ipconfig getifaddr en0
   ```

2. **Toegang vanaf andere devices:**
   ```
   http://[jouw-ip]:8000/recordings
   ```

⚠️ **Waarschuwing:** Er is geen authenticatie! Alleen voor gebruik op vertrouwde netwerken.

### Firewall

macOS kan vragen of je inkomende verbindingen wilt toestaan. Klik "Allow" als je de API vanaf andere devices wilt gebruiken.

## Integratie Voorbeelden

### Open-WebUI Tool Integratie

```python
# In Open-WebUI als custom tool
import requests

def get_voicecapture_recordings():
    """Haal VoiceCapture opnames op"""
    response = requests.get("http://localhost:8000/recordings")
    return response.json()
```

### Home Assistant Integratie

```yaml
# configuration.yaml
rest_command:
  voicecapture_get_recordings:
    url: "http://localhost:8000/recordings"
    method: GET
```

### Raycast Script Command

```bash
#!/bin/bash
# @raycast.title VoiceCapture Recordings
# @raycast.mode fullOutput

curl -s http://localhost:8000/recordings | jq '.'
```

## Troubleshooting

### Server draait niet
```bash
# Check of de app draait
ps aux | grep VoiceCapture

# Check of poort 8000 gebruikt wordt
lsof -i :8000
```

### Geen data beschikbaar
```bash
# Check of de recordings folder bestaat
ls -la ~/Documents/VoiceCapture/

# Check of er opnames zijn
ls -la ~/Documents/VoiceCapture/recording_*/
```

### API geeft foutmelding
```bash
# Check server logs
# Logs worden getoond in de terminal waar je de app startte
# Of in Console.app als je de .app bundle gebruikt
```

## Logging

### OpenAPI Server Logs
De server logt automatisch naar stdout. Bij het draaien als .app bundle:
- Open Console.app
- Filter op "VoiceCapture"
- Bekijk de logs

### Debug Mode
Start de server in debug mode:
```bash
python openapi_server.py
# Of met meer logging:
LOG_LEVEL=debug python openapi_server.py
```

## Performance

### Aantal Opnames
De API kan honderden opnames aan zonder performance problemen.

### Response Times
- `GET /recordings`: < 100ms (zelfs met 100+ opnames)
- `GET /recordings/{id}`: < 10ms
- `GET /recordings/{id}/transcription`: < 20ms

### Caching
Momenteel geen caching geïmplementeerd. Alle data wordt real-time gelezen uit bestanden.

## Toekomstige Features

Mogelijke uitbreidingen:
- [ ] Authenticatie (API keys)
- [ ] Rate limiting
- [ ] Response caching
- [ ] Webhooks voor nieuwe opnames
- [ ] Audio streaming endpoint
- [ ] Search/filter capabilities
- [ ] Pagination voor grote datasets
- [ ] GraphQL endpoint
