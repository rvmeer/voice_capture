"""
Recording Manager Module
Manages recording metadata and storage
"""

import json
import wave
from datetime import datetime
from pathlib import Path


class RecordingManager:
    """Manages recording metadata and storage"""

    def __init__(self, data_file="recordings/recordings.json"):
        self.data_file = data_file
        self.recordings = []
        self.load_recordings()

    def load_recordings(self):
        """Load recordings from JSON file"""
        try:
            if Path(self.data_file).exists():
                with open(self.data_file, 'r', encoding='utf-8') as f:
                    self.recordings = json.load(f)

                # Migrate old recordings to add missing fields
                needs_save = False
                default_prompt = """Maak een samenvatting wat hier besproken is. Geef ook de actiepunten.
Er zijn meerdere personen aan het woord geweest maar dat is niet aangegeven in de tekst,
probeer dat er zelf uit te halen. Geef het weer in de volgende vorm, waarbij je <blabla> vervangt door
de juiste informatie. Zet deelnemers in alfabetische volgorde, actiepunten in volgorde van hoe ze aan bod kwamen in
de tekst. Soms wordt er over personen gesproken maar zijn ze niet aanwezig in de meeting,
zet ze dan ook niet bij de deelnemers.

--- Deelnemers ---
- <persoon 1> - <Mening van die persoon in 1 zin>
- <persoon 2> - <Mening van die persoon in 1 zin>
- etc...

--- Samenvatting ---
<korte samenvatting in 3 zinnen>

--- Actiepunten ---
- <actiepunt 1> -- <verantwoordelijke persoon>
- <actiepunt 2> -- <verantwoordelijke persoon>
- etc...

Hier volgt de tekst:"""

                for rec in self.recordings:
                    changed = False

                    # Add missing summary_prompt
                    if 'summary_prompt' not in rec:
                        rec['summary_prompt'] = default_prompt
                        changed = True

                    # Add missing AI provider settings
                    if 'ai_provider' not in rec:
                        rec['ai_provider'] = 'azure'
                        changed = True

                    if 'segment_duration' not in rec:
                        rec['segment_duration'] = 30
                        changed = True

                    if 'overlap_duration' not in rec:
                        rec['overlap_duration'] = 15
                        changed = True

                    if 'ollama_url' not in rec:
                        rec['ollama_url'] = 'http://localhost:11434/v1'
                        changed = True

                    if 'ollama_model' not in rec:
                        rec['ollama_model'] = ''
                        changed = True

                    if changed:
                        needs_save = True

                # Save if we migrated any recordings
                if needs_save:
                    print(f"DEBUG: Migrated {sum(1 for rec in self.recordings if 'summary_prompt' in rec)} recordings with missing fields")
                    self.save_recordings()

        except Exception as e:
            print(f"Error loading recordings: {e}")
            self.recordings = []

    def save_recordings(self):
        """Save recordings to JSON file"""
        try:
            Path("recordings").mkdir(exist_ok=True)
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump(self.recordings, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving recordings: {e}")

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
        self.save_recordings()
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
                self.save_recordings()
                break

    def get_recording(self, recording_id):
        """Get recording by ID"""
        for rec in self.recordings:
            if rec["id"] == recording_id:
                return rec
        return None
