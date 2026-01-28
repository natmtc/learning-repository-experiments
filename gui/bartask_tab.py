"""
Bar Task - COMPLETELY DIFFERENT BUTTON APPROACH

Changes:
1. Lambda connections for buttons
2. Immediate debug prints when clicked
3. Try-except everywhere
4. Sample auto-populates text box
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QDoubleSpinBox, QGroupBox, QProgressBar, QMessageBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QFileDialog, QSpinBox, QTextEdit,
    QSplitter, QFrame, QCheckBox, QApplication,
)
from PySide6.QtCore import Qt, Signal, Slot, QTimer
from PySide6.QtGui import QColor

from typing import Optional, List, Dict
from datetime import datetime
from pathlib import Path
import csv
import traceback

from clients.base import NovecentoClient, StreamData
from data.managers import CalibrationManager, TrialLogger, DataRecorder, RecordingMetadata
from protocols import (
    BarTaskProtocol, BarTaskParams, BarSpec, BarTrialResult,
    TrialState, Direction, create_sample_bar_task_csv,
)
from gui.widgets import BeautifulPianoBarTask


class BarTaskTab(QWidget):
    trialCompleted = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)

        self._client: Optional[NovecentoClient] = None
        self._calibration_manager: Optional[CalibrationManager] = None
        self._trial_logger: Optional[TrialLogger] = None
        self._protocol: Optional[BarTaskProtocol] = None
        self._recorder: Optional[DataRecorder] = None
        self._data_folder: Optional[Path] = None

        self._bar_specs: List[BarSpec] = []
        self._available_aux_channels: List[str] = []
        self._trial_count = 0
        self._is_running = False
        self._is_streaming = False
        self._countdown_active = False
        self._protocol_start_time: Optional[datetime] = None
        self._time_to_target_enabled = True
        self._time_in_trial = 0.0
        self._just_reached_target = False  # NEW: Track when we first reach target
        self._reached_target_time = None  # NEW: When we reached target
        self._display_phase = "waiting"  # NEW: "waiting", "reaching", "just_reached", "holding", "complete"
        self._SHOW_HOLD_MESSAGE = False  # SIMPLE FLAG: Show "NOW HOLD FOR" message

        self._display_refresh_ms: int = 50

        self._latest_channel_values: Dict[str, float] = {}
        self._latest_channel_mvc_percents: Dict[str, float] = {}
        self._channel_offset_values: Dict[str, float] = {}
        self._channel_mvc_values: Dict[str, float] = {}

        self._setup_ui()

        self._display_timer = QTimer()
        self._display_timer.timeout.connect(self._update_display)
        
        # DEBUG: Verify time to target widgets are enabled
        print(f"[BarTask] Init complete - Time to target checkbox enabled: {self._time_to_target_check.isEnabled()}")
        print(f"[BarTask] Init complete - Time to target spinbox enabled: {self._time_to_target_spin.isEnabled()}")
        print(f"[BarTask] Init complete - Time to target checked: {self._time_to_target_check.isChecked()}")
        print(f"[BarTask] __init__ complete")

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Horizontal)

        # LEFT PANEL
        config_widget = QWidget()
        config_layout = QVBoxLayout(config_widget)

        # File loading
        file_group = QGroupBox("Task Configuration")
        file_layout = QVBoxLayout(file_group)

        file_btn_layout = QHBoxLayout()
        self._load_btn = QPushButton("📁 Load CSV")
        self._load_btn.clicked.connect(lambda: self._safe_call(self._load_csv))
        file_btn_layout.addWidget(self._load_btn)

        # SAMPLE BUTTON - AUTO POPULATES
        self._create_sample_btn = QPushButton("📝 Sample")
        self._create_sample_btn.clicked.connect(lambda: self._safe_call(self._create_sample))
        file_btn_layout.addWidget(self._create_sample_btn)
        file_layout.addLayout(file_btn_layout)

        self._file_label = QLabel("No file loaded")
        self._file_label.setStyleSheet("color: #888888;")
        file_layout.addWidget(self._file_label)

        file_layout.addWidget(QLabel("Manual entry:"))
        self._manual_entry = QTextEdit()
        self._manual_entry.setMaximumHeight(120)
        self._manual_entry.setPlaceholderText("Click 'Sample' button to load example")
        file_layout.addWidget(self._manual_entry)

        self._parse_btn = QPushButton("✓ Parse")
        self._parse_btn.clicked.connect(lambda: self._safe_call(self._parse_manual_entry))
        file_layout.addWidget(self._parse_btn)

        config_layout.addWidget(file_group)

        # Parameters
        params_group = QGroupBox("Parameters")
        params_layout = QGridLayout(params_group)

        params_layout.addWidget(QLabel("Tolerance (±%):"), 0, 0)
        self._tolerance_spin = QDoubleSpinBox()
        self._tolerance_spin.setRange(1, 50)
        self._tolerance_spin.setValue(5)
        self._tolerance_spin.valueChanged.connect(lambda v: self._bar_display.set_tolerance(v))
        params_layout.addWidget(self._tolerance_spin, 0, 1)

        time_to_target_layout = QHBoxLayout()
        self._time_to_target_check = QCheckBox("Time to Target (s):")
        self._time_to_target_check.setChecked(True)
        self._time_to_target_check.setEnabled(True)  # Explicitly enable
        self._time_to_target_check.stateChanged.connect(self._on_time_to_target_toggled)
        time_to_target_layout.addWidget(self._time_to_target_check)
        
        self._time_to_target_spin = QDoubleSpinBox()
        self._time_to_target_spin.setRange(1, 30)
        self._time_to_target_spin.setValue(5)
        self._time_to_target_spin.setEnabled(True)  # Explicitly enable
        time_to_target_layout.addWidget(self._time_to_target_spin)
        params_layout.addLayout(time_to_target_layout, 1, 0, 1, 2)

        params_layout.addWidget(QLabel("Hold Time (s):"), 2, 0)
        self._hold_time_spin = QDoubleSpinBox()
        self._hold_time_spin.setRange(0.5, 30)
        self._hold_time_spin.setValue(3)
        params_layout.addWidget(self._hold_time_spin, 2, 1)

        params_layout.addWidget(QLabel("Trials:"), 3, 0)
        self._num_trials_spin = QSpinBox()
        self._num_trials_spin.setRange(1, 100)
        self._num_trials_spin.setValue(10)
        params_layout.addWidget(self._num_trials_spin, 3, 1)

        config_layout.addWidget(params_group)

        # CONTROL BUTTONS - USING LAMBDA
        control_group = QGroupBox("Control")
        control_layout = QVBoxLayout(control_group)

        self._arm_btn = QPushButton("▶ Arm Streaming")
        self._arm_btn.setEnabled(False)
        self._arm_btn.setMinimumHeight(45)
        self._arm_btn.setStyleSheet(
            "QPushButton { background-color: #4A9EFF; color: white; font-weight: bold; font-size: 14px; }"
        )
        # LAMBDA CONNECTION
        self._arm_btn.clicked.connect(lambda: self._safe_call(self._toggle_streaming))
        control_layout.addWidget(self._arm_btn)

        self._stream_status_label = QLabel("Configure first")
        self._stream_status_label.setStyleSheet("color: #9da3ab;")
        self._stream_status_label.setAlignment(Qt.AlignCenter)
        control_layout.addWidget(self._stream_status_label)

        self._start_btn = QPushButton("▶ Start Task")
        self._start_btn.setEnabled(False)
        self._start_btn.setMinimumHeight(45)
        self._start_btn.setStyleSheet(
            "QPushButton { background-color: #48BB78; color: white; font-weight: bold; font-size: 14px; }"
        )
        # LAMBDA CONNECTION
        self._start_btn.clicked.connect(lambda: self._safe_call(self._start_task))
        control_layout.addWidget(self._start_btn)

        # NEXT TRIAL - THE PROBLEM BUTTON
        self._next_btn = QPushButton("→ NEXT TRIAL")
        self._next_btn.setEnabled(False)
        self._next_btn.setMinimumHeight(50)
        self._next_btn.setStyleSheet(
            "QPushButton { background-color: #FFA726; color: white; font-weight: bold; font-size: 16px; }"
        )
        # LAMBDA CONNECTION WITH IMMEDIATE DEBUG
        self._next_btn.clicked.connect(lambda: print("🔥🔥🔥 NEXT TRIAL BUTTON CLICKED! 🔥🔥🔥") or self._safe_call(self._next_trial))
        control_layout.addWidget(self._next_btn)

        self._stop_btn = QPushButton("⬛ Stop")
        self._stop_btn.setEnabled(False)
        self._stop_btn.setStyleSheet("QPushButton { background-color: #ff0000; }")
        self._stop_btn.clicked.connect(lambda: self._safe_call(self._stop_task))
        control_layout.addWidget(self._stop_btn)
        
        # RESET ALL BUTTON
        self._reset_piano_btn = QPushButton("🔄 Reset All")
        self._reset_piano_btn.setMinimumHeight(40)
        self._reset_piano_btn.setStyleSheet(
            "QPushButton { background-color: #9b59b6; color: white; font-weight: bold; font-size: 14px; }"
        )
        self._reset_piano_btn.clicked.connect(lambda: self._safe_call(self._reset_piano))
        control_layout.addWidget(self._reset_piano_btn)

        config_layout.addWidget(control_group)

        # Results
        results_group = QGroupBox("Results")
        results_layout = QVBoxLayout(results_group)

        self._results_table = QTableWidget()
        self._results_table.setColumnCount(5)
        self._results_table.setHorizontalHeaderLabels(["#", "Hold %", "Reach", "Reach Time", "Hold Time"])
        self._results_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._results_table.setMaximumHeight(180)
        results_layout.addWidget(self._results_table)

        self._summary_label = QLabel("No trials")
        self._summary_label.setStyleSheet("color: #888888;")
        results_layout.addWidget(self._summary_label)
        
        # EXPORT BUTTON
        self._export_btn = QPushButton("📊 Export Results")
        self._export_btn.setMinimumHeight(35)
        self._export_btn.setStyleSheet(
            "QPushButton { background-color: #3498db; color: white; font-weight: bold; font-size: 13px; }"
        )
        self._export_btn.clicked.connect(lambda: self._safe_call(self._export_results))
        results_layout.addWidget(self._export_btn)

        config_layout.addWidget(results_group)
        config_layout.addStretch()

        splitter.addWidget(config_widget)

        # RIGHT PANEL
        viz_widget = QWidget()
        viz_layout = QVBoxLayout(viz_widget)

        status_frame = QFrame()
        status_frame.setStyleSheet("background-color: #2a2a3e; border-radius: 5px; padding: 15px;")
        status_layout = QVBoxLayout(status_frame)

        self._status_label = QLabel("Ready")
        self._status_label.setStyleSheet("color: white; font-size: 48px; font-weight: bold;")  # BIGGER!
        self._status_label.setAlignment(Qt.AlignCenter)
        self._status_label.setMinimumHeight(100)  # Taller
        status_layout.addWidget(self._status_label)
        
        # PROGRESS BAR for hold phase (hidden initially)
        self._hold_progress_bar = QProgressBar()
        self._hold_progress_bar.setRange(0, 100)
        self._hold_progress_bar.setTextVisible(True)
        self._hold_progress_bar.setFormat("%p%")
        self._hold_progress_bar.setMaximumHeight(45)  # Thicker!
        self._hold_progress_bar.setMinimumWidth(800)  # Longer!
        self._hold_progress_bar.setStyleSheet("""
            QProgressBar {
                border: 3px solid #48BB78;
                border-radius: 8px;
                text-align: center;
                height: 45px;
                font-size: 22px;
                font-weight: bold;
                background-color: #2a2a2a;
            }
            QProgressBar::chunk {
                background-color: #48BB78;
                border-radius: 5px;
            }
        """)
        self._hold_progress_bar.setVisible(False)  # Hidden initially
        status_layout.addWidget(self._hold_progress_bar, alignment=Qt.AlignCenter)  # Center it
        
        # Hold time label (shows "HOLD: 1.2s / 3.0s")
        self._hold_time_label = QLabel("")
        self._hold_time_label.setStyleSheet("color: #cccccc; font-size: 22px;")  # Match bar font
        self._hold_time_label.setAlignment(Qt.AlignCenter)
        self._hold_time_label.setVisible(False)  # Hidden initially
        status_layout.addWidget(self._hold_time_label)

        trial_info = QHBoxLayout()
        self._trial_label = QLabel("Trial: 0/0")
        self._trial_label.setStyleSheet("color: #cccccc; font-size: 24px; font-weight: bold;")  # BIGGER!
        trial_info.addWidget(self._trial_label)

        self._timer_label = QLabel("0.0 s")
        self._timer_label.setStyleSheet("color: #cccccc; font-size: 24px; font-weight: bold;")  # BIGGER!
        trial_info.addWidget(self._timer_label)
        status_layout.addLayout(trial_info)

        viz_layout.addWidget(status_frame)

        self._bar_display = BeautifulPianoBarTask()
        self._bar_display.setMinimumHeight(500)
        viz_layout.addWidget(self._bar_display, stretch=10)

        splitter.addWidget(viz_widget)
        splitter.setStretchFactor(1, 2)
        main_layout.addWidget(splitter)

    def _safe_call(self, func):
        """Wrapper to catch and print exceptions"""
        try:
            print(f"[BarTask] Calling {func.__name__}...")
            result = func()
            print(f"[BarTask] {func.__name__} completed")
            return result
        except Exception as e:
            print(f"[BarTask] ❌ ERROR in {func.__name__}: {e}")
            traceback.print_exc()
            QMessageBox.critical(self, "Error", f"{func.__name__} failed:\n{str(e)}")
    
    def _unlock_hold_message(self):
        """Called 1 second after reaching target to unlock and start countdown"""
        print(f"\n[BarTask] ⏰ 1 second elapsed - UNLOCKING message")
        print(f"[BarTask] Switching phase from 'just_reached' to 'holding'")
        self._display_phase = "holding"
    
    def _restart_display_timer(self):
        """Restart display timer after showing NOW HOLD FOR message"""
        print(f"\n{'!'*80}")
        print(f"!!! RESTARTING DISPLAY TIMER !!!")
        print(f"{'!'*80}\n")
        self._display_phase = "holding"
        if not self._display_timer.isActive():
            self._display_timer.start(self._display_refresh_ms)

    def set_client(self, client: NovecentoClient):
        self._client = client
        self._update_ui_state()

    def set_calibration_manager(self, manager: CalibrationManager):
        self._calibration_manager = manager

    def set_trial_logger(self, logger: TrialLogger):
        self._trial_logger = logger
    
    def set_data_folder(self, folder: Path):
        self._data_folder = folder

    def set_aux_channels(self, channels: List[str]):
        self._available_aux_channels = channels
        self._update_ui_state()

    def set_display_refresh_rate(self, ms: int):
        self._display_refresh_ms = ms
        
    def _on_time_to_target_toggled(self, state):
        """Handle time to target checkbox"""
        # Use isChecked() instead of comparing state
        self._time_to_target_enabled = self._time_to_target_check.isChecked()
        self._time_to_target_spin.setEnabled(self._time_to_target_enabled)
        print(f"[BarTask] Time to target: {'ENABLED' if self._time_to_target_enabled else 'DISABLED'} (value={self._time_to_target_spin.value()}s)")

    def _update_ui_state(self):
        has_channels = len(self._available_aux_channels) > 0
        has_config = len(self._bar_specs) > 0
        
        is_ready = (
            self._client is not None
            and self._client.is_connected
            and has_channels
            and has_config
        )
        
        self._start_btn.setEnabled(is_ready and not self._is_running)
        self._arm_btn.setEnabled(is_ready and not self._is_streaming)
        
        if is_ready:
            if self._is_streaming:
                self._stream_status_label.setText("✓ Streaming active")
                self._stream_status_label.setStyleSheet("color: #48BB78;")
            else:
                self._stream_status_label.setText("Ready")
                self._stream_status_label.setStyleSheet("color: #4A9EFF;")
        else:
            if not self._client or not self._client.is_connected:
                self._stream_status_label.setText("Connect device")
            elif not has_channels:
                self._stream_status_label.setText("Configure channels")
            elif not has_config:
                self._stream_status_label.setText("Load CSV")
            self._stream_status_label.setStyleSheet("color: #F6AD55;")

    def _create_sample(self):
        """AUTO-POPULATE sample CSV in text box"""
        print("[BarTask] Creating sample in text box")
        
        sample_text = """column_id,aux_channel,finger,direction,target_mvc_percent,hold_time_s
1,AUX2,index,ext,10,3
2,AUX3,middle,ext,15,3"""
        
        self._manual_entry.setPlainText(sample_text)
        self._file_label.setText("Sample loaded - click Parse")
        self._file_label.setStyleSheet("color: #4A9EFF;")
        print("[BarTask] Sample text populated (index + middle)!")

    def _load_csv(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Load CSV", "", "CSV Files (*.csv)")
        if filename:
            try:
                self._parse_csv_file(filename)
                self._file_label.setText(f"Loaded: {Path(filename).name}")
                self._file_label.setStyleSheet("color: #48BB78;")
            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))

    def _parse_manual_entry(self):
        print("[BarTask] Parsing manual entry")
        text = self._manual_entry.toPlainText().strip()
        if not text:
            print("[BarTask] No text to parse")
            return

        try:
            lines = text.split('\n')
            if any(h in lines[0].lower() for h in ['column', 'finger']):
                lines = lines[1:]
            
            self._bar_specs = []
            for line in lines:
                if not line.strip():
                    continue
                parts = [p.strip() for p in line.split(',')]
                if len(parts) >= 6:
                    spec = BarSpec(
                        finger=parts[2].lower(),
                        channel=parts[1],
                        direction=Direction.EXTENSION if parts[3].lower() == 'ext' else Direction.FLEXION,
                        target_mvc_percent=float(parts[4]),
                        hold_time_s=float(parts[5])
                    )
                    self._bar_specs.append(spec)

            if self._bar_specs:
                self._file_label.setText("Parsed successfully!")
                self._file_label.setStyleSheet("color: #48BB78;")
                self._setup_piano_display()
                self._check_calibration()
                self._update_ui_state()
                print(f"[BarTask] Parsed {len(self._bar_specs)} specs")
            else:
                QMessageBox.warning(self, "Error", "No valid entries")
        except Exception as e:
            print(f"[BarTask] Parse error: {e}")
            traceback.print_exc()
            QMessageBox.critical(self, "Error", str(e))

    def _parse_csv_file(self, filename: str):
        with open(filename, 'r') as f:
            reader = csv.DictReader(f)
            self._bar_specs = []
            for row in reader:
                spec = BarSpec(
                    finger=row['finger'].lower(),
                    channel=row['aux_channel'],
                    direction=Direction.EXTENSION if row['direction'].lower() == 'ext' else Direction.FLEXION,
                    target_mvc_percent=float(row['target_mvc_percent']),
                    hold_time_s=float(row['hold_time_s'])
                )
                self._bar_specs.append(spec)
        
        self._setup_piano_display()
        self._check_calibration()
        self._update_ui_state()

    def _setup_piano_display(self):
        if not self._bar_specs:
            return
        
        finger_config = {}
        for spec in self._bar_specs:
            if spec.finger not in finger_config:
                finger_config[spec.finger] = {'ext_target': 0, 'flex_target': 0}
            
            if spec.direction == Direction.EXTENSION:
                finger_config[spec.finger]['ext_target'] = spec.target_mvc_percent
            else:
                finger_config[spec.finger]['flex_target'] = spec.target_mvc_percent

        self._bar_display.setup_fingers(finger_config)
        self._bar_display.set_tolerance(self._tolerance_spin.value())

    def _check_calibration(self):
        if not self._calibration_manager or not self._bar_specs:
            return

        missing = []
        for spec in self._bar_specs:
            if not self._calibration_manager.get_mvc(spec.channel):
                missing.append(spec.channel)

        if missing:
            QMessageBox.warning(self, "Calibration", f"Calibrate: {', '.join(missing)}")

    def _toggle_streaming(self):
        if self._is_streaming:
            print("[BarTask] Disarming")
            
            if self._client and self._client.is_streaming:
                self._client.stop_streaming()
            
            self._display_timer.stop()
            self._is_streaming = False
            
            self._arm_btn.setText("▶ Arm Streaming")
            self._arm_btn.setStyleSheet(
                "QPushButton { background-color: #4A9EFF; color: white; font-weight: bold; font-size: 14px; }"
            )
            self._update_ui_state()
            
        else:
            print("[BarTask] Arming")
            
            self._channel_offset_values = {}
            self._channel_mvc_values = {}
            
            for spec in self._bar_specs:
                mvc = self._calibration_manager.get_mvc(spec.channel)
                offset = self._calibration_manager.get_offset(spec.channel)
                if mvc and offset is not None:
                    self._channel_mvc_values[spec.channel] = mvc
                    self._channel_offset_values[spec.channel] = offset

            if self._client:
                self._client.start_streaming(self._on_stream_data)
            
            self._display_timer.start(self._display_refresh_ms)
            self._is_streaming = True
            
            self._arm_btn.setText("⬛ Disarm")
            self._arm_btn.setStyleSheet(
                "QPushButton { background-color: #ff6b6b; color: white; font-weight: bold; font-size: 14px; }"
            )
            self._update_ui_state()

    def _start_task(self):
        print("[BarTask] ========== STARTING TASK ==========")

        self._channel_offset_values = {}
        self._channel_mvc_values = {}
        
        for spec in self._bar_specs:
            mvc = self._calibration_manager.get_mvc(spec.channel)
            offset = self._calibration_manager.get_offset(spec.channel)
            if mvc and offset is not None:
                self._channel_mvc_values[spec.channel] = mvc
                self._channel_offset_values[spec.channel] = offset

        calibration = {ch: (self._channel_mvc_values[ch], self._channel_offset_values[ch]) 
                      for ch in self._channel_mvc_values.keys()}
        
        time_to_target = self._time_to_target_spin.value() if self._time_to_target_enabled else 999.0
        
        print(f"[BarTask] Creating protocol with:")
        print(f"  - Time to Target: {time_to_target}s (enabled={self._time_to_target_enabled})")
        print(f"  - Hold Time: {self._hold_time_spin.value()}s")
        print(f"  - Tolerance: {self._tolerance_spin.value()}%")
        
        params = BarTaskParams(
            bar_specs=self._bar_specs,
            tolerance_percent=self._tolerance_spin.value(),
            time_to_target_s=time_to_target,
            hold_time_s=self._hold_time_spin.value()
        )
        
        self._protocol = BarTaskProtocol(params, calibration)
        self._protocol.set_state_callback(self._on_protocol_state_change)
        print(f"[BarTask] Protocol created: {self._protocol}")

        # Start trial logger with correct arguments
        if self._trial_logger:
            try:
                # start_session needs: subject_id, task_type, channels (optional)
                channels = list(self._channel_mvc_values.keys())
                self._trial_logger.start_session(
                    subject_id="bar_task_subject",  # You can get this from config later
                    task_type="bar_task",
                    channels=channels
                )
                print("[BarTask] Trial logger started")
            except Exception as e:
                print(f"[BarTask] Trial logger error: {e}")

        self._results_table.setRowCount(0)
        self._trial_count = 0
        self._is_running = False

        if self._client and not self._client.is_streaming:
            self._client.start_streaming(self._on_stream_data)
            self._is_streaming = True
        
        if not self._display_timer.isActive():
            self._display_timer.start(self._display_refresh_ms)

        # UI buttons
        self._start_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._arm_btn.setEnabled(False)
        self._next_btn.setEnabled(False)  # Will be enabled after trial 1
        
        print("[BarTask] ========== TASK STARTED ==========")
        print("[BarTask] Starting Trial 1 automatically...")
        
        # AUTO-START FIRST TRIAL (no need to click Next Trial)
        QTimer.singleShot(500, self._next_trial)  # Small delay for UI to update

    def _next_trial(self):
        """THIS IS THE FUNCTION THAT RUNS WHEN YOU CLICK NEXT TRIAL"""
        print("\n" + "="*60)
        print("🔥🔥🔥 _next_trial() CALLED! 🔥🔥🔥")
        print("="*60 + "\n")
        
        if not self._protocol:
            print("[BarTask] ❌ ERROR: No protocol!")
            QMessageBox.critical(self, "Error", "No protocol! Click Start Task first.")
            return

        max_trials = self._num_trials_spin.value()
        if self._trial_count >= max_trials:
            print("[BarTask] All trials complete")
            self._complete_task()
            return

        self._trial_count += 1
        self._trial_label.setText(f"Trial: {self._trial_count}/{max_trials}")
        self._next_btn.setEnabled(False)
        
        print(f"\n{'='*60}")
        print(f"TRIAL {self._trial_count} STARTING")
        print(f"{'='*60}\n")

        # CLEAR previous success/failure flash AND glow
        self._bar_display._clear_flash()
        self._bar_display.clear_result_glow()
        print("✓ Cleared previous trial flash and glow")

        # Countdown
        self._countdown_active = True
        self._bar_display.start_countdown()
        self._status_label.setText("GET READY...")
        self._status_label.setStyleSheet("color: #FFA726; font-size: 32px; font-weight: bold;")
        
        print("[BarTask] Starting countdown...")
        QTimer.singleShot(1000, lambda: self._countdown_step(2))

    def _countdown_step(self, remaining: int):
        print(f"[BarTask] Countdown: {remaining}")
        if remaining > 0:
            self._status_label.setText(f"{remaining}...")
            self._status_label.setStyleSheet("color: #FFA726; font-size: 48px; font-weight: bold;")
            QTimer.singleShot(1000, lambda: self._countdown_step(remaining - 1))
        else:
            print("[BarTask] Countdown complete - STARTING TRIAL")
            self._countdown_active = False
            
            if self._data_folder and not self._recorder:
                self._start_recording_for_trial()
            
            self._protocol.start_trial(self._trial_count)
            self._is_running = True
            self._protocol_start_time = datetime.now()
            self._time_in_trial = 0.0
            self._just_reached_target = False  # Reset flag
            self._SHOW_HOLD_MESSAGE = False  # Reset flag
            self._display_phase = "reaching"  # Set to reaching phase
            
            # Reset progress bar tracking for new trial
            if hasattr(self, '_bar_test_counter'):
                delattr(self, '_bar_test_counter')
            if hasattr(self, '_last_print_time'):
                delattr(self, '_last_print_time')
            print(f"[RESET] Progress bar reset for Trial {self._trial_count}")
            
            # BETTER GO MESSAGE
            if self._time_to_target_enabled:
                time_limit = self._time_to_target_spin.value()
                self._status_label.setText(f"YOU HAVE {time_limit:.0f}s to reach target! GO!")
                self._status_label.setStyleSheet("color: #FFA726; font-size: 36px; font-weight: bold;")
            else:
                self._status_label.setText("REACH TARGET - NO TIME LIMIT!")
                self._status_label.setStyleSheet("color: #48BB78; font-size: 36px; font-weight: bold;")
            
            print(f"\n{'='*60}")
            print(f"✓✓✓ TRIAL {self._trial_count} GO! ✓✓✓")
            print(f"{'='*60}\n")
    
    def _start_recording_for_trial(self):
        if not self._data_folder:
            return
        
        try:
            channels = {"emg": [], "aux": self._available_aux_channels}
            metadata = RecordingMetadata(
                subject_id="bar_task",
                protocol_type="bar_task",
                trial_number=self._trial_count,
                timestamp=datetime.now().isoformat(),
                channels=channels,
                sample_rate=2000,
                notes=f"Bar task trial {self._trial_count}"
            )
            
            self._recorder = DataRecorder(self._data_folder)
            self._recorder.start_recording(metadata)
            print(f"[BarTask] Recording started")
        except Exception as e:
            print(f"[BarTask] Recording error: {e}")

    def _stop_task(self):
        print("[BarTask] Stopping task")
        self._is_running = False
        
        if self._recorder:
            try:
                self._recorder.stop_recording()
            except:
                pass
            self._recorder = None

        if self._trial_logger:
            self._trial_logger.end_session()

        self._next_btn.setEnabled(False)
        self._stop_btn.setEnabled(False)
        
        self._start_btn.setText("▶ Start Task")
        self._start_btn.setStyleSheet(
            "QPushButton { background-color: #48BB78; color: white; font-weight: bold; font-size: 14px; }"
        )
        
        self._update_ui_state()
        self._status_label.setText("Stopped")
    
    def _reset_piano(self):
        """Reset EVERYTHING to initial state - piano, table, all displays"""
        print("[BarTask] Resetting EVERYTHING to initial state")
        
        # 1. RESET PIANO DISPLAY
        if hasattr(self, '_bar_display'):
            # Clear background flash color (green/red)
            if hasattr(self._bar_display, '_clear_flash'):
                self._bar_display._clear_flash()
            
            # Clear result glow effects
            if hasattr(self._bar_display, 'clear_result_glow'):
                self._bar_display.clear_result_glow()
            
            # Reset all bars to zero
            self._bar_display.update_forces({})
            
            # Reset all key widgets completely
            for key_widget in self._bar_display.findChildren(QWidget):
                if hasattr(key_widget, '_glow_intensity'):
                    key_widget._glow_intensity = 0
                    key_widget._glow_target = 0
                if hasattr(key_widget, 'extension_value'):
                    key_widget.extension_value = 0
                if hasattr(key_widget, 'flexion_value'):
                    key_widget.flexion_value = 0
                if hasattr(key_widget, 'extension_in_target'):
                    key_widget.extension_in_target = False
                if hasattr(key_widget, 'flexion_in_target'):
                    key_widget.flexion_in_target = False
                key_widget.update()
            
            # Force full repaint
            self._bar_display.update()
            
            print("[BarTask] ✓ Piano display reset!")
        
        # 2. RESET TABLE
        self._results_table.setRowCount(0)
        print("[BarTask] ✓ Table cleared!")
        
        # 3. RESET COUNTERS
        self._trial_count = 0
        self._trial_label.setText("Trial: 0/0")
        self._timer_label.setText("0.0 s")
        print("[BarTask] ✓ Counters reset!")
        
        # 4. RESET STATUS DISPLAY
        self._status_label.setText("Ready")
        self._status_label.setStyleSheet("color: white; font-size: 48px; font-weight: bold;")
        self._status_label.setVisible(True)
        self._hold_progress_bar.setVisible(False)
        self._hold_time_label.setVisible(False)
        print("[BarTask] ✓ Status display reset!")
        
        # 5. RESET SUMMARY
        self._summary_label.setText("0 trials")
        self._summary_label.setStyleSheet("color: #cccccc;")
        print("[BarTask] ✓ Summary reset!")
        
        # 6. RESET FLAGS
        self._is_running = False
        self._SHOW_HOLD_MESSAGE = False
        if hasattr(self, '_reached_target_time'):
            self._reached_target_time = None
        if hasattr(self, '_protocol_start_time'):
            self._protocol_start_time = None
        print("[BarTask] ✓ Internal flags reset!")
        
        # 7. RESET BUTTONS
        self._start_btn.setEnabled(True)
        self._start_btn.setText("▶ Start Task")
        self._start_btn.setStyleSheet(
            "QPushButton { background-color: #48BB78; color: white; font-weight: bold; font-size: 14px; }"
        )
        self._next_btn.setEnabled(False)
        self._stop_btn.setEnabled(False)
        print("[BarTask] ✓ Buttons reset!")
        
        print("[BarTask] 🎉 COMPLETE RESET DONE! Ready to start fresh!")
    
    def _export_results(self):
        """Export results table to CSV file"""
        print("[BarTask] Exporting results...")
        
        # Check if there are results to export
        if self._results_table.rowCount() == 0:
            QMessageBox.warning(self, "No Data", "No trials to export!")
            return
        
        # Ask user where to save
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Export Results",
            f"bartask_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            "CSV Files (*.csv)"
        )
        
        if not filename:
            return  # User cancelled
        
        try:
            with open(filename, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                
                # Write header
                headers = []
                for col in range(self._results_table.columnCount()):
                    header_item = self._results_table.horizontalHeaderItem(col)
                    headers.append(header_item.text() if header_item else f"Column {col}")
                writer.writerow(headers)
                
                # Write data rows
                for row in range(self._results_table.rowCount()):
                    row_data = []
                    for col in range(self._results_table.columnCount()):
                        item = self._results_table.item(row, col)
                        text = item.text() if item else ""
                        # Replace checkmark/cross with simple text for compatibility
                        text = text.replace('✓', 'Pass').replace('✗', 'Fail')
                        row_data.append(text)
                    writer.writerow(row_data)
            
            print(f"[BarTask] ✓ Results exported to: {filename}")
            QMessageBox.information(
                self,
                "Export Successful",
                f"Results exported to:\n{filename}"
            )
            
        except Exception as e:
            print(f"[BarTask] ✗ Export failed: {e}")
            QMessageBox.critical(
                self,
                "Export Failed",
                f"Failed to export results:\n{str(e)}"
            )


    def _on_stream_data(self, data: StreamData):
        if data.aux_samples.size == 0:
            return

        if self._recorder and self._is_running and not self._countdown_active:
            try:
                self._recorder.write_samples(data.emg_samples, data.aux_samples, data.timestamps)
            except:
                pass

        channels_needed = []
        for spec in self._bar_specs:
            if spec.channel not in channels_needed:
                channels_needed.append(spec.channel)

        for ch_name in channels_needed:
            if ch_name in self._available_aux_channels:
                idx = self._available_aux_channels.index(ch_name)
                if idx < data.aux_samples.shape[0] and data.aux_samples.shape[1] > 0:
                    raw_value = float(data.aux_samples[idx, -1])
                    self._latest_channel_values[ch_name] = raw_value
                    
                    offset = self._channel_offset_values.get(ch_name, 0.0)
                    mvc = self._channel_mvc_values.get(ch_name, 1.0)
                    corrected = raw_value - offset
                    mvc_pct = (corrected / mvc) * 100.0 if mvc > 0 else 0.0
                    self._latest_channel_mvc_percents[ch_name] = mvc_pct

        if self._is_running and not self._countdown_active and self._protocol:
            for i in range(data.aux_samples.shape[1]):
                force_values = {}
                for ch_name in channels_needed:
                    if ch_name in self._available_aux_channels:
                        idx = self._available_aux_channels.index(ch_name)
                        if idx < data.aux_samples.shape[0]:
                            force_values[ch_name] = data.aux_samples[idx, i]

                if force_values:
                    state = self._protocol.update(force_values)
                    
                    if state != TrialState.RUNNING:
                        break

    def _update_display(self):
        if self._countdown_active:
            return

        if self._is_running and self._protocol_start_time:
            elapsed = (datetime.now() - self._protocol_start_time).total_seconds()
            self._timer_label.setText(f"{elapsed:.1f} s")
            self._time_in_trial = elapsed
            
            # Check if we reached target BY LOOKING AT PROTOCOL DIRECTLY
            if self._protocol and hasattr(self._protocol, '_first_all_in_target_time'):
                if self._protocol._first_all_in_target_time is not None and not self._SHOW_HOLD_MESSAGE:
                    # JUST REACHED! Set flag NOW!
                    self._SHOW_HOLD_MESSAGE = True
                    self._reached_target_time = datetime.now()
                    print(f"\n{'!'*80}")
                    print(f"!!! REACHED TARGET! FLAG SET TO TRUE! !!!")
                    print(f"!!! self._SHOW_HOLD_MESSAGE = {self._SHOW_HOLD_MESSAGE}")
                    print(f"{'!'*80}\n")
            
            # Check if we reached target
            if self._SHOW_HOLD_MESSAGE:
                # IN HOLD PHASE - Show progress bar!
                
                # Hide countdown message, show progress bar
                self._status_label.setVisible(False)
                self._hold_progress_bar.setVisible(True)
                self._hold_time_label.setVisible(True)
                
                # Calculate time since reaching target
                if hasattr(self, '_reached_target_time') and self._reached_target_time:
                    time_since_reached = (datetime.now() - self._reached_target_time).total_seconds()
                else:
                    time_since_reached = 0
                
                hold_needed = self._hold_time_spin.value()
                
                # Calculate percentage: 0% at start, 100% after hold_needed seconds
                percentage = int((time_since_reached / hold_needed) * 100) if hold_needed > 0 else 0
                percentage = min(100, max(0, percentage))
                
                # Update progress bar
                self._hold_progress_bar.setValue(percentage)
                
                # Print every 0.5 seconds
                if not hasattr(self, '_last_print_time'):
                    self._last_print_time = 0
                if int(time_since_reached * 2) != self._last_print_time:
                    self._last_print_time = int(time_since_reached * 2)
                    print(f"[PROGRESS] Time: {time_since_reached:.2f}s / {hold_needed:.1f}s = {percentage}%")
                
                # Update label with both elapsed and accumulated time
                # Get accumulated time in target from protocol
                if self._protocol and hasattr(self._protocol, 'get_bar_states'):
                    bar_states = self._protocol.get_bar_states()
                    if bar_states:
                        max_hold = max(s.time_in_target for s in bar_states.values())
                        all_in_target = all(s.in_target for s in bar_states.values())
                        
                        self._hold_time_label.setText(f"HOLD: {time_since_reached:.1f}s / {hold_needed:.1f}s (in target: {max_hold:.1f}s)")
                        
                        # Change bar color if dropped out
                        if not all_in_target and time_since_reached > 0:
                            # Dropped out!
                            self._hold_progress_bar.setStyleSheet("""
                                QProgressBar {
                                    border: 3px solid #F44336;
                                    border-radius: 8px;
                                    text-align: center;
                                    height: 45px;
                                    font-size: 22px;
                                    font-weight: bold;
                                    background-color: #2a2a2a;
                                }
                                QProgressBar::chunk {
                                    background-color: #F44336;
                                    border-radius: 5px;
                                }
                            """)
                            self._hold_time_label.setText(f"DROPPED OUT! ({max_hold:.1f}s in target)")
                            self._hold_time_label.setStyleSheet("color: #F44336; font-size: 22px; font-weight: bold;")
            
            else:
                # STILL REACHING - Show countdown
                
                # Show countdown message, hide progress bar
                self._status_label.setVisible(True)
                self._hold_progress_bar.setVisible(False)
                self._hold_time_label.setVisible(False)
                
                if self._time_to_target_enabled:
                    time_limit = self._time_to_target_spin.value()
                    remaining = time_limit - elapsed
                    if remaining > 0:
                        self._status_label.setText(f"{remaining:.1f}s to reach target")
                        self._status_label.setStyleSheet("color: #FFA726; font-size: 32px; font-weight: bold;")
                    else:
                        # TIMEOUT!
                        self._status_label.setText("TIME UP! FAILED")
                        self._status_label.setStyleSheet("color: #F44336; font-size: 42px; font-weight: bold;")
                else:
                    self._status_label.setText("REACH TARGET")
                    self._status_label.setStyleSheet("color: #48BB78; font-size: 36px; font-weight: bold;")

        if self._latest_channel_mvc_percents:
            forces = {}
            
            for spec in self._bar_specs:
                finger = spec.finger
                channel = spec.channel
                direction = spec.direction
                
                if finger not in forces:
                    forces[finger] = {
                        'ext': 0, 'flex': 0,
                        'ext_in_target': False, 'flex_in_target': False
                    }
                
                if channel in self._latest_channel_mvc_percents:
                    mvc_pct = abs(self._latest_channel_mvc_percents[channel])
                    target = spec.target_mvc_percent
                    tolerance = self._tolerance_spin.value()
                    in_target = abs(mvc_pct - target) <= tolerance if target > 0 else False
                    
                    if direction == Direction.EXTENSION:
                        forces[finger]['ext'] = mvc_pct
                        forces[finger]['ext_in_target'] = in_target
                    else:
                        forces[finger]['flex'] = mvc_pct
                        forces[finger]['flex_in_target'] = in_target
            
            self._bar_display.update_forces(forces)

    def _on_protocol_state_change(self, state: TrialState):
        print(f"[BarTask] Protocol state: {state}")
        
        # When trial completes, show percentage
        if state == TrialState.SUCCESS or state == TrialState.COMPLETED:
            # Calculate percentage for hold phase
            percentage = self._protocol.get_hold_percentage()
            self._on_trial_complete(True, percentage)
        elif state in [TrialState.FAILURE_TIMEOUT, TrialState.FAILURE_OUT_OF_RANGE]:
            self._on_trial_complete(False, 0.0)

    def _on_trial_complete(self, success: bool, percentage: float = 0.0):
        result = self._protocol.compute_results()
        
        # Hide progress bar, show status label
        self._hold_progress_bar.setVisible(False)
        self._hold_time_label.setVisible(False)
        self._status_label.setVisible(True)
        
        # Determine what happened
        if success:
            # Show percentage-based result
            print(f"\n{'='*60}")
            print(f"✓ TRIAL {self._trial_count} COMPLETED")
            print(f"Phase 1 (Reach): {result.time_to_target:.1f}s")
            print(f"Phase 2 (Hold): You were {percentage:.1f}% in target")
            print(f"  (Required: {self._hold_time_spin.value():.1f}s hold time)")
            print(f"{'='*60}\n")
            
            # Color code based on 70% threshold
            if percentage >= 70.0:
                color = "#48BB78"  # Green
                symbol = "✓"
            else:
                color = "#F44336"  # Red
                symbol = "✗"
            
            self._status_label.setText(f"You were {percentage:.0f}% in target")
            self._status_label.setStyleSheet(f"color: {color}; font-size: 32px; font-weight: bold;")
            
            # Flash keys with appropriate color
            if percentage >= 70.0:
                self._bar_display.show_success()
            else:
                self._bar_display.show_failure()
        else:
            print(f"\n{'='*60}")
            print(f"✗✗✗ TRIAL {self._trial_count} FAILED ✗✗✗")
            if result.time_to_target == 0 or (self._time_to_target_enabled and result.time_to_target > self._time_to_target_spin.value()):
                print(f"Failed in Phase 1 (Reach): Timeout")
            else:
                print(f"Phase 1 (Reach): {result.time_to_target:.1f}s ✓")
                print(f"Failed in Phase 2 (Hold): Issue during hold")
            print(f"{'='*60}\n")
            
            self._status_label.setText("✗ FAILED")
            self._status_label.setStyleSheet("color: #F44336; font-size: 42px; font-weight: bold;")
            self._bar_display.show_failure()
        
        self._is_running = False
        
        if self._recorder:
            try:
                filepath = self._recorder.stop_recording()
                print(f"[BarTask] Recording saved: {filepath}")
            except:
                pass
            self._recorder = None

        # result already computed above

        # Table: Update with percentage
        if self._trial_logger:
            from data.managers import TrialResult
            trial_result = TrialResult(
                trial_number=result.trial_number,
                start_time=result.start_time.isoformat() if isinstance(result.start_time, datetime) else result.start_time,
                end_time=result.end_time.isoformat() if isinstance(result.end_time, datetime) else result.end_time,
                success=success,
                time_in_target=result.hold_time_achieved,
                rms_error=0.0,
                target_value=0.0,
                mean_value=0.0,
                raw_data={},
                timestamps=result.timestamps,
                target_trace=None,
                extra_data={'bar_results': result.bar_results, 'hold_percentage': percentage}
            )
            self._trial_logger.log_trial(trial_result)

        row = self._results_table.rowCount()
        self._results_table.insertRow(row)
        self._results_table.setItem(row, 0, QTableWidgetItem(str(result.trial_number)))
        
        # Column 1: Overall result - show percentage or fail
        if success:
            result_text = f"{percentage:.0f}%"
            result_color = "#48BB78" if percentage >= 70.0 else "#F44336"
        else:
            result_text = "✗"
            result_color = "#F44336"
        result_item = QTableWidgetItem(result_text)
        result_item.setForeground(QColor(result_color))
        self._results_table.setItem(row, 1, result_item)
        
        # Column 2: Time to Target result (if enabled)
        if self._time_to_target_enabled:
            time_limit = self._time_to_target_spin.value()
            reached_in_time = result.time_to_target <= time_limit if result.time_to_target > 0 else False
            reach_item = QTableWidgetItem("✓" if reached_in_time else "✗")
            reach_item.setForeground(QColor("#48BB78") if reached_in_time else QColor("#F44336"))
            self._results_table.setItem(row, 2, reach_item)
        else:
            self._results_table.setItem(row, 2, QTableWidgetItem("-"))
        
        # Column 3: Time to reach
        self._results_table.setItem(row, 3, QTableWidgetItem(f"{result.time_to_target:.1f}s"))
        
        # Column 4: Hold time
        self._results_table.setItem(row, 4, QTableWidgetItem(f"{result.hold_time_achieved:.1f}s"))

        self._update_summary()

        if self._trial_count >= self._num_trials_spin.value():
            self._complete_task()
        else:
            self._next_btn.setEnabled(True)
            print("[BarTask] ✓ NEXT TRIAL button re-enabled")

    def _complete_task(self):
        self._is_running = False

        if self._trial_logger:
            self._trial_logger.end_session()

        self._next_btn.setEnabled(False)
        self._stop_btn.setEnabled(False)
        
        self._start_btn.setText("▶ Start Task")
        self._start_btn.setStyleSheet(
            "QPushButton { background-color: #48BB78; color: white; font-weight: bold; font-size: 14px; }"
        )
        
        self._update_ui_state()

        self._status_label.setText("🎉 COMPLETE!")
        self._status_label.setStyleSheet("color: #48BB78; font-size: 36px; font-weight: bold;")

        n_rows = self._results_table.rowCount()
        n_success = sum(1 for i in range(n_rows) if "✓" in self._results_table.item(i, 1).text())
        
        QMessageBox.information(
            self, "Complete",
            f"Trials: {n_rows}\nSuccess: {n_success}\nRate: {(n_success/n_rows)*100:.1f}%"
        )

    def _update_summary(self):
        n_rows = self._results_table.rowCount()
        if n_rows > 0:
            n_success = sum(1 for i in range(n_rows) if "✓" in self._results_table.item(i, 2).text())
            self._summary_label.setText(f"{n_rows} trials | {n_success} success | {(n_success/n_rows)*100:.0f}%")
            self._summary_label.setStyleSheet("color: #48BB78;")
        else:
            self._summary_label.setText("0 trials")
            self._summary_label.setStyleSheet("color: #cccccc;")