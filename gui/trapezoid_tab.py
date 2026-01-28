"""
Trapezoid Tab - Force-feedback trapezoidal contraction protocol (Training Version).

FIXED:
- Timer-based display updates (not tied to data arrival)
- Proper AUX channel indexing (position in active list, not channel number)
- Configurable refresh rate (original OT code uses 200ms)
- Cursor shows YOUR ACTUAL FORCE, not target
- Force trail shows historical force data
"""

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QComboBox,
    QSpinBox,
    QDoubleSpinBox,
    QGroupBox,
    QProgressBar,
    QMessageBox,
    QToolBar,
    QFrame,
    QCheckBox,
    QScrollArea,
    QLineEdit,
)
from PySide6.QtCore import Qt, Signal, Slot, QTimer
from typing import Optional, List, Tuple, Dict
import numpy as np
import time
from datetime import datetime
from scipy import signal

from clients.mock_client import MockNovecentoClient, StreamData
from core.novecento_config import NovecentoConfiguration
from data.managers import DataRecorder, RecordingMetadata
from gui.widgets import TrapezoidForceWidget


# Original OT code uses Update_time = 200 (200ms)
DEFAULT_DISPLAY_REFRESH_MS = 75  # Slightly faster for real-time feedback


class TrapezoidTab(QWidget):
    """
    Trapezoid tab for force-feedback contractions.

    Protocol phases:
    1. Rest (baseline)
    2. Ramp up (increase force to target)
    3. Hold (maintain target force)
    4. Ramp down (decrease force to baseline)
    5. Rest (recovery)
    """

    protocolStarted = Signal()
    protocolCompleted = Signal()
    protocolStopped = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self._client: Optional[MockNovecentoClient] = None
        self._config: Optional[NovecentoConfiguration] = None
        self._recorder: Optional[DataRecorder] = None

        self._mvc_value: float = 100.0  # Default MVC
        self._offset_value: float = 0.0  # Default offset
        self._data_folder: str = "./data"
        self._subject_id: str = ""

        # Multi-channel support
        self._selected_channels: List[str] = []  # Channels to display
        self._channel_mvc_values: Dict[str, float] = {}
        self._channel_offset_values: Dict[str, float] = {}

        # Protocol state
        self._is_running = False
        self._current_phase = "idle"
        self._phase_start_time: Optional[datetime] = None
        self._protocol_start_time: Optional[datetime] = None

        # Countdown before protocol starts
        self._countdown_active = False
        self._countdown_seconds = 3

        # Display refresh rate (configurable)
        self._display_refresh_ms: int = DEFAULT_DISPLAY_REFRESH_MS

        # Latest force values (updated by data callback, displayed by timer)
        self._latest_force_value: float = 0.0
        self._latest_force_mvc_percent: float = 0.0
        self._latest_channel_values: Dict[str, float] = {}  # All channel values
        self._latest_channel_mvc_percents: Dict[str, float] = {}  # All channel %MVC
        self._latest_data_packet: Optional[dict] = None  # Store full packet for display processing

        # Moving average filter for display (does not affect recording)
        self._filter_enabled = True
        self._filter_window_ms = 20.0  # 20ms moving average window
        self._filter_buffers: Dict[str, List[float]] = {}  # Channel -> sample buffer

        # Active AUX channels list (for proper indexing)
        self._active_aux_channels: List[str] = []
        self._channel_checkboxes: Dict[str, "QCheckBox"] = {}

        # Finger labels for each channel
        self._channel_finger_labels: Dict[str, str] = {}
        self._finger_label_inputs: Dict[str, "QLineEdit"] = {}

        # Summed forces visualization
        self._sum_forces: bool = False

        # Protocol timing (seconds)
        self._rest_duration_start = 5.0
        self._rest_duration_end = 10.0
        self._ramp_duration = 3.0
        self._hold_duration = 20.0
        self._target_mvc_percent = 15.0
        self._tolerance_percent = 5.0

        # TRAINING MODE SPECIFIC
        self._imbalance_threshold_percent = (
            5.0  # Max allowed difference between min and max channel forces
        )
        self._imbalance_detected = False
        self._imbalance_ever_exceeded = (
            False  # Track if tolerance was exceeded at any point
        )
        self._show_post_trial_review = True  # Show individual traces after trial
        self._show_feedback = False  # Show force balance feedback during trial

        # Store individual channel force data for post-trial review (not displayed during trial when summing)
        self._individual_channel_data: Dict[str, List[Tuple[float, float]]] = (
            {}
        )  # channel -> [(time, force), ...]
        
        # Track sample count for post-trial review
        self._last_trial_sample_count: int = 0

        self._setup_ui()

        # DISPLAY TIMER - triggers repaint at fixed interval
        self._display_timer = QTimer()
        self._display_timer.timeout.connect(self._update_display)

        # Protocol phase timer
        self._phase_timer = QTimer()
        self._phase_timer.timeout.connect(self._check_phase)
        
        # Warm-up UI update timer (updates sample counter during warm-up)
        self._warmup_timer = QTimer()
        self._warmup_timer.timeout.connect(self._update_warmup_display)

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)

        # Toolbar with refresh rate control
        toolbar = QToolBar()
        toolbar.addWidget(QLabel("Refresh:"))
        self._refresh_spin = QSpinBox()
        self._refresh_spin.setRange(20, 500)
        self._refresh_spin.setValue(DEFAULT_DISPLAY_REFRESH_MS)
        self._refresh_spin.setSuffix(" ms")
        self._refresh_spin.setToolTip(
            "Display update interval\n"
            "Original OT code: 200ms\n"
            "Lower = smoother but more CPU"
        )
        self._refresh_spin.valueChanged.connect(self._on_refresh_rate_changed)
        toolbar.addWidget(self._refresh_spin)
        toolbar.addSeparator()

        # Filter checkbox
        self._filter_checkbox = QCheckBox("Filter (20ms)")
        self._filter_checkbox.setChecked(True)  # Enabled by default
        self._filter_checkbox.setToolTip("Enable/disable 20ms moving average filter")
        self._filter_checkbox.stateChanged.connect(self._on_filter_toggled)
        toolbar.addWidget(self._filter_checkbox)
        toolbar.addSeparator()

        self._phase_label = QLabel("Phase: Idle")
        self._phase_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        toolbar.addWidget(self._phase_label)

        toolbar.addSeparator()

        self._time_label = QLabel("Time: 0.0s")
        toolbar.addWidget(self._time_label)

        main_layout.addWidget(toolbar)

        # Main content
        content_layout = QHBoxLayout()

        # ============ LEFT PANEL - Controls ============
        controls_widget = QWidget()
        controls_layout = QVBoxLayout(controls_widget)
        controls_widget.setMaximumWidth(350)

        # Protocol Settings
        settings_group = QGroupBox("Protocol Settings")
        settings_layout = QGridLayout(settings_group)

        row = 0
        settings_layout.addWidget(QLabel("Target Force:"), row, 0)
        self._target_spin = QDoubleSpinBox()
        self._target_spin.setRange(5, 100)
        self._target_spin.setValue(15)
        self._target_spin.setSuffix(" % MVC")
        self._target_spin.valueChanged.connect(self._on_settings_changed)
        settings_layout.addWidget(self._target_spin, row, 1)

        row += 1
        settings_layout.addWidget(QLabel("Tolerance:"), row, 0)
        self._tolerance_spin = QDoubleSpinBox()
        self._tolerance_spin.setRange(0.5, 20)  # Allow down to 0.5%
        self._tolerance_spin.setValue(5)
        self._tolerance_spin.setSingleStep(0.5)  # Step by 0.5%
        self._tolerance_spin.setDecimals(1)  # Show 1 decimal place
        self._tolerance_spin.setSuffix(" %")
        self._tolerance_spin.valueChanged.connect(self._on_settings_changed)
        settings_layout.addWidget(self._tolerance_spin, row, 1)

        row += 1
        settings_layout.addWidget(QLabel("Rest Duration (Start):"), row, 0)
        self._rest_start_spin = QDoubleSpinBox()
        self._rest_start_spin.setRange(1, 30)
        self._rest_start_spin.setValue(5)
        self._rest_start_spin.setSuffix(" sec")
        self._rest_start_spin.valueChanged.connect(self._on_settings_changed)
        settings_layout.addWidget(self._rest_start_spin, row, 1)

        row += 1
        settings_layout.addWidget(QLabel("Ramp Duration:"), row, 0)
        self._ramp_spin = QDoubleSpinBox()
        self._ramp_spin.setRange(1, 30)
        self._ramp_spin.setValue(3)
        self._ramp_spin.setSuffix(" sec")
        self._ramp_spin.valueChanged.connect(self._on_settings_changed)
        settings_layout.addWidget(self._ramp_spin, row, 1)

        row += 1
        settings_layout.addWidget(QLabel("Hold Duration:"), row, 0)
        self._hold_spin = QDoubleSpinBox()
        self._hold_spin.setRange(1, 120)
        self._hold_spin.setValue(20)
        self._hold_spin.setSuffix(" sec")
        self._hold_spin.valueChanged.connect(self._on_settings_changed)
        settings_layout.addWidget(self._hold_spin, row, 1)

        row += 1
        settings_layout.addWidget(QLabel("Rest Duration (End):"), row, 0)
        self._rest_end_spin = QDoubleSpinBox()
        self._rest_end_spin.setRange(1, 30)
        self._rest_end_spin.setValue(10)
        self._rest_end_spin.setSuffix(" sec")
        self._rest_end_spin.valueChanged.connect(self._on_settings_changed)
        settings_layout.addWidget(self._rest_end_spin, row, 1)

        controls_layout.addWidget(settings_group)

        # Channel Selection for Display
        channel_sel_group = QGroupBox("Display Channels")
        channel_sel_layout = QVBoxLayout(channel_sel_group)

        channel_sel_layout.addWidget(QLabel("Select channels to plot:"))

        # Scrollable channel list
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(250)  # Fixed height - will scroll if content is taller

        self._channel_list_widget = QWidget()
        self._channel_list_layout = QVBoxLayout(self._channel_list_widget)
        self._channel_list_layout.setContentsMargins(0, 0, 0, 0)
        self._channel_list_layout.setSpacing(2)  # Tight vertical spacing between rows
        scroll.setWidget(self._channel_list_widget)

        channel_sel_layout.addWidget(scroll)

        # Select all/none buttons
        select_btn_layout = QHBoxLayout()
        select_all_btn = QPushButton("All")
        select_all_btn.clicked.connect(self._select_all_channels)
        select_btn_layout.addWidget(select_all_btn)

        select_none_btn = QPushButton("None")
        select_none_btn.clicked.connect(self._select_no_channels)
        select_btn_layout.addWidget(select_none_btn)

        channel_sel_layout.addLayout(select_btn_layout)

        controls_layout.addWidget(channel_sel_group)

        # MODE: Sum Settings
        sum_settings_group = QGroupBox("Summed Force Settings")
        sum_settings_layout = QVBoxLayout(sum_settings_group)

        # Sum forces checkbox
        self._sum_forces_checkbox = QCheckBox("Sum Forces")
        self._sum_forces_checkbox.setToolTip(
            "Display averaged force across selected channels\n"
            "Formula: (F1 + F2 + ... + Fn) / n"
        )
        self._sum_forces_checkbox.setChecked(False)
        self._sum_forces_checkbox.stateChanged.connect(self._on_sum_forces_changed)
        sum_settings_layout.addWidget(self._sum_forces_checkbox)

        # Individual forces tolerance (only shown when sum forces is checked)
        self._individual_forces_tolerance_widget = QWidget()
        individual_tol_layout = QHBoxLayout(self._individual_forces_tolerance_widget)
        individual_tol_layout.setContentsMargins(20, 0, 0, 0)  # Indent

        individual_tol_layout.addWidget(QLabel("Balance Tolerance:"))
        self._imbalance_threshold_spin = QDoubleSpinBox()
        self._imbalance_threshold_spin.setRange(0.5, 50)  # Allow down to 0.5%
        self._imbalance_threshold_spin.setValue(5)
        self._imbalance_threshold_spin.setSingleStep(0.5)  # Step by 0.5%
        self._imbalance_threshold_spin.setDecimals(1)  # Show 1 decimal place
        self._imbalance_threshold_spin.setSuffix(" %")
        self._imbalance_threshold_spin.setToolTip(
            "Maximum allowed difference between weakest and strongest finger forces.\n"
            "Background turns red when exceeded."
        )
        self._imbalance_threshold_spin.valueChanged.connect(
            self._on_imbalance_threshold_changed
        )
        individual_tol_layout.addWidget(self._imbalance_threshold_spin)

        sum_settings_layout.addWidget(self._individual_forces_tolerance_widget)
        self._individual_forces_tolerance_widget.setVisible(False)  # Hidden by default

        # Show Feedback checkbox (only shown when sum forces is checked)
        self._show_feedback_checkbox = QCheckBox("Show Feedback")
        self._show_feedback_checkbox.setToolTip(
            "Display force balance feedback during the trial.\n"
            "Shows whether finger forces are balanced within tolerance."
        )
        self._show_feedback_checkbox.setChecked(False)
        self._show_feedback_checkbox.stateChanged.connect(
            self._on_show_feedback_changed
        )
        sum_settings_layout.addWidget(self._show_feedback_checkbox)
        self._show_feedback_checkbox.setVisible(False)  # Hidden by default

        controls_layout.addWidget(sum_settings_group)

        # Protocol Control
        control_group = QGroupBox("Protocol Control")
        control_layout = QVBoxLayout(control_group)

        self._start_btn = QPushButton("Start Protocol")
        self._start_btn.setEnabled(False)
        self._start_btn.clicked.connect(self._toggle_protocol)
        self._start_btn.setMinimumHeight(50)
        self._start_btn.setStyleSheet("font-size: 14px; font-weight: bold;")
        control_layout.addWidget(self._start_btn)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        control_layout.addWidget(self._progress_bar)

        self._status_label = QLabel("Configure device first")
        self._status_label.setStyleSheet("color: #9da3ab;")
        self._status_label.setAlignment(Qt.AlignCenter)
        control_layout.addWidget(self._status_label)

        controls_layout.addWidget(control_group)

        # Recording Control (inherited from config tab)
        recording_group = QGroupBox("Recording Control")
        recording_layout = QVBoxLayout(recording_group)

        # Display subject ID and file format (read-only)
        info_layout = QGridLayout()
        info_layout.addWidget(QLabel("Subject ID:"), 0, 0)
        self._recording_subject_label = QLabel("Not set")
        self._recording_subject_label.setStyleSheet("color: #9da3ab;")
        info_layout.addWidget(self._recording_subject_label, 0, 1)

        info_layout.addWidget(QLabel("File Format:"), 1, 0)
        self._recording_format_label = QLabel("Not set")
        self._recording_format_label.setStyleSheet("color: #9da3ab;")
        info_layout.addWidget(self._recording_format_label, 1, 1)

        recording_layout.addLayout(info_layout)

        # Recording button
        self._recording_btn = QPushButton("Start Recording")
        self._recording_btn.setEnabled(False)
        self._recording_btn.clicked.connect(self._toggle_recording)
        self._recording_btn.setMinimumHeight(40)
        recording_layout.addWidget(self._recording_btn)

        self._recording_status_label = QLabel("Configure in Settings tab")
        self._recording_status_label.setStyleSheet("color: #9da3ab;")
        self._recording_status_label.setAlignment(Qt.AlignCenter)
        recording_layout.addWidget(self._recording_status_label)

        controls_layout.addWidget(recording_group)
        controls_layout.addStretch()

        content_layout.addWidget(controls_widget)

        # ============ RIGHT PANEL - Force Widget ============
        plot_widget = QWidget()
        plot_layout = QVBoxLayout(plot_widget)

        plot_label = QLabel("Force Feedback Display")
        plot_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        plot_layout.addWidget(plot_label)

        # Legend and Force Balance section - horizontal layout
        info_layout = QHBoxLayout()

        # Legend section (shrinks to fit content)
        legend_frame = QFrame()
        legend_frame.setStyleSheet(
            "background-color: #2d2d2d; border-radius: 5px; padding: 8px;"
        )
        legend_layout = QHBoxLayout(legend_frame)
        legend_layout.setContentsMargins(10, 5, 10, 5)

        legend_title = QLabel("<b>Legend:</b>")
        legend_title.setStyleSheet("font-size: 18px; color: #e8eaed;")
        legend_layout.addWidget(legend_title)

        self._legend_entries_widget = QWidget()
        self._legend_entries_layout = QHBoxLayout(self._legend_entries_widget)
        self._legend_entries_layout.setContentsMargins(0, 0, 0, 0)
        self._legend_entries_layout.setSpacing(5)

        legend_layout.addWidget(self._legend_entries_widget)
        legend_layout.addStretch()

        info_layout.addWidget(legend_frame)  # No stretch - shrinks to fit

        # TRAINING MODE: Imbalance feedback indicator (takes remaining space)
        self._imbalance_label = QLabel("Force Balance: OK")
        self._imbalance_label.setStyleSheet(
            "font-size: 18px; font-weight: bold; color: #48BB78; "
            "background-color: #1a1a1a; padding: 10px; border-radius: 5px;"
        )
        self._imbalance_label.setAlignment(Qt.AlignCenter)
        self._imbalance_label.setVisible(
            False
        )  # Hidden by default until sum forces is checked
        info_layout.addWidget(
            self._imbalance_label, stretch=1
        )  # Stretch to fill remaining space

        plot_layout.addLayout(info_layout)

        # Create force widget and configure it
        self._force_widget = TrapezoidForceWidget()
        self._force_widget.set_trapezoid_params(
            rest_before=self._rest_duration_start,
            ramp_up=self._ramp_duration,
            plateau=self._hold_duration,
            ramp_down=self._ramp_duration,
            rest_after=self._rest_duration_end,
            target_percent=self._target_mvc_percent,
            tolerance=self._tolerance_percent,
        )
        # TRAINING MODE: Override y_max to be target + tolerance/2 + 5% buffer
        self._force_widget._y_max = (
            self._target_mvc_percent + self._tolerance_percent / 2.0 + 5.0
        )
        # Set color for Summed Force channel (red/coral)
        from PySide6.QtGui import QColor

        self._force_widget._assigned_colors["Summed Force"] = QColor("#ff6b6b")
        self._force_widget.setMinimumHeight(500)
        plot_layout.addWidget(self._force_widget)

        content_layout.addWidget(plot_widget, stretch=1)

        main_layout.addLayout(content_layout)

    def _apply_lowpass_filter(
        self, channel_name: str, samples: np.ndarray, sample_rate: float
    ) -> np.ndarray:
        """
        Apply moving average filter to samples for display smoothing.
        Uses a 20ms sliding window.
        """
        if not self._filter_enabled or len(samples) == 0:
            return samples

        # Calculate window size in samples for 20ms
        window_size = int(sample_rate * self._filter_window_ms / 1000.0)

        # Ensure window size is at least 1
        if window_size < 1:
            return samples

        # Initialize buffer for this channel if needed
        if channel_name not in self._filter_buffers:
            self._filter_buffers[channel_name] = []

        # Add new samples to buffer
        self._filter_buffers[channel_name].extend(samples.tolist())

        # Keep only the necessary samples in buffer (window_size + current batch)
        max_buffer_size = window_size * 10  # Keep extra for smooth transitions
        if len(self._filter_buffers[channel_name]) > max_buffer_size:
            self._filter_buffers[channel_name] = self._filter_buffers[channel_name][
                -max_buffer_size:
            ]

        # Apply moving average to the new samples
        buffer = self._filter_buffers[channel_name]
        filtered = np.zeros(len(samples))

        for i in range(len(samples)):
            # Get the index in the buffer for this sample
            buffer_idx = len(buffer) - len(samples) + i

            # Calculate window start (ensure it's not negative)
            window_start = max(0, buffer_idx - window_size + 1)
            window_end = buffer_idx + 1

            # Calculate moving average
            window_samples = buffer[window_start:window_end]
            filtered[i] = np.mean(window_samples)

        return filtered

    def _calculate_total_duration(self) -> float:
        """Calculate total protocol duration"""
        return (
            self._rest_duration_start  # Initial rest
            + self._ramp_duration  # Ramp up
            + self._hold_duration  # Hold
            + self._ramp_duration  # Ramp down
            + self._rest_duration_end  # Final rest
        )

    def _on_refresh_rate_changed(self, value: int):
        """Handle refresh rate change"""
        self._display_refresh_ms = value
        if self._display_timer.isActive():
            self._display_timer.stop()
            self._display_timer.start(self._display_refresh_ms)

    def _on_filter_toggled(self, state: int):
        """Handle filter checkbox toggle"""
        self._filter_enabled = state == Qt.CheckState.Checked.value
        # Clear filter buffers when toggling to start fresh
        self._filter_buffers.clear()

    def set_display_refresh_rate(self, ms: int):
        """Set display refresh rate from external source"""
        self._display_refresh_ms = ms
        self._refresh_spin.setValue(ms)
        if self._display_timer.isActive():
            self._display_timer.stop()
            self._display_timer.start(self._display_refresh_ms)

    def _on_settings_changed(self):
        """Handle protocol settings change"""
        self._target_mvc_percent = self._target_spin.value()
        self._tolerance_percent = self._tolerance_spin.value()
        self._rest_duration_start = self._rest_start_spin.value()
        self._rest_duration_end = self._rest_end_spin.value()
        self._ramp_duration = self._ramp_spin.value()
        self._hold_duration = self._hold_spin.value()

        # Update widget with trapezoid parameters
        # set_trapezoid_params(rest_before, ramp_up, plateau, ramp_down, rest_after, target_percent, tolerance)
        self._force_widget.set_trapezoid_params(
            rest_before=self._rest_duration_start,
            ramp_up=self._ramp_duration,
            plateau=self._hold_duration,
            ramp_down=self._ramp_duration,
            rest_after=self._rest_duration_end,
            target_percent=self._target_mvc_percent,
            tolerance=self._tolerance_percent,
        )
        # TRAINING MODE: Override y_max to be target + tolerance/2 + 5% buffer
        self._force_widget._y_max = (
            self._target_mvc_percent + self._tolerance_percent / 2.0 + 5.0
        )

    def _on_imbalance_threshold_changed(self):
        """Handle imbalance threshold change"""
        self._imbalance_threshold_percent = self._imbalance_threshold_spin.value()

    def set_client(self, client: Optional[MockNovecentoClient]):
        """Set the Novecento client"""
        self._client = client
        self._update_ui_state()

    def set_configuration(self, config: Optional[NovecentoConfiguration]):
        """Set device configuration"""
        self._config = config
        self._update_channel_list()
        self._update_ui_state()

    def set_channels(self, emg_channels: List[str], aux_channels: List[str]):
        """Update available channels"""
        self._active_aux_channels = sorted(aux_channels)
        self._update_channel_list()

    def set_mvc_value(self, mvc: float):
        """Set MVC reference value"""
        self._mvc_value = mvc
        self._on_settings_changed()  # Update target force

    def set_data_folder(self, folder: str):
        """Set data folder"""
        print(f"[TrapezoidTab] set_data_folder called: '{folder}'")
        self._data_folder = folder
        self._update_recording_ui()

    def set_subject_id(self, subject_id: str):
        """Set subject ID"""
        print(f"[TrapezoidTab] set_subject_id called: '{subject_id}'")
        self._subject_id = subject_id
        self._recording_subject_label.setText(subject_id if subject_id else "Not set")
        self._update_recording_ui()
        self._update_ui_state()  # ADDED: Update protocol start button state

    def set_recorder(self, recorder):
        """Set data recorder from config tab"""
        print(f"[TrapezoidTab] set_recorder called: {recorder}")
        self._recorder = recorder
        self._update_recording_ui()

    def set_file_format(self, file_format: str):
        """Update file format display"""
        print(f"[TrapezoidTab] set_file_format called: '{file_format}'")
        self._recording_format_label.setText(file_format if file_format else "Not set")
        self._update_recording_ui()

    def set_config_tab(self, config_tab):
        """Set reference to config tab to access current values"""
        self._config_tab = config_tab

    def showEvent(self, event):
        """Called when tab is shown - sync values"""
        super().showEvent(event)
        print("[TrapezoidTab] showEvent - forcing UI update")

        # If we have a reference to config tab, pull values directly
        if hasattr(self, "_config_tab") and self._config_tab:
            print("[TrapezoidTab] Getting values from config tab")
            subject_id = self._config_tab.get_subject_id()
            data_folder = self._config_tab.get_data_folder()
            file_format = self._config_tab.get_file_format()
            print(f"  Retrieved subject_id: '{subject_id}'")
            print(f"  Retrieved data_folder: '{data_folder}'")
            print(f"  Retrieved file_format: '{file_format}'")

            if subject_id:
                self._subject_id = subject_id
                self._recording_subject_label.setText(subject_id)
            else:
                # Subject ID was cleared - update to empty
                self._subject_id = ""
                self._recording_subject_label.setText("Not set")
            if data_folder:
                self._data_folder = data_folder
            if file_format:
                self._recording_format_label.setText(file_format)

        # Reload calibration for selected channels (participant may have changed)
        self._reload_calibration_for_selected_channels()

        self._update_recording_ui()
        self._update_ui_state()  # ADDED: Update protocol start button state

    def _reload_calibration_for_selected_channels(self):
        """Reload calibration values from calibration manager for all selected channels"""
        if not self._calibration_manager or not self._selected_channels:
            return

        print(
            f"[TrapezoidTab] Reloading calibration for channels: {self._selected_channels}"
        )
        for ch in self._selected_channels:
            offset = self._calibration_manager.get_offset(ch)
            mvc = self._calibration_manager.get_mvc(ch)

            old_offset = self._channel_offset_values.get(ch, "not set")
            old_mvc = self._channel_mvc_values.get(ch, "not set")

            # Always set values - use calibration if available, otherwise use global/defaults
            self._channel_offset_values[ch] = offset if offset is not None else 0.0
            self._channel_mvc_values[ch] = mvc if mvc is not None else self._mvc_value

            print(
                f"  {ch}: offset {old_offset} -> {self._channel_offset_values[ch]}, "
                f"mvc {old_mvc} -> {self._channel_mvc_values[ch]}"
            )

    def _update_warmup_display(self):
        """Update UI during warm-up to show sample count"""
        if self._recorder and self._recorder.is_warming_up:
            self._recording_status_label.setText(
                f"Warming up... ({self._recorder.warmup_sample_count:,} samples discarded)"
            )
        else:
            # Stop timer if no longer warming up
            self._warmup_timer.stop()

    def _update_recording_ui(self):
        """Update recording button state based on configuration"""
        # Can record if we have client, subject, and data folder
        can_record = bool(
            self._client is not None
            and self._client.is_connected
            and self._subject_id
            and self._data_folder
        )

        # DEBUG: Print state
        print(f"Recording UI Update:")
        print(f"  client: {self._client}")
        print(
            f"  client.is_connected: {self._client.is_connected if self._client else 'N/A'}"
        )
        print(f"  subject_id: '{self._subject_id}'")
        print(f"  data_folder: '{self._data_folder}'")
        print(f"  can_record: {can_record}")

        self._recording_btn.setEnabled(can_record)

        if self._recorder and self._recorder.is_recording:
            # Actually recording
            self._recording_btn.setText("Stop Recording")
            self._recording_btn.setStyleSheet("background-color: #E53E3E;")
            self._recording_status_label.setText(
                f"Recording... ({self._recorder.sample_count:,} samples)"
            )
            self._recording_status_label.setStyleSheet(
                "color: #48BB78; font-weight: bold;"
            )
        elif self._recorder and self._recorder.is_warming_up:
            # Warming up
            self._recording_btn.setText("Disarm Recording")
            self._recording_btn.setStyleSheet("background-color: #F6AD55;")
            self._recording_status_label.setText(
                f"Warming up... ({self._recorder.warmup_sample_count:,} samples discarded)"
            )
            self._recording_status_label.setStyleSheet(
                "color: #F6AD55; font-weight: bold;"
            )
        elif self._recorder:
            # Armed but not recording yet
            self._recording_btn.setText("Disarm Recording")
            self._recording_btn.setStyleSheet("background-color: #F6AD55;")
            self._recording_status_label.setText(
                "Armed - will record when protocol starts"
            )
            self._recording_status_label.setStyleSheet(
                "color: #F6AD55; font-weight: bold;"
            )
        else:
            # Not armed
            self._recording_btn.setText("Arm Recording")
            self._recording_btn.setStyleSheet("background-color: #003E74;")  # Blue
            if can_record:
                self._recording_status_label.setText("Click to arm recording")
                self._recording_status_label.setStyleSheet("color: #9da3ab;")
            else:
                missing = []
                if not self._client or not self._client.is_connected:
                    missing.append("connection")
                if not self._subject_id:
                    missing.append("subject ID")
                if not self._data_folder:
                    missing.append("data folder")
                self._recording_status_label.setText(f"Need: {', '.join(missing)}")
                self._recording_status_label.setStyleSheet("color: #9da3ab;")

    def _toggle_recording(self):
        """Toggle recording armed state - starts warm-up streaming immediately"""
        if self._recorder and self._recorder.is_recording:
            # Stop active recording
            self._recorder.stop_recording()
            
            # Stop streaming if we started it
            if self._client and self._client.is_streaming:
                self._client.stop_streaming(self._on_stream_data)
            
            # Stop warm-up timer if running
            self._warmup_timer.stop()
            
            self._recorder = None
            self._update_recording_ui()
        elif self._recorder:
            # Disarm (stop warm-up and streaming)
            if self._recorder.is_warming_up:
                self._recorder.stop_warmup()
            
            # Stop streaming
            if self._client and self._client.is_streaming:
                self._client.stop_streaming(self._on_stream_data)
            
            # Stop warm-up timer
            self._warmup_timer.stop()
            
            # Stop display timer if protocol is not running
            if not self._is_running:
                if self._display_timer.isActive():
                    self._display_timer.stop()
                # Disable widget display 
                self._force_widget.set_running(False)
            
            self._recorder = None
            self._update_recording_ui()
        else:
            # Arm recording - start warm-up mode and streaming
            from data.managers import DataRecorder

            self._recorder = DataRecorder(self._data_folder)
            self._recorder.start_warmup()
            
            # Start streaming immediately for warm-up
            if self._client and self._active_aux_channels:
                self._client.set_active_channels([], self._active_aux_channels)
                self._client.start_streaming(self._on_stream_data)
                print("[TrapezoidTab] Warm-up streaming started")
                
                # Enable widget display so forces are visible even without protocol running
                self._force_widget.set_running(True)
                
                # Start display timer so forces are visualized even when not running protocol
                if not self._display_timer.isActive():
                    self._display_timer.start(self._display_refresh_ms)
            
            # Start timer to update warm-up sample count
            self._warmup_timer.start(500)  # Update every 500ms
            
            self._update_recording_ui()

    def set_aux_channels(self, channels: List[str]):
        """Set available AUX channels (called by main_window)"""
        self._active_aux_channels = sorted(channels)
        self._update_channel_list()
        self._update_ui_state()

    def set_calibration_manager(self, manager):
        """Set calibration manager"""
        self._calibration_manager = manager

    def set_trial_logger(self, logger):
        """Set trial logger"""
        self._trial_logger = logger

    def _update_channel_list(self):
        """Update checkbox list"""
        # Clear existing checkboxes and inputs
        while self._channel_list_layout.count():
            item = self._channel_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._channel_checkboxes.clear()
        self._finger_label_inputs.clear()

        # Use _active_aux_channels if set, otherwise use config
        channels = (
            self._active_aux_channels
            if self._active_aux_channels
            else (sorted(self._config.aux_channels) if self._config else [])
        )

        for aux_name in channels:
            # Create row with checkbox and label input
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(5)  # Tight spacing within row

            # Add checkbox
            cb = QCheckBox(aux_name)
            cb.stateChanged.connect(self._on_channel_selection_changed)
            row_layout.addWidget(cb)

            # Add finger label input (for full finger name)
            label_input = QLineEdit()
            label_input.setMaximumWidth(80)  # Wider to fit full words like "Index"
            label_input.setPlaceholderText("Index")
            label_input.setToolTip(
                "Enter full finger name (e.g., Index, Middle, Ring, Pinky, Thumb)"
            )
            label_input.setMaxLength(10)  # Allow up to 10 characters
            label_input.textChanged.connect(
                lambda text, ch=aux_name: self._on_finger_label_changed(ch, text)
            )
            row_layout.addWidget(label_input)

            row_layout.addStretch()

            self._channel_list_layout.addWidget(row_widget)
            self._channel_checkboxes[aux_name] = cb
            self._finger_label_inputs[aux_name] = label_input

        # Add stretch at the end to push items to top
        self._channel_list_layout.addStretch()

        # Auto-select first channel for display
        if channels and channels[0] in self._channel_checkboxes:
            self._channel_checkboxes[channels[0]].setChecked(True)

    def _on_finger_label_changed(self, channel_name: str, label: str):
        """Handle finger label text change"""
        # Store the full label (for legend and post-trial feedback)
        self._channel_finger_labels[channel_name] = label.capitalize()

        # Send only first letter to widget (for plot dots)
        if hasattr(self, "_force_widget"):
            abbreviated_labels = {
                ch: lbl[0].upper() if lbl else ""
                for ch, lbl in self._channel_finger_labels.items()
            }
            self._force_widget.set_channel_finger_labels(abbreviated_labels)

        # Update legend colors with new labels
        self._update_legend_colors()

    def _on_channel_selection_changed(self):
        """Handle checkbox state change"""
        self._selected_channels = [
            ch for ch, cb in self._channel_checkboxes.items() if cb.isChecked()
        ]

        # Update legend colors
        self._update_legend_colors()

        # Load calibration for all selected channels
        if self._calibration_manager:
            for ch in self._selected_channels:
                offset = self._calibration_manager.get_offset(ch)
                mvc = self._calibration_manager.get_mvc(ch)
                # Always set values - use calibration if available, otherwise use global/defaults
                self._channel_offset_values[ch] = offset if offset is not None else 0.0
                self._channel_mvc_values[ch] = (
                    mvc if mvc is not None else self._mvc_value
                )
        else:
            # No calibration manager - use global values as defaults
            for ch in self._selected_channels:
                if ch not in self._channel_offset_values:
                    self._channel_offset_values[ch] = 0.0
                if ch not in self._channel_mvc_values:
                    self._channel_mvc_values[ch] = self._mvc_value

    def _update_legend_colors(self):
        """Update legend by pre-assigning colors to channels and updating legend display"""
        if not hasattr(self, "_force_widget"):
            return

        from PySide6.QtGui import QColor

        colors = ["#4a9eff", "#48BB78", "#F6AD55", "#E53E3E", "#9F7AEA", "#38B2AC"]

        # Clear old assignments
        self._force_widget._assigned_colors.clear()

        # Clear legend entries
        while self._legend_entries_layout.count():
            item = self._legend_entries_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # If sum forces is checked, only show Summed Force
        if self._sum_forces:
            self._force_widget._assigned_colors["Summed Force"] = QColor("#ff6b6b")

            # Add to legend display
            entry = QLabel("\u25cf  <b>Summed Force</b>")
            entry.setStyleSheet("font-size: 18px; color: #ff6b6b;")
            self._legend_entries_layout.addWidget(entry)
        else:
            # Show individual channels
            for idx, ch_name in enumerate(self._selected_channels):
                color = colors[idx % len(colors)]
                # Use full finger label if available, otherwise use channel name
                display_name = self._channel_finger_labels.get(ch_name, ch_name)
                if not display_name:
                    display_name = ch_name

                self._force_widget._assigned_colors[display_name] = QColor(color)

                # Add to legend display
                entry = QLabel(f"\u25cf  <b>{display_name}</b>")
                entry.setStyleSheet(f"font-size: 18px; color: {color};")
                self._legend_entries_layout.addWidget(entry)

        # Show message if no channels selected
        if not self._selected_channels:
            entry = QLabel("No channels selected")
            entry.setStyleSheet("font-size: 14px; color: #9da3ab; font-style: italic;")
            self._legend_entries_layout.addWidget(entry)

        # Add a dummy "Target" entry to widget's assigned colors to ensure on-plot legend shows (needs 2+ entries)
        if len(self._force_widget._assigned_colors) == 1:
            self._force_widget._assigned_colors["Target"] = QColor("#666666")

        # Force widget to repaint
        self._force_widget.update()

    def _update_legend(self):
        """Update the legend display - deprecated, using _update_legend_colors now"""
        self._update_legend_colors()

    def _select_all_channels(self):
        """Select all channels for display"""
        for cb in self._channel_checkboxes.values():
            cb.setChecked(True)

    def _select_no_channels(self):
        """Deselect all channels"""
        for cb in self._channel_checkboxes.values():
            cb.setChecked(False)

    def _on_sum_forces_changed(self, state):
        """Handle sum forces checkbox state change"""
        self._sum_forces = self._sum_forces_checkbox.isChecked()
        # Show/hide individual forces tolerance based on sum forces checkbox
        self._individual_forces_tolerance_widget.setVisible(self._sum_forces)
        # Show/hide Show Feedback checkbox based on sum forces checkbox
        self._show_feedback_checkbox.setVisible(self._sum_forces)
        # Show/hide force balance indicator based on sum forces checkbox AND show feedback checkbox
        self._imbalance_label.setVisible(self._sum_forces and self._show_feedback)
        # Update legend to show Summed Force or individual channels
        self._update_legend_colors()

    def _on_show_feedback_changed(self, state):
        """Handle show feedback checkbox state change"""
        self._show_feedback = self._show_feedback_checkbox.isChecked()
        # Show/hide force balance indicator based on show feedback checkbox
        self._imbalance_label.setVisible(self._sum_forces and self._show_feedback)

    def _update_ui_state(self):
        """Update UI based on state"""
        has_channels = len(self._active_aux_channels) > 0
        has_subject = bool(self._subject_id and self._subject_id.strip())

        is_ready = (
            self._client is not None
            and self._client.is_connected
            and has_channels
            and has_subject  # ADDED: Require subject ID
        )

        self._start_btn.setEnabled(is_ready and not self._is_running)

        if is_ready:
            self._status_label.setText("Ready - Click Start to begin")
            self._status_label.setStyleSheet("color: #48BB78;")
        elif self._client is None or not self._client.is_connected:
            self._status_label.setText("Connect to device first")
            self._status_label.setStyleSheet("color: #9da3ab;")
        elif not has_subject:
            self._status_label.setText("Enter Subject ID in Configuration tab")
            self._status_label.setStyleSheet("color: #F6AD55;")
        elif not has_channels:
            self._status_label.setText("No AUX channels configured")
            self._status_label.setStyleSheet("color: #F6AD55;")
        else:
            self._status_label.setText("Configure channels first")
            self._status_label.setStyleSheet("color: #9da3ab;")

    def _toggle_protocol(self):
        """Start or stop protocol"""
        if self._is_running:
            self._stop_protocol()
        else:
            self._start_protocol()

    def _start_protocol(self):
        """Start the trapezoid protocol"""
        if not self._client or not self._selected_channels:
            QMessageBox.warning(
                self, "Cannot Start", "Please select at least one channel to display"
            )
            return

        self._is_running = True
        self._current_phase = "rest1"
        self._protocol_start_time = datetime.now()
        self._recording_start_time = (
            datetime.now()
        )  # Track when recording actually starts
        self._phase_start_time = datetime.now()

        # Start countdown
        self._countdown_active = True
        self._countdown_start_time = datetime.now()

        self._latest_force_value = 0.0
        self._latest_force_mvc_percent = 0.0
        self._latest_channel_values.clear()
        self._latest_channel_mvc_percents.clear()
        self._filter_buffers.clear()  # Clear filter buffers

        # TRAINING MODE: Reset imbalance tracking and individual channel storage
        self._imbalance_detected = False
        self._imbalance_ever_exceeded = False  # Reset for new trial
        self._individual_channel_data.clear()  # Clear stored individual channel data
        self._force_widget.setStyleSheet("")  # Clear any red background
        self._imbalance_label.setText("Force Balance: OK")
        self._imbalance_label.setStyleSheet(
            "font-size: 18px; font-weight: bold; color: #48BB78; "
            "background-color: #1a1a1a; padding: 10px; border-radius: 5px;"
        )

        # Reset widget and ENABLE cursor display
        self._force_widget.clear_force_data()
        self._force_widget.set_current_time(0.0)
        self._force_widget.set_current_force(0.0)
        self._force_widget.set_running(True)  # CRITICAL: Enable cursor display!

        # Show countdown overlay
        self._force_widget.set_countdown_active(True)

        # Update UI
        self._start_btn.setText("Stop")
        self._start_btn.setStyleSheet(
            "background-color: #E53E3E; font-size: 14px; font-weight: bold;"
        )
        self._phase_label.setText("GET READY...")
        self._status_label.setText("Starting soon...")
        self._status_label.setStyleSheet("color: #F6AD55;")
        self._progress_bar.setValue(0)

        # CRITICAL: Set active channels BEFORE streaming!
        # Calibration tab may have changed them to just one channel
        # We need all AUX channels active for proper indexing
        if self._client and self._active_aux_channels:
            self._client.set_active_channels([], self._active_aux_channels)

        # Start streaming ONLY if not already streaming (warm-up mode)
        if self._client and not self._client.is_streaming:
            self._client.start_streaming(self._on_stream_data)

        # Keep warm-up mode active during countdown - don't start recording yet
        # Recording will start after countdown completes (in _check_phase)

        # START DISPLAY TIMER at configured rate
        self._display_timer.start(self._display_refresh_ms)

        # Start phase checking timer (100ms for phase transitions)
        self._phase_timer.start(100)

        # Save protocol settings
        self._save_protocol_settings()

        self.protocolStarted.emit()

    def _start_recording_for_protocol(self):
        """Actually start recording when protocol begins"""
        from data.managers import RecordingMetadata
        from datetime import datetime

        channels = {"emg": [], "aux": []}
        if self._client:
            try:
                channels = self._client.get_active_channels()
            except:
                pass

        # Get sample rate
        sample_rate = 2000
        if self._config:
            for inp in self._config.inputs.values():
                if inp.is_enabled:
                    sample_rate = inp.sampling_rate.frequency
                    break

        metadata = RecordingMetadata(
            subject_id=self._subject_id,
            session_id=datetime.now().strftime("%Y%m%d_%H%M%S"),
            start_time=datetime.now().isoformat(),
            sample_rate=sample_rate,
            task_type="Trapezoid",
            emg_channels=channels.get("emg", []),
            aux_channels=channels.get("aux", []),
        )

        # Determine file format from label
        file_format = "hdf5" if "HDF5" in self._recording_format_label.text() else "csv"

        try:
            self._recorder.start_recording(metadata, file_format)
            print(f"[TrapezoidTab] Recording started at protocol start")
        except Exception as e:
            QMessageBox.critical(
                self, "Recording Error", f"Failed to start recording: {e}"
            )

        self._update_recording_ui()

    def _inject_protocol_metadata(self):
        """Inject protocol parameters into active recording metadata if recording is active"""
        # Use this tab's own recorder, not config tab's
        recorder = self._recorder

        if not recorder or not recorder.is_recording:
            return

        # Get the metadata object
        metadata = getattr(recorder, "_metadata", None)

        if not metadata:
            return

        # Inject protocol parameters into extra_params
        protocol_params = {
            "protocol_type": "trapezoid",
            "protocol_start_time": (
                self._protocol_start_time.isoformat()
                if self._protocol_start_time
                else None
            ),
            "countdown_duration_s": self._countdown_seconds,
            "selected_channels": self._selected_channels,
            "filter_enabled": self._filter_enabled,
            "filter_window_ms": self._filter_window_ms,
            "sum_forces": self._sum_forces,
            "show_feedback": self._show_feedback,
            "balance_tolerance_percent": self._imbalance_threshold_percent,
            "target_mvc_percent": self._target_mvc_percent,
            "tolerance_percent": self._tolerance_percent,
            "rest_duration_start_s": self._rest_duration_start,
            "rest_duration_end_s": self._rest_duration_end,
            "ramp_duration_s": self._ramp_duration,
            "hold_duration_s": self._hold_duration,
            "channel_mvc_values": self._channel_mvc_values,
            "channel_offset_values": self._channel_offset_values,
            "channel_finger_labels": self._channel_finger_labels,
            "trial_successful": None,  # Will be updated when trial completes
            "imbalance_exceeded": None,  # Will be updated when trial completes
            "protocol_completed": None,  # Will be updated: True if finished naturally, False if cancelled
        }

        print(f"[TrapezoidTab] Injecting trapezoid protocol metadata")

        metadata.extra_params.update(protocol_params)

        # Also update the task_type field
        metadata.task_type = "trapezoid"

        # Re-save the metadata JSON file with updated parameters
        import json
        from pathlib import Path

        recording_path = getattr(recorder, "_recording_path", None)

        if recording_path:
            # Get metadata file path (recording file with _metadata.json suffix)
            recording_file = Path(recording_path)
            meta_path = recording_file.parent / f"{recording_file.stem}_metadata.json"
            try:
                with open(meta_path, "w") as f:
                    json.dump(metadata.to_dict(), f, indent=2)
                print(f"[TrapezoidTab] Saved metadata to {meta_path}")
            except Exception as e:
                print(f"[TrapezoidTab] Error saving metadata: {e}")

    def _save_protocol_settings(self):
        """Save protocol settings to JSON file"""
        import json
        import os
        from pathlib import Path

        if not self._subject_id:
            return

        # Create trials directory if it doesn't exist
        trials_dir = Path(self._data_folder) / "trials"
        trials_dir.mkdir(parents=True, exist_ok=True)

        # Create settings filename with timestamp
        timestamp = self._protocol_start_time.strftime("%Y%m%d_%H%M%S")
        settings_file = (
            trials_dir / f"{self._subject_id}_trapezoid_{timestamp}_settings.json"
        )

        # Collect settings
        settings = {
            "subject_id": self._subject_id,
            "protocol_type": "trapezoid_training",
            "timestamp": timestamp,
            "selected_channels": self._selected_channels,
            "filter_enabled": self._filter_enabled,
            "filter_window_ms": self._filter_window_ms,
            "summed_forces": self._sum_forces,
            "show_feedback": self._show_feedback,
            "balance_tolerance_percent": self._imbalance_threshold_percent,
            "target_mvc_percent": self._target_mvc_percent,
            "tolerance_percent": self._tolerance_percent,
            "rest_duration_start": self._rest_duration_start,
            "rest_duration_end": self._rest_duration_end,
            "ramp_duration": self._ramp_duration,
            "hold_duration": self._hold_duration,
            "mvc_value": self._mvc_value,
            "offset_value": self._offset_value,
            "channel_mvc_values": self._channel_mvc_values,
            "channel_offset_values": self._channel_offset_values,
            "channel_finger_labels": self._channel_finger_labels,
            "display_refresh_ms": self._display_refresh_ms,
        }

        # Save to JSON
        try:
            with open(settings_file, "w") as f:
                json.dump(settings, f, indent=2)
        except Exception as e:
            print(f"Warning: Could not save protocol settings: {e}")

    def _stop_protocol(self):
        """Stop the protocol"""
        self._is_running = False
        self._countdown_active = False
        self._current_phase = "idle"
        self._display_timer.stop()
        self._phase_timer.stop()

        # Disable cursor display
        self._force_widget.set_running(False)

        # Update metadata with trial outcome before stopping recording
        if self._recorder and self._recorder.is_recording:
            self._update_trial_outcome_in_metadata(
                protocol_completed=False
            )  # Cancelled/stopped early
            self._recorder.stop_recording()
            print("[TrapezoidTab] Recording stopped automatically with protocol")
            self._update_recording_ui()

        # Remove only our callback, don't stop streaming entirely
        if self._client and self._client.is_streaming:
            self._client.stop_streaming(self._on_stream_data)

        self._start_btn.setText("Start Protocol")
        self._start_btn.setStyleSheet("font-size: 14px; font-weight: bold;")
        self._phase_label.setText("Phase: Stopped")
        self._status_label.setText("Protocol stopped")
        self._status_label.setStyleSheet("color: #F6AD55;")

        self._start_btn.setEnabled(True)

        self.protocolStopped.emit()

    def _update_trial_outcome_in_metadata(self, protocol_completed=True):
        """Update metadata with trial success/failure information

        Args:
            protocol_completed: True if protocol finished naturally, False if cancelled
        """
        if not self._recorder or not self._recorder.is_recording:
            return

        metadata = getattr(self._recorder, "_metadata", None)

        if not metadata:
            return

        # Check if extra_params exists
        if not hasattr(metadata, "extra_params"):
            return

        # Calculate duration
        from datetime import datetime

        protocol_end_time = datetime.now()
        # Use recording_start_time (not protocol_start_time which gets reset after countdown)
        duration_s = (
            (protocol_end_time - self._recording_start_time).total_seconds()
            if hasattr(self, "_recording_start_time")
            else None
        )

        # Determine if trial was successful
        # For summed forces: successful if imbalance never exceeded threshold
        # For non-summed: just mark as completed
        trial_successful = (
            not self._imbalance_ever_exceeded if self._sum_forces else True
        )

        metadata.extra_params["trial_successful"] = trial_successful
        metadata.extra_params["imbalance_exceeded"] = self._imbalance_ever_exceeded
        metadata.extra_params["protocol_completed"] = protocol_completed
        metadata.extra_params["protocol_end_time"] = protocol_end_time.isoformat()
        metadata.extra_params["protocol_duration_s"] = duration_s
        metadata.extra_params["samples_recorded"] = self._recorder.sample_count

        # Set end_time in main metadata
        metadata.end_time = protocol_end_time.isoformat()

        print(f"[TrapezoidTab] Trial outcome - successful: {trial_successful}, completed: {protocol_completed}")

        # Re-save metadata JSON with outcome
        import json
        from pathlib import Path

        recording_path = getattr(self._recorder, "_recording_path", None)

        if recording_path:
            recording_file = Path(recording_path)
            meta_path = recording_file.parent / f"{recording_file.stem}_metadata.json"
            try:
                with open(meta_path, "w") as f:
                    json.dump(metadata.to_dict(), f, indent=2)
            except Exception as e:
                print(f"[TrapezoidTab] Error updating metadata: {e}")

    def _on_stream_data(self, data: StreamData):
        """
        Handle incoming stream data.
        CRITICAL: Keep this FAST - only record data, defer all processing!
        """
        # Write data to recorder (handles both recording and warm-up modes)
        if self._recorder:
            try:
                self._recorder.write_samples(
                    data.emg_samples, data.aux_samples, data.timestamps
                )
            except Exception as e:
                print(f"Recording error: {e}")

        # Only process for display if protocol is running (not during countdown)
        if not self._is_running or self._countdown_active:
            return

        # Store raw data for display thread to process later
        # Don't do heavy processing here - just store the latest packet
        if self._protocol_start_time and self._selected_channels:
            # Quick extraction of latest values only (no loops, no filtering)
            for ch_name in self._selected_channels:
                if ch_name not in self._active_aux_channels:
                    continue

                idx = self._active_aux_channels.index(ch_name)

                if data.aux_samples.shape[0] > idx and data.aux_samples.shape[1] > 0:
                    force_samples = data.aux_samples[idx, :]
                    
    def _on_stream_data(self, data: StreamData):
        """
        Handle incoming stream data - optimized version.
        Records raw data + updates latest values only (no per-sample loops).
        """
        # 1. Record raw data (ALWAYS first - this is what gets saved to .h5)
        if self._recorder:
            try:
                self._recorder.write_samples(
                    data.emg_samples, data.aux_samples, data.timestamps
                )
            except Exception as e:
                print(f"Recording error: {e}")

        # 2. Update display values - ALWAYS update, not just when protocol running
        # This allows force plotting even when not running protocol
        if not self._selected_channels:
            return

        # Calculate elapsed time - use protocol start if running, otherwise use current time
        if self._protocol_start_time and self._is_running:
            elapsed = (datetime.now() - self._protocol_start_time).total_seconds()
        else:
            # Not running - just use a rolling time counter for display
            elapsed = time.time()

        # Extract just the LATEST value from each channel for display
        for ch_name in self._selected_channels:
            if ch_name in self._active_aux_channels:
                idx = self._active_aux_channels.index(ch_name)
                if data.aux_samples.shape[0] > idx and data.aux_samples.shape[1] > 0:
                    raw_value = float(data.aux_samples[idx, -1])
                    self._latest_channel_values[ch_name] = raw_value
                    
                    # Calculate %MVC for this value
                    offset = self._channel_offset_values.get(ch_name, 0.0)
                    mvc = self._channel_mvc_values.get(ch_name, 1.0)
                    corrected = raw_value - offset
                    mvc_pct = (corrected / mvc) * 100.0 if mvc > 0 else 0.0
                    self._latest_channel_mvc_percents[ch_name] = mvc_pct
                    
                    # ALWAYS store individual data for post-trial review (regardless of sum mode)
                    if self._is_running and not self._countdown_active:
                        if ch_name not in self._individual_channel_data:
                            self._individual_channel_data[ch_name] = []
                        self._individual_channel_data[ch_name].append((elapsed, mvc_pct))
                    
        # Add force trails AFTER processing all channels
        if self._is_running and not self._countdown_active:
            if self._sum_forces and self._latest_channel_mvc_percents:
                # Show only summed force trail
                summed_force = np.mean(list(self._latest_channel_mvc_percents.values()))
                self._force_widget.add_force_sample_for_channel("Summed Force", elapsed, summed_force)
            elif not self._sum_forces:
                # Show individual force trails
                for ch_name in self._selected_channels:
                    if ch_name in self._latest_channel_mvc_percents:
                        display_name = self._channel_finger_labels.get(ch_name, ch_name) or ch_name
                        mvc_pct = self._latest_channel_mvc_percents[ch_name]
                        self._force_widget.add_force_sample_for_channel(display_name, elapsed, mvc_pct)

    def _update_display(self):
        """
        TIMER CALLBACK - Updates GUI at fixed interval.
        This is called every _display_refresh_ms milliseconds.

        Key fix: Cursor shows YOUR ACTUAL FORCE at current time.
        Now also works when protocol is not running.
        """
        # During countdown, just show countdown
        if self._countdown_active:
            return

        # If protocol is running, update progress and time
        if self._is_running and self._protocol_start_time:
            # Calculate elapsed time
            elapsed = (datetime.now() - self._protocol_start_time).total_seconds()
            total_duration = self._calculate_total_duration()

            # Update progress bar
            progress = min(100, int(elapsed / total_duration * 100))
            self._progress_bar.setValue(progress)

            # Update time display
            self._time_label.setText(f"Time: {elapsed:.1f}s")

            # Update widget time and force (cursor position)
            self._force_widget.set_current_time(elapsed)
        else:
            # Not running protocol - just show current force at time 0 (no timeline)
            self._force_widget.set_current_time(0.0)
        
        # Always update force display if we have latest values
        if self._latest_channel_mvc_percents:
            # If sum forces is enabled, show averaged force
            if self._sum_forces:
                summed_force = np.mean(list(self._latest_channel_mvc_percents.values()))
                self._force_widget.set_current_force(summed_force)
                # Clear individual channel dots - only show summed dot
                self._force_widget.set_current_channel_forces({})

                # TRAINING MODE: Check force imbalance across channels (only during protocol)
                if self._is_running and self._show_feedback and len(self._latest_channel_mvc_percents) > 1:
                    forces = list(self._latest_channel_mvc_percents.values())
                    min_force = min(forces)
                    max_force = max(forces)
                    imbalance = max_force - min_force

                    # Check if imbalance exceeds threshold
                    if imbalance > self._imbalance_threshold_percent:
                        if not self._imbalance_detected:
                            self._imbalance_detected = True
                            self._imbalance_ever_exceeded = (
                                True  # Record that it happened at least once
                            )
                            # Turn background red
                            self._force_widget.setStyleSheet("background-color: #4d1a1a;")
                            self._imbalance_label.setText(
                                f"\u26a0 IMBALANCE DETECTED: {imbalance:.1f}% \u26a0"
                            )
                            self._imbalance_label.setStyleSheet(
                                "font-size: 18px; font-weight: bold; color: #ff6b6b; "
                                "background-color: #2d0d0d; padding: 10px; border-radius: 5px;"
                            )
                    else:
                        if self._imbalance_detected:
                            self._imbalance_detected = False
                            # Restore normal background
                            self._force_widget.setStyleSheet("")
                            self._imbalance_label.setText(
                                f"Force Balance: OK ({imbalance:.1f}%)"
                            )
                            self._imbalance_label.setStyleSheet(
                                "font-size: 18px; font-weight: bold; color: #48BB78; "
                                "background-color: #1a1a1a; padding: 10px; border-radius: 5px;"
                            )
                elif not self._show_feedback and len(self._latest_channel_mvc_percents) > 1:
                    # Still track imbalance_ever_exceeded for post-trial feedback, but don't show it
                    forces = list(self._latest_channel_mvc_percents.values())
                    min_force = min(forces)
                    max_force = max(forces)
                    imbalance = max_force - min_force

                    if imbalance > self._imbalance_threshold_percent:
                        self._imbalance_ever_exceeded = True
            else:
                # Not summing - show individual channel dots only
                # Widget will automatically hide the main cursor when channel forces are set
                # Show individual channel dots
                self._force_widget.set_current_channel_forces(
                    self._latest_channel_mvc_percents
                )

        # Update recording status if recording
        if self._recorder and self._recorder.is_recording:
            self._recording_status_label.setText(
                f"Recording... ({self._recorder.sample_count:,} samples)"
            )

        # TRIGGER REPAINT - this is the key fix!
        self._force_widget.update()

    def _get_current_target(self, elapsed: float) -> float:
        """Get current target force for elapsed time"""
        rest1_end = self._rest_duration_start
        ramp1_end = rest1_end + self._ramp_duration
        hold_end = ramp1_end + self._hold_duration
        ramp2_end = hold_end + self._ramp_duration

        if elapsed < rest1_end:
            return 0.0
        elif elapsed < ramp1_end:
            # Ramping up
            ramp_progress = (elapsed - rest1_end) / self._ramp_duration
            return self._target_mvc_percent * ramp_progress
        elif elapsed < hold_end:
            return self._target_mvc_percent
        elif elapsed < ramp2_end:
            # Ramping down
            ramp_progress = (elapsed - hold_end) / self._ramp_duration
            return self._target_mvc_percent * (1 - ramp_progress)
        else:
            return 0.0

    def _is_in_ramp_phase(self, elapsed: float) -> bool:
        """Check if elapsed time is in a ramp phase"""
        rest1_end = self._rest_duration_start
        ramp1_end = rest1_end + self._ramp_duration
        hold_end = ramp1_end + self._hold_duration
        ramp2_end = hold_end + self._ramp_duration

        # In ramp up or ramp down
        return (rest1_end <= elapsed < ramp1_end) or (hold_end <= elapsed < ramp2_end)

    def _check_phase(self):
        """Check and update protocol phase"""
        # Check countdown first
        if self._countdown_active:
            elapsed = (datetime.now() - self._countdown_start_time).total_seconds()
            remaining = self._countdown_seconds - elapsed

            if remaining <= 0:
                # Countdown complete - NOW start actual recording
                if self._recorder:
                    if self._recorder.is_warming_up:
                        # Stop warm-up mode and timer
                        warmup_samples = self._recorder.warmup_sample_count
                        self._recorder.stop_warmup()
                        self._warmup_timer.stop()
                        print(f"[TrapezoidTab] Warm-up complete - discarded {warmup_samples} samples ({warmup_samples/2000:.1f}s)")
                    
                    # Start actual recording if not already recording
                    if not self._recorder.is_recording:
                        self._start_recording_for_protocol()
                        # Inject protocol parameters into active recording metadata
                        self._inject_protocol_metadata()
                
                # Hide countdown overlay and start protocol
                self._countdown_active = False
                self._force_widget.set_countdown_active(False)
                self._protocol_start_time = (
                    datetime.now()
                )  # Reset start time for phase calculations
                self._phase_start_time = datetime.now()
                self._phase_label.setText("Phase: Rest (Initial)")
                self._status_label.setText("Relax...")
                self._status_label.setStyleSheet("color: #4a9eff;")
                self._force_widget.update()  # Repaint to remove overlay
                # Note: Recording starts NOW, synchronized with protocol phases
            else:
                # Update countdown number in widget
                countdown_num = int(remaining) + 1
                self._force_widget.set_countdown_number(countdown_num)
                self._force_widget.update()  # Repaint to show new number
            return

        if not self._is_running or not self._phase_start_time:
            return

        elapsed = (datetime.now() - self._protocol_start_time).total_seconds()
        total_duration = self._calculate_total_duration()

        rest1_end = self._rest_duration_start
        ramp1_end = rest1_end + self._ramp_duration
        hold_end = ramp1_end + self._hold_duration
        ramp2_end = hold_end + self._ramp_duration

        # Determine current phase
        old_phase = self._current_phase

        if elapsed < rest1_end:
            self._current_phase = "rest1"
            phase_text = "Rest (Initial)"
            status_text = "Relax..."
        elif elapsed < ramp1_end:
            self._current_phase = "ramp_up"
            phase_text = "Ramp Up"
            status_text = "Increase force gradually!"
        elif elapsed < hold_end:
            self._current_phase = "hold"
            phase_text = "Hold"
            status_text = f"HOLD at {self._target_mvc_percent:.0f}% MVC!"
        elif elapsed < ramp2_end:
            self._current_phase = "ramp_down"
            phase_text = "Ramp Down"
            status_text = "Decrease force gradually..."
        elif elapsed < total_duration:
            self._current_phase = "rest2"
            phase_text = "Rest (Final)"
            status_text = "Relax..."
        else:
            self._on_protocol_complete()
            print(f"[TrapezoidTab] Protocol complete at {elapsed:.2f}s (expected {total_duration:.2f}s)")
            return

        # Update phase display if changed
        if old_phase != self._current_phase:
            print(f"[TrapezoidTab] Phase transition at {elapsed:.2f}s: {old_phase} -> {self._current_phase}")
            self._phase_label.setText(f"Phase: {phase_text}")
            self._status_label.setText(status_text)

            # Update status color based on phase
            if "hold" in self._current_phase:
                self._status_label.setStyleSheet("color: #F6AD55; font-weight: bold;")
            elif "ramp" in self._current_phase:
                self._status_label.setStyleSheet("color: #4a9eff;")
            else:
                self._status_label.setStyleSheet("color: #48BB78;")

    def _on_protocol_complete(self):
        """Handle protocol completion"""
        self._is_running = False
        self._current_phase = "complete"
        self._display_timer.stop()
        self._phase_timer.stop()

        # Update UI immediately
        # Remove only our callback, don't stop streaming entirely
        if self._client and self._client.is_streaming:
            self._client.stop_streaming(self._on_stream_data)

        self._start_btn.setText("Start Protocol")
        self._start_btn.setStyleSheet("font-size: 14px; font-weight: bold;")
        self._phase_label.setText("Phase: Complete")
        self._status_label.setText("Protocol completed successfully!")
        self._status_label.setStyleSheet("color: #48BB78; font-weight: bold;")
        self._progress_bar.setValue(100)

        self._start_btn.setEnabled(True)

        # Don't stop recording immediately - schedule it to allow queued packets to drain
        from PySide6.QtCore import QTimer
        QTimer.singleShot(500, self._stop_recording_after_protocol)
        
    def _stop_recording_after_protocol(self):
        """Stop recording after protocol completes (called by timer)"""
        # Update metadata with trial outcome before stopping recording
        if self._recorder and self._recorder.is_recording:
            # Capture sample count before stopping
            self._last_trial_sample_count = self._recorder.sample_count
            
            self._update_trial_outcome_in_metadata(
                protocol_completed=True
            )  # Natural completion
            self._recorder.stop_recording()
            print(
                f"[TrapezoidTab] Recording stopped automatically after protocol completion - {self._last_trial_sample_count:,} samples recorded"
            )
            self._update_recording_ui()
        else:
            # Not recording - set to 0
            self._last_trial_sample_count = 0

        # TRAINING MODE: Show post-trial review for both summed and non-summed trials
        if self._show_post_trial_review and len(self._selected_channels) > 0:
            self._show_post_trial_feedback()

        self.protocolCompleted.emit()

    def _show_post_trial_feedback(self):
        """Show post-trial feedback with individual channel force traces plot"""
        from PySide6.QtWidgets import (
            QDialog,
            QVBoxLayout,
            QHBoxLayout,
            QPushButton,
            QSizePolicy,
        )
        from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
        from matplotlib.figure import Figure

        # Create dialog
        dialog = QDialog(self)
        dialog.setWindowTitle("Training Trial Complete - Force Review")
        dialog.resize(1000, 700)

        layout = QVBoxLayout(dialog)

        # Create matplotlib figure
        fig = Figure(figsize=(10, 6))
        canvas = FigureCanvas(fig)
        canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        ax = fig.add_subplot(111)

        # Get force data from widget for each channel
        colors = ["#4a9eff", "#48BB78", "#F6AD55", "#E53E3E", "#9F7AEA", "#38B2AC"]

        # Plot individual channel traces from stored data
        plotted_channels = []
        for idx, ch_name in enumerate(self._selected_channels):
            # Get data from _individual_channel_data (stored for all trials now)
            if (
                ch_name in self._individual_channel_data
                and self._individual_channel_data[ch_name]
            ):
                force_data = self._individual_channel_data[ch_name]
                times = [point[0] for point in force_data]
                forces = [point[1] for point in force_data]

                finger_label = self._channel_finger_labels.get(ch_name, ch_name)
                color = colors[idx % len(colors)]
                ax.plot(
                    times,
                    forces,
                    label=finger_label,
                    linewidth=2,
                    color=color,
                    alpha=0.8,
                )
                plotted_channels.append(ch_name)

        # If no channels were plotted, show a message
        if not plotted_channels:
            ax.text(
                0.5,
                0.5,
                "No force data recorded",
                ha="center",
                va="center",
                transform=ax.transAxes,
                fontsize=16,
                color="gray",
            )

        # Plot target trapezoid outline
        total_duration = self._calculate_total_duration()
        rest1_end = self._rest_duration_start
        ramp1_end = rest1_end + self._ramp_duration
        hold_end = ramp1_end + self._hold_duration
        ramp2_end = hold_end + self._ramp_duration

        trap_times = [0, rest1_end, ramp1_end, hold_end, ramp2_end, total_duration]
        trap_forces = [0, 0, self._target_mvc_percent, self._target_mvc_percent, 0, 0]
        ax.plot(trap_times, trap_forces, "k--", linewidth=2, label="Target", alpha=0.5)

        # Shade tolerance bands - simple vertical tolerance
        n_points = 1000
        times_fine = np.linspace(0, total_duration, n_points)
        targets = [self._get_current_target(t) for t in times_fine]
        half_tol = self._tolerance_percent / 2.0

        upper_band = [t + half_tol for t in targets]
        lower_band = [max(0, t - half_tol) for t in targets]

        ax.fill_between(
            times_fine,
            lower_band,
            upper_band,
            color="gray",
            alpha=0.2,
            label="Tolerance",
        )

        ax.set_xlabel("Time (s)", fontsize=12)
        ax.set_ylabel("Force (% MVC)", fontsize=12)
        
        # Create title with sample count if recording was active
        title = "Individual Finger Forces During Trial"
        if self._last_trial_sample_count > 0:
            title += f"\nSamples Collected: {self._last_trial_sample_count:,}"
        
        ax.set_title(title, fontsize=14, fontweight="bold")
        ax.legend(loc="upper right", fontsize=10)
        ax.grid(True, alpha=0.3)
        ax.set_xlim(0, total_duration)
        # Set y-axis max to target + tolerance/2 + 5% buffer
        y_max = self._target_mvc_percent + self._tolerance_percent / 2.0 + 5.0
        ax.set_ylim(0, y_max)

        fig.tight_layout()
        layout.addWidget(canvas)

        # Calculate and display statistics

        stats_text = QLabel()
        stats_html = "<div style='background-color: #2d2d2d; padding: 15px; border-radius: 5px; text-align: center;'>"

        if self._imbalance_ever_exceeded:
            stats_html += "<span style='color: #ff6b6b; font-weight: bold; font-size: 20px;'>\u2718 UNSUCCESSFUL</span><br><br>"
            stats_html += "<span style='color: #ff6b6b; font-size: 14px;'>Individual finger forces exceeded the tolerance at some point during the trial.<br>"
            stats_html += "Try to keep forces more balanced throughout the entire protocol.</span>"
        else:
            stats_html += "<span style='color: #48BB78; font-weight: bold; font-size: 20px;'>\u2714 SUCCESSFUL</span><br><br>"
            stats_html += "<span style='color: #48BB78; font-size: 14px;'>All forces remained within tolerance throughout the entire trial!</span>"

        stats_html += "</div>"
        stats_text.setText(stats_html)
        stats_text.setWordWrap(True)
        layout.addWidget(stats_text)

        # Close button
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        close_btn.setStyleSheet("padding: 10px 30px; font-size: 12px;")
        button_layout.addWidget(close_btn)
        button_layout.addStretch()
        layout.addLayout(button_layout)

        # Show dialog
        dialog.exec()

        # After review, automatically show individual channel traces
        for ch_name, checkbox in self._channel_checkboxes.items():
            if ch_name in self._latest_channel_mvc_percents:
                checkbox.setChecked(True)
        self._status_label.setText("Protocol completed successfully!")
        self._status_label.setStyleSheet("color: #48BB78; font-weight: bold;")
        self._progress_bar.setValue(100)

        self._start_btn.setEnabled(True)

        self.protocolCompleted.emit()