#!/usr/bin/env python3
"""
MCP Server for Whisper Demo Recordings
Provides access to recordings, metadata, and transcriptions via MCP protocol
"""

import json
import asyncio
from pathlib import Path
from typing import Any
from mcp.server.models import InitializationOptions
from mcp.server import NotificationOptions, Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# Setup logging FIRST - DISABLE console output for MCP (uses stdio for JSON-RPC)
from logging_config import setup_logging, get_logger
setup_logging(enable_console=False)

# Import recording manager for title updates (after logging is configured)
from recording_manager import RecordingManager
from transcription_utils import remove_overlap

logger = get_logger(__name__)

# Initialize MCP server
server = Server("whisper-recordings-server")

# Path to recordings directory - use Documents/VoiceCapture
RECORDINGS_DIR = Path.home() / "Documents" / "VoiceCapture"

# Initialize recording manager with same directory
recording_manager = RecordingManager(recordings_dir=str(RECORDINGS_DIR))


def load_recordings() -> list[dict]:
    """Load all recordings from individual JSON files in subfolders"""
    recordings = []

    try:
        if not RECORDINGS_DIR.exists():
            return []

        # Find all recording_* directories
        recording_dirs = sorted(
            [d for d in RECORDINGS_DIR.iterdir() if d.is_dir() and d.name.startswith('recording_')],
            key=lambda d: d.name,
            reverse=True  # Most recent first
        )

        # Load each recording's JSON file
        for rec_dir in recording_dirs:
            json_file = rec_dir / f"{rec_dir.name}.json"

            if json_file.exists():
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        recording = json.load(f)
                        recordings.append(recording)
                except Exception as e:
                    logger.error(f"Error loading recording from {json_file}: {e}", exc_info=True)

    except Exception as e:
        logger.error(f"Error loading recordings: {e}", exc_info=True)

    return recordings


def get_recording_by_id(recording_id: str) -> dict | None:
    """Get a specific recording by ID"""
    recordings = load_recordings()
    for rec in recordings:
        if rec.get("id") == recording_id:
            return rec
    return None


def get_transcription_text(recording_id: str) -> str | None:
    """Get the transcription text for a recording"""
    rec_dir = RECORDINGS_DIR / f"recording_{recording_id}"
    transcription_file = rec_dir / f"transcription_{recording_id}.txt"

    # Try to read the final transcription file
    if transcription_file.exists():
        try:
            with open(transcription_file, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            logger.error(f"Error reading transcription file: {e}", exc_info=True)
            return None

    # If no final transcription, try to combine segment transcriptions
    segments_dir = rec_dir / "segments"
    if segments_dir.exists():
        try:
            # Find all transcription files in segments folder (sorted by number)
            transcription_files = sorted(segments_dir.glob("transcription_*.txt"))

            if transcription_files:
                logger.info(f"No final transcription found for {recording_id}, combining {len(transcription_files)} segment transcriptions")

                # Read all segment transcriptions
                segment_texts = []
                for trans_file in transcription_files:
                    try:
                        with open(trans_file, 'r', encoding='utf-8') as f:
                            text = f.read().strip()
                            if text:
                                segment_texts.append(text)
                    except Exception as e:
                        logger.error(f"Failed to read {trans_file}: {e}")

                # Combine all texts with overlap removal
                if segment_texts:
                    combined_texts = []
                    for i, text in enumerate(segment_texts):
                        if i == 0:
                            # First segment - add as-is
                            combined_texts.append(text)
                        else:
                            # Remove overlap with previous segment
                            previous_text = combined_texts[-1]
                            deduplicated_text = remove_overlap(previous_text, text)
                            if deduplicated_text.strip():
                                combined_texts.append(deduplicated_text)

                    final_transcription = " ".join(combined_texts)
                    logger.info(f"Combined {len(segment_texts)} segment transcriptions with overlap removal ({len(final_transcription)} chars)")
                    return final_transcription
        except Exception as e:
            logger.error(f"Error combining segment transcriptions: {e}", exc_info=True)

    # Fallback to JSON if TXT doesn't exist
    recording = get_recording_by_id(recording_id)
    if recording:
        return recording.get("transcription", "")

    return None


@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    """List available tools"""
    return [
        Tool(
            name="get_recordings",
            description="Get a list of all recordings with their date and name",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="get_recording",
            description="Get the complete JSON metadata for a specific recording by ID",
            inputSchema={
                "type": "object",
                "properties": {
                    "recording_id": {
                        "type": "string",
                        "description": "The ID (timestamp) of the recording to retrieve"
                    }
                },
                "required": ["recording_id"]
            }
        ),
        Tool(
            name="get_transcription",
            description="Get the transcription text for a specific recording by ID",
            inputSchema={
                "type": "object",
                "properties": {
                    "recording_id": {
                        "type": "string",
                        "description": "The ID (timestamp) of the recording to retrieve transcription for"
                    }
                },
                "required": ["recording_id"]
            }
        ),
        Tool(
            name="update_recording_title",
            description="Update the title/name of a specific recording",
            inputSchema={
                "type": "object",
                "properties": {
                    "recording_id": {
                        "type": "string",
                        "description": "The ID (timestamp) of the recording to update"
                    },
                    "new_title": {
                        "type": "string",
                        "description": "The new title/name for the recording"
                    }
                },
                "required": ["recording_id", "new_title"]
            }
        )
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle tool execution"""

    if name == "get_recordings":
        # Get all recordings with date and name
        recordings = load_recordings()
        result = []

        for rec in recordings:
            rec_data = {
                "id": rec.get("id"),
                "date": rec.get("date"),
                "name": rec.get("name")
            }
            # Only include duration if it exists in the recording
            if "duration" in rec:
                rec_data["duration"] = rec.get("duration")
            result.append(rec_data)

        return [
            TextContent(
                type="text",
                text=json.dumps(result, indent=2, ensure_ascii=False)
            )
        ]

    elif name == "get_recording":
        # Get complete recording JSON
        recording_id = arguments.get("recording_id")

        if not recording_id:
            return [
                TextContent(
                    type="text",
                    text=json.dumps({"error": "recording_id is required"})
                )
            ]

        recording = get_recording_by_id(recording_id)

        if recording is None:
            return [
                TextContent(
                    type="text",
                    text=json.dumps({"error": f"Recording with id '{recording_id}' not found"})
                )
            ]

        return [
            TextContent(
                type="text",
                text=json.dumps(recording, indent=2, ensure_ascii=False)
            )
        ]

    elif name == "get_transcription":
        # Get transcription text
        recording_id = arguments.get("recording_id")

        if not recording_id:
            return [
                TextContent(
                    type="text",
                    text=json.dumps({"error": "recording_id is required"})
                )
            ]

        transcription = get_transcription_text(recording_id)

        if transcription is None:
            return [
                TextContent(
                    type="text",
                    text=json.dumps({"error": f"Transcription for recording '{recording_id}' not found"})
                )
            ]

        return [
            TextContent(
                type="text",
                text=transcription
            )
        ]

    elif name == "update_recording_title":
        # Update recording title
        recording_id = arguments.get("recording_id")
        new_title = arguments.get("new_title")

        if not recording_id:
            return [
                TextContent(
                    type="text",
                    text=json.dumps({"error": "recording_id is required"})
                )
            ]

        if not new_title:
            return [
                TextContent(
                    type="text",
                    text=json.dumps({"error": "new_title is required"})
                )
            ]

        # Update the title using recording manager
        success = recording_manager.update_recording_title(recording_id, new_title)

        if success:
            return [
                TextContent(
                    type="text",
                    text=json.dumps({
                        "success": True,
                        "message": f"Successfully updated title for recording '{recording_id}' to '{new_title}'"
                    })
                )
            ]
        else:
            return [
                TextContent(
                    type="text",
                    text=json.dumps({"error": f"Recording with id '{recording_id}' not found"})
                )
            ]

    else:
        return [
            TextContent(
                type="text",
                text=json.dumps({"error": f"Unknown tool: {name}"})
            )
        ]


async def main():
    """Run the MCP server"""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="whisper-recordings-server",
                server_version="1.0.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                )
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
