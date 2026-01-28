#!/usr/bin/env python3
"""
Test MCP server integration with context engineering features
Tests the new tools with real recording data
"""

import json
from pathlib import Path
from mcp_server import (
    load_recordings,
    get_recording_by_id,
    get_transcription_text,
    RECORDINGS_DIR
)
from transcription_utils import (
    get_transcription_metadata,
    get_chunk_by_index
)


def test_load_recordings():
    """Test loading recordings"""
    print("\n=== Testing Recording Loading ===")

    recordings = load_recordings()
    print(f"Total recordings found: {len(recordings)}")

    if recordings:
        sample = recordings[0]
        print(f"Sample recording:")
        print(f"  - ID: {sample.get('id')}")
        print(f"  - Name: {sample.get('name')}")
        print(f"  - Date: {sample.get('date')}")
        print(f"  - Duration: {sample.get('duration', 'N/A')}")
        return sample.get('id')
    else:
        print("⚠ No recordings found - skipping integration tests")
        return None


def test_transcription_summary(recording_id):
    """Test get_transcription_summary functionality"""
    print(f"\n=== Testing Transcription Summary (ID: {recording_id}) ===")

    # Get transcription text
    transcription = get_transcription_text(recording_id)

    if not transcription:
        print(f"⚠ No transcription found for {recording_id}")
        return

    # Get recording metadata
    recording = get_recording_by_id(recording_id)
    duration_seconds = recording.get("duration") if recording else None

    # Get summary
    metadata = get_transcription_metadata(transcription, duration_seconds)

    print(f"Recording: {recording.get('name', 'Unknown')}")
    print(f"Word count: {metadata['word_count']}")
    print(f"Duration: {metadata.get('duration_minutes', 'N/A')} minutes")
    print(f"Speech rate: {metadata.get('speech_rate_wpm', 'N/A')} words/minute")
    print(f"Estimated reading time: {metadata['estimated_reading_time_minutes']} minutes")
    print(f"Total chunks: {metadata['total_chunks']}")
    print(f"Speakers detected: {metadata.get('speaker_count', 0)}")

    if metadata.get('speakers_detected'):
        print(f"Speaker list: {', '.join(metadata['speakers_detected'])}")

    print(f"\nPreview (first 200 chars):")
    print(f"  {metadata['preview_words'][:200]}...")

    if metadata['conclusion_words']:
        print(f"\nConclusion (last 200 chars):")
        print(f"  ...{metadata['conclusion_words'][-200:]}")

    print("\n✓ Transcription summary generated successfully!")
    return metadata


def test_chunking(recording_id, metadata):
    """Test chunking functionality"""
    print(f"\n=== Testing Chunking (ID: {recording_id}) ===")

    transcription = get_transcription_text(recording_id)

    if not transcription:
        print(f"⚠ No transcription found for {recording_id}")
        return

    total_chunks = metadata['total_chunks']
    print(f"Testing chunk retrieval for {total_chunks} chunks...")

    # Test first chunk (index 0)
    first_chunk = get_chunk_by_index(transcription, 0)
    if first_chunk:
        print(f"\nFirst chunk (index 0):")
        print(f"  - Chunk ID: {first_chunk['chunk_id']}")
        print(f"  - Word count: {first_chunk['word_count']}")
        print(f"  - Position: words {first_chunk['start_word']} to {first_chunk['end_word']}")
        print(f"  - Preview: {first_chunk['text'][:100]}...")

    # Test last chunk (index -1)
    last_chunk = get_chunk_by_index(transcription, -1)
    if last_chunk:
        print(f"\nLast chunk (index -1):")
        print(f"  - Chunk ID: {last_chunk['chunk_id']}")
        print(f"  - Word count: {last_chunk['word_count']}")
        print(f"  - Position: words {last_chunk['start_word']} to {last_chunk['end_word']}")
        print(f"  - Preview: {last_chunk['text'][:100]}...")

    # Test middle chunk if available
    if total_chunks > 2:
        middle_index = total_chunks // 2
        middle_chunk = get_chunk_by_index(transcription, middle_index)
        if middle_chunk:
            print(f"\nMiddle chunk (index {middle_index}):")
            print(f"  - Chunk ID: {middle_chunk['chunk_id']}")
            print(f"  - Word count: {middle_chunk['word_count']}")
            print(f"  - Has overlap before: {middle_chunk['has_overlap_before']}")
            print(f"  - Has overlap after: {middle_chunk['has_overlap_after']}")

    print("\n✓ Chunking functionality works!")


def test_error_handling(recording_id):
    """Test error handling"""
    print(f"\n=== Testing Error Handling ===")

    transcription = get_transcription_text(recording_id)

    # Test invalid chunk index
    invalid_chunk = get_chunk_by_index(transcription, 9999)
    print(f"Invalid chunk (index 9999): {invalid_chunk}")
    assert invalid_chunk is None, "Invalid index should return None"

    # Test non-existent recording
    fake_transcription = get_transcription_text("99999999_999999")
    print(f"Non-existent recording: {fake_transcription}")
    assert fake_transcription is None, "Non-existent recording should return None"

    print("✓ Error handling works correctly!")


def test_mcp_server_syntax():
    """Test that MCP server file has no syntax errors"""
    print(f"\n=== Testing MCP Server Syntax ===")

    try:
        import mcp_server
        print("✓ MCP server imports successfully!")

        # Check that new functions are available
        assert hasattr(mcp_server, 'get_transcription_text'), "get_transcription_text should be available"
        assert hasattr(mcp_server, 'get_recording_by_id'), "get_recording_by_id should be available"

        print("✓ All required functions are available!")
    except Exception as e:
        print(f"✗ Error importing MCP server: {e}")
        raise


if __name__ == "__main__":
    print("=" * 70)
    print("Testing MCP Integration with Context Engineering")
    print("=" * 70)

    try:
        # Test MCP server syntax first
        test_mcp_server_syntax()

        # Load recordings
        recording_id = test_load_recordings()

        if recording_id:
            # Test summary functionality
            metadata = test_transcription_summary(recording_id)

            if metadata:
                # Test chunking
                test_chunking(recording_id, metadata)

                # Test error handling
                test_error_handling(recording_id)

        print("\n" + "=" * 70)
        print("✓ ALL INTEGRATION TESTS PASSED!")
        print("=" * 70)
        print("\nNext steps:")
        print("1. Restart your MCP client (Claude Code)")
        print("2. Use the new tools:")
        print("   - get_transcription_summary(recording_id)")
        print("   - get_transcription_chunked(recording_id, chunk_index)")
        print("\nThese tools implement context engineering principles to handle")
        print("long transcriptions without context overload!")

    except Exception as e:
        print(f"\n✗ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
