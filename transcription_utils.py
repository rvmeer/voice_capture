"""
Transcription Utilities
Shared functions for transcription processing
"""

from logging_config import get_logger

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
