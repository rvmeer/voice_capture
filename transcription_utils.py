"""
Transcription Utilities
Shared functions for transcription processing

Context Engineering Principles:
- Progressive disclosure: Load metadata first, full content on demand
- Chunking with overlap: Prevent lost-in-the-middle effect
- Front-load critical information: Start/end contain key details
"""

from logging_config import get_logger
from typing import Dict, List, Optional, Any, Union
import re

logger = get_logger(__name__)


def remove_overlap(previous_text: str, new_text: str) -> str:
    """Remove overlapping text between segments

    Args:
        previous_text: The text from the previous segment
        new_text: The text from the new segment

    Returns:
        The new text with overlapping portion removed
    """
    if not previous_text or not new_text:
        return new_text

    # Split into words
    prev_words = previous_text.split()
    new_words = new_text.split()

    # Look for overlap at the end of previous and beginning of new
    # Check up to 50 words (covers ~15 seconds at normal speech rate)
    max_overlap = min(50, len(prev_words), len(new_words))

    best_overlap_length = 0
    for overlap_len in range(max_overlap, 0, -1):
        # Get last N words from previous text
        prev_tail = prev_words[-overlap_len:]
        # Get first N words from new text
        new_head = new_words[:overlap_len]

        # Calculate similarity (allow for some transcription variations)
        matches = sum(1 for p, n in zip(prev_tail, new_head) if p.lower() == n.lower())
        similarity = matches / overlap_len

        # If 70% or more words match, consider it an overlap
        if similarity >= 0.7:
            best_overlap_length = overlap_len
            logger.debug(f"Found overlap of {overlap_len} words with {similarity:.1%} similarity")
            break

    # Remove the overlapping portion from the new text
    if best_overlap_length > 0:
        deduplicated = " ".join(new_words[best_overlap_length:])
        logger.debug(f"Removed {best_overlap_length} overlapping words")
        return deduplicated
    else:
        return new_text


def count_words(text: str) -> int:
    """Count words in text, handling punctuation and whitespace properly"""
    # Remove extra whitespace and split on word boundaries
    words = text.split()
    return len(words)


def extract_speakers(text: str) -> List[str]:
    """
    Attempt to detect speaker labels in transcription text.

    Common patterns:
    - "Speaker 1:", "Speaker A:", "[SPEAKER_00]"
    - "John:", "Mary:"

    Args:
        text: The transcription text

    Returns:
        List of unique speaker identifiers found
    """
    speakers = set()

    # Pattern 1: "Speaker X:" or "[Speaker X]" or "[SPEAKER_XX]"
    pattern1 = re.findall(r'(?:Speaker\s+[A-Z0-9]+|SPEAKER_\d+)', text, re.IGNORECASE)
    speakers.update(pattern1)

    # Pattern 2: Names followed by colon (capitalized words)
    # Look for pattern like "John: " at start of lines or after periods
    pattern2 = re.findall(r'(?:^|\. )([A-Z][a-z]+):', text, re.MULTILINE)
    speakers.update(pattern2)

    return sorted(list(speakers))


def parse_duration(duration: Union[str, int, float, None]) -> Optional[float]:
    """
    Parse duration from various formats to seconds.

    Args:
        duration: Duration as ISO 8601 string (e.g., "PT1H23M45S"), seconds (float/int), or None

    Returns:
        Duration in seconds, or None if invalid/missing
    """
    if duration is None:
        return None

    # If already numeric (seconds)
    if isinstance(duration, (int, float)):
        return float(duration)

    # If string, try to parse as ISO 8601
    if isinstance(duration, str):
        try:
            # Simple ISO 8601 duration parser for format like: PT1H23M45S
            # P = Period, T = Time separator, H = Hours, M = Minutes, S = Seconds
            if not duration.startswith('PT'):
                logger.warning(f"Duration format not supported (expected PT...): '{duration}'")
                return None

            # Remove PT prefix
            time_part = duration[2:]

            # Extract hours, minutes, seconds
            hours = 0
            minutes = 0
            seconds = 0

            # Parse hours
            if 'H' in time_part:
                h_parts = time_part.split('H')
                hours = float(h_parts[0])
                time_part = h_parts[1]

            # Parse minutes
            if 'M' in time_part:
                m_parts = time_part.split('M')
                minutes = float(m_parts[0])
                time_part = m_parts[1]

            # Parse seconds
            if 'S' in time_part:
                s_parts = time_part.split('S')
                seconds = float(s_parts[0])

            total_seconds = hours * 3600 + minutes * 60 + seconds
            return total_seconds

        except Exception as e:
            logger.warning(f"Failed to parse duration '{duration}': {e}")
            return None

    return None


def get_transcription_metadata(text: str, duration: Optional[Union[str, int, float]] = None) -> Dict[str, Any]:
    """
    Extract metadata from transcription text.

    Context Engineering: Front-load critical information before loading full text.
    This allows LLMs to understand scope and structure before processing content.

    Args:
        text: The full transcription text
        duration: Optional duration as ISO 8601 string (e.g., "PT1H23M45S") or seconds (int/float)

    Returns:
        Dictionary with metadata including:
        - word_count: Total number of words
        - duration_minutes: Duration in minutes (if available)
        - estimated_reading_time_minutes: Approximate time to read
        - speakers: List of detected speaker identifiers
        - preview_words: First ~500 words for context
        - conclusion_words: Last ~500 words for conclusions
        - total_chunks: Number of chunks (assuming 500 words per chunk with 50 word overlap)
    """
    if not text:
        return {
            "word_count": 0,
            "error": "Empty transcription"
        }

    word_count = count_words(text)
    words = text.split()

    # Calculate preview and conclusion sizes (aim for ~500 words each)
    preview_size = min(500, word_count)
    conclusion_size = min(500, word_count)

    preview_text = " ".join(words[:preview_size])
    conclusion_text = " ".join(words[-conclusion_size:]) if word_count > preview_size else ""

    # Detect speakers
    speakers = extract_speakers(text)

    # Calculate chunk information (500 words per chunk, 50 word overlap)
    chunk_size = 500
    overlap = 50
    effective_chunk_size = chunk_size - overlap
    total_chunks = max(1, (word_count - overlap) // effective_chunk_size +
                      (1 if (word_count - overlap) % effective_chunk_size > 0 else 0))

    metadata = {
        "word_count": word_count,
        "preview_words": preview_text,
        "conclusion_words": conclusion_text,
        "speakers_detected": speakers if speakers else None,
        "speaker_count": len(speakers) if speakers else 0,
        "total_chunks": total_chunks,
        "chunk_size": chunk_size,
        "chunk_overlap": overlap,
        "estimated_reading_time_minutes": round(word_count / 200, 1)  # ~200 words/minute reading speed
    }

    # Add duration information if available
    duration_seconds = parse_duration(duration)
    if duration_seconds is not None:
        metadata["duration_minutes"] = round(duration_seconds / 60, 1)
        metadata["speech_rate_wpm"] = round(word_count / (duration_seconds / 60), 1)

    logger.info(f"Extracted metadata: {word_count} words, {total_chunks} chunks, {len(speakers)} speakers")

    return metadata


def chunk_transcription(text: str, chunk_size: int = 500, overlap: int = 50) -> List[Dict[str, Any]]:
    """
    Split transcription into overlapping chunks for progressive processing.

    Context Engineering Principle: Chunking with overlap prevents the "lost-in-the-middle"
    effect by ensuring no critical information is split across chunk boundaries.

    Args:
        text: The full transcription text
        chunk_size: Target number of words per chunk (default: 500)
        overlap: Number of words to overlap between chunks (default: 50)

    Returns:
        List of dictionaries, each containing:
        - chunk_index: 0-based index of the chunk
        - chunk_id: Human-readable ID (e.g., "chunk_0", "chunk_1")
        - text: The chunk text
        - word_count: Number of words in this chunk
        - start_word: Starting word position in full text (0-based)
        - end_word: Ending word position in full text
        - has_overlap_before: Boolean indicating if this chunk overlaps with previous
        - has_overlap_after: Boolean indicating if this chunk overlaps with next
    """
    if not text:
        return []

    words = text.split()
    total_words = len(words)

    if total_words <= chunk_size:
        # Text is small enough to fit in one chunk
        return [{
            "chunk_index": 0,
            "chunk_id": "chunk_0",
            "text": text,
            "word_count": total_words,
            "start_word": 0,
            "end_word": total_words,
            "has_overlap_before": False,
            "has_overlap_after": False
        }]

    chunks = []
    current_position = 0
    chunk_index = 0

    while current_position < total_words:
        # Calculate end position for this chunk
        end_position = min(current_position + chunk_size, total_words)

        # Extract chunk words
        chunk_words = words[current_position:end_position]
        chunk_text = " ".join(chunk_words)

        # Determine if there's overlap
        has_overlap_before = current_position > 0
        has_overlap_after = end_position < total_words

        chunk_data = {
            "chunk_index": chunk_index,
            "chunk_id": f"chunk_{chunk_index}",
            "text": chunk_text,
            "word_count": len(chunk_words),
            "start_word": current_position,
            "end_word": end_position,
            "has_overlap_before": has_overlap_before,
            "has_overlap_after": has_overlap_after
        }

        chunks.append(chunk_data)

        # Move to next chunk position (with overlap)
        current_position += chunk_size - overlap
        chunk_index += 1

        # Prevent infinite loop if overlap >= chunk_size
        if chunk_size <= overlap:
            logger.error(f"Invalid chunking: overlap ({overlap}) >= chunk_size ({chunk_size})")
            break

    logger.info(f"Created {len(chunks)} chunks from {total_words} words (size={chunk_size}, overlap={overlap})")

    return chunks


def get_chunk_by_index(text: str, chunk_index: int, chunk_size: int = 500, overlap: int = 50) -> Optional[Dict[str, Any]]:
    """
    Get a specific chunk by index. Supports negative indexing (-1 = last chunk).

    Context Engineering: Progressive disclosure - load only the chunk needed.

    Args:
        text: The full transcription text
        chunk_index: Index of chunk to retrieve (supports negative indexing)
        chunk_size: Target number of words per chunk (default: 500)
        overlap: Number of words to overlap between chunks (default: 50)

    Returns:
        Dictionary with chunk information, or None if index is out of range
    """
    chunks = chunk_transcription(text, chunk_size, overlap)

    if not chunks:
        return None

    # Handle negative indexing
    if chunk_index < 0:
        chunk_index = len(chunks) + chunk_index

    # Check bounds
    if chunk_index < 0 or chunk_index >= len(chunks):
        logger.warning(f"Chunk index {chunk_index} out of range (0 to {len(chunks)-1})")
        return None

    return chunks[chunk_index]
