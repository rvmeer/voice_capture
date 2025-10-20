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
from openai import AzureOpenAI

# Load environment variables
load_dotenv()
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTextEdit, QLabel, QStatusBar, QProgressBar, QTabWidget,
    QListWidget, QListWidgetItem, QInputDialog, QMessageBox, QSplitter,
    QRadioButton, QButtonGroup, QGroupBox, QCheckBox, QSpinBox, QFormLayout
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

    def add_recording(self, audio_file, timestamp, name=None, transcription="", summary="", duration=0, model=""):
        """Add a new recording"""
        recording = {
            "id": timestamp,
            "audio_file": audio_file,
            "name": name or f"Opname {timestamp}",
            "date": datetime.strptime(timestamp, "%Y%m%d_%H%M%S").strftime("%Y-%m-%d %H:%M:%S"),
            "transcription": transcription,
            "summary": summary,
            "duration": duration,  # Duration in seconds
            "model": model  # Model used for transcription
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


class TranscriptionApp(QMainWindow):
    """Main application window"""

    # Define signals for thread-safe communication
    transcription_complete = pyqtSignal(dict)
    summary_complete = pyqtSignal(str)
    model_loaded = pyqtSignal(str, object)  # (model_name, model_object)
    segment_transcribed = pyqtSignal(str)  # Signal for incremental transcription updates

    def __init__(self):
        super().__init__()
        self.recorder = AudioRecorder()
        self.recording_manager = RecordingManager()

        # Model caching: store loaded models
        self.loaded_models = {}  # {model_name: model_object}
        self.selected_model_name = "tiny"  # Default selected model

        self.is_recording = False
        self.recording_time = 0
        self.current_audio_file = None
        self.current_recording_id = None
        self.playback_process = None

        # Connect signals to slots
        self.transcription_complete.connect(self.on_transcription_complete)
        self.summary_complete.connect(self.on_summary_complete)
        self.model_loaded.connect(self.on_model_loaded)
        self.segment_transcribed.connect(self.on_segment_transcribed)

        # Track pending transcription
        self.pending_transcription = False

        # Track segments for incremental transcription
        self.segments_to_transcribe = []  # Queue of segments to transcribe
        self.transcribed_segments = []  # List of transcribed texts
        self.is_transcribing_segment = False  # Flag to track if currently transcribing

        # Settings
        self.segment_duration = 30  # seconds
        self.overlap_duration = 15  # seconds
        self.summary_prompt = """Maak een samenvatting wat hier besproken is. Geef ook de actiepunten.
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

        # Azure OpenAI client for summary generation
        self.azure_client = None
        self.init_azure_client()

        self.init_ui()
        self.refresh_recording_list()

        # Load default model (tiny) on startup
        QTimer.singleShot(500, lambda: self.load_model_async(self.selected_model_name))

    def init_azure_client(self):
        """Initialize Azure OpenAI client"""
        try:
            api_key = os.getenv('AZURE_OPENAI_API_KEY')
            endpoint = os.getenv('AZURE_OPENAI_ENDPOINT')
            api_version = os.getenv('OPENAI_API_VERSION')

            if not all([api_key, endpoint, api_version]):
                print("WARNING: Azure OpenAI credentials not found in .env file")
                return

            self.azure_client = AzureOpenAI(
                api_key=api_key,
                api_version=api_version,
                azure_endpoint=endpoint
            )
            print(f"DEBUG: Azure OpenAI client initialized successfully")
        except Exception as e:
            print(f"WARNING: Could not initialize Azure OpenAI client: {e}")
            self.azure_client = None

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

        # Settings tab
        settings_widget = QWidget()
        settings_layout = QVBoxLayout(settings_widget)
        settings_layout.setContentsMargins(15, 15, 15, 15)

        settings_label = QLabel("⚙️ Instellingen")
        settings_label.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        settings_label.setStyleSheet("color: #1976D2;")
        settings_layout.addWidget(settings_label)

        # Form for settings
        settings_form = QWidget()
        form_layout = QFormLayout(settings_form)
        form_layout.setSpacing(15)
        form_layout.setContentsMargins(10, 20, 10, 10)

        # Segment duration
        self.segment_duration_spin = QSpinBox()
        self.segment_duration_spin.setMinimum(10)
        self.segment_duration_spin.setMaximum(120)
        self.segment_duration_spin.setValue(self.segment_duration)
        self.segment_duration_spin.setSuffix(" seconden")
        self.segment_duration_spin.setStyleSheet("QSpinBox { padding: 8px; font-size: 13px; }")
        form_layout.addRow("Lengte fragmenten:", self.segment_duration_spin)

        # Overlap duration
        self.overlap_duration_spin = QSpinBox()
        self.overlap_duration_spin.setMinimum(5)
        self.overlap_duration_spin.setMaximum(60)
        self.overlap_duration_spin.setValue(self.overlap_duration)
        self.overlap_duration_spin.setSuffix(" seconden")
        self.overlap_duration_spin.setStyleSheet("QSpinBox { padding: 8px; font-size: 13px; }")
        form_layout.addRow("Overlap fragmenten:", self.overlap_duration_spin)

        settings_layout.addWidget(settings_form)

        # Summary prompt text area
        prompt_label = QLabel("Samenvatting Prompt:")
        prompt_label.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        prompt_label.setStyleSheet("color: #333; margin-top: 10px;")
        settings_layout.addWidget(prompt_label)

        self.summary_prompt_text = QTextEdit()
        self.summary_prompt_text.setPlainText(self.summary_prompt)
        self.summary_prompt_text.setFont(QFont("Arial", 12))
        self.summary_prompt_text.setMinimumHeight(250)
        settings_layout.addWidget(self.summary_prompt_text)

        # Apply button
        apply_btn = QPushButton("✓ Instellingen Toepassen")
        apply_btn.setMinimumHeight(45)
        apply_btn.clicked.connect(self.apply_settings)
        settings_layout.addWidget(apply_btn)

        settings_layout.addStretch()

        self.tabs.addTab(transcription_widget, "Transcriptie")
        self.tabs.addTab(summary_widget, "Samenvatting")
        self.tabs.addTab(settings_widget, "Instellingen")

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

    def on_model_changed(self, model_name):
        """Handle model selection change"""
        if model_name == self.selected_model_name:
            return  # No change

        print(f"DEBUG: Model selection changed to: {model_name}")
        self.selected_model_name = model_name

        # Check if already loaded
        if model_name in self.loaded_models:
            self.status_bar.showMessage(f"{model_name.capitalize()} model geselecteerd (reeds geladen)")
            self.status_label.setText(f"✅ {model_name.capitalize()} model klaar")
        else:
            # Load model immediately
            self.status_bar.showMessage(f"{model_name.capitalize()} model wordt geladen...")
            self.status_label.setText(f"Model {model_name} laden...")
            self.load_model_async(model_name)

    def load_model_async(self, model_name):
        """Load a model asynchronously (used for immediate loading on model switch)"""
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
        self.load_model_async(model_name)

    def on_model_loaded(self, model_name, model):
        """Handle model loaded signal (main thread)"""
        print(f"DEBUG: on_model_loaded called for {model_name}, model: {model is not None}")

        if model:
            self.status_label.setText(f"✅ {model_name.capitalize()} model geladen")
            self.status_bar.showMessage(f"Whisper {model_name} model succesvol geladen en gecached")
        else:
            self.status_label.setText(f"❌ {model_name.capitalize()} model laden mislukt")
            self.status_bar.showMessage(f"Fout bij laden van {model_name} model")

        # Re-enable UI
        self.enable_ui_after_model_load()

        # If there was a pending transcription, start it now
        if model and self.pending_transcription:
            print(f"DEBUG: Starting pending transcription...")
            self.pending_transcription = False
            self.start_transcription_with_model(model)
        elif not model and self.pending_transcription:
            self.pending_transcription = False
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
            # Format duration
            duration = rec.get('duration', 0)
            minutes = duration // 60
            seconds = duration % 60
            duration_str = f"{minutes}:{seconds:02d}"

            # Get model name
            model = rec.get('model', 'onbekend')

            # Create item text with duration and model
            item_text = f"🎵 {rec['name']}\n📅 {rec['date']} • ⏱️ {duration_str} • 🤖 {model}"
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

        # Reset segment tracking
        self.segments_to_transcribe = []
        self.transcribed_segments = []
        self.is_transcribing_segment = False

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

        # Start recording with segment callback
        self.recorder.start_recording(segment_callback=self.on_segment_ready)
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

        # Get audio duration
        duration = self.recording_manager.get_audio_duration(self.current_audio_file)

        # Add to manager
        self.recording_manager.add_recording(
            self.current_audio_file,
            self.current_recording_id,
            name=recording_name,
            duration=duration,
            model=self.selected_model_name
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

    def on_segment_ready(self, segment_file, segment_num):
        """Called when a new 30-second segment is ready"""
        print(f"DEBUG: Segment {segment_num} ready: {segment_file}")
        self.segments_to_transcribe.append((segment_file, segment_num))

        # Start transcribing if not already doing so
        if not self.is_transcribing_segment:
            self.transcribe_next_segment()

    def transcribe_next_segment(self):
        """Transcribe the next segment in the queue"""
        if not self.segments_to_transcribe:
            self.is_transcribing_segment = False
            return

        # Get model
        model_name = self.selected_model_name
        if model_name not in self.loaded_models:
            # Model not loaded yet, wait
            print(f"DEBUG: Model {model_name} not loaded yet, waiting...")
            self.is_transcribing_segment = False
            return

        model = self.loaded_models[model_name]
        self.is_transcribing_segment = True

        # Get next segment
        segment_file, segment_num = self.segments_to_transcribe.pop(0)

        def worker():
            try:
                print(f"DEBUG: Transcribing segment {segment_num}: {segment_file}")
                result = model.transcribe(
                    segment_file,
                    language="nl",
                    task="transcribe",
                    fp16=False
                )

                segment_text = result.get('text', '').strip()
                print(f"DEBUG: Segment {segment_num} transcribed: {segment_text[:50]}...")

                # Emit signal with transcribed text
                self.segment_transcribed.emit(segment_text)

            except Exception as e:
                print(f"ERROR transcribing segment {segment_num}: {e}")
                import traceback
                traceback.print_exc()

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

    def remove_overlap(self, previous_text, new_text):
        """Remove overlapping text between segments"""
        if not previous_text or not new_text:
            return new_text

        # Split into words
        prev_words = previous_text.split()
        new_words = new_text.split()

        # Look for overlap at the end of previous and beginning of new
        # Check up to 50 words (covers ~15 seconds at normal speech rate)
        max_overlap = min(50, len(prev_words), len(new_words))

        best_overlap_length = 0
        for overlap_len in range(max_overlap, 0, -1):
            # Get last N words from previous text
            prev_tail = prev_words[-overlap_len:]
            # Get first N words from new text
            new_head = new_words[:overlap_len]

            # Calculate similarity (allow for some transcription variations)
            matches = sum(1 for p, n in zip(prev_tail, new_head) if p.lower() == n.lower())
            similarity = matches / overlap_len

            # If 70% or more words match, consider it an overlap
            if similarity >= 0.7:
                best_overlap_length = overlap_len
                print(f"DEBUG: Found overlap of {overlap_len} words with {similarity:.1%} similarity")
                break

        # Remove the overlapping portion from the new text
        if best_overlap_length > 0:
            deduplicated = " ".join(new_words[best_overlap_length:])
            print(f"DEBUG: Removed {best_overlap_length} overlapping words")
            return deduplicated
        else:
            return new_text

    def on_segment_transcribed(self, segment_text):
        """Handle segment transcription completion"""
        print(f"DEBUG: on_segment_transcribed called")

        # Remove overlap with previous segment
        if self.transcribed_segments:
            previous_text = self.transcribed_segments[-1]
            segment_text = self.remove_overlap(previous_text, segment_text)

        # Only add if there's text left after deduplication
        if segment_text.strip():
            self.transcribed_segments.append(segment_text)

        # Update UI with concatenated text
        full_text = " ".join(self.transcribed_segments)
        self.transcription_text.setPlainText(full_text)

        print(f"DEBUG: Updated transcription display ({len(self.transcribed_segments)} segments)")

        # Generate incremental summary with current transcription
        print(f"DEBUG: Generating incremental summary after segment")
        self.generate_summary(full_text)

        # Mark as not transcribing and process next segment
        self.is_transcribing_segment = False
        self.transcribe_next_segment()

        # Check if all segments are done
        if not self.segments_to_transcribe and not self.is_transcribing_segment:
            print(f"DEBUG: All segments transcribed, saving to database")
            # All segments complete - save transcription and model to database
            self.recording_manager.update_recording(
                self.current_recording_id,
                transcription=full_text,
                model=self.selected_model_name
            )
            # Refresh list to show updated model
            self.refresh_recording_list()
            print(f"DEBUG: Model {self.selected_model_name} saved for recording {self.current_recording_id}")

    def retranscribe_with_segments(self):
        """Split existing recording into segments and transcribe incrementally"""
        print(f"DEBUG: Starting segmented retranscription of {self.current_audio_file}")

        # Split audio file into 30-second segments with 15-second overlap
        def split_audio():
            try:
                import wave
                import numpy as np

                # Open the audio file
                with wave.open(self.current_audio_file, 'rb') as wf:
                    sample_rate = wf.getframerate()
                    num_channels = wf.getnchannels()
                    sample_width = wf.getsampwidth()
                    total_frames = wf.getnframes()

                    # Read all audio data
                    audio_data = wf.readframes(total_frames)

                # Calculate segment sizes using app settings
                segment_duration = self.segment_duration  # seconds
                overlap_duration = self.overlap_duration  # seconds
                frames_per_segment = int(sample_rate * segment_duration)
                frames_per_overlap = int(sample_rate * overlap_duration)
                bytes_per_frame = sample_width * num_channels

                # Create segments directory
                timestamp = Path(self.current_audio_file).stem.replace("recording_", "")
                segments_dir = Path(f"recordings/segments_{timestamp}")
                segments_dir.mkdir(parents=True, exist_ok=True)

                segment_num = 0
                offset = 0
                segment_files = []

                while offset < len(audio_data):
                    # Calculate segment boundaries
                    segment_start = offset
                    segment_end = min(offset + frames_per_segment * bytes_per_frame, len(audio_data))

                    # Extract segment data
                    segment_data = audio_data[segment_start:segment_end]

                    # Save segment
                    segment_filename = segments_dir / f"segment_{segment_num:03d}.wav"
                    with wave.open(str(segment_filename), 'wb') as seg_wf:
                        seg_wf.setnchannels(num_channels)
                        seg_wf.setsampwidth(sample_width)
                        seg_wf.setframerate(sample_rate)
                        seg_wf.writeframes(segment_data)

                    print(f"DEBUG: Created segment {segment_num}: {segment_filename}")
                    segment_files.append((str(segment_filename), segment_num))

                    # Move forward by (segment_duration - overlap_duration) seconds
                    offset += (frames_per_segment - frames_per_overlap) * bytes_per_frame
                    segment_num += 1

                # Queue segments for transcription
                self.segments_to_transcribe = segment_files
                print(f"DEBUG: Created {len(segment_files)} segments, starting transcription...")

                # Start transcribing
                self.transcribe_next_segment()

            except Exception as e:
                print(f"ERROR splitting audio: {e}")
                import traceback
                traceback.print_exc()

        # Run in thread
        thread = threading.Thread(target=split_audio, daemon=True)
        thread.start()

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

                # Transcribe with Whisper
                print(f"DEBUG: Starting Whisper transcription...")
                result = model.transcribe(
                    self.current_audio_file,
                    language="nl",
                    task="transcribe",
                    fp16=False
                )
                print(f"DEBUG: Transcription completed!")

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

    def on_transcription_complete(self, result):
        """Handle transcription completion in main thread (slot)"""
        print(f"DEBUG: on_transcription_complete called with result type: {type(result)}")
        self.progress_bar.setVisible(False)

        if "error" in result:
            print(f"DEBUG: Error in result: {result['error']}")
            self.status_label.setText(f"Fout: {result['error']}")
            self.status_bar.showMessage(f"Transcriptie fout: {result['error']}")
        else:
            # Get transcription text
            transcription_text = result.get("text", "")

            print(f"DEBUG: Setting transcription text (length={len(transcription_text)}): {transcription_text[:100]}...")

            # Update UI
            self.transcription_text.clear()
            self.transcription_text.setPlainText(transcription_text)

            print(f"DEBUG: Text set in UI, updating labels")
            self.status_label.setText("✅ Transcriptie voltooid")
            self.status_bar.showMessage("Transcriptie succesvol voltooid")

            # Update recording with transcription
            print(f"DEBUG: Updating recording in database")
            self.recording_manager.update_recording(
                self.current_recording_id,
                transcription=transcription_text,
                model=self.selected_model_name
            )

            # Refresh the recording list to show updated model
            self.refresh_recording_list()

            # Generate summary
            print(f"DEBUG: Generating summary")
            self.generate_summary(transcription_text)

        self.record_btn.setEnabled(True)
        print(f"DEBUG: on_transcription_complete finished")

    def generate_summary(self, text):
        """Generate a summary of the transcription using Azure OpenAI"""
        if not text or not text.strip():
            print("DEBUG: No text to summarize")
            return

        self.status_label.setText("Samenvatting genereren met AI...")

        def worker():
            try:
                print(f"DEBUG: Summary worker started")

                # Check if Azure client is available
                if not self.azure_client:
                    print("WARNING: Azure OpenAI client not available, skipping summary")
                    self.summary_complete.emit("Azure OpenAI niet beschikbaar voor samenvattingen")
                    return

                # Get model name from env
                model_name = os.getenv('AZURE_OPENAI_MODEL', 'gpt-4o')

                # Create prompt for Azure OpenAI using configured prompt
                prompt = f"{self.summary_prompt}\n\n{text}"

                print(f"DEBUG: Calling Azure OpenAI with model {model_name}")

                # Call Azure OpenAI
                response = self.azure_client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {"role": "system", "content": "Je bent een assistent die samenvattingen maakt van transcripties van vergaderingen en gesprekken in het Nederlands."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.7,
                    max_tokens=2000
                )

                # Extract summary from response
                summary = response.choices[0].message.content.strip()
                print(f"DEBUG: Summary generated by Azure OpenAI (length={len(summary)})")

                # Emit signal to update UI
                self.summary_complete.emit(summary)

            except Exception as e:
                print(f"ERROR generating summary: {e}")
                import traceback
                traceback.print_exc()
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

            # Clear transcription display
            self.transcription_text.clear()
            self.summary_text.clear()

            # Reset segment tracking
            self.segments_to_transcribe = []
            self.transcribed_segments = []
            self.is_transcribing_segment = False

            # Start segmented transcription
            self.status_bar.showMessage(f"Hertranscriberen van '{recording['name']}'...")
            self.retranscribe_with_segments()

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

    def apply_settings(self):
        """Apply settings from the Settings tab"""
        # Get values from UI
        segment_duration = self.segment_duration_spin.value()
        overlap_duration = self.overlap_duration_spin.value()
        summary_prompt = self.summary_prompt_text.toPlainText()

        # Validate: overlap must be less than segment duration
        if overlap_duration >= segment_duration:
            QMessageBox.warning(
                self,
                "Ongeldige Instellingen",
                f"Overlap ({overlap_duration}s) moet kleiner zijn dan de fragmentlengte ({segment_duration}s).\n\n"
                f"Pas de waardes aan zodat overlap < fragmentlengte."
            )
            return

        # Apply settings
        self.segment_duration = segment_duration
        self.overlap_duration = overlap_duration
        self.summary_prompt = summary_prompt

        # Update AudioRecorder settings
        self.recorder.segment_duration = segment_duration
        self.recorder.overlap_duration = overlap_duration

        # Show confirmation
        self.status_bar.showMessage(
            f"Instellingen toegepast: {segment_duration}s fragmenten, {overlap_duration}s overlap"
        )

        QMessageBox.information(
            self,
            "Instellingen Toegepast",
            f"De volgende instellingen zijn opgeslagen:\n\n"
            f"• Fragmentlengte: {segment_duration} seconden\n"
            f"• Overlap: {overlap_duration} seconden\n"
            f"• Samenvatting prompt aangepast\n\n"
            f"Deze worden gebruikt voor alle nieuwe opnames en hertranscripties."
        )

    def closeEvent(self, event):
        """Clean up on close"""
        print("DEBUG: closeEvent called, cleaning up...")

        # Stop recording if active
        if self.is_recording:
            print("DEBUG: Stopping active recording...")
            self.is_recording = False
            self.timer.stop()

        # Clean up recorder
        try:
            self.recorder.cleanup()
        except Exception as e:
            print(f"Error cleaning up recorder: {e}")

        # Stop any playback
        try:
            if self.playback_process and self.playback_process.poll() is None:
                self.playback_process.terminate()
                self.playback_process.wait()
        except Exception as e:
            print(f"Error stopping playback: {e}")

        print("DEBUG: Cleanup complete, accepting close event")
        event.accept()


def main():
    """Main application entry point"""
    import signal

    # Handle Ctrl+C gracefully
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    app = QApplication(sys.argv)
    app.setStyle('Fusion')

    # Set quit on last window closed
    app.setQuitOnLastWindowClosed(True)

    window = TranscriptionApp()
    window.show()

    # Run the application
    exit_code = app.exec()

    print("DEBUG: Application exiting cleanly")
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
