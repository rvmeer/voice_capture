"""
Tray Icon Actions Module
Contains all tray menu action handlers
"""

from PyQt6.QtWidgets import QSystemTrayIcon, QMessageBox, QInputDialog
from PyQt6.QtCore import Qt
from datetime import datetime
from pathlib import Path
from logging_config import get_logger

logger = get_logger(__name__)


class TrayActions:
    """Mixin class containing all tray icon menu actions"""

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

        # Update tray icon to recording state
        from main import create_tray_icon
        self.tray_icon.setIcon(create_tray_icon(recording=True))
        self.tray_icon.setToolTip("Opname bezig... (klik om te stoppen)")

        self.start_recording()

    def tray_stop_recording(self):
        """Stop recording from tray"""
        logger.info("Stopping recording from tray")

        # Update tray icon to idle state
        from main import create_tray_icon
        self.tray_icon.setIcon(create_tray_icon(recording=False))
        self.tray_icon.setToolTip("Voice Capture (klik om op te nemen)")

        def save_and_continue():
            try:
                self.current_audio_file, self.current_recording_id = self.recorder.stop_recording()

                # Auto-generate name based on timestamp
                recording_name = f"Opname {datetime.now().strftime('%Y-%m-%d %H:%M')}"

                # Store the recording name for later use
                self.pending_recording_name = recording_name

                # Wait for all segments to be transcribed, then finalize
                logger.info(f"Recording stopped (tray mode), waiting for all segments to be transcribed...")
                self.check_and_finalize_recording()

            except Exception as e:
                logger.error(f"Error in save_and_continue: {e}", exc_info=True)
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
            f"Voice Capture\n\nVersie: {version}"
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
        """Quit the application"""
        logger.info("Quitting application...")

        # Stop recording if active
        if self.is_recording:
            self.recorder.stop_recording()

        # Clean up
        self.recorder.cleanup()

        # Quit
        from PyQt6.QtWidgets import QApplication
        QApplication.quit()
