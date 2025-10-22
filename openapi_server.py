#!/usr/bin/env python3
"""
OpenAPI Tool Server for Whisper Demo Recordings
Provides access to recordings, metadata, and transcriptions via OpenAPI/FastAPI
Compatible with Open-WebUI tool integration
"""

import json
from pathlib import Path
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn


# Initialize FastAPI app
app = FastAPI(
    title="Whisper Recordings API",
    description="API for accessing Whisper demo recordings, metadata, and transcriptions",
    version="1.0.0"
)

# Add CORS middleware for Open-WebUI
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Path to recordings directory
RECORDINGS_DIR = Path(__file__).parent / "recordings"


# Pydantic models for requests/responses
class RecordingSummary(BaseModel):
    id: str = Field(..., description="Recording ID (timestamp)")
    date: str = Field(..., description="Recording date and time")
    name: str = Field(..., description="Recording name")
    duration: str = Field(..., description="Recording duration in ISO 8601 format")


class RecordingDetail(BaseModel):
    id: str
    audio_file: str
    name: str
    date: str
    transcription: str
    summary: str
    duration: str
    model: str
    segment_duration: int
    overlap_duration: int


class TranscriptionResponse(BaseModel):
    recording_id: str
    transcription: str


class ErrorResponse(BaseModel):
    error: str


# Helper functions (same as MCP server)
def load_recordings() -> List[Dict[str, Any]]:
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
                    print(f"Error loading recording from {json_file}: {e}")

    except Exception as e:
        print(f"Error loading recordings: {e}")

    return recordings


def get_recording_by_id(recording_id: str) -> Optional[Dict[str, Any]]:
    """Get a specific recording by ID"""
    recordings = load_recordings()
    for rec in recordings:
        if rec.get("id") == recording_id:
            return rec
    return None


def get_transcription_text(recording_id: str) -> Optional[str]:
    """Get the transcription text for a recording"""
    rec_dir = RECORDINGS_DIR / f"recording_{recording_id}"
    transcription_file = rec_dir / f"transcription_{recording_id}.txt"

    if transcription_file.exists():
        try:
            with open(transcription_file, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            print(f"Error reading transcription file: {e}")
            return None

    # Fallback to JSON if TXT doesn't exist
    recording = get_recording_by_id(recording_id)
    if recording:
        return recording.get("transcription", "")

    return None


# API Endpoints
@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "name": "Whisper Recordings API",
        "version": "1.0.0",
        "description": "API for accessing Whisper demo recordings",
        "endpoints": {
            "GET /recordings": "List all recordings",
            "GET /recordings/{recording_id}": "Get specific recording metadata",
            "GET /recordings/{recording_id}/transcription": "Get recording transcription",
            "GET /openapi.json": "OpenAPI schema"
        }
    }


@app.get(
    "/recordings",
    response_model=List[RecordingSummary],
    summary="Get all recordings",
    description="Returns a list of all recordings with their basic metadata (id, date, name, duration)"
)
async def get_recordings():
    """Get a list of all recordings with their date and name"""
    recordings = load_recordings()
    result = []

    for rec in recordings:
        result.append({
            "id": rec.get("id"),
            "date": rec.get("date"),
            "name": rec.get("name"),
            "duration": rec.get("duration", "PT0S")
        })

    return result


@app.get(
    "/recordings/{recording_id}",
    response_model=RecordingDetail,
    summary="Get recording details",
    description="Returns the complete metadata for a specific recording including all settings and information"
)
async def get_recording(recording_id: str):
    """Get the complete JSON metadata for a specific recording by ID"""
    recording = get_recording_by_id(recording_id)

    if recording is None:
        raise HTTPException(
            status_code=404,
            detail=f"Recording with id '{recording_id}' not found"
        )

    return recording


@app.get(
    "/recordings/{recording_id}/transcription",
    response_model=TranscriptionResponse,
    summary="Get recording transcription",
    description="Returns the full transcription text for a specific recording"
)
async def get_transcription(recording_id: str):
    """Get the transcription text for a specific recording by ID"""
    transcription = get_transcription_text(recording_id)

    if transcription is None:
        raise HTTPException(
            status_code=404,
            detail=f"Transcription for recording '{recording_id}' not found"
        )

    return {
        "recording_id": recording_id,
        "transcription": transcription
    }


# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}


if __name__ == "__main__":
    # Run the server
    print("Starting Whisper Recordings OpenAPI Server...")
    print("API documentation available at: http://localhost:8000/docs")
    print("OpenAPI schema available at: http://localhost:8000/openapi.json")

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )
