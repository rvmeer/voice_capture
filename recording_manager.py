"""
Recording Manager Module
Manages recording metadata and storage with subfolder structure
"""

import json
import wave
from datetime import datetime, timedelta
from pathlib import Path
from logging_config import get_logger

logger = get_logger(__name__)


def seconds_to_iso_duration(seconds):
    """Convert seconds to ISO 8601 duration format (e.g., PT1M30S)"""
    if seconds == 0:
        return "PT0S"

    td = timedelta(seconds=int(seconds))
    hours = td.seconds // 3600
    minutes = (td.seconds % 3600) // 60
    secs = td.seconds % 60

    parts = []
    if td.days > 0:
        parts.append(f"{td.days}D")

    time_parts = []
    if hours > 0:
        time_parts.append(f"{hours}H")
    if minutes > 0:
        time_parts.append(f"{minutes}M")
    if secs > 0 or len(time_parts) == 0:
        time_parts.append(f"{secs}S")

    if time_parts:
        parts.append("T" + "".join(time_parts))

    return "P" + "".join(parts) if parts else "PT0S"


def iso_duration_to_seconds(iso_duration):
    """Convert ISO 8601 duration format to seconds"""
    if not iso_duration or iso_duration == "PT0S":
        return 0

    # Simple parser for PT format (hours, minutes, seconds)
    import re
    pattern = r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?'
    match = re.match(pattern, iso_duration)

    if not match:
        return 0

    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)

    return hours * 3600 + minutes * 60 + seconds


class RecordingManager:
    """Manages recording metadata and storage"""

    def __init__(self, recordings_dir=None):
        # Use Documents/VoiceCapture if no directory specified
        if recordings_dir is None:
            self.recordings_dir = Path.home() / "Documents" / "VoiceCapture"
        else:
            self.recordings_dir = Path(recordings_dir)

        self.recordings = []
        self.load_recordings()

    def load_recordings(self):
        """Load recordings from individual JSON files in subfolders"""
        self.recordings = []

        try:
            # Create recordings directory if it doesn't exist
            self.recordings_dir.mkdir(exist_ok=True)

            # Find all recording_* directories
            recording_dirs = sorted(
                [d for d in self.recordings_dir.iterdir() if d.is_dir() and d.name.startswith('recording_')],
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
                            self.recordings.append(recording)
                    except Exception as e:
                        logger.error(f"Error loading recording from {json_file}: {e}", exc_info=True)

            logger.debug(f"Loaded {len(self.recordings)} recordings from subfolders")

        except Exception as e:
            logger.error(f"Error loading recordings: {e}", exc_info=True)
            self.recordings = []

    def save_recording(self, recording):
        """Save a single recording to its JSON file"""
        try:
            timestamp = recording['id']
            rec_dir = self.recordings_dir / f"recording_{timestamp}"
            rec_dir.mkdir(parents=True, exist_ok=True)

            json_file = rec_dir / f"recording_{timestamp}.json"
            with open(json_file, 'w', encoding='utf-8') as f:
                json.dump(recording, f, indent=2, ensure_ascii=False)

            logger.debug(f"Saved recording to {json_file}")
        except Exception as e:
            logger.error(f"Error saving recording: {e}", exc_info=True)

    def add_recording(self, audio_file, timestamp, name=None, transcription="", summary="", duration=None, model="",
                      segment_duration=30, overlap_duration=15):
        """Add a new recording with all settings"""
        recording = {
            "id": timestamp,
            "audio_file": audio_file,
            "name": name or f"Opname {timestamp}",
            "date": datetime.strptime(timestamp, "%Y%m%d_%H%M%S").strftime("%Y-%m-%d %H:%M:%S"),
            "transcription": transcription,
            "summary": summary,
            "model": model,  # Whisper model used for transcription
            "segment_duration": segment_duration,  # Segment length in seconds
            "overlap_duration": overlap_duration,  # Overlap length in seconds
        }

        # Only add duration if it's provided (not None)
        if duration is not None:
            recording["duration"] = seconds_to_iso_duration(duration)  # Duration in ISO 8601 format

        self.recordings.insert(0, recording)  # Add to beginning
        self.save_recording(recording)
        return recording

    def get_audio_duration(self, audio_file):
        """Get duration of audio file in seconds"""
        try:
            with wave.open(audio_file, 'rb') as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                duration = frames / float(rate)
                return int(duration)
        except Exception as e:
            logger.error(f"Error getting audio duration: {e}", exc_info=True)
            return 0

    def update_recording(self, recording_id, **kwargs):
        """Update recording data"""
        for rec in self.recordings:
            if rec["id"] == recording_id:
                # Convert duration to ISO format if it's provided as seconds
                if 'duration' in kwargs and isinstance(kwargs['duration'], (int, float)):
                    kwargs['duration'] = seconds_to_iso_duration(kwargs['duration'])
                rec.update(kwargs)
                self.save_recording(rec)
                break

    def get_recording(self, recording_id):
        """Get recording by ID"""
        for rec in self.recordings:
            if rec["id"] == recording_id:
                return rec
        return None

    def update_recording_title(self, recording_id, new_title):
        """Update the title/name of a recording"""
        for rec in self.recordings:
            if rec["id"] == recording_id:
                rec["name"] = new_title
                self.save_recording(rec)
                return True
        return False
