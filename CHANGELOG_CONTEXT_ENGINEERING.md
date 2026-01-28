# Changelog: Context Engineering Features

## 2026-01-22: Context Engineering Uitbreidingen

### Nieuwe Features

#### 1. **get_transcription_summary** Tool
Haalt metadata en samenvatting op zonder volledige transcriptie te laden.

**Retourneert**:
- Word count, duration, speech rate
- First ~500 words (preview)
- Last ~500 words (conclusion)
- Detected speakers
- Total number of chunks
- Estimated reading time

**Use Case**: Altijd EERST aanroepen voor lange transcripties om scope te begrijpen.

#### 2. **get_transcription_chunked** Tool
Haalt specifieke chunk op met ~500 woorden + 50 woorden overlap.

**Features**:
- Supports negative indexing (-1 = last chunk)
- Configurable chunk size and overlap
- Includes position metadata
- Prevents "lost-in-the-middle" effect

**Use Case**: Progressive loading van alleen benodigde delen.

#### 3. **get_transcription** Tool Update
Bestaande tool blijft werken voor backwards compatibility, maar geeft nu waarschuwing voor lange transcripties.

### Nieuwe Utilities (transcription_utils.py)

- **get_transcription_metadata()**: Extract comprehensive metadata from text
- **chunk_transcription()**: Split text into overlapping chunks
- **get_chunk_by_index()**: Retrieve specific chunk by index
- **parse_duration()**: Parse ISO 8601 duration format (PT1H23M45S)
- **extract_speakers()**: Detect speaker labels in transcription

### Testing

Twee nieuwe test suites toegevoegd:
- `test_context_engineering.py`: Unit tests voor chunking logic
- `test_mcp_integration.py`: Integration tests met echte opnames

**Test Results**: ✅ ALL TESTS PASSED

### Context Engineering Principes

Gebaseerd op [Agent-Skills-for-Context-Engineering](https://github.com/muratcankoylan/Agent-Skills-for-Context-Engineering):

1. **Progressive Disclosure**: Load metadata first, full content on demand
2. **Chunking with Overlap**: Prevent information loss at boundaries
3. **Front-loading Critical Info**: Start/end contain key details
4. **Minimal High-Signal Tokens**: Efficiency over comprehensiveness

### Technical Changes

**Modified Files**:
- `transcription_utils.py`: Added 5 new functions (185 lines)
- `mcp_server.py`: Added 2 new tools + handlers (118 lines)

**New Files**:
- `test_context_engineering.py`: Comprehensive unit tests
- `test_mcp_integration.py`: Integration tests with real recordings
- `CONTEXT_ENGINEERING.md`: Full documentation (270 lines)
- `CHANGELOG_CONTEXT_ENGINEERING.md`: This file

### Breaking Changes

**None** - All changes are backwards compatible. Existing `get_transcription` tool still works.

### Example Usage

#### Before (problematic for long recordings):
```python
# Loads entire 12,000 word transcription → context overload
text = get_transcription("20260122_100025")
```

#### After (context-efficient):
```python
# Step 1: Get overview (only ~1000 words)
summary = get_transcription_summary("20260122_100025")
# → Shows: 12,064 words, 27 chunks, 54.9 minutes

# Step 2: Load only relevant chunks
intro = get_transcription_chunked("20260122_100025", 0)      # First chunk
middle = get_transcription_chunked("20260122_100025", 13)    # Middle
conclusion = get_transcription_chunked("20260122_100025", -1) # Last chunk

# Result: Processed ~1,500 words instead of 12,000
# Saved: 87% context budget while maintaining coverage
```

### Performance Benefits

**Test Case**: 55-minute recording with 12,064 words

| Approach | Words Loaded | Context Efficiency | Coverage |
|----------|--------------|-------------------|----------|
| get_transcription | 12,064 | 0% | 100% |
| Summary only | ~1,000 | 92% saved | Edges only |
| Summary + 3 chunks | ~2,500 | 79% saved | Strategic |
| Summary + 5 chunks | ~3,500 | 71% saved | Comprehensive |

### Migration Guide

**For Claude/AI Assistants**:

1. **Short recordings (<10 min, <2000 words)**:
   - Continue using `get_transcription()` directly

2. **Long recordings (30+ min, 5000+ words)**:
   - ✅ Start with `get_transcription_summary()`
   - ✅ Analyze preview and conclusion
   - ✅ Load specific chunks as needed
   - ❌ Avoid loading full transcription

3. **Very long recordings (2+ hours, 20000+ words)**:
   - ✅ MUST use chunked approach
   - ✅ Never load full transcription
   - ✅ Use binary search strategy through chunks

### Future Enhancements

Potential improvements:
- Semantic chunking (split on topics/paragraphs)
- Keyword-based chunk filtering
- Automatic topic detection per chunk
- Vector embeddings for similarity search
- Timestamp mapping (chunk index → audio timestamp)

### Documentation

Full documentation available in:
- `CONTEXT_ENGINEERING.md`: Complete guide with examples
- `transcription_utils.py`: Docstrings for all functions
- `mcp_server.py`: Tool descriptions for MCP clients

### Testing

Run tests to verify installation:
```bash
python test_context_engineering.py    # Unit tests
python test_mcp_integration.py        # Integration tests
```

Both test suites should pass with "✓ ALL TESTS PASSED".

---

**Summary**: Voice Capture MCP server now handles long transcriptions efficiently using context engineering principles. No breaking changes - fully backwards compatible.
