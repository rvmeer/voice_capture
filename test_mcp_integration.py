#!/usr/bin/env python3
"""
Test MCP server integration
Tests the MCP tools with real recording data
"""

from mcp_server import (
    load_recordings,
    get_recording_by_id,
    get_transcription_text,
    RECORDINGS_DIR
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
        print("No recordings found - skipping integration tests")
        return None


def test_error_handling(recording_id):
    """Test error handling"""
    print(f"\n=== Testing Error Handling ===")

    # Test non-existent recording
    fake_transcription = get_transcription_text("99999999_999999")
    print(f"Non-existent recording: {fake_transcription}")
    assert fake_transcription is None, "Non-existent recording should return None"

    print("Error handling works correctly!")


def test_mcp_server_syntax():
    """Test that MCP server file has no syntax errors"""
    print(f"\n=== Testing MCP Server Syntax ===")

    try:
        import mcp_server
        print("MCP server imports successfully!")

        assert hasattr(mcp_server, 'get_transcription_text'), "get_transcription_text should be available"
        assert hasattr(mcp_server, 'get_recording_by_id'), "get_recording_by_id should be available"

        print("All required functions are available!")
    except Exception as e:
        print(f"Error importing MCP server: {e}")
        raise


if __name__ == "__main__":
    print("=" * 70)
    print("Testing MCP Integration")
    print("=" * 70)

    try:
        test_mcp_server_syntax()

        recording_id = test_load_recordings()

        if recording_id:
            test_error_handling(recording_id)

        print("\n" + "=" * 70)
        print("ALL INTEGRATION TESTS PASSED!")
        print("=" * 70)

    except Exception as e:
        print(f"\nTEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
