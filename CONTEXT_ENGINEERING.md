# Context Engineering voor Voice Capture MCP Server

## Overzicht

De Voice Capture MCP server is uitgebreid met context engineering principes om lange transcripties (30 minuten tot 2+ uur) effectief te verwerken zonder context overload en het "lost-in-the-middle" probleem.

## Het Probleem

Bij lange transcripties ontstaan de volgende problemen:
- **Context overload**: De volledige transcriptie overschrijdt de context window
- **Lost-in-the-middle effect**: Informatie in het midden van lange context wordt gemist
- **Attention scarcity**: De aandacht van het LLM wordt verspreid over te veel tokens

## De Oplossing: Progressive Disclosure

In plaats van de volledige transcriptie te laden, gebruiken we een gelaagde aanpak:

### 1. Metadata First (get_transcription_summary)

**Principe**: Front-load critical information

Start altijd met het ophalen van metadata:
```python
summary = get_transcription_summary(recording_id)
```

Dit geeft je:
- **word_count**: Totaal aantal woorden
- **duration_minutes**: Duur van de opname
- **speech_rate_wpm**: Spraaksnelheid (woorden per minuut)
- **estimated_reading_time_minutes**: Geschatte leestijd
- **total_chunks**: Aantal beschikbare chunks
- **speakers_detected**: Lijst van gedetecteerde sprekers
- **speaker_count**: Aantal sprekers
- **preview_words**: Eerste ~500 woorden (voor context)
- **conclusion_words**: Laatste ~500 woorden (voor conclusies)

### 2. Progressive Loading (get_transcription_chunked)

**Principe**: Load only what you need, when you need it

Haal specifieke delen op op basis van je analyse:
```python
# Eerste chunk voor introductie
first = get_transcription_chunked(recording_id, chunk_index=0)

# Laatste chunk voor conclusies
last = get_transcription_chunked(recording_id, chunk_index=-1)

# Middelste chunk
middle = get_transcription_chunked(recording_id, chunk_index=13)
```

## Implementatie Details

### Chunking Strategie

- **Chunk size**: 500 woorden (ongeveer 2-3 minuten spraak)
- **Overlap**: 50 woorden tussen chunks
- **Waarom overlap?**: Voorkomt dat belangrijke informatie wordt afgesneden op chunk grenzen

### Voorbeeld: Verwerking van een 55-minuten opname

```
Transcriptie: 12.064 woorden
Totaal chunks: 27

Workflow:
1. get_transcription_summary → Zie dat het 27 chunks heeft
2. Lees preview (eerste 500 woorden) en conclusion (laatste 500 woorden)
3. Bepaal welke delen interessant zijn
4. Haal specifieke chunks op:
   - Chunk 0: Introductie/opening
   - Chunk 13: Midden van gesprek
   - Chunk 26: Conclusie
```

## MCP Tools

### get_transcription_summary

**Gebruik**: Altijd EERST aanroepen voor lange transcripties

**Parameters**:
- `recording_id` (string): De ID van de opname

**Returns**: JSON met metadata en preview/conclusion

**Voorbeeld**:
```json
{
  "recording_id": "20260122_100025",
  "recording_name": "Opname 2026-01-22 10:55",
  "word_count": 12064,
  "duration_minutes": 54.9,
  "speech_rate_wpm": 219.6,
  "total_chunks": 27,
  "preview_words": "Eerste 500 woorden...",
  "conclusion_words": "Laatste 500 woorden..."
}
```

### get_transcription_chunked

**Gebruik**: Haal specifieke delen op na analyse van summary

**Parameters**:
- `recording_id` (string): De ID van de opname
- `chunk_index` (integer): Index van chunk (ondersteunt negatieve indexing)
  - `0` = eerste chunk
  - `-1` = laatste chunk
  - `-2` = voorlaatste chunk
- `chunk_size` (integer, optioneel): Aantal woorden per chunk (default: 500)
- `overlap` (integer, optioneel): Overlap tussen chunks (default: 50)

**Returns**: JSON met chunk data

**Voorbeeld**:
```json
{
  "recording_id": "20260122_100025",
  "recording_name": "Opname 2026-01-22 10:55",
  "chunk_index": 0,
  "chunk_id": "chunk_0",
  "text": "De tekst van deze chunk...",
  "word_count": 500,
  "start_word": 0,
  "end_word": 500,
  "has_overlap_before": false,
  "has_overlap_after": true
}
```

### get_transcription (legacy)

**Gebruik**: Alleen voor korte transcripties (<10 minuten)

**Waarschuwing**: Voor lange opnames geeft dit een waarschuwing en adviseert het gebruik van de nieuwe tools.

## Best Practices voor Claude/LLM gebruik

### ✅ Goede workflow voor meeting summaries:

```
1. Gebruik get_transcription_summary()
   → Krijg context: duur, aantal sprekers, preview, conclusie

2. Analyseer de preview en conclusie
   → Begrijp waar de meeting over gaat

3. Bepaal relevante secties
   → Bijv. als preview wijst op probleem → zoek middle chunks
   → Als conclusie belangrijk → haal chunk -1 op

4. Iteratief chunks ophalen
   → Alleen de chunks die je nodig hebt

5. Maak summary op basis van geladen chunks
   → Veel efficiënter context gebruik
```

### ❌ Slechte workflow:

```
1. Gebruik get_transcription()
   → 12.000 woorden in één keer
   → Context overload
   → Lost-in-the-middle effect
```

## Technical Implementation

### Bestanden:

- **transcription_utils.py**: Core functies voor chunking en metadata
  - `get_transcription_metadata()`: Extract metadata from text
  - `chunk_transcription()`: Split text into overlapping chunks
  - `get_chunk_by_index()`: Get specific chunk by index
  - `parse_duration()`: Parse ISO 8601 duration format
  - `extract_speakers()`: Detect speaker labels

- **mcp_server.py**: MCP tool registratie en handlers
  - Registreert nieuwe tools in `handle_list_tools()`
  - Implementeert tool handlers in `handle_call_tool()`

### Testing:

- **test_context_engineering.py**: Unit tests voor chunking logic
- **test_mcp_integration.py**: Integration tests met echte opnames

Run tests:
```bash
python test_context_engineering.py
python test_mcp_integration.py
```

## Context Engineering Principes (gebaseerd op Agent-Skills-for-Context-Engineering)

### 1. Progressive Disclosure
Load context in stages - metadata first, full content on demand

### 2. Chunking with Overlap
Prevent lost-in-the-middle by ensuring continuity across boundaries

### 3. Front-loading Critical Information
Start and end positions contain key details (intro/conclusion)

### 4. Smallest Possible High-Signal Token Set
Efficiency trumps comprehensiveness - load only what you need

## Voorbeelden

### Voorbeeld 1: Quick Overview

```
Q: "Wat is de hoofdconclusie van opname 20260122_100025?"

Workflow:
1. get_transcription_summary(20260122_100025)
   → Lees conclusion_words
2. Klaar! (geen extra chunks nodig)
```

### Voorbeeld 2: Detailed Summary

```
Q: "Maak een gedetailleerde summary van opname 20260122_100025"

Workflow:
1. get_transcription_summary(20260122_100025)
   → 27 chunks, 54.9 minuten
2. get_transcription_chunked(20260122_100025, 0)
   → Opening
3. get_transcription_chunked(20260122_100025, 7)
   → Kwartier punt
4. get_transcription_chunked(20260122_100025, 13)
   → Halverwege
5. get_transcription_chunked(20260122_100025, 20)
   → Driekwart punt
6. get_transcription_chunked(20260122_100025, -1)
   → Afsluiting
7. Maak summary op basis van 5 strategische chunks
   → Dekkende coverage zonder full context
```

### Voorbeeld 3: Search for Topics

```
Q: "Zoek discussie over 'budget' in opname 20260122_100025"

Workflow:
1. get_transcription_summary(20260122_100025)
   → 27 chunks
2. get_transcription_chunked(20260122_100025, 0)
   → Controleer eerste chunk op 'budget'
3. Indien gevonden: lees verder
4. Indien niet: probeer volgende chunks
5. Optimalisatie: binaire search door chunks
```

## Toekomstige Verbeteringen

Potentiële uitbreidingen:
- [ ] Semantic chunking (splits op paragrafen/onderwerpen)
- [ ] Keyword-based chunk selection
- [ ] Automatic topic detection per chunk
- [ ] Vector embeddings voor similarity search
- [ ] Timestamp mapping (chunk → audio tijdstip)

## Referenties

- [Agent Skills for Context Engineering](https://github.com/muratcankoylan/Agent-Skills-for-Context-Engineering)
- Context window limitations en "lost-in-the-middle" effect
- Progressive disclosure patterns voor LLMs
