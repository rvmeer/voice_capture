#!/usr/bin/env python3
"""
Audio Transcription Application with Whisper
Professional GUI for recording, transcribing, and summarizing audio with history
"""

import sys
import os
import wave
import threading
import subprocess
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

import whisper
import numpy as np
from openai import AzureOpenAI, OpenAI
import requests

# Load environment variables
load_dotenv()

# Import custom modules
from audio_recorder import AudioRecorder
from recording_manager import RecordingManager

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTextEdit, QLabel, QStatusBar, QProgressBar, QTabWidget,
    QListWidget, QListWidgetItem, QInputDialog, QMessageBox, QSplitter,
    QRadioButton, QButtonGroup, QGroupBox, QCheckBox, QSpinBox, QFormLayout,
    QComboBox, QLineEdit, QScrollArea, QSystemTrayIcon, QMenu
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QSize
from PyQt6.QtGui import QFont, QPalette, QColor, QIcon, QPainter, QPixmap, QPen, QActionGroup


def create_tray_icon(recording=False):
    """Create a tray icon - open circle when idle, filled red circle when recording"""
    # Create a 22x22 pixmap (standard size for macOS menu bar icons)
    pixmap = QPixmap(22, 22)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    if recording:
        # Filled red circle when recording
        painter.setBrush(QColor(244, 67, 54))  # Red color
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(3, 3, 16, 16)
    else:
        # Empty circle outline when idle
        pen = QPen(QColor(100, 100, 100))  # Dark gray
        pen.setWidth(2)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(3, 3, 16, 16)

    painter.end()
    return QIcon(pixmap)


class TranscriptionApp(QMainWindow):
    """Main application window"""

    # Define signals for thread-safe communication
    transcription_complete = pyqtSignal(dict)
    summary_complete = pyqtSignal(str)
    model_loaded = pyqtSignal(str, object)  # (model_name, model_object)
    segment_transcribed = pyqtSignal(str)  # Signal for incremental transcription updates
    ollama_models_loaded = pyqtSignal(list)  # Signal for Ollama models loaded

    def __init__(self):
        super().__init__()
        self.recorder = AudioRecorder()
        self.recording_manager = RecordingManager()

        # Model caching: store loaded models
        self.loaded_models = {}  # {model_name: model_object}
        self.selected_model_name = "small"  # Default selected model

        self.is_recording = False
        self.recording_time = 0
        self.current_audio_file = None
        self.current_recording_id = None
        self.playback_process = None

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

        # Track summary generation
        self.is_generating_summary = False  # Flag to track if currently generating summary
        self.pending_summary_needed = False  # Flag to indicate if a summary is needed after current one completes

        # Settings
        self.segment_duration = 10  # seconds
        self.overlap_duration = 5  # seconds
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

        # AI Provider settings
        self.ai_provider = "azure"  # "azure" or "ollama"
        self.ollama_url = "http://localhost:11434/v1"  # Default Ollama URL
        self.ollama_model = "llama2"  # Default Ollama model
        self.ollama_available_models = []  # Will be populated when Ollama is selected

        # Azure OpenAI client for summary generation
        self.azure_client = None
        self.ollama_client = None
        
        self.init_ui()
        self.init_tray_icon()
        self.refresh_recording_list()

        # Load default model (tiny) on startup
        QTimer.singleShot(500, lambda: self.load_model_async(self.selected_model_name))


    def init_tray_icon(self):
        """Initialize system tray icon"""
        # Create system tray icon
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(create_tray_icon(recording=False))

        # Create context menu for tray icon
        tray_menu = QMenu()

        # Add toggle recording action
        self.tray_toggle_action = tray_menu.addAction("Start Opname")
        if self.tray_toggle_action is not None:
            self.tray_toggle_action.triggered.connect(self.tray_toggle_recording)

        tray_menu.addSeparator()

        # Add transcription model selection submenu
        self.model_menu = QMenu("Transcription Model", tray_menu)
        self.model_action_group = QActionGroup(self.model_menu)
        self.model_action_group.setExclusive(True)

        # Add model options
        self.tray_tiny_action = self.model_menu.addAction("Tiny (Snel, ~1GB)")
        if self.tray_tiny_action is not None:
            self.tray_tiny_action.setCheckable(True)
            self.tray_tiny_action.triggered.connect(lambda: self.set_tray_model("tiny"))

            
        self.tray_small_action = self.model_menu.addAction("Small (Goed, ~2GB)")
        if self.tray_small_action is not None:
            self.tray_small_action.setCheckable(True)
            self.tray_small_action.triggered.connect(lambda: self.set_tray_model("small"))

        
        self.tray_medium_action = self.model_menu.addAction("Medium (Beter, ~5GB)")
        if self.tray_medium_action is not None:
            self.tray_medium_action.setCheckable(True)
            self.tray_medium_action.triggered.connect(lambda: self.set_tray_model("medium"))
        
        self.tray_large_action = self.model_menu.addAction("Large (Best, ~10GB)")
        if self.tray_large_action is not None:
            self.tray_large_action.setCheckable(True)
            self.tray_large_action.triggered.connect(lambda: self.set_tray_model("large"))

        if self.model_action_group is not None:
            self.model_action_group.addAction(self.tray_tiny_action)
            self.model_action_group.addAction(self.tray_small_action)
            self.model_action_group.addAction(self.tray_medium_action)
            self.model_action_group.addAction(self.tray_large_action)

        # Set initial selection based on current model
        if self.selected_model_name == "tiny":
            if self.tray_tiny_action is not None:
                self.tray_tiny_action.setChecked(True)
        elif self.selected_model_name == "small":
            if self.tray_small_action is not None:
                self.tray_small_action.setChecked(True)
        elif self.selected_model_name == "medium":
            if self.tray_medium_action is not None:
                self.tray_medium_action.setChecked(True)
        elif self.selected_model_name == "large":
            if self.tray_large_action is not None:
                self.tray_large_action.setChecked(True)

        tray_menu.addMenu(self.model_menu)

        tray_menu.addSeparator()

        # Add input device selection submenu
        self.input_menu = QMenu("Input Selection", tray_menu)
        self.input_action_group = QActionGroup(self.input_menu)
        self.input_action_group.setExclusive(True)

        # Will be populated by refresh_tray_input_devices()
        tray_menu.addMenu(self.input_menu)

        tray_menu.addSeparator()

        # Add show window action
        show_action = tray_menu.addAction("Toon Venster")
        if show_action is not None:
            show_action.triggered.connect(self.show)

        # Add quit action
        quit_action = tray_menu.addAction("Afsluiten")
        if quit_action is not None:
            quit_action.triggered.connect(self.quit_application)

        self.tray_icon.setContextMenu(tray_menu)

        # Handle tray icon click (left-click toggles recording)
        self.tray_icon.activated.connect(self.on_tray_icon_activated)

        # Show the tray icon
        self.tray_icon.show()

        # Populate input devices in tray menu
        self.refresh_tray_input_devices()


    def on_tray_icon_activated(self, reason):
        """Handle tray icon activation (click)"""
        if reason == QSystemTrayIcon.ActivationReason.Trigger:  # Left click
            self.tray_toggle_recording()

    def tray_toggle_recording(self):
        """Toggle recording from tray icon"""
        if not self.is_recording:
            self.tray_start_recording()
        else:
            self.tray_stop_recording()

    def tray_start_recording(self):
        """Start recording from tray icon (without showing dialog)"""
        # Start the recording
        self.start_recording()

        # Update tray icon to red filled circle
        self.tray_icon.setIcon(create_tray_icon(recording=True))
        if self.tray_toggle_action is not None:
            self.tray_toggle_action.setText("Stop Opname")

        # Show notification
        self.tray_icon.showMessage(
            "Opname Gestart",
            "Audio opname is gestart",
            QSystemTrayIcon.MessageIcon.Information,
            2000
        )

    def tray_stop_recording(self):
        """Stop recording from tray icon (auto-save without dialog)"""
        self.is_recording = False
        self.timer.stop()

        # Update tray icon back to empty circle
        self.tray_icon.setIcon(create_tray_icon(recording=False))
        if self.tray_toggle_action is not None:
            self.tray_toggle_action.setText("Start Opname")

        # Save recording in background
        def save_and_transcribe():
            try:
                self.current_audio_file, self.current_recording_id = self.recorder.stop_recording()

                # Auto-generate name based on timestamp
                recording_name = f"Opname {datetime.now().strftime('%Y-%m-%d %H:%M')}"

                # Get audio duration
                duration = self.recording_manager.get_audio_duration(self.current_audio_file)

                # Update existing recording with final name and duration
                self.recording_manager.update_recording(
                    self.current_recording_id,
                    name=recording_name,
                    duration=duration
                )

                # Refresh list
                self.refresh_recording_list()

                # Show notification
                self.tray_icon.showMessage(
                    "Opname Opgeslagen",
                    f"Opname opgeslagen als '{recording_name}'",
                    QSystemTrayIcon.MessageIcon.Information,
                    2000
                )

                # Start transcription in background
                self.transcribe_audio()

            except Exception as e:
                print(f"Error in tray save_and_transcribe: {e}")
                import traceback
                traceback.print_exc()

        # Delay the save operation to let audio thread cleanup
        QTimer.singleShot(100, save_and_transcribe)

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

        left_layout.addLayout(list_btn_layout2)

        # List action buttons - Row 3
        list_btn_layout3 = QHBoxLayout()
        list_btn_layout3.setSpacing(10)

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
        self.tiny_radio.toggled.connect(lambda: self.on_model_changed("tiny") if self.tiny_radio.isChecked() else None)
        self.model_button_group.addButton(self.tiny_radio)
        model_layout.addWidget(self.tiny_radio)

        self.small_radio = QRadioButton("Small (Goed, ~2GB)")
        self.small_radio.setChecked(True)
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

    
        # Settings tab with scroll area
        settings_widget = QWidget()
        settings_main_layout = QVBoxLayout(settings_widget)
        settings_main_layout.setContentsMargins(0, 0, 0, 0)
        settings_main_layout.setSpacing(0)

        # Create scroll area
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)

        # Create content widget for scroll area
        settings_content = QWidget()
        settings_layout = QVBoxLayout(settings_content)
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


        # Audio Input Device selection
        self.audio_device_combo = QComboBox()
        self.audio_device_combo.setStyleSheet("QComboBox { padding: 8px; font-size: 13px; }")
        form_layout.addRow("Audio Invoerapparaat:", self.audio_device_combo)

        # Refresh audio devices button
        refresh_audio_btn = QPushButton("🔄 Audio Apparaten Ophalen")
        refresh_audio_btn.clicked.connect(self.refresh_audio_devices)
        form_layout.addRow("", refresh_audio_btn)

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

        # Set the content widget in the scroll area
        scroll_area.setWidget(settings_content)

        # Add scroll area to main settings layout
        settings_main_layout.addWidget(scroll_area)

        self.tabs.addTab(transcription_widget, "Transcriptie")
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

        # Load audio devices after status bar is created
        self.refresh_audio_devices()

    def on_model_changed(self, model_name):
        """Handle model selection change"""
        if model_name == self.selected_model_name:
            return  # No change

        print(f"DEBUG: Model selection changed to: {model_name}")
        self.selected_model_name = model_name

        # Update tray menu checkmarks if tray icon exists
        if hasattr(self, 'tray_tiny_action'):
            if self.tray_tiny_action is not None:
                self.tray_tiny_action.setChecked(model_name == "tiny")
            if self.tray_small_action is not None:
                self.tray_small_action.setChecked(model_name == "small")
            if self.tray_medium_action is not None:
                self.tray_medium_action.setChecked(model_name == "medium")
            if self.tray_large_action is not None:
                self.tray_large_action.setChecked(model_name == "large")

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

            # Get Whisper model name
            whisper_model = rec.get('model', 'onbekend')

            # Get AI provider and model for summary
            ai_provider = rec.get('ai_provider', 'azure')
            if ai_provider == 'ollama':
                ollama_model = rec.get('ollama_model', 'onbekend')
                summary_model = f"Ollama ({ollama_model})"
            else:
                summary_model = "Azure OpenAI"

            # Create item text with duration, Whisper model, and summary model
            item_text = f"🎵 {rec['name']}\n📅 {rec['date']} • ⏱️ {duration_str} • 🤖 {whisper_model} • 📊 {summary_model}"
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
        
        # Reset segment tracking
        self.segments_to_transcribe = []
        self.transcribed_segments = []
        self.is_transcribing_segment = False

        # Reset summary generation tracking
        self.is_generating_summary = False
        self.pending_summary_needed = False

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

        # Get the recording timestamp and create initial JSON file
        self.current_recording_id = self.recorder.recording_timestamp
        self.current_audio_file = f"recordings/recording_{self.current_recording_id}/recording_{self.current_recording_id}.wav"

        # Create initial recording entry in database
        recording_name = f"Opname {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        self.recording_manager.add_recording(
            self.current_audio_file,
            self.current_recording_id,
            name=recording_name,
            duration=0,  # Will be updated when recording stops
            model=self.selected_model_name,
            ai_provider=self.ai_provider,
            segment_duration=self.segment_duration,
            overlap_duration=self.overlap_duration,
            ollama_url=self.ollama_url,
            ollama_model=self.ollama_model,
            summary_prompt=self.summary_prompt
        )

        # Refresh list to show the new recording
        self.refresh_recording_list()

        print(f"DEBUG: Created initial JSON for recording {self.current_recording_id}")

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

        # Update existing recording with final name and duration
        self.recording_manager.update_recording(
            self.current_recording_id,
            name=recording_name,
            duration=duration
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

        # Write incremental transcription to file (both TXT and update JSON)
        if self.current_recording_id and full_text.strip():
            try:
                rec_dir = Path(f"recordings/recording_{self.current_recording_id}")
                transcription_file = rec_dir / f"transcription_{self.current_recording_id}.txt"

                # Write TXT file
                with open(transcription_file, 'w', encoding='utf-8') as f:
                    f.write(full_text)

                print(f"DEBUG: Updated transcription file: {transcription_file}")

                # Update JSON file with current transcription
                self.recording_manager.update_recording(
                    self.current_recording_id,
                    transcription=full_text
                )

                print(f"DEBUG: Updated JSON with incremental transcription")
            except Exception as e:
                print(f"ERROR: Failed to write transcription file: {e}")

        print(f"DEBUG: Updated transcription display ({len(self.transcribed_segments)} segments)")

        # Mark as not transcribing and process next segment
        self.is_transcribing_segment = False
        self.transcribe_next_segment()

        # Check if all segments are done
        if not self.segments_to_transcribe and not self.is_transcribing_segment:
            print(f"DEBUG: All segments transcribed, saving to database")
            # All segments complete - save transcription, model, and all settings to database
            self.recording_manager.update_recording(
                self.current_recording_id,
                transcription=full_text,
                model=self.selected_model_name,
                ai_provider=self.ai_provider,
                segment_duration=self.segment_duration,
                overlap_duration=self.overlap_duration,
                ollama_url=self.ollama_url,
                ollama_model=self.ollama_model,
                summary_prompt=self.summary_prompt
            )
            # Refresh list to show updated model and settings
            self.refresh_recording_list()
            print(f"DEBUG: Model {self.selected_model_name} and all settings saved for recording {self.current_recording_id}")


    def retranscribe_with_segments(self):
        """Split existing recording into segments and transcribe incrementally"""
        print(f"DEBUG: Starting segmented retranscription of {self.current_audio_file}")

        # Split audio file into 30-second segments with 15-second overlap
        def split_audio():
            try:
                import wave
                import numpy as np

                if not self.current_audio_file:
                    print("ERROR: No current audio file to split")
                    return

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

                # Create segments directory inside the recording folder
                # Extract timestamp from the audio file path
                audio_path = Path(self.current_audio_file)
                # The parent directory should be recording_<timestamp>
                rec_dir = audio_path.parent
                segments_dir = rec_dir / "segments"
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

            # Update recording with transcription, model, and all settings
            print(f"DEBUG: Updating recording in database")
            self.recording_manager.update_recording(
                self.current_recording_id,
                transcription=transcription_text,
                model=self.selected_model_name,
                ai_provider=self.ai_provider,
                segment_duration=self.segment_duration,
                overlap_duration=self.overlap_duration,
                ollama_url=self.ollama_url,
                ollama_model=self.ollama_model,
                summary_prompt=self.summary_prompt
            )

            # Refresh the recording list to show updated model
            self.refresh_recording_list()

            

        self.record_btn.setEnabled(True)
        print(f"DEBUG: on_transcription_complete finished")

   
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

            # Enable extract button only if transcription exists
            recording_id = selected_items[0].data(Qt.ItemDataRole.UserRole)
            recording = self.recording_manager.get_recording(recording_id)
            has_transcription = bool(recording and recording.get('transcription', '').strip())
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
            transcription = recording.get('transcription', '')
            self.transcription_text.setPlainText(transcription)
            
            # Load all settings from the recording
            # Whisper model
            saved_model = recording.get('model', 'small')
            self.selected_model_name = saved_model

            # Update radio button selection
            if saved_model == 'tiny':
                self.tiny_radio.setChecked(True)
            elif saved_model == 'small':
                self.small_radio.setChecked(True)
            elif saved_model == 'medium':
                self.medium_radio.setChecked(True)
            elif saved_model == 'large':
                self.large_radio.setChecked(True)

            # Load segment settings
            self.segment_duration = recording.get('segment_duration', 30)
            self.overlap_duration = recording.get('overlap_duration', 15)
            self.segment_duration_spin.setValue(self.segment_duration)
            self.overlap_duration_spin.setValue(self.overlap_duration)

            # Update recorder settings
            self.recorder.segment_duration = self.segment_duration
            self.recorder.overlap_duration = self.overlap_duration

            # Initialize Ollama client if needed
            if self.ai_provider == "ollama" and self.ollama_url:
                try:
                    self.ollama_client = OpenAI(
                        base_url=self.ollama_url,
                        api_key="ollama"
                    )
                except Exception as e:
                    print(f"Warning: Could not initialize Ollama client: {e}")

            self.status_label.setText(f"Geladen: {recording['name']}")
            self.status_bar.showMessage(f"Opname en instellingen geladen: {recording['date']}")

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
            if not recording:
                return
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
                    # Delete entire recording folder
                    audio_file = Path(recording['audio_file'])
                    rec_dir = audio_file.parent  # Get the recording_<timestamp> folder

                    if rec_dir.exists() and rec_dir.is_dir():
                        try:
                            import shutil
                            shutil.rmtree(rec_dir)
                            print(f"DEBUG: Deleted recording folder: {rec_dir}")
                        except Exception as e:
                            print(f"Error deleting recording folder: {e}")

                    # Remove from in-memory list
                    self.recording_manager.recordings.remove(recording)
                    deleted_count += 1

            # Clear current selection if it was deleted
            if self.current_recording_id in [item.data(Qt.ItemDataRole.UserRole) for item in selected_items]:
                self.current_recording_id = None
                self.current_audio_file = None
                self.transcription_text.clear()

            # Refresh list
            self.refresh_recording_list()

            # Update status
            if deleted_count == 1:
                self.status_bar.showMessage("Opname verwijderd")
            else:
                self.status_bar.showMessage(f"{deleted_count} opnames verwijderd")

   
   
    def refresh_audio_devices(self):
        """Refresh the list of available audio input devices"""
        try:
            self.status_bar.showMessage("Audio apparaten ophalen...")

            # Get devices from the recorder
            devices = self.recorder.get_audio_devices()

            # Clear and populate the combo box
            self.audio_device_combo.clear()

            # Add default device option
            self.audio_device_combo.addItem("Standaard (Systeem Default)", None)

            # Add all available input devices
            for device in devices:
                device_name = device['name']
                device_index = device['index']
                self.audio_device_combo.addItem(device_name, device_index)

            self.status_bar.showMessage(f"{len(devices)} audio apparaten gevonden")
            print(f"DEBUG: Found {len(devices)} audio input devices")

            # Also refresh tray menu
            self.refresh_tray_input_devices()

        except Exception as e:
            self.status_bar.showMessage(f"Fout bij ophalen audio apparaten: {str(e)}")
            print(f"ERROR: Failed to refresh audio devices: {e}")
            import traceback
            traceback.print_exc()

    def refresh_tray_input_devices(self):
        """Refresh the input device list in the tray menu"""
        # Check if tray icon is initialized
        if not hasattr(self, 'input_menu'):
            return

        try:
            # Clear existing actions
            self.input_menu.clear()

            # Get devices from the recorder
            devices = self.recorder.get_audio_devices()

            # Get current device index
            current_device = self.recorder.input_device_index

            # Add default device option
            default_action = self.input_menu.addAction("Standaard (Systeem Default)")
            if default_action is not None:
                default_action.setCheckable(True)
                default_action.setData(None)
                default_action.triggered.connect(lambda checked, idx=None: self.set_tray_input_device(idx))
                self.input_action_group.addAction(default_action)

                # Check default if no device is selected
                if current_device is None:
                    default_action.setChecked(True)

            

            # Add separator
            self.input_menu.addSeparator()

            # Add all available input devices
            for device in devices:
                device_name = device['name']
                device_index = device['index']

                action = self.input_menu.addAction(device_name)
                if action is not None:
                    action.setCheckable(True)
                    action.setData(device_index)
                    action.triggered.connect(lambda checked, idx=device_index: self.set_tray_input_device(idx))
                    self.input_action_group.addAction(action)

                    # Check if this is the current device
                    if current_device == device_index:
                        action.setChecked(True)


            print(f"DEBUG: Tray menu updated with {len(devices)} audio input devices")

        except Exception as e:
            print(f"ERROR: Failed to refresh tray input devices: {e}")
            import traceback
            traceback.print_exc()

    def set_tray_input_device(self, device_index):
        """Set the input device from the tray menu"""
        try:
            # Set the device on the recorder
            self.recorder.set_input_device(device_index)

            # Update the combo box in settings to match
            for i in range(self.audio_device_combo.count()):
                if self.audio_device_combo.itemData(i) == device_index:
                    self.audio_device_combo.setCurrentIndex(i)
                    break

            # Show notification
            device_name = "Standaard (Systeem Default)" if device_index is None else f"Device {device_index}"
            # Try to get the actual device name
            if device_index is not None:
                devices = self.recorder.get_audio_devices()
                for device in devices:
                    if device['index'] == device_index:
                        device_name = device['name']
                        break

            self.tray_icon.showMessage(
                "Input Device Gewijzigd",
                f"Audio input ingesteld op:\n{device_name}",
                QSystemTrayIcon.MessageIcon.Information,
                2000
            )

            print(f"DEBUG: Input device set to: {device_name} (index: {device_index})")

        except Exception as e:
            print(f"ERROR: Failed to set tray input device: {e}")
            import traceback
            traceback.print_exc()

    def set_tray_model(self, model_name):
        """Set the transcription model from the tray menu"""
        try:
            print(f"DEBUG: Tray menu - changing model to: {model_name}")

            # Update the selected model
            self.selected_model_name = model_name

            # Update radio buttons in main window to match
            if model_name == "tiny":
                self.tiny_radio.setChecked(True)
            elif model_name == "small":
                self.small_radio.setChecked(True)
            elif model_name == "medium":
                self.medium_radio.setChecked(True)
            elif model_name == "large":
                self.large_radio.setChecked(True)

            # Update tray menu checkmarks
            if self.tray_tiny_action is not None:
                self.tray_tiny_action.setChecked(model_name == "tiny")
            if self.tray_small_action is not None:
                self.tray_small_action.setChecked(model_name == "small")
            if self.tray_medium_action is not None:
                self.tray_medium_action.setChecked(model_name == "medium")
            if self.tray_large_action is not None:
                self.tray_large_action.setChecked(model_name == "large")

            # Check if model is already loaded
            if model_name in self.loaded_models:
                self.tray_icon.showMessage(
                    "Model Geselecteerd",
                    f"{model_name.capitalize()} model geselecteerd\n(reeds geladen)",
                    QSystemTrayIcon.MessageIcon.Information,
                    2000
                )
                print(f"DEBUG: {model_name} model already loaded")
            else:
                # Model needs to be loaded
                self.tray_icon.showMessage(
                    "Model Laden",
                    f"{model_name.capitalize()} model wordt geladen...\nDit kan even duren.",
                    QSystemTrayIcon.MessageIcon.Information,
                    3000
                )
                print(f"DEBUG: Loading {model_name} model...")
                self.load_model_async(model_name)

        except Exception as e:
            print(f"ERROR: Failed to set tray model: {e}")
            import traceback
            traceback.print_exc()

    
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
       

        # Get audio device settings
        selected_device_index = self.audio_device_combo.currentData()

        # Update AudioRecorder settings
        self.recorder.segment_duration = segment_duration
        self.recorder.overlap_duration = overlap_duration
        self.recorder.set_input_device(selected_device_index)

        print(f"DEBUG: Audio device set to index: {selected_device_index}")

        # Save settings to currently selected recording if one is loaded
        if self.current_recording_id:
            self.recording_manager.update_recording(
                self.current_recording_id,
                segment_duration=segment_duration,
                overlap_duration=overlap_duration,
                summary_prompt=summary_prompt
            )
            # Refresh list to show updated settings
            self.refresh_recording_list()
            print(f"DEBUG: Settings saved to recording {self.current_recording_id}")

        # Show confirmation
        status_msg = f"Instellingen toegepast: {segment_duration}s fragmenten, {overlap_duration}s overlap"
        if self.current_recording_id:
            status_msg += " (opgeslagen bij huidige opname)"
        self.status_bar.showMessage(status_msg)

        confirmation_msg = f"De volgende instellingen zijn opgeslagen:\n\n" \
                          f"• Fragmentlengte: {segment_duration} seconden\n" \
                          f"• Overlap: {overlap_duration} seconden\n" \
                          f"• Samenvatting prompt aangepast\n\n" \
                          f"Deze worden gebruikt voor alle nieuwe opnames en hertranscripties."

        if self.current_recording_id:
            recording = self.recording_manager.get_recording(self.current_recording_id)
            if recording:
                confirmation_msg += f"\n\nDe instellingen zijn ook opgeslagen bij de geselecteerde opname:\n'{recording['name']}'"

        QMessageBox.information(
            self,
            "Instellingen Toegepast",
            confirmation_msg
        )

    def closeEvent(self, event):
        """Handle window close - minimize to tray instead of quitting"""
        # If tray icon exists, minimize to tray instead of closing
        if hasattr(self, 'tray_icon') and self.tray_icon.isVisible():
            self.hide()
            event.ignore()
            # Show notification
            self.tray_icon.showMessage(
                "Applicatie Verborgen",
                "De applicatie draait nog in de achtergrond. Klik op het icoon om het venster te tonen.",
                QSystemTrayIcon.MessageIcon.Information,
                2000
            )
        else:
            # Actually closing - clean up
            self.cleanup_and_quit()
            event.accept()

    def quit_application(self):
        """Quit the application properly"""
        self.cleanup_and_quit()
        QApplication.quit()

    def cleanup_and_quit(self):
        """Clean up resources before quitting"""
        print("DEBUG: cleanup_and_quit called")

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

        print("DEBUG: Cleanup complete")


def main():
    """Main application entry point"""
    import signal

    # Handle Ctrl+C gracefully
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    app = QApplication(sys.argv)
    app.setStyle('Fusion')

    # Don't quit when last window closed (keeps tray icon running)
    app.setQuitOnLastWindowClosed(False)

    window = TranscriptionApp()
    window.show()

    # Run the application
    exit_code = app.exec()

    print("DEBUG: Application exiting cleanly")
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
