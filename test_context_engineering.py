#!/usr/bin/env python3
"""
Test script for context engineering features in transcription_utils
"""

from transcription_utils import (
    get_transcription_metadata,
    chunk_transcription,
    get_chunk_by_index,
    extract_speakers
)


def test_metadata_extraction():
    """Test metadata extraction from sample text"""
    print("\n=== Testing Metadata Extraction ===")

    # Create sample transcription (simulate a meeting)
    sample_text = " ".join(["This is a test word."] * 100)  # 500 words

    metadata = get_transcription_metadata(sample_text, duration_seconds=300)

    print(f"Word count: {metadata['word_count']}")
    print(f"Duration: {metadata.get('duration_minutes', 'N/A')} minutes")
    print(f"Estimated reading time: {metadata['estimated_reading_time_minutes']} minutes")
    print(f"Total chunks: {metadata['total_chunks']}")
    print(f"Chunk size: {metadata['chunk_size']}")
    print(f"Chunk overlap: {metadata['chunk_overlap']}")
    print(f"Preview (first 50 chars): {metadata['preview_words'][:50]}...")

    assert metadata['word_count'] == 500, f"Expected 500 words, got {metadata['word_count']}"
    print("✓ Metadata extraction works!")


def test_speaker_detection():
    """Test speaker detection patterns"""
    print("\n=== Testing Speaker Detection ===")

    text_with_speakers = """
    Speaker 1: Hello everyone, welcome to the meeting.
    Speaker 2: Thanks for having me.
    John: I have a question about the project.
    Mary: Let me answer that.
    """

    speakers = extract_speakers(text_with_speakers)
    print(f"Detected speakers: {speakers}")

    assert len(speakers) > 0, "Should detect at least one speaker"
    print("✓ Speaker detection works!")


def test_chunking():
    """Test transcription chunking with overlap"""
    print("\n=== Testing Chunking ===")

    # Create sample text (1200 words)
    words = [f"word{i}" for i in range(1200)]
    sample_text = " ".join(words)

    chunks = chunk_transcription(sample_text, chunk_size=500, overlap=50)

    print(f"Total chunks created: {len(chunks)}")

    for i, chunk in enumerate(chunks[:3]):  # Show first 3 chunks
        print(f"\nChunk {i}:")
        print(f"  - Index: {chunk['chunk_index']}")
        print(f"  - ID: {chunk['chunk_id']}")
        print(f"  - Word count: {chunk['word_count']}")
        print(f"  - Start word: {chunk['start_word']}")
        print(f"  - End word: {chunk['end_word']}")
        print(f"  - Has overlap before: {chunk['has_overlap_before']}")
        print(f"  - Has overlap after: {chunk['has_overlap_after']}")
        print(f"  - Text preview: {chunk['text'][:50]}...")

    # Verify overlap
    if len(chunks) > 1:
        chunk0_words = chunks[0]['text'].split()
        chunk1_words = chunks[1]['text'].split()

        # Last 50 words of chunk 0 should match first 50 words of chunk 1
        overlap_words_0 = chunk0_words[-50:]
        overlap_words_1 = chunk1_words[:50]

        overlap_match = overlap_words_0 == overlap_words_1
        print(f"\n✓ Overlap verification: {'PASS' if overlap_match else 'FAIL'}")

        if not overlap_match:
            print(f"  Chunk 0 last words: {' '.join(overlap_words_0[-5:])}")
            print(f"  Chunk 1 first words: {' '.join(overlap_words_1[:5])}")

    assert len(chunks) == 3, f"Expected 3 chunks for 1200 words, got {len(chunks)}"
    print("✓ Chunking works!")


def test_chunk_indexing():
    """Test getting specific chunks by index"""
    print("\n=== Testing Chunk Indexing ===")

    words = [f"word{i}" for i in range(1200)]
    sample_text = " ".join(words)

    # Test positive indexing
    first_chunk = get_chunk_by_index(sample_text, 0)
    print(f"First chunk (index 0): {first_chunk['chunk_id']}")

    # Test negative indexing
    last_chunk = get_chunk_by_index(sample_text, -1)
    print(f"Last chunk (index -1): {last_chunk['chunk_id']}")

    second_last_chunk = get_chunk_by_index(sample_text, -2)
    print(f"Second-to-last chunk (index -2): {second_last_chunk['chunk_id']}")

    # Test out of bounds
    invalid_chunk = get_chunk_by_index(sample_text, 999)
    print(f"Invalid chunk (index 999): {invalid_chunk}")

    assert first_chunk is not None, "First chunk should exist"
    assert last_chunk is not None, "Last chunk should exist"
    assert invalid_chunk is None, "Invalid index should return None"
    print("✓ Chunk indexing works!")


def test_small_text():
    """Test with text smaller than chunk size"""
    print("\n=== Testing Small Text ===")

    small_text = "This is a very short text with only a few words."

    metadata = get_transcription_metadata(small_text)
    chunks = chunk_transcription(small_text, chunk_size=500)

    print(f"Word count: {metadata['word_count']}")
    print(f"Total chunks: {len(chunks)}")
    print(f"Preview equals conclusion: {metadata['preview_words'] == metadata['conclusion_words']}")

    assert len(chunks) == 1, "Small text should result in 1 chunk"
    assert not chunks[0]['has_overlap_after'], "Single chunk should have no overlap after"
    print("✓ Small text handling works!")


if __name__ == "__main__":
    print("=" * 60)
    print("Testing Context Engineering Features")
    print("=" * 60)

    try:
        test_metadata_extraction()
        test_speaker_detection()
        test_chunking()
        test_chunk_indexing()
        test_small_text()

        print("\n" + "=" * 60)
        print("✓ ALL TESTS PASSED!")
        print("=" * 60)

    except AssertionError as e:
        print(f"\n✗ TEST FAILED: {e}")
        exit(1)
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
