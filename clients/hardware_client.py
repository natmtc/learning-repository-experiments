"""
Hardware Novecento Client for real device communication.
Implements the OT Bioelettronica Novecento+ Configuration Protocol v2.3

TCP/IP Communication:
    - Default IP: 169.254.1.10 (link-local address)
    - Default Port: 23456
    - Data arrives in 2ms blocks

Protocol Commands (2 bytes: COMMAND + CRC8):
    0x00: Stop data transfer
    0x01: Get hardware configuration (20-byte response)
    0x02: Get firmware version (20-byte response)
    0x03: Get battery level (20-byte response)
    0x04: Reset device
    0x05: Get serial number
    0x06: Trigger OUT low
    0x07: Trigger OUT high

Configuration Command (15 bytes):
    Byte 0:   ACQ_SETT_A
    Byte 1:   ACQ_SETT_B
    Byte 2:   AN_OUT_A
    Byte 3:   AN_OUT_B
    Bytes 4-13: IN1_CONF - IN10_CONF
    Byte 14:  CRC8
"""

import socket
import numpy as np
import threading
import time
from typing import Callable, Dict, List, Optional, Tuple
from dataclasses import dataclass

from core.novecento_config import (
    NovecentoConfiguration, InputConfiguration,
    SamplingRate, AnalogOutGain, ProbeType,
    compute_crc8, calculate_packet_info
)


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class StreamData:
    """Data packet from streaming"""
    emg_samples: np.ndarray      # Shape: (n_emg_channels, n_samples)
    aux_samples: np.ndarray      # Shape: (n_aux_channels, n_samples)
    timestamps: np.ndarray       # Shape: (n_samples,)
    accessory_data: Optional[dict] = None  # Additional data (ACC1-4)


@dataclass
class DeviceInfo:
    """Device information"""
    firmware_version: str
    serial_number: str
    battery_level: int
    hardware_config: Dict[int, ProbeType] = None


# =============================================================================
# HARDWARE CLIENT
# =============================================================================

class HardwareNovecentoClient:
    """
    Hardware implementation for Novecento+ communication.
    Communicates via TCP/IP socket using the exact protocol specification.
    """
    
    # Command bytes
    CMD_STOP = 0x00
    CMD_GET_HW_CONFIG = 0x01
    CMD_GET_FIRMWARE = 0x02
    CMD_GET_BATTERY = 0x03
    CMD_RESET = 0x04
    CMD_GET_SERIAL = 0x05
    CMD_TRIG_LOW = 0x06
    CMD_TRIG_HIGH = 0x07
    
    # Probe type to total channels (ChVsType array)
    PROBE_CHANNELS = {
        ProbeType.NO_PROBE: 0,
        ProbeType.CHANNELS_8: 14,    # 8 BIO + 4 IMU + 2 ACC
        ProbeType.CHANNELS_16: 22,   # 16 + 4 + 2
        ProbeType.CHANNELS_32: 38,   # 32 + 4 + 2
        ProbeType.CHANNELS_40: 46,   # 40 + 4 + 2
        ProbeType.CHANNELS_64: 70,   # 64 + 4 + 2
        ProbeType.CHANNELS_96: 102,  # 96 + 4 + 2
    }
    
    # Sampling rate values
    FSAMP_VALUES = {
        SamplingRate.HZ_500: 500,
        SamplingRate.HZ_2000: 2000,
        SamplingRate.HZ_4000: 4000,
        SamplingRate.HZ_8000: 8000,
    }
    
    # AUX packet sizes per 2ms block
    AUX_SIZES = {
        SamplingRate.HZ_500: 32,
        SamplingRate.HZ_2000: 128,
        SamplingRate.HZ_4000: 256,
        SamplingRate.HZ_8000: 512,
    }
    
    # Gain factors from original code
    EMG_GAIN_FACTOR = 0.0002861
    AUX_GAIN_FACTOR = 5 / (2**16) / 0.5
    
    def __init__(self, timeout: float = 2.0):
        self._socket: Optional[socket.socket] = None
        self._timeout = timeout
        self._connected = False
        self._streaming = False
        
        # Configuration
        self._config: Optional[NovecentoConfiguration] = None
        self._hw_probe_types: Dict[int, ProbeType] = {}
        
        # Streaming
        self._stream_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._stream_callbacks: List[Callable[[StreamData], None]] = []
    
    # -------------------------------------------------------------------------
    # Connection Management
    # -------------------------------------------------------------------------
    
    def connect(self, address: str = None) -> bool:
        """
        Connect to Novecento+ device.
        
        Args:
            address: IP:PORT or just IP (uses default port 23456)
                    Default: 169.254.1.10:23456
        
        Returns:
            True if connection successful
        """
        if self._connected:
            return True
        
        # Parse address
        if address:
            if ":" in address:
                ip, port_str = address.split(":")
                port = int(port_str)
            else:
                ip = address
                port = 23456
        else:
            ip = "169.254.1.10"
            port = 23456
        
        try:
            # Create TCP socket
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._socket.settimeout(self._timeout)
            
            print(f"Connecting to {ip}:{port}...")
            self._socket.connect((ip, port))
            print("Connected to the Socket")
            
            # Query hardware configuration
            self._hw_probe_types = self._query_hardware_config()
            
            # Initialize default configuration
            self._config = NovecentoConfiguration(ip_address=ip, port=port)
            
            # Set probe types in config
            for i, probe_type in self._hw_probe_types.items():
                if f"IN{i}" in self._config.inputs:
                    self._config.inputs[f"IN{i}"].probe_type = probe_type
            
            self._connected = True
            return True
            
        except Exception as e:
            print(f"Connection error: {e}")
            if self._socket:
                try:
                    self._socket.close()
                except:
                    pass
                self._socket = None
            return False
    
    def disconnect(self) -> None:
        """Disconnect from device"""
        if self._streaming:
            self.stop_streaming()
        
        if self._socket:
            try:
                # Send stop command
                self._send_stop_config()
            except:
                pass
            
            try:
                self._socket.close()
            except:
                pass
            
            self._socket = None
            print("Socket closed")
        
        self._connected = False
    
    @property
    def is_connected(self) -> bool:
        return self._connected
    
    @property
    def is_streaming(self) -> bool:
        return self._streaming
    
    @property
    def sample_rate(self) -> SamplingRate:
        """Get current sample rate from first enabled input"""
        if self._config:
            for inp in self._config.inputs.values():
                if inp.is_enabled:
                    return inp.sampling_rate
        return SamplingRate.HZ_2000
    
    # -------------------------------------------------------------------------
    # Command Sending
    # -------------------------------------------------------------------------
    
    def _send_command(self, cmd_byte: int) -> Optional[bytes]:
        """
        Send a 2-byte command (command + CRC8) and receive 20-byte response.
        """
        if not self._socket:
            return None
        
        # Build command with CRC
        cmd = [cmd_byte, compute_crc8([cmd_byte])]
        self._socket.sendall(bytearray(cmd))
        
        # Some commands have no response
        if cmd_byte in [self.CMD_STOP, self.CMD_RESET, 
                        self.CMD_TRIG_LOW, self.CMD_TRIG_HIGH]:
            return None
        
        # Read 20-byte response
        response = self._socket.recv(20)
        
        if len(response) != 20:
            raise RuntimeError(f"Incomplete response: got {len(response)} bytes")
        
        # Check for errors (byte 19)
        if response[19] == 0:
            pass  # No error
        elif response[19] == 255:
            raise RuntimeError("Device reported CRC error")
        
        return response
    
    def _send_config(self, config_bytes: List[int]) -> None:
        """
        Send 15-byte configuration command.
        """
        if not self._socket or len(config_bytes) != 15:
            raise ValueError("Invalid configuration")
        
        self._socket.sendall(bytearray(config_bytes))
        time.sleep(0.1)  # Allow device to process
    
    def _send_stop_config(self) -> None:
        """Send configuration with ACQ bit cleared to stop acquisition"""
        if self._config:
            config_bytes = self._config.build_stop_command()
            self._send_config(config_bytes)
    
    # -------------------------------------------------------------------------
    # Device Queries
    # -------------------------------------------------------------------------
    
    def _query_hardware_config(self) -> Dict[int, ProbeType]:
        """
        Query which probes are connected to each input.
        
        Response format: 0x01, IN1PrType, IN2PrType, ..., IN10PrType, 0x00...
        """
        response = self._send_command(self.CMD_GET_HW_CONFIG)
        if not response:
            raise RuntimeError("Failed to get hardware configuration")
        
        config = {}
        print("Probes configuration:", list(response[1:11]))
        
        for i in range(10):
            probe_code = response[i + 1]
            if probe_code <= 6:
                config[i + 1] = ProbeType(probe_code)
            else:
                config[i + 1] = ProbeType.NO_PROBE
        
        return config
    
    def get_hardware_configuration(self) -> Dict[str, dict]:
        """Get connected probe information for each input"""
        if not self._connected:
            raise RuntimeError("Not connected")
        
        result = {}
        for i, probe_type in self._hw_probe_types.items():
            result[f"IN{i}"] = {
                "input_number": i,
                "probe_type": probe_type,
                "num_channels": self.PROBE_CHANNELS.get(probe_type, 0),
                "bio_channels": probe_type.bio_channels
            }
        return result
    
    def get_device_info(self) -> DeviceInfo:
        """Get device information"""
        if not self._connected:
            raise RuntimeError("Not connected")
        
        # Firmware version
        fw_response = self._send_command(self.CMD_GET_FIRMWARE)
        firmware = "Unknown"
        if fw_response:
            firmware = fw_response[1:].decode("ascii", errors="ignore").strip("\x00")
            print(f"Firmware Version: {firmware}")
        
        # Battery level
        bat_response = self._send_command(self.CMD_GET_BATTERY)
        battery = bat_response[1] if bat_response else 0
        print(f"Battery Level: {battery}%")
        
        # Serial number
        try:
            sn_response = self._send_command(self.CMD_GET_SERIAL)
            serial = sn_response[1:].decode("ascii", errors="ignore").strip("\x00") if sn_response else "Unknown"
        except:
            serial = "Unknown"
        
        return DeviceInfo(
            firmware_version=firmware,
            serial_number=serial,
            battery_level=battery,
            hardware_config=self._hw_probe_types
        )
    
    def get_battery_level(self) -> int:
        """Get battery percentage"""
        if not self._connected:
            raise RuntimeError("Not connected")
        response = self._send_command(self.CMD_GET_BATTERY)
        return response[1] if response else 0
    
    # -------------------------------------------------------------------------
    # Configuration Management
    # -------------------------------------------------------------------------
    
    def apply_configuration(self, config: NovecentoConfiguration) -> bool:
        """
        Apply a configuration to the device.
        
        This stores the configuration - actual device config is sent when
        streaming starts.
        """
        if not self._connected:
            raise RuntimeError("Not connected")
        if self._streaming:
            raise RuntimeError("Cannot configure while streaming")
        
        # Preserve probe types from hardware detection
        for name, inp in config.inputs.items():
            input_num = int(name[2:])
            if input_num in self._hw_probe_types:
                inp.probe_type = self._hw_probe_types[input_num]
        
        self._config = config
        return True
    
    def get_configuration(self) -> Optional[NovecentoConfiguration]:
        """Get current configuration"""
        return self._config
    
    def set_active_channels(self, emg_channels: List[str], aux_channels: List[str]):
        """Set active channels for streaming"""
        if self._config:
            self._config.aux_channels = set(aux_channels)
    
    def get_active_channels(self) -> Dict[str, List[str]]:
        """Get list of active channel IDs based on current configuration"""
        if not self._config:
            return {"emg": [], "aux": []}
        
        emg_channels = []
        for name, inp in sorted(self._config.inputs.items(), key=lambda x: int(x[0][2:])):
            if inp.is_enabled:
                for ch in range(1, inp.num_channels + 1):
                    emg_channels.append(f"{name}_CH{ch:02d}")
        
        # FIXED: Use aux_channels directly (it's a Set[str]), not aux_config.enabled_channels
        aux_channels = sorted(list(self._config.aux_channels))
        
        return {"emg": emg_channels, "aux": aux_channels}
    
    # -------------------------------------------------------------------------
    # Streaming
    # -------------------------------------------------------------------------
    
    def start_streaming(self, callback: Callable[[StreamData], None]) -> None:
        """
        Start streaming data from the device.
        Adds callback to list of stream consumers.
        
        Args:
            callback: Function called with each StreamData packet
        """
        if not self._connected:
            raise RuntimeError("Not connected")
        if not self._config:
            raise RuntimeError("No configuration set")
        
        # Add callback if not already in list
        if callback not in self._stream_callbacks:
            self._stream_callbacks.append(callback)
        
        # If already streaming, just add the callback and return
        if self._streaming:
            return
        
        # Ensure aux_channels is populated if empty
        if not self._config.aux_channels:
            print("Warning: No AUX channels configured, enabling LC1 by default")
            self._config.aux_channels = {"LC1"}
        
        # Debug: show active channels
        active = self.get_active_channels()
        print(f"Active channels - EMG: {len(active['emg'])}, AUX: {active['aux']}")
        
        # Build and send configuration command
        config_bytes = self._config.build_config_bytes(start_acquisition=True)
        self._send_config(config_bytes)
        
        print("Configuration sent, starting stream...")
        print(f"Config bytes: {[hex(b) for b in config_bytes]}")
        
        self._streaming = True
        self._stop_event.clear()
        
        # Start streaming thread
        self._stream_thread = threading.Thread(target=self._stream_loop, daemon=True)
        self._stream_thread.start()
    
    def stop_streaming(self, callback: Optional[Callable[[StreamData], None]] = None) -> None:
        """
        Stop data streaming.
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
                
                # Send stop command
                try:
                    self._send_stop_config()
                except:
                    pass
                
                if self._stream_thread:
                    self._stream_thread.join(timeout=2.0)
                
                self._streaming = False
        else:
            # Stop all streaming
            if not self._streaming:
                return
            
            self._stop_event.set()
            
            # Send stop command
            try:
                self._send_stop_config()
            except:
                pass
            
            if self._stream_thread:
                self._stream_thread.join(timeout=2.0)
            
            self._streaming = False
            self._stream_callbacks.clear()
    
    def _stream_loop(self):
        """
        Main streaming loop.
        Implements exact data parsing from OT Bioelettronica code.
        
        CRITICAL: Process data frequently for smooth display!
        We process every ~50ms worth of data (25 blocks of 2ms each).
        """
        if not self._config or not self._socket:
            return
        
        # Calculate packet structure
        pointers, sizes = self._config.get_input_pointers()
        packet_size_2ms = self._config.packet_size_2ms  # BYTES per 2ms block
        
        # Get parameters
        aux_fsamp = self._config.aux_sampling_rate
        
        # CRITICAL FIX: Process data frequently, not in huge chunks!
        # Process every 25 blocks = 50ms of data for smooth display
        blocks_per_chunk = 25  # 25 blocks x 2ms = 50ms
        chunk_size_bytes = packet_size_2ms * blocks_per_chunk
        
        # For parsing, we need to know samples per chunk
        aux_fsamp_val = self.FSAMP_VALUES[aux_fsamp]
        aux_samples_per_chunk = (aux_fsamp_val * blocks_per_chunk * 2) // 1000  # samples in 50ms
        
        print(f"Stream configuration:")
        print(f"  Packet size (2ms): {packet_size_2ms} bytes")
        print(f"  Blocks per chunk: {blocks_per_chunk} (={blocks_per_chunk*2}ms)")
        print(f"  Chunk size: {chunk_size_bytes} bytes")
        print(f"  AUX samples per chunk: {aux_samples_per_chunk}")
        print(f"  Input pointers (bytes): {pointers}")
        print(f"  AUX sampling rate: {aux_fsamp}")
        
        # Set socket to non-blocking with small timeout for responsive streaming
        self._socket.settimeout(0.1)
        
        buffer = b""
        sample_counter = 0
        first_packet = True
        
        while not self._stop_event.is_set() and self._socket:
            try:
                # Read data from TCP socket
                chunk = self._socket.recv(chunk_size_bytes * 4)  # Read up to 4 chunks at once
                if len(chunk) == 0:
                    continue
                
                buffer += chunk
                
                # Process complete chunks (50ms each)
                while len(buffer) >= chunk_size_bytes:
                    packet = buffer[:chunk_size_bytes]
                    buffer = buffer[chunk_size_bytes:]
                    
                    # Parse packet
                    stream_data = self._parse_chunk(
                        packet, 
                        packet_size_2ms,
                        blocks_per_chunk,
                        pointers,
                        sample_counter
                    )
                    
                    if stream_data:
                        if first_packet:
                            print(f"First chunk - EMG: {stream_data.emg_samples.shape}, "
                                  f"AUX: {stream_data.aux_samples.shape}")
                            if stream_data.aux_samples.size > 0:
                                print(f"  AUX range: [{stream_data.aux_samples.min():.4f}, "
                                      f"{stream_data.aux_samples.max():.4f}]")
                            first_packet = False
                        
                        # Call all registered callbacks
                        for callback in self._stream_callbacks:
                            try:
                                callback(stream_data)
                            except Exception as e:
                                print(f"Error in stream callback: {e}")
                    
                    if stream_data:
                        n_samples = stream_data.aux_samples.shape[1] if stream_data.aux_samples.size > 0 else (
                            stream_data.emg_samples.shape[1] if stream_data.emg_samples.size > 0 else 0
                        )
                        sample_counter += n_samples
                        
            except socket.timeout:
                continue
            except Exception as e:
                print(f"Stream error: {e}")
                import traceback
                traceback.print_exc()
                if self._stop_event.is_set():
                    break
    
    def _parse_chunk(
        self, 
        packet: bytes,
        packet_size_2ms: int,
        blocks_per_chunk: int,
        pointers: List[int],
        sample_counter: int
    ) -> Optional[StreamData]:
        """
        Parse a data chunk (multiple 2ms blocks).
        
        This is called frequently (every ~50ms) for smooth display.
        """
        if not self._config:
            return None
        
        aux_fsamp = self._config.aux_sampling_rate
        aux_fsamp_val = self.FSAMP_VALUES[aux_fsamp]
        
        # Convert to numpy array (little-endian 16-bit)
        temp = np.frombuffer(packet, dtype="<i2")
        
        # packet_size_2ms is in BYTES, convert to int16 units
        packet_size_int16 = packet_size_2ms // 2
        
        # Expected int16 values for this chunk
        expected_int16 = packet_size_int16 * blocks_per_chunk
        
        if len(temp) != expected_int16:
            # Don't spam warnings, just skip
            return None
        
        # Reshape into (packet_size_int16, blocks_per_chunk) - Fortran order
        data = temp.reshape(packet_size_int16, blocks_per_chunk, order="F")
        
        # Convert byte pointers to int16 pointers
        pointers_int16 = [p // 2 for p in pointers]
        
        # Calculate samples for this chunk
        chunk_time = blocks_per_chunk * 0.002  # seconds
        aux_samples_per_chunk = int(aux_fsamp_val * chunk_time)
        
        # Parse EMG data for each active input
        emg_data_dict = {}
        
        for i in range(10):
            input_num = i + 1
            inp = self._config.inputs.get(f"IN{input_num}")
            
            if inp and inp.is_enabled and inp.num_channels > 0:
                start_ptr = pointers_int16[i]
                end_ptr = pointers_int16[i + 1]
                
                if end_ptr > start_ptr:
                    input_data = data[start_ptr:end_ptr, :]
                    
                    fsamp_val = self.FSAMP_VALUES[inp.sampling_rate]
                    num_ch = inp.num_channels
                    samples_per_chunk = int(fsamp_val * chunk_time)
                    
                    flat = input_data.reshape(1, -1, order="F")
                    sig_in = flat.reshape(num_ch, samples_per_chunk, order="F").astype(np.int32)
                    emg_data_dict[input_num] = sig_in * self.EMG_GAIN_FACTOR
        
        # Parse AUX data (16 channels always present)
        aux_samples_per_2ms = aux_fsamp_val // 500
        aux_int16_per_2ms = 16 * aux_samples_per_2ms
        accessory_int16_per_2ms = 128
        
        aux_start_int16 = pointers_int16[10] if len(pointers_int16) > 10 else 0
        aux_end_int16 = aux_start_int16 + aux_int16_per_2ms
        
        if aux_end_int16 <= packet_size_int16 - accessory_int16_per_2ms:
            aux_data_raw = data[aux_start_int16:aux_end_int16, :]
            aux_flat = aux_data_raw.reshape(1, -1, order="F")
            sig_aux = aux_flat.reshape(16, aux_samples_per_chunk, order="F").astype(np.float32)
            sig_aux = sig_aux * self.AUX_GAIN_FACTOR
        else:
            sig_aux = np.zeros((16, aux_samples_per_chunk), dtype=np.float32)
        
        # Organize EMG data by channel ID order
        emg_samples_list = []
        active_channels = self.get_active_channels()
        
        for ch_id in active_channels["emg"]:
            parts = ch_id.split("_")
            input_num = int(parts[0].replace("IN", ""))
            ch_num = int(parts[1].replace("CH", ""))
            
            if input_num in emg_data_dict:
                inp = self._config.inputs.get(f"IN{input_num}")
                if inp and ch_num <= inp.num_channels:
                    emg_samples_list.append(emg_data_dict[input_num][ch_num - 1, :])
        
        # Organize AUX data - ALL 16 channels, we'll select later
        aux_samples_list = []
        for ch_id in active_channels["aux"]:
            if ch_id.startswith("AUX"):
                aux_num = int(ch_id.replace("AUX", ""))
                if 1 <= aux_num <= 4:
                    aux_samples_list.append(sig_aux[aux_num - 1, :])
            elif ch_id.startswith("LC"):
                lc_num = int(ch_id.replace("LC", ""))
                if 1 <= lc_num <= 2:
                    aux_samples_list.append(sig_aux[4 + lc_num - 1, :])
            elif ch_id.startswith("EXT"):
                ext_num = int(ch_id.replace("EXT", ""))
                if 1 <= ext_num <= 10:
                    aux_samples_list.append(sig_aux[6 + ext_num - 1, :])
        
        # Convert to numpy arrays
        if emg_samples_list:
            emg_samples = np.array(emg_samples_list)
        else:
            emg_samples = np.zeros((0, aux_samples_per_chunk))
        
        if aux_samples_list:
            aux_samples = np.array(aux_samples_list)
        else:
            aux_samples = np.zeros((0, aux_samples_per_chunk))
        
        # Generate timestamps
        n_samples = aux_samples.shape[1] if aux_samples.size > 0 else (
            emg_samples.shape[1] if emg_samples.size > 0 else aux_samples_per_chunk
        )
        sample_period = 1.0 / aux_fsamp_val
        timestamps = np.arange(sample_counter, sample_counter + n_samples) * sample_period
        
        return StreamData(
            emg_samples=emg_samples,
            aux_samples=aux_samples,
            timestamps=timestamps,
            accessory_data=None  # Skip accessory for performance
        )
    
    # -------------------------------------------------------------------------
    # Trigger Control
    # -------------------------------------------------------------------------
    
    def set_trigger_high(self) -> None:
        """Set trigger output high"""
        if not self._connected:
            raise RuntimeError("Not connected")
        self._send_command(self.CMD_TRIG_HIGH)
    
    def set_trigger_low(self) -> None:
        """Set trigger output low"""
        if not self._connected:
            raise RuntimeError("Not connected")
        self._send_command(self.CMD_TRIG_LOW)
    
    # -------------------------------------------------------------------------
    # Metadata
    # -------------------------------------------------------------------------
    
    def get_settings_for_metadata(self) -> dict:
        """Get complete device settings for recording metadata"""
        if not self._connected:
            return {}
        
        info = self.get_device_info()
        
        return {
            "device_serial": info.serial_number,
            "firmware_version": info.firmware_version,
            "battery_level": info.battery_level,
            "configuration": self._config.to_dict() if self._config else {},
            "packet_info": calculate_packet_info(self._config) if self._config else {}
        }