# MCP Server voor Audio Transcriptie Applicatie

Deze MCP (Model Context Protocol) server geeft toegang tot je opnames, metadata en transcripties vanuit de Audio Transcriptie Applicatie.

**Cross-platform**: Werkt op macOS, Windows en Linux

## Installatie

De MCP library is al opgenomen in `requirements.txt`. Als je de applicatie hebt geïnstalleerd, is MCP al beschikbaar.

Als je MCP separaat wilt installeren:

```bash
# Activeer eerst je virtual environment
source env/bin/activate  # macOS/Linux
env\Scripts\activate     # Windows

# Installeer MCP
pip install mcp
```

## Server Starten

De MCP server wordt normaal gesproken automatisch gestart door Claude Desktop via de configuratie. Je kunt hem ook handmatig starten voor testing:

```bash
# Activeer je virtual environment
source env/bin/activate  # macOS/Linux
env\Scripts\activate     # Windows

# Start de MCP server
python mcp_server.py
```

**Let op**: De server verwacht stdio communicatie en zal geen output tonen tenzij er data via stdin komt.

## Beschikbare Tools

De MCP server biedt 3 tools:

### 1. `get_recordings`
Geeft een lijst van alle opnames met datum en naam.

**Parameters:** geen

**Voorbeeld response:**
```json
[
  {
    "id": "20250122_143022",
    "date": "2025-01-22 14:30:22",
    "name": "Meeting met team",
    "duration": 245
  },
  {
    "id": "20250122_101545",
    "date": "2025-01-22 10:15:45",
    "name": "Opname 10:15",
    "duration": 120
  }
]
```

### 2. `get_recording`
Geeft de volledige JSON metadata voor een specifieke opname.

**Parameters:**
- `recording_id` (string, verplicht): Het ID (timestamp) van de opname

**Voorbeeld aanroep:**
```json
{
  "recording_id": "20250122_143022"
}
```

**Voorbeeld response:**
```json
{
  "id": "20250122_143022",
  "audio_file": "recordings/recording_20250122_143022/recording_20250122_143022.wav",
  "name": "Meeting met team",
  "date": "2025-01-22 14:30:22",
  "transcription": "Welkom allemaal bij deze meeting...",
  "duration": "PT4M5S",
  "model": "small",
  "segment_duration": 10,
  "overlap_duration": 5
}
```

**Opmerking**: De `duration` is in ISO 8601 format (bijv. "PT4M5S" = 4 minuten en 5 seconden)

### 3. `get_transcription`
Geeft alleen de transcriptie tekst voor een specifieke opname.

**Parameters:**
- `recording_id` (string, verplicht): Het ID (timestamp) van de opname

**Voorbeeld aanroep:**
```json
{
  "recording_id": "20250122_143022"
}
```

**Voorbeeld response:**
```
Welkom allemaal bij deze meeting. Vandaag gaan we het hebben over...
[volledige transcriptie tekst]
```

### 4. `update_recording_title`
Update de titel/naam van een specifieke opname.

**Parameters:**
- `recording_id` (string, verplicht): Het ID (timestamp) van de opname
- `new_title` (string, verplicht): De nieuwe titel/naam voor de opname

**Voorbeeld aanroep:**
```json
{
  "recording_id": "20250122_143022",
  "new_title": "Team Meeting - Q1 Planning"
}
```

**Voorbeeld response:**
```json
{
  "success": true,
  "message": "Successfully updated title for recording '20250122_143022' to 'Team Meeting - Q1 Planning'"
}
```

## Integratie met Claude Desktop

Om deze MCP server te gebruiken met Claude Desktop, voeg het volgende toe aan je Claude configuratie bestand.

### Configuratie locaties

| Platform | Bestand |
|----------|---------|
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| Linux | `~/.config/Claude/claude_desktop_config.json` |

---

### Optie 1: Via uvx (aanbevolen)

De eenvoudigste manier is via `uvx`. Dit vereist geen lokale installatie of virtual environment.

**Vanuit PyPI** (als het package gepubliceerd is):
```json
{
  "mcpServers": {
    "voice-capture": {
      "command": "uvx",
      "args": ["voice-capture-mcp"]
    }
  }
}
```

**Vanuit GitHub**:
```json
{
  "mcpServers": {
    "voice-capture": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/rvmeer/voice_capture",
        "voice-capture-mcp"
      ]
    }
  }
}
```

**Vanuit een lokaal pad**:
```json
{
  "mcpServers": {
    "voice-capture": {
      "command": "uvx",
      "args": [
        "--from",
        "/absolute/path/to/voice_capture",
        "voice-capture-mcp"
      ]
    }
  }
}
```

Op Windows met lokaal pad:
```json
{
  "mcpServers": {
    "voice-capture": {
      "command": "uvx",
      "args": [
        "--from",
        "C:\\Users\\naam\\git\\voice_capture",
        "voice-capture-mcp"
      ]
    }
  }
}
```

**Vereisten voor uvx**:
- Installeer `uv`: https://docs.astral.sh/uv/getting-started/installation/
- `uvx` moet beschikbaar zijn in je PATH

---

### Optie 2: Via lokale Python environment

Als je het project al lokaal hebt geïnstalleerd met een virtual environment:

**macOS/Linux**:
```json
{
  "mcpServers": {
    "voice-capture": {
      "command": "/absolute/path/to/voice_capture/env/bin/python",
      "args": ["/absolute/path/to/voice_capture/mcp_server.py"]
    }
  }
}
```

**Windows**:
```json
{
  "mcpServers": {
    "voice-capture": {
      "command": "C:\\absolute\\path\\to\\voice_capture\\env\\Scripts\\python.exe",
      "args": ["C:\\absolute\\path\\to\\voice_capture\\mcp_server.py"]
    }
  }
}
```

---

### Belangrijke opmerkingen

- Vervang paden door je eigen absolute paden
- Op Windows gebruik je backslashes (`\`) met dubbele escaping (`\\`) in JSON
- Herstart Claude Desktop na het wijzigen van de configuratie

**Tip**: Om je absolute pad te vinden:
```bash
# macOS/Linux
pwd

# Windows (in PowerShell)
pwd
```

## Foutafhandeling

Alle tools geven een error response als er iets misgaat:

```json
{
  "error": "Recording with id '20250122_999999' not found"
}
```

## Technische Details

- **Communicatie**: De server gebruikt `stdio` voor communicatie (standaard MCP transport)
- **Opslag**: Recordings worden geladen uit de `recordings/` directory
- **Structuur**: Elke opname staat in een subfolder `recording_<timestamp>/`
- **Metadata**: Wordt gelezen uit `recording_<timestamp>.json` (per opname)
- **Transcripties**: Worden bij voorkeur gelezen uit `transcription_<timestamp>.txt`, met fallback naar de JSON
- **Cross-platform**: Werkt identiek op macOS, Windows en Linux
- **Path handling**: Gebruikt `pathlib.Path` voor cross-platform bestandspaden

## Vereisten

- Python 3.8+ met virtual environment
- `mcp` library (automatisch geïnstalleerd via `requirements.txt`)
- Audio Transcriptie Applicatie geïnstalleerd
- Toegang tot de `recordings/` directory
- Claude Desktop (voor integratie met Claude)
