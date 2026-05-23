"""
Transcription Utilities
Shared functions for transcription processing
"""

from logging_config import get_logger

logger = get_logger(__name__)


WHISPER_SILENCE_HALLUCINATIONS = {"Thank you.", "you", "You"}


def is_empty_segment(text: str) -> bool:
    """Return True if a transcription segment contains no real content.

    Covers both truly empty segments and known Whisper silence hallucinations.
    """
    if not text or not text.strip():
        return True
    return text.strip() in WHISPER_SILENCE_HALLUCINATIONS


def remove_overlap(previous_text: str, new_text: str) -> str:
    """Remove overlapping text between segments"""
    if not previous_text or not new_text:
        return new_text

    prev_words = previous_text.split()
    new_words = new_text.split()

    max_overlap = min(50, len(prev_words), len(new_words))

    best_overlap_length = 0
    for overlap_len in range(max_overlap, 0, -1):
        prev_tail = prev_words[-overlap_len:]
        new_head = new_words[:overlap_len]

        matches = sum(1 for p, n in zip(prev_tail, new_head) if p.lower() == n.lower())
        similarity = matches / overlap_len

        if similarity >= 0.7:
            best_overlap_length = overlap_len
            logger.debug(f"Found overlap of {overlap_len} words with {similarity:.1%} similarity")
            break

    if best_overlap_length > 0:
        deduplicated = " ".join(new_words[best_overlap_length:])
        logger.debug(f"Removed {best_overlap_length} overlapping words")
        return deduplicated
    else:
        return new_text
