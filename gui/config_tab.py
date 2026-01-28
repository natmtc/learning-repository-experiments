"""
Configuration Tab - Device connection, configuration, and recording settings.

ARCHITECTURE:
- Timer-based display updates at configurable refresh rate
- Data arrives in 2ms blocks via TCP/IP
- Display timer triggers repaint, NOT data callbacks
- All protocol parameters exposed via NovecentoConfigDialog
"""

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QComboBox,
    QLineEdit,
    QSpinBox,
    QGroupBox,
    QFileDialog,
    QMessageBox,
    QSplitter,
    QFrame,
    QDoubleSpinBox,
)
from PySide6.QtCore import Qt, Signal, Slot, QTimer
from typing import Optional, List, Dict, Callable
from datetime import datetime
import numpy as np
import threading
from collections import deque

from core.novecento_config import NovecentoConfiguration, ProbeType, SamplingRate
from gui.widgets import MultiChannelPlotWidget, StatusIndicator


DEFAULT_DISPLAY_REFRESH_MS = 75  # 75ms is smoother for real-time


class ConfigurationTab(QWidget):
    """
    Configuration tab for device connection, configuration, and live preview.

    Signals:
        connectionChanged(bool): Emitted when connection status changes
        channelsChanged(list, list): Emitted when active channels change (emg, aux)
        configurationChanged(object): Emitted when configuration is applied
        dataFolderChanged(str): Emitted when data folder changes
        subjectChanged(str): Emitted when subject ID changes
        displayRefreshChanged(int): Emitted when refresh rate changes
    """

    connectionChanged = Signal(bool)
    channelsChanged = Signal(list, list)
    configurationChanged = Signal(object)
    dataFolderChanged = Signal(str)
    subjectChanged = Signal(str)
    displayRefreshChanged = Signal(int)

    # Default TCP connection settings
    DEFAULT_IP = "169.254.1.10"
    DEFAULT_PORT = 23456

    def __init__(self, parent=None):
        super().__init__(parent)

        self._client = None
        self._config: Optional[NovecentoConfiguration] = None

        self._visualizing_input: Optional[str] = None
        self._is_visualising = False

        # Display refresh rate (configurable)
        self._display_refresh_ms: int = DEFAULT_DISPLAY_REFRESH_MS

        # THREAD-SAFE DATA BUFFER
        # Background thread appends, display timer pops
        # deque is thread-safe for append/popleft
        self._sample_buffer = deque(maxlen=100)  # Hold up to 100 data chunks
        self._buffer_lock = threading.Lock()
        self._latest_value: float = 0.0

        self._setup_ui()

        # DISPLAY TIMER - triggers repaint at fixed interval
        self._display_timer = QTimer()
        self._display_timer.timeout.connect(self._update_display)

        # Additional stream consumers (e.g., calibration tab)
        self._additional_stream_consumers = []

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)

        splitter = QSplitter(Qt.Horizontal)

        # ============ LEFT PANEL ============
        settings_widget = QWidget()
        settings_layout = QVBoxLayout(settings_widget)

        # 1. Device Connection
        conn_group = QGroupBox("1. Device Connection")
        conn_layout = QGridLayout(conn_group)

        conn_layout.addWidget(QLabel("Device:"), 0, 0)
        self._device_combo = QComboBox()
        self._device_combo.addItem("Mock Device (Testing)")
        self._device_combo.addItem("Novecento+ (TCP)")
        self._device_combo.currentTextChanged.connect(self._on_device_selection_changed)
        conn_layout.addWidget(self._device_combo, 0, 1, 1, 2)

        conn_layout.addWidget(QLabel("IP Address:"), 1, 0)
        self._ip_input = QLineEdit()
        self._ip_input.setPlaceholderText(f"{self.DEFAULT_IP}:{self.DEFAULT_PORT}")
        self._ip_input.setText(f"{self.DEFAULT_IP}:{self.DEFAULT_PORT}")
        conn_layout.addWidget(self._ip_input, 1, 1, 1, 2)

        self._ip_label = conn_layout.itemAtPosition(1, 0).widget()
        self._on_device_selection_changed(self._device_combo.currentText())

        btn_layout = QHBoxLayout()
        self._connect_btn = QPushButton("Connect")
        self._connect_btn.clicked.connect(self._connect)
        btn_layout.addWidget(self._connect_btn)

        self._disconnect_btn = QPushButton("Disconnect")
        self._disconnect_btn.clicked.connect(self._disconnect)
        self._disconnect_btn.setEnabled(False)
        btn_layout.addWidget(self._disconnect_btn)

        self._connection_status = StatusIndicator("Connected")
        btn_layout.addWidget(self._connection_status)

        conn_layout.addLayout(btn_layout, 2, 0, 1, 3)

        self._device_info = QLabel("")
        self._device_info.setStyleSheet("color: #9da3ab;")
        conn_layout.addWidget(self._device_info, 3, 0, 1, 3)

        settings_layout.addWidget(conn_group)

        # 2. Configuration
        config_group = QGroupBox("2. Device Configuration")
        config_layout = QVBoxLayout(config_group)

        self._probes_label = QLabel("Connect to see detected probes")
        self._probes_label.setStyleSheet("color: #9da3ab; font-style: italic;")
        config_layout.addWidget(self._probes_label)

        config_btn_layout = QHBoxLayout()
        self._config_btn = QPushButton("Open Configuration...")
        self._config_btn.clicked.connect(self._open_config_dialog)
        self._config_btn.setEnabled(False)
        config_btn_layout.addWidget(self._config_btn)

        self._config_status = QLabel("")
        self._config_status.setStyleSheet("color: #9da3ab;")
        config_btn_layout.addWidget(self._config_status)
        config_btn_layout.addStretch()

        config_layout.addLayout(config_btn_layout)
        settings_layout.addWidget(config_group)

        # 3. Display Settings (CONFIGURABLE REFRESH RATE)
        display_group = QGroupBox("3. Display Settings")
        display_layout = QHBoxLayout(display_group)

        display_layout.addWidget(QLabel("Refresh Rate:"))
        self._refresh_spin = QSpinBox()
        self._refresh_spin.setRange(20, 500)
        self._refresh_spin.setValue(DEFAULT_DISPLAY_REFRESH_MS)
        self._refresh_spin.setSuffix(" ms")
        self._refresh_spin.setToolTip(
            "Display update interval (how often screen repaints)\n"
            "50-100ms recommended for real-time feedback"
        )
        self._refresh_spin.valueChanged.connect(self._on_refresh_rate_changed)
        display_layout.addWidget(self._refresh_spin)
        display_layout.addStretch()

        settings_layout.addWidget(display_group)

        # 4. Live Preview
        preview_group = QGroupBox("4. Live Preview")
        preview_layout = QHBoxLayout(preview_group)

        preview_layout.addWidget(QLabel("View Input:"))
        self._preview_input_combo = QComboBox()
        self._preview_input_combo.setEnabled(False)
        self._preview_input_combo.setMinimumWidth(100)
        self._preview_input_combo.currentTextChanged.connect(
            self._on_preview_input_changed
        )
        preview_layout.addWidget(self._preview_input_combo)

        self._visualise_btn = QPushButton("Start")
        self._visualise_btn.clicked.connect(self._toggle_visualisation)
        self._visualise_btn.setEnabled(False)
        preview_layout.addWidget(self._visualise_btn)

        self._viz_status = QLabel("Configure first")
        self._viz_status.setStyleSheet("color: #9da3ab;")
        preview_layout.addWidget(self._viz_status)

        # Live value display
        self._live_value_label = QLabel(
            "Value: ----------------------------------------"
        )
        self._live_value_label.setStyleSheet(
            "color: #4a9eff; font-size: 14px; font-weight: bold;"
        )
        preview_layout.addWidget(self._live_value_label)

        preview_layout.addStretch()

        settings_layout.addWidget(preview_group)

        # 5. Session Settings
        session_group = QGroupBox("5. Session Settings")
        session_layout = QGridLayout(session_group)

        session_layout.addWidget(QLabel("Subject ID:"), 0, 0)
        self._subject_input = QLineEdit()
        self._subject_input.setPlaceholderText("Enter subject ID")
        self._subject_input.editingFinished.connect(self._on_subject_changed)
        session_layout.addWidget(self._subject_input, 0, 1, 1, 2)

        session_layout.addWidget(QLabel("Data Folder:"), 1, 0)
        self._folder_input = QLineEdit("./data")
        session_layout.addWidget(self._folder_input, 1, 1)

        self._browse_btn = QPushButton("Browse")
        self._browse_btn.clicked.connect(self._browse_folder)
        session_layout.addWidget(self._browse_btn, 1, 2)

        session_layout.addWidget(QLabel("File Format:"), 2, 0)
        self._format_combo = QComboBox()
        self._format_combo.addItems(["HDF5 (.h5)", "CSV (.csv)"])
        session_layout.addWidget(self._format_combo, 2, 1, 1, 2)

        # Info label
        info_label = QLabel("Note: Recording is controlled from protocol tabs")
        info_label.setStyleSheet("color: #9da3ab; font-style: italic; font-size: 11px;")
        session_layout.addWidget(info_label, 3, 0, 1, 3)

        settings_layout.addWidget(session_group)
        settings_layout.addStretch()

        splitter.addWidget(settings_widget)

        # ============ RIGHT PANEL - Live Plots ============
        plots_widget = QWidget()
        plots_layout = QVBoxLayout(plots_widget)

        self._preview_label = QLabel("Live Signal Preview - Select an input to view")
        self._preview_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        plots_layout.addWidget(self._preview_label)

        # Zoom controls
        zoom_layout = QHBoxLayout()
        zoom_layout.addWidget(QLabel("Time window (s):"))
        self._time_window_spin = QDoubleSpinBox()
        self._time_window_spin.setRange(0.5, 30.0)
        self._time_window_spin.setValue(5.0)
        self._time_window_spin.setSingleStep(0.5)
        self._time_window_spin.valueChanged.connect(self._on_time_window_changed)
        zoom_layout.addWidget(self._time_window_spin)

        zoom_layout.addWidget(QLabel("Y-scale:"))
        self._y_scale_spin = QDoubleSpinBox()
        self._y_scale_spin.setRange(0.1, 10.0)
        self._y_scale_spin.setValue(1.0)
        self._y_scale_spin.setSingleStep(0.1)
        self._y_scale_spin.setDecimals(1)
        self._y_scale_spin.setSuffix("x")
        self._y_scale_spin.valueChanged.connect(self._on_y_scale_changed)
        zoom_layout.addWidget(self._y_scale_spin)

        zoom_layout.addStretch()
        plots_layout.addLayout(zoom_layout)

        self._multi_plot = MultiChannelPlotWidget(n_channels=1, buffer_seconds=5.0)
        self._multi_plot.set_channel_names(["No input selected"])
        self._multi_plot.setMinimumHeight(400)
        plots_layout.addWidget(self._multi_plot)

        splitter.addWidget(plots_widget)
        splitter.setSizes([400, 400])

        main_layout.addWidget(splitter)

    def _on_refresh_rate_changed(self, value: int):
        """Handle refresh rate change"""
        self._display_refresh_ms = value
        # Restart timer with new interval if running
        if self._display_timer.isActive():
            self._display_timer.stop()
            self._display_timer.start(self._display_refresh_ms)
        # Update config if exists
        if self._config:
            self._config.display_refresh_ms = value
        # Emit signal so other tabs can sync
        self.displayRefreshChanged.emit(value)

    def _on_time_window_changed(self, value: float):
        """Handle time window (X-axis) change"""
        self._multi_plot.set_time_window(value)

    def _on_y_scale_changed(self, value: float):
        """Handle Y-axis scale change"""
        self._multi_plot.set_y_scale(value)

    def get_display_refresh_rate(self) -> int:
        """Get current display refresh rate"""
        return self._display_refresh_ms

    def _on_device_selection_changed(self, text: str):
        """Show/hide IP input based on device selection"""
        is_novecento = "Novecento+" in text
        self._ip_input.setVisible(is_novecento)
        self._ip_label.setVisible(is_novecento)

    def _connect(self):
        """Connect to selected device"""
        device = self._device_combo.currentText()

        try:
            if "Mock" in device:
                from clients.mock_client import MockNovecentoClient

                self._client = MockNovecentoClient()
                success = self._client.connect("mock")
            elif "Novecento+" in device:
                try:
                    from clients.hardware_client import HardwareNovecentoClient

                    ip_address = self._ip_input.text().strip()
                    if not ip_address:
                        ip_address = f"{self.DEFAULT_IP}:{self.DEFAULT_PORT}"

                    self._client = HardwareNovecentoClient()
                    success = self._client.connect(ip_address)

                    if not success:
                        QMessageBox.warning(
                            self,
                            "Connection Failed",
                            f"Could not connect to Novecento+ at {ip_address}.\n\n"
                            "Please check:\n"
                            "- The Novecento+ is powered on\n"
                            "- The Ethernet cable is connected\n"
                            "- Network adapter configured for 169.254.x.x\n\n"
                            "Use 'Mock Device' for testing.",
                        )
                        return

                except ImportError as e:
                    QMessageBox.information(
                        self,
                        "Hardware Client Not Available",
                        f"Hardware client not available:\n{e}\n\n"
                        "Using Mock Device instead.",
                    )
                    from clients.mock_client import MockNovecentoClient

                    self._client = MockNovecentoClient()
                    success = self._client.connect("mock")
                except Exception as e:
                    QMessageBox.warning(self, "Connection Error", str(e))
                    return
            else:
                try:
                    from clients.hardware_client import HardwareNovecentoClient

                    self._client = HardwareNovecentoClient()
                    success = self._client.connect(device)
                except ImportError:
                    from clients.mock_client import MockNovecentoClient

                    self._client = MockNovecentoClient()
                    success = self._client.connect("mock")

            if success:
                self._on_connected()
            else:
                QMessageBox.critical(
                    self, "Connection Failed", f"Failed to connect to {device}"
                )
        except Exception as e:
            QMessageBox.critical(self, "Connection Error", str(e))

    def _disconnect(self):
        """Disconnect from device"""
        if self._is_visualising:
            self._stop_visualisation()

        if self._client:
            self._client.disconnect()
            self._client = None

        self._on_disconnected()

    def _on_connected(self):
        """Handle successful connection"""
        self._connect_btn.setEnabled(False)
        self._disconnect_btn.setEnabled(True)
        self._connection_status.set_status(True)
        self._config_btn.setEnabled(True)
        self._device_combo.setEnabled(False)
        self._ip_input.setEnabled(False)

        try:
            info = self._client.get_device_info()
            self._device_info.setText(
                f"Firmware: {info.firmware_version} | Battery: {info.battery_level}%"
            )

            # Get detected probes
            probes = self._client.get_hardware_configuration()
            probe_info = []
            for name, probe_data in probes.items():
                probe_type = probe_data.get("probe_type", ProbeType.NO_PROBE)
                if (
                    isinstance(probe_type, ProbeType)
                    and probe_type != ProbeType.NO_PROBE
                ):
                    probe_info.append(f"{name}: {probe_type.bio_channels}ch")
                elif isinstance(probe_type, int) and probe_type > 0:
                    probe_info.append(f"{name}: probe type {probe_type}")

            if probe_info:
                self._probes_label.setText("Detected: " + ", ".join(probe_info))
                self._probes_label.setStyleSheet("color: #48BB78;")
            else:
                self._probes_label.setText("No probes detected")
                self._probes_label.setStyleSheet("color: #F6AD55;")
        except Exception as e:
            print(f"Error getting device info: {e}")

        self._config_status.setText("Click to configure...")
        self.connectionChanged.emit(True)

    def _on_disconnected(self):
        """Handle disconnection"""
        self._connect_btn.setEnabled(True)
        self._disconnect_btn.setEnabled(False)
        self._connection_status.set_status(False)
        self._config_btn.setEnabled(False)
        self._visualise_btn.setEnabled(False)
        self._device_combo.setEnabled(True)
        self._ip_input.setEnabled(True)
        self._device_info.setText("")
        self._probes_label.setText("Connect to see detected probes")
        self._probes_label.setStyleSheet("color: #9da3ab; font-style: italic;")
        self._config_status.setText("")
        self._preview_input_combo.clear()
        self._preview_input_combo.setEnabled(False)
        self._viz_status.setText("Disconnected")
        self._live_value_label.setText(
            "Value: ----------------------------------------"
        )

        self._config = None
        self._is_visualising = False
        self._visualizing_input = None
        self._display_timer.stop()
        self._multi_plot.clear()
        self._multi_plot.set_channel_names(["No input selected"])

        self.connectionChanged.emit(False)

    def _open_config_dialog(self):
        """Open the configuration dialog"""
        from gui.config_dialog import NovecentoConfigDialog

        # Create dialog with current config or default
        dialog = NovecentoConfigDialog(self, self._config)

        # Set probe types from hardware if available
        if self._client:
            try:
                probes = self._client.get_hardware_configuration()
                probe_types = {}
                for name, probe_data in probes.items():
                    probe_type = probe_data.get("probe_type", ProbeType.NO_PROBE)
                    if isinstance(probe_type, ProbeType):
                        probe_types[name] = probe_type
                    elif isinstance(probe_type, int):
                        probe_types[name] = (
                            ProbeType(probe_type)
                            if probe_type <= 6
                            else ProbeType.NO_PROBE
                        )
                dialog.set_probe_types(probe_types)
            except Exception as e:
                print(f"Error setting probe types: {e}")

        dialog.config_saved.connect(self._on_config_applied)
        dialog.exec()

    def _on_config_applied(self, config: NovecentoConfiguration):
        """Handle configuration applied from dialog"""
        self._config = config

        # Apply to client
        if self._client:
            try:
                self._client.apply_configuration(config)
            except Exception as e:
                print(f"Error applying configuration: {e}")

        # Update display refresh from config
        self._display_refresh_ms = config.display_refresh_ms
        self._refresh_spin.setValue(config.display_refresh_ms)

        # Update UI
        n_emg = config.total_emg_channels
        n_aux = config.total_aux_channels
        self._config_status.setText(f"{n_emg} EMG ch, {n_aux} AUX ch")
        self._config_status.setStyleSheet("color: #48BB78;")

        # Populate preview dropdown
        self._preview_input_combo.clear()
        for input_name in sorted(config.enabled_inputs, key=lambda x: int(x[2:])):
            inp = config.inputs[input_name]
            self._preview_input_combo.addItem(
                f"{input_name} ({inp.num_channels} ch)", input_name
            )
        for aux_name in sorted(config.aux_channels):
            self._preview_input_combo.addItem(f"{aux_name} (1 ch)", aux_name)

        self._preview_input_combo.setEnabled(True)
        self._visualise_btn.setEnabled(True)
        self._viz_status.setText("Ready")
        self._viz_status.setStyleSheet("color: #48BB78;")

        # Get active channels and emit
        if self._client:
            try:
                channels = self._client.get_active_channels()
                self.channelsChanged.emit(
                    channels.get("emg", []), channels.get("aux", [])
                )
            except:
                self.channelsChanged.emit([], [])

        self.configurationChanged.emit(config)

    def _on_preview_input_changed(self, text: str):
        """Handle preview input selection change"""
        if self._is_visualising:
            self._stop_visualisation()
            self._start_visualisation()

    def _toggle_visualisation(self):
        """Toggle live visualization"""
        if self._is_visualising:
            self._stop_visualisation()
        else:
            self._start_visualisation()

    def _start_visualisation(self):
        """Start live visualization for selected input"""
        if not self._client or not self._client.is_connected:
            return
        if not self._config:
            QMessageBox.warning(
                self, "Not Configured", "Please configure the device first"
            )
            return

        input_id = self._preview_input_combo.currentData()
        if not input_id:
            return

        self._visualizing_input = input_id
        self._latest_value = 0.0

        # Clear the sample buffer
        self._sample_buffer.clear()

        # Determine channel count and names
        if input_id.startswith("IN"):
            inp = self._config.inputs.get(input_id)
            n_channels = inp.num_channels if inp else 0
            channel_names = [f"CH{i:02d}" for i in range(1, n_channels + 1)]
        else:
            n_channels = 1
            channel_names = [input_id]

        # Configure plot
        self._multi_plot.set_channel_names(channel_names)
        self._multi_plot.clear()
        self._preview_label.setText(
            f"Live Signal Preview - {input_id} ({n_channels} channels)"
        )

        # Start streaming
        self._client.start_streaming(self._on_stream_data)

        self._is_visualising = True
        self._visualise_btn.setText("Stop")
        self._viz_status.setText("Streaming...")
        self._viz_status.setStyleSheet("color: #4a9eff;")

        # START DISPLAY TIMER at configured refresh rate
        self._display_timer.start(self._display_refresh_ms)

    def _stop_visualisation(self):
        """Stop live visualization"""
        if self._client and self._client.is_streaming:
            self._client.stop_streaming()

        self._is_visualising = False
        self._visualizing_input = None
        self._visualise_btn.setText("Start")
        self._viz_status.setText("Stopped")
        self._viz_status.setStyleSheet("color: #9da3ab;")
        self._display_timer.stop()
        self._sample_buffer.clear()

    def _on_stream_data(self, data):
        """
        Handle incoming stream data FROM BACKGROUND THREAD.
        Just buffers data - does NOT touch GUI!
        """
        # First, handle visualization if active
        if self._visualizing_input and self._config:
            samples = None

            if self._visualizing_input.startswith("IN"):
                # EMG input - find offset in data array
                offset = 0
                for input_name in sorted(
                    self._config.inputs.keys(), key=lambda x: int(x[2:])
                ):
                    if input_name == self._visualizing_input:
                        break
                    inp = self._config.inputs[input_name]
                    if inp.is_enabled:
                        offset += inp.num_channels

                inp = self._config.inputs.get(self._visualizing_input)
                n_ch = inp.num_channels if inp else 0

                if (
                    data.emg_samples.shape[0] > 0
                    and offset + n_ch <= data.emg_samples.shape[0]
                ):
                    samples = data.emg_samples[offset : offset + n_ch].copy()
            else:
                # AUX channel
                active_aux = sorted(list(self._config.aux_channels))

                if self._visualizing_input in active_aux:
                    idx = active_aux.index(self._visualizing_input)

                    if data.aux_samples.shape[0] > idx:
                        samples = data.aux_samples[idx : idx + 1, :].copy()

            # Add to thread-safe buffer (deque.append is atomic)
            if samples is not None and samples.size > 0:
                self._sample_buffer.append(samples)
                self._latest_value = float(samples[0, -1])

        # Call any additional stream consumers (e.g., calibration tab)
        for consumer in self._additional_stream_consumers:
            try:
                consumer(data)
            except Exception as e:
                print(f"Stream consumer error: {e}")

    def _update_display(self):
        """
        TIMER CALLBACK - Updates GUI at fixed interval.
        Called every _display_refresh_ms milliseconds.
        Processes all buffered samples and updates plot.
        """
        # Drain the buffer and add all samples to plot
        samples_to_add = []
        while True:
            try:
                samples = self._sample_buffer.popleft()
                samples_to_add.append(samples)
            except IndexError:
                break  # Buffer empty

        # Concatenate and add to plot in one batch
        if samples_to_add:
            combined = np.concatenate(samples_to_add, axis=1)
            self._multi_plot.add_samples(combined)

        # Update live value label
        self._live_value_label.setText(f"Value: {self._latest_value:.4f}")

    def _browse_folder(self):
        """Browse for data folder"""
        folder = QFileDialog.getExistingDirectory(self, "Select Data Folder")
        if folder:
            self._folder_input.setText(folder)
            self.dataFolderChanged.emit(folder)

    def _on_subject_changed(self):
        """Handle subject ID change"""
        self.subjectChanged.emit(self._subject_input.text())

    def client(self):
        return self._client

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    @property
    def configuration(self) -> Optional[NovecentoConfiguration]:
        return self._config

    @property
    def subject_id(self) -> str:
        return self._subject_input.text().strip()

    @property
    def data_folder(self) -> str:
        return self._folder_input.text()

    def get_client(self):
        return self._client

    def get_subject_id(self) -> str:
        return self._subject_input.text().strip()

    def set_subject_id(self, subject_id: str):
        """Set subject ID programmatically"""
        self._subject_input.setText(subject_id)

    def get_data_folder(self) -> str:
        return self._folder_input.text()

    def get_file_format(self) -> str:
        """Get current file format selection"""
        return self._format_combo.currentText()

    def get_emg_channels(self) -> List[str]:
        if self._client:
            try:
                return self._client.get_active_channels().get("emg", [])
            except:
                pass
        return []

    def get_aux_channels(self) -> List[str]:
        if self._client:
            try:
                return self._client.get_active_channels().get("aux", [])
            except:
                pass
        return []

    def register_stream_consumer(self, callback: Callable):
        """
        Register an additional consumer of stream data.
        Used by other tabs (e.g., calibration) to receive data without
        interfering with visualization/recording.
        """
        if callback not in self._additional_stream_consumers:
            self._additional_stream_consumers.append(callback)
            print(f"Registered stream consumer: {callback.__name__}")

    def unregister_stream_consumer(self, callback: Callable):
        """Unregister a stream consumer"""
        if callback in self._additional_stream_consumers:
            self._additional_stream_consumers.remove(callback)
            print(f"Unregistered stream consumer: {callback.__name__}")
