"""
Force Feedback Protocols
Implements trapezoid and bar-task protocols.

UPDATED: Simplified Bar Task Protocol for Beautiful Piano Display
- 5 fingers always visible
- Each finger has extension (top) and flexion (bottom)
- Clear color feedback (green = in target, red = outside)
- 3-2-1 countdown support
"""

import numpy as np
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Callable, Any, Tuple
from enum import Enum
from datetime import datetime
import csv
import time
from pathlib import Path


class TrialState(Enum):
    """State of a trial"""
    IDLE = "idle"
    PREPARING = "preparing"
    RUNNING = "running"
    SUCCESS = "success"
    FAILURE_TIMEOUT = "failure_timeout"
    FAILURE_OUT_OF_RANGE = "failure_out_of_range"
    COMPLETED = "completed"


class Direction(Enum):
    """Force direction for bar task"""
    EXTENSION = "ext"
    FLEXION = "flex"


@dataclass
class TrapezoidParams:
    """Parameters for trapezoid protocol"""
    aux_channel: str
    target_mvc_percent: float
    rest_before: float = 2.0      # seconds
    ramp_up: float = 3.0          # seconds
    plateau_duration: float = 5.0  # seconds
    ramp_down: float = 3.0        # seconds
    rest_after: float = 2.0       # seconds
    tolerance_percent: float = 5.0  # ± % of target
    
    @property
    def total_duration(self) -> float:
        return (self.rest_before + self.ramp_up + self.plateau_duration + 
                self.ramp_down + self.rest_after)
    
    def get_target_at_time(self, t: float) -> float:
        """Get the target %MVC at time t"""
        if t < self.rest_before:
            return 0.0
        
        t_ramp_start = self.rest_before
        t_plateau_start = t_ramp_start + self.ramp_up
        t_ramp_down_start = t_plateau_start + self.plateau_duration
        t_rest_start = t_ramp_down_start + self.ramp_down
        
        if t < t_plateau_start:
            # Ramp up phase
            progress = (t - t_ramp_start) / self.ramp_up
            return self.target_mvc_percent * progress
        elif t < t_ramp_down_start:
            # Plateau phase
            return self.target_mvc_percent
        elif t < t_rest_start:
            # Ramp down phase
            progress = (t - t_ramp_down_start) / self.ramp_down
            return self.target_mvc_percent * (1 - progress)
        else:
            return 0.0


@dataclass
class TrapezoidResult:
    """Results from trapezoid protocol"""
    params: TrapezoidParams
    start_time: str
    end_time: str
    success: bool
    time_in_target: float
    total_time: float
    rms_error: float
    mean_error: float
    max_error: float
    raw_force: np.ndarray
    target_trace: np.ndarray
    timestamps: np.ndarray
    
    @property
    def time_in_target_percent(self) -> float:
        plateau_time = self.params.plateau_duration
        if plateau_time > 0:
            return (self.time_in_target / plateau_time) * 100
        return 0.0


class TrapezoidProtocol:
    """
    Trapezoid force-matching protocol.
    User must track a trapezoidal force profile.
    """
    
    def __init__(self, params: TrapezoidParams,
                 mvc_value: float,
                 offset_value: float = 0.0,
                 sample_rate: int = 2000):
        self.params = params
        self.mvc_value = mvc_value
        self.offset_value = offset_value
        self.sample_rate = sample_rate
        
        self._state = TrialState.IDLE
        self._start_time: Optional[float] = None
        self._force_buffer: List[float] = []
        self._time_buffer: List[float] = []
        
        self._on_state_change: Optional[Callable[[TrialState], None]] = None
        self._on_update: Optional[Callable[[float, float, float], None]] = None
    
    @property
    def state(self) -> TrialState:
        return self._state
    
    def set_callbacks(self, 
                     on_state_change: Callable[[TrialState], None] = None,
                     on_update: Callable[[float, float, float], None] = None):
        """Set callback functions"""
        self._on_state_change = on_state_change
        self._on_update = on_update
    
    def _set_state(self, state: TrialState):
        self._state = state
        if self._on_state_change:
            self._on_state_change(state)
    
    @property
    def elapsed_time(self) -> float:
        """Get elapsed time since protocol started"""
        if self._start_time is None:
            return 0.0
        return time.time() - self._start_time
    
    def get_target_at_time(self, t: float) -> float:
        """Get target %MVC at given time"""
        return self.params.get_target_at_time(t)
    
    def start(self):
        """Start the protocol"""
        self._state = TrialState.RUNNING
        self._start_time = time.time()
        self._force_buffer = []
        self._time_buffer = []
        self._set_state(TrialState.RUNNING)
    
    def stop(self):
        """Stop the protocol"""
        self._set_state(TrialState.COMPLETED)
    
    def update(self, force_value: float) -> Tuple[float, float, bool]:
        """
        Update with new force sample.
        
        Args:
            force_value: Current force reading
        
        Returns:
            Tuple of (current_target, tolerance_band, is_in_target)
        """
        if self._state != TrialState.RUNNING or self._start_time is None:
            return 0.0, 0.0, False
        
        elapsed = time.time() - self._start_time
        
        # Check if protocol complete
        if elapsed >= self.params.total_duration:
            self._set_state(TrialState.COMPLETED)
            return 0.0, 0.0, False
        
        # Store sample
        self._force_buffer.append(force_value)
        self._time_buffer.append(elapsed)
        
        # Get target at current time
        target_percent = self.params.get_target_at_time(elapsed)
        target_force = (target_percent / 100.0) * self.mvc_value + self.offset_value
        
        # Compute tolerance band
        tolerance_force = (self.params.tolerance_percent / 100.0) * self.mvc_value
        
        # Check if in target
        error = abs(force_value - target_force)
        is_in_target = error <= tolerance_force
        
        # Notify callback
        if self._on_update:
            self._on_update(elapsed, target_force, force_value)
        
        return target_force, tolerance_force, is_in_target
    
    def get_target_trace(self, n_points: int = 1000) -> Tuple[np.ndarray, np.ndarray]:
        """Generate the full target trace for visualization"""
        times = np.linspace(0, self.params.total_duration, n_points)
        targets = np.array([self.params.get_target_at_time(t) for t in times])
        target_forces = (targets / 100.0) * self.mvc_value + self.offset_value
        return times, target_forces
    
    def compute_results(self) -> TrapezoidResult:
        """Compute results from the trial"""
        times = np.array(self._time_buffer)
        forces = np.array(self._force_buffer)
        
        # Compute target trace
        target_percents = np.array([self.params.get_target_at_time(t) for t in times])
        target_forces = (target_percents / 100.0) * self.mvc_value + self.offset_value
        
        # Compute errors
        errors = forces - target_forces
        rms_error = np.sqrt(np.mean(errors ** 2))
        mean_error = np.mean(np.abs(errors))
        max_error = np.max(np.abs(errors))
        
        # Time in target (during plateau only)
        plateau_start = self.params.rest_before + self.params.ramp_up
        plateau_end = plateau_start + self.params.plateau_duration
        plateau_mask = (times >= plateau_start) & (times <= plateau_end)
        
        tolerance_force = (self.params.tolerance_percent / 100.0) * self.mvc_value
        in_target = np.abs(errors[plateau_mask]) <= tolerance_force
        time_in_target = np.sum(in_target) / self.sample_rate if len(in_target) > 0 else 0.0
        
        success = time_in_target >= (self.params.plateau_duration * 0.8)  # 80% of plateau
        
        return TrapezoidResult(
            params=self.params,
            start_time=datetime.fromtimestamp(self._start_time).isoformat() if self._start_time else "",
            end_time=datetime.now().isoformat(),
            success=success,
            time_in_target=time_in_target,
            total_time=times[-1] if len(times) > 0 else 0.0,
            rms_error=rms_error,
            mean_error=mean_error,
            max_error=max_error,
            raw_force=forces,
            target_trace=target_forces,
            timestamps=times
        )


# ============================================================================
# BEAUTIFUL PIANO BAR TASK PROTOCOL (SIMPLIFIED)
# ============================================================================

@dataclass
class BarSpec:
    """Specification for a single bar (finger + direction)"""
    finger: str  # 'thumb', 'index', 'middle', 'ring', 'pinkie'
    channel: str  # 'AUX1', 'AUX2', etc.
    direction: Direction  # Extension or flexion
    target_mvc_percent: float  # Target force level
    hold_time_s: float  # Required hold duration
    
    def get_required_channels(self) -> List[str]:
        """Get list of channels needed for this bar"""
        return [self.channel]


@dataclass
class BarTaskParams:
    """Parameters for bar task protocol"""
    bar_specs: List[BarSpec]
    tolerance_percent: float = 5.0  # ± tolerance for being "in target"
    time_to_target_s: float = 5.0  # Max time to reach target
    hold_time_s: float = 3.0  # Time to hold in target


@dataclass
class BarState:
    """State of a single bar during trial"""
    bar_spec: BarSpec
    current_force: float = 0.0  # Raw force value
    current_mvc_percent: float = 0.0  # As % of MVC
    is_in_target: bool = False
    time_in_target: float = 0.0  # Cumulative time in target zone
    time_out_of_target: float = 0.0  # Time spent out of target


@dataclass
class BarTrialResult:
    """Results from a completed bar task trial"""
    trial_number: int
    start_time: datetime
    end_time: datetime
    success: bool
    time_to_target: float  # Time to first achieve all targets
    hold_time_achieved: float  # Time all targets held
    bar_results: Dict[str, Dict]  # Detailed results per bar
    timestamps: List[float]


class BarTaskProtocol:
    """
    Protocol for piano-style multi-finger force matching.
    Each finger can have extension and/or flexion targets.
    
    SIMPLIFIED VERSION for Beautiful Piano Display:
    - Clear separation between extension and flexion
    - Direct mapping to piano keys
    - Easy color feedback
    """
    
    def __init__(self, params: BarTaskParams, calibration: Dict[str, Tuple[float, float]]):
        """
        Args:
            params: Protocol parameters
            calibration: {channel: (mvc, offset)} for each channel
        """
        self.params = params
        self.calibration = calibration
        
        # Group bars by finger
        self._bars_by_finger: Dict[str, List[BarSpec]] = {}
        for spec in params.bar_specs:
            if spec.finger not in self._bars_by_finger:
                self._bars_by_finger[spec.finger] = []
            self._bars_by_finger[spec.finger].append(spec)
        
        # State
        self._state = TrialState.IDLE
        self._bar_states: Dict[str, BarState] = {}
        self._trial_number = 0
        self._start_time: Optional[datetime] = None
        self._first_all_in_target_time: Optional[float] = None
        
        # Data storage
        self._force_history: Dict[str, List[float]] = {}
        self._timestamps: List[float] = []
        self._last_update_time: Optional[float] = None
        
        # Callbacks
        self._state_callback = None
        self._update_callback = None
        
    def set_state_callback(self, callback):
        """Set callback for state changes: callback(TrialState)"""
        self._state_callback = callback
        
    def set_update_callback(self, callback):
        """Set callback for updates: callback(Dict[str, BarState])"""
        self._update_callback = callback
        
    def start_trial(self, trial_number: int):
        """Start a new trial"""
        self._trial_number = trial_number
        self._state = TrialState.RUNNING
        self._start_time = datetime.now()
        self._first_all_in_target_time = None
        self._last_update_time = None
        
        # Initialize bar states
        self._bar_states = {}
        self._force_history = {}
        self._timestamps = []
        
        for spec in self.params.bar_specs:
            key = f"{spec.finger}_{spec.direction.value}"
            self._bar_states[key] = BarState(bar_spec=spec)
            self._force_history[key] = []
            
        if self._state_callback:
            self._state_callback(self._state)
            
    def update(self, force_values: Dict[str, float]) -> TrialState:
        """
        Update protocol with new force readings.
        Args:
            force_values: {channel_name: force_value}
        Returns:
            Current trial state
        """
        if self._state not in [TrialState.RUNNING]:
            return self._state
            
        # Calculate time
        current_time = datetime.now()
        if self._last_update_time is None:
            dt = 0.0
            elapsed = 0.0
        else:
            elapsed = (current_time - self._start_time).total_seconds()
            dt = (current_time.timestamp() - self._last_update_time)
            
        self._last_update_time = current_time.timestamp()
        self._timestamps.append(elapsed)
        
        # Update each bar state
        all_in_target = True
        
        for key, state in self._bar_states.items():
            spec = state.bar_spec
            channel = spec.channel
            
            # Get calibration
            if channel not in self.calibration:
                continue
            mvc, offset = self.calibration[channel]
            
            # Get force value
            if channel in force_values:
                raw_force = force_values[channel]
                # Apply offset and convert to %MVC
                normalized_force = raw_force - offset
                mvc_percent = (normalized_force / mvc * 100.0) if mvc > 0 else 0.0
                
                state.current_force = raw_force
                state.current_mvc_percent = mvc_percent
                
                # Store history
                self._force_history[key].append(mvc_percent)
                
                # Check if in target
                target = spec.target_mvc_percent
                tolerance = self.params.tolerance_percent
                
                if abs(mvc_percent - target) <= tolerance:
                    state.is_in_target = True
                    state.time_in_target += dt
                else:
                    state.is_in_target = False
                    state.time_out_of_target += dt
                    all_in_target = False
        
        # Track first time all targets achieved
        if all_in_target and self._first_all_in_target_time is None:
            self._first_all_in_target_time = elapsed
            
        # Call update callback
        if self._update_callback:
            self._update_callback(self._bar_states)
            
        # Check if hold phase complete (not success, just time elapsed)
        if self._first_all_in_target_time is not None:
            # We reached target - now in hold phase
            time_since_reaching = elapsed - self._first_all_in_target_time
            
            # Check if hold time has elapsed
            if time_since_reaching >= self.params.hold_time_s:
                # Hold phase complete - calculate percentage
                self._state = TrialState.COMPLETED
                if self._state_callback:
                    self._state_callback(self._state)
                return self._state
                
        # Check timeout condition (only for reaching target initially)
        # Only timeout if time_to_target is reasonable (< 100s means it's enabled)
        if self.params.time_to_target_s < 100.0:
            # Time to target is ENABLED
            if self._first_all_in_target_time is None:
                # Not in target yet - check if time expired
                if elapsed > self.params.time_to_target_s:
                    self._state = TrialState.FAILURE_TIMEOUT
                    if self._state_callback:
                        self._state_callback(self._state)
                    return self._state
        # Note: If time_to_target >= 100s (disabled), we never timeout on reaching target
        # We only end on success (held long enough) or if manually stopped
            
        return self._state
        
    def compute_results(self) -> BarTrialResult:
        """Compute final trial results"""
        end_time = datetime.now()
        
        # Get time to target and hold time
        time_to_target = self._first_all_in_target_time if self._first_all_in_target_time else 0.0
        max_hold = max(s.time_in_target for s in self._bar_states.values()) if self._bar_states else 0.0
        
        # Bar-specific results
        bar_results = {}
        for key, state in self._bar_states.items():
            bar_results[key] = {
                'final_in_target': state.is_in_target,
                'time_in_target': state.time_in_target,
                'final_mvc_percent': state.current_mvc_percent,
            }
            
        return BarTrialResult(
            trial_number=self._trial_number,
            start_time=self._start_time,
            end_time=end_time,
            success=(self._state == TrialState.SUCCESS or self._state == TrialState.COMPLETED),
            time_to_target=time_to_target,
            hold_time_achieved=max_hold,
            bar_results=bar_results,
            timestamps=self._timestamps,
        )
    
    def get_hold_percentage(self) -> float:
        """Calculate percentage of hold time that was in target
        
        Example: If hold_time_s = 3.0 seconds
                 And time_in_target = 2.4 seconds
                 Then percentage = (2.4 / 3.0) * 100 = 80%
        """
        if not self._first_all_in_target_time:
            return 0.0
        
        # Get the REQUIRED hold time (e.g., 3.0 seconds)
        required_hold_time = self.params.hold_time_s
        
        # Get actual time spent in target during hold phase
        max_time_in_target = max(s.time_in_target for s in self._bar_states.values()) if self._bar_states else 0.0
        
        # Calculate percentage: (time in target) / (required time) * 100
        if required_hold_time > 0:
            percentage = (max_time_in_target / required_hold_time) * 100.0
            return min(100.0, percentage)  # Cap at 100%
        return 0.0
        
    @property
    def state(self) -> TrialState:
        return self._state


def create_sample_bar_task_csv(filepath: str):
    """Create a sample CSV file for bar task configuration"""
    sample_data = [
        ["column_id", "aux_channel", "finger", "direction", "target_mvc_percent", "hold_time_s"],
        [1, "AUX1", "thumb", "ext", 0, 3],
        [1, "AUX2", "thumb", "flex", 15, 3],
        [2, "AUX3", "index", "ext", 0, 3],
        [2, "AUX4", "index", "flex", 15, 3],
        [3, "AUX5", "middle", "ext", 0, 3],
        [3, "AUX6", "middle", "flex", 20, 3],
    ]
    
    with open(filepath, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerows(sample_data)