"""
Tray Icon Actions Module
Contains business logic for tray menu actions (no Qt/GUI code)
"""

from datetime import datetime
from logging_config import get_logger

logger = get_logger(__name__)


class TrayActions:
    """Handler for tray icon action business logic (no Qt/GUI code)"""

    def __init__(self, voice_capture):
        """
        Initialize tray actions handler

        Args:
            voice_capture: The VoiceCapture instance (main application)
        """
        self.app = voice_capture

    def toggle_recording(self):
        """Toggle recording - business logic only"""
        if not self.app.is_recording:
            self.start_recording()
        else:
            self.stop_recording()

    def start_recording(self):
        """Start recording - business logic only"""
        logger.info("Starting recording from tray")
        self.app.start_recording()

    def stop_recording(self):
        """Stop recording - business logic only"""
        logger.info("Stopping recording from tray")

        try:
            # Stop the recorder
            self.app.current_audio_file, self.app.current_recording_id = self.app.recorder.stop_recording()

            # Auto-generate name based on timestamp
            recording_name = f"Opname {datetime.now().strftime('%Y-%m-%d %H:%M')}"

            # Store the recording name for later use
            self.app.pending_recording_name = recording_name

            # Wait for all segments to be transcribed, then finalize
            logger.info(f"Recording stopped (tray mode), waiting for all segments to be transcribed...")
            self.app.check_and_finalize_recording()

        except Exception as e:
            logger.error(f"Error stopping recording: {e}", exc_info=True)
            # Reset state even on error
            self.app.is_recording = False
            raise  # Re-raise so UI can handle it

    def set_input_device(self, device_index):
        """Set input device - business logic only"""
        try:
            self.app.recorder.set_input_device(device_index)

            if device_index is None:
                logger.info("Set input device to default")
                return "Invoerapparaat ingesteld op standaard apparaat"
            else:
                # Get device name
                devices = self.app.recorder.get_audio_devices()
                device_name = next((d['name'] for d in devices if d['index'] == device_index), f"Device {device_index}")
                logger.info(f"Set input device to: {device_name}")
                return f"Invoerapparaat ingesteld op: {device_name}"

        except Exception as e:
            logger.error(f"Error setting input device: {e}", exc_info=True)
            raise  # Re-raise so UI can handle it

    def set_model(self, model_name):
        """Set Whisper model - business logic only"""
        try:
            logger.info(f"Setting model to {model_name} from tray")

            # Update selected model
            self.app.selected_model_name = model_name

            # Load model if not already loaded
            if model_name not in self.app.loaded_models:
                logger.info(f"Loading {model_name} model...")
                self.app.load_model_async(model_name)

            return f"Whisper model ingesteld op: {model_name}"

        except Exception as e:
            logger.error(f"Error setting model: {e}", exc_info=True)
            raise  # Re-raise so UI can handle it

    def get_retranscribe_recordings(self):
        """Get list of recordings that can be retranscribed - business logic only"""
        # Load all recordings
        self.app.recording_manager.load_recordings()
        all_recordings = self.app.recording_manager.recordings

        # Filter recordings to only include those with a WAV file
        recordings = []
        for recording in all_recordings:
            recording_id = recording.get('id', '')
            # Check if recording_<timestamp>.wav exists
            rec_dir = self.app.recording_manager.recordings_dir / f"recording_{recording_id}"
            audio_file = rec_dir / f"recording_{recording_id}.wav"
            if audio_file.exists():
                recordings.append(recording)

        return recordings

    def start_retranscription(self, recording_id):
        """Start retranscription - business logic only"""
        logger.info(f"Starting retranscription of recording {recording_id} with model {self.app.selected_model_name}")
        self.app.start_retranscription(recording_id)

    def quit_application(self):
        """Quit the application - business logic only"""
        logger.info("Quitting application...")

        try:
            # Stop recording if active
            if self.app.is_recording:
                logger.info("Stopping active recording...")
                try:
                    self.app.recorder.stop_recording()
                except Exception as e:
                    logger.error(f"Error stopping recording: {e}")

            # Stop timer
            if hasattr(self.app, 'timer') and self.app.timer.isActive():
                self.app.timer.stop()

            # Clean up recorder
            try:
                self.app.recorder.cleanup()
            except Exception as e:
                logger.error(f"Error during recorder cleanup: {e}")

        except Exception as e:
            logger.error(f"Error during quit: {e}", exc_info=True)
