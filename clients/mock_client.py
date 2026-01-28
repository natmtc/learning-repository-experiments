"""
Mock Novecento+ client for testing without hardware.
Based on Configuration Protocol v2.3

Hardware Architecture:
- IN1 to IN10: 10 input ports on front panel
- Each input can have probes: 8, 16, 32, 40, 64, or 96 channels
- AUX1-AUX8: Auxiliary inputs on back panel
"""

import time
import threading
import numpy as np
from typing import Optional, List, Dict, Callable, Set
from dataclasses import dataclass

from core.novecento_config import (
    NovecentoConfiguration,
    ProbeType, SamplingRate
)


@dataclass
class StreamData:
    """Data from a single streaming block"""
    emg_samples: np.ndarray      # Shape: (n_channels, n_samples)
    aux_samples: np.ndarray      # Shape: (n_aux, n_samples)
    timestamps: np.ndarray       # Shape: (n_samples,)
    accessory_data: dict         # Counter, trigger, etc.


@dataclass
class DeviceInfo:
    """Device information"""
    device_id: str
    firmware_version: str
    hardware_version: str
    battery_level: int
    serial_number: str


@dataclass
class ProbeInfo:
    """Information about probe connected to an input"""
    input_number: int
    probe_type: ProbeType
    num_channels: int


class MockNovecentoClient:
    """
    Mock implementation of Novecento+ client for testing.
    Generates realistic synthetic EMG and force sensor data.
    
    Hardware Configuration (from protocol):
    - IN1 to IN10: Input ports
    - Each input can have 0, 8, 16, 32, 40, 64, or 96 channels
    - AUX1-AUX8: Auxiliary channels
    """
    
    NUM_INPUTS = 10      # IN1-IN10
    NUM_AUX = 8          # AUX1-AUX8
    
    def __init__(self):
        self._connected = False
        self._streaming = False
        self._stream_callbacks: List[Callable[[StreamData], None]] = []
        
        # Configuration
        self._config: Optional[NovecentoConfiguration] = None
        
        # Detected probes (simulated hardware detection)
        self._detected_probes: Dict[str, ProbeType] = {}
        
        self._stream_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        
        # Synthetic signal parameters
        self._emg_noise_level = 0.1  # mV
        self._aux_noise_level = 0.5  # N
        
        # For force tracking
        self._force_targets: Dict[str, float] = {}
        self._time_offset = 0.0
    
    @property
    def is_connected(self) -> bool:
        return self._connected
    
    @property
    def is_streaming(self) -> bool:
        return self._streaming
    
    @property
    def sample_rate(self) -> SamplingRate:
        """Get the current sampling rate from configuration"""
        if self._config:
            # Return highest sampling rate among enabled inputs
            max_rate = SamplingRate.HZ_2000  # Default
            for input_name, inp_config in self._config.inputs.items():
                if inp_config.is_enabled:
                    if inp_config.sampling_rate.frequency > max_rate.frequency:
                        max_rate = inp_config.sampling_rate
            return max_rate
        return SamplingRate.HZ_2000  # Default
    
    def connect(self, port_or_device_id: str) -> bool:
        """Simulate connection to device"""
        if self._connected:
            return True
        
        # Simulate connection delay
        time.sleep(0.5)
        
        # Simulate probe detection (random for testing)
        self._detect_probes()
        
        self._connected = True
        return True
    
    def _detect_probes(self):
        """Simulate probe detection - returns what probes are physically connected"""
        # For testing, simulate some probes connected
        self._detected_probes = {
            "IN1": ProbeType.CHANNELS_64,
            "IN2": ProbeType.CHANNELS_64,
            "IN3": ProbeType.CHANNELS_32,
            "IN4": ProbeType.NO_PROBE,
            "IN5": ProbeType.NO_PROBE,
            "IN6": ProbeType.NO_PROBE,
            "IN7": ProbeType.NO_PROBE,
            "IN8": ProbeType.NO_PROBE,
            "IN9": ProbeType.NO_PROBE,
            "IN10": ProbeType.NO_PROBE,
        }
    
    def disconnect(self) -> None:
        """Disconnect from device"""
        if self._streaming:
            self.stop_streaming()
        self._connected = False
        self._config = None
    
    def get_device_info(self) -> DeviceInfo:
        """Get device information"""
        if not self._connected:
            raise RuntimeError("Not connected to device")
        
        return DeviceInfo(
            device_id="MOCK_NOVECENTO_001",
            firmware_version="v2.3.0-mock",
            hardware_version="v1.0",
            battery_level=85,
            serial_number="MOCK-2024-001"
        )
    
    def get_hardware_configuration(self) -> Dict[str, ProbeInfo]:
        """
        Request hardware configuration (command 0x01).
        Returns what probes are physically connected to each input.
        """
        if not self._connected:
            raise RuntimeError("Not connected to device")
        
        probes = {}
        for i in range(1, 11):
            input_name = f"IN{i}"
            probe_type = self._detected_probes.get(input_name, ProbeType.NO_PROBE)
            probes[input_name] = ProbeInfo(
                input_number=i,
                probe_type=probe_type,
                num_channels=probe_type.num_channels
            )
        return probes
    
    def get_battery_level(self) -> int:
        """Request battery level (command 0x03)"""
        if not self._connected:
            raise RuntimeError("Not connected to device")
        return 85  # Mock battery level
    
    def list_channels(self) -> Dict[str, List]:
        """Legacy method for backwards compatibility with other tabs"""
        if not self._connected:
            raise RuntimeError("Not connected to device")
        
        # Return based on detected probes (not applied config)
        emg_channels = []
        for input_name, probe_type in self._detected_probes.items():
            if probe_type != ProbeType.NO_PROBE:
                for ch in range(1, probe_type.num_channels + 1):
                    emg_channels.append(type('ChannelInfo', (), {
                        'channel_id': f"{input_name}_CH{ch:02d}",
                        'channel_type': 'emg',
                        'input_number': int(input_name[2:]),
                        'channel_number': ch,
                        'is_active': False
                    })())
        
        aux_channels = []
        for i in range(1, 9):
            aux_channels.append(type('ChannelInfo', (), {
                'channel_id': f"AUX{i}",
                'channel_type': 'aux',
                'input_number': i,
                'channel_number': 1,
                'is_active': False
            })())
        
        return {"emg": emg_channels, "aux": aux_channels}
    
    def apply_configuration(self, config: NovecentoConfiguration) -> bool:
        """
        Apply configuration to device.
        This sends the 15-byte configuration string.
        """
        if not self._connected:
            raise RuntimeError("Not connected to device")
        if self._streaming:
            raise RuntimeError("Cannot configure while streaming")
        
        self._config = config
        
        # In real implementation, this would send:
        # config.build_config_bytes(start_acquisition=False)
        
        return True
    
    def get_input_list(self) -> List[str]:
        """Get list of all input names"""
        return [f"IN{i}" for i in range(1, 11)]
    
    def get_aux_list(self) -> List[str]:
        """Get list of all AUX names"""
        return [f"AUX{i}" for i in range(1, 9)]
    
    def get_active_channels(self) -> Dict[str, List[str]]:
        """Get list of active channel IDs based on current configuration"""
        if not self._config:
            return {"emg": [], "aux": []}
        
        emg_channels = []
        for input_name in sorted(self._config.inputs.keys(), key=lambda x: int(x[2:])):
            inp = self._config.inputs[input_name]
            if inp.is_enabled:
                for ch in range(1, inp.num_channels + 1):
                    emg_channels.append(f"{input_name}_CH{ch:02d}")
        
        aux_channels = sorted(list(self._config.aux_channels))
        
        return {"emg": emg_channels, "aux": aux_channels}
    
    def set_active_channels(self, emg_channels: List[str], aux_channels: List[str]) -> None:
        """Legacy method - creates config from channel lists"""
        if not self._connected:
            raise RuntimeError("Not connected to device")
        # NOTE: No longer preventing this during streaming since we support multiple callbacks
        # The configuration change will be applied but streaming will continue
        
        # Create a new config from channel lists
        if not self._config:
            self._config = NovecentoConfiguration.create_default()
        
        # Parse EMG channels to determine which inputs are enabled
        for ch_id in emg_channels:
            # Parse "IN1_CH01" -> "IN1"
            if "_CH" in ch_id:
                input_name = ch_id.rsplit("_CH", 1)[0]
                if input_name in self._config.inputs:
                    self._config.inputs[input_name].is_enabled = True
                    # Set probe type based on detected probes
                    if input_name in self._detected_probes:
                        self._config.inputs[input_name].probe_type = self._detected_probes[input_name]
        
        # Parse AUX channels
        self._config.aux_channels = set(aux_channels)
    
    def start_streaming(self, callback: Callable[[StreamData], None]) -> None:
        """Start data streaming - adds callback to list of stream consumers"""
        if not self._connected:
            raise RuntimeError("Not connected to device")
        if not self._config:
            raise RuntimeError("No configuration applied")
        
        # Add callback if not already in list
        if callback not in self._stream_callbacks:
            self._stream_callbacks.append(callback)
        
        # Start streaming thread if not already running
        if not self._streaming:
            self._streaming = True
            self._stop_event.clear()
            self._time_offset = time.time()
            
            self._stream_thread = threading.Thread(target=self._stream_loop, daemon=True)
            self._stream_thread.start()
    
    def stop_streaming(self, callback: Optional[Callable[[StreamData], None]] = None) -> None:
        """
        Stop streaming. 
        If callback is provided, only removes that callback.
        If callback is None, stops all streaming and clears all callbacks.
        """
        if callback is not None:
            # Remove specific callback
            if callback in self._stream_callbacks:
                self._stream_callbacks.remove(callback)
            
            # If no more callbacks, stop streaming
            if not self._stream_callbacks and self._streaming:
                self._stop_event.set()
                if self._stream_thread:
                    self._stream_thread.join(timeout=2.0)
                self._streaming = False
        else:
            # Stop all streaming
            if not self._streaming:
                return
            
            self._stop_event.set()
            if self._stream_thread:
                self._stream_thread.join(timeout=2.0)
            self._streaming = False
            self._stream_callbacks.clear()
    
    def _stream_loop(self):
        """Main streaming loop"""
        if not self._config:
            return
        
        # Use highest sampling rate among enabled inputs
        max_rate = 2000
        for inp in self._config.inputs.values():
            if inp.is_enabled:
                max_rate = max(max_rate, inp.sampling_rate.frequency)
        
        samples_per_block = max_rate // 50  # 20ms blocks
        sample_period = 1.0 / max_rate
        block_period = samples_per_block * sample_period
        
        sample_counter = 0
        
        while not self._stop_event.is_set():
            block_start = time.time()
            
            # Generate timestamps
            timestamps = np.arange(sample_counter, sample_counter + samples_per_block) * sample_period
            sample_counter += samples_per_block
            
            # Count active EMG channels
            n_emg = sum(
                inp.num_channels 
                for inp in self._config.inputs.values() 
                if inp.is_enabled
            )
            
            # Generate EMG data
            if n_emg > 0:
                emg_samples = self._generate_emg_data(n_emg, samples_per_block, timestamps)
            else:
                emg_samples = np.zeros((0, samples_per_block))
            
            # Generate AUX data
            n_aux = len(self._config.aux_channels)
            if n_aux > 0:
                aux_samples = self._generate_aux_data(n_aux, samples_per_block, timestamps)
            else:
                aux_samples = np.zeros((0, samples_per_block))
            
            # Create stream data
            stream_data = StreamData(
                emg_samples=emg_samples,
                aux_samples=aux_samples,
                timestamps=timestamps,
                accessory_data={
                    'counter': np.arange(sample_counter - samples_per_block, sample_counter),
                    'trigger': np.zeros(samples_per_block, dtype=np.int32)
                }
            )
            
            # Call all callbacks
            for callback in self._stream_callbacks:
                try:
                    callback(stream_data)
                except Exception as e:
                    print(f"Error in stream callback: {e}")
            
            # Maintain timing
            elapsed = time.time() - block_start
            sleep_time = block_period - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)
    
    def _generate_emg_data(self, n_channels: int, n_samples: int,
                          timestamps: np.ndarray) -> np.ndarray:
        """Generate synthetic EMG signals"""
        emg = np.zeros((n_channels, n_samples))
        
        for ch in range(n_channels):
            # Base noise
            noise = np.random.randn(n_samples) * self._emg_noise_level
            
            # Low-frequency drift
            t = timestamps
            slow_wave = 0.05 * np.sin(2 * np.pi * 0.5 * t + ch * 0.1)
            
            # Muscle activation bursts
            burst_freq = 0.2 + 0.1 * np.random.random()
            burst = 0.3 * np.sin(2 * np.pi * burst_freq * t) * np.sin(2 * np.pi * 20 * t + ch)
            burst *= (np.sin(2 * np.pi * 0.3 * t) > 0.5).astype(float)
            
            # High frequency components
            emg_hf = 0.1 * np.sin(2 * np.pi * 150 * t + np.random.random() * 2 * np.pi)
            
            emg[ch] = noise + slow_wave + burst + emg_hf
        
        return emg
    
    def _generate_aux_data(self, n_channels: int, n_samples: int,
                          timestamps: np.ndarray) -> np.ndarray:
        """Generate synthetic force sensor data"""
        aux = np.zeros((n_channels, n_samples))
        
        aux_list = sorted(list(self._config.aux_channels)) if self._config else []
        
        for ch_idx, aux_name in enumerate(aux_list):
            if ch_idx >= n_channels:
                break
            
            target = self._force_targets.get(aux_name, 0.0)
            t = timestamps
            
            if target > 0:
                base_force = target * (1 + 0.1 * np.sin(2 * np.pi * 0.3 * t))
                noise = np.random.randn(n_samples) * self._aux_noise_level
                aux[ch_idx] = base_force + noise
            else:
                aux[ch_idx] = np.random.randn(n_samples) * self._aux_noise_level
        
        return aux
    
    def set_force_target(self, channel_id: str, target_force: float) -> None:
        """Set target force for an AUX channel"""
        self._force_targets[channel_id] = target_force
    
    def set_trigger_low(self) -> None:
        """Set trigger output low (command 0x06)"""
        pass  # Mock implementation
    
    def set_trigger_high(self) -> None:
        """Set trigger output high (command 0x07)"""
        pass  # Mock implementation
    
    def reset_device(self) -> None:
        """Reset device (command 0x04)"""
        if self._streaming:
            self.stop_streaming()


# Backwards compatibility aliases
ChannelInfo = ProbeInfo