"""
Recording Manager Module
Manages recording metadata and storage with subfolder structure
"""

import json
import wave
from datetime import datetime
from pathlib import Path


class RecordingManager:
    """Manages recording metadata and storage"""

    def __init__(self, recordings_dir="recordings"):
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
                        print(f"Error loading recording from {json_file}: {e}")

            print(f"DEBUG: Loaded {len(self.recordings)} recordings from subfolders")

        except Exception as e:
            print(f"Error loading recordings: {e}")
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

            print(f"DEBUG: Saved recording to {json_file}")
        except Exception as e:
            print(f"Error saving recording: {e}")

    def add_recording(self, audio_file, timestamp, name=None, transcription="", summary="", duration=0, model="",
                      ai_provider="azure", segment_duration=30, overlap_duration=15,
                      ollama_url="", ollama_model="", summary_prompt=""):
        """Add a new recording with all settings"""
        recording = {
            "id": timestamp,
            "audio_file": audio_file,
            "name": name or f"Opname {timestamp}",
            "date": datetime.strptime(timestamp, "%Y%m%d_%H%M%S").strftime("%Y-%m-%d %H:%M:%S"),
            "transcription": transcription,
            "summary": summary,
            "duration": duration,  # Duration in seconds
            "model": model,  # Whisper model used for transcription
            "ai_provider": ai_provider,  # "azure" or "ollama"
            "segment_duration": segment_duration,  # Segment length in seconds
            "overlap_duration": overlap_duration,  # Overlap length in seconds
            "ollama_url": ollama_url,  # Ollama server URL
            "ollama_model": ollama_model,  # Ollama model name
            "summary_prompt": summary_prompt  # Summary prompt text
        }
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
            print(f"Error getting audio duration: {e}")
            return 0

    def update_recording(self, recording_id, **kwargs):
        """Update recording data"""
        for rec in self.recordings:
            if rec["id"] == recording_id:
                rec.update(kwargs)
                self.save_recording(rec)
                break

    def get_recording(self, recording_id):
        """Get recording by ID"""
        for rec in self.recordings:
            if rec["id"] == recording_id:
                return rec
        return None
