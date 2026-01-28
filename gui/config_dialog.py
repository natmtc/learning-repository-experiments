"""
Novecento+ Configuration Dialog
Complete GUI for configuring all protocol parameters.

Exposes ALL parameters that affect the 15-byte CRC8 command:
- Per-input: Mode, Gain, HPF, HRES, Sampling Rate
- AUX sampling frequency  
- Analog output: Source input, channel, gain
- Display/buffer settings
- Live 15-byte command preview with CRC8
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout,
    QLabel, QPushButton, QComboBox, QCheckBox, QSpinBox, QDoubleSpinBox,
    QGroupBox, QTabWidget, QWidget, QScrollArea, QFrame, QLineEdit,
    QMessageBox, QTextEdit, QSplitter, QFileDialog, QSizePolicy
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont

from typing import Dict, Optional
from datetime import datetime

from core.novecento_config import (
    NovecentoConfiguration, InputConfiguration,
    SamplingRate, WorkingMode, Gain, AnalogOutGain, ProbeType,
    compute_crc8, calculate_packet_info, format_config_bytes
)


class InputConfigWidget(QGroupBox):
    """Widget for configuring a single input (IN1-IN10)"""
    
    configChanged = Signal()
    
    def __init__(self, input_number: int, parent=None):
        super().__init__(f"IN{input_number}", parent)
        self._input_number = input_number
        self._config = InputConfiguration()
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QGridLayout(self)
        layout.setSpacing(4)
        
        # Set minimum size for the widget
        self.setMinimumHeight(180)
        self.setMinimumWidth(150)  # Increased from 200 to 250
        
        row = 0
        
        # Enable checkbox
        self._enable_cb = QCheckBox("Enable")
        self._enable_cb.stateChanged.connect(self._on_changed)
        layout.addWidget(self._enable_cb, row, 0, 1, 2)
        
        # Probe type (read-only from hardware, but can override for testing)
        self._probe_label = QLabel("No probe")
        self._probe_label.setStyleSheet("color: #888;")
        layout.addWidget(self._probe_label, row, 2)
        row += 1
        
        # Mode
        layout.addWidget(QLabel("Mode:"), row, 0)
        self._mode_combo = QComboBox()
        self._mode_combo.addItem("Monopolar", WorkingMode.MONOPOLAR)
        self._mode_combo.addItem("Impedance", WorkingMode.IMPEDANCE_CHECK)
        self._mode_combo.addItem("Test", WorkingMode.TEST_MODE)
        self._mode_combo.currentIndexChanged.connect(self._on_changed)
        layout.addWidget(self._mode_combo, row, 1, 1, 2)
        row += 1
        
        # Gain
        layout.addWidget(QLabel("Gain:"), row, 0)
        self._gain_combo = QComboBox()
        self._gain_combo.addItem("x2 (HRES) / x8", Gain.GAIN_2)
        self._gain_combo.addItem("x4", Gain.GAIN_4)
        self._gain_combo.addItem("x6", Gain.GAIN_6)
        self._gain_combo.addItem("x8", Gain.GAIN_8)
        self._gain_combo.setCurrentIndex(1)  # Default to Gain 4
        self._gain_combo.currentIndexChanged.connect(self._on_changed)
        layout.addWidget(self._gain_combo, row, 1, 1, 2)
        row += 1
        
        # Sampling Rate
        layout.addWidget(QLabel("Fs:"), row, 0)
        self._fsamp_combo = QComboBox()
        self._fsamp_combo.addItem("500 Hz", SamplingRate.HZ_500)
        self._fsamp_combo.addItem("2000 Hz", SamplingRate.HZ_2000)
        self._fsamp_combo.addItem("4000 Hz", SamplingRate.HZ_4000)
        self._fsamp_combo.addItem("8000 Hz", SamplingRate.HZ_8000)
        self._fsamp_combo.setCurrentIndex(1)  # Default 2000 Hz
        self._fsamp_combo.currentIndexChanged.connect(self._on_changed)
        layout.addWidget(self._fsamp_combo, row, 1, 1, 2)
        row += 1
        
        # HPF and HRES checkboxes
        hbox = QHBoxLayout()
        self._hpf_cb = QCheckBox("HPF")
        self._hpf_cb.setChecked(True)
        self._hpf_cb.setToolTip("High-pass filter (cutoff = Fs/190 Hz)")
        self._hpf_cb.stateChanged.connect(self._on_changed)
        hbox.addWidget(self._hpf_cb)
        
        self._hres_cb = QCheckBox("24-bit")
        self._hres_cb.setToolTip("High resolution (24-bit samples, 4 bytes/sample)")
        self._hres_cb.stateChanged.connect(self._on_changed)
        hbox.addWidget(self._hres_cb)
        layout.addLayout(hbox, row, 0, 1, 3)
        row += 1
        
        # Info labels
        self._info_label = QLabel()
        self._info_label.setStyleSheet("color: #666; font-size: 10px;")
        layout.addWidget(self._info_label, row, 0, 1, 3)
        
        self._update_info()
    
    def _on_changed(self):
        self._update_info()
        self.configChanged.emit()
    
    def _update_info(self):
        """Update info label with computed values"""
        fsamp = self._fsamp_combo.currentData()
        hpf = self._hpf_cb.isChecked()
        hres = self._hres_cb.isChecked()
        gain = self._gain_combo.currentData()
        
        if fsamp and gain:
            hpf_cutoff = fsamp.frequency / 190.0 if hpf else 0
            actual_gain = gain.get_actual_gain(hres)
            range_mv = gain.get_range_mv(hres)
            
            info = f"Gain: x{actual_gain} | Range: ±{range_mv:.1f}mV"
            if hpf:
                info += f" | HPF: {hpf_cutoff:.1f}Hz"
            self._info_label.setText(info)
    
    def set_config(self, config: InputConfiguration):
        """Set widget state from configuration"""
        self._config = config
        
        # Block signals during update
        for w in [self._enable_cb, self._mode_combo, self._gain_combo,
                  self._fsamp_combo, self._hpf_cb, self._hres_cb]:
            w.blockSignals(True)
        
        self._enable_cb.setChecked(config.is_enabled)
        
        for i in range(self._mode_combo.count()):
            if self._mode_combo.itemData(i) == config.mode:
                self._mode_combo.setCurrentIndex(i)
                break
        
        for i in range(self._gain_combo.count()):
            if self._gain_combo.itemData(i) == config.gain:
                self._gain_combo.setCurrentIndex(i)
                break
        
        for i in range(self._fsamp_combo.count()):
            if self._fsamp_combo.itemData(i) == config.sampling_rate:
                self._fsamp_combo.setCurrentIndex(i)
                break
        
        self._hpf_cb.setChecked(config.high_pass_filter)
        self._hres_cb.setChecked(config.high_resolution)
        
        # Update probe label
        if config.probe_type != ProbeType.NO_PROBE:
            self._probe_label.setText(f"{config.probe_type.bio_channels}ch probe")
            self._probe_label.setStyleSheet("color: #4a9eff;")
        else:
            self._probe_label.setText("No probe")
            self._probe_label.setStyleSheet("color: #888;")
        
        for w in [self._enable_cb, self._mode_combo, self._gain_combo,
                  self._fsamp_combo, self._hpf_cb, self._hres_cb]:
            w.blockSignals(False)
        
        self._update_info()
    
    def get_config(self) -> InputConfiguration:
        """Get configuration from widget state"""
        return InputConfiguration(
            is_enabled=self._enable_cb.isChecked(),
            mode=self._mode_combo.currentData() or WorkingMode.MONOPOLAR,
            gain=self._gain_combo.currentData() or Gain.GAIN_4,
            high_pass_filter=self._hpf_cb.isChecked(),
            high_resolution=self._hres_cb.isChecked(),
            sampling_rate=self._fsamp_combo.currentData() or SamplingRate.HZ_2000,
            probe_type=self._config.probe_type,
            muscle_name=self._config.muscle_name,
            side=self._config.side,
            placement=self._config.placement
        )
    
    def set_probe_type(self, probe_type: ProbeType):
        """Set detected probe type"""
        self._config.probe_type = probe_type
        if probe_type != ProbeType.NO_PROBE:
            self._probe_label.setText(f"{probe_type.bio_channels}ch probe")
            self._probe_label.setStyleSheet("color: #4a9eff;")
        else:
            self._probe_label.setText("No probe")
            self._probe_label.setStyleSheet("color: #888;")


class AuxConfigWidget(QGroupBox):
    """Widget for configuring auxiliary channels"""
    
    configChanged = Signal()
    
    def __init__(self, parent=None):
        super().__init__("AUX Channels (16 channels: 4 AUX + 2 LOAD CELL + 10 EXT)", parent)
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Sampling rate
        fsamp_layout = QHBoxLayout()
        fsamp_layout.addWidget(QLabel("Sampling Rate:"))
        self._fsamp_combo = QComboBox()
        self._fsamp_combo.addItem("500 Hz (32 B/2ms)", SamplingRate.HZ_500)
        self._fsamp_combo.addItem("2000 Hz (128 B/2ms)", SamplingRate.HZ_2000)
        self._fsamp_combo.addItem("4000 Hz (256 B/2ms)", SamplingRate.HZ_4000)
        self._fsamp_combo.addItem("8000 Hz (512 B/2ms)", SamplingRate.HZ_8000)
        self._fsamp_combo.setCurrentIndex(1)  # Default 2000 Hz
        self._fsamp_combo.currentIndexChanged.connect(self._on_changed)
        fsamp_layout.addWidget(self._fsamp_combo)
        fsamp_layout.addStretch()
        layout.addLayout(fsamp_layout)
        
        # Channel selection grid
        self._channel_frame = QFrame()
        self._channel_frame.setMinimumHeight(120)  # Ensure adequate height for checkboxes
        channel_layout = QGridLayout(self._channel_frame)
        channel_layout.setSpacing(4)
        
        self._channel_cbs = []
        labels = ["AUX1", "AUX2", "AUX3", "AUX4", 
                  "LC1", "LC2",
                  "EXT1", "EXT2", "EXT3", "EXT4", "EXT5", 
                  "EXT6", "EXT7", "EXT8", "EXT9", "EXT10"]
        
        for i, label in enumerate(labels):
            cb = QCheckBox(label)
            cb.setChecked(i < 4)  # Default: first 4 (AUX1-4) checked
            cb.stateChanged.connect(self._on_changed)
            self._channel_cbs.append(cb)
            channel_layout.addWidget(cb, i // 8, i % 8)
        
        layout.addWidget(self._channel_frame, 1)  # Give it stretch factor
        
        # Info
        self._info_label = QLabel("Resolution: 16-bit | Always enabled")
        self._info_label.setStyleSheet("color: #666; font-size: 10px;")
        layout.addWidget(self._info_label)
    
    def _on_changed(self):
        self.configChanged.emit()
    
    def get_sampling_rate(self) -> SamplingRate:
        return self._fsamp_combo.currentData() or SamplingRate.HZ_2000
    
    def get_enabled_channels(self) -> set:
        labels = ["AUX1", "AUX2", "AUX3", "AUX4", 
                  "LC1", "LC2",
                  "EXT1", "EXT2", "EXT3", "EXT4", "EXT5", 
                  "EXT6", "EXT7", "EXT8", "EXT9", "EXT10"]
        return {labels[i] for i, cb in enumerate(self._channel_cbs) if cb.isChecked()}
    
    def set_sampling_rate(self, rate: SamplingRate):
        for i in range(self._fsamp_combo.count()):
            if self._fsamp_combo.itemData(i) == rate:
                self._fsamp_combo.setCurrentIndex(i)
                break
    
    def set_enabled_channels(self, channels: set):
        labels = ["AUX1", "AUX2", "AUX3", "AUX4", 
                  "LC1", "LC2",
                  "EXT1", "EXT2", "EXT3", "EXT4", "EXT5", 
                  "EXT6", "EXT7", "EXT8", "EXT9", "EXT10"]
        for i, cb in enumerate(self._channel_cbs):
            cb.setChecked(labels[i] in channels)


class AnalogOutputWidget(QGroupBox):
    """Widget for configuring analog output"""
    
    configChanged = Signal()
    
    def __init__(self, parent=None):
        super().__init__("Analog Output (BNC)", parent)
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QFormLayout(self)
        
        # Source input
        self._input_spin = QSpinBox()
        self._input_spin.setRange(1, 10)
        self._input_spin.setValue(1)
        self._input_spin.valueChanged.connect(self._on_changed)
        layout.addRow("Source Input (IN1-10):", self._input_spin)
        
        # Source channel
        self._channel_spin = QSpinBox()
        self._channel_spin.setRange(0, 101)
        self._channel_spin.setValue(0)
        self._channel_spin.setToolTip("0-based channel index")
        self._channel_spin.valueChanged.connect(self._on_changed)
        layout.addRow("Channel (0-based):", self._channel_spin)
        
        # Output gain
        self._gain_combo = QComboBox()
        self._gain_combo.addItem("x1", 1)
        self._gain_combo.addItem("x2", 2)
        self._gain_combo.addItem("x4", 4)
        self._gain_combo.addItem("x16", 16)
        self._gain_combo.currentIndexChanged.connect(self._on_changed)
        layout.addRow("Output Gain:", self._gain_combo)
        
        # Info
        info = QLabel("Note: 3 sample delay on analog output")
        info.setStyleSheet("color: #888; font-size: 10px;")
        layout.addRow(info)
    
    def _on_changed(self):
        self.configChanged.emit()
    
    def get_config(self) -> tuple:
        """Returns (input, channel, gain)"""
        return (
            self._input_spin.value(),
            self._channel_spin.value(),
            self._gain_combo.currentData() or 1
        )
    
    def set_config(self, input_num: int, channel: int, gain: int):
        self._input_spin.setValue(input_num)
        self._channel_spin.setValue(channel)
        for i in range(self._gain_combo.count()):
            if self._gain_combo.itemData(i) == gain:
                self._gain_combo.setCurrentIndex(i)
                break


class DisplaySettingsWidget(QGroupBox):
    """Widget for display and buffer settings"""
    
    configChanged = Signal()
    
    def __init__(self, parent=None):
        super().__init__("Display & Buffer Settings", parent)
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QFormLayout(self)
        
        # Refresh rate
        self._refresh_spin = QSpinBox()
        self._refresh_spin.setRange(20, 500)
        self._refresh_spin.setValue(200)
        self._refresh_spin.setSuffix(" ms")
        self._refresh_spin.setToolTip("Display update interval (OT default: 200ms)")
        self._refresh_spin.valueChanged.connect(self._on_changed)
        layout.addRow("Refresh Rate:", self._refresh_spin)
        
        # Plot time - DISPLAY BUFFER DURATION (NOT streaming frequency!)
        # The hardware_client streams in 50ms chunks regardless of this setting
        self._plot_time_spin = QDoubleSpinBox()
        self._plot_time_spin.setRange(0.5, 10.0)
        self._plot_time_spin.setValue(2.0)  # 2 seconds of display history
        self._plot_time_spin.setSuffix(" s")
        self._plot_time_spin.setDecimals(1)
        self._plot_time_spin.setSingleStep(0.5)
        self._plot_time_spin.setToolTip("Display history duration (how many seconds to show on screen)")
        self._plot_time_spin.valueChanged.connect(self._on_changed)
        layout.addRow("Display History:", self._plot_time_spin)
        
        # Vertical offset
        self._offset_spin = QDoubleSpinBox()
        self._offset_spin.setRange(0.0, 10.0)
        self._offset_spin.setValue(2.0)
        self._offset_spin.setDecimals(1)
        self._offset_spin.setToolTip("Vertical offset between channels for display")
        self._offset_spin.valueChanged.connect(self._on_changed)
        layout.addRow("Channel Offset:", self._offset_spin)
    
    def _on_changed(self):
        self.configChanged.emit()
    
    def get_config(self) -> tuple:
        """Returns (refresh_ms, plot_time_s, offset)"""
        return (
            self._refresh_spin.value(),
            self._plot_time_spin.value(),
            self._offset_spin.value()
        )
    
    def set_config(self, refresh_ms: int, plot_time: float, offset: float):
        self._refresh_spin.setValue(refresh_ms)
        self._plot_time_spin.setValue(plot_time)
        self._offset_spin.setValue(offset)


class ConfigPreviewWidget(QGroupBox):
    """Widget showing the 15-byte configuration command preview"""
    
    def __init__(self, parent=None):
        super().__init__("15-Byte Configuration Command Preview", parent)
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Command bytes display
        self._cmd_text = QTextEdit()
        self._cmd_text.setReadOnly(True)
        self._cmd_text.setFont(QFont("Courier New", 9))
        self._cmd_text.setMaximumHeight(320)
        layout.addWidget(self._cmd_text)
        
        # Packet info
        self._info_label = QLabel()
        self._info_label.setStyleSheet("color: #4a9eff;")
        layout.addWidget(self._info_label)
    
    def update_preview(self, config: NovecentoConfiguration):
        """Update preview with current configuration"""
        try:
            config_bytes = config.build_config_bytes()
            text = format_config_bytes(config_bytes)
            self._cmd_text.setPlainText(text)
            
            info = calculate_packet_info(config)
            self._info_label.setText(
                f"2ms block: {info['total_2ms_block']} bytes | \n"
                f"Rate: {info['bytes_per_second']:,} B/s | \n"
                f"Buffer: {info['buffer_size']:,} bytes"
            )
        except Exception as e:
            self._cmd_text.setPlainText(f"Error: {e}")
            self._info_label.setText("")


class NovecentoConfigDialog(QDialog):
    """
    Main configuration dialog exposing all protocol parameters.
    """
    
    config_saved = Signal(object)  # Emits NovecentoConfiguration
    
    def __init__(self, parent=None, initial_config: Optional[NovecentoConfiguration] = None):
        super().__init__(parent)
        
        self._config = initial_config.copy() if initial_config else NovecentoConfiguration.create_default()
        
        self.setWindowTitle("Novecento+ Configuration - All Protocol Parameters")
        self.setMinimumSize(1200, 800)  # Increased width from 1000 to 1200
        self.resize(1400, 850)  # Increased initial width from 1200 to 1400
        self.setModal(True)
        
        self._setup_ui()
        self._load_config()
        self._update_preview()
        self._apply_styling()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Main splitter
        splitter = QSplitter(Qt.Horizontal)
        
        # Left side - Configuration
        config_widget = QWidget()
        config_layout = QVBoxLayout(config_widget)
        
        # Tabs for different sections
        tabs = QTabWidget()
        
        # ===== Inputs Tab =====
        inputs_tab = QWidget()
        inputs_layout = QVBoxLayout(inputs_tab)
        
        # Scroll area for inputs
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(450)  # Ensure adequate height for all 10 inputs
        scroll_widget = QWidget()
        scroll_layout = QGridLayout(scroll_widget)
        scroll_layout.setSpacing(8)  # Add spacing between widgets
        
        self._input_widgets: Dict[str, InputConfigWidget] = {}
        for i in range(10):
            input_num = i + 1
            widget = InputConfigWidget(input_num)
            widget.configChanged.connect(self._on_config_changed)
            self._input_widgets[f"IN{input_num}"] = widget
            scroll_layout.addWidget(widget, i // 5, i % 5)
        
        scroll.setWidget(scroll_widget)
        inputs_layout.addWidget(scroll, 1)  # Give stretch factor
        
        # Quick controls
        quick_layout = QHBoxLayout()
        
        enable_all_btn = QPushButton("Enable All With Probes")
        enable_all_btn.clicked.connect(self._enable_all_inputs)
        quick_layout.addWidget(enable_all_btn)
        
        disable_all_btn = QPushButton("Disable All")
        disable_all_btn.clicked.connect(self._disable_all_inputs)
        quick_layout.addWidget(disable_all_btn)
        
        quick_layout.addWidget(QLabel("Set All Fs:"))
        self._global_fsamp = QComboBox()
        self._global_fsamp.addItem("500 Hz", SamplingRate.HZ_500)
        self._global_fsamp.addItem("2000 Hz", SamplingRate.HZ_2000)
        self._global_fsamp.addItem("4000 Hz", SamplingRate.HZ_4000)
        self._global_fsamp.addItem("8000 Hz", SamplingRate.HZ_8000)
        self._global_fsamp.setCurrentIndex(1)
        self._global_fsamp.currentIndexChanged.connect(self._apply_global_fsamp)
        quick_layout.addWidget(self._global_fsamp)
        
        quick_layout.addStretch()
        inputs_layout.addLayout(quick_layout)
        
        tabs.addTab(inputs_tab, "Inputs (IN1-IN10)")
        
        # ===== AUX & Analog Tab =====
        aux_tab = QWidget()
        aux_layout = QVBoxLayout(aux_tab)
        
        self._aux_widget = AuxConfigWidget()
        self._aux_widget.configChanged.connect(self._on_config_changed)
        aux_layout.addWidget(self._aux_widget)
        
        self._analog_widget = AnalogOutputWidget()
        self._analog_widget.configChanged.connect(self._on_config_changed)
        aux_layout.addWidget(self._analog_widget)
        
        aux_layout.addStretch()
        
        tabs.addTab(aux_tab, "AUX & Analog Out")
        
        # ===== Display Tab =====
        display_tab = QWidget()
        display_layout = QVBoxLayout(display_tab)
        
        self._display_widget = DisplaySettingsWidget()
        self._display_widget.configChanged.connect(self._on_config_changed)
        display_layout.addWidget(self._display_widget)
        
        # Connection settings
        conn_group = QGroupBox("TCP Connection")
        conn_layout = QFormLayout(conn_group)
        
        self._ip_edit = QLineEdit()
        self._ip_edit.setText("169.254.1.10")
        self._ip_edit.setToolTip("Device IP address (default: 169.254.1.10)")
        conn_layout.addRow("IP Address:", self._ip_edit)
        
        self._port_spin = QSpinBox()
        self._port_spin.setRange(1, 65535)
        self._port_spin.setValue(23456)
        self._port_spin.setToolTip("TCP port (default: 23456)")
        conn_layout.addRow("TCP Port:", self._port_spin)
        
        display_layout.addWidget(conn_group)
        display_layout.addStretch()
        
        tabs.addTab(display_tab, "Display & Connection")
        
        config_layout.addWidget(tabs)
        splitter.addWidget(config_widget)
        
        # Right side - Preview
        self._preview_widget = ConfigPreviewWidget()
        splitter.addWidget(self._preview_widget)
        
        splitter.setSizes([800, 250])
        layout.addWidget(splitter)
        
        # Summary
        self._summary_label = QLabel()
        self._summary_label.setStyleSheet("font-style: italic; color: #9da3ab;")
        layout.addWidget(self._summary_label)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        save_btn = QPushButton("Save Config...")
        save_btn.clicked.connect(self._save_config)
        button_layout.addWidget(save_btn)
        
        load_btn = QPushButton("Load Config...")
        load_btn.clicked.connect(self._load_config_file)
        button_layout.addWidget(load_btn)
        
        validate_btn = QPushButton("Validate")
        validate_btn.clicked.connect(self._validate)
        button_layout.addWidget(validate_btn)
        
        button_layout.addStretch()
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        apply_btn = QPushButton("Apply")
        apply_btn.setStyleSheet("background-color: #48BB78;")
        apply_btn.clicked.connect(self._apply)
        apply_btn.setDefault(True)
        button_layout.addWidget(apply_btn)
        
        layout.addLayout(button_layout)
    
    def _apply_styling(self):
        """Apply dark theme styling"""
        self.setStyleSheet("""
            QDialog { background-color: #1a1d21; color: #e8eaed; }
            QGroupBox {
                font-weight: bold;
                border: 1px solid #3d4248;
                border-radius: 6px;
                margin-top: 10px;
                padding-top: 10px;
                background-color: #21252b;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
                color: #e8eaed;
            }
            QCheckBox { color: #e8eaed; }
            QCheckBox::indicator {
                width: 16px; height: 16px;
                border-radius: 3px;
                border: 1px solid #4a5568;
                background-color: #2d3139;
            }
            QCheckBox::indicator:checked {
                background-color: #48BB78;
                border-color: #48BB78;
            }
            QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {
                background-color: #2d3139;
                border: 1px solid #4a5568;
                border-radius: 4px;
                padding: 4px 8px;
                color: #e8eaed;
            }
            QComboBox:hover, QSpinBox:hover, QLineEdit:hover { border-color: #4a9eff; }
            QPushButton {
                background-color: #003E74;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                color: white;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #004d91; }
            QTextEdit {
                background-color: #2d3139;
                border: 1px solid #4a5568;
                border-radius: 4px;
                color: #e8eaed;
            }
            QScrollArea { border: 1px solid #3d4248; background-color: #1a1d21; }
            QLabel { color: #e8eaed; }
            QTabWidget::pane { border: 1px solid #3d4248; }
            QTabBar::tab {
                background-color: #2d3139;
                color: #e8eaed;
                padding: 8px 16px;
                border: 1px solid #3d4248;
            }
            QTabBar::tab:selected { background-color: #003E74; }
        """)
    
    def _load_config(self):
        """Load configuration into widgets"""
        for name, widget in self._input_widgets.items():
            if name in self._config.inputs:
                widget.set_config(self._config.inputs[name])
        
        self._aux_widget.set_sampling_rate(self._config.aux_sampling_rate)
        self._aux_widget.set_enabled_channels(self._config.aux_channels)
        
        self._analog_widget.set_config(
            self._config.analog_out_input,
            self._config.analog_out_channel,
            self._config.analog_out_gain
        )
        
        self._display_widget.set_config(
            self._config.display_refresh_ms,
            self._config.plot_time_seconds,
            self._config.vertical_offset
        )
        
        self._ip_edit.setText(self._config.ip_address)
        self._port_spin.setValue(self._config.port)
        
        self._update_summary()
    
    def _gather_config(self) -> NovecentoConfiguration:
        """Gather configuration from all widgets"""
        config = NovecentoConfiguration()
        
        for name, widget in self._input_widgets.items():
            config.inputs[name] = widget.get_config()
        
        config.aux_sampling_rate = self._aux_widget.get_sampling_rate()
        config.aux_channels = self._aux_widget.get_enabled_channels()
        
        an_input, an_channel, an_gain = self._analog_widget.get_config()
        config.analog_out_input = an_input
        config.analog_out_channel = an_channel
        config.analog_out_gain = an_gain
        
        refresh_ms, plot_time, offset = self._display_widget.get_config()
        config.display_refresh_ms = refresh_ms
        config.plot_time_seconds = plot_time
        config.vertical_offset = offset
        
        config.ip_address = self._ip_edit.text()
        config.port = self._port_spin.value()
        
        return config
    
    def _on_config_changed(self):
        """Handle any configuration change"""
        self._update_preview()
        self._update_summary()
    
    def _update_preview(self):
        """Update command preview"""
        config = self._gather_config()
        self._preview_widget.update_preview(config)
    
    def _update_summary(self):
        """Update summary label"""
        config = self._gather_config()
        n_emg = config.total_emg_channels
        n_aux = len(config.aux_channels)
        enabled = len(config.enabled_inputs)
        self._summary_label.setText(
            f"Total: {enabled} inputs enabled, {n_emg} EMG channels, {n_aux} AUX channels"
        )
    
    def _enable_all_inputs(self):
        """Enable all inputs with detected probes"""
        for name, widget in self._input_widgets.items():
            config = widget.get_config()
            if config.probe_type != ProbeType.NO_PROBE:
                config.is_enabled = True
                widget.set_config(config)
        self._on_config_changed()
    
    def _disable_all_inputs(self):
        """Disable all inputs"""
        for widget in self._input_widgets.values():
            config = widget.get_config()
            config.is_enabled = False
            widget.set_config(config)
        self._on_config_changed()
    
    def _apply_global_fsamp(self):
        """Apply global sampling rate to all inputs and AUX"""
        fsamp = self._global_fsamp.currentData()
        if fsamp:
            for widget in self._input_widgets.values():
                config = widget.get_config()
                config.sampling_rate = fsamp
                widget.set_config(config)
            self._aux_widget.set_sampling_rate(fsamp)
        self._on_config_changed()
    
    def _save_config(self):
        """Save configuration to file"""
        filepath, _ = QFileDialog.getSaveFileName(
            self, "Save Configuration",
            f"novecento_config_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            "JSON Files (*.json)"
        )
        if filepath:
            try:
                config = self._gather_config()
                config.save_to_file(filepath)
                QMessageBox.information(self, "Success", "Configuration saved!")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save: {e}")
    
    def _load_config_file(self):
        """Load configuration from file"""
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Load Configuration", "", "JSON Files (*.json)"
        )
        if filepath:
            try:
                self._config = NovecentoConfiguration.load_from_file(filepath)
                self._load_config()
                self._update_preview()
                QMessageBox.information(self, "Success", "Configuration loaded!")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to load: {e}")
    
    def _validate(self):
        """Validate current configuration"""
        config = self._gather_config()
        warnings = config.validate()
        
        if warnings:
            QMessageBox.warning(
                self, "Configuration Warnings",
                "\n".join(f"\u26A0 {w}" for w in warnings)
            )
        else:
            QMessageBox.information(self, "Validation", "Configuration is valid!")
    
    def _apply(self):
        """Apply and save configuration"""
        config = self._gather_config()
        warnings = config.validate()
        
        if warnings:
            reply = QMessageBox.question(
                self, "Configuration Warnings",
                "There are warnings:\n" + 
                "\n".join(f"\u26A0 {w}" for w in warnings) +
                "\n\nApply anyway?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return
        
        self._config = config
        self.config_saved.emit(config)
        self.accept()
    
    def set_probe_types(self, probe_types: dict):
        """
        Set detected probe types from hardware.
        probe_types: dict mapping 'IN1'-'IN10' to ProbeType
        """
        for name, probe_type in probe_types.items():
            if name in self._input_widgets:
                self._input_widgets[name].set_probe_type(probe_type)
    
    def get_configuration(self) -> NovecentoConfiguration:
        """Get the current configuration"""
        return self._gather_config()