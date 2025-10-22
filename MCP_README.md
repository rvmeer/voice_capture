# MCP Server voor Whisper Demo Recordings

Deze MCP (Model Context Protocol) server geeft toegang tot je opnames, metadata en transcripties.

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
  "summary": "--- Deelnemers ---\n- Alice - Voorstander van nieuwe aanpak\n...",
  "duration": 245,
  "model": "small",
  "ai_provider": "azure",
  "segment_duration": 10,
  "overlap_duration": 5,
  "ollama_url": "",
  "ollama_model": "",
  "summary_prompt": "Maak een samenvatting..."
}
```

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

## Integratie met Claude Desktop

Om deze MCP server te gebruiken met Claude Desktop, voeg het volgende toe aan je Claude configuratie (`~/Library/Application Support/Claude/claude_desktop_config.json` op macOS):

```json
{
  "mcpServers": {
    "whisper-recordings": {
      "command": "python",
      "args": ["/Users/rvmeer/git/whisper_demo/mcp_server.py"]
    }
  }
}
```

Pas het pad aan naar de locatie van je `mcp_server.py` bestand.

## Foutafhandeling

Alle tools geven een error response als er iets misgaat:

```json
{
  "error": "Recording with id '20250122_999999' not found"
}
```

## Technische Details

- De server gebruikt `stdio` voor communicatie (standaard MCP transport)
- Recordings worden geladen uit de `recordings/` directory
- Elke opname staat in een subfolder `recording_<timestamp>/`
- Metadata wordt gelezen uit `recording_<timestamp>.json`
- Transcripties worden bij voorkeur gelezen uit `transcription_<timestamp>.txt`, met fallback naar de JSON
