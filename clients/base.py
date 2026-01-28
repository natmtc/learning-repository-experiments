"""
Abstract base class for Novecento client interface.
Based on OT Bioelettronica Novecento+ Configuration Protocol v2.3
"""

from abc import ABC, abstractmethod
from typing import Callable, Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum
import numpy as np


class SamplingRate(Enum):
    """Supported sampling rates for the Novecento+"""
    HZ_500 = 500
    HZ_2000 = 2000
    HZ_4000 = 4000
    HZ_8000 = 8000
    
    @property
    def frequency(self) -> int:
        """Get frequency in Hz (for compatibility with novecento_config.SamplingRate)"""
        return self.value


class ProbeType(Enum):
    """Probe types that can be connected to Novecento+"""
    NO_PROBE = 0
    CHANNELS_8 = 1
    CHANNELS_16 = 2
    CHANNELS_32 = 3
    CHANNELS_40 = 4
    CHANNELS_64 = 5
    CHANNELS_96 = 6


@dataclass
class ChannelInfo:
    """Information about a single channel"""
    channel_id: str
    channel_type: str  # 'emg' or 'aux'
    input_number: int
    channel_number: int
    is_active: bool = False
    probe_type: Optional[ProbeType] = None


@dataclass
class DeviceInfo:
    """Information about the connected device"""
    firmware_version: str
    serial_number: str
    battery_level: int
    hardware_config: Dict[int, ProbeType]


@dataclass
class StreamData:
    """Container for streamed data"""
    emg_samples: np.ndarray  # Shape: (n_emg_channels, n_samples)
    aux_samples: np.ndarray  # Shape: (n_aux_channels, n_samples)
    timestamps: np.ndarray   # Shape: (n_samples,)
    accessory_data: Optional[Dict[str, np.ndarray]] = None


class NovecentoClient(ABC):
    """
    Abstract base class defining the interface for Novecento+ communication.
    
    The Novecento+ is a bioelectrical signal amplifier from OT Bioelettronica
    that supports up to 10 EMG inputs and 10 auxiliary inputs.
    
    Connection is via TCP/IP socket (default: 169.254.1.10:23456).
    """
    
    def __init__(self):
        self._connected = False
        self._streaming = False
        self._emg_channels: List[ChannelInfo] = []
        self._aux_channels: List[ChannelInfo] = []
        self._sample_rate = SamplingRate.HZ_2000
        self._stream_callback: Optional[Callable[[StreamData], None]] = None
    
    @property
    def is_connected(self) -> bool:
        """Check if client is connected to device"""
        return self._connected
    
    @property
    def is_streaming(self) -> bool:
        """Check if data streaming is active"""
        return self._streaming
    
    @property
    def sample_rate(self) -> SamplingRate:
        """Get current sampling rate"""
        return self._sample_rate
    
    @sample_rate.setter
    def sample_rate(self, rate: SamplingRate):
        """Set sampling rate"""
        if self._streaming:
            raise RuntimeError("Cannot change sample rate while streaming")
        self._sample_rate = rate
    
    @abstractmethod
    def connect(self, port_or_device_id: str) -> bool:
        """
        Connect to the Novecento+ device.
        
        Args:
            port_or_device_id: Connection string, can be:
                - IP address (e.g., '169.254.1.10') - uses default port 23456
                - IP:port format (e.g., '169.254.1.10:23456')
                - None or empty string for default connection
        
        Returns:
            True if connection successful, False otherwise
        """
        pass
    
    @abstractmethod
    def disconnect(self) -> None:
        """Disconnect from the device"""
        pass
    
    @abstractmethod
    def list_channels(self) -> Dict[str, List[ChannelInfo]]:
        """
        Get available channels.
        
        Returns:
            Dictionary with 'emg' and 'aux' keys containing lists of ChannelInfo
        """
        pass
    
    @abstractmethod
    def start_streaming(self, callback: Callable[[StreamData], None]) -> None:
        """
        Start streaming data from the device.
        
        Args:
            callback: Function called with StreamData for each data block
        """
        pass
    
    @abstractmethod
    def stop_streaming(self) -> None:
        """Stop data streaming"""
        pass
    
    @abstractmethod
    def get_device_info(self) -> DeviceInfo:
        """Get device information (firmware, serial, battery, etc.)"""
        pass
    
    @abstractmethod
    def set_active_channels(self, emg_channels: List[str], 
                           aux_channels: List[str]) -> None:
        """
        Set which channels are active for recording.
        
        Args:
            emg_channels: List of EMG channel IDs to activate
            aux_channels: List of auxiliary channel IDs to activate
        """
        pass
    
    @abstractmethod
    def configure_input(self, input_number: int, 
                       gain: int = 4,
                       high_pass_filter: bool = True,
                       high_resolution: bool = False,
                       sampling_rate: SamplingRate = SamplingRate.HZ_2000) -> None:
        """
        Configure an input channel.
        
        Args:
            input_number: Input number (1-10)
            gain: Preamp gain (2, 4, 6, or 8)
            high_pass_filter: Enable high-pass filter
            high_resolution: Use 24-bit resolution instead of 16-bit
            sampling_rate: Sampling frequency
        """
        pass