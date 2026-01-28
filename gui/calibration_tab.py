"""
Calibration Tab - MVC and Offset measurement procedures.

FIXED: Uses get_active_channels() instead of list_channels()
FIXED: Thread-safe data buffering
FIXED: Single _update_display method
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QComboBox, QLineEdit, QSpinBox,
    QGroupBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QDoubleSpinBox, QProgressBar
)
from PySide6.QtCore import Qt, Signal, Slot, QTimer
from PySide6.QtGui import QColor

from typing import Optional, List, Dict, Callable
from datetime import datetime
from collections import deque
import numpy as np
import threading

from data.managers import CalibrationManager, MVCRecord, OffsetRecord
from gui.widgets import LivePlotWidget, CalibrationProgress


class CalibrationTab(QWidget):
    """
    Calibration tab for MVC and offset measurements.
    """
    
    calibrationUpdated = Signal()  # Emitted when calibration data changes
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._client = None
        self._config_tab = None  # Reference to config tab for stream registration
        self._calibration_manager: Optional[CalibrationManager] = None
        self._subject_id: str = ""
        
        self._current_channel: Optional[str] = None
        self._collecting_data = False
        self._data_buffer: List[float] = []
        self._collection_start_time: float = 0
        self._collection_duration: float = 5.0  # Track duration for progress
        
        self._stream_callback: Optional[Callable] = None
        
        # Display refresh rate (controlled by Configuration tab)
        self._display_refresh_ms: int = 50
        
        # Channel index for data extraction
        self._channel_index: int = 0
        self._collection_type: str = ""
        
        # Store available aux channels
        self._aux_channels: List[str] = []
        
        # THREAD-SAFE SAMPLE BUFFER for display
        self._sample_buffer = deque(maxlen=100)
        self._latest_force: float = 0.0
        
        self._setup_ui()
        
        self._update_timer = QTimer()
        self._update_timer.timeout.connect(self._update_display)
    
    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        
        # Subject selection
        subject_layout = QHBoxLayout()
        subject_layout.addWidget(QLabel("Subject ID:"))
        self._subject_display = QLabel("Not set")
        self._subject_display.setStyleSheet("color: #00ccff; font-weight: bold;")
        subject_layout.addWidget(self._subject_display)
        subject_layout.addStretch()
        main_layout.addLayout(subject_layout)
        
        # Main content area
        content_layout = QHBoxLayout()
        
        # Left side - Channel selection and procedures
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        
        # Channel selection
        channel_group = QGroupBox("Auxiliary Channel Selection")
        channel_layout = QVBoxLayout(channel_group)
        
        self._channel_combo = QComboBox()
        self._channel_combo.currentTextChanged.connect(self._on_channel_changed)
        channel_layout.addWidget(self._channel_combo)
        
        # Current values display
        values_layout = QGridLayout()
        values_layout.addWidget(QLabel("Current Offset:"), 0, 0)
        self._offset_display = QLabel("----------------------------------------")
        self._offset_display.setStyleSheet("color: #ffcc00; font-size: 14px;")
        values_layout.addWidget(self._offset_display, 0, 1)
        
        values_layout.addWidget(QLabel("Current MVC:"), 1, 0)
        self._mvc_display = QLabel("----------------------------------------")
        self._mvc_display.setStyleSheet("color: #48BB78; font-size: 14px;")
        values_layout.addWidget(self._mvc_display, 1, 1)
        
        values_layout.addWidget(QLabel("Live Force:"), 2, 0)
        self._force_display = QLabel("----------------------------------------")
        self._force_display.setStyleSheet("color: #4a9eff; font-size: 24px; font-weight: bold;")
        values_layout.addWidget(self._force_display, 2, 1)
        
        channel_layout.addLayout(values_layout)
        left_layout.addWidget(channel_group)
        
        # Offset procedure
        offset_group = QGroupBox("Offset Measurement (Rest)")
        offset_layout = QVBoxLayout(offset_group)
        
        offset_params = QHBoxLayout()
        offset_params.addWidget(QLabel("Duration (s):"))
        self._offset_duration = QSpinBox()
        self._offset_duration.setRange(1, 30)
        self._offset_duration.setValue(3)
        offset_params.addWidget(self._offset_duration)
        offset_layout.addLayout(offset_params)
        
        offset_layout.addWidget(QLabel(
            "Keep ALL fingers/hand relaxed during measurement.\n"
            "This will set the baseline for all channels simultaneously."
        ))
        
        # Button to record all offsets at once
        self._offset_all_btn = QPushButton("Record ALL Channel Offsets")
        self._offset_all_btn.clicked.connect(self._start_offset_all_recording)
        self._offset_all_btn.setStyleSheet("""
            QPushButton {
                background-color: #cc4400;
                color: white;
                padding: 12px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #ee5500;
            }
            QPushButton:disabled {
                background-color: #444444;
            }
        """)
        offset_layout.addWidget(self._offset_all_btn)
        
        # Separator
        offset_layout.addWidget(QLabel("-" * 40))
        offset_layout.addWidget(QLabel("Or record single channel:"))
        
        self._offset_btn = QPushButton("Record Offset (Current Channel)")
        self._offset_btn.clicked.connect(self._start_offset_recording)
        self._offset_btn.setStyleSheet("""
            QPushButton {
                background-color: #cc8800;
                color: white;
                padding: 10px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #ee9900;
            }
            QPushButton:disabled {
                background-color: #444444;
            }
        """)
        offset_layout.addWidget(self._offset_btn)
        
        left_layout.addWidget(offset_group)
        
        # MVC procedure
        mvc_group = QGroupBox("MVC Measurement (Max Effort)")
        mvc_layout = QVBoxLayout(mvc_group)
        
        mvc_params = QHBoxLayout()
        mvc_params.addWidget(QLabel("Duration (s):"))
        self._mvc_duration = QSpinBox()
        self._mvc_duration.setRange(1, 30)
        self._mvc_duration.setValue(3)
        mvc_params.addWidget(self._mvc_duration)
        mvc_layout.addLayout(mvc_params)
        
        mvc_layout.addWidget(QLabel(
            "Apply maximum voluntary contraction during measurement."
        ))
        
        self._mvc_btn = QPushButton("Record MVC")
        self._mvc_btn.clicked.connect(self._start_mvc_recording)
        self._mvc_btn.setStyleSheet("""
            QPushButton {
                background-color: #006600;
                color: white;
                padding: 10px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #008800;
            }
            QPushButton:disabled {
                background-color: #444444;
            }
        """)
        mvc_layout.addWidget(self._mvc_btn)
        
        left_layout.addWidget(mvc_group)
        
        # Progress indicator
        self._progress = CalibrationProgress()
        self._progress.countdownFinished.connect(self._on_collection_complete)
        left_layout.addWidget(self._progress)
        
        left_layout.addStretch()
        content_layout.addWidget(left_panel)
        
        # Right side - Visualization and results table
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        
        # Live force plot
        right_layout.addWidget(QLabel("Live Force Signal:"))
        self._force_plot = LivePlotWidget(n_channels=1, buffer_seconds=5.0)
        self._force_plot.set_channel_names(["Force"])
        self._force_plot.set_y_range(-0.5, 3.0)
        self._force_plot.setMinimumHeight(250)
        right_layout.addWidget(self._force_plot)
        
        # Calibration history table
        right_layout.addWidget(QLabel("Calibration History:"))
        self._history_table = QTableWidget()
        self._history_table.setColumnCount(5)
        self._history_table.setHorizontalHeaderLabels([
            "Channel", "Type", "Value", "Time", "Notes"
        ])
        self._history_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch
        )
        right_layout.addWidget(self._history_table)
        
        # Export/import buttons
        btn_layout = QHBoxLayout()
        self._export_btn = QPushButton("Export Calibration")
        self._export_btn.clicked.connect(self._export_calibration)
        btn_layout.addWidget(self._export_btn)
        
        self._clear_btn = QPushButton("Clear All")
        self._clear_btn.clicked.connect(self._clear_calibration)
        btn_layout.addWidget(self._clear_btn)
        
        right_layout.addLayout(btn_layout)
        
        content_layout.addWidget(right_panel)
        content_layout.setStretch(0, 1)
        content_layout.setStretch(1, 2)
        
        main_layout.addLayout(content_layout)
    
    def set_client(self, client):
        """Set the Novecento client"""
        self._client = client
        self._update_channels()
    
    def set_config_tab(self, config_tab):
        """Set reference to configuration tab for stream registration"""
        self._config_tab = config_tab
    
    def set_subject(self, subject_id: str):
        """Set the current subject"""
        self._subject_id = subject_id
        self._subject_display.setText(subject_id)
        
        # Use the existing calibration manager, just update subject
        if self._calibration_manager:
            self._calibration_manager.set_subject(subject_id)
            self._update_calibration_display()
    
    def set_calibration_manager(self, manager: CalibrationManager):
        """Set the calibration manager (shared from main window)"""
        self._calibration_manager = manager
        if self._subject_id:
            self._calibration_manager.set_subject(self._subject_id)
        self._update_calibration_display()
    
    def set_display_refresh_rate(self, rate_ms: int):
        """Set display refresh rate (from Configuration tab)"""
        self._display_refresh_ms = rate_ms
        # If timer is running, restart with new rate
        if self._update_timer.isActive():
            self._update_timer.stop()
            self._update_timer.start(self._display_refresh_ms)
    
    def set_aux_channels(self, channels: List[str]):
        """Set available auxiliary channels (from Configuration tab selection)"""
        self._aux_channels = channels
        self._channel_combo.clear()
        if channels:
            for ch in channels:
                self._channel_combo.addItem(ch)
            self._channel_combo.setEnabled(True)
        else:
            self._channel_combo.addItem("No channels selected")
            self._channel_combo.setEnabled(False)
    
    def _update_channels(self):
        """Update channel list from client"""
        if self._client and self._client.is_connected:
            try:
                # Use get_active_channels() - the correct method
                channels = self._client.get_active_channels()
                aux_channels = channels.get('aux', [])
                self.set_aux_channels(aux_channels)
            except Exception as e:
                print(f"Error getting channels: {e}")
                self.set_aux_channels([])
    
    def _on_channel_changed(self, channel: str):
        """Handle channel selection change"""
        self._current_channel = channel
        self._update_calibration_display()
        
        # Update plot
        self._force_plot.clear()
        self._force_plot.set_channel_names([channel])
    
    def _update_calibration_display(self):
        """Update display with current calibration values"""
        if not self._calibration_manager or not self._current_channel:
            return
        
        offset = self._calibration_manager.get_offset(self._current_channel)
        mvc = self._calibration_manager.get_mvc(self._current_channel)
        
        if offset is not None:
            self._offset_display.setText(f"{offset:.3f} V")
        else:
            self._offset_display.setText("---------------------------------------- (not calibrated)")
        
        if mvc is not None:
            self._mvc_display.setText(f"{mvc:.3f} V")
        else:
            self._mvc_display.setText("---------------------------------------- (not calibrated)")
        
        self._update_history_table()
    
    def _update_history_table(self):
        """Update the calibration history table"""
        if not self._calibration_manager:
            return
        
        mvcs = self._calibration_manager.get_all_mvcs()
        offsets = self._calibration_manager.get_all_offsets()
        
        self._history_table.setRowCount(0)
        
        # Add offset entries
        for ch, val in offsets.items():
            row = self._history_table.rowCount()
            self._history_table.insertRow(row)
            self._history_table.setItem(row, 0, QTableWidgetItem(ch))
            self._history_table.setItem(row, 1, QTableWidgetItem("Offset"))
            self._history_table.setItem(row, 2, QTableWidgetItem(f"{val:.4f}"))
            self._history_table.setItem(row, 3, QTableWidgetItem(datetime.now().strftime("%H:%M")))
            self._history_table.setItem(row, 4, QTableWidgetItem("Rest baseline"))
        
        # Add MVC entries
        for ch, val in mvcs.items():
            row = self._history_table.rowCount()
            self._history_table.insertRow(row)
            self._history_table.setItem(row, 0, QTableWidgetItem(ch))
            self._history_table.setItem(row, 1, QTableWidgetItem("MVC"))
            self._history_table.setItem(row, 2, QTableWidgetItem(f"{val:.4f}"))
            self._history_table.setItem(row, 3, QTableWidgetItem(datetime.now().strftime("%H:%M")))
            self._history_table.setItem(row, 4, QTableWidgetItem("Max contraction"))
    
    def _start_offset_recording(self):
        """Start offset recording procedure for single channel"""
        if not self._current_channel:
            QMessageBox.warning(self, "No Channel", 
                              "Please select a channel first")
            return
        
        if not self._subject_id:
            QMessageBox.warning(self, "No Subject",
                              "Please set a subject ID first")
            return
        
        self._start_data_collection(
            duration_s=self._offset_duration.value(),
            procedure_type="offset"
        )
    
    def _start_offset_all_recording(self):
        """Start offset recording for ALL auxiliary channels simultaneously"""
        if not self._subject_id:
            QMessageBox.warning(self, "No Subject",
                              "Please set a subject ID first")
            return
        
        if not self._aux_channels:
            QMessageBox.warning(self, "No Channels",
                              "No auxiliary channels available. Please configure channels first.")
            return
        
        # Confirm with user
        reply = QMessageBox.question(
            self, 
            "Record All Offsets",
            f"This will record offsets for ALL {len(self._aux_channels)} auxiliary channels:\n"
            f"{', '.join(self._aux_channels)}\n\n"
            f"Make sure ALL fingers/hand are completely relaxed.\n"
            f"Duration: {self._offset_duration.value()} seconds\n\n"
            f"Continue?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        self._start_data_collection(
            duration_s=self._offset_duration.value(),
            procedure_type="offset_all"
        )
    
    def _start_mvc_recording(self):
        """Start MVC recording procedure"""
        if not self._current_channel:
            QMessageBox.warning(self, "No Channel",
                              "Please select a channel first")
            return
        
        if not self._subject_id:
            QMessageBox.warning(self, "No Subject",
                              "Please set a subject ID first")
            return
        
        self._start_data_collection(
            duration_s=self._mvc_duration.value(),
            procedure_type="mvc"
        )
    
    def _start_data_collection(self, duration_s: float, procedure_type: str):
        """Start collecting data for calibration"""
        self._collecting_data = True
        self._collection_type = procedure_type
        self._collection_start_time = datetime.now().timestamp()
        self._collection_duration = duration_s
        
        # Find channel index/indices FIRST
        if self._client and self._client.is_connected:
            active = self._client.get_active_channels()
            aux_channels = active.get('aux', [])
            
            if procedure_type == "offset_all":
                # Check all channels are active
                missing = set(self._aux_channels) - set(aux_channels)
                if missing:
                    QMessageBox.warning(
                        self, "Channels Not Active",
                        f"These channels are not configured: {', '.join(missing)}\n"
                        f"Please configure them in the Configuration tab first."
                    )
                    self._collecting_data = False
                    return
                # Initialize buffer with ACTUAL active channels (not self._aux_channels)
                self._data_buffer = {ch: [] for ch in aux_channels}
                print(f"Calibration: Recording offsets for {len(aux_channels)} channels: {aux_channels}")
            else:
                # Single channel mode
                if self._current_channel not in aux_channels:
                    QMessageBox.warning(
                        self, "Channel Not Active",
                        f"Channel {self._current_channel} is not currently configured.\n"
                        f"Please configure and enable this channel in the Configuration tab first."
                    )
                    self._collecting_data = False
                    return
                
                self._channel_index = aux_channels.index(self._current_channel)
                self._data_buffer = []
                print(f"Calibration: Monitoring channel {self._current_channel} at index {self._channel_index}")
        else:
            QMessageBox.warning(self, "Not Connected", "Device not connected")
            self._collecting_data = False
            return
        
        # Clear display buffer
        self._sample_buffer.clear()
        self._latest_force = 0.0
        self._force_plot.clear()
        
        # Disable buttons
        self._offset_btn.setEnabled(False)
        self._offset_all_btn.setEnabled(False)
        self._mvc_btn.setEnabled(False)
        
        # CRITICAL FIX: Use stream consumer registration instead of replacing callback
        if not self._config_tab:
            QMessageBox.warning(
                self, "Configuration Error",
                "Config tab reference not set. Cannot start calibration."
            )
            self._collecting_data = False
            self._offset_btn.setEnabled(True)
            self._offset_all_btn.setEnabled(True)
            self._mvc_btn.setEnabled(True)
            return
        
        # Register as a stream consumer
        self._config_tab.register_stream_consumer(self._on_calibration_data)
        print(f"Registered calibration stream consumer")
        
        # If streaming isn't active, start it
        if self._client and not self._client.is_streaming:
            print("Starting streaming for calibration...")
            # Use the config_tab's callback system
            self._client.start_streaming(self._config_tab._on_stream_data)
        
        # Start progress indicator
        if procedure_type == "offset_all":
            instruction = f"RELAX ALL - Keep entire hand relaxed ({len(self._aux_channels)} channels)"
        elif procedure_type == "offset":
            instruction = "RELAX - Keep finger relaxed"
        else:
            instruction = "PUSH MAX - Apply maximum force!"
        
        self._progress.start_countdown(
            duration_ms=int(duration_s * 1000),
            instruction=instruction
        )
        
        # Start display update timer
        self._update_timer.start(self._display_refresh_ms)
    
    def _on_calibration_data(self, data):
        """
        Handle incoming data during calibration FROM BACKGROUND THREAD.
        Just buffers data - does NOT touch GUI!
        """
        if not self._collecting_data:
            return
        
        if data.aux_samples.size == 0:
            return
        
        if self._collection_type == "offset_all":
            # Collect from ALL channels
            active = self._client.get_active_channels() if self._client else {'aux': []}
            aux_channels = active.get('aux', [])
            
            for idx, ch_name in enumerate(aux_channels):
                if idx < data.aux_samples.shape[0] and ch_name in self._data_buffer:
                    samples = data.aux_samples[idx, :].copy()
                    self._data_buffer[ch_name].extend(samples.tolist())
                    
                    # For display, show the current channel if selected
                    if ch_name == self._current_channel:
                        self._sample_buffer.append(samples)
                        if len(samples) > 0:
                            self._latest_force = float(samples[-1])
        else:
            # Single channel mode
            if data.aux_samples.shape[0] > self._channel_index:
                samples = data.aux_samples[self._channel_index, :].copy()
                
                # Add RAW samples to data buffer for final calculation (no offset applied)
                self._data_buffer.extend(samples.tolist())
                
                # For display: apply offset if collecting MVC and offset exists
                display_samples = samples.copy()
                offset_applied = False
                if self._collection_type == "mvc" and self._calibration_manager:
                    offset_value = self._calibration_manager.get_offset(self._current_channel)
                    if offset_value is not None:
                        display_samples = display_samples - offset_value
                        offset_applied = True
                
                # Debug: print once when MVC starts
                if self._collection_type == "mvc" and len(self._data_buffer) < 100:
                    print(f"[Calibration] MVC collection: raw sample={samples[0]:.3f}, display sample={display_samples[0]:.3f}, offset_applied={offset_applied}")
                
                # Add to display buffer (thread-safe deque.append)
                self._sample_buffer.append(display_samples)
                
                # Update latest force value
                if len(display_samples) > 0:
                    self._latest_force = float(display_samples[-1])
    
    def _update_display(self):
        """
        TIMER CALLBACK - Updates GUI at fixed interval.
        Called every _display_refresh_ms milliseconds.
        """
        # Drain the sample buffer and add all to plot
        samples_to_add = []
        while True:
            try:
                samples = self._sample_buffer.popleft()
                samples_to_add.append(samples)
            except IndexError:
                break  # Buffer empty
        
        # Concatenate and add to plot in one batch
        if samples_to_add:
            combined = np.concatenate(samples_to_add)
            plot_data = combined.reshape(1, -1)
            self._force_plot.add_samples(plot_data)
        
        # Update force display
        self._force_display.setText(f"{self._latest_force:.3f}")
        
        # Trigger repaint
        self._force_plot.update()
    
    
    def _on_collection_complete(self):
        """Handle completion of data collection"""
        self._collecting_data = False
        self._update_timer.stop()
        self._sample_buffer.clear()
        
        # Unregister as stream consumer
        if self._config_tab:
            self._config_tab.unregister_stream_consumer(self._on_calibration_data)
            print("Unregistered calibration stream consumer")
        
        # Re-enable buttons
        self._offset_btn.setEnabled(True)
        self._offset_all_btn.setEnabled(True)
        self._mvc_btn.setEnabled(True)
        
        # Get sample rate
        sample_rate = 2000
        if self._client and hasattr(self._client, 'sample_rate'):
            sr = self._client.sample_rate
            if hasattr(sr, 'frequency'):
                sample_rate = sr.frequency
            elif hasattr(sr, 'value'):
                sample_rate = sr.value
            elif isinstance(sr, (int, float)):
                sample_rate = int(sr)
        
        # Handle different collection types
        if self._collection_type == "offset_all":
            # Process all channels simultaneously
            if not isinstance(self._data_buffer, dict):
                QMessageBox.warning(self, "Error", "Invalid data buffer")
                return
            
            success_count = 0
            failed_channels = []
            
            for ch_name, samples_list in self._data_buffer.items():
                if len(samples_list) == 0:
                    failed_channels.append(ch_name)
                    continue
                
                samples = np.array(samples_list)
                duration = len(samples) / sample_rate
                
                # Use center 1s to avoid artifacts
                if duration >= 3.0:
                    center_count = int(sample_rate * 1.0)
                    start_idx = (len(samples) - center_count) // 2
                    end_idx = start_idx + center_count
                    samples_for_offset = samples[start_idx:end_idx]
                else:
                    samples_for_offset = samples
                
                record = self._calibration_manager.compute_offset(
                    samples_for_offset, ch_name, 1.0
                )
                self._calibration_manager.save_offset(record)
                success_count += 1
                print(f"Saved offset for {ch_name}: {record.offset_value:.4f}")
            
            if failed_channels:
                QMessageBox.warning(
                    self, "Partial Success",
                    f"Saved {success_count} offsets.\nFailed: {', '.join(failed_channels)}"
                )
            else:
                QMessageBox.information(
                    self, "Success", 
                    f"\u2714 Saved offsets for all {success_count} channels!"
                )
            
            self._progress.set_instruction(f"\u2714 {success_count} Offsets Saved!")
            
        elif self._collection_type == "offset":
            # Single channel offset
            if not isinstance(self._data_buffer, list) or len(self._data_buffer) == 0:
                QMessageBox.warning(self, "No Data", "No data collected")
                return
            
            samples = np.array(self._data_buffer)
            duration = len(samples) / sample_rate
            
            if duration >= 3.0:
                center_count = int(sample_rate * 1.0)
                start_idx = (len(samples) - center_count) // 2
                end_idx = start_idx + center_count
                samples_for_offset = samples[start_idx:end_idx]
            else:
                samples_for_offset = samples
            
            record = self._calibration_manager.compute_offset(
                samples_for_offset, self._current_channel, 1.0
            )
            self._calibration_manager.save_offset(record)
            
            self._progress.set_value_display(f"Offset: {record.offset_value:.4f}")
            self._progress.set_instruction("\u2714 Offset Saved!")
            print(f"Saved offset for {self._current_channel}: {record.offset_value:.4f}")
            
        else:  # MVC
            if not isinstance(self._data_buffer, list) or len(self._data_buffer) == 0:
                QMessageBox.warning(self, "No Data", "No data collected")
                return
            
            samples = np.array(self._data_buffer)
            duration = len(samples) / sample_rate
            
            offset = self._calibration_manager.get_offset(self._current_channel) or 0.0
            record = self._calibration_manager.compute_mvc(
                samples, self._current_channel, duration, offset
            )
            self._calibration_manager.save_mvc(record)
            
            self._progress.set_value_display(f"MVC: {record.mvc_value:.4f}")
            self._progress.set_instruction("\u2714 MVC Saved!")
            print(f"Saved MVC for {self._current_channel}: {record.mvc_value:.4f}")
        
        # Update displays
        self._update_calibration_display()
        self._update_history_table()
        self.calibrationUpdated.emit()
    
    def _export_calibration(self):
        """Export calibration data"""
        QMessageBox.information(self, "Export", "Export functionality not yet implemented")
    
    def _clear_calibration(self):
        """Clear calibration data for current subject"""
        if not self._subject_id:
            QMessageBox.warning(self, "No Subject", "No subject selected")
            return
        
        reply = QMessageBox.question(
            self, "Clear Calibration",
            f"Clear all calibration data for {self._subject_id}?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            if self._calibration_manager:
                # Clear in memory
                self._calibration_manager._mvc_data.clear()
                self._calibration_manager._offset_data.clear()
                self._update_table()
                self._update_channel_display()
                self.calibrationUpdated.emit()
                QMessageBox.information(self, "Cleared", "Calibration data cleared")