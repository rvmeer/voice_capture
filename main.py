#!/usr/bin/env python3
"""
Audio Transcription Application with Whisper
Professional GUI for recording, transcribing, and summarizing audio with history
"""

import sys
import os
import wave
import json
import threading
import subprocess
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

import pyaudio
import whisper
import numpy as np
from pyannote.audio import Pipeline

# Load environment variables
load_dotenv()
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTextEdit, QLabel, QStatusBar, QProgressBar, QTabWidget,
    QListWidget, QListWidgetItem, QInputDialog, QMessageBox, QSplitter,
    QRadioButton, QButtonGroup, QGroupBox, QCheckBox
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QFont, QPalette, QColor, QIcon


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

    def start_recording(self):
        """Start recording audio from microphone"""
        self.frames = []
        self.is_recording = True

        self.stream = self.audio.open(
            format=self.FORMAT,
            channels=self.CHANNELS,
            rate=self.RATE,
            input=True,
            frames_per_buffer=self.CHUNK
        )

        def record():
            while self.is_recording:
                try:
                    data = self.stream.read(self.CHUNK, exception_on_overflow=False)
                    self.frames.append(data)
                except Exception as e:
                    print(f"Recording error: {e}")
                    break

        self.record_thread = threading.Thread(target=record, daemon=True)
        self.record_thread.start()

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

        # Save to temporary file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"recordings/recording_{timestamp}.wav"

        # Create recordings directory if it doesn't exist
        Path("recordings").mkdir(exist_ok=True)

        # Save the recording
        try:
            wf = wave.open(filename, 'wb')
            wf.setnchannels(self.CHANNELS)
            wf.setsampwidth(self.audio.get_sample_size(self.FORMAT))
            wf.setframerate(self.RATE)
            wf.writeframes(b''.join(self.frames))
            wf.close()
        except Exception as e:
            print(f"Error saving recording: {e}")

        return filename, timestamp

    def cleanup(self):
        """Clean up audio resources"""
        if self.stream:
            self.stream.close()
        self.audio.terminate()


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

    def add_recording(self, audio_file, timestamp, name=None, transcription="", summary=""):
        """Add a new recording"""
        recording = {
            "id": timestamp,
            "audio_file": audio_file,
            "name": name or f"Opname {timestamp}",
            "date": datetime.strptime(timestamp, "%Y%m%d_%H%M%S").strftime("%Y-%m-%d %H:%M:%S"),
            "transcription": transcription,
            "summary": summary
        }
        self.recordings.insert(0, recording)  # Add to beginning
        self.save_recordings()
        return recording

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


class TranscriptionApp(QMainWindow):
    """Main application window"""

    # Define signals for thread-safe communication
    transcription_complete = pyqtSignal(dict)
    summary_complete = pyqtSignal(str)
    model_loaded = pyqtSignal(str, object)  # (model_name, model_object)

    def __init__(self):
        super().__init__()
        self.recorder = AudioRecorder()
        self.recording_manager = RecordingManager()

        # Model caching: store loaded models
        self.loaded_models = {}  # {model_name: model_object}
        self.selected_model_name = "tiny"  # Default selected model

        # Speaker diarization setup
        self.diarization_pipeline = None
        self.enable_diarization = False

        self.is_recording = False
        self.recording_time = 0
        self.current_audio_file = None
        self.current_recording_id = None
        self.playback_process = None

        # Connect signals to slots
        self.transcription_complete.connect(self.on_transcription_complete)
        self.summary_complete.connect(self.on_summary_complete)
        self.model_loaded.connect(self.on_model_loaded)

        # Track pending transcription
        self.pending_transcription = False

        self.init_ui()
        self.refresh_recording_list()

    def init_ui(self):
        """Initialize the user interface"""
        self.setWindowTitle("Audio Transcriptie Applicatie")
        self.setGeometry(100, 100, 1400, 800)

        # Set modern style
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f5f5f5;
            }
            QPushButton {
                background-color: #2196F3;
                color: white;
                border: none;
                padding: 12px 24px;
                font-size: 14px;
                border-radius: 6px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
            QPushButton:pressed {
                background-color: #0D47A1;
            }
            QPushButton:disabled {
                background-color: #BDBDBD;
            }
            QTextEdit {
                background-color: white;
                border: 2px solid #e0e0e0;
                border-radius: 8px;
                padding: 12px;
                font-size: 13px;
                line-height: 1.6;
            }
            QLabel {
                color: #333;
                font-size: 13px;
            }
            QTabWidget::pane {
                border: 2px solid #e0e0e0;
                border-radius: 8px;
                background-color: white;
            }
            QTabBar::tab {
                background-color: #e0e0e0;
                color: #333;
                padding: 10px 20px;
                margin-right: 2px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
            }
            QTabBar::tab:selected {
                background-color: white;
                color: #2196F3;
                font-weight: bold;
            }
            QListWidget {
                background-color: white;
                border: 2px solid #e0e0e0;
                border-radius: 8px;
                padding: 5px;
                font-size: 13px;
            }
            QListWidget::item {
                padding: 10px;
                border-radius: 4px;
                margin: 2px;
            }
            QListWidget::item:selected {
                background-color: #2196F3;
                color: white;
            }
            QListWidget::item:hover {
                background-color: #E3F2FD;
            }
        """)

        # Central widget with splitter
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)

        # Left panel - Recording list
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(20, 20, 10, 20)
        left_layout.setSpacing(15)

        list_header = QLabel("📚 Opnames")
        list_header.setFont(QFont("Arial", 18, QFont.Weight.Bold))
        list_header.setStyleSheet("color: #1976D2;")
        left_layout.addWidget(list_header)

        self.recording_list = QListWidget()
        # Enable multi-selection
        self.recording_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.recording_list.itemClicked.connect(self.load_recording)
        self.recording_list.itemSelectionChanged.connect(self.update_button_states)
        left_layout.addWidget(self.recording_list)

        # List action buttons - Row 1
        list_btn_layout1 = QHBoxLayout()
        list_btn_layout1.setSpacing(10)

        self.play_btn = QPushButton("▶ Afspelen")
        self.play_btn.clicked.connect(self.play_recording)
        self.play_btn.setEnabled(False)
        list_btn_layout1.addWidget(self.play_btn)

        self.rename_btn = QPushButton("✏️ Hernoemen")
        self.rename_btn.clicked.connect(self.rename_recording)
        self.rename_btn.setEnabled(False)
        list_btn_layout1.addWidget(self.rename_btn)

        left_layout.addLayout(list_btn_layout1)

        # List action buttons - Row 2
        list_btn_layout2 = QHBoxLayout()
        list_btn_layout2.setSpacing(10)

        self.retranscribe_btn = QPushButton("🔄 Hertranscribeer")
        self.retranscribe_btn.clicked.connect(self.retranscribe_recording)
        self.retranscribe_btn.setEnabled(False)
        list_btn_layout2.addWidget(self.retranscribe_btn)

        self.delete_btn = QPushButton("🗑️ Verwijderen")
        self.delete_btn.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #da190b;
            }
            QPushButton:disabled {
                background-color: #BDBDBD;
            }
        """)
        self.delete_btn.clicked.connect(self.delete_recordings)
        self.delete_btn.setEnabled(False)
        list_btn_layout2.addWidget(self.delete_btn)

        left_layout.addLayout(list_btn_layout2)

        # Right panel - Main content
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setSpacing(20)
        right_layout.setContentsMargins(10, 30, 30, 30)

        # Header
        header_label = QLabel("🎙️ Audio Transcriptie met Whisper")
        header_label.setFont(QFont("Arial", 24, QFont.Weight.Bold))
        header_label.setStyleSheet("color: #1976D2; margin-bottom: 10px;")
        header_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right_layout.addWidget(header_label)

        # Model selection group
        model_group = QGroupBox("Whisper Model Keuze")
        model_group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #333;
                border: 2px solid #e0e0e0;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
            QRadioButton {
                font-size: 13px;
                spacing: 8px;
            }
            QRadioButton::indicator {
                width: 18px;
                height: 18px;
            }
        """)
        model_layout = QHBoxLayout()
        model_layout.setSpacing(20)

        self.model_button_group = QButtonGroup()

        self.tiny_radio = QRadioButton("Tiny (Snel, ~1GB)")
        self.tiny_radio.setChecked(True)
        self.tiny_radio.toggled.connect(lambda: self.on_model_changed("tiny") if self.tiny_radio.isChecked() else None)
        self.model_button_group.addButton(self.tiny_radio)
        model_layout.addWidget(self.tiny_radio)

        self.small_radio = QRadioButton("Small (Goed, ~2GB)")
        self.small_radio.toggled.connect(lambda: self.on_model_changed("small") if self.small_radio.isChecked() else None)
        self.model_button_group.addButton(self.small_radio)
        model_layout.addWidget(self.small_radio)

        self.medium_radio = QRadioButton("Medium (Beter, ~5GB)")
        self.medium_radio.toggled.connect(lambda: self.on_model_changed("medium") if self.medium_radio.isChecked() else None)
        self.model_button_group.addButton(self.medium_radio)
        model_layout.addWidget(self.medium_radio)

        self.large_radio = QRadioButton("Large (Best, ~10GB)")
        self.large_radio.toggled.connect(lambda: self.on_model_changed("large") if self.large_radio.isChecked() else None)
        self.model_button_group.addButton(self.large_radio)
        model_layout.addWidget(self.large_radio)

        model_layout.addStretch()
        model_group.setLayout(model_layout)
        right_layout.addWidget(model_group)

        # Speaker diarization checkbox
        self.diarization_checkbox = QCheckBox("🎭 Speaker herkenning (langzaam, ~5-10 min)")
        self.diarization_checkbox.setStyleSheet("font-size: 13px; padding: 5px;")
        self.diarization_checkbox.stateChanged.connect(self.on_diarization_toggled)
        right_layout.addWidget(self.diarization_checkbox)

        # Recording controls
        control_layout = QHBoxLayout()
        control_layout.setSpacing(15)

        self.record_btn = QPushButton("● Opname Starten")
        self.record_btn.setMinimumHeight(50)
        self.record_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                font-size: 16px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        self.record_btn.clicked.connect(self.toggle_recording)
        control_layout.addWidget(self.record_btn)

        self.timer_label = QLabel("00:00")
        self.timer_label.setFont(QFont("Courier", 20, QFont.Weight.Bold))
        self.timer_label.setStyleSheet("color: #666; background-color: #e0e0e0; padding: 10px 20px; border-radius: 6px;")
        self.timer_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.timer_label.setMinimumWidth(100)
        control_layout.addWidget(self.timer_label)

        right_layout.addLayout(control_layout)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 2px solid #e0e0e0;
                border-radius: 6px;
                text-align: center;
                height: 25px;
            }
            QProgressBar::chunk {
                background-color: #2196F3;
                border-radius: 4px;
            }
        """)
        right_layout.addWidget(self.progress_bar)

        # Status label
        self.status_label = QLabel("Klaar om op te nemen")
        self.status_label.setFont(QFont("Arial", 12))
        self.status_label.setStyleSheet("color: #666; font-style: italic;")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right_layout.addWidget(self.status_label)

        # Tabs for transcription and summary
        self.tabs = QTabWidget()

        # Transcription tab
        transcription_widget = QWidget()
        transcription_layout = QVBoxLayout(transcription_widget)
        transcription_layout.setContentsMargins(15, 15, 15, 15)

        transcription_label = QLabel("📝 Transcriptie")
        transcription_label.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        transcription_label.setStyleSheet("color: #1976D2;")
        transcription_layout.addWidget(transcription_label)

        self.transcription_text = QTextEdit()
        self.transcription_text.setPlaceholderText("Transcriptie verschijnt hier na de opname...")
        self.transcription_text.setFont(QFont("Arial", 13))
        transcription_layout.addWidget(self.transcription_text)

        # Summary tab
        summary_widget = QWidget()
        summary_layout = QVBoxLayout(summary_widget)
        summary_layout.setContentsMargins(15, 15, 15, 15)

        summary_label = QLabel("📊 Samenvatting")
        summary_label.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        summary_label.setStyleSheet("color: #1976D2;")
        summary_layout.addWidget(summary_label)

        self.summary_text = QTextEdit()
        self.summary_text.setPlaceholderText("Samenvatting verschijnt hier na de transcriptie...")
        self.summary_text.setFont(QFont("Arial", 13))
        summary_layout.addWidget(self.summary_text)

        self.tabs.addTab(transcription_widget, "Transcriptie")
        self.tabs.addTab(summary_widget, "Samenvatting")

        right_layout.addWidget(self.tabs, stretch=1)

        # Add panels to splitter
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        # Status bar
        self.status_bar = QStatusBar()
        self.status_bar.setStyleSheet("background-color: #e0e0e0; color: #666;")
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Applicatie gestart")

        # Timer for recording duration
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_timer)

    def load_diarization_pipeline(self):
        """Load speaker diarization pipeline with HF token"""
        def load_pipeline():
            try:
                hf_token = os.getenv('HF_TOKEN')
                if not hf_token:
                    print("WARNING: HF_TOKEN not found in .env file")
                    return

                print(f"DEBUG: Loading diarization pipeline with HF token...")
                self.diarization_pipeline = Pipeline.from_pretrained(
                    "pyannote/speaker-diarization",
                    use_auth_token=hf_token
                )
                print(f"DEBUG: Diarization pipeline loaded successfully!")
            except Exception as e:
                print(f"WARNING: Could not load diarization pipeline: {e}")
                print(f"Speaker detection will be disabled")

        # Load in background
        thread = threading.Thread(target=load_pipeline, daemon=True)
        thread.start()

    def on_diarization_toggled(self, state):
        """Handle speaker diarization checkbox toggle"""
        self.enable_diarization = (state == Qt.CheckState.Checked.value)

        if self.enable_diarization:
            # Load pipeline if not already loaded
            if not self.diarization_pipeline:
                self.status_bar.showMessage("Speaker herkenning pipeline laden...")
                self.load_diarization_pipeline()
            else:
                self.status_bar.showMessage("Speaker herkenning ingeschakeld (zeer traag op CPU)")
        else:
            self.status_bar.showMessage("Speaker herkenning uitgeschakeld")

    def on_model_changed(self, model_name):
        """Handle model selection change"""
        if model_name == self.selected_model_name:
            return  # No change

        print(f"DEBUG: Model selection changed to: {model_name}")
        self.selected_model_name = model_name

        # Check if already loaded
        if model_name in self.loaded_models:
            self.status_bar.showMessage(f"{model_name.capitalize()} model geselecteerd (reeds geladen)")
        else:
            self.status_bar.showMessage(f"{model_name.capitalize()} model geselecteerd (wordt geladen bij volgende transcriptie)")

    def get_or_load_model(self, model_name):
        """Get model from cache or load it (lazy loading with caching)"""
        # Check if model is already cached
        if model_name in self.loaded_models:
            print(f"DEBUG: Using cached {model_name} model")
            # Immediately proceed with transcription
            self.start_transcription_with_model(self.loaded_models[model_name])
            return

        # Model not cached, need to load it
        print(f"DEBUG: Loading {model_name} model for first time...")
        self.pending_transcription = True

        model_sizes = {
            "tiny": "~1GB, snel",
            "small": "~2GB, goed",
            "medium": "~5GB, beter",
            "large": "~10GB, best"
        }

        self.status_label.setText(f"Whisper {model_name} model laden...")
        self.status_bar.showMessage(f"Whisper {model_name} model aan het laden ({model_sizes.get(model_name, '')})...")

        # Disable UI during loading
        self.record_btn.setEnabled(False)
        self.tiny_radio.setEnabled(False)
        self.small_radio.setEnabled(False)
        self.medium_radio.setEnabled(False)
        self.large_radio.setEnabled(False)

        def load_model():
            try:
                print(f"DEBUG: Starting to load Whisper {model_name} model...")
                # Load model for CPU transcription
                model = whisper.load_model(model_name, device="cpu")
                print(f"DEBUG: Whisper {model_name} model loaded successfully!")

                # Cache the model
                self.loaded_models[model_name] = model
                print(f"DEBUG: Model cached, emitting signal...")

                # Emit signal to handle in main thread
                self.model_loaded.emit(model_name, model)

            except Exception as e:
                print(f"DEBUG: Error loading model: {e}")
                import traceback
                traceback.print_exc()
                self.model_loaded.emit(model_name, None)

        thread = threading.Thread(target=load_model, daemon=True)
        thread.start()

    def on_model_loaded(self, model_name, model):
        """Handle model loaded signal (main thread)"""
        print(f"DEBUG: on_model_loaded called for {model_name}, model: {model is not None}")

        self.status_label.setText(f"✅ {model_name.capitalize()} model geladen")
        self.status_bar.showMessage(f"Whisper {model_name} model succesvol geladen en gecached")
        self.enable_ui_after_model_load()

        if model and self.pending_transcription:
            print(f"DEBUG: Starting pending transcription...")
            self.pending_transcription = False
            self.start_transcription_with_model(model)
        elif not model:
            self.transcription_complete.emit({"error": "Model laden mislukt"})

    def enable_ui_after_model_load(self):
        """Re-enable UI after model loading"""
        self.tiny_radio.setEnabled(True)
        self.small_radio.setEnabled(True)
        self.medium_radio.setEnabled(True)
        self.large_radio.setEnabled(True)
        self.record_btn.setEnabled(True)

    def refresh_recording_list(self):
        """Refresh the recording list"""
        self.recording_list.clear()
        for rec in self.recording_manager.recordings:
            item_text = f"🎵 {rec['name']}\n📅 {rec['date']}"
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, rec['id'])
            self.recording_list.addItem(item)

    def toggle_recording(self):
        """Toggle recording on/off"""
        if not self.is_recording:
            self.start_recording()
        else:
            self.stop_recording()

    def start_recording(self):
        """Start audio recording"""
        self.is_recording = True
        self.recording_time = 0
        self.transcription_text.clear()
        self.summary_text.clear()

        self.record_btn.setText("■ Opname Stoppen")
        self.record_btn.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                font-size: 16px;
            }
            QPushButton:hover {
                background-color: #da190b;
            }
        """)
        self.status_label.setText("🔴 Opname bezig...")
        self.status_bar.showMessage("Opname gestart")

        self.recorder.start_recording()
        self.timer.start(1000)  # Update every second

    def stop_recording(self):
        """Stop audio recording and process"""
        self.is_recording = False
        self.timer.stop()

        self.record_btn.setEnabled(False)
        self.record_btn.setText("● Opname Starten")
        self.record_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                font-size: 16px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        self.status_label.setText("Opname opslaan...")
        self.status_bar.showMessage("Opname gestopt, aan het opslaan...")

        # Force process events to handle UI updates
        QApplication.processEvents()

        # Save recording in a thread-safe way
        def save_and_continue():
            try:
                self.current_audio_file, self.current_recording_id = self.recorder.stop_recording()
                # Use QTimer to safely show dialog after save completes
                QTimer.singleShot(200, self.ask_recording_name)
            except Exception as e:
                print(f"Error in save_and_continue: {e}")
                import traceback
                traceback.print_exc()
                self.record_btn.setEnabled(True)

        # Delay the save operation to let audio thread cleanup
        QTimer.singleShot(100, save_and_continue)

    def ask_recording_name(self):
        """Ask for recording name (called after stop_recording completes)"""
        # Ask for name
        default_name = f"Opname {datetime.now().strftime('%H:%M')}"
        name, ok = QInputDialog.getText(
            self,
            "Opname Naam",
            "Geef deze opname een naam:",
            text=default_name
        )

        if ok and name:
            recording_name = name
        else:
            recording_name = f"Opname {self.current_recording_id}"

        # Add to manager
        self.recording_manager.add_recording(
            self.current_audio_file,
            self.current_recording_id,
            name=recording_name
        )

        # Refresh list
        self.refresh_recording_list()

        # Start transcription in background
        self.transcribe_audio()

    def update_timer(self):
        """Update recording timer display"""
        self.recording_time += 1
        minutes = self.recording_time // 60
        seconds = self.recording_time % 60
        self.timer_label.setText(f"{minutes:02d}:{seconds:02d}")

    def transcribe_audio(self):
        """Transcribe audio using Whisper"""
        print(f"DEBUG: Starting transcription for file: {self.current_audio_file}")
        print(f"DEBUG: Selected model: {self.selected_model_name}")

        # Load model if needed, then transcribe
        self.get_or_load_model(self.selected_model_name)

    def start_transcription_with_model(self, model):
        """Start transcription with loaded model"""
        print(f"DEBUG: start_transcription_with_model called")

        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminate progress

        model_times = {
            "tiny": "5-10 seconden",
            "small": "15-30 seconden",
            "medium": "30-60 seconden",
            "large": "1-3 minuten"
        }

        time_estimate = model_times.get(self.selected_model_name, "enkele seconden")

        self.status_label.setText(f"Transcriptie bezig (~{time_estimate})...")
        self.status_bar.showMessage(f"Audio wordt getranscribeerd...")

        # Force UI update
        QApplication.processEvents()

        def worker():
            try:
                print(f"DEBUG: Worker thread started with {self.selected_model_name} model")

                # Step 1: Transcribe with Whisper (with word timestamps for speaker alignment)
                print(f"DEBUG: Starting Whisper transcription...")
                result = model.transcribe(
                    self.current_audio_file,
                    language="nl",
                    task="transcribe",
                    fp16=False,
                    word_timestamps=True  # Get word-level timestamps
                )
                print(f"DEBUG: Transcription completed!")

                # Step 2: Speaker diarization if enabled
                if self.enable_diarization and self.diarization_pipeline:
                    print(f"DEBUG: Running speaker diarization...")
                    formatted_text = self.apply_speaker_diarization(result)
                    result['formatted_text'] = formatted_text
                    print(f"DEBUG: Diarization completed!")
                else:
                    print(f"DEBUG: Speaker diarization disabled, using plain text")
                    result['formatted_text'] = result.get('text', '')

                # Emit signal to update UI in main thread
                print(f"DEBUG: Emitting transcription_complete signal")
                self.transcription_complete.emit(result)
                print(f"DEBUG: Signal emitted successfully")

            except Exception as e:
                print(f"DEBUG: Transcription error: {e}")
                import traceback
                traceback.print_exc()
                self.transcription_complete.emit({"error": str(e)})

        print(f"DEBUG: Creating worker thread...")
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        print(f"DEBUG: Worker thread started")

    def apply_speaker_diarization(self, whisper_result):
        """Apply speaker diarization and align with transcription"""
        try:
            # Run diarization on audio file
            print(f"DEBUG: Running diarization on {self.current_audio_file}")
            diarization = self.diarization_pipeline(self.current_audio_file)

            # Get segments with speaker info
            segments = whisper_result.get('segments', [])
            formatted = []

            for segment in segments:
                start = segment.get('start', 0)
                end = segment.get('end', 0)
                text = segment.get('text', '').strip()

                # Find which speaker is active at this time
                speaker = self.get_speaker_at_time(diarization, start, end)

                if speaker:
                    formatted.append(f"[{speaker}]: {text}")
                else:
                    formatted.append(f"[Onbekend]: {text}")

            return "\n\n".join(formatted)

        except Exception as e:
            print(f"ERROR in diarization: {e}")
            import traceback
            traceback.print_exc()
            # Fallback to plain text
            return whisper_result.get('text', '')

    def get_speaker_at_time(self, diarization, start, end):
        """Get the speaker who is active during the given time range"""
        mid_point = (start + end) / 2

        for turn, _, speaker in diarization.itertracks(yield_label=True):
            if turn.start <= mid_point <= turn.end:
                return f"Spreker {speaker}"

        return None

    def on_transcription_complete(self, result):
        """Handle transcription completion in main thread (slot)"""
        print(f"DEBUG: on_transcription_complete called with result type: {type(result)}")
        self.progress_bar.setVisible(False)

        if "error" in result:
            print(f"DEBUG: Error in result: {result['error']}")
            self.status_label.setText(f"Fout: {result['error']}")
            self.status_bar.showMessage(f"Transcriptie fout: {result['error']}")
        else:
            # Use formatted text with speakers if available
            formatted_text = result.get("formatted_text", "")
            plain_text = result.get("text", "")

            # Use formatted version for display
            display_text = formatted_text if formatted_text else plain_text

            print(f"DEBUG: Setting transcription text (length={len(display_text)}): {display_text[:100]}...")

            # Update UI
            self.transcription_text.clear()
            self.transcription_text.setPlainText(display_text)

            print(f"DEBUG: Text set in UI, updating labels")
            if self.enable_diarization and self.diarization_pipeline:
                self.status_label.setText("✅ Transcriptie + speakers voltooid")
                self.status_bar.showMessage("Transcriptie met speaker herkenning voltooid")
            else:
                self.status_label.setText("✅ Transcriptie voltooid")
                self.status_bar.showMessage("Transcriptie succesvol voltooid")

            # Update recording with transcription (use plain text for summary)
            print(f"DEBUG: Updating recording in database")
            self.recording_manager.update_recording(
                self.current_recording_id,
                transcription=display_text
            )

            # Generate summary (use plain text)
            print(f"DEBUG: Generating summary")
            self.generate_summary(plain_text)

        self.record_btn.setEnabled(True)
        print(f"DEBUG: on_transcription_complete finished")

    def generate_summary(self, text):
        """Generate a summary of the transcription"""
        self.status_label.setText("Samenvatting genereren...")

        def worker():
            try:
                print(f"DEBUG: Summary worker started")
                # Simple extractive summary: take first few sentences and key points
                sentences = text.split('. ')

                # Word frequency for key topics
                words = text.lower().split()
                word_freq = {}
                stop_words = {'de', 'het', 'een', 'en', 'is', 'van', 'in', 'te', 'dat', 'op', 'voor', 'met', 'als', 'zijn', 'er', 'maar', 'om', 'hij', 'ze', 'aan', 'werd', 'ook', 'tot', 'die', 'dit', 'bij', 'zo', 'deze', 'naar', 'door'}

                for word in words:
                    word = word.strip('.,!?;:').lower()
                    if len(word) > 3 and word not in stop_words:
                        word_freq[word] = word_freq.get(word, 0) + 1

                # Get top keywords
                top_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)[:10]
                keywords = [word for word, freq in top_words]

                # Build summary
                summary = "**Belangrijkste punten:**\n\n"

                # Add first sentence as intro
                if sentences:
                    summary += f"• {sentences[0].strip()}.\n\n"

                # Add statistics
                word_count = len(words)
                sentence_count = len([s for s in sentences if s.strip()])
                summary += f"**Statistieken:**\n"
                summary += f"• Aantal woorden: {word_count}\n"
                summary += f"• Aantal zinnen: {sentence_count}\n\n"

                # Add keywords
                summary += f"**Kernwoorden:**\n"
                summary += ", ".join(keywords[:8])

                print(f"DEBUG: Summary generated, emitting signal")
                # Emit signal to update UI
                self.summary_complete.emit(summary)

            except Exception as e:
                self.summary_complete.emit(f"Fout bij samenvatting: {str(e)}")

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

    def on_summary_complete(self, summary):
        """Handle summary completion in main thread (slot)"""
        print(f"DEBUG: on_summary_complete called")
        self.summary_text.clear()
        self.summary_text.setPlainText(summary)
        self.status_label.setText("✅ Klaar - Transcriptie en samenvatting voltooid")
        self.status_bar.showMessage("Volledig verwerkt en klaar")

        # Update recording with summary
        self.recording_manager.update_recording(
            self.current_recording_id,
            summary=summary
        )
        print(f"DEBUG: Summary completed and saved")

    def update_button_states(self):
        """Update button states based on selection"""
        selected_items = self.recording_list.selectedItems()
        num_selected = len(selected_items)

        if num_selected == 0:
            self.play_btn.setEnabled(False)
            self.rename_btn.setEnabled(False)
            self.retranscribe_btn.setEnabled(False)
            self.delete_btn.setEnabled(False)
        elif num_selected == 1:
            self.play_btn.setEnabled(True)
            self.rename_btn.setEnabled(True)
            self.retranscribe_btn.setEnabled(True)
            self.delete_btn.setEnabled(True)
        else:  # Multiple selections
            self.play_btn.setEnabled(False)
            self.rename_btn.setEnabled(False)
            self.retranscribe_btn.setEnabled(False)
            self.delete_btn.setEnabled(True)

    def load_recording(self, item):
        """Load a recording from the list"""
        # Only load if single selection
        selected_items = self.recording_list.selectedItems()
        if len(selected_items) != 1:
            return

        recording_id = item.data(Qt.ItemDataRole.UserRole)
        recording = self.recording_manager.get_recording(recording_id)

        if recording:
            self.current_recording_id = recording_id
            self.current_audio_file = recording['audio_file']
            self.transcription_text.setPlainText(recording.get('transcription', ''))
            self.summary_text.setPlainText(recording.get('summary', ''))
            self.status_label.setText(f"Geladen: {recording['name']}")
            self.status_bar.showMessage(f"Opname geladen: {recording['date']}")

    def play_recording(self):
        """Play the selected recording using system audio player"""
        if self.current_audio_file and Path(self.current_audio_file).exists():
            try:
                # Stop any existing playback
                if self.playback_process and self.playback_process.poll() is None:
                    self.playback_process.terminate()

                # Use macOS afplay command for audio playback
                audio_path = str(Path(self.current_audio_file).absolute())
                self.playback_process = subprocess.Popen(
                    ['afplay', audio_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                self.status_bar.showMessage("Audio afspelen...")

                # Update button text
                self.play_btn.setText("⏹ Stoppen")
                self.play_btn.clicked.disconnect()
                self.play_btn.clicked.connect(self.stop_playback)

                # Monitor playback completion
                def check_playback():
                    if self.playback_process and self.playback_process.poll() is not None:
                        self.reset_play_button()
                    else:
                        QTimer.singleShot(500, check_playback)

                QTimer.singleShot(500, check_playback)

            except Exception as e:
                QMessageBox.warning(self, "Fout", f"Kan audio niet afspelen: {str(e)}")
        else:
            QMessageBox.warning(self, "Fout", "Audio bestand niet gevonden")

    def stop_playback(self):
        """Stop audio playback"""
        if self.playback_process and self.playback_process.poll() is None:
            self.playback_process.terminate()
            self.playback_process.wait()
        self.reset_play_button()
        self.status_bar.showMessage("Afspelen gestopt")

    def reset_play_button(self):
        """Reset play button to default state"""
        try:
            self.play_btn.clicked.disconnect()
        except:
            pass
        self.play_btn.setText("▶ Afspelen")
        self.play_btn.clicked.connect(self.play_recording)

    def rename_recording(self):
        """Rename the selected recording"""
        selected_items = self.recording_list.selectedItems()
        if len(selected_items) != 1:
            return

        recording_id = selected_items[0].data(Qt.ItemDataRole.UserRole)
        recording = self.recording_manager.get_recording(recording_id)
        if recording:
            new_name, ok = QInputDialog.getText(
                self,
                "Opname Hernoemen",
                "Nieuwe naam:",
                text=recording['name']
            )
            if ok and new_name:
                self.recording_manager.update_recording(recording_id, name=new_name)
                self.refresh_recording_list()
                self.status_bar.showMessage(f"Hernoemd naar: {new_name}")

    def retranscribe_recording(self):
        """Re-transcribe the selected recording with current model"""
        selected_items = self.recording_list.selectedItems()
        if len(selected_items) != 1:
            return

        recording_id = selected_items[0].data(Qt.ItemDataRole.UserRole)
        recording = self.recording_manager.get_recording(recording_id)

        if not recording:
            return

        # Confirm re-transcription
        reply = QMessageBox.question(
            self,
            "Hertranscribeer Opname",
            f"Wil je '{recording['name']}' hertranscriberen met het {self.selected_model_name} model?\n\nDe huidige transcriptie wordt overschreven.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            # Set current audio file for transcription
            self.current_audio_file = recording['audio_file']
            self.current_recording_id = recording_id

            # Check if file exists
            if not Path(self.current_audio_file).exists():
                QMessageBox.warning(self, "Fout", f"Audio bestand niet gevonden: {self.current_audio_file}")
                return

            # Start transcription
            self.status_bar.showMessage(f"Hertranscriberen van '{recording['name']}'...")
            self.transcribe_audio()

    def delete_recordings(self):
        """Delete selected recording(s)"""
        selected_items = self.recording_list.selectedItems()
        if not selected_items:
            return

        num_selected = len(selected_items)

        # Confirmation dialog
        if num_selected == 1:
            recording_id = selected_items[0].data(Qt.ItemDataRole.UserRole)
            recording = self.recording_manager.get_recording(recording_id)
            msg = f"Weet je zeker dat je '{recording['name']}' wilt verwijderen?"
        else:
            msg = f"Weet je zeker dat je {num_selected} opnames wilt verwijderen?"

        reply = QMessageBox.question(
            self,
            "Opnames Verwijderen",
            msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            # Delete each selected recording
            deleted_count = 0
            for item in selected_items:
                recording_id = item.data(Qt.ItemDataRole.UserRole)
                recording = self.recording_manager.get_recording(recording_id)

                if recording:
                    # Delete audio file
                    audio_file = Path(recording['audio_file'])
                    if audio_file.exists():
                        try:
                            audio_file.unlink()
                        except Exception as e:
                            print(f"Error deleting audio file: {e}")

                    # Remove from database
                    self.recording_manager.recordings.remove(recording)
                    deleted_count += 1

            # Save updated database
            self.recording_manager.save_recordings()

            # Clear current selection if it was deleted
            if self.current_recording_id in [item.data(Qt.ItemDataRole.UserRole) for item in selected_items]:
                self.current_recording_id = None
                self.current_audio_file = None
                self.transcription_text.clear()
                self.summary_text.clear()

            # Refresh list
            self.refresh_recording_list()

            # Update status
            if deleted_count == 1:
                self.status_bar.showMessage("Opname verwijderd")
            else:
                self.status_bar.showMessage(f"{deleted_count} opnames verwijderd")

    def closeEvent(self, event):
        """Clean up on close"""
        self.recorder.cleanup()

        # Stop any playback
        if self.playback_process and self.playback_process.poll() is None:
            self.playback_process.terminate()
            self.playback_process.wait()

        event.accept()


def main():
    """Main application entry point"""
    app = QApplication(sys.argv)
    app.setStyle('Fusion')

    window = TranscriptionApp()
    window.show()

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
