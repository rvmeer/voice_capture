# MCP Server voor Audio Transcriptie Applicatie

Deze MCP (Model Context Protocol) server geeft toegang tot je opnames, metadata en transcripties vanuit de Audio Transcriptie Applicatie.

**Cross-platform**: Werkt op macOS, Windows en Linux

## Installatie

Installeer eerst de benodigde MCP library:

```bash
pip install mcp
```

## Server Starten

Start de MCP server met:

```bash
python mcp_server.py
```

Of als executable:

```bash
./mcp_server.py
```

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

Om deze MCP server te gebruiken met Claude Desktop, voeg het volgende toe aan je Claude configuratie bestand:

### macOS
Bestand: `~/Library/Application Support/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "voice-capture": {
      "command": "python",
      "args": ["/absolute/path/to/voice_capture/mcp_server.py"]
    }
  }
}
```

### Windows
Bestand: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "voice-capture": {
      "command": "python",
      "args": ["C:\\absolute\\path\\to\\voice_capture\\mcp_server.py"]
    }
  }
}
```

### Linux
Bestand: `~/.config/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "voice-capture": {
      "command": "python3",
      "args": ["/absolute/path/to/voice_capture/mcp_server.py"]
    }
  }
}
```

**Belangrijk**:
- Vervang het pad door de absolute locatie van je `mcp_server.py` bestand
- Op Windows gebruik je backslashes (`\`) of forward slashes met dubbele escaping (`\\`)
- Op Linux gebruik mogelijk `python3` in plaats van `python`
- Herstart Claude Desktop na het wijzigen van de configuratie

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

- Python 3.8+
- `mcp` library (`pip install mcp`)
- Draaiende Audio Transcriptie Applicatie (voor nieuwe opnames)
- Toegang tot de `recordings/` directory
