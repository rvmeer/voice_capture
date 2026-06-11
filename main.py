#!/usr/bin/env python3
"""
Voice Capture - Tray-Only Application
Clean implementation using composition pattern with tray_actions
"""

import sys
import json
import queue
import signal
import threading
import shutil
import platform
import subprocess
import time
from datetime import datetime
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler

INTERNAL_API_PORT = 5151

import whisper
import torch
from PyQt6.QtWidgets import (
    QApplication, QSystemTrayIcon, QMenu, QMessageBox,
    QDialog, QVBoxLayout, QListWidget, QPushButton, QLabel, QHBoxLayout, QListWidgetItem
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QIcon, QPainter, QPixmap, QPen, QColor, QActionGroup, QCursor, QKeySequence

# Import custom modules
from audio_recorder import AudioRecorder
from recording_manager import RecordingManager
from logging_config import setup_logging, get_logger
try:
    from version import get_version_string
except ImportError:
    def get_version_string():
        return "unknown"
from transcription_utils import remove_overlap, is_empty_segment
from tray_actions import TrayActions
import ollama_utils
from transcribe_server import start_transcribe_server_in_background
from qdrant import QdrantIndexer, QdrantUnavailableError

try:
    from pynput import keyboard as pynput_keyboard
except ImportError:
    pynput_keyboard = None

# Setup logging
logger = get_logger(__name__)


def check_ffmpeg():
    """Check if ffmpeg is installed and accessible."""
    if shutil.which("ffmpeg") is not None:
        return True

    # ffmpeg not found - show error message
    system = platform.system()

    if system == "Windows":
        message = """ffmpeg is niet geïnstalleerd of niet gevonden in PATH.

Voice Capture heeft ffmpeg nodig voor audio verwerking.

Installeer ffmpeg via een van deze methodes:

1. Via winget (aanbevolen):
   Open een terminal en voer uit:
   winget install ffmpeg

2. Handmatig:
   - Download van https://www.gyan.dev/ffmpeg/builds/
   - Pak uit naar C:\\ffmpeg
   - Voeg C:\\ffmpeg\\bin toe aan je PATH

Na installatie: herstart deze applicatie."""

    elif system == "Darwin":  # macOS
        message = """ffmpeg is niet geïnstalleerd of niet gevonden in PATH.

Voice Capture heeft ffmpeg nodig voor audio verwerking.

Installeer ffmpeg via Homebrew:
   brew install ffmpeg

Als je Homebrew niet hebt:
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

Na installatie: herstart deze applicatie."""

    else:  # Linux
        message = """ffmpeg is niet geïnstalleerd of niet gevonden in PATH.

Voice Capture heeft ffmpeg nodig voor audio verwerking.

Installeer ffmpeg via je package manager:

Ubuntu/Debian:  sudo apt install ffmpeg
Fedora:         sudo dnf install ffmpeg
Arch:           sudo pacman -S ffmpeg

Na installatie: herstart deze applicatie."""

    print(f"\n{'='*60}\nFOUT: ffmpeg niet gevonden\n{'='*60}\n{message}\n{'='*60}\n",
          file=sys.stderr)
    logger.error("ffmpeg not found - required for audio processing")

    return False


def create_tray_icon(recording=False, level=0.0, pulse_phase=0):
    """Create a tray icon.

    Idle: white open circle.
    Recording: white ring + animated red center based on input level.
    """
    # Create a 22x22 pixmap (standard size for macOS menu bar icons)
    pixmap = QPixmap(22, 22)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    if recording:
        # Outer white ring
        pen = QPen(QColor(255, 255, 255))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(2, 2, 18, 18)

        # Animated red center reacting to live input level
        clamped = max(0.0, min(1.0, float(level)))
        pulse = 0.6 if (pulse_phase % 2 == 0) else 1.0

        # Radius between 4 and 7 px depending on level + subtle pulse
        radius = 4 + int(round(3 * clamped * pulse))
        alpha = 180 + int(75 * clamped)

        painter.setBrush(QColor(244, 67, 54, alpha))
        painter.setPen(Qt.PenStyle.NoPen)
        diameter = radius * 2
        top_left = 11 - radius
        painter.drawEllipse(top_left, top_left, diameter, diameter)
    else:
        # White open circle outline when idle
        pen = QPen(QColor(255, 255, 255))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(3, 3, 16, 16)

    painter.end()
    return QIcon(pixmap)


class CommandBridge(QObject):
    """Thread-safe bridge to run callbacks on the Qt main thread via signals"""
    _trigger = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._queue = queue.Queue()
        self._trigger.connect(self._process, Qt.ConnectionType.QueuedConnection)

    def run(self, func, timeout=5):
        result_event = threading.Event()
        result_container = [None]

        def wrapper():
            try:
                result_container[0] = func()
            except Exception as e:
                result_container[0] = {"error": str(e)}
            finally:
                result_event.set()

        self._queue.put(wrapper)
        self._trigger.emit()
        result_event.wait(timeout=timeout)
        return result_container[0]

    def _process(self):
        try:
            self._queue.get_nowait()()
        except queue.Empty:
            pass


class RecordingAPIHandler(BaseHTTPRequestHandler):
    """Minimal HTTP API handler for MCP server communication"""
    voice_capture = None
    bridge = None

    def log_message(self, format, *args):
        pass  # Suppress default HTTP access logging

    def _respond(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self):
        content_length = int(self.headers.get("Content-Length", "0") or 0)
        if content_length <= 0:
            return {}
        raw = self.rfile.read(content_length)
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return None

    def do_GET(self):
        if self.path != "/status":
            self._respond(404, {"error": "Not found"})
            return
        vc = RecordingAPIHandler.voice_capture
        self._respond(200, {
            "is_recording": vc.is_recording if vc else False,
            "recording_id": vc.current_recording_id if vc else None,
            "qdrant_enabled": bool(vc and vc.qdrant_enabled),
        })

    def do_POST(self):
        allowed_paths = (
            "/start", "/stop",
            "/qdrant/search", "/qdrant/reindex", "/qdrant/build", "/qdrant/init",
        )
        if self.path not in allowed_paths:
            self._respond(404, {"error": "Not found"})
            return

        vc = RecordingAPIHandler.voice_capture
        bridge = RecordingAPIHandler.bridge
        if vc is None or bridge is None:
            self._respond(503, {"error": "App not ready"})
            return

        body = self._read_json_body()
        if body is None:
            self._respond(400, {"error": "Invalid JSON body"})
            return

        def execute():
            if self.path in ("/start", "/stop"):
                action = self.path[1:]  # "start" or "stop"
                if action == "start" and not vc.is_recording:
                    vc.on_tray_toggle_recording()
                elif action == "stop" and vc.is_recording:
                    vc.on_tray_toggle_recording()
                return {
                    "success": True,
                    "is_recording": vc.is_recording,
                    "recording_id": vc.current_recording_id,
                }

            if not vc.qdrant_enabled or vc.qdrant_indexer is None:
                return {"error": "Qdrant is not enabled in Voice Capture"}

            if self.path == "/qdrant/search":
                query = (body.get("query") or "").strip()
                if not query:
                    return {"error": "query is required"}
                limit = int(body.get("limit", 10) or 10)
                recording_id = body.get("recording_id")
                results = vc.qdrant_indexer.search(query, limit=limit, recording_id=recording_id)
                return {"success": True, "results": results}

            if self.path == "/qdrant/reindex":
                recording_id = body.get("recording_id")
                if not recording_id:
                    return {"error": "recording_id is required"}
                result = vc.qdrant_indexer.reindex_recording(recording_id)
                return {"success": True, "result": result}

            if self.path == "/qdrant/build":
                recording_id = body.get("recording_id")
                result = vc.qdrant_indexer.index_recordings(recording_id=recording_id)
                return {"success": True, "result": result}

            if self.path == "/qdrant/init":
                force_recreate = bool(body.get("force_recreate", False))
                result = vc.qdrant_indexer.init_collection(force_recreate=force_recreate)
                return {"success": True, "result": result}

            return {"error": "Unknown action"}

        result = bridge.run(execute, timeout=30)

        if result is None:
            self._respond(504, {"error": "Timeout waiting for Qt main thread"})
            return
        if isinstance(result, dict) and result.get("error"):
            self._respond(400, result)
            return
        self._respond(200, result)


class VoiceCapture(QObject):
    """Voice Capture application - tray-only mode using composition"""

    # Define signals for thread-safe communication
    transcription_complete = pyqtSignal(dict)
    model_loaded = pyqtSignal(str, object)  # (model_name, model_object)
    segment_transcribed = pyqtSignal(str, int)  # Signal for incremental transcription updates (text, segment_num)
    ollama_status_checked = pyqtSignal(bool, object)  # (available, models_list)
    ollama_title_generated = pyqtSignal(str, str)      # (recording_id, title)
    hotkey_toggle_requested = pyqtSignal()             # Global hotkey -> toggle recording

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
        self.use_mlx = False  # Use MLX Whisper (Apple Silicon only), default off

        # Ollama title generation
        self.ollama_available = False
        self.ollama_models = []
        self.selected_ollama_model = ""
        self.determine_title = False  # Default: off

        # Load persisted settings (may override defaults above)
        self._load_settings()

        # Recording state
        self.is_recording = False
        self.current_audio_file = None
        self.current_recording_id = None

        # Connect signals to slots
        self.transcription_complete.connect(self.on_transcription_complete)
        self.model_loaded.connect(self.on_model_loaded)
        self.segment_transcribed.connect(self.on_segment_transcribed)
        self.ollama_status_checked.connect(self.on_ollama_status_checked)
        self.ollama_title_generated.connect(self._apply_generated_title)
        self.hotkey_toggle_requested.connect(self._on_hotkey_toggle_requested)

        # Track pending transcription
        self.pending_transcription = False

        # Track segments for incremental transcription
        self.segments_to_transcribe = []  # Queue of segments to transcribe
        self.transcribed_segments = []  # List of transcribed texts
        self.transcribed_segment_map = {}  # {segment_num: text} for live qdrant window indexing
        self.is_transcribing_segment = False  # Flag to track if currently transcribing

        # Qdrant live index (best effort) — initialized in background to avoid blocking startup
        self.qdrant_indexer = None
        self.qdrant_enabled = False
        self._qdrant_init_done = False
        threading.Thread(target=self.init_qdrant, daemon=True, name="qdrant-init").start()

        # Dashboard client (best effort) — initialized in background to avoid blocking startup
        self.dashboard_client = None
        threading.Thread(target=self._init_dashboard_client, daemon=True, name="dashboard-init").start()

        # Track pending recording name (set when recording stops)
        self.pending_recording_name = None

        # Track consecutive empty segments for silence detection
        self.consecutive_empty_segments = 0
        self.empty_segment_warning_shown = False

        # Global hotkey listener (macOS): Ctrl+Option+Command+R
        self.global_hotkey_listener = None
        self.hotkey_combo_active = False

        # Ollama status refresh throttling/state
        self.ollama_check_in_progress = False
        self.last_ollama_check_started_at = 0.0

        # Settings
        self.segment_duration = 10  # seconds
        self.overlap_duration = 5  # seconds

        # Tray animation state (recording input meter)
        self.icon_pulse_phase = 0
        self.icon_animation_timer = QTimer(self)
        self.icon_animation_timer.setInterval(140)
        self.icon_animation_timer.timeout.connect(self.update_recording_tray_icon)

        # Initialize tray actions handler (business logic only)
        self.tray_actions = TrayActions(self)

        # Initialize tray icon (GUI) — uses self.selected_model_name and self.use_mlx
        self.init_tray_icon()

        # Setup global hotkey (macOS only)
        self.setup_global_hotkey()

        # Load model on startup (skip when MLX is active)
        if not self.use_mlx:
            QTimer.singleShot(500, lambda: self.load_model_async(self.selected_model_name))

        # Check Ollama availability asynchronously
        QTimer.singleShot(300, self.check_ollama_async)

        # Start internal HTTP API for MCP server communication
        RecordingAPIHandler.voice_capture = self
        RecordingAPIHandler.bridge = CommandBridge()
        api_server = HTTPServer(("127.0.0.1", INTERNAL_API_PORT), RecordingAPIHandler)
        api_thread = threading.Thread(target=api_server.serve_forever, daemon=True)
        api_thread.start()
        logger.info(f"Internal API server started on 127.0.0.1:{INTERNAL_API_PORT}")

        # Start async transcribe API server on port 5152 (localhost only)
        start_transcribe_server_in_background(host="127.0.0.1", port=5152)

    def init_qdrant(self):
        """Initialize Qdrant indexer (best effort, app keeps working without it)."""
        try:
            self.qdrant_indexer = QdrantIndexer(recordings_dir=self.base_recordings_dir)
            self.qdrant_indexer.init_collection(force_recreate=False)
            self.qdrant_enabled = True
            logger.info("Qdrant indexing enabled")
        except QdrantUnavailableError as e:
            self.qdrant_enabled = False
            logger.info(f"Qdrant indexing disabled: {e}")
        except Exception as e:
            self.qdrant_enabled = False
            logger.warning(f"Qdrant initialization failed: {e}")
        finally:
            self._qdrant_init_done = True

    def _init_dashboard_client(self):
        try:
            from dashboard_client import DashboardClient
            self.dashboard_client = DashboardClient()
            logger.info("Dashboard client initialized")
        except ImportError:
            logger.info("Dashboard client not available (dashboard deps not installed)")
        except Exception as e:
            logger.warning(f"Dashboard client initialization failed: {e}")

    def _settings_path(self) -> Path:
        return self.base_recordings_dir / "settings.json"

    def _load_settings(self):
        try:
            path = self._settings_path()
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                valid_models = {"tiny", "small", "medium", "large"}
                if data.get("model") in valid_models:
                    self.selected_model_name = data["model"]
                if isinstance(data.get("use_mlx"), bool):
                    self.use_mlx = data["use_mlx"]
                if isinstance(data.get("determine_title"), bool):
                    self.determine_title = data["determine_title"]
                if isinstance(data.get("ollama_model"), str):
                    self.selected_ollama_model = data["ollama_model"]
                logger.info(f"Settings loaded: model={self.selected_model_name}, use_mlx={self.use_mlx}, determine_title={self.determine_title}")
        except Exception as e:
            logger.warning(f"Could not load settings: {e}")

    def _save_settings(self):
        try:
            path = self._settings_path()
            with open(path, "w", encoding="utf-8") as f:
                json.dump({
                    "model": self.selected_model_name,
                    "use_mlx": self.use_mlx,
                    "determine_title": self.determine_title,
                    "ollama_model": self.selected_ollama_model,
                }, f, indent=2)
            logger.debug(f"Settings saved: model={self.selected_model_name}, use_mlx={self.use_mlx}, determine_title={self.determine_title}")
        except Exception as e:
            logger.warning(f"Could not save settings: {e}")

    def init_tray_icon(self):
        """Initialize system tray icon and menu (GUI)"""
        # Create system tray icon
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(create_tray_icon(recording=False))

        # Create context menu for tray icon
        self.tray_menu = QMenu()

        # Add toggle recording action
        self.tray_toggle_action = self.tray_menu.addAction("Start Opname")
        self.tray_toggle_action.triggered.connect(self.on_tray_toggle_recording)
        # Show shortcut in menu as grey hint on the right (macOS style)
        self.tray_toggle_action.setShortcut(QKeySequence("Ctrl+Alt+Meta+R"))
        self.tray_toggle_action.setShortcutVisibleInContextMenu(True)
        # Fallback: keep shortcut visible in title for tray implementations that hide shortcut hints
        self.tray_toggle_action.setText("Start Opname\t⌃⌥⌘R")

        self.tray_menu.addSeparator()

        # Add transcription model selection submenu
        model_menu = QMenu("Transcription Model", self.tray_menu)
        model_action_group = QActionGroup(model_menu)
        model_action_group.setExclusive(True)

        # Add model options
        self.tray_tiny_action = model_menu.addAction("Tiny (Snel, ~1GB)")
        self.tray_tiny_action.setCheckable(True)
        self.tray_tiny_action.triggered.connect(lambda: self.on_tray_set_model("tiny"))
        model_action_group.addAction(self.tray_tiny_action)

        self.tray_small_action = model_menu.addAction("Small (Goed, ~2GB)")
        self.tray_small_action.setCheckable(True)
        self.tray_small_action.triggered.connect(lambda: self.on_tray_set_model("small"))
        model_action_group.addAction(self.tray_small_action)

        self.tray_medium_action = model_menu.addAction("Medium (Beter, ~5GB)")
        self.tray_medium_action.setCheckable(True)
        self.tray_medium_action.triggered.connect(lambda: self.on_tray_set_model("medium"))
        model_action_group.addAction(self.tray_medium_action)

        self.tray_large_action = model_menu.addAction("Large (Best, ~10GB)")
        self.tray_large_action.setCheckable(True)
        self.tray_large_action.triggered.connect(lambda: self.on_tray_set_model("large"))
        model_action_group.addAction(self.tray_large_action)

        # Set initial selection based on current model
        if self.selected_model_name == "medium":
            self.tray_medium_action.setChecked(True)
        elif self.selected_model_name == "tiny":
            self.tray_tiny_action.setChecked(True)
        elif self.selected_model_name == "small":
            self.tray_small_action.setChecked(True)
        elif self.selected_model_name == "large":
            self.tray_large_action.setChecked(True)

        self.tray_menu.addMenu(model_menu)

        # MLX Whisper toggle (Apple Silicon)
        self.tray_mlx_action = self.tray_menu.addAction("Gebruik MLX (Apple Silicon)")
        self.tray_mlx_action.setCheckable(True)
        self.tray_mlx_action.setChecked(self.use_mlx)
        self.tray_mlx_action.triggered.connect(self.on_tray_toggle_mlx)

        self.tray_menu.addSeparator()

        # Ollama title determination
        self.tray_determine_title_action = self.tray_menu.addAction("Bepaal titel na opname")
        self.tray_determine_title_action.setCheckable(True)
        self.tray_determine_title_action.setChecked(self.determine_title)
        self.tray_determine_title_action.setEnabled(self.ollama_available)
        self.tray_determine_title_action.triggered.connect(self.on_tray_toggle_determine_title)

        self.tray_ollama_model_menu = QMenu("Ollama Model", self.tray_menu)
        self.tray_ollama_model_menu.setEnabled(self.ollama_available)
        self._rebuild_ollama_model_menu()
        self.tray_menu.addMenu(self.tray_ollama_model_menu)

        self.tray_menu.addSeparator()

        # Add input device selection submenu
        self.tray_input_menu = QMenu("Input Selection", self.tray_menu)
        self.tray_menu.addMenu(self.tray_input_menu)

        self.tray_menu.addSeparator()

        # Add retranscribe action
        retranscribe_action = self.tray_menu.addAction("Hertranscriberen")
        retranscribe_action.triggered.connect(self.on_tray_retranscribe)

        self.tray_menu.addSeparator()

        # Add version info action
        version_action = self.tray_menu.addAction("Toon Versie")
        version_action.triggered.connect(self.on_tray_show_version)

        self.tray_menu.addSeparator()

        # Add quit action
        quit_action = self.tray_menu.addAction("Afsluiten")
        quit_action.triggered.connect(self.on_tray_quit)

        # Connect tray icon activation (click)
        self.tray_icon.activated.connect(self.on_tray_icon_activated)
        # Refresh Ollama availability when menu opens (async, non-blocking)
        self.tray_menu.aboutToShow.connect(self.on_tray_menu_about_to_show)

        # Show tray icon
        self.tray_icon.show()
        self.tray_icon.setToolTip("Voice Capture (klik om op te nemen)")

        # Refresh input devices menu
        self.refresh_tray_input_devices()

    def setup_global_hotkey(self):
        """Setup global macOS hotkey: Ctrl+Option+Command+R (toggle recording)."""
        if platform.system() != "Darwin":
            logger.info("Global hotkey is momenteel alleen actief op macOS")
            return

        if pynput_keyboard is None:
            logger.warning(
                "Global hotkey niet beschikbaar: module 'pynput' ontbreekt. "
                "Installeer via: pip install pynput"
            )
            return

        combo = {
            pynput_keyboard.Key.ctrl,
            pynput_keyboard.Key.alt,
            pynput_keyboard.Key.cmd,
            pynput_keyboard.KeyCode.from_char('r'),
        }
        current_keys = set()

        def on_press(key):
            current_keys.add(key)
            if combo.issubset(current_keys):
                if not self.hotkey_combo_active:
                    self.hotkey_combo_active = True
                    self.hotkey_toggle_requested.emit()
            else:
                self.hotkey_combo_active = False

        def on_release(key):
            if key in current_keys:
                current_keys.remove(key)
            if not combo.issubset(current_keys):
                self.hotkey_combo_active = False

        try:
            self.global_hotkey_listener = pynput_keyboard.Listener(on_press=on_press, on_release=on_release)
            self.global_hotkey_listener.daemon = True
            self.global_hotkey_listener.start()
            logger.info("Global hotkey actief: Ctrl+Option+Command+R")
        except Exception as e:
            logger.warning(f"Kon global hotkey niet starten: {e}")
            self.global_hotkey_listener = None

    def _on_hotkey_toggle_requested(self):
        """Handle global hotkey event on Qt main thread."""
        self.on_tray_toggle_recording()

    # Tray GUI event handlers (delegate to tray_actions for business logic)

    def on_tray_icon_activated(self, reason):
        """Handle tray icon activation (click) - GUI handler"""
        if reason == QSystemTrayIcon.ActivationReason.Trigger:  # Left click
            self.on_tray_toggle_recording()
        elif reason == QSystemTrayIcon.ActivationReason.Context:  # Right click / Control+click on macOS
            # Show context menu at cursor position (menu show triggers async Ollama refresh)
            self.tray_menu.popup(QCursor.pos())

    def on_tray_menu_about_to_show(self):
        """Refresh Ollama availability when tray menu opens (asynchronous)."""
        self.check_ollama_async(force=False)

    def on_tray_toggle_recording(self):
        """Handle toggle recording from tray - GUI handler"""
        if not self.is_recording:
            # Start recording
            self.tray_actions.start_recording()
            # Update UI
            self.update_recording_tray_icon()
            self.icon_animation_timer.start()
            self.tray_icon.setToolTip("Opname bezig... (klik om te stoppen)")
            self.tray_toggle_action.setText("Stop Opname")
        else:
            # Stop recording
            try:
                self.tray_actions.stop_recording()
                # Update UI
                self.icon_animation_timer.stop()
                self.tray_icon.setIcon(create_tray_icon(recording=False))
                self.tray_icon.setToolTip("Voice Capture (klik om op te nemen)")
                self.tray_toggle_action.setText("Start Opname")
            except Exception as e:
                # Handle error in UI
                self.icon_animation_timer.stop()
                self.tray_icon.setIcon(create_tray_icon(recording=False))
                self.tray_icon.setToolTip("Voice Capture (klik om op te nemen)")
                self.tray_toggle_action.setText("Start Opname")
                QMessageBox.critical(None, "Fout", f"Fout bij opslaan: {str(e)}")

    def update_recording_tray_icon(self):
        """Animate tray icon while recording based on current input level."""
        if not self.is_recording:
            return
        level = getattr(self.recorder, "input_level", 0.0)
        self.tray_icon.setIcon(create_tray_icon(recording=True, level=level, pulse_phase=self.icon_pulse_phase))
        self.icon_pulse_phase = (self.icon_pulse_phase + 1) % 1000000

    def refresh_tray_input_devices(self):
        """Refresh the audio input device list in tray menu - GUI handler"""
        try:
            # Get list of audio input devices
            devices = self.recorder.get_audio_devices()

            # Clear existing input device actions
            if self.tray_input_menu:
                self.tray_input_menu.clear()

                # Create action group for exclusive selection
                input_device_group = QActionGroup(self.tray_input_menu)
                input_device_group.setExclusive(True)

                # Add default device option
                default_action = self.tray_input_menu.addAction("Standaard apparaat")
                default_action.setCheckable(True)
                default_action.setChecked(self.recorder.input_device_index is None)
                input_device_group.addAction(default_action)
                default_action.triggered.connect(lambda checked, idx=None: self.on_tray_set_input_device(idx))

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
                    action.triggered.connect(lambda checked, idx=device_index: self.on_tray_set_input_device(idx))

                logger.debug(f"Refreshed tray input devices menu with {len(devices)} devices")

        except Exception as e:
            logger.error(f"Error refreshing tray input devices: {e}", exc_info=True)

    def on_tray_set_input_device(self, device_index):
        """Handle set input device from tray - GUI handler"""
        try:
            message = self.tray_actions.set_input_device(device_index)
            # Show notification
            self.tray_icon.showMessage(
                "Invoerapparaat Gewijzigd",
                message,
                QSystemTrayIcon.MessageIcon.Information,
                2000
            )
        except Exception as e:
            QMessageBox.warning(None, "Fout", f"Kon invoerapparaat niet instellen: {str(e)}")

    def on_tray_set_model(self, model_name):
        """Handle set Whisper model from tray - GUI handler"""
        try:
            message = self.tray_actions.set_model(model_name)

            # Update tray menu checkmarks
            self.tray_tiny_action.setChecked(model_name == "tiny")
            self.tray_small_action.setChecked(model_name == "small")
            self.tray_medium_action.setChecked(model_name == "medium")
            self.tray_large_action.setChecked(model_name == "large")

            if self.use_mlx:
                message += " (MLX)"

            self._save_settings()

            # Show notification
            self.tray_icon.showMessage(
                "Model Gewijzigd",
                message,
                QSystemTrayIcon.MessageIcon.Information,
                2000
            )
        except Exception as e:
            QMessageBox.warning(None, "Fout", f"Kon model niet instellen: {str(e)}")

    def on_tray_toggle_mlx(self):
        """Handle MLX Whisper toggle from tray - GUI handler"""
        try:
            enabling = self.tray_mlx_action.isChecked()

            if enabling:
                try:
                    import mlx_whisper  # noqa: F401
                except ImportError:
                    self.tray_mlx_action.setChecked(False)
                    QMessageBox.warning(
                        None,
                        "MLX niet beschikbaar",
                        "mlx-whisper is niet geïnstalleerd.\n\nInstalleer via:\n  pip install mlx-whisper"
                    )
                    return

            self.use_mlx = enabling
            self._save_settings()
            status = "ingeschakeld" if self.use_mlx else "uitgeschakeld"
            self.tray_icon.showMessage(
                "MLX Whisper",
                f"MLX (Apple Silicon) transcriptie {status}",
                QSystemTrayIcon.MessageIcon.Information,
                2000
            )
        except Exception as e:
            QMessageBox.warning(None, "Fout", f"Kon MLX niet instellen: {str(e)}")

    def on_tray_toggle_determine_title(self):
        """Handle 'Bepaal titel na opname' toggle - GUI handler"""
        self.determine_title = self.tray_determine_title_action.isChecked()
        self._save_settings()
        status = "ingeschakeld" if self.determine_title else "uitgeschakeld"
        self.tray_icon.showMessage(
            "Titelbepaling",
            f"Automatische titelbepaling {status}",
            QSystemTrayIcon.MessageIcon.Information,
            2000,
        )

    def on_tray_set_ollama_model(self, model_name: str):
        """Handle Ollama model selection - GUI handler"""
        self.selected_ollama_model = model_name
        self._save_settings()
        logger.info(f"Ollama model set to: {model_name}")

    def _rebuild_ollama_model_menu(self):
        """Rebuild the Ollama model radio-button submenu."""
        self.tray_ollama_model_menu.clear()
        if not self.ollama_models:
            placeholder = self.tray_ollama_model_menu.addAction("(geen modellen beschikbaar)")
            placeholder.setEnabled(False)
            return

        group = QActionGroup(self.tray_ollama_model_menu)
        group.setExclusive(True)
        # Default to first model if stored model is no longer in the list
        if self.selected_ollama_model not in self.ollama_models:
            self.selected_ollama_model = self.ollama_models[0]
            self._save_settings()

        for model in self.ollama_models:
            action = self.tray_ollama_model_menu.addAction(model)
            action.setCheckable(True)
            action.setChecked(model == self.selected_ollama_model)
            action.triggered.connect(lambda checked, m=model: self.on_tray_set_ollama_model(m))
            group.addAction(action)

    def check_ollama_async(self, force: bool = False):
        """Check Ollama availability in a background thread and emit signal when done."""
        now = time.monotonic()
        # Avoid stacking checks when the menu opens repeatedly.
        if self.ollama_check_in_progress:
            return
        # Throttle quick repeated opens; force=True bypasses this.
        if not force and (now - self.last_ollama_check_started_at) < 2.0:
            return

        self.ollama_check_in_progress = True
        self.last_ollama_check_started_at = now
        logger.info("Ollama: beschikbaarheid controleren ...")

        def _check():
            available = ollama_utils.check_ollama_available()
            models = ollama_utils.get_ollama_models() if available else []
            self.ollama_status_checked.emit(available, models)

        t = threading.Thread(target=_check, daemon=True, name="ollama-check")
        t.start()

    def on_ollama_status_checked(self, available: bool, models: object):
        """Update Ollama-related menu items after availability check (main thread)."""
        self.ollama_check_in_progress = False
        self.ollama_available = available
        self.ollama_models = list(models) if models else []
        logger.info(f"Ollama available={available}, models={self.ollama_models}")

        self.tray_determine_title_action.setEnabled(available)
        self.tray_ollama_model_menu.setEnabled(available)
        self._rebuild_ollama_model_menu()

    def _generate_title_async(self, recording_id: str, transcription: str):
        """Generate a recording title via Ollama in a background thread."""
        model = self.selected_ollama_model
        logger.info(f"Ollama: titel genereren voor opname {recording_id} met model '{model}' ({len(transcription)} tekens)")

        def _run():
            try:
                available = ollama_utils.check_ollama_available()
                models = ollama_utils.get_ollama_models() if available else []
                self.ollama_status_checked.emit(available, models)
                if not available:
                    logger.warning("Ollama: titelbepaling geannuleerd — Ollama niet beschikbaar")
                    return
                logger.info(f"Ollama: verzoek verstuurd naar {ollama_utils.OLLAMA_BASE_URL} ...")
                title = ollama_utils.generate_title(transcription, model)
                if title:
                    logger.info(f"Ollama: titel ontvangen: '{title}'")
                    self.ollama_title_generated.emit(recording_id, title)
                else:
                    logger.warning("Ollama: lege titel ontvangen, opname naam ongewijzigd")
            except Exception as e:
                logger.warning(f"Ollama: titelbepaling mislukt: {e}")

        t = threading.Thread(target=_run, daemon=True, name="ollama-title")
        t.start()

    def _apply_generated_title(self, recording_id: str, title: str):
        """Save the Ollama-generated title to the recording JSON (main thread)."""
        self.recording_manager.update_recording(recording_id, name=title)
        logger.info(f"Ollama: titel opgeslagen voor {recording_id}: '{title}'")
        if hasattr(self, 'tray_icon'):
            self.tray_icon.showMessage(
                "Titel Bepaald",
                title,
                QSystemTrayIcon.MessageIcon.Information,
                4000,
            )

    def on_tray_show_version(self):
        """Handle show version from tray - GUI handler"""
        version = get_version_string()
        QMessageBox.information(
            None,
            "Versie Informatie",
            f"Voice Capture\n\nVersie: {version}"
        )

    def on_tray_retranscribe(self):
        """Handle retranscribe from tray - GUI handler"""
        # Check if currently recording
        if self.is_recording:
            QMessageBox.warning(None, "Fout", "Stop eerst de huidige opname voordat je hertranscribeert.")
            return

        # Check if currently transcribing
        if self.is_transcribing_segment:
            QMessageBox.warning(None, "Fout", "Wacht tot de huidige transcriptie is voltooid.")
            return

        # Get recordings from business logic
        recordings = self.tray_actions.get_retranscribe_recordings()

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
        effective_model_display = f"mlx-{self.selected_model_name}" if self.use_mlx else self.selected_model_name
        instruction_label = QLabel(f"Selecteer een opname om te hertranscriberen met het <b>{effective_model_display}</b> model:")
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

        # Right-click context menu on list items
        list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        def on_context_menu(pos):
            item = list_widget.itemAt(pos)
            if not item:
                return

            recording_id = item.data(Qt.ItemDataRole.UserRole)
            context_menu = QMenu(list_widget)
            bepaal_titel_action = context_menu.addAction("Bepaal titel")
            bepaal_titel_action.setEnabled(self.ollama_available and bool(self.selected_ollama_model))
            kopieer_opname_id_action = context_menu.addAction("Kopieer opname id")

            action = context_menu.exec(list_widget.viewport().mapToGlobal(pos))
            if action == kopieer_opname_id_action:
                QApplication.clipboard().setText(str(recording_id))
                self.tray_icon.showMessage(
                    "Opname id gekopieerd",
                    str(recording_id),
                    QSystemTrayIcon.MessageIcon.Information,
                    2000,
                )
            elif action == bepaal_titel_action:
                recording = self.recording_manager.get_recording(recording_id)
                if not recording:
                    QMessageBox.warning(dialog, "Fout", "Opname niet gevonden.")
                    return
                transcription = recording.get('transcription', '')
                if not transcription:
                    QMessageBox.warning(dialog, "Geen transcriptie", "Deze opname heeft geen transcriptie om een titel van te bepalen.")
                    return
                self._generate_title_async(recording_id, transcription)
                self.tray_icon.showMessage(
                    "Titel Bepalen",
                    "Bezig met bepalen van de titel...",
                    QSystemTrayIcon.MessageIcon.Information,
                    2000,
                )

        list_widget.customContextMenuRequested.connect(on_context_menu)

        # Update list item text when a title is generated while dialog is open
        def update_list_item_title(gen_recording_id, title):
            for i in range(list_widget.count()):
                it = list_widget.item(i)
                if it.data(Qt.ItemDataRole.UserRole) == gen_recording_id:
                    rec = self.recording_manager.get_recording(gen_recording_id)
                    if rec:
                        recording_date = rec.get('date', '')
                        duration = rec.get('duration', '')
                        current_model = rec.get('model', '')
                        new_text = f"{title} - {recording_date}"
                        if duration:
                            new_text += f" ({duration})"
                        if current_model:
                            new_text += f" [model: {current_model}]"
                        it.setText(new_text)
                    break

        self.ollama_title_generated.connect(update_list_item_title)
        dialog.finished.connect(lambda: self.ollama_title_generated.disconnect(update_list_item_title))

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

            # Start retranscription via business logic
            self.tray_actions.start_retranscription(recording_id)

            # Show notification
            effective_model_notif = f"mlx-{self.selected_model_name}" if self.use_mlx else self.selected_model_name
            self.tray_icon.showMessage(
                "Hertranscriptie Gestart",
                f"Hertranscriberen met {effective_model_notif} model...",
                QSystemTrayIcon.MessageIcon.Information,
                2000
            )

        def on_cancel():
            dialog.reject()

        ok_button.clicked.connect(on_ok)
        cancel_button.clicked.connect(on_cancel)

        # Show dialog
        dialog.exec()

    def on_tray_quit(self):
        """Handle quit from tray - GUI handler"""
        # Stop global hotkey listener
        if self.global_hotkey_listener is not None:
            try:
                self.global_hotkey_listener.stop()
            except Exception as e:
                logger.debug(f"Failed stopping hotkey listener: {e}")
            self.global_hotkey_listener = None

        # Call business logic
        self.tray_actions.quit_application()

        # Hide tray icon
        if self.tray_icon:
            self.tray_icon.hide()

        # Quit application
        QApplication.quit()

    # Core recording methods

    def start_recording(self):
        """Start recording"""
        logger.info("Starting recording...")
        self.is_recording = True

        # Clear previous segments
        self.segments_to_transcribe = []
        self.transcribed_segments = []
        self.transcribed_segment_map = {}
        self.consecutive_empty_segments = 0
        self.empty_segment_warning_shown = False

        # Set segment settings on recorder
        self.recorder.segment_duration = self.segment_duration
        self.recorder.overlap_duration = self.overlap_duration

        # Start recording with segment callback
        self.recorder.start_recording(segment_callback=self.on_segment_ready)
        self.current_recording_id = self.recorder.recording_timestamp

        # Add recording to manager (without duration initially)
        recording_name = f"Opname {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        self.current_audio_file = str(self.base_recordings_dir / f"recording_{self.current_recording_id}" / f"recording_{self.current_recording_id}.wav")

        effective_model = f"mlx-{self.selected_model_name}" if self.use_mlx else self.selected_model_name
        logger.info(f"Transcription model: {effective_model}")
        self.recording_manager.add_recording(
            audio_file=self.current_audio_file,
            timestamp=self.current_recording_id,
            name=recording_name,
            duration=None,  # Don't set duration yet
            model=effective_model,
            segment_duration=self.segment_duration,
            overlap_duration=self.overlap_duration
        )

        logger.info(f"Recording started with ID: {self.current_recording_id}")

        # Notify dashboard (best effort)
        if self.dashboard_client:
            try:
                self.dashboard_client.recording_started(
                    self.current_recording_id,
                    recording_name,
                    datetime.now()
                )
            except Exception as e:
                logger.warning(f"Dashboard recording_started failed: {e}")

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

        # Get model (not needed for MLX)
        model_name = self.selected_model_name
        model = None
        if not self.use_mlx:
            if model_name not in self.loaded_models:
                logger.warning(f"Model {model_name} not loaded yet, waiting...")
                self.is_transcribing_segment = False
                return
            model = self.loaded_models[model_name]

        self.is_transcribing_segment = True

        # Get next segment
        segment_file, segment_num = self.segments_to_transcribe.pop(0)

        # Count total segments in recording directory
        rec_dir = self.base_recordings_dir / f"recording_{self.current_recording_id}"
        segments_dir = rec_dir / "segments"
        total_segments = len(list(segments_dir.glob("segment_*.wav"))) if segments_dir.exists() else 0

        logger.info(f"Transcribing segment {segment_num}/{total_segments}...")

        # Start transcription in background thread
        thread = threading.Thread(
            target=self.transcribe_segment_thread,
            args=(segment_file, segment_num, model, self.use_mlx)
        )
        thread.daemon = True
        thread.start()

    def transcribe_segment_thread(self, audio_file, segment_num, model, use_mlx=False):
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

            if use_mlx:
                import mlx_whisper
                result = mlx_whisper.transcribe(
                    audio_file,
                    path_or_hf_repo=f"mlx-community/whisper-{self.selected_model_name}-mlx",
                    verbose=False
                )
            else:
                # Transcribe with fp16=False to avoid NaN issues on MPS
                result = model.transcribe(
                    audio_file,
                    task="transcribe",
                    fp16=False,
                    verbose=False
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

        if is_empty_segment(text):
            self.consecutive_empty_segments += 1
            logger.debug(f"Empty segment {segment_num}, consecutive empty: {self.consecutive_empty_segments}")
            if self.consecutive_empty_segments >= 5 and not self.empty_segment_warning_shown:
                self.empty_segment_warning_shown = True
                QMessageBox.warning(
                    None,
                    "Geen audio gedetecteerd",
                    "Er zijn 5 opeenvolgende segmenten zonder transcriptie.\n\n"
                    "Controleer of uw microfoon correct werkt en geluid opneemt.",
                    QMessageBox.StandardButton.Ok
                )
            return

        self.consecutive_empty_segments = 0
        self.transcribed_segment_map[segment_num] = text

        # Live ingest into Qdrant (best effort)
        if self.qdrant_enabled and self.qdrant_indexer and self.current_recording_id:
            try:
                recording = self.recording_manager.get_recording(self.current_recording_id) or {}
                prev_text = self.transcribed_segment_map.get(segment_num - 1)
                self.qdrant_indexer.index_live_segment(
                    recording_id=self.current_recording_id,
                    segment_num=segment_num,
                    text=text,
                    recording_name=recording.get("name"),
                    recording_date=recording.get("date"),
                    prev_segment_text=prev_text,
                )
            except Exception as e:
                logger.warning(f"Qdrant live segment indexing failed for segment {segment_num}: {e}")

        # Dashboard live segment push (best effort)
        if self.dashboard_client and self.current_recording_id:
            try:
                self.dashboard_client.segment(
                    self.current_recording_id,
                    segment_num,
                    text,
                    datetime.now(),
                    self.segment_duration,
                )
            except Exception as e:
                logger.warning(f"Dashboard segment push failed for segment {segment_num}: {e}")

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

        # Reindex final transcript in Qdrant (replaces live segment points for this recording)
        if self.qdrant_enabled and self.qdrant_indexer:
            try:
                self.qdrant_indexer.reindex_recording(self.current_recording_id)
                logger.info(f"Qdrant reindexed recording {self.current_recording_id}")
            except Exception as e:
                logger.warning(f"Qdrant reindex failed for {self.current_recording_id}: {e}")
        elif not self._qdrant_init_done:
            logger.warning(f"Qdrant was still initializing when recording {self.current_recording_id} finished — recording not indexed")

        # Notify dashboard recording ended (best effort)
        if self.dashboard_client and self.current_recording_id:
            try:
                self.dashboard_client.recording_ended(self.current_recording_id, datetime.now())
            except Exception as e:
                logger.warning(f"Dashboard recording_ended failed: {e}")

        # Generate title via Ollama if enabled (availability is checked fresh inside the thread)
        if self.determine_title and self.selected_ollama_model:
            self._generate_title_async(self.current_recording_id, final_transcription)
        elif self.determine_title:
            logger.warning("Ollama: titelbepaling actief maar geen model geselecteerd")

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
        """Start retranscription of a recording using segments or full audio file"""
        logger.info(f"Starting retranscription of recording {recording_id} with model {self.selected_model_name}")

        # Get recording metadata
        recording = self.recording_manager.get_recording(recording_id)
        if not recording:
            logger.error(f"Recording {recording_id} not found")
            # Use signal to show error on main thread
            QTimer.singleShot(0, lambda: QMessageBox.warning(None, "Fout", "Opname niet gevonden."))
            return

        # Find the recording directory
        rec_dir = self.base_recordings_dir / f"recording_{recording_id}"
        audio_file = rec_dir / f"recording_{recording_id}.wav"
        segments_dir = rec_dir / "segments"

        # Check if we should use segments or main file
        use_segments = False
        if not audio_file.exists() or audio_file.stat().st_size == 0:
            # Main file doesn't exist or is empty - check for segments
            if segments_dir.exists():
                segment_files = sorted(segments_dir.glob("segment_*.wav"))
                if segment_files:
                    logger.info(f"Main audio file is missing/empty, will use {len(segment_files)} segments for retranscription")
                    use_segments = True
                else:
                    logger.error(f"No segments found for recording {recording_id}")
                    QTimer.singleShot(0, lambda: QMessageBox.warning(None, "Fout", "Geen audio bestanden gevonden voor deze opname."))
                    return
            else:
                logger.error(f"Audio file not found and no segments for recording {recording_id}")
                QTimer.singleShot(0, lambda: QMessageBox.warning(None, "Fout", "Geen audio bestanden gevonden voor deze opname."))
                return

        # Set current recording ID for retranscription
        self.current_recording_id = recording_id

        # Note: notification is shown by the GUI handler (on_tray_retranscribe)

        # Capture MLX state at time of starting retranscription
        use_mlx_retranscribe = self.use_mlx
        effective_model_name = f"mlx-{self.selected_model_name}" if use_mlx_retranscribe else self.selected_model_name

        # Start transcription in background thread
        def retranscribe_worker():
            try:
                model_name = self.selected_model_name

                if use_mlx_retranscribe:
                    import mlx_whisper
                    mlx_repo = f"mlx-community/whisper-{model_name}-mlx"

                    def transcribe_file(path):
                        return mlx_whisper.transcribe(str(path), path_or_hf_repo=mlx_repo, verbose=False)
                else:
                    if model_name not in self.loaded_models:
                        logger.error(f"Model {model_name} not loaded yet")
                        QTimer.singleShot(0, lambda: QMessageBox.warning(None, "Fout", f"Model {model_name} is nog niet geladen. Probeer later opnieuw."))
                        return
                    loaded_model = self.loaded_models[model_name]

                    def transcribe_file(path):
                        return loaded_model.transcribe(str(path), task="transcribe", fp16=False, verbose=False)

                if use_segments:
                    logger.info(f"Retranscribing {len(segment_files)} segments with {effective_model_name} model...")

                    segment_texts = []
                    for i, segment_file in enumerate(segment_files):
                        logger.info(f"Transcribing segment {i+1}/{len(segment_files)}: {segment_file.name}")

                        # Check if segment has sufficient duration
                        import wave
                        try:
                            with wave.open(str(segment_file), 'rb') as wf:
                                frames = wf.getnframes()
                                rate = wf.getframerate()
                                duration = frames / float(rate)

                                if duration < 0.1:
                                    logger.warning(f"Segment {i} too short ({duration:.2f}s), skipping")
                                    continue
                        except Exception as e:
                            logger.error(f"Error checking segment {i}: {e}")
                            continue

                        result = transcribe_file(segment_file)
                        text = result["text"].strip()
                        if text:
                            if len(segment_texts) == 0:
                                segment_texts.append(text)
                            else:
                                previous_text = segment_texts[-1]
                                deduplicated_text = remove_overlap(previous_text, text)
                                if deduplicated_text.strip():
                                    segment_texts.append(deduplicated_text)

                    transcription_text = " ".join(segment_texts)
                    logger.info(f"Retranscription complete from segments: {len(transcription_text)} chars")
                else:
                    logger.info(f"Transcribing full audio file {audio_file} with {effective_model_name} model...")
                    result = transcribe_file(audio_file)
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
                    model=effective_model_name
                )

                logger.info(f"Updated recording {recording_id} with new transcription and model {effective_model_name}")

                # Show completion notification on main thread
                def show_completion():
                    if hasattr(self, 'tray_icon'):
                        self.tray_icon.showMessage(
                            "Hertranscriptie Voltooid",
                            f"Opname hertranscribeerd met {effective_model_name}: {len(transcription_text)} tekens",
                            QSystemTrayIcon.MessageIcon.Information,
                            3000
                        )
                QTimer.singleShot(0, show_completion)

            except Exception as e:
                logger.error(f"Error during retranscription: {e}", exc_info=True)
                # Use signal to show error on main thread
                error_msg = str(e)
                QTimer.singleShot(0, lambda: QMessageBox.critical(None, "Fout", f"Fout bij hertranscriberen: {error_msg}"))
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

    # Check for ffmpeg
    if not check_ffmpeg():
        sys.exit(1)

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
        QTimer.singleShot(0, voice_capture.on_tray_quit)

    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)   # Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler)  # Termination signal

    # Install a timer to allow Python to process signals
    # Qt event loop blocks Python signal handlers, so we need to wake up periodically
    timer = QTimer()
    timer.start(30000)  # Wake up every 30 seconds to allow signal processing (battery optimized)
    timer.timeout.connect(lambda: None)  # Do nothing, just process signals

    # Run the application
    try:
        exit_code = app.exec()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received, shutting down...")
        voice_capture.on_tray_quit()
        sys.exit(0)


if __name__ == "__main__":
    main()
