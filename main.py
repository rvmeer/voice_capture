#!/usr/bin/env python3
"""
Voice Capture - Tray-Only Application
Clean implementation using composition pattern with tray_actions
"""

import sys
import signal
import threading
from datetime import datetime
from pathlib import Path

import whisper
import torch
from PyQt6.QtWidgets import (
    QApplication, QSystemTrayIcon, QMenu, QMessageBox
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QIcon, QPainter, QPixmap, QPen, QColor, QActionGroup

# Import custom modules
from audio_recorder import AudioRecorder
from recording_manager import RecordingManager
from logging_config import setup_logging, get_logger
from version import get_version_string
from transcription_utils import remove_overlap

# Setup logging
logger = get_logger(__name__)


def create_tray_icon(recording=False):
    """Create a tray icon - white open circle when idle, red solid circle when recording"""
    # Create a 22x22 pixmap (standard size for macOS menu bar icons)
    pixmap = QPixmap(22, 22)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    if recording:
        # White open circle outline
        pen = QPen(QColor(255, 255, 255))  # White
        pen.setWidth(2)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(2, 2, 18, 18)

        # Red solid circle inside
        painter.setBrush(QColor(244, 67, 54))  # Red color
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(6, 6, 10, 10)
    else:
        # White open circle outline when idle
        pen = QPen(QColor(255, 255, 255))  # White
        pen.setWidth(2)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(3, 3, 16, 16)

    painter.end()
    return QIcon(pixmap)


class VoiceCapture(QObject):
    """Voice Capture application - tray-only mode using composition"""

    # Define signals for thread-safe communication
    transcription_complete = pyqtSignal(dict)
    model_loaded = pyqtSignal(str, object)  # (model_name, model_object)
    segment_transcribed = pyqtSignal(str, int)  # Signal for incremental transcription updates (text, segment_num)

    def __init__(self):
        super().__init__()

        # Core components
        self.recorder = AudioRecorder()
        self.recording_manager = RecordingManager()

        # Get base recordings directory from recorder
        self.base_recordings_dir = self.recorder.base_recordings_dir

        # Model caching: store loaded models
        self.loaded_models = {}  # {model_name: model_object}
        self.selected_model_name = "medium"  # Default selected model

        # Recording state
        self.is_recording = False
        self.recording_time = 0
        self.current_audio_file = None
        self.current_recording_id = None

        # Connect signals to slots
        self.transcription_complete.connect(self.on_transcription_complete)
        self.model_loaded.connect(self.on_model_loaded)
        self.segment_transcribed.connect(self.on_segment_transcribed)

        # Track pending transcription
        self.pending_transcription = False

        # Track segments for incremental transcription
        self.segments_to_transcribe = []  # Queue of segments to transcribe
        self.transcribed_segments = []  # List of transcribed texts
        self.is_transcribing_segment = False  # Flag to track if currently transcribing

        # Track pending recording name (set when recording stops)
        self.pending_recording_name = None

        # Settings
        self.segment_duration = 10  # seconds
        self.overlap_duration = 5  # seconds

        # Timer for recording duration
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_timer)

        # Initialize tray icon
        self.init_tray_icon()

        # Load default model on startup
        QTimer.singleShot(500, lambda: self.load_model_async(self.selected_model_name))

    def init_tray_icon(self):
        """Initialize system tray icon"""
        # Create system tray icon
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(create_tray_icon(recording=False))

        # Create context menu for tray icon
        self.tray_menu = QMenu()

        # Add toggle recording action
        self.tray_toggle_action = self.tray_menu.addAction("Start Opname")
        self.tray_toggle_action.triggered.connect(self.tray_toggle_recording)

        self.tray_menu.addSeparator()

        # Add transcription model selection submenu
        model_menu = QMenu("Transcription Model", self.tray_menu)
        model_action_group = QActionGroup(model_menu)
        model_action_group.setExclusive(True)

        # Add model options
        self.tray_tiny_action = model_menu.addAction("Tiny (Snel, ~1GB)")
        self.tray_tiny_action.setCheckable(True)
        self.tray_tiny_action.triggered.connect(lambda: self.set_tray_model("tiny"))
        model_action_group.addAction(self.tray_tiny_action)

        self.tray_small_action = model_menu.addAction("Small (Goed, ~2GB)")
        self.tray_small_action.setCheckable(True)
        self.tray_small_action.triggered.connect(lambda: self.set_tray_model("small"))
        model_action_group.addAction(self.tray_small_action)

        self.tray_medium_action = model_menu.addAction("Medium (Beter, ~5GB)")
        self.tray_medium_action.setCheckable(True)
        self.tray_medium_action.triggered.connect(lambda: self.set_tray_model("medium"))
        model_action_group.addAction(self.tray_medium_action)

        self.tray_large_action = model_menu.addAction("Large (Best, ~10GB)")
        self.tray_large_action.setCheckable(True)
        self.tray_large_action.triggered.connect(lambda: self.set_tray_model("large"))
        model_action_group.addAction(self.tray_large_action)

        # Set initial selection based on current model
        if self.selected_model_name == "medium":
            self.tray_medium_action.setChecked(True)

        self.tray_menu.addMenu(model_menu)

        self.tray_menu.addSeparator()

        # Add input device selection submenu
        self.tray_input_menu = QMenu("Input Selection", self.tray_menu)
        self.tray_menu.addMenu(self.tray_input_menu)

        self.tray_menu.addSeparator()

        # Add retranscribe action
        retranscribe_action = self.tray_menu.addAction("Hertranscriberen")
        retranscribe_action.triggered.connect(self.show_retranscribe_dialog)

        self.tray_menu.addSeparator()

        # Add version info action
        version_action = self.tray_menu.addAction("Toon Versie")
        version_action.triggered.connect(self.show_version_info)

        self.tray_menu.addSeparator()

        # Add quit action
        quit_action = self.tray_menu.addAction("Afsluiten")
        quit_action.triggered.connect(self.quit_application)

        # Don't set context menu automatically - we'll handle it manually
        # This prevents the menu from showing on left click on macOS
        # self.tray_icon.setContextMenu(self.tray_menu)

        # Connect tray icon activation (click)
        self.tray_icon.activated.connect(self.on_tray_icon_activated)

        # Show tray icon
        self.tray_icon.show()
        self.tray_icon.setToolTip("Voice Capture (klik om op te nemen)")

        # Refresh input devices menu
        self.refresh_tray_input_devices()

    # Tray action methods - delegated from tray_actions via composition pattern

    def on_tray_icon_activated(self, reason):
        """Handle tray icon activation (click)"""
        from PyQt6.QtGui import QCursor

        if reason == QSystemTrayIcon.ActivationReason.Trigger:  # Left click
            self.tray_toggle_recording()
        elif reason == QSystemTrayIcon.ActivationReason.Context:  # Right click / Control+click on macOS
            # Show context menu at cursor position
            self.tray_menu.popup(QCursor.pos())

    def tray_toggle_recording(self):
        """Toggle recording from tray icon"""
        if not self.is_recording:
            self.tray_start_recording()
        else:
            self.tray_stop_recording()

    def tray_start_recording(self):
        """Start recording from tray"""
        logger.info("Starting recording from tray")

        # Start recording first
        self.start_recording()

        # Update tray icon to recording state AFTER starting
        self.tray_icon.setIcon(create_tray_icon(recording=True))
        self.tray_icon.setToolTip("Opname bezig... (klik om te stoppen)")

    def tray_stop_recording(self):
        """Stop recording from tray"""
        logger.info("Stopping recording from tray")

        def save_and_continue():
            try:
                # Stop the recorder
                self.current_audio_file, self.current_recording_id = self.recorder.stop_recording()

                # Update tray icon to idle state immediately
                # (is_recording will be set to False in finalize_recording)
                self.tray_icon.setIcon(create_tray_icon(recording=False))
                self.tray_icon.setToolTip("Voice Capture (klik om op te nemen)")

                # Auto-generate name based on timestamp
                recording_name = f"Opname {datetime.now().strftime('%Y-%m-%d %H:%M')}"

                # Store the recording name for later use
                self.pending_recording_name = recording_name

                # Wait for all segments to be transcribed, then finalize
                logger.info(f"Recording stopped (tray mode), waiting for all segments to be transcribed...")
                self.check_and_finalize_recording()

            except Exception as e:
                logger.error(f"Error in save_and_continue: {e}", exc_info=True)
                # Make sure to reset state even on error
                self.is_recording = False
                self.tray_icon.setIcon(create_tray_icon(recording=False))
                self.tray_icon.setToolTip("Voice Capture (klik om op te nemen)")
                QMessageBox.critical(None, "Fout", f"Fout bij opslaan: {str(e)}")

        # Stop recording and save
        save_and_continue()

    def refresh_tray_input_devices(self):
        """Refresh the audio input device list in tray menu"""
        try:
            # Get list of audio input devices
            devices = self.recorder.get_audio_devices()

            # Clear existing input device actions
            if hasattr(self, 'tray_input_menu') and self.tray_input_menu:
                self.tray_input_menu.clear()

                # Create action group for exclusive selection
                from PyQt6.QtGui import QActionGroup
                input_device_group = QActionGroup(self.tray_input_menu)
                input_device_group.setExclusive(True)

                # Add default device option
                default_action = self.tray_input_menu.addAction("Standaard apparaat")
                default_action.setCheckable(True)
                default_action.setChecked(self.recorder.input_device_index is None)
                input_device_group.addAction(default_action)
                default_action.triggered.connect(lambda checked, idx=None: self.set_tray_input_device(idx))

                # Add separator
                self.tray_input_menu.addSeparator()

                # Add each device
                for device in devices:
                    device_name = device['name']
                    device_index = device['index']

                    action = self.tray_input_menu.addAction(device_name)
                    action.setCheckable(True)
                    action.setChecked(self.recorder.input_device_index == device_index)
                    input_device_group.addAction(action)
                    action.triggered.connect(lambda checked, idx=device_index: self.set_tray_input_device(idx))

                logger.debug(f"Refreshed tray input devices menu with {len(devices)} devices")

        except Exception as e:
            logger.error(f"Error refreshing tray input devices: {e}", exc_info=True)

    def set_tray_input_device(self, device_index):
        """Set input device from tray menu"""
        try:
            self.recorder.set_input_device(device_index)

            if device_index is None:
                logger.info("Set input device to default")
                if hasattr(self, 'tray_icon'):
                    self.tray_icon.showMessage(
                        "Invoerapparaat Gewijzigd",
                        "Invoerapparaat ingesteld op standaard apparaat",
                        QSystemTrayIcon.MessageIcon.Information,
                        2000
                    )
            else:
                # Get device name
                devices = self.recorder.get_audio_devices()
                device_name = next((d['name'] for d in devices if d['index'] == device_index), f"Device {device_index}")

                logger.info(f"Set input device to: {device_name}")
                if hasattr(self, 'tray_icon'):
                    self.tray_icon.showMessage(
                        "Invoerapparaat Gewijzigd",
                        f"Invoerapparaat ingesteld op: {device_name}",
                        QSystemTrayIcon.MessageIcon.Information,
                        2000
                    )

        except Exception as e:
            logger.error(f"Error setting tray input device: {e}", exc_info=True)
            QMessageBox.warning(None, "Fout", f"Kon invoerapparaat niet instellen: {str(e)}")

    def set_tray_model(self, model_name):
        """Set Whisper model from tray menu"""
        try:
            logger.info(f"Setting model to {model_name} from tray")

            # Update selected model
            self.selected_model_name = model_name

            # Update tray menu checkmarks
            if hasattr(self, 'tray_tiny_action'):
                self.tray_tiny_action.setChecked(model_name == "tiny")
            if hasattr(self, 'tray_small_action'):
                self.tray_small_action.setChecked(model_name == "small")
            if hasattr(self, 'tray_medium_action'):
                self.tray_medium_action.setChecked(model_name == "medium")
            if hasattr(self, 'tray_large_action'):
                self.tray_large_action.setChecked(model_name == "large")

            # Show notification
            if hasattr(self, 'tray_icon'):
                self.tray_icon.showMessage(
                    "Model Gewijzigd",
                    f"Whisper model ingesteld op: {model_name}",
                    QSystemTrayIcon.MessageIcon.Information,
                    2000
                )

            # Load model if not already loaded
            if model_name not in self.loaded_models:
                logger.info(f"Loading {model_name} model...")
                self.load_model_async(model_name)

        except Exception as e:
            logger.error(f"Error setting tray model: {e}", exc_info=True)
            QMessageBox.warning(None, "Fout", f"Kon model niet instellen: {str(e)}")

    def show_version_info(self):
        """Show version information"""
        from version import get_version_string
        version = get_version_string()

        QMessageBox.information(
            None,
            "Versie Informatie",
            f"Voice Capture\\n\\nVersie: {version}"
        )

    def show_retranscribe_dialog(self):
        """Show dialog to select a recording to retranscribe"""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QListWidget, QPushButton, QLabel, QHBoxLayout, QListWidgetItem

        # Check if currently recording
        if self.is_recording:
            QMessageBox.warning(None, "Fout", "Stop eerst de huidige opname voordat je hertranscribeert.")
            return

        # Check if currently transcribing
        if self.is_transcribing_segment:
            QMessageBox.warning(None, "Fout", "Wacht tot de huidige transcriptie is voltooid.")
            return

        # Load all recordings
        self.recording_manager.load_recordings()
        all_recordings = self.recording_manager.recordings

        # Filter recordings to only include those with a WAV file
        recordings = []
        for recording in all_recordings:
            recording_id = recording.get('id', '')
            # Check if recording_<timestamp>.wav exists
            rec_dir = self.recording_manager.recordings_dir / f"recording_{recording_id}"
            audio_file = rec_dir / f"recording_{recording_id}.wav"
            if audio_file.exists():
                recordings.append(recording)

        if not recordings:
            QMessageBox.information(None, "Geen Opnames", "Er zijn geen opnames met audio bestanden gevonden om te hertranscriberen.")
            return

        # Create dialog
        dialog = QDialog()
        dialog.setWindowTitle("Selecteer Opname voor Hertranscriptie")
        dialog.setMinimumWidth(500)
        dialog.setMinimumHeight(400)

        layout = QVBoxLayout()

        # Add instruction label
        instruction_label = QLabel(f"Selecteer een opname om te hertranscriberen met het <b>{self.selected_model_name}</b> model:")
        layout.addWidget(instruction_label)

        # Create list widget
        list_widget = QListWidget()

        # Populate with recordings that have WAV files
        for recording in recordings:
            recording_id = recording.get('id', '')
            recording_name = recording.get('name', recording_id)
            recording_date = recording.get('date', '')
            duration = recording.get('duration', '')
            current_model = recording.get('model', '')

            # Format display text
            display_text = f"{recording_name} - {recording_date}"
            if duration:
                display_text += f" ({duration})"
            if current_model:
                display_text += f" [model: {current_model}]"

            item = QListWidgetItem(display_text)
            item.setData(Qt.ItemDataRole.UserRole, recording_id)
            list_widget.addItem(item)

        layout.addWidget(list_widget)

        # Add buttons
        button_layout = QHBoxLayout()

        ok_button = QPushButton("Hertranscriberen")
        cancel_button = QPushButton("Annuleren")

        button_layout.addWidget(ok_button)
        button_layout.addWidget(cancel_button)

        layout.addLayout(button_layout)

        dialog.setLayout(layout)

        # Connect buttons
        def on_ok():
            selected_items = list_widget.selectedItems()
            if not selected_items:
                QMessageBox.warning(dialog, "Geen Selectie", "Selecteer een opname om te hertranscriberen.")
                return

            recording_id = selected_items[0].data(Qt.ItemDataRole.UserRole)
            dialog.accept()

            # Start retranscription
            self.start_retranscription(recording_id)

        def on_cancel():
            dialog.reject()

        ok_button.clicked.connect(on_ok)
        cancel_button.clicked.connect(on_cancel)

        # Show dialog
        dialog.exec()

    def quit_application(self):
        """Quit the application gracefully"""
        logger.info("Quitting application...")

        try:
            # Stop recording if active
            if self.is_recording:
                logger.info("Stopping active recording...")
                try:
                    self.recorder.stop_recording()
                except Exception as e:
                    logger.error(f"Error stopping recording: {e}")

            # Stop timer
            if hasattr(self, 'timer') and self.timer.isActive():
                self.timer.stop()

            # Clean up recorder
            try:
                self.recorder.cleanup()
            except Exception as e:
                logger.error(f"Error during recorder cleanup: {e}")

            # Hide tray icon
            if hasattr(self, 'tray_icon'):
                self.tray_icon.hide()

        except Exception as e:
            logger.error(f"Error during quit: {e}", exc_info=True)
        finally:
            # Quit application
            QApplication.quit()

    # Core recording methods

    def start_recording(self):
        """Start recording"""
        logger.info("Starting recording...")
        self.is_recording = True
        self.recording_time = 0

        # Clear previous segments
        self.segments_to_transcribe = []
        self.transcribed_segments = []

        # Set segment settings on recorder
        self.recorder.segment_duration = self.segment_duration
        self.recorder.overlap_duration = self.overlap_duration

        # Start recording with segment callback
        self.recorder.start_recording(segment_callback=self.on_segment_ready)
        self.current_recording_id = self.recorder.recording_timestamp

        # Add recording to manager (without duration initially)
        recording_name = f"Opname {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        self.current_audio_file = str(self.base_recordings_dir / f"recording_{self.current_recording_id}" / f"recording_{self.current_recording_id}.wav")

        self.recording_manager.add_recording(
            audio_file=self.current_audio_file,
            timestamp=self.current_recording_id,
            name=recording_name,
            duration=None,  # Don't set duration yet
            model=self.selected_model_name,
            segment_duration=self.segment_duration,
            overlap_duration=self.overlap_duration
        )

        # Start timer
        self.timer.start(1000)  # Update every second

        logger.info(f"Recording started with ID: {self.current_recording_id}")

    def update_timer(self):
        """Update recording timer"""
        self.recording_time += 1

    def on_segment_ready(self, segment_file, segment_num):
        """Called when a new segment is ready"""
        logger.debug(f"Segment {segment_num} ready: {segment_file}")
        self.segments_to_transcribe.append((segment_file, segment_num))

        # Start transcribing if not already doing so
        if not self.is_transcribing_segment:
            self.transcribe_next_segment()

    def transcribe_next_segment(self):
        """Transcribe the next segment in queue"""
        if not self.segments_to_transcribe:
            self.is_transcribing_segment = False
            return

        # Get model
        model_name = self.selected_model_name
        if model_name not in self.loaded_models:
            # Model not loaded yet, wait
            logger.warning(f"Model {model_name} not loaded yet, waiting...")
            self.is_transcribing_segment = False
            return

        model = self.loaded_models[model_name]
        self.is_transcribing_segment = True

        # Get next segment
        segment_file, segment_num = self.segments_to_transcribe.pop(0)

        logger.info(f"Transcribing segment {segment_num}...")

        # Start transcription in background thread
        thread = threading.Thread(
            target=self.transcribe_segment_thread,
            args=(segment_file, segment_num, model)
        )
        thread.daemon = True
        thread.start()

    def transcribe_segment_thread(self, audio_file, segment_num, model):
        """Transcribe a segment in a background thread"""
        try:
            # Check if audio file has sufficient duration
            # Whisper fails with tensor errors on very short or empty audio
            import wave
            try:
                with wave.open(audio_file, 'rb') as wf:
                    frames = wf.getnframes()
                    rate = wf.getframerate()
                    duration = frames / float(rate)

                    # Minimum 0.1 seconds of audio required
                    if duration < 0.1:
                        logger.warning(f"Segment {segment_num} too short ({duration:.2f}s), skipping transcription")
                        # Create empty transcription file
                        rec_dir = self.base_recordings_dir / f"recording_{self.current_recording_id}"
                        segments_dir = rec_dir / "segments"
                        transcription_file = segments_dir / f"transcription_{segment_num}.txt"
                        with open(transcription_file, 'w', encoding='utf-8') as f:
                            f.write("")
                        self.segment_transcribed.emit("", segment_num)
                        return
            except Exception as audio_check_error:
                logger.error(f"Error checking audio duration for segment {segment_num}: {audio_check_error}")
                # Create empty transcription file on error
                rec_dir = self.base_recordings_dir / f"recording_{self.current_recording_id}"
                segments_dir = rec_dir / "segments"
                transcription_file = segments_dir / f"transcription_{segment_num}.txt"
                with open(transcription_file, 'w', encoding='utf-8') as f:
                    f.write("")
                self.segment_transcribed.emit("", segment_num)
                return

            # Transcribe with fp16=False to avoid NaN issues on MPS
            result = model.transcribe(
                audio_file,
                language="nl",
                task="transcribe",
                fp16=False,
                verbose=False  # Suppress whisper output
            )
            text = result["text"].strip()

            # Save transcription to file
            rec_dir = self.base_recordings_dir / f"recording_{self.current_recording_id}"
            segments_dir = rec_dir / "segments"
            transcription_file = segments_dir / f"transcription_{segment_num}.txt"

            with open(transcription_file, 'w', encoding='utf-8') as f:
                f.write(text)

            logger.info(f"Segment {segment_num} transcribed: {len(text)} chars")

            # Emit signal
            self.segment_transcribed.emit(text, segment_num)

        except Exception as e:
            logger.error(f"Error transcribing segment {segment_num}: {e}", exc_info=True)
        finally:
            self.is_transcribing_segment = False
            # Continue with next segment
            self.transcribe_next_segment()

    def on_segment_transcribed(self, text, segment_num):
        """Handle segment transcription complete"""
        logger.debug(f"Segment {segment_num} transcription complete")

    def check_and_finalize_recording(self):
        """Check if all segments are transcribed and finalize recording"""
        if not self.current_recording_id:
            return

        rec_dir = self.base_recordings_dir / f"recording_{self.current_recording_id}"
        segments_dir = rec_dir / "segments"

        if not segments_dir.exists():
            logger.warning("Segments directory does not exist - recording was too short, finalizing with empty transcription")
            # Recording was too short to create any segments
            # Finalize with empty transcription
            self.finalize_recording_no_segments()
            return

        # Find all segment WAV files
        segment_files = sorted(segments_dir.glob("segment_*.wav"))

        if len(segment_files) == 0:
            logger.warning("No segment files found - recording was too short, finalizing with empty transcription")
            # No segments created - recording was too short
            self.finalize_recording_no_segments()
            return

        # Check if all segments have transcriptions
        all_transcribed = True
        for segment_file in segment_files:
            segment_num = int(segment_file.stem.split('_')[1])
            transcription_file = segments_dir / f"transcription_{segment_num}.txt"
            if not transcription_file.exists():
                all_transcribed = False
                break

        if all_transcribed and not self.is_transcribing_segment:
            # All segments transcribed - finalize
            logger.info("All segments transcribed - finalizing recording")
            self.finalize_recording()
        else:
            # Check again in 1 second
            QTimer.singleShot(1000, self.check_and_finalize_recording)

    def finalize_recording(self):
        """Finalize recording after all segments are transcribed"""
        if not self.current_recording_id:
            return

        logger.info(f"Finalizing recording {self.current_recording_id}")

        rec_dir = self.base_recordings_dir / f"recording_{self.current_recording_id}"
        segments_dir = rec_dir / "segments"
        audio_file = rec_dir / f"recording_{self.current_recording_id}.wav"

        # Get audio duration
        duration = self.recording_manager.get_audio_duration(str(audio_file))

        # Combine all transcriptions with overlap removal
        transcription_files = sorted(segments_dir.glob("transcription_*.txt"))
        combined_texts = []

        for trans_file in transcription_files:
            try:
                with open(trans_file, 'r', encoding='utf-8') as f:
                    text = f.read().strip()
                    if text:
                        if len(combined_texts) == 0:
                            # First segment - add as-is
                            combined_texts.append(text)
                        else:
                            # Remove overlap with previous segment
                            previous_text = combined_texts[-1]
                            deduplicated_text = remove_overlap(previous_text, text)
                            if deduplicated_text.strip():
                                combined_texts.append(deduplicated_text)
            except Exception as e:
                logger.error(f"Error reading transcription file {trans_file}: {e}")

        final_transcription = " ".join(combined_texts)

        # Check if transcription is empty - if so, delete the recording
        if not final_transcription.strip():
            logger.info(f"Recording {self.current_recording_id} has empty transcription - removing recording folder")
            
            # Delete the entire recording folder since transcription is empty
            import shutil
            if rec_dir.exists():
                try:
                    shutil.rmtree(rec_dir)
                    logger.info(f"Removed recording folder: {rec_dir} (duration: {duration}s)")
                except Exception as e:
                    logger.error(f"Failed to remove recording folder {rec_dir}: {e}", exc_info=True)

            # Show notification
            if hasattr(self, 'tray_icon'):
                self.tray_icon.showMessage(
                    "Opname Leeg",
                    f"Opname heeft geen transcriptie en is verwijderd ({duration}s)",
                    QSystemTrayIcon.MessageIcon.Warning,
                    3000
                )

            # Reset state
            self.is_recording = False
            self.pending_recording_name = None
            return

        # Save final transcription
        transcription_file = rec_dir / f"transcription_{self.current_recording_id}.txt"
        with open(transcription_file, 'w', encoding='utf-8') as f:
            f.write(final_transcription)

        # Update recording metadata
        self.recording_manager.update_recording(
            self.current_recording_id,
            transcription=final_transcription,
            duration=duration,
            name=self.pending_recording_name or f"Opname {self.current_recording_id}"
        )

        logger.info(f"Recording finalized: {len(final_transcription)} chars, {duration}s")

        # Show notification
        if hasattr(self, 'tray_icon'):
            self.tray_icon.showMessage(
                "Opname Voltooid",
                f"Opname getranscribeerd: {len(final_transcription)} tekens",
                QSystemTrayIcon.MessageIcon.Information,
                3000
            )

        # Reset state
        self.is_recording = False
        self.pending_recording_name = None

    def finalize_recording_no_segments(self):
        """Finalize recording when no segments were created (recording too short)"""
        if not self.current_recording_id:
            return

        logger.info(f"Recording {self.current_recording_id} was too short - removing recording folder")

        rec_dir = self.base_recordings_dir / f"recording_{self.current_recording_id}"
        audio_file = rec_dir / f"recording_{self.current_recording_id}.wav"

        # Get audio duration for notification
        duration = 0
        if audio_file.exists():
            duration = self.recording_manager.get_audio_duration(str(audio_file))

        # Delete the entire recording folder since it has no transcription
        import shutil
        if rec_dir.exists():
            try:
                shutil.rmtree(rec_dir)
                logger.info(f"Removed recording folder: {rec_dir} (duration: {duration}s)")
            except Exception as e:
                logger.error(f"Failed to remove recording folder {rec_dir}: {e}", exc_info=True)

        # Show notification
        if hasattr(self, 'tray_icon'):
            self.tray_icon.showMessage(
                "Opname Te Kort",
                f"Opname was te kort voor transcriptie ({duration}s) en is verwijderd",
                QSystemTrayIcon.MessageIcon.Warning,
                3000
            )

        # Reset state
        self.is_recording = False
        self.pending_recording_name = None

    def start_retranscription(self, recording_id):
        """Start retranscription of a recording using the full audio file"""
        logger.info(f"Starting retranscription of recording {recording_id} with model {self.selected_model_name}")

        # Get recording metadata
        recording = self.recording_manager.get_recording(recording_id)
        if not recording:
            logger.error(f"Recording {recording_id} not found")
            QMessageBox.warning(None, "Fout", "Opname niet gevonden.")
            return

        # Find the main audio file
        rec_dir = self.base_recordings_dir / f"recording_{recording_id}"
        audio_file = rec_dir / f"recording_{recording_id}.wav"

        if not audio_file.exists():
            logger.error(f"Audio file not found for recording {recording_id}")
            QMessageBox.warning(None, "Fout", "Audio bestand niet gevonden voor deze opname.")
            return

        # Set current recording ID for retranscription
        self.current_recording_id = recording_id

        # Show notification
        if hasattr(self, 'tray_icon'):
            self.tray_icon.showMessage(
                "Hertranscriptie Gestart",
                f"Hertranscriberen met {self.selected_model_name} model...",
                QSystemTrayIcon.MessageIcon.Information,
                2000
            )

        # Start transcription in background thread
        def retranscribe_worker():
            try:
                # Get the model
                model_name = self.selected_model_name
                if model_name not in self.loaded_models:
                    logger.error(f"Model {model_name} not loaded yet")
                    QMessageBox.warning(None, "Fout", f"Model {model_name} is nog niet geladen. Probeer later opnieuw.")
                    return

                model = self.loaded_models[model_name]
                logger.info(f"Transcribing full audio file {audio_file} with {model_name} model...")

                # Transcribe the full audio file
                result = model.transcribe(
                    str(audio_file),
                    language="nl",
                    task="transcribe",
                    fp16=False,
                    verbose=False
                )

                transcription_text = result["text"].strip()
                logger.info(f"Retranscription complete: {len(transcription_text)} chars")

                # Save new transcription to file
                transcription_file = rec_dir / f"transcription_{recording_id}.txt"
                with open(transcription_file, 'w', encoding='utf-8') as f:
                    f.write(transcription_text)

                # Update recording metadata with new transcription and model
                self.recording_manager.update_recording(
                    recording_id,
                    transcription=transcription_text,
                    model=model_name
                )

                logger.info(f"Updated recording {recording_id} with new transcription and model {model_name}")

                # Show completion notification
                if hasattr(self, 'tray_icon'):
                    self.tray_icon.showMessage(
                        "Hertranscriptie Voltooid",
                        f"Opname hertranscribeerd met {model_name}: {len(transcription_text)} tekens",
                        QSystemTrayIcon.MessageIcon.Information,
                        3000
                    )

            except Exception as e:
                logger.error(f"Error during retranscription: {e}", exc_info=True)
                QMessageBox.critical(None, "Fout", f"Fout bij hertranscriberen: {str(e)}")
            finally:
                # Reset current recording ID
                self.current_recording_id = None

        # Start worker thread
        thread = threading.Thread(target=retranscribe_worker)
        thread.daemon = True
        thread.start()

    # Model loading

    def load_model_async(self, model_name):
        """Load a Whisper model asynchronously"""
        if model_name in self.loaded_models:
            logger.info(f"Model {model_name} already loaded")
            return

        logger.info(f"Loading Whisper model: {model_name}")

        def load_model():
            try:
                # Detect best available device
                if torch.cuda.is_available():
                    device = "cuda"
                elif torch.backends.mps.is_available():
                    device = "mps"
                else:
                    device = "cpu"

                logger.info(f"Loading {model_name} model on {device}...")
                model = whisper.load_model(model_name, device=device)
                self.model_loaded.emit(model_name, model)
                logger.info(f"Model {model_name} loaded successfully on {device}")

            except Exception as e:
                logger.error(f"Error loading model {model_name}: {e}", exc_info=True)

        # Load in background thread
        thread = threading.Thread(target=load_model)
        thread.daemon = True
        thread.start()

    def on_model_loaded(self, model_name, model):
        """Handle model loaded signal"""
        self.loaded_models[model_name] = model
        logger.info(f"Model {model_name} cached")

        # Show notification
        if hasattr(self, 'tray_icon'):
            self.tray_icon.showMessage(
                "Model Geladen",
                f"Whisper model '{model_name}' is geladen en gereed",
                QSystemTrayIcon.MessageIcon.Information,
                2000
            )

    def on_transcription_complete(self, result):
        """Handle transcription complete signal"""
        logger.info("Transcription complete")


def main():
    """Main entry point"""
    # Setup logging
    setup_logging()

    # Log version info
    version = get_version_string()
    logger.info(f"Starting Voice Capture (Tray-Only) - Version {version}")

    # Create QApplication
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # Keep running when no windows

    # Create and show the app
    voice_capture = VoiceCapture()

    # Setup signal handlers for graceful shutdown
    # Use a flag to track if we received a signal
    shutdown_requested = [False]  # Use list to allow modification in nested function

    def signal_handler(signum, frame):
        """Handle shutdown signals gracefully"""
        if shutdown_requested[0]:
            return  # Already shutting down
        shutdown_requested[0] = True
        signal_name = signal.Signals(signum).name
        logger.info(f"Received signal {signal_name}, shutting down gracefully...")
        # Use QTimer to quit from event loop
        QTimer.singleShot(0, voice_capture.quit_application)

    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)   # Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler)  # Termination signal

    # Install a timer to allow Python to process signals
    # Qt event loop blocks Python signal handlers, so we need to wake up periodically
    timer = QTimer()
    timer.start(5000)  # Wake up every 5 seconds to allow signal processing (reduced CPU usage)
    timer.timeout.connect(lambda: None)  # Do nothing, just process signals

    # Run the application
    try:
        exit_code = app.exec()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received, shutting down...")
        voice_capture.quit_application()
        sys.exit(0)


if __name__ == "__main__":
    main()
