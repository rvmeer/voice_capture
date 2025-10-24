"""
Audio Recording Module
Handles audio recording functionality with segmented recording support
"""

import wave
import threading
from datetime import datetime
from pathlib import Path
import pyaudio
import os


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

        # For 10-second segments with 5-second overlap
        self.segment_duration = 10  # seconds
        self.overlap_duration = 5  # seconds
        self.segment_callback = None  # Callback function for segment ready
        self.segment_counter = 0
        self.recording_timestamp = None
        self.all_frames = []  # Keep all frames for complete recording

        # Audio input device selection
        self.input_device_index = None  # None = default device

        # Set base directory for recordings - use Documents folder
        self.base_recordings_dir = Path.home() / "Documents" / "VoiceCapture"
        self.base_recordings_dir.mkdir(parents=True, exist_ok=True)
        print(f"DEBUG: Recordings will be saved to: {self.base_recordings_dir}")

    def get_audio_devices(self):
        """Get list of available audio input devices"""
        devices = []
        info = self.audio.get_host_api_info_by_index(0)
        num_devices = info.get('deviceCount')

        for i in range(num_devices):
            device_info = self.audio.get_device_info_by_host_api_device_index(0, i)
            # Only include input devices (max_input_channels > 0)
            if device_info.get('maxInputChannels') > 0:
                devices.append({
                    'index': i,
                    'name': device_info.get('name'),
                    'max_input_channels': device_info.get('maxInputChannels'),
                    'default_sample_rate': device_info.get('defaultSampleRate')
                })

        return devices

    def set_input_device(self, device_index):
        """Set the input device for recording"""
        self.input_device_index = device_index
        print(f"DEBUG: Input device set to index {device_index}")

    def start_recording(self, segment_callback=None):
        """Start recording audio from microphone"""
        self.frames = []
        self.all_frames = []  # Reset complete recording
        self.is_recording = True
        self.segment_callback = segment_callback
        self.segment_counter = 0
        self.recording_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Open stream with selected input device
        stream_params = {
            'format': self.FORMAT,
            'channels': self.CHANNELS,
            'rate': self.RATE,
            'input': True,
            'frames_per_buffer': self.CHUNK
        }

        # Add input_device_index if one is selected
        if self.input_device_index is not None:
            stream_params['input_device_index'] = self.input_device_index
            print(f"DEBUG: Opening stream with device index {self.input_device_index}")

        self.stream = self.audio.open(**stream_params)

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
            # Create segments directory inside recording folder
            rec_dir = self.base_recordings_dir / f"recording_{self.recording_timestamp}"
            segments_dir = rec_dir / "segments"
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

        # Create recording directory structure
        rec_dir = self.base_recordings_dir / f"recording_{timestamp}"
        rec_dir.mkdir(parents=True, exist_ok=True)

        # Save the complete recording in the recording folder
        filename = rec_dir / f"recording_{timestamp}.wav"

        # Save the complete recording using all_frames
        try:
            wf = wave.open(str(filename), 'wb')
            wf.setnchannels(self.CHANNELS)
            wf.setsampwidth(self.audio.get_sample_size(self.FORMAT))
            wf.setframerate(self.RATE)
            wf.writeframes(b''.join(self.all_frames))  # Use all_frames for complete recording
            wf.close()
            print(f"DEBUG: Saved complete recording with {len(self.all_frames)} frames to {filename}")
        except Exception as e:
            print(f"Error saving recording: {e}")

        return str(filename), timestamp

    def cleanup(self):
        """Clean up audio resources"""
        if self.stream:
            self.stream.close()
        self.audio.terminate()
