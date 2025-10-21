"""
Audio Recording Module
Handles audio recording functionality with segmented recording support
"""

import wave
import threading
from datetime import datetime
from pathlib import Path
import pyaudio


class AudioRecorder:
    """Handles audio recording functionality"""

    def __init__(self):
        self.CHUNK = 1024
        self.FORMAT = pyaudio.paInt16
        self.CHANNELS = 1
        self.RATE = 16000
        self.frames = []
        self.is_recording = False
        self.audio = pyaudio.PyAudio()
        self.stream = None

        # For 30-second segments with 15-second overlap
        self.segment_duration = 30  # seconds
        self.overlap_duration = 15  # seconds
        self.segment_callback = None  # Callback function for segment ready
        self.segment_counter = 0
        self.recording_timestamp = None
        self.all_frames = []  # Keep all frames for complete recording

    def start_recording(self, segment_callback=None):
        """Start recording audio from microphone"""
        self.frames = []
        self.all_frames = []  # Reset complete recording
        self.is_recording = True
        self.segment_callback = segment_callback
        self.segment_counter = 0
        self.recording_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        self.stream = self.audio.open(
            format=self.FORMAT,
            channels=self.CHANNELS,
            rate=self.RATE,
            input=True,
            frames_per_buffer=self.CHUNK
        )

        def record():
            frames_per_segment = int(self.RATE * self.segment_duration / self.CHUNK)
            frames_for_overlap = int(self.RATE * self.overlap_duration / self.CHUNK)

            while self.is_recording:
                try:
                    data = self.stream.read(self.CHUNK, exception_on_overflow=False)
                    self.frames.append(data)
                    self.all_frames.append(data)  # Also store in complete recording

                    # Check if we have 30 seconds of audio
                    if len(self.frames) >= frames_per_segment:
                        # Save 30-second segment
                        segment_frames = self.frames[:frames_per_segment]
                        self.save_segment(segment_frames, self.segment_counter)

                        # Keep only last 15 seconds for overlap in segment buffer
                        self.frames = self.frames[frames_per_segment - frames_for_overlap:]
                        self.segment_counter += 1

                except Exception as e:
                    print(f"Recording error: {e}")
                    break

        self.record_thread = threading.Thread(target=record, daemon=True)
        self.record_thread.start()

    def save_segment(self, frames, segment_num):
        """Save a 30-second segment to file"""
        try:
            # Create segments directory
            segments_dir = Path(f"recordings/segments_{self.recording_timestamp}")
            segments_dir.mkdir(parents=True, exist_ok=True)

            # Save segment file
            segment_filename = segments_dir / f"segment_{segment_num:03d}.wav"
            wf = wave.open(str(segment_filename), 'wb')
            wf.setnchannels(self.CHANNELS)
            wf.setsampwidth(self.audio.get_sample_size(self.FORMAT))
            wf.setframerate(self.RATE)
            wf.writeframes(b''.join(frames))
            wf.close()

            print(f"DEBUG: Saved segment {segment_num} to {segment_filename}")

            # Call callback if provided
            if self.segment_callback:
                self.segment_callback(str(segment_filename), segment_num)

        except Exception as e:
            print(f"Error saving segment: {e}")

    def stop_recording(self):
        """Stop recording and return the audio file path"""
        self.is_recording = False

        # Wait for recording thread to finish
        if hasattr(self, 'record_thread') and self.record_thread.is_alive():
            self.record_thread.join(timeout=1.0)

        # Safely close stream
        try:
            if self.stream:
                self.stream.stop_stream()
                self.stream.close()
                self.stream = None
        except Exception as e:
            print(f"Error closing stream: {e}")

        # Use the recording timestamp from start_recording
        timestamp = self.recording_timestamp if self.recording_timestamp else datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"recordings/recording_{timestamp}.wav"

        # Create recordings directory if it doesn't exist
        Path("recordings").mkdir(exist_ok=True)

        # Save the complete recording using all_frames
        try:
            wf = wave.open(filename, 'wb')
            wf.setnchannels(self.CHANNELS)
            wf.setsampwidth(self.audio.get_sample_size(self.FORMAT))
            wf.setframerate(self.RATE)
            wf.writeframes(b''.join(self.all_frames))  # Use all_frames for complete recording
            wf.close()
            print(f"DEBUG: Saved complete recording with {len(self.all_frames)} frames to {filename}")
        except Exception as e:
            print(f"Error saving recording: {e}")

        return filename, timestamp

    def cleanup(self):
        """Clean up audio resources"""
        if self.stream:
            self.stream.close()
        self.audio.terminate()
