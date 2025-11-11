#!/usr/bin/env python3
"""
Audio Transcription Application with Whisper
Professional GUI for recording, transcribing, and summarizing audio with history
"""

import sys
import os
import wave
import threading
from datetime import datetime
from pathlib import Path

import whisper
import numpy as np
from openai import AzureOpenAI, OpenAI
import requests
import uvicorn
import torch

# Import custom modules
from audio_recorder import AudioRecorder
from recording_manager import RecordingManager, iso_duration_to_seconds, seconds_to_iso_duration
from logging_config import setup_logging, get_logger
from version import get_version_string

# Setup logging
logger = get_logger(__name__)

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


class TranscriptionApp(QMainWindow):
    """Main application window"""

    # Define signals for thread-safe communication
    transcription_complete = pyqtSignal(dict)
    summary_complete = pyqtSignal(str)
    model_loaded = pyqtSignal(str, object)  # (model_name, model_object)
    segment_transcribed = pyqtSignal(str, int)  # Signal for incremental transcription updates (text, segment_num)

    def __init__(self):
        super().__init__()
        self.recorder = AudioRecorder()
        self.recording_manager = RecordingManager()

        # Get base recordings directory from recorder
        self.base_recordings_dir = self.recorder.base_recordings_dir

        # Model caching: store loaded models
        self.loaded_models = {}  # {model_name: model_object}
        self.selected_model_name = "medium"  # Default selected model

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

        # Track retranscription metadata
        self.retranscribe_metadata = None  # Metadata for retranscription (if any)

        # Track pending recording name (set when recording stops)
        self.pending_recording_name = None

        # Track summary generation
        self.is_generating_summary = False  # Flag to track if currently generating summary
        self.pending_summary_needed = False  # Flag to indicate if a summary is needed after current one completes

        # Settings
        self.segment_duration = 10  # seconds
        self.overlap_duration = 5  # seconds

        # Timer for recording duration (needed even in tray-only mode)
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_timer)

        # Don't initialize UI - tray only mode
        # self.init_ui()
        self.init_tray_icon()
        # self.refresh_recording_list()

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

        # Add retranscribe action
        retranscribe_action = tray_menu.addAction("Hertranscriberen")
        if retranscribe_action is not None:
            retranscribe_action.triggered.connect(self.show_retranscribe_dialog)

        tray_menu.addSeparator()

        # Don't add show window action in tray-only mode
        # show_action = tray_menu.addAction("Toon Venster")
        # if show_action is not None:
        #     show_action.triggered.connect(self.show)

        # Add version info action
        version_action = tray_menu.addAction("Toon Versie")
        if version_action is not None:
            version_action.triggered.connect(self.show_version_info)

        tray_menu.addSeparator()

        # Add quit action
        quit_action = tray_menu.addAction("Afsluiten")
        if quit_action is not None:
            quit_action.triggered.connect(self.quit_application)

        self.tray_menu = tray_menu
        # Don't set context menu automatically - we'll handle it manually
        # self.tray_icon.setContextMenu(tray_menu)

        # Handle tray icon click
        self.tray_icon.activated.connect(self.on_tray_icon_activated)

        # Show the tray icon
        self.tray_icon.show()

        # Populate input devices in tray menu
        self.refresh_tray_input_devices()


    def on_tray_icon_activated(self, reason):
        """Handle tray icon activation (click)"""
        if reason == QSystemTrayIcon.ActivationReason.Trigger:  # Left click
            self.tray_toggle_recording()
        elif reason == QSystemTrayIcon.ActivationReason.Context:  # Right click / Control+click on macOS
            # Show context menu at cursor position
            from PyQt6.QtGui import QCursor
            self.tray_menu.popup(QCursor.pos())
        elif reason == QSystemTrayIcon.ActivationReason.MiddleClick:  # Middle click
            # Also show menu on middle click
            from PyQt6.QtGui import QCursor
            self.tray_menu.popup(QCursor.pos())

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
        def save_and_continue():
            try:
                self.current_audio_file, self.current_recording_id = self.recorder.stop_recording()

                # Auto-generate name based on timestamp
                recording_name = f"Opname {datetime.now().strftime('%Y-%m-%d %H:%M')}"

                # Store the recording name for later use
                self.pending_recording_name = recording_name

                # Show notification
                self.tray_icon.showMessage(
                    "Opname Opgeslagen",
                    f"Opname opgeslagen als '{recording_name}'",
                    QSystemTrayIcon.MessageIcon.Information,
                    2000
                )

                # Wait for all segments to be transcribed, then finalize
                logger.info(f"Recording stopped (tray mode), waiting for all segments to be transcribed...")
                self.check_and_finalize_recording()

            except Exception as e:
                logger.error(f"Error in tray save_and_continue: {e}", exc_info=True)

        # Delay the save operation to let audio thread cleanup
        QTimer.singleShot(100, save_and_continue)

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

        logger.debug(f"Model selection changed to: {model_name}")
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
            if hasattr(self, 'status_bar'):
                self.status_bar.showMessage(f"{model_name.capitalize()} model geselecteerd (reeds geladen)")
            if hasattr(self, 'status_label'):
                self.status_label.setText(f"✅ {model_name.capitalize()} model klaar")
        else:
            # Load model immediately
            if hasattr(self, 'status_bar'):
                self.status_bar.showMessage(f"{model_name.capitalize()} model wordt geladen...")
            if hasattr(self, 'status_label'):
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

        if hasattr(self, 'status_label'):
            self.status_label.setText(f"Whisper {model_name} model laden...")
        if hasattr(self, 'status_bar'):
            self.status_bar.showMessage(f"Whisper {model_name} model aan het laden ({model_sizes.get(model_name, '')})...")

        # Disable UI during loading
        if hasattr(self, 'record_btn'):
            self.record_btn.setEnabled(False)
        if hasattr(self, 'tiny_radio'):
            self.tiny_radio.setEnabled(False)
            self.small_radio.setEnabled(False)
            self.medium_radio.setEnabled(False)
            self.large_radio.setEnabled(False)

        def load_model():
            try:
                logger.info(f"Starting to load Whisper {model_name} model...")
                # Load model for CPU transcription
                model = whisper.load_model(model_name, device="cpu")
                logger.info(f"Whisper {model_name} model loaded successfully!")

                # Cache the model
                self.loaded_models[model_name] = model
                logger.debug(f"Model cached, emitting signal...")

                # Emit signal to handle in main thread
                self.model_loaded.emit(model_name, model)

            except Exception as e:
                logger.error(f"Error loading model: {e}", exc_info=True)
                self.model_loaded.emit(model_name, None)

        thread = threading.Thread(target=load_model, daemon=True)
        thread.start()

    def get_or_load_model(self, model_name):
        """Get model from cache or load it (lazy loading with caching)"""
        # Check if model is already cached
        if model_name in self.loaded_models:
            logger.debug(f"Using cached {model_name} model")
            # Immediately proceed with transcription
            self.start_transcription_with_model(self.loaded_models[model_name])
            return

        # Model not cached, need to load it
        logger.info(f"Loading {model_name} model for first time...")
        self.pending_transcription = True
        self.load_model_async(model_name)

    def on_model_loaded(self, model_name, model):
        """Handle model loaded signal (main thread)"""
        logger.debug(f"on_model_loaded called for {model_name}, model: {model is not None}")

        if model:
            if hasattr(self, 'status_label'):
                self.status_label.setText(f"✅ {model_name.capitalize()} model geladen")
            if hasattr(self, 'status_bar'):
                self.status_bar.showMessage(f"Whisper {model_name} model succesvol geladen en gecached")
        else:
            if hasattr(self, 'status_label'):
                self.status_label.setText(f"❌ {model_name.capitalize()} model laden mislukt")
            if hasattr(self, 'status_bar'):
                self.status_bar.showMessage(f"Fout bij laden van {model_name} model")

        # Re-enable UI
        if hasattr(self, 'tiny_radio'):
            self.enable_ui_after_model_load()

        # If there was a pending transcription, start it now
        if model and self.pending_transcription:
            logger.debug("Starting pending transcription...")
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
            # Format duration - handle both ISO format and legacy seconds format
            duration_value = rec.get('duration', 'PT0S')
            if isinstance(duration_value, str):
                # ISO duration format
                duration_seconds = iso_duration_to_seconds(duration_value)
            else:
                # Legacy format (seconds)
                duration_seconds = duration_value

            minutes = duration_seconds // 60
            seconds = duration_seconds % 60
            duration_str = f"{minutes}:{seconds:02d}"

            # Get Whisper model name
            whisper_model = rec.get('model', 'onbekend')

            # Create item text with duration, Whisper model, and summary model
            item_text = f"🎵 {rec['name']}\n📅 {rec['date']} • ⏱️ {duration_str} • 🤖 {whisper_model}"
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
        if hasattr(self, 'transcription_text'):
            self.transcription_text.clear()
        
        # Reset segment tracking
        self.segments_to_transcribe = []
        self.transcribed_segments = []
        self.is_transcribing_segment = False

        # Reset summary generation tracking
        self.is_generating_summary = False
        self.pending_summary_needed = False

        if hasattr(self, 'record_btn'):
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
        if hasattr(self, 'status_label'):
            self.status_label.setText("🔴 Opname bezig...")
        if hasattr(self, 'status_bar'):
            self.status_bar.showMessage("Opname gestart")

        # Start recording with segment callback
        self.recorder.start_recording(segment_callback=self.on_segment_ready)
        self.timer.start(1000)  # Update every second

        # Get the recording timestamp and create initial JSON file
        self.current_recording_id = self.recorder.recording_timestamp
        self.current_audio_file = str(self.base_recordings_dir / f"recording_{self.current_recording_id}" / f"recording_{self.current_recording_id}.wav")

        # Create initial recording entry in database
        recording_name = f"Opname {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        self.recording_manager.add_recording(
            self.current_audio_file,
            self.current_recording_id,
            name=recording_name,
            duration=0,  # Will be updated when recording stops
            model=self.selected_model_name,
            segment_duration=self.segment_duration,
            overlap_duration=self.overlap_duration
        )

        # Refresh list to show the new recording (disabled in tray-only mode)
        # self.refresh_recording_list()

        logger.info(f"Created initial JSON for recording {self.current_recording_id}")

    def stop_recording(self):
        """Stop audio recording and process"""
        self.is_recording = False
        self.timer.stop()

        if hasattr(self, 'record_btn'):
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
        if hasattr(self, 'status_label'):
            self.status_label.setText("Opname opslaan...")
        if hasattr(self, 'status_bar'):
            self.status_bar.showMessage("Opname gestopt, aan het opslaan...")

        # Force process events to handle UI updates
        if hasattr(self, 'transcription_text'):
            QApplication.processEvents()

        # Save recording in a thread-safe way
        def save_and_continue():
            try:
                self.current_audio_file, self.current_recording_id = self.recorder.stop_recording()
                # Use QTimer to safely show dialog after save completes
                QTimer.singleShot(200, self.ask_recording_name)
            except Exception as e:
                logger.error(f"Error in save_and_continue: {e}", exc_info=True)
                if hasattr(self, 'record_btn'):
                    self.record_btn.setEnabled(True)

        # Delay the save operation to let audio thread cleanup
        QTimer.singleShot(100, save_and_continue)

    def ask_recording_name(self):
        """Ask for recording name (called after stop_recording completes)"""
        # In tray-only mode, automatically generate a name
        if not hasattr(self, 'transcription_text'):
            # Tray-only mode - auto-generate name
            recording_name = f"Opname {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        else:
            # Ask for name (UI mode)
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

        # Store the recording name for later use
        self.pending_recording_name = recording_name

        # Wait for all segments to be transcribed, then finalize
        logger.info(f"Recording stopped, waiting for all segments to be transcribed...")
        self.check_and_finalize_recording()

    def check_and_finalize_recording(self):
        """Check if all segments are transcribed and finalize the recording"""
        # Check if all segments have been transcribed
        if self.segments_to_transcribe or self.is_transcribing_segment:
            # Still transcribing - wait a bit and check again
            logger.debug("Still transcribing segments, checking again in 1 second...")
            QTimer.singleShot(1000, self.check_and_finalize_recording)
            return

        logger.info("All segments transcribed, finalizing recording...")
        self.finalize_recording()

    def finalize_recording(self):
        """Finalize recording by combining transcriptions and creating JSON"""
        import wave

        # Combine all segment transcriptions
        final_transcription = self.combine_segment_transcriptions()

        # Check if transcription is empty
        if not final_transcription.strip():
            logger.info("Transcription is empty, deleting recording folder")
            # Delete the entire recording folder
            import shutil
            rec_dir = self.base_recordings_dir / f"recording_{self.current_recording_id}"
            if rec_dir.exists() and rec_dir.is_dir():
                try:
                    shutil.rmtree(rec_dir)
                    logger.info(f"Deleted empty recording folder: {rec_dir}")

                    # Show notification in tray-only mode
                    if hasattr(self, 'tray_icon'):
                        self.tray_icon.showMessage(
                            "Opname Verwijderd",
                            "Opname was leeg en is automatisch verwijderd",
                            QSystemTrayIcon.MessageIcon.Information,
                            2000
                        )
                except Exception as e:
                    logger.error(f"Failed to delete empty recording folder: {e}", exc_info=True)

            # Re-enable record button
            if hasattr(self, 'record_btn'):
                self.record_btn.setEnabled(True)
            return

        # Write final transcription file
        rec_dir = self.base_recordings_dir / f"recording_{self.current_recording_id}"
        transcription_file = rec_dir / f"transcription_{self.current_recording_id}.txt"
        try:
            with open(transcription_file, 'w', encoding='utf-8') as f:
                f.write(final_transcription)
            logger.info(f"Wrote final transcription file: {transcription_file}")
        except Exception as e:
            logger.error(f"Failed to write final transcription file: {e}", exc_info=True)

        # Get audio duration from the main recording file
        try:
            audio_file = rec_dir / f"recording_{self.current_recording_id}.wav"
            with wave.open(str(audio_file), 'rb') as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                duration_seconds = frames / float(rate)
        except Exception as e:
            logger.error(f"Failed to get audio duration: {e}")
            duration_seconds = 0

        # Parse date from recording ID
        from datetime import datetime
        try:
            date_obj = datetime.strptime(self.current_recording_id, "%Y%m%d_%H%M%S")
            date_iso = date_obj.strftime("%Y-%m-%d %H:%M:%S")
        except:
            date_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Create JSON with all metadata
        audio_file_path = str(rec_dir / f"recording_{self.current_recording_id}.wav")

        # Add recording to manager (this will create the JSON file)
        self.recording_manager.add_recording(
            audio_file=audio_file_path,
            timestamp=self.current_recording_id,
            name=self.pending_recording_name,
            transcription=final_transcription,
            summary="",
            duration=duration_seconds,
            model=self.selected_model_name,
            segment_duration=self.segment_duration,
            overlap_duration=self.overlap_duration
        )

        logger.info(f"Recording finalized: {self.pending_recording_name}")

        # Show notification
        if hasattr(self, 'tray_icon'):
            self.tray_icon.showMessage(
                "Opname Voltooid",
                f"'{self.pending_recording_name}' is opgeslagen en getranscribeerd",
                QSystemTrayIcon.MessageIcon.Information,
                2000
            )

        # Update status
        if hasattr(self, 'status_label'):
            self.status_label.setText("✅ Opname voltooid")
        if hasattr(self, 'status_bar'):
            self.status_bar.showMessage("Opname succesvol opgeslagen")

        # Re-enable record button
        if hasattr(self, 'record_btn'):
            self.record_btn.setEnabled(True)

    def update_timer(self):
        """Update recording timer display"""
        self.recording_time += 1
        minutes = self.recording_time // 60
        seconds = self.recording_time % 60
        if hasattr(self, 'timer_label'):
            self.timer_label.setText(f"{minutes:02d}:{seconds:02d}")

    def on_segment_ready(self, segment_file, segment_num):
        """Called when a new 30-second segment is ready"""
        logger.debug(f"Segment {segment_num} ready: {segment_file}")
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
            logger.warning(f"Model {model_name} not loaded yet, waiting...")
            self.is_transcribing_segment = False
            return

        model = self.loaded_models[model_name]
        self.is_transcribing_segment = True

        # Get next segment
        segment_file, segment_num = self.segments_to_transcribe.pop(0)

        def worker():
            try:
                logger.debug(f"Transcribing segment {segment_num}: {segment_file}")

                # Check if audio file has sufficient duration
                # Whisper fails with tensor errors on very short or empty audio
                try:
                    with wave.open(segment_file, 'rb') as wf:
                        frames = wf.getnframes()
                        rate = wf.getframerate()
                        duration = frames / float(rate)

                        # Minimum 0.1 seconds of audio required
                        if duration < 0.1:
                            logger.warning(f"Segment {segment_num} too short ({duration:.2f}s), skipping transcription")
                            self.segment_transcribed.emit("", segment_num)  # Emit empty text with segment number
                            return
                except Exception as audio_check_error:
                    logger.error(f"Error checking audio duration for segment {segment_num}: {audio_check_error}")
                    self.segment_transcribed.emit("", segment_num)  # Emit empty text on error with segment number
                    return

                # Use torch.no_grad() to prevent gradient computation and cache issues
                with torch.no_grad():
                    # Clear model decoder state to prevent KeyError in kv_cache
                    # This is crucial when transcribing multiple segments with the same model instance
                    # The KV cache can get corrupted between different transcribe() calls
                    try:
                        # Clear decoder cache if it exists
                        if hasattr(model, 'decoder'):
                            # Reset all blocks' kv_cache
                            for block in model.decoder.blocks:
                                if hasattr(block, 'attn') and hasattr(block.attn, 'kv_cache'):
                                    block.attn.kv_cache.clear()
                                if hasattr(block, 'cross_attn') and hasattr(block.cross_attn, 'kv_cache'):
                                    block.cross_attn.kv_cache.clear()
                    except Exception as cache_error:
                        logger.debug(f"Could not clear cache (non-critical): {cache_error}")

                    result = model.transcribe(
                        segment_file,
                        language="nl",
                        task="transcribe",
                        fp16=False,
                        verbose=False  # Suppress whisper output
                    )

                segment_text = result.get('text', '').strip()
                logger.debug(f"Segment {segment_num} transcribed: {segment_text[:50]}...")

                # Emit signal with transcribed text and segment number
                self.segment_transcribed.emit(segment_text, segment_num)

            except Exception as e:
                logger.error(f"Error transcribing segment {segment_num}: {e}", exc_info=True)
                # Emit empty text so the JSON still gets updated
                self.segment_transcribed.emit("", segment_num)

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
                logger.debug(f"Found overlap of {overlap_len} words with {similarity:.1%} similarity")
                break

        # Remove the overlapping portion from the new text
        if best_overlap_length > 0:
            deduplicated = " ".join(new_words[best_overlap_length:])
            logger.debug(f"Removed {best_overlap_length} overlapping words")
            return deduplicated
        else:
            return new_text

    def on_segment_transcribed(self, segment_text, segment_num):
        """Handle segment transcription completion"""
        logger.debug(f"on_segment_transcribed called for segment {segment_num}")

        # Store segment transcription with its number
        self.transcribed_segments.append(segment_text)

        # Save individual segment transcription to file (even if empty, to maintain numbering)
        if self.current_recording_id:
            try:
                rec_dir = self.base_recordings_dir / f"recording_{self.current_recording_id}"
                segments_dir = rec_dir / "segments"
                segments_dir.mkdir(parents=True, exist_ok=True)

                # Write individual segment transcription file using the actual segment number
                segment_transcription_file = segments_dir / f"transcription_{segment_num:03d}.txt"
                with open(segment_transcription_file, 'w', encoding='utf-8') as f:
                    f.write(segment_text)

                logger.debug(f"Saved segment transcription: {segment_transcription_file}")
            except Exception as e:
                logger.error(f"Failed to write segment transcription file: {e}", exc_info=True)

        # Update UI with concatenated text (for display only, not saved yet)
        full_text = " ".join(self.transcribed_segments)
        if hasattr(self, 'transcription_text'):
            self.transcription_text.setPlainText(full_text)

        logger.debug(f"Segment {segment_num} transcribed ({len(self.transcribed_segments)} total segments)")

        # Mark as not transcribing and process next segment
        self.is_transcribing_segment = False
        self.transcribe_next_segment()

        # Check if all segments are done
        if not self.segments_to_transcribe and not self.is_transcribing_segment:
            logger.info("All segments transcribed")

            # All segments transcribed - nothing to do here
            # Transcription files and JSON will be created when recording stops
            logger.info("All segments transcribed - waiting for recording to stop")

    def combine_segment_transcriptions(self):
        """Combine all segment transcription files into final transcription"""
        logger.info("Combining segment transcriptions...")

        rec_dir = self.base_recordings_dir / f"recording_{self.current_recording_id}"
        segments_dir = rec_dir / "segments"

        if not segments_dir.exists():
            logger.warning(f"Segments directory not found: {segments_dir}")
            return ""

        # Find all transcription files in segments folder
        transcription_files = sorted(segments_dir.glob("transcription_*.txt"))

        if not transcription_files:
            logger.warning("No segment transcription files found")
            return ""

        # Read all segment transcriptions
        segment_texts = []
        for trans_file in transcription_files:
            try:
                with open(trans_file, 'r', encoding='utf-8') as f:
                    text = f.read().strip()
                    if text:
                        segment_texts.append(text)
                logger.debug(f"Read segment transcription: {trans_file.name}")
            except Exception as e:
                logger.error(f"Failed to read {trans_file}: {e}")

        if not segment_texts:
            logger.warning("All segment transcriptions are empty")
            return ""

        # Remove overlap between consecutive segments
        combined_texts = []
        for i, text in enumerate(segment_texts):
            if i == 0:
                # First segment: add as-is
                combined_texts.append(text)
            else:
                # Remove overlap with previous segment
                previous_text = combined_texts[-1]
                deduplicated_text = self.remove_overlap(previous_text, text)
                if deduplicated_text.strip():
                    combined_texts.append(deduplicated_text)

        # Join all texts
        final_transcription = " ".join(combined_texts)
        logger.info(f"Combined {len(segment_texts)} segment transcriptions into final transcription ({len(final_transcription)} chars)")

        return final_transcription

    def retranscribe_with_segments(self):
        """Split existing recording into segments and transcribe incrementally"""
        logger.info(f"Starting segmented retranscription of {self.current_audio_file}")

        # Split audio file into 30-second segments with 15-second overlap
        def split_audio():
            try:
                import wave
                import numpy as np

                if not self.current_audio_file:
                    logger.error("No current audio file to split")
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

                    logger.debug(f"Created segment {segment_num}: {segment_filename}")
                    segment_files.append((str(segment_filename), segment_num))

                    # Move forward by (segment_duration - overlap_duration) seconds
                    offset += (frames_per_segment - frames_per_overlap) * bytes_per_frame
                    segment_num += 1

                # Queue segments for transcription
                self.segments_to_transcribe = segment_files
                logger.info(f"Created {len(segment_files)} segments, starting transcription...")

                # Start transcribing
                self.transcribe_next_segment()

            except Exception as e:
                logger.error(f"Error splitting audio: {e}", exc_info=True)

        # Run in thread
        thread = threading.Thread(target=split_audio, daemon=True)
        thread.start()

    def transcribe_audio(self):
        """Transcribe audio using Whisper"""
        logger.info(f"Starting transcription for file: {self.current_audio_file}")
        logger.debug(f"Selected model: {self.selected_model_name}")

        # Load model if needed, then transcribe
        self.get_or_load_model(self.selected_model_name)

    def start_transcription_with_model(self, model):
        """Start transcription with loaded model"""
        logger.debug("start_transcription_with_model called")

        if hasattr(self, 'progress_bar'):
            self.progress_bar.setVisible(True)
            self.progress_bar.setRange(0, 0)  # Indeterminate progress

        model_times = {
            "tiny": "5-10 seconden",
            "small": "15-30 seconden",
            "medium": "30-60 seconden",
            "large": "1-3 minuten"
        }

        time_estimate = model_times.get(self.selected_model_name, "enkele seconden")

        if hasattr(self, 'status_label'):
            self.status_label.setText(f"Transcriptie bezig (~{time_estimate})...")
        if hasattr(self, 'status_bar'):
            self.status_bar.showMessage(f"Audio wordt getranscribeerd...")

        # Force UI update
        if hasattr(self, 'transcription_text'):
            QApplication.processEvents()

        def worker():
            try:
                logger.debug(f"Worker thread started with {self.selected_model_name} model")

                # Transcribe with Whisper
                logger.info("Starting Whisper transcription...")
                result = model.transcribe(
                    self.current_audio_file,
                    language="nl",
                    task="transcribe",
                    fp16=False
                )
                logger.info("Transcription completed!")

                # Emit signal to update UI in main thread
                logger.debug("Emitting transcription_complete signal")
                self.transcription_complete.emit(result)
                logger.debug("Signal emitted successfully")

            except Exception as e:
                logger.error(f"Transcription error: {e}", exc_info=True)
                self.transcription_complete.emit({"error": str(e)})

        logger.debug("Creating worker thread...")
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        logger.debug("Worker thread started")

    def on_transcription_complete(self, result):
        """Handle transcription completion in main thread (slot)"""
        logger.debug(f"on_transcription_complete called with result type: {type(result)}")
        if hasattr(self, 'progress_bar'):
            self.progress_bar.setVisible(False)

        if "error" in result:
            logger.error(f"Error in result: {result['error']}")
            if hasattr(self, 'status_label'):
                self.status_label.setText(f"Fout: {result['error']}")
            if hasattr(self, 'status_bar'):
                self.status_bar.showMessage(f"Transcriptie fout: {result['error']}")
        else:
            # Get transcription text
            transcription_text = result.get("text", "")

            logger.debug(f"Setting transcription text (length={len(transcription_text)}): {transcription_text[:100]}...")

            # Update UI
            if hasattr(self, 'transcription_text'):
                self.transcription_text.clear()
                self.transcription_text.setPlainText(transcription_text)

            logger.debug("Text set in UI, updating labels")

            # Check if transcription is empty
            if not transcription_text.strip():
                logger.info("Transcription is empty, deleting recording folder")
                # Delete the entire recording folder
                import shutil
                rec_dir = self.base_recordings_dir / f"recording_{self.current_recording_id}"
                if rec_dir.exists() and rec_dir.is_dir():
                    try:
                        shutil.rmtree(rec_dir)
                        logger.info(f"Deleted empty recording folder: {rec_dir}")

                        # Remove from in-memory recordings list
                        self.recording_manager.recordings = [
                            rec for rec in self.recording_manager.recordings
                            if rec.get("id") != self.current_recording_id
                        ]

                        # Update status
                        if hasattr(self, 'status_label'):
                            self.status_label.setText("❌ Opname was leeg en is verwijderd")
                        if hasattr(self, 'status_bar'):
                            self.status_bar.showMessage("Opname was leeg en is automatisch verwijderd")

                        # Show notification in tray-only mode
                        if hasattr(self, 'tray_icon'):
                            self.tray_icon.showMessage(
                                "Opname Verwijderd",
                                "Opname was leeg en is automatisch verwijderd",
                                QSystemTrayIcon.MessageIcon.Information,
                                2000
                            )
                    except Exception as e:
                        logger.error(f"Failed to delete empty recording folder: {e}", exc_info=True)
            else:
                # Transcription is not empty - save it
                if hasattr(self, 'status_label'):
                    self.status_label.setText("✅ Transcriptie voltooid")
                if hasattr(self, 'status_bar'):
                    self.status_bar.showMessage("Transcriptie succesvol voltooid")

                # Check if this is a retranscription
                is_retranscription = hasattr(self, 'retranscribe_metadata') and self.retranscribe_metadata is not None

                if is_retranscription:
                    # Hertranscription: Write JSON and transcription file
                    logger.info("Completing retranscription - writing files")

                    # Update metadata with transcription
                    self.retranscribe_metadata['transcription'] = transcription_text

                    # Get recording directory
                    rec_dir = self.recording_manager.recordings_dir / f"recording_{self.current_recording_id}"
                    rec_dir.mkdir(parents=True, exist_ok=True)

                    # Write transcription text file
                    transcription_file = rec_dir / f"transcription_{self.current_recording_id}.txt"
                    try:
                        with open(transcription_file, 'w', encoding='utf-8') as f:
                            f.write(transcription_text)
                        logger.info(f"Wrote transcription file: {transcription_file}")
                    except Exception as e:
                        logger.error(f"Failed to write transcription file: {e}", exc_info=True)

                    # Check if recording exists in manager's list
                    existing_rec = self.recording_manager.get_recording(self.current_recording_id)
                    if existing_rec:
                        # Update existing recording
                        existing_rec.update(self.retranscribe_metadata)
                    else:
                        # Add new recording to the list
                        self.recording_manager.recordings.insert(0, self.retranscribe_metadata)

                    # Save JSON file
                    self.recording_manager.save_recording(self.retranscribe_metadata)
                    logger.info(f"Saved JSON metadata for recording {self.current_recording_id}")

                    # Show completion notification
                    if self.tray_icon:
                        recording_name = self.retranscribe_metadata.get('name', self.current_recording_id)
                        self.tray_icon.showMessage(
                            "Hertranscriptie Voltooid",
                            f"'{recording_name}' is succesvol hertranscribeerd met het {self.selected_model_name} model.",
                            QSystemTrayIcon.MessageIcon.Information,
                            3000
                        )

                    # Clear retranscribe metadata
                    self.retranscribe_metadata = None
                else:
                    # Normal transcription: Update recording with transcription, model, and all settings
                    logger.debug("Updating recording in database")
                    self.recording_manager.update_recording(
                        self.current_recording_id,
                        transcription=transcription_text,
                        model=self.selected_model_name,
                        segment_duration=self.segment_duration,
                        overlap_duration=self.overlap_duration
                    )

                # Refresh the recording list to show updated model (disabled in tray-only mode)
                # self.refresh_recording_list()



        if hasattr(self, 'record_btn'):
            self.record_btn.setEnabled(True)
        logger.debug("on_transcription_complete finished")

   
    def update_button_states(self):
        """Update button states based on selection"""
        selected_items = self.recording_list.selectedItems()
        num_selected = len(selected_items)

        if num_selected == 0:
            self.rename_btn.setEnabled(False)
            self.retranscribe_btn.setEnabled(False)
            self.delete_btn.setEnabled(False)
        elif num_selected == 1:
            self.rename_btn.setEnabled(True)
            self.retranscribe_btn.setEnabled(True)

            # Enable extract button only if transcription exists
            recording_id = selected_items[0].data(Qt.ItemDataRole.UserRole)
            recording = self.recording_manager.get_recording(recording_id)
            has_transcription = bool(recording and recording.get('transcription', '').strip())
            self.delete_btn.setEnabled(True)
        else:  # Multiple selections
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

            self.status_label.setText(f"Geladen: {recording['name']}")
            self.status_bar.showMessage(f"Opname en instellingen geladen: {recording['date']}")

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
            if hasattr(self, 'status_bar'):
                self.status_bar.showMessage("Audio apparaten ophalen...")

            # Get devices from the recorder
            devices = self.recorder.get_audio_devices()

            # Clear and populate the combo box (only if UI exists)
            if hasattr(self, 'audio_device_combo'):
                self.audio_device_combo.clear()

                # Add default device option
                self.audio_device_combo.addItem("Standaard (Systeem Default)", None)

                # Add all available input devices
                for device in devices:
                    device_name = device['name']
                    device_index = device['index']
                    self.audio_device_combo.addItem(device_name, device_index)

            if hasattr(self, 'status_bar'):
                self.status_bar.showMessage(f"{len(devices)} audio apparaten gevonden")
            logger.info(f"Found {len(devices)} audio input devices")

            # Also refresh tray menu
            self.refresh_tray_input_devices()

        except Exception as e:
            if hasattr(self, 'status_bar'):
                self.status_bar.showMessage(f"Fout bij ophalen audio apparaten: {str(e)}")
            logger.error(f"Failed to refresh audio devices: {e}", exc_info=True)

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


            logger.debug(f"Tray menu updated with {len(devices)} audio input devices")

        except Exception as e:
            logger.error(f"Failed to refresh tray input devices: {e}", exc_info=True)

    def set_tray_input_device(self, device_index):
        """Set the input device from the tray menu"""
        try:
            # Set the device on the recorder
            self.recorder.set_input_device(device_index)

            # Update the combo box in settings to match (only if UI exists)
            if hasattr(self, 'audio_device_combo'):
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

            logger.info(f"Input device set to: {device_name} (index: {device_index})")

        except Exception as e:
            logger.error(f"Failed to set tray input device: {e}", exc_info=True)

    def set_tray_model(self, model_name):
        """Set the transcription model from the tray menu"""
        try:
            logger.debug(f"Tray menu - changing model to: {model_name}")

            # Update the selected model
            self.selected_model_name = model_name

            # Update radio buttons in main window to match (only if UI exists)
            if hasattr(self, 'tiny_radio'):
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
                logger.debug(f"{model_name} model already loaded")
            else:
                # Model needs to be loaded
                self.tray_icon.showMessage(
                    "Model Laden",
                    f"{model_name.capitalize()} model wordt geladen...\nDit kan even duren.",
                    QSystemTrayIcon.MessageIcon.Information,
                    3000
                )
                logger.info(f"Loading {model_name} model...")
                self.load_model_async(model_name)

        except Exception as e:
            logger.error(f"Failed to set tray model: {e}", exc_info=True)

    
    def apply_settings(self):
        """Apply settings from the Settings tab"""
        # Get values from UI
        segment_duration = self.segment_duration_spin.value()
        overlap_duration = self.overlap_duration_spin.value()

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
       

        # Get audio device settings
        selected_device_index = self.audio_device_combo.currentData()

        # Update AudioRecorder settings
        self.recorder.segment_duration = segment_duration
        self.recorder.overlap_duration = overlap_duration
        self.recorder.set_input_device(selected_device_index)

        logger.info(f"Audio device set to index: {selected_device_index}")

        # Save settings to currently selected recording if one is loaded
        if self.current_recording_id:
            self.recording_manager.update_recording(
                self.current_recording_id,
                segment_duration=segment_duration,
                overlap_duration=overlap_duration
            )
            # Refresh list to show updated settings
            self.refresh_recording_list()
            logger.debug(f"Settings saved to recording {self.current_recording_id}")

        # Show confirmation
        status_msg = f"Instellingen toegepast: {segment_duration}s fragmenten, {overlap_duration}s overlap"
        if self.current_recording_id:
            status_msg += " (opgeslagen bij huidige opname)"
        self.status_bar.showMessage(status_msg)

        confirmation_msg = f"De volgende instellingen zijn opgeslagen:\n\n" \
                          f"• Fragmentlengte: {segment_duration} seconden\n" \
                          f"• Overlap: {overlap_duration} seconden\n\n" \
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
        """Handle window close - in tray-only mode, always clean up and quit"""
        # In tray-only mode, if close is called, clean up and quit
        self.cleanup_and_quit()
        event.accept()

    def show_version_info(self):
        """Show version information dialog"""
        from PyQt6.QtWidgets import QMessageBox

        version_text = get_version_string()

        msg = QMessageBox()
        msg.setWindowTitle("VoiceCapture Versie Informatie")
        msg.setText(version_text)
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()

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

            # Format display text
            display_text = f"{recording_name} - {recording_date}"
            if duration:
                display_text += f" ({duration})"

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

            selected_id = selected_items[0].data(Qt.ItemDataRole.UserRole)
            dialog.accept()

            # Start retranscription
            self.start_retranscription(selected_id)

        def on_cancel():
            dialog.reject()

        ok_button.clicked.connect(on_ok)
        cancel_button.clicked.connect(on_cancel)

        # Double-click to select
        list_widget.itemDoubleClicked.connect(on_ok)

        # Show dialog
        dialog.exec()

    def start_retranscription(self, recording_id):
        """Start retranscription of a recording with the current model"""
        import wave
        from datetime import datetime

        # Get recording
        recording = self.recording_manager.get_recording(recording_id)

        # Construct the audio file path
        rec_dir = self.recording_manager.recordings_dir / f"recording_{recording_id}"
        audio_file = rec_dir / f"recording_{recording_id}.wav"

        # Verify audio file exists
        if not audio_file.exists():
            QMessageBox.warning(None, "Fout", f"Audio bestand niet gevonden: {audio_file}")
            return

        logger.info(f"Starting retranscription of {recording_id} with model {self.selected_model_name}")

        # Get existing name if available
        existing_name = recording.get('name', '') if recording else ''

        # Parse date from folder name (recording_YYYYMMDD_HHMMSS)
        timestamp_str = recording_id
        try:
            date_obj = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
            date_iso = date_obj.strftime("%Y-%m-%d %H:%M:%S")
        except:
            date_iso = recording.get('date', datetime.now().strftime("%Y-%m-%d %H:%M:%S")) if recording else datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Get audio duration from file
        try:
            with wave.open(str(audio_file), 'rb') as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                duration_seconds = frames / float(rate)
                duration_iso = seconds_to_iso_duration(duration_seconds)
        except Exception as e:
            logger.error(f"Error getting audio duration: {e}")
            duration_iso = recording.get('duration', 'PT0S') if recording else 'PT0S'

        # Get segment settings (use existing if available, otherwise use app defaults)
        segment_duration = recording.get('segment_duration', self.segment_duration) if recording else self.segment_duration
        overlap_duration = recording.get('overlap_duration', self.overlap_duration) if recording else self.overlap_duration

        # Store metadata for later use (will be written after transcription completes)
        self.retranscribe_metadata = {
            'id': recording_id,
            'audio_file': str(audio_file),
            'name': existing_name,
            'date': date_iso,
            'duration': duration_iso,
            'model': self.selected_model_name,
            'segment_duration': segment_duration,
            'overlap_duration': overlap_duration
        }

        # Set current recording info for transcription
        self.current_audio_file = str(audio_file)
        self.current_recording_id = recording_id

        # Show notification
        if self.tray_icon:
            model_times = {
                "tiny": "5-10 seconden",
                "small": "15-30 seconden",
                "medium": "30-60 seconden",
                "large": "1-3 minuten"
            }
            time_estimate = model_times.get(self.selected_model_name, "enkele seconden")

            self.tray_icon.showMessage(
                "Hertranscriptie Gestart",
                f"Hertranscriberen van '{existing_name or recording_id}' met {self.selected_model_name} model (~{time_estimate})...",
                QSystemTrayIcon.MessageIcon.Information,
                3000
            )

        logger.info(f"Starting full file retranscription for {recording_id}")

        # Start full file transcription (not segmented)
        self.transcribe_audio()

    def quit_application(self):
        """Quit the application properly"""
        self.cleanup_and_quit()
        QApplication.quit()

    def cleanup_and_quit(self):
        """Clean up resources before quitting"""
        logger.info("cleanup_and_quit called")

        # Stop recording if active
        if self.is_recording:
            logger.info("Stopping active recording...")
            self.is_recording = False
            self.timer.stop()

        # Clean up recorder
        try:
            self.recorder.cleanup()
        except Exception as e:
            logger.error(f"Error cleaning up recorder: {e}", exc_info=True)

        logger.info("Cleanup complete")


def start_openapi_server():
    """Start OpenAPI server in a background thread"""
    try:
        # Import the FastAPI app
        from openapi_server import app

        # Configure uvicorn to run without access logs to reduce console clutter
        config = uvicorn.Config(
            app,
            host="0.0.0.0",
            port=8000,
            log_level="info",
            access_log=False
        )
        server = uvicorn.Server(config)

        logger.info("=" * 60)
        logger.info("🚀 OpenAPI Server Starting...")
        logger.info(f"   API URL: http://localhost:8000")
        logger.info(f"   Swagger UI: http://localhost:8000/docs")
        logger.info(f"   ReDoc: http://localhost:8000/redoc")
        logger.info(f"   OpenAPI Schema: http://localhost:8000/openapi.json")
        logger.info("=" * 60)

        # Run the server (this will block in this thread)
        server.run()
    except Exception as e:
        logger.error(f"Failed to start OpenAPI server: {e}", exc_info=True)


def main():
    """Main application entry point"""
    import signal
    import multiprocessing

    # Required for PyInstaller on macOS to prevent duplicate processes
    multiprocessing.freeze_support()

    # Initialize logging first
    setup_logging()

    # Log version information
    try:
        from version import get_version_info
        version_info = get_version_info()
        logger.info("=" * 60)
        logger.info("VoiceCapture Starting")
        logger.info("=" * 60)
        logger.info(f"Version: {version_info['commit_short']}")
        logger.info(f"Date: {version_info['date']}")
        logger.info(f"Branch: {version_info['branch']}")
        logger.info(f"Commit: {version_info['commit']}")
        if version_info['dirty']:
            logger.warning("Warning: Running with uncommitted changes")
        logger.info("=" * 60)
    except Exception as e:
        logger.info("=" * 60)
        logger.info("VoiceCapture Starting (Development Mode)")
        logger.info("=" * 60)
        logger.debug(f"Version info not available: {e}")

    # Fix PATH for bundled ffmpeg (cross-platform)
    if getattr(sys, 'frozen', False):
        # Running in a PyInstaller bundle
        bundle_dir = Path(getattr(sys, '_MEIPASS', '.'))

        # Platform-specific PATH handling
        if sys.platform == 'darwin':  # macOS
            # PyInstaller bundles ffmpeg in Contents/Frameworks on macOS
            path_separator = ':'
            new_paths = f"{bundle_dir}{path_separator}{bundle_dir.parent / 'Frameworks'}"
        elif sys.platform == 'win32':  # Windows
            # On Windows, ffmpeg should be in the same directory as the exe
            path_separator = ';'
            new_paths = str(bundle_dir)
        else:  # Linux
            path_separator = ':'
            new_paths = str(bundle_dir)

        os.environ['PATH'] = f"{new_paths}{path_separator}{os.environ.get('PATH', '')}"
        logger.info(f"Running as bundled app on {sys.platform}, updated PATH to include: {bundle_dir}")

    # Handle Ctrl+C gracefully
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    # Start OpenAPI server in background thread
    api_thread = threading.Thread(target=start_openapi_server, daemon=True, name="OpenAPI-Server")
    api_thread.start()
    logger.info("OpenAPI server thread started")

    app = QApplication(sys.argv)
    app.setStyle('Fusion')

    # Don't quit when last window closed (keeps tray icon running)
    app.setQuitOnLastWindowClosed(False)

    window = TranscriptionApp()
    # Don't show window in tray-only mode
    # window.show()

    # Run the application
    exit_code = app.exec()

    logger.info("Application exiting cleanly")
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
