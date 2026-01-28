"""
Custom widgets for the Novecento application.

IMPORTANT: These widgets use BUFFER-BASED updates.
- Data callbacks store values in buffers
- External timer calls update() at fixed refresh rate
- Widgets do NOT call update() themselves from add_samples()
"""

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QFrame,
    QSizePolicy,
    QGridLayout,
)
from PySide6.QtCore import Qt, Signal, QTimer, QPoint, QRect
from PySide6.QtGui import QPainter, QPen, QColor, QBrush, QFont, QPolygon
import numpy as np
from typing import List, Dict, Optional, Tuple
from collections import deque


class LivePlotWidget(QWidget):
    """
    Real-time plotting widget for EMG/force signals.

    USAGE:
    - Call add_samples() when data arrives (stores to buffer, NO repaint)
    - Call update() from external timer at your desired refresh rate
    """

    def __init__(
        self,
        n_channels: int = 1,
        buffer_seconds: float = 5.0,
        sample_rate: int = 2000,
        parent=None,
    ):
        super().__init__(parent)

        self.n_channels = n_channels
        self.buffer_size = int(buffer_seconds * sample_rate)
        self.sample_rate = sample_rate

        # Data buffers (circular)
        self._buffers: List[deque] = [
            deque(maxlen=self.buffer_size) for _ in range(n_channels)
        ]

        # LATEST VALUE for real-time display
        self._latest_values: List[float] = [0.0] * n_channels

        # Display settings
        self._channel_colors = [
            QColor("#4a9eff"),
            QColor("#48BB78"),
            QColor("#ff6b9d"),
            QColor("#F6AD55"),
            QColor("#a78bfa"),
            QColor("#fc8181"),
        ]

        self._y_range = (-1.0, 1.0)
        self._auto_scale = True
        self._grid_enabled = True
        self._channel_names: List[str] = [f"Ch {i+1}" for i in range(n_channels)]

        # Target line
        self._target_value: Optional[float] = None
        self._tolerance_band: Optional[float] = None
        self._y_label: str = ""

        # Colors
        self._bg_color = QColor("#0e1318")
        self._grid_color = QColor("#2d3139")
        self._text_color = QColor("#e8eaed")
        self._target_color = QColor("#48BB78")
        self._tolerance_color = QColor(72, 187, 120, 40)

        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(self.backgroundRole(), QColor("#0e1318"))
        self.setPalette(palette)

    def set_channel_count(self, n: int):
        self.n_channels = n
        self._buffers = [deque(maxlen=self.buffer_size) for _ in range(n)]
        self._channel_names = [f"Ch {i+1}" for i in range(n)]
        self._latest_values = [0.0] * n

    def set_channel_names(self, names: List[str]):
        self._channel_names = names[: self.n_channels]

    def set_y_range(self, y_min: float, y_max: float):
        self._y_range = (y_min, y_max)
        self._auto_scale = False

    def set_auto_scale(self, enabled: bool):
        self._auto_scale = enabled

    def set_y_label(self, label: str):
        self._y_label = label

    def set_target(self, target: Optional[float], tolerance: Optional[float] = None):
        self._target_value = target
        self._tolerance_band = tolerance

    def add_samples(self, samples: np.ndarray):
        """
        Add samples to buffer.
        DOES NOT TRIGGER REPAINT - call update() from external timer!
        """
        if samples.ndim == 1:
            samples = samples.reshape(1, -1)

        n_ch = min(samples.shape[0], self.n_channels)
        n_samp = samples.shape[1]

        for ch in range(n_ch):
            for s in range(n_samp):
                self._buffers[ch].append(samples[ch, s])
            # Store latest value
            if n_samp > 0:
                self._latest_values[ch] = float(samples[ch, -1])

    def get_latest_value(self, channel: int = 0) -> float:
        """Get the most recent value for a channel"""
        if 0 <= channel < len(self._latest_values):
            return self._latest_values[channel]
        return 0.0

    def clear(self):
        for buf in self._buffers:
            buf.clear()
        self._latest_values = [0.0] * self.n_channels
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        margin = 60
        plot_w = w - margin - 20
        plot_h = h - margin * 2

        painter.fillRect(self.rect(), self._bg_color)

        # Compute Y range with auto-scale
        if self._auto_scale:
            all_data = []
            for buf in self._buffers:
                if len(buf) > 0:
                    all_data.extend(buf)
            if all_data:
                data_min = min(all_data)
                data_max = max(all_data)
                data_range = data_max - data_min
                if data_range < 0.01:
                    data_range = 1.0
                margin_y = data_range * 0.15
                self._y_range = (data_min - margin_y, data_max + margin_y)

        y_min, y_max = self._y_range
        y_range = y_max - y_min
        if y_range == 0:
            y_range = 1

        # Grid
        if self._grid_enabled:
            painter.setPen(QPen(self._grid_color, 1, Qt.DotLine))
            for i in range(5):
                y = margin + (plot_h * i) // 4
                painter.drawLine(margin, y, w - 20, y)
            for i in range(5):
                x = margin + (plot_w * i) // 4
                painter.drawLine(x, margin, x, h - margin)

        # Target line and tolerance
        if self._target_value is not None:
            target_y = margin + plot_h * (1 - (self._target_value - y_min) / y_range)

            if self._tolerance_band is not None:
                band_top = margin + plot_h * (
                    1 - (self._target_value + self._tolerance_band - y_min) / y_range
                )
                band_bottom = margin + plot_h * (
                    1 - (self._target_value - self._tolerance_band - y_min) / y_range
                )
                painter.fillRect(
                    margin,
                    int(band_top),
                    plot_w,
                    int(band_bottom - band_top),
                    self._tolerance_color,
                )

            painter.setPen(QPen(self._target_color, 2, Qt.DashLine))
            painter.drawLine(margin, int(target_y), w - 20, int(target_y))

        # Draw data
        for ch_idx, buf in enumerate(self._buffers):
            if len(buf) == 0:
                continue

            color = self._channel_colors[ch_idx % len(self._channel_colors)]
            painter.setPen(QPen(color, 2))

            data = list(buf)
            n_points = len(data)
            if n_points < 2:
                continue

            step = max(1, self.buffer_size // plot_w)
            prev_x, prev_y = None, None
            start_x_offset = self.buffer_size - n_points

            for i in range(0, n_points, step):
                x = margin + ((start_x_offset + i) * plot_w) // self.buffer_size
                val = data[i]
                y = margin + plot_h * (1 - (val - y_min) / y_range)
                y = max(margin, min(h - margin, y))

                if prev_x is not None:
                    painter.drawLine(int(prev_x), int(prev_y), int(x), int(y))
                prev_x, prev_y = x, y

        # Labels
        painter.setPen(self._text_color)
        font = QFont("Segoe UI", 10)
        painter.setFont(font)

        for i in range(5):
            y = margin + (plot_h * i) // 4
            val = y_max - (y_range * i) / 4
            painter.drawText(5, y + 5, f"{val:.1f}")

        if self._y_label:
            painter.save()
            painter.translate(15, h // 2)
            painter.rotate(-90)
            painter.drawText(-30, 0, self._y_label)
            painter.restore()


class TrapezoidForceWidget(QWidget):
    """
    Trapezoid force tracking widget.

    THE CURSOR SHOWS YOUR ACTUAL FORCE (set via set_current_force)

    USAGE:
    - Call set_current_force() when data arrives (stores value, NO repaint)
    - Call set_current_time() when data arrives (stores value, NO repaint)
    - Call add_force_sample() to add to trail (stores value, NO repaint)
    - Call update() from external timer at your desired refresh rate
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        # Trapezoid parameters
        self._rest_before = 2.0
        self._ramp_up = 3.0
        self._plateau = 5.0
        self._ramp_down = 3.0
        self._rest_after = 2.0
        self._target_percent = 15.0
        self._tolerance = 5.0

        # State
        self._total_duration = self._calculate_total_duration()
        self._current_time = 0.0
        self._is_running = False

        # YOUR CURRENT FORCE - updated by set_current_force()
        self._current_force = 0.0

        # Force trail - now support multiple channels
        self._force_data: Dict[str, List[Tuple[float, float]]] = (
            {}
        )  # channel_name -> [(time, value), ...]
        self._max_points = 10000

        # Cached interpolated curves for smooth rendering
        self._cached_curves: Dict[str, List[Tuple[float, float]]] = {}
        self._cache_dirty: Dict[str, bool] = {}

        # Visual smoothing filter (applied to cached curves only, not raw data)
        self._visual_smoothing_enabled = True
        self._visual_smoothing_cutoff = 5.0  # Hz - adjust for more/less smoothing

        # Channel colors for multi-channel display
        self._channel_colors = [
            QColor("#4a9eff"),  # Blue
            QColor("#48BB78"),  # Green
            QColor("#ff6b9d"),  # Pink
            QColor("#F6AD55"),  # Orange
            QColor("#a78bfa"),  # Purple
            QColor("#fc8181"),  # Light red
        ]
        self._assigned_colors: Dict[str, QColor] = {}

        # Finger labels for channels
        self._channel_finger_labels: Dict[str, str] = {}

        # Current force values for all channels
        self._current_channel_forces: Dict[str, float] = {}

        # Countdown overlay
        self._countdown_active = False
        self._countdown_number = 3

        # Display
        self._y_min = -5.0
        self._y_max = 25.0

        # Colors
        self._bg_color = QColor("#0e1318")
        self._grid_color = QColor("#2d3139")
        self._text_color = QColor("#e8eaed")
        self._target_color = QColor("#606060")  # Dark grey for trapezoid line
        self._tolerance_color = QColor(
            120, 120, 120, 50
        )  # Light grey with transparency
        self._force_trail_color = QColor("#4a9eff")  # Default/primary channel
        self._cursor_color = QColor("#ff3333")  # RED = out of target
        self._cursor_in_target_color = QColor("#00ff00")  # GREEN = in target

        self.setMinimumHeight(300)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(self.backgroundRole(), self._bg_color)
        self.setPalette(palette)

    def _calculate_total_duration(self) -> float:
        return (
            self._rest_before
            + self._ramp_up
            + self._plateau
            + self._ramp_down
            + self._rest_after
        )

    def set_trapezoid_params(
        self,
        rest_before: float,
        ramp_up: float,
        plateau: float,
        ramp_down: float,
        rest_after: float,
        target_percent: float,
        tolerance: float,
    ):
        self._rest_before = rest_before
        self._ramp_up = ramp_up
        self._plateau = plateau
        self._ramp_down = ramp_down
        self._rest_after = rest_after
        self._target_percent = target_percent
        self._tolerance = tolerance
        self._total_duration = self._calculate_total_duration()
        self._y_min = -5.0
        self._y_max = max(25.0, target_percent + tolerance + 10.0)

    def set_running(self, running: bool):
        self._is_running = running
        if not running:
            self._current_time = 0.0

    def set_current_time(self, time_sec: float):
        """Set current time (X position). NO REPAINT - call update() separately!"""
        self._current_time = time_sec

    def set_current_force(self, force_percent: float):
        """Set YOUR current force (Y position). NO REPAINT - call update() separately!"""
        self._current_force = force_percent

    def get_current_force(self) -> float:
        """Get the current force value"""
        return self._current_force

    def add_force_sample(self, time_sec: float, force_percent: float):
        """Add a force sample to the default trail (backward compatibility). NO REPAINT - call update() separately!"""
        if "default" not in self._force_data:
            self._force_data["default"] = []
        self._force_data["default"].append((time_sec, force_percent))
        if len(self._force_data["default"]) > self._max_points:
            self._force_data["default"] = self._force_data["default"][
                -self._max_points :
            ]

    def add_force_sample_for_channel(
        self, channel_name: str, time_sec: float, force_percent: float
    ):
        """Add a force sample for a specific channel. NO REPAINT - call update() separately!"""
        if channel_name not in self._force_data:
            self._force_data[channel_name] = []
            # Assign a color if not already assigned
            if channel_name not in self._assigned_colors:
                color_idx = len(self._assigned_colors) % len(self._channel_colors)
                self._assigned_colors[channel_name] = self._channel_colors[color_idx]

        self._force_data[channel_name].append((time_sec, force_percent))
        if len(self._force_data[channel_name]) > self._max_points:
            self._force_data[channel_name] = self._force_data[channel_name][
                -self._max_points :
            ]

        # Mark cache as dirty for this channel
        self._cache_dirty[channel_name] = True

    def clear_force_data(self):
        """Clear all force data"""
        self._force_data.clear()
        self._cached_curves.clear()
        self._cache_dirty.clear()
        self._current_time = 0.0
        self._current_force = 0.0

    def clear_trail(self):
        """Alias for clear_force_data - clears the force trail"""
        self.clear_force_data()

    def set_channel_finger_labels(self, labels: Dict[str, str]):
        """Set finger labels for channels"""
        self._channel_finger_labels = labels.copy()

    def set_countdown_active(self, active: bool):
        """Show/hide countdown overlay"""
        self._countdown_active = active

    def set_countdown_number(self, num: int):
        """Set countdown number to display"""
        self._countdown_number = num

    def set_current_channel_forces(self, channel_forces: Dict[str, float]):
        """Set current force values for all channels. NO REPAINT - call update() separately!"""
        self._current_channel_forces = channel_forces.copy()

    def set_protocol(
        self,
        total_duration: float,
        target_mvc: float,
        tolerance: float,
        ramp_up: float,
        hold: float,
        ramp_down: float,
    ):
        """
        Configure the trapezoid protocol parameters.
        """
        self._rest_before = 0.0
        self._ramp_up = ramp_up
        self._plateau = hold
        self._ramp_down = ramp_down
        self._rest_after = 0.0
        self._target_percent = target_mvc
        self._tolerance = tolerance
        self._total_duration = total_duration

        self._y_min = -5.0
        self._y_max = max(25.0, target_mvc + tolerance + 15.0)

    def _get_target_at_time(self, t: float) -> float:
        """Get the target %MVC at a given time"""
        if t < self._rest_before:
            return 0.0
        t1 = self._rest_before
        t2 = t1 + self._ramp_up
        t3 = t2 + self._plateau
        t4 = t3 + self._ramp_down

        if t < t2:
            return self._target_percent * (t - t1) / self._ramp_up
        elif t < t3:
            return self._target_percent
        elif t < t4:
            return self._target_percent * (1 - (t - t3) / self._ramp_down)
        else:
            return 0.0

    def _is_in_ramp_phase(self, t: float) -> bool:
        """Check if time is in a ramp phase (up or down)"""
        t1 = self._rest_before
        t2 = t1 + self._ramp_up
        t3 = t2 + self._plateau
        t4 = t3 + self._ramp_down

        return (t1 <= t < t2) or (t3 <= t < t4)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        margin_left = 70
        margin_right = 20
        margin_top = 20
        margin_bottom = 50

        plot_w = w - margin_left - margin_right
        plot_h = h - margin_top - margin_bottom

        if plot_w <= 0 or plot_h <= 0:
            return

        painter.fillRect(self.rect(), self._bg_color)

        y_range = self._y_max - self._y_min

        # 5-second sliding window centered on current time
        window_duration = 5.0
        padding = window_duration / 2  # 2.5s padding at start/end

        # Window is always centered on current time, with padding extending beyond protocol bounds
        window_center = self._current_time
        window_start = window_center - window_duration / 2
        window_end = window_center + window_duration / 2

        def time_to_x(t: float) -> int:
            # Map time within the visible window to screen coordinates
            # This works even when window extends beyond [0, total_duration]
            return int(margin_left + ((t - window_start) / window_duration) * plot_w)

        def value_to_y(v: float) -> int:
            return int(margin_top + plot_h * (1 - (v - self._y_min) / y_range))

        # Grid - only draw for valid protocol time range
        painter.setPen(QPen(self._grid_color, 1, Qt.DotLine))

        # Horizontal grid lines (Y-axis)
        for y_val in range(int(self._y_min), int(self._y_max) + 1, 5):
            if self._y_min <= y_val <= self._y_max:
                y = value_to_y(y_val)
                painter.drawLine(margin_left, y, w - margin_right, y)

        # Vertical grid lines (X-axis) - only for times within [0, total_duration]
        start_sec = max(0, int(window_start))
        end_sec = min(int(self._total_duration), int(window_end)) + 1
        for t in range(start_sec, end_sec + 1):
            if 0 <= t <= self._total_duration and window_start <= t <= window_end:
                x = time_to_x(t)
                if margin_left <= x <= w - margin_right:
                    painter.drawLine(x, margin_top, x, h - margin_bottom)

        # Tolerance band - only draw within protocol bounds [0, total_duration]
        # Sample more densely for smooth rendering in the zoomed window
        n_pts = 1000
        upper, lower = [], []

        half_tol = self._tolerance / 2.0

        # Calculate time boundaries
        t1 = self._rest_before
        t2 = t1 + self._ramp_up
        t3 = t2 + self._plateau
        t4 = t3 + self._ramp_down

        # Only sample within the intersection of window and protocol bounds
        sample_start = max(0, window_start)
        sample_end = min(self._total_duration, window_end)

        if sample_end > sample_start:
            for i in range(n_pts + 1):
                t = sample_start + (i / n_pts) * (sample_end - sample_start)

                target = self._get_target_at_time(t)
                x = time_to_x(t)

                # For simplicity, use vertical tolerance bands (perpendicular offset complicates the window view)
                upper.append((x, value_to_y(target + half_tol)))
                lower.append((x, value_to_y(target - half_tol)))

            # Create polygon from upper and lower bounds
            if upper and lower:
                polygon_points = [QPoint(int(x), int(y)) for x, y in upper] + [
                    QPoint(int(x), int(y)) for x, y in reversed(lower)
                ]
                painter.setBrush(QBrush(self._tolerance_color))
                painter.setPen(Qt.NoPen)
                painter.drawPolygon(QPolygon(polygon_points))

        # Target line (trapezoid) - only draw within protocol bounds
        painter.setPen(QPen(self._target_color, 3))
        last_x, last_y = None, None

        sample_start = max(0, window_start)
        sample_end = min(self._total_duration, window_end)

        if sample_end > sample_start:
            for i in range(n_pts + 1):
                t = sample_start + (i / n_pts) * (sample_end - sample_start)

                target = self._get_target_at_time(t)
                x = time_to_x(t)
                y = value_to_y(target)

                if last_x is not None:
                    painter.drawLine(last_x, last_y, x, y)
                last_x, last_y = x, y

        # Force trails - render at pixel resolution by interpolating between data points
        if self._force_data:
            for channel_name, data in self._force_data.items():
                if len(data) < 2:
                    continue

                # Get color for this channel
                if channel_name == "default":
                    color = self._force_trail_color
                else:
                    color = self._assigned_colors.get(
                        channel_name, self._force_trail_color
                    )

                # Check if we need to rebuild the interpolated curve
                rebuild_cache = (
                    channel_name not in self._cached_curves
                    or self._cache_dirty.get(channel_name, True)
                )

                if rebuild_cache:
                    # Filter data to protocol bounds (cache all data, window will clip later)
                    protocol_data = [
                        (t, v) for t, v in data if 0 <= t <= self._total_duration
                    ]

                    if len(protocol_data) >= 2:
                        # Convert to arrays for vectorized interpolation
                        times = np.array([t for t, v in protocol_data])
                        values = np.array([v for t, v in protocol_data])

                        # Interpolate at high temporal resolution (every 10ms = 100 samples/sec)
                        # This is denser than display needs but smooth and cached
                        t_start, t_end = times[0], times[-1]
                        sample_rate = 100  # Hz
                        n_samples = max(50, int((t_end - t_start) * sample_rate))
                        dense_times = np.linspace(t_start, t_end, n_samples)
                        dense_values = np.interp(dense_times, times, values)

                        # Apply visual smoothing filter if enabled
                        if self._visual_smoothing_enabled and len(dense_values) > 10:
                            from scipy import signal as scipy_signal

                            # Design 5Hz low-pass Butterworth filter
                            nyquist = sample_rate / 2.0
                            cutoff_norm = self._visual_smoothing_cutoff / nyquist
                            # Use lower order (2nd) for gentler smoothing
                            b, a = scipy_signal.butter(2, cutoff_norm, btype="low")
                            # Apply forward-backward filter for zero phase delay
                            dense_values = scipy_signal.filtfilt(b, a, dense_values)

                        # Cache the interpolated curve
                        self._cached_curves[channel_name] = list(
                            zip(dense_times, dense_values)
                        )
                        self._cache_dirty[channel_name] = False

                # Get the cached curve
                if channel_name not in self._cached_curves:
                    continue

                curve_data = self._cached_curves[channel_name]

                # Add current position if running (not cached, real-time)
                render_data = curve_data.copy()
                if self._is_running and self._current_time <= self._total_duration:
                    if (
                        channel_name == "default"
                        or channel_name in self._current_channel_forces
                    ):
                        current_force = (
                            self._current_channel_forces.get(
                                channel_name, self._current_force
                            )
                            if channel_name in self._current_channel_forces
                            else self._current_force
                        )
                        render_data.append((self._current_time, current_force))

                # Filter to visible window only
                visible_data = [
                    (t, v)
                    for t, v in render_data
                    if window_start - 0.1 <= t <= window_end + 0.1
                ]

                if len(visible_data) < 2:
                    continue

                # Render the curve
                painter.setPen(QPen(color, 5))
                last_x, last_y = None, None

                for t, v in visible_data:
                    x = time_to_x(t)
                    y = value_to_y(v)

                    if last_x is not None:
                        painter.drawLine(last_x, last_y, x, y)
                    last_x, last_y = x, y

        # Legend for multiple channels
        if len(self._force_data) > 1 and self._assigned_colors:
            legend_x = w - margin_right - 100
            legend_y = margin_top + 10
            painter.setFont(QFont("Segoe UI", 9))

            for channel_name, color in self._assigned_colors.items():
                # Draw color box
                painter.fillRect(legend_x, legend_y, 12, 12, color)
                painter.setPen(self._text_color)
                painter.drawText(legend_x + 16, legend_y + 10, channel_name)
                legend_y += 16

        # THE CURSOR - YOUR ACTUAL FORCE
        if self._is_running and 0 <= self._current_time <= self._total_duration:
            cursor_x = time_to_x(self._current_time)
            current_target = self._get_target_at_time(self._current_time)

            # Use constant half tolerance throughout (matching the band)
            half_tol = self._tolerance / 2.0

            # Vertical time line
            painter.setPen(QPen(QColor("#444444"), 1, Qt.DashLine))
            painter.drawLine(cursor_x, margin_top, cursor_x, h - margin_bottom)

            # Draw cursor for primary channel ONLY if not showing individual channel cursors
            # When showing individual channels, we don't need the main cursor
            if not self._current_channel_forces:
                cursor_y = value_to_y(self._current_force)
                in_target = abs(self._current_force - current_target) <= half_tol
                cursor_color = (
                    self._cursor_in_target_color if in_target else self._cursor_color
                )

                # THE CURSOR CIRCLE for primary (no horizontal line to match other channels)
                painter.setBrush(QBrush(cursor_color))
                painter.setPen(QPen(QColor("#ffffff"), 2))
                radius = 12
                painter.drawEllipse(
                    cursor_x - radius, cursor_y - radius, radius * 2, radius * 2
                )

                # Crosshair for primary
                painter.setPen(QPen(QColor("#000000"), 2))
                painter.drawLine(cursor_x - 6, cursor_y, cursor_x + 6, cursor_y)
                painter.drawLine(cursor_x, cursor_y - 6, cursor_x, cursor_y + 6)

                # Force value label for primary
                painter.setPen(cursor_color)
                font = QFont("Segoe UI", 12, QFont.Bold)
                painter.setFont(font)
                label = f"{self._current_force:.1f}%"
                label_x = cursor_x + 16
                if label_x + 50 > w - margin_right:
                    label_x = cursor_x - 60
                painter.drawText(label_x, cursor_y + 5, label)

            # Draw cursors for all individual channels with finger labels
            if self._current_channel_forces:
                for channel_name, force_value in self._current_channel_forces.items():
                    ch_cursor_y = value_to_y(force_value)
                    ch_in_target = abs(force_value - current_target) <= half_tol

                    # Get channel color
                    if channel_name in self._assigned_colors:
                        ch_color = self._assigned_colors[channel_name]
                    else:
                        ch_color = self._force_trail_color

                    # Use channel color when in target, red when out
                    ch_cursor_color = ch_color if ch_in_target else self._cursor_color

                    # Draw cursor circle for this channel
                    painter.setBrush(QBrush(ch_cursor_color))
                    painter.setPen(QPen(ch_color, 3))
                    ch_radius = 12
                    painter.drawEllipse(
                        cursor_x - ch_radius,
                        ch_cursor_y - ch_radius,
                        ch_radius * 2,
                        ch_radius * 2,
                    )

                    # Draw finger label inside the circle if available
                    if channel_name in self._channel_finger_labels:
                        finger_label = self._channel_finger_labels[channel_name]
                        if finger_label:
                            painter.setPen(QColor("#000000"))
                            label_font = QFont("Segoe UI", 10, QFont.Bold)
                            painter.setFont(label_font)
                            # Draw text centered in circle
                            painter.drawText(
                                cursor_x - 5, ch_cursor_y + 5, finger_label
                            )

            # Small marker on target line
            target_y = value_to_y(current_target)
            painter.setPen(QPen(self._target_color, 1))
            painter.setBrush(QBrush(self._target_color))
            painter.drawEllipse(cursor_x - 4, target_y - 4, 8, 8)

        # Axis labels
        painter.setPen(self._text_color)
        font = QFont("Segoe UI", 10)
        painter.setFont(font)

        # Y-axis labels (unchanged)
        for y_val in range(int(self._y_min), int(self._y_max) + 1, 5):
            if self._y_min <= y_val <= self._y_max:
                painter.drawText(5, value_to_y(y_val) + 5, f"{y_val}%")

        # X-axis labels - only show times within protocol bounds [0, total_duration]
        start_sec = max(0, int(window_start))
        end_sec = min(int(self._total_duration), int(window_end)) + 1
        for t in range(start_sec, end_sec + 1):
            if 0 <= t <= self._total_duration and window_start <= t <= window_end:
                x = time_to_x(t)
                if margin_left <= x <= w - margin_right:
                    painter.drawText(x - 8, h - margin_bottom + 18, f"{t}s")

        font = QFont("Segoe UI", 11, QFont.Bold)
        painter.setFont(font)
        painter.save()
        painter.translate(18, h // 2)
        painter.rotate(-90)
        painter.drawText(-25, 0, "%MVC")
        painter.restore()
        painter.drawText(w // 2 - 30, h - 8, "Time (s)")

        # COUNTDOWN OVERLAY - draws on top of everything
        if self._countdown_active:
            # Semi-transparent dark overlay
            overlay_color = QColor(0, 0, 0, 180)
            painter.fillRect(self.rect(), overlay_color)

            # Draw countdown number or "GO!"
            if self._countdown_number > 0:
                countdown_text = str(self._countdown_number)
                font_size = 180
                color = QColor("#F6AD55")  # Orange
            else:
                countdown_text = "GO!"
                font_size = 120
                color = QColor("#48BB78")  # Green

            painter.setPen(color)
            countdown_font = QFont("Segoe UI", font_size, QFont.Bold)
            painter.setFont(countdown_font)

            # Center the text
            text_rect = painter.fontMetrics().boundingRect(countdown_text)
            text_x = (w - text_rect.width()) // 2
            text_y = (h + text_rect.height()) // 2

            # Add glow effect
            painter.setPen(QPen(color, 4))
            painter.drawText(text_x, text_y, countdown_text)


class CalibrationProgress(QWidget):
    """Progress display for calibration procedures"""

    countdownFinished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)

        self._instruction = QLabel("Ready")
        self._instruction.setStyleSheet("color: white; font-size: 16px;")
        self._instruction.setAlignment(Qt.AlignCenter)

        self._progress = QProgressBar()
        self._progress.setStyleSheet(
            """
            QProgressBar {
                border: 2px solid #333;
                border-radius: 5px;
                text-align: center;
                background-color: #1a1a2e;
                color: white;
            }
            QProgressBar::chunk {
                background-color: #00cc00;
            }
        """
        )

        self._value_display = QLabel("")
        self._value_display.setStyleSheet("color: #00ff00; font-size: 24px;")
        self._value_display.setAlignment(Qt.AlignCenter)

        layout.addWidget(self._instruction)
        layout.addWidget(self._progress)
        layout.addWidget(self._value_display)

        self._timer = QTimer()
        self._timer.timeout.connect(self._tick)
        self._countdown_value = 0
        self._total_time = 0

    def start_countdown(self, duration_ms: int, instruction: str = "Recording..."):
        self._instruction.setText(instruction)
        self._total_time = duration_ms
        self._countdown_value = duration_ms
        self._progress.setRange(0, duration_ms)
        self._progress.setValue(0)
        self._timer.start(50)

    def _tick(self):
        self._countdown_value -= 50
        self._progress.setValue(self._total_time - self._countdown_value)
        if self._countdown_value <= 0:
            self._timer.stop()
            self.countdownFinished.emit()

    def stop(self):
        self._timer.stop()

    def set_value_display(self, text: str):
        self._value_display.setText(text)

    def set_instruction(self, text: str):
        self._instruction.setText(text)


class MultiChannelPlotWidget(QWidget):
    """Multi-channel stacked plot - same buffer pattern as LivePlotWidget"""

    def __init__(
        self,
        n_channels: int = 4,
        buffer_seconds: float = 5.0,
        sample_rate: int = 2000,
        parent=None,
    ):
        super().__init__(parent)

        self.n_channels = n_channels
        self.buffer_size = int(buffer_seconds * sample_rate)
        self.sample_rate = sample_rate
        self._buffer_seconds = buffer_seconds  # Track for zoom
        self._y_scale = 1.0  # Y-axis scale multiplier

        self._buffers: List[deque] = [
            deque(maxlen=self.buffer_size) for _ in range(n_channels)
        ]
        self._channel_names: List[str] = [f"Ch {i+1}" for i in range(n_channels)]
        self._channel_colors = [
            QColor("#4a9eff"),
            QColor("#48BB78"),
            QColor("#ff6b9d"),
            QColor("#F6AD55"),
            QColor("#a78bfa"),
            QColor("#fc8181"),
        ]

        self._bg_color = QColor("#0e1318")
        self._grid_color = QColor("#2d3139")
        self._text_color = QColor("#e8eaed")

        self.setMinimumHeight(200)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(self.backgroundRole(), self._bg_color)
        self.setPalette(palette)

    def set_channel_count(self, n: int):
        self.n_channels = n
        self._buffers = [deque(maxlen=self.buffer_size) for _ in range(n)]

    def set_channel_names(self, names: List[str]):
        self._channel_names = names.copy()
        self.n_channels = len(names)
        self._buffers = [deque(maxlen=self.buffer_size) for _ in range(self.n_channels)]

    def set_time_window(self, seconds: float):
        """Set the time window to display (X-axis zoom)"""
        self._buffer_seconds = seconds
        new_buffer_size = int(seconds * self.sample_rate)
        # Recreate buffers with new size
        old_buffers = self._buffers
        self._buffers = [deque(maxlen=new_buffer_size) for _ in range(self.n_channels)]
        # Copy existing data to new buffers
        for i, old_buf in enumerate(old_buffers):
            for val in old_buf:
                self._buffers[i].append(val)
        self.buffer_size = new_buffer_size
        self.update()

    def set_y_scale(self, scale: float):
        """Set Y-axis scale multiplier (zoom in/out vertically)"""
        self._y_scale = scale
        self.update()

    def add_samples(self, samples: np.ndarray):
        """Add samples - NO REPAINT, call update() from timer"""
        if samples.ndim == 1:
            samples = samples.reshape(1, -1)
        for ch_idx in range(min(samples.shape[0], self.n_channels)):
            for val in samples[ch_idx]:
                self._buffers[ch_idx].append(val)

    def clear(self):
        for buf in self._buffers:
            buf.clear()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        margin_left, margin_right, margin_top, margin_bottom = 70, 15, 15, 25

        plot_w = w - margin_left - margin_right
        plot_h = h - margin_top - margin_bottom

        painter.fillRect(self.rect(), self._bg_color)

        if self.n_channels == 0:
            return

        # Draw time axis (X-axis) at bottom
        painter.setPen(self._text_color)
        painter.setFont(QFont("Segoe UI", 8))
        time_labels = [1, 2, 3, 4, 5]  # Time in seconds
        for t in time_labels:
            if t <= self._buffer_seconds:
                x_pos = margin_left + (plot_w * t) / self._buffer_seconds
                painter.drawText(int(x_pos) - 10, h - 5, f"{t}s")

        channel_spacing = 8
        channel_h = (plot_h - channel_spacing * (self.n_channels - 1)) / self.n_channels

        for ch_idx in range(self.n_channels):
            ch_top = margin_top + ch_idx * (channel_h + channel_spacing)
            ch_bottom = ch_top + channel_h
            ch_center = (ch_top + ch_bottom) / 2

            painter.fillRect(
                margin_left, int(ch_top), plot_w, int(channel_h), QColor("#161b20")
            )
            painter.setPen(QPen(self._grid_color, 1, Qt.DotLine))
            painter.drawLine(
                margin_left, int(ch_center), w - margin_right, int(ch_center)
            )

            color = self._channel_colors[ch_idx % len(self._channel_colors)]
            painter.setPen(color)
            painter.setFont(QFont("Segoe UI", 9))
            name = (
                self._channel_names[ch_idx]
                if ch_idx < len(self._channel_names)
                else f"Ch {ch_idx+1}"
            )
            painter.drawText(5, int(ch_center + 5), name[:8])

            buf = self._buffers[ch_idx]
            if len(buf) < 2:
                continue

            data = list(buf)
            
            # Use FIXED y-range, not dynamic
            # The _y_scale controls zoom level
            y_range = 2.0 / self._y_scale  # Fixed range of Â±1.0 by default, adjustable via _y_scale
            data_center = 0.0  # Center at zero

            painter.setPen(QPen(color, 0.8))
            step = max(1, self.buffer_size // plot_w)
            prev_x, prev_y = None, None
            start_offset = self.buffer_size - len(data)

            # Calculate standard deviation for this channel
            data_std = np.std(data) if len(data) > 1 else 0.0

            for i in range(0, len(data), step):
                x = margin_left + ((start_offset + i) * plot_w) // self.buffer_size
                val = data[i]
                # Center the data and apply scaling
                y = ch_top + channel_h * (1 - (val - data_center) / y_range - 0.5)
                y = max(ch_top, min(ch_bottom, y))

                if prev_x is not None:
                    painter.drawLine(int(prev_x), int(prev_y), int(x), int(y))
                prev_x, prev_y = x, y

            # Display SD on the RIGHT side of the plot
            painter.setPen(self._text_color)
            painter.setFont(QFont("Segoe UI", 8))
            sd_text = f"Ïƒ={data_std:.3f}"
            painter.drawText(w - margin_right - 70, int(ch_center + 5), sd_text)


class StatusIndicator(QFrame):
    """LED-like status indicator"""

    def __init__(self, label: str = "", parent=None):
        super().__init__(parent)
        self._status = False
        self._color_on = QColor("#48BB78")
        self._color_off = QColor("#333333")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 2, 5, 2)

        self._led = QWidget()
        self._led.setFixedSize(12, 12)
        self._led.setStyleSheet(
            f"background-color: {self._color_off.name()}; border-radius: 6px;"
        )

        self._label_widget = QLabel(label)
        self._label_widget.setStyleSheet("color: white;")

        layout.addWidget(self._led)
        layout.addWidget(self._label_widget)

    def set_status(self, on: bool):
        self._status = on
        color = self._color_on if on else self._color_off
        self._led.setStyleSheet(
            f"background-color: {color.name()}; border-radius: 6px;"
        )


class ForceBarWidget(QWidget):
    """Single force bar for legacy compatibility"""

    def __init__(self, finger_name: str = "", parent=None):
        super().__init__(parent)
        self.finger_name = finger_name
        self._up_value = 0.0
        self._down_value = 0.0
        self.setMinimumSize(60, 150)

    def set_values(self, up: float, down: float):
        self._up_value = up
        self._down_value = down

    def set_targets(self, up: float, down: float):
        pass

    def set_tolerance(self, t: float):
        pass

    def set_in_target(self, up: bool, down: bool):
        pass

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#0e1318"))


class BarTaskDisplay(QWidget):
    """Legacy bar task display - minimal stub"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bars = {}
        self._layout = QHBoxLayout(self)

    def setup_bars(self, fingers):
        pass

    def update_values(self, v):
        pass

    def update_targets(self, t):
        pass

    def update_in_target(self, s):
        pass

    def set_tolerance(self, t):
        pass

    def show_success(self):
        pass

    def show_failure(self):
        pass


class BarTaskDisplayNew(QWidget):
    """
    Multi-finger force bar display for piano task.
    Shows ONE bar per finger that displays net force:
    - Positive (up) = extension
    - Negative (down) = flexion
    - Zero = neutral (calibration baseline)
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(300)

        # Data storage: one value per finger (net force)
        self._fingers: List[str] = []
        self._values: Dict[str, float] = (
            {}
        )  # finger -> net %MVC (positive=extension, negative=flexion)
        self._targets: Dict[str, float] = (
            {}
        )  # finger -> target %MVC (positive=extension, negative=flexion)
        self._target_directions: Dict[str, str] = {}  # finger -> 'up'/'down'/'no'
        self._in_target: Dict[str, bool] = {}  # finger -> is_in_target
        self._tolerance: float = 5.0

        # Visual feedback
        self._flash_color: Optional[QColor] = None
        self._flash_timer = QTimer()
        self._flash_timer.timeout.connect(self._clear_flash)

        # Colors
        self._bg_color = QColor("#1a1a2e")
        self._bar_bg_color = QColor("#2d2d44")
        self._extension_color = QColor("#4a9eff")  # Blue for extension (up)
        self._flexion_color = QColor("#ff6b9d")  # Pink for flexion (down)
        self._target_color = QColor("#48BB78")  # Green target zone
        self._zero_tolerance_color = QColor(
            "#666666"
        )  # Gray for "no movement" tolerance
        self._in_target_color = QColor("#00ff00")  # Bright green when in target

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def setup_bars(self, fingers: List[str]):
        """Setup bars for the given finger names"""
        self._fingers = fingers
        self._values = {f: 0.0 for f in fingers}
        self._targets = {f: 0.0 for f in fingers}
        self._target_directions = {f: "no" for f in fingers}
        self._in_target = {f: False for f in fingers}

    def update_values(self, values: Dict[str, float]):
        """
        Update current net force values.
        Args:
            values: {finger: net_mvc_percent} where positive=extension, negative=flexion
        """
        self._values.update(values)

    def update_targets(self, targets: Dict[str, float], directions: Dict[str, str]):
        """
        Update target values and directions.
        Args:
            targets: {finger: target_mvc_percent}
            directions: {finger: 'up'/'down'/'no'}
        """
        self._targets.update(targets)
        self._target_directions.update(directions)

    def update_in_target(self, states: Dict[str, bool]):
        """Update in-target states: {finger: is_in_target}"""
        self._in_target.update(states)

    def set_tolerance(self, tolerance: float):
        """Set tolerance band width (ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â± %MVC)"""
        self._tolerance = tolerance

    def clear_all(self):
        """Clear all values"""
        for f in self._fingers:
            self._values[f] = 0.0
            self._in_target[f] = False

    def show_success(self):
        """Flash green for success"""
        self._flash_color = QColor(0, 255, 0, 80)
        self._flash_timer.start(500)

    def show_failure(self):
        """Flash red for failure"""
        self._flash_color = QColor(255, 0, 0, 80)
        self._flash_timer.start(500)

    def _clear_flash(self):
        self._flash_timer.stop()
        self._flash_color = None

    def paintEvent(self, event):
        if not self.isVisible() or self.width() <= 0 or self.height() <= 0:
            return

        painter = QPainter(self)
        if not painter.isActive():
            return

        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()

        # Background
        painter.fillRect(self.rect(), self._bg_color)

        # Flash overlay
        if self._flash_color:
            painter.fillRect(self.rect(), self._flash_color)

        if not self._fingers:
            painter.setPen(QColor("#888888"))
            painter.drawText(self.rect(), Qt.AlignCenter, "No fingers configured")
            return

        n_fingers = len(self._fingers)

        # Layout
        margin_left = 80
        margin_right = 40
        margin_top = 60
        margin_bottom = 60
        bar_spacing = 30

        total_bar_width = w - margin_left - margin_right - (n_fingers - 1) * bar_spacing
        bar_width = max(total_bar_width // n_fingers, 40)
        bar_height = h - margin_top - margin_bottom

        # Center line Y (0% MVC - calibration baseline)
        center_y = margin_top + bar_height // 2
        half_height = bar_height // 2

        # Dynamic scaling: find maximum absolute value across targets
        max_abs_target = 0.0
        for finger in self._fingers:
            target = abs(self._targets.get(finger, 0.0))
            max_abs_target = max(max_abs_target, target)

        # Add 20% buffer
        max_scale = max(max_abs_target * 1.2, 20.0)  # Minimum 20%

        # Scale function: max_scale MVC = half_height pixels
        def mvc_to_pixels(mvc_percent: float) -> int:
            return int((mvc_percent / max_scale) * half_height)

        # Draw scale labels on left
        painter.setPen(QColor("#888888"))
        painter.setFont(QFont("Arial", 10))
        for pct in [max_scale, max_scale / 2, 0, -max_scale / 2, -max_scale]:
            y = center_y - mvc_to_pixels(pct)
            painter.drawText(
                QRect(5, y - 10, margin_left - 10, 20),
                Qt.AlignRight | Qt.AlignVCenter,
                f"{pct:.0f}%",
            )
            painter.drawLine(margin_left - 5, y, margin_left, y)

        # Draw each finger column
        for i, finger in enumerate(self._fingers):
            bar_x = margin_left + i * (bar_width + bar_spacing)
            column_center_x = bar_x + bar_width // 2

            # Column background
            painter.fillRect(
                bar_x, margin_top, bar_width, bar_height, self._bar_bg_color
            )

            # Center line (0% - calibration baseline)
            painter.setPen(QPen(QColor("#ffffff"), 3))
            painter.drawLine(bar_x, center_y, bar_x + bar_width, center_y)

            # Get values
            net_val = self._values.get(finger, 0.0)
            target_val = self._targets.get(finger, 0.0)
            target_dir = self._target_directions.get(finger, "no")
            in_target = self._in_target.get(finger, False)

            # Draw target zone
            if target_dir == "no":
                # Draw tolerance band around zero
                tol_pixels = mvc_to_pixels(self._tolerance)
                painter.fillRect(
                    bar_x,
                    center_y - tol_pixels,
                    bar_width,
                    2 * tol_pixels,
                    QColor(
                        self._zero_tolerance_color.red(),
                        self._zero_tolerance_color.green(),
                        self._zero_tolerance_color.blue(),
                        60,
                    ),
                )
            else:
                # Draw target zone for up or down
                target_pixels = mvc_to_pixels(abs(target_val))
                tol_pixels = mvc_to_pixels(self._tolerance)

                if target_dir == "down":
                    # Negative target (flexion)
                    target_y = center_y + target_pixels
                    painter.fillRect(
                        bar_x,
                        target_y - tol_pixels,
                        bar_width,
                        2 * tol_pixels,
                        QColor(
                            self._target_color.red(),
                            self._target_color.green(),
                            self._target_color.blue(),
                            80,
                        ),
                    )
                    # Target line
                    painter.setPen(QPen(self._target_color, 3))
                    painter.drawLine(bar_x, target_y, bar_x + bar_width, target_y)
                else:  # 'up'
                    # Positive target (extension)
                    target_y = center_y - target_pixels
                    painter.fillRect(
                        bar_x,
                        target_y - tol_pixels,
                        bar_width,
                        2 * tol_pixels,
                        QColor(
                            self._target_color.red(),
                            self._target_color.green(),
                            self._target_color.blue(),
                            80,
                        ),
                    )
                    # Target line
                    painter.setPen(QPen(self._target_color, 3))
                    painter.drawLine(bar_x, target_y, bar_x + bar_width, target_y)

            # Draw current force bar
            val_pixels = mvc_to_pixels(abs(net_val))

            if abs(net_val) > 0.5:  # Only draw if significant
                if net_val > 0:  # Extension (up)
                    bar_y = center_y - val_pixels
                    bar_h = val_pixels
                    bar_color = self._extension_color
                else:  # Flexion (down)
                    bar_y = center_y
                    bar_h = val_pixels
                    bar_color = self._flexion_color

                # Highlight if in target
                if in_target:
                    bar_color = self._in_target_color

                painter.fillRect(bar_x + 5, bar_y, bar_width - 10, bar_h, bar_color)

            # Finger label at bottom
            painter.setPen(QColor("#ffffff"))
            painter.setFont(QFont("Arial", 11, QFont.Bold))
            painter.drawText(
                QRect(bar_x, margin_top + bar_height + 5, bar_width, 30),
                Qt.AlignCenter | Qt.AlignTop,
                finger.capitalize(),
            )

            # Current value text at top
            painter.setFont(QFont("Arial", 10))
            painter.drawText(
                QRect(bar_x, margin_top - 40, bar_width, 30),
                Qt.AlignCenter,
                f"{net_val:.1f}%",
            )

# CLEAN PIANO WIDGETS - NO TEXT, JUST MOVING BARS
# Copy this and REPLACE the PianoKeyWidget and BeautifulPianoBarTask classes
# at the END of your gui/widgets.py file

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QTimer, QRect
from PySide6.QtGui import QPainter, QPen, QColor, QFont
from typing import Dict, Optional


class PianoKeyWidget(QWidget):
    """
    Clean piano key - just moving bars, no text labels
    """
    
    def __init__(self, finger_name: str, parent=None):
        super().__init__(parent)
        self.finger_name = finger_name
        
        # Values
        self.extension_value = 0.0
        self.flexion_value = 0.0
        self.extension_target = 0.0
        self.flexion_target = 0.0
        self.tolerance = 5.0
        
        # State
        self.extension_in_target = False
        self.flexion_in_target = False
        
        # Animation
        self._glow_intensity = 0.0
        
        # Colors
        self.bg_color = QColor("#2a2a3e")
        self.extension_color = QColor("#4FC3F7")  # Blue
        self.flexion_color = QColor("#FF6B9D")  # Pink
        self.in_target_color = QColor("#4CAF50")  # Green
        self.out_target_color = QColor("#F44336")  # Red
        self.neutral_color = QColor("#757575")  # Gray
        self.tolerance_color = QColor(120, 120, 120, 80)  # Gray shaded
        
    def set_tolerance(self, tolerance: float):
        self.tolerance = tolerance
        self.update()
        
    def set_extension(self, value: float, target: float, in_target: bool):
        self.extension_value = value
        self.extension_target = target
        self.extension_in_target = in_target
        self.update()
        
    def set_flexion(self, value: float, target: float, in_target: bool):
        self.flexion_value = value
        self.flexion_target = target
        self.flexion_in_target = in_target
        self.update()
        
    def trigger_glow(self, success: bool):
        self._glow_intensity = 1.0 if success else -1.0
        QTimer.singleShot(500, self._clear_glow)
        self.update()
        
    def _clear_glow(self):
        self._glow_intensity = 0.0
        self.update()
        
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        w = self.width()
        h = self.height()
        mid_y = h // 2
        
        # Background
        painter.fillRect(0, 0, w, h, self.bg_color)
        
        # Separation line
        painter.setPen(QPen(QColor("#ffffff"), 2))
        painter.drawLine(0, mid_y, w, mid_y)
        
        # EXTENSION (TOP)
        self._draw_half(painter, 0, 0, w, mid_y, 
                       self.extension_value, self.extension_target,
                       self.extension_in_target, self.extension_color)
        
        # FLEXION (BOTTOM)
        self._draw_half(painter, 0, mid_y, w, mid_y,
                       self.flexion_value, self.flexion_target,
                       self.flexion_in_target, self.flexion_color)
        
        # Finger label (ONLY TEXT WE KEEP)
        painter.setPen(QColor("#ffffff"))
        painter.setFont(QFont("Arial", 14, QFont.Bold))
        painter.drawText(QRect(0, h - 35, w, 30), 
                        Qt.AlignCenter, self.finger_name.upper())
        
        # Glow overlay
        if abs(self._glow_intensity) > 0.01:
            glow_color = self.in_target_color if self._glow_intensity > 0 else self.out_target_color
            glow_color.setAlpha(int(abs(self._glow_intensity) * 100))
            painter.fillRect(self.rect(), glow_color)
            
        painter.end()
        
    def _draw_half(self, painter, x, y, w, h, value, target, in_target, base_color):
        """
        Draw half - CLEAN, NO TEXT
        Y-axis: 0-25% MVC (not 0-100%)
        """
        
        # Y-AXIS MAX = 25% MVC (not 100%)
        Y_MAX = 25.0
        
        # Clamp values to max
        value = min(value, Y_MAX)
        target = min(target, Y_MAX)
        
        # TOLERANCE BAND (gray shaded area)
        if target > 0:
            target_upper = min(target + self.tolerance, Y_MAX)
            target_lower = max(target - self.tolerance, 0.0)
            
            # Convert to pixels (using Y_MAX instead of 100)
            upper_pixels = (target_upper / Y_MAX) * h * 0.85
            lower_pixels = (target_lower / Y_MAX) * h * 0.85
            
            # Y positions from bottom
            upper_y = y + h - upper_pixels
            lower_y = y + h - lower_pixels
            
            # Draw tolerance band
            tolerance_height = upper_pixels - lower_pixels
            if tolerance_height > 0:
                painter.fillRect(
                    int(x + 8), 
                    int(upper_y), 
                    int(w - 16), 
                    int(tolerance_height),
                    self.tolerance_color
                )
            
            # PURPLE LINE showing exact target
            target_pixels = (target / Y_MAX) * h * 0.85
            target_y = y + h - target_pixels
            painter.setPen(QPen(QColor("#9b59b6"), 3))  # Purple, 3px thick
            painter.drawLine(int(x + 8), int(target_y), int(x + w - 8), int(target_y))
            
            # CURRENT VALUE BAR
            if value > 0:
                value_pixels = (value / Y_MAX) * h * 0.85  # Scale to Y_MAX
                value_y = y + h - value_pixels
                
                # Color
                if in_target:
                    bar_color = self.in_target_color  # GREEN
                else:
                    bar_color = self.out_target_color  # RED
                
                bar_color.setAlpha(220)
                
                # Draw bar
                painter.fillRect(
                    int(x + 18), 
                    int(value_y), 
                    int(w - 36), 
                    int(value_pixels), 
                    bar_color
                )


class BeautifulPianoBarTask(QWidget):
    """
    Clean piano display - bars move up/down, no text labels
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(500)
        
        self.fingers = ['thumb', 'index', 'middle', 'ring', 'pinkie']
        self.keys: Dict[str, PianoKeyWidget] = {}
        self._tolerance = 5.0
        
        # Countdown
        self.countdown_active = False
        self.countdown_value = 3
        
        # Flash
        self._flash_color: Optional[QColor] = None
        self._flash_timer = QTimer()
        self._flash_timer.timeout.connect(self._clear_flash)
        
        self._setup_keys()
        
    def _setup_keys(self):
        for finger in self.fingers:
            key = PianoKeyWidget(finger, self)
            key.set_tolerance(self._tolerance)
            self.keys[finger] = key
            
    def set_tolerance(self, tolerance: float):
        self._tolerance = tolerance
        for key in self.keys.values():
            key.set_tolerance(tolerance)
        
    def resizeEvent(self, event):
        w = self.width()
        h = self.height()
        
        status_height = 100
        available_height = h - status_height
        
        n_keys = len(self.fingers)
        key_spacing = 15
        total_spacing = key_spacing * (n_keys + 1)
        key_width = (w - total_spacing) // n_keys
        key_height = available_height - 20
        
        x = key_spacing
        y = status_height + 10
        
        for finger in self.fingers:
            key = self.keys[finger]
            key.setGeometry(x, y, key_width, key_height)
            key.show()
            x += key_width + key_spacing
            
        super().resizeEvent(event)
        
    def setup_fingers(self, finger_config: Dict[str, Dict]):
        for finger, config in finger_config.items():
            if finger in self.keys:
                key = self.keys[finger]
                key.extension_target = config.get('ext_target', 0)
                key.flexion_target = config.get('flex_target', 0)
                
    def update_forces(self, forces: Dict[str, Dict[str, float]]):
        """Update force values - BARS WILL MOVE!"""
        for finger, values in forces.items():
            if finger in self.keys:
                key = self.keys[finger]
                
                ext_val = values.get('ext', 0)
                flex_val = values.get('flex', 0)
                ext_in = values.get('ext_in_target', False)
                flex_in = values.get('flex_in_target', False)
                
                key.set_extension(ext_val, key.extension_target, ext_in)
                key.set_flexion(flex_val, key.flexion_target, flex_in)
                
    def start_countdown(self):
        self.countdown_active = True
        self.countdown_value = 3
        self._countdown_step()
        
    def _countdown_step(self):
        if self.countdown_value > 0:
            self.update()
            QTimer.singleShot(1000, self._countdown_step)
            self.countdown_value -= 1
        else:
            self.countdown_active = False
            self.update()
            
    def show_success(self):
        self._flash_color = QColor(76, 175, 80, 100)
        self._flash_timer.start(800)
        for key in self.keys.values():
            key.trigger_glow(True)
            
    def show_failure(self):
        self._flash_color = QColor(244, 67, 54, 100)
        self._flash_timer.start(800)
        for key in self.keys.values():
            key.trigger_glow(False)
    
    def clear_result_glow(self):
        """Clear success/failure glow - for NEW trial"""
        for key in self.keys.values():
            key._glow_intensity = 0.0
            key._glow_target = 0.0
        self.update()
            
    def _clear_flash(self):
        self._flash_timer.stop()
        self._flash_color = None
        self.update()
        
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Background
        bg_color = QColor("#1a1a2e")
        painter.fillRect(self.rect(), bg_color)
        
        # Flash
        if self._flash_color:
            painter.fillRect(self.rect(), self._flash_color)
        
        # Countdown
        if self.countdown_active and self.countdown_value > 0:
            overlay = QColor(0, 0, 0, 180)
            painter.fillRect(self.rect(), overlay)
            
            painter.setPen(QColor("#ffffff"))
            painter.setFont(QFont("Arial", 120, QFont.Bold))
            painter.drawText(self.rect(), Qt.AlignCenter, str(self.countdown_value))
            
        painter.end()