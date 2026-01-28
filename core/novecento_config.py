"""
Novecento+ Configuration Module
Implements the OT Bioelettronica Configuration Protocol v2.3

This module handles all configurable parameters that affect the 15-byte
CRC8 command sent to the device via TCP/IP (169.254.1.10:23456).

15-byte Configuration Command Structure:
    Byte 0:  ACQ_SETT_A - ACQ bit, AUX sampling freq, IN9/10 enable
    Byte 1:  ACQ_SETT_B - IN1-8 enable bits
    Byte 2:  AN_OUT_A   - Analog output gain + source input
    Byte 3:  AN_OUT_B   - Analog output channel
    Byte 4-13: IN1_CONF - IN10_CONF - Per-input configuration
    Byte 14: CRC8 checksum

Data Timing:
    - Data arrives in 2ms blocks (minimum interval = 500 Hz)
    - Buffer size depends on sampling rate and active channels
"""

from enum import IntEnum
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple
import copy
import json
import os


# =============================================================================
# ENUMERATIONS - Matching Protocol Specification Exactly
# =============================================================================

class SamplingRate(IntEnum):
    """
    Sampling frequency codes (FSAMP bits 1-0 or AUXFS bits 5-4)
    From Configuration Protocol v2.3
    """
    HZ_500 = 0b00   # 500 Hz
    HZ_2000 = 0b01  # 2000 Hz (default)
    HZ_4000 = 0b10  # 4000 Hz
    HZ_8000 = 0b11  # 8000 Hz
    
    @property
    def frequency(self) -> int:
        """Get actual frequency in Hz"""
        return {0b00: 500, 0b01: 2000, 0b10: 4000, 0b11: 8000}[self.value]
    
    @property
    def samples_per_2ms(self) -> int:
        """Number of samples in each 2ms block"""
        return self.frequency // 500
    
    @property
    def hpf_cutoff(self) -> float:
        """High-pass filter cutoff frequency = Fsamp/190"""
        return self.frequency / 190.0
    
    @classmethod
    def from_frequency(cls, freq: int) -> 'SamplingRate':
        """Get enum from frequency value"""
        for sr in cls:
            if sr.frequency == freq:
                return sr
        raise ValueError(f"Invalid frequency: {freq}")


class WorkingMode(IntEnum):
    """
    Working mode (MODE bits 7-6)
    From Configuration Protocol v2.3
    """
    MONOPOLAR = 0b00        # Normal acquisition, all channels vs reference
    NOT_USED = 0b01         # Reserved
    IMPEDANCE_CHECK = 0b10  # Impedance measurement mode
    TEST_MODE = 0b11        # Sends ramps on all channels (for testing)


# Alias for backward compatibility
InputMode = WorkingMode


class Gain(IntEnum):
    """
    Preamplifier gain (GAIN bits 5-4)
    Resolution and range depend on HRES setting.
    From Configuration Protocol v2.3
    """
    GAIN_2 = 0b00   # Gain 2 if HRES=1, Gain 8 if HRES=0
    GAIN_4 = 0b01   # Gain 4
    GAIN_6 = 0b10   # Gain 6
    GAIN_8 = 0b11   # Gain 8
    
    @property
    def value_numeric(self) -> int:
        """Get numeric gain value (assuming 16-bit mode for simplicity)"""
        return {0b00: 8, 0b01: 4, 0b10: 6, 0b11: 8}[self.value]
    
    def get_actual_gain(self, high_resolution: bool) -> int:
        """Get actual gain value based on resolution setting"""
        if self == Gain.GAIN_2:
            return 2 if high_resolution else 8
        return {Gain.GAIN_4: 4, Gain.GAIN_6: 6, Gain.GAIN_8: 8}[self]
    
    def get_resolution_nv(self, high_resolution: bool) -> float:
        """Get resolution in nanovolts (nV)"""
        gain = self.get_actual_gain(high_resolution)
        if high_resolution:
            return 286.1 / (gain / 2)
        else:
            return 286.1
    
    def get_range_mv(self, high_resolution: bool) -> float:
        """Get input range in millivolts"""
        if high_resolution:
            gain = self.get_actual_gain(True)
            return {2: 1200.0, 4: 600.0, 6: 400.0, 8: 300.0}[gain]
        else:
            return {0b00: 9.375, 0b01: 18.75, 0b10: 12.5, 0b11: 9.375}[self.value]


# Alias for backward compatibility
PreampGain = Gain


class AnalogOutGain(IntEnum):
    """
    Analog output gain (AN_GAIN bits 5-4)
    From Configuration Protocol v2.3
    """
    GAIN_1 = 0b00   # x1
    GAIN_2 = 0b01   # x2
    GAIN_4 = 0b10   # x4
    GAIN_16 = 0b11  # x16
    
    @property
    def multiplier(self) -> int:
        return {0b00: 1, 0b01: 2, 0b10: 4, 0b11: 16}[self.value]


class ProbeType(IntEnum):
    """
    Probe type codes returned by hardware config query.
    From Configuration Protocol v2.3
    """
    NO_PROBE = 0
    CHANNELS_8 = 1    # Bio8-BP: 8 BIO + 4 IMU + 2 ACC = 14 total
    CHANNELS_16 = 2   # 16 + 4 + 2 = 22 total
    CHANNELS_32 = 3   # Bio32-HD: 32 + 4 + 2 = 38 total
    CHANNELS_40 = 4   # Bio40-IM: 40 + 4 + 2 = 46 total
    CHANNELS_64 = 5   # Bio64-HD: 64 + 4 + 2 = 70 total
    CHANNELS_96 = 6   # Bio96-HD: 96 + 4 + 2 = 102 total
    
    @property
    def num_channels(self) -> int:
        """Total channels including IMU and ACC (ChVsType array)"""
        return [0, 14, 22, 38, 46, 70, 102, 0, 0, 0, 0, 0, 0, 0, 0, 0][self.value]
    
    @property
    def bio_channels(self) -> int:
        """Number of bioelectrical signal channels only"""
        return [0, 8, 16, 32, 40, 64, 96][self.value] if self.value <= 6 else 0


# =============================================================================
# INPUT CONFIGURATION
# =============================================================================

@dataclass
class InputConfiguration:
    """
    Configuration for a single input (IN1-IN10).
    Each field corresponds to bits in the INx_CONF byte.
    
    INx_CONF byte structure:
        bit 7-6: MODE (working mode)
        bit 5-4: GAIN (preamp gain)
        bit 3:   HPF (high pass filter)
        bit 2:   HRES (high resolution 24-bit)
        bit 1-0: FSAMP (sampling frequency)
    """
    is_enabled: bool = False
    probe_type: ProbeType = ProbeType.NO_PROBE
    mode: WorkingMode = WorkingMode.MONOPOLAR
    gain: Gain = Gain.GAIN_4
    high_pass_filter: bool = True
    high_resolution: bool = False
    sampling_rate: SamplingRate = SamplingRate.HZ_2000
    
    # Metadata for documentation
    muscle_name: str = ""
    side: str = ""
    placement: str = ""
    
    @property
    def num_channels(self) -> int:
        """Number of channels based on connected probe"""
        return self.probe_type.num_channels
    
    @property
    def bytes_per_2ms(self) -> int:
        """
        Size of data packet for this input per 2ms block.
        Formula: (HRES+1) × (Fsamp/500) × NumChannels × 2
        """
        if not self.is_enabled or self.num_channels == 0:
            return 0
        bytes_per_sample = 4 if self.high_resolution else 2
        samples_per_2ms = self.sampling_rate.frequency // 500
        return bytes_per_sample * samples_per_2ms * self.num_channels
    
    @property
    def actual_gain(self) -> int:
        """Actual preamp gain value"""
        return self.gain.get_actual_gain(self.high_resolution)
    
    @property
    def resolution_nv(self) -> float:
        """Resolution in nanovolts"""
        return self.gain.get_resolution_nv(self.high_resolution)
    
    @property
    def range_mv(self) -> float:
        """Input range in millivolts"""
        return self.gain.get_range_mv(self.high_resolution)
    
    @property
    def hpf_cutoff_hz(self) -> float:
        """High-pass filter cutoff frequency (0 if disabled)"""
        if not self.high_pass_filter:
            return 0.0
        return self.sampling_rate.frequency / 190.0
    
    def to_config_byte(self) -> int:
        """
        Convert to INx_CONF byte.
        MODE1 MODE0 GAIN1 GAIN0 HPF HRES FSAMP1 FSAMP0
        """
        return (
            (self.mode.value << 6) |
            (self.gain.value << 4) |
            (int(self.high_pass_filter) << 3) |
            (int(self.high_resolution) << 2) |
            self.sampling_rate.value
        )
    
    @classmethod
    def from_config_byte(cls, byte: int, probe_type: ProbeType = ProbeType.NO_PROBE) -> 'InputConfiguration':
        """Create from INx_CONF byte"""
        return cls(
            is_enabled=True,
            mode=WorkingMode((byte >> 6) & 0x03),
            gain=Gain((byte >> 4) & 0x03),
            high_pass_filter=bool((byte >> 3) & 0x01),
            high_resolution=bool((byte >> 2) & 0x01),
            sampling_rate=SamplingRate(byte & 0x03),
            probe_type=probe_type
        )


# =============================================================================
# COMPLETE DEVICE CONFIGURATION
# =============================================================================

@dataclass
class NovecentoConfiguration:
    """
    Complete configuration for Novecento+ device.
    Contains all parameters that affect the 15-byte CRC8 command.
    """
    # Connection settings
    ip_address: str = "169.254.1.10"
    port: int = 23456
    
    # 10 input configurations (IN1-IN10)
    inputs: Dict[str, InputConfiguration] = field(default_factory=dict)
    
    # Auxiliary channels
    aux_channels: Set[str] = field(default_factory=set)
    aux_sampling_rate: SamplingRate = SamplingRate.HZ_2000
    
    # Analog output
    analog_out_input: int = 1      # 1-10 (IN1-IN10)
    analog_out_channel: int = 0    # 0-based channel number
    analog_out_gain: int = 1       # 1, 2, 4, or 16
    
    # Display settings
    display_refresh_ms: int = 75
    plot_time_seconds: float = 1.0
    vertical_offset: float = 2.0
    
    # Buffer settings
    receive_buffer_multiplier: int = 2
    
    def __post_init__(self):
        """Initialize input configurations if not provided"""
        if not self.inputs:
            for i in range(1, 11):
                self.inputs[f"IN{i}"] = InputConfiguration()
    
    @classmethod
    def create_default(cls) -> 'NovecentoConfiguration':
        """Create default configuration"""
        config = cls()
        for i in range(1, 11):
            config.inputs[f"IN{i}"] = InputConfiguration()
        return config
    
    # -------------------------------------------------------------------------
    # Computed Properties
    # -------------------------------------------------------------------------
    
    @property
    def enabled_inputs(self) -> List[str]:
        """List of enabled input names"""
        return [name for name, inp in self.inputs.items() if inp.is_enabled]
    
    @property
    def total_emg_channels(self) -> int:
        """Total number of EMG channels"""
        return sum(inp.num_channels for inp in self.inputs.values() if inp.is_enabled)
    
    @property
    def total_aux_channels(self) -> int:
        """Number of active AUX channels"""
        return len(self.aux_channels)
    
    @property
    def aux_bytes_per_2ms(self) -> int:
        """AUX packet size per 2ms block"""
        return 16 * self.aux_sampling_rate.samples_per_2ms * 2
    
    @property
    def packet_size_2ms(self) -> int:
        """
        Size of one 2ms data block in bytes.
        Sum of all active inputs + AUX + Accessory (256 bytes)
        """
        size = 0
        for inp in self.inputs.values():
            if inp.is_enabled:
                size += inp.bytes_per_2ms
        size += self.aux_bytes_per_2ms
        size += 256  # Accessory channels always 256 bytes
        return size
    
    @property
    def bytes_per_second(self) -> int:
        """Total bytes per second of data"""
        return self.packet_size_2ms * 500
    
    @property
    def buffer_size_bytes(self) -> int:
        """Total buffer size for PlotTime seconds"""
        return int(self.packet_size_2ms * 500 * self.plot_time_seconds * 2)
    
    # -------------------------------------------------------------------------
    # Configuration Command Building
    # -------------------------------------------------------------------------
    
    def build_acq_sett_a(self, start_acquisition: bool = True) -> int:
        """
        Build ACQ_SETT_A byte (byte 0).
        ACQ  0  AUXFS1 AUXFS0  0  0  IN10ON IN9ON
        """
        acq_bit = 0b10000000 if start_acquisition else 0b00000000
        aux_fs = (self.aux_sampling_rate.value & 0x03) << 4
        in10_on = 0b00000010 if self.inputs.get("IN10", InputConfiguration()).is_enabled else 0
        in9_on = 0b00000001 if self.inputs.get("IN9", InputConfiguration()).is_enabled else 0
        return acq_bit | aux_fs | in10_on | in9_on
    
    def build_acq_sett_b(self) -> int:
        """
        Build ACQ_SETT_B byte (byte 1).
        IN8ON IN7ON IN6ON IN5ON IN4ON IN3ON IN2ON IN1ON
        """
        result = 0
        for i in range(1, 9):
            if self.inputs.get(f"IN{i}", InputConfiguration()).is_enabled:
                result |= (1 << (i - 1))
        return result
    
    def build_an_out_a(self) -> int:
        """Build AN_OUT_A byte (byte 2)"""
        gain_map = {1: 0b00, 2: 0b01, 4: 0b10, 16: 0b11}
        gain_code = gain_map.get(self.analog_out_gain, 0b00)
        in_code = self.analog_out_input - 1
        if self.analog_out_input >= 8:
            in_code = self.analog_out_input
        return (gain_code << 4) | (in_code & 0x0F)
    
    def build_an_out_b(self) -> int:
        """Build AN_OUT_B byte (byte 3)"""
        return self.analog_out_channel & 0x7F
    
    def build_config_bytes(self, start_acquisition: bool = True) -> List[int]:
        """
        Build the complete 15-byte configuration command.
        Returns list of 15 integers (bytes 0-14).
        """
        config = []
        
        # Byte 0: ACQ_SETT_A
        config.append(self.build_acq_sett_a(start_acquisition))
        
        # Byte 1: ACQ_SETT_B
        config.append(self.build_acq_sett_b())
        
        # Byte 2: AN_OUT_A
        config.append(self.build_an_out_a())
        
        # Byte 3: AN_OUT_B
        config.append(self.build_an_out_b())
        
        # Bytes 4-13: IN1_CONF through IN10_CONF
        for i in range(1, 11):
            inp = self.inputs.get(f"IN{i}", InputConfiguration())
            config.append(inp.to_config_byte())
        
        # Byte 14: CRC8
        config.append(compute_crc8(config))
        
        return config
    
    def build_stop_command(self) -> List[int]:
        """Build command to stop acquisition (ACQ bit = 0)"""
        return self.build_config_bytes(start_acquisition=False)
    
    # -------------------------------------------------------------------------
    # Input Pointer Calculation (for data parsing)
    # -------------------------------------------------------------------------
    
    def get_input_pointers(self) -> Tuple[List[int], List[int]]:
        """
        Calculate data pointers for each input.
        Returns (pointers, sizes) where:
            pointers[i] = byte offset to start of INi+1 data
            sizes[i] = bytes of data for INi+1
        """
        pointers = [0] * 11
        sizes = [0] * 10
        
        for i in range(10):
            inp = self.inputs.get(f"IN{i+1}", InputConfiguration())
            sizes[i] = inp.bytes_per_2ms if inp.is_enabled else 0
            pointers[i + 1] = pointers[i] + sizes[i]
        
        return pointers, sizes
    
    # -------------------------------------------------------------------------
    # Validation
    # -------------------------------------------------------------------------
    
    def validate(self) -> List[str]:
        """Validate configuration, return list of warnings/errors."""
        warnings = []
        
        if not self.enabled_inputs:
            warnings.append("No inputs enabled")
        
        src_input = self.inputs.get(f"IN{self.analog_out_input}")
        if src_input and src_input.is_enabled:
            if self.analog_out_channel >= src_input.num_channels:
                warnings.append(
                    f"Analog output channel {self.analog_out_channel} "
                    f"exceeds IN{self.analog_out_input} channels ({src_input.num_channels})"
                )
        
        rates = set()
        for inp in self.inputs.values():
            if inp.is_enabled:
                rates.add(inp.sampling_rate)
        if len(rates) > 1:
            warnings.append(f"Mixed sampling rates: {[r.frequency for r in rates]}Hz")
        
        return warnings
    
    # -------------------------------------------------------------------------
    # Serialization
    # -------------------------------------------------------------------------
    
    def to_dict(self) -> dict:
        """Convert to dictionary for saving"""
        return {
            "ip_address": self.ip_address,
            "port": self.port,
            "inputs": {
                name: {
                    "is_enabled": inp.is_enabled,
                    "probe_type": inp.probe_type.value,
                    "mode": inp.mode.value,
                    "gain": inp.gain.value,
                    "high_pass_filter": inp.high_pass_filter,
                    "high_resolution": inp.high_resolution,
                    "sampling_rate": inp.sampling_rate.value,
                    "muscle_name": inp.muscle_name,
                    "side": inp.side,
                    "placement": inp.placement
                }
                for name, inp in self.inputs.items()
            },
            "aux_channels": list(self.aux_channels),
            "aux_sampling_rate": self.aux_sampling_rate.value,
            "analog_out_input": self.analog_out_input,
            "analog_out_channel": self.analog_out_channel,
            "analog_out_gain": self.analog_out_gain,
            "display_refresh_ms": self.display_refresh_ms,
            "plot_time_seconds": self.plot_time_seconds,
            "vertical_offset": self.vertical_offset
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'NovecentoConfiguration':
        """Create from dictionary"""
        config = cls(
            ip_address=data.get("ip_address", "169.254.1.10"),
            port=data.get("port", 23456)
        )
        
        for name, inp_data in data.get("inputs", {}).items():
            config.inputs[name] = InputConfiguration(
                is_enabled=inp_data.get("is_enabled", False),
                probe_type=ProbeType(inp_data.get("probe_type", 0)),
                mode=WorkingMode(inp_data.get("mode", 0)),
                gain=Gain(inp_data.get("gain", 1)),
                high_pass_filter=inp_data.get("high_pass_filter", True),
                high_resolution=inp_data.get("high_resolution", False),
                sampling_rate=SamplingRate(inp_data.get("sampling_rate", 1)),
                muscle_name=inp_data.get("muscle_name", ""),
                side=inp_data.get("side", ""),
                placement=inp_data.get("placement", "")
            )
        
        config.aux_channels = set(data.get("aux_channels", []))
        config.aux_sampling_rate = SamplingRate(data.get("aux_sampling_rate", 1))
        config.analog_out_input = data.get("analog_out_input", 1)
        config.analog_out_channel = data.get("analog_out_channel", 0)
        config.analog_out_gain = data.get("analog_out_gain", 1)
        config.display_refresh_ms = data.get("display_refresh_ms", 75)
        config.plot_time_seconds = data.get("plot_time_seconds", 1.0)
        config.vertical_offset = data.get("vertical_offset", 2.0)
        
        return config
    
    def save_to_file(self, filepath: str):
        """Save configuration to JSON file"""
        with open(filepath, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)
    
    @classmethod
    def load_from_file(cls, filepath: str) -> 'NovecentoConfiguration':
        """Load configuration from JSON file"""
        with open(filepath, 'r') as f:
            data = json.load(f)
        return cls.from_dict(data)
    
    def copy(self) -> 'NovecentoConfiguration':
        """Create a deep copy"""
        return copy.deepcopy(self)


# =============================================================================
# CRC8 CALCULATION
# =============================================================================

def compute_crc8(data: List[int]) -> int:
    """
    Compute CRC8 checksum for Novecento+ protocol.
    Uses the exact algorithm from OT Bioelettronica code.
    """
    crc = 0
    j = 0
    length = len(data)
    
    while length > 0:
        extract = data[j]
        for i in range(8, 0, -1):
            sum_val = crc % 2 ^ extract % 2
            crc //= 2
            
            if sum_val > 0:
                a = format(crc, "08b")
                b = format(140, "08b")
                str_list = [0] * 8
                
                for k in range(8):
                    str_list[k] = int(a[k] != b[k])
                
                crc = int("".join(map(str, str_list)), 2)
            
            extract //= 2
        
        length -= 1
        j += 1
    
    return crc


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def calculate_packet_info(config: NovecentoConfiguration) -> dict:
    """Calculate detailed packet size information."""
    pointers, sizes = config.get_input_pointers()
    
    return {
        "inputs": {
            f"IN{i+1}": {
                "enabled": config.inputs.get(f"IN{i+1}", InputConfiguration()).is_enabled,
                "channels": config.inputs.get(f"IN{i+1}", InputConfiguration()).num_channels,
                "bytes_per_2ms": sizes[i],
                "pointer": pointers[i]
            }
            for i in range(10)
        },
        "aux": {
            "channels": 16,
            "bytes_per_2ms": config.aux_bytes_per_2ms,
            "pointer": pointers[10]
        },
        "accessory": {
            "channels": 4,
            "bytes_per_2ms": 256,
            "pointer": pointers[10] + config.aux_bytes_per_2ms
        },
        "total_2ms_block": config.packet_size_2ms,
        "bytes_per_second": config.bytes_per_second,
        "buffer_size": config.buffer_size_bytes
    }


def format_config_bytes(config_bytes: List[int]) -> str:
    """Format configuration bytes for display"""
    lines = [
        f"ACQ_SETT_A (0):  {config_bytes[0]:08b} = 0x{config_bytes[0]:02X}",
        f"ACQ_SETT_B (1):  {config_bytes[1]:08b} = 0x{config_bytes[1]:02X}",
        f"AN_OUT_A   (2):  {config_bytes[2]:08b} = 0x{config_bytes[2]:02X}",
        f"AN_OUT_B   (3):  {config_bytes[3]:08b} = 0x{config_bytes[3]:02X}",
    ]
    for i in range(10):
        lines.append(f"IN{i+1}_CONF  ({4+i}):  {config_bytes[4+i]:08b} = 0x{config_bytes[4+i]:02X}")
    lines.append(f"CRC8       (14): {config_bytes[14]:08b} = 0x{config_bytes[14]:02X}")
    return "\n".join(lines)