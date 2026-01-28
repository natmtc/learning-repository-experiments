# Novecento EMG Recording & Force Feedback Application

A professional desktop application for EMG recording and force-feedback protocols using the OT Bioelettronica Novecento+ bioelectrical signal amplifier.

## Overview

This application provides a complete solution for:
- **Multi-channel EMG recording** from up to 10 inputs (8-96 channels each)
- **Force sensor data acquisition** via 8 auxiliary channels  
- **Real-time visualization** with configurable display refresh rates
- **MVC and offset calibration** with persistent storage per subject
- **Force-feedback protocols** including trapezoid tracking and multi-finger bar tasks
- **Mock device support** for testing without hardware

## Key Features

### Device Communication
- Full implementation of Novecento+ Configuration Protocol v2.3
- TCP/IP communication (default: 169.254.1.10:23456)
- Automatic probe detection for IN1-IN10 inputs
- Real-time streaming at up to 8000 Hz

### Recording Capabilities  
- Configurable sampling rates: 500, 2000, 4000, 8000 Hz
- 16-bit or 24-bit resolution per input
- Adjustable preamp gain (x2, x4, x6, x8)
- High-pass filtering (cutoff = Fsamp/190)
- Data export to HDF5 or CSV formats

### Calibration System
- Per-channel MVC (Maximum Voluntary Contraction) measurement
- Offset (rest baseline) recording for all channels or individually  
- Subject-specific calibration storage
- Automatic calibration loading/saving

### Force Protocols
- **Trapezoid Protocol**: Force-tracking with trapezoidal target profiles
- **Bar Task Protocol**: Multi-finger force matching (piano task)
- Visual feedback with real-time performance indicators
- Trial logging with detailed result metrics

## Installation

### Requirements
- Python 3.8+
- PySide6 (Qt 6 for Python)
- NumPy
- h5py
- pyserial

### Setup

1. Create and activate a conda environment:
```bash
conda create -n novecento python=3.10
conda activate novecento
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

Or install manually:
```bash
pip install PySide6 numpy h5py pyserial
```

## Quick Start

### 1. Launch the Application
```bash
python main.py
```

For testing without hardware:
```bash
python main.py --mock
```

### 2. Connect to Device

**Configuration Tab:**
- Select "Mock Device (Testing)" or "Novecento+ (TCP)"
- For hardware: Enter IP address (default: 169.254.1.10:23456)
- Click "Connect"
- Application will auto-detect connected probes

### 3. Configure Device

**Click "Open Configuration...":**
- **Inputs (IN1-IN10):** Enable inputs with connected probes
  - Mode: Monopolar (standard), Impedance Check, or Test
  - Gain: x2, x4, x6, or x8 preamp gain
  - HPF: High-pass filter (recommended: ON)
  - Resolution: 16-bit (standard) or 24-bit (high precision)
  - Sampling Rate: 500, 2000, 4000, or 8000 Hz

- **AUX Channels:** Select force sensor channels (AUX1-8, LC1-2, EXT1-10)
  - All AUX channels share a common sampling rate
  - Default: 2000 Hz recommended

- **Display Settings:**
  - Refresh Rate: 50-200 ms (lower = smoother but more CPU)
  - Display History: How many seconds to show on screen

Click "Apply" to save configuration to device.

### 4. Calibrate Force Sensors

**Calibration Tab:**

For each force sensor channel:
1. **Record Offset** (Baseline):
   - Keep finger/hand completely relaxed
   - Click "Record Offset" (or "Record ALL Channel Offsets" for all at once)
   - Wait 5 seconds
   - Offset value saved automatically

2. **Record MVC** (Maximum Voluntary Contraction):
   - Apply maximum force for selected channel
   - Click "Record MVC"
   - Push as hard as possible for 5 seconds
   - MVC value saved automatically

Calibration data is stored per subject in `./calibration/` folder.

### 5. Record Data

**Configuration Tab:**
- Enter Subject ID
- Choose data folder (default: `./data/`)
- Select format: HDF5 (.h5) or CSV (.csv)
- Click "Start Recording"
- Click "Stop Recording" when done

### 6. Run Protocols

**Trapezoid Protocol Tab:**
- Select force channel
- Set target force (% MVC)
- Configure timing: rest, ramp, hold durations
- Click "Start Protocol"
- Follow on-screen visual feedback
- Green = in target, Red = out of target

**Bar Task Tab:**
- Load CSV file defining finger combinations
- Or use "Create Sample" to generate template
- Configure tolerance and timing
- Click "Start Task" then "Next Trial" for each trial
- Results saved automatically to `./trials/` folder

## Application Architecture

```
novecento_app/
├── main.py                     # Application entry point
├── requirements.txt            # Python dependencies
├── README.md                   # This file
│
├── clients/                    # Device communication layer
│   ├── base.py                 # Abstract client interface
│   ├── mock_client.py          # Simulated device for testing
│   └── hardware_client.py      # Real Novecento+ TCP/IP communication
│
├── core/                       # Core data models
│   └── novecento_config.py     # Configuration classes and protocol
│
├── data/                       # Data management
│   └── __init__.py             # DataRecorder, CalibrationManager, TrialLogger
│
├── protocols/                  # Force feedback protocols
│   └── __init__.py             # TrapezoidProtocol, BarTaskProtocol
│
└── gui/                        # User interface
    ├── main_window.py          # Main window with 4 tabs
    ├── config_tab.py           # Device connection & recording
    ├── config_dialog.py        # Detailed configuration popup
    ├── calibration_tab.py      # MVC/Offset calibration
    ├── trapezoid_tab.py        # Trapezoid force protocol
    ├── bartask_tab.py          # Multi-finger bar task
    ├── widgets.py              # Custom plot widgets
    └── style/
        └── __init__.py         # Dark theme styling
```

## Configuration Protocol

### Per-Input Configuration

Each of 10 inputs (IN1-IN10) has independent settings:

| Parameter | Options | Description |
|-----------|---------|-------------|
| Probe Type | 8, 16, 32, 40, 64, 96 ch | Automatically detected from hardware |
| Mode | Monopolar, Impedance, Test | Working mode |
| Gain | x2, x4, x6, x8 | Preamplifier gain |
| HPF | On/Off | High-pass filter (~10.5 Hz at 2000 Hz) |
| Resolution | 16-bit, 24-bit | ADC bit depth |
| Sample Rate | 500, 2000, 4000, 8000 Hz | Sampling frequency |

### Configuration File Format

Configurations saved as JSON:

```json
{
  "inputs": {
    "IN1": {
      "is_enabled": true,
      "probe_type": 5,
      "mode": 0,
      "gain": 1,
      "high_pass_filter": true,
      "high_resolution": false,
      "sampling_rate": 1
    }
  },
  "aux_channels": ["AUX1", "AUX2"],
  "aux_sampling_rate": 1,
  "display_refresh_ms": 50
}
```

## Data Files

### Recording Data
- **Location:** `./data/`
- **Formats:** HDF5 (.h5) or CSV (.csv)
- **Contents:** Raw EMG and AUX channel data with timestamps

### Calibration Data
- **Location:** `./calibration/`
- **Format:** JSON per subject: `{subject_id}_calibration.json`
- **Contents:** MVC and offset values for all calibrated channels

### Trial Results
- **Location:** `./trials/`
- **Format:** JSON files with detailed trial metrics
- **Contents:** Success/failure, time-to-target, hold duration, error statistics

## Bar Task CSV Format

Define multi-finger tasks with CSV files:

```csv
column_id,aux_channel,finger,direction,target_mvc_percent,hold_time_s
1,AUX1,thumb,ext,0,3
1,EXT2,thumb,flex,15,3
2,AUX2,index,ext,0,3
2,EXT3,index,flex,15,3
```

**Fields:**
- `column_id`: Groups channels for same finger (1-5)
- `aux_channel`: Channel name (AUX1-8, LC1-2, EXT1-10)
- `finger`: Finger name (thumb, index, middle, ring, pinkie)
- `direction`: "ext" (extension) or "flex" (flexion)
- `target_mvc_percent`: Target force (0 = no movement, >0 = target)
- `hold_time_s`: Required hold duration

## Hardware Protocol Details

Based on OT Bioelettronica Configuration Protocol v2.3:

### Communication
- **Interface:** TCP/IP socket
- **Default Address:** 169.254.1.10:23456
- **Data Timing:** 2ms blocks (500 Hz minimum interval)

### Command Structure
- **Simple Commands:** 2 bytes (command + CRC8)
- **Configuration Command:** 15 bytes
  - Byte 0: ACQ_SETT_A (acquisition start, AUX rate, IN9-10 enable)
  - Byte 1: ACQ_SETT_B (IN1-8 enable bits)
  - Bytes 2-3: Analog output settings
  - Bytes 4-13: Per-input configuration (IN1-IN10)
  - Byte 14: CRC8 checksum

### Data Packet Structure
- **EMG Data:** Variable size based on enabled inputs and sampling rates
- **AUX Data:** 16 channels (4 AUX + 2 LOAD CELL + 10 EXT) at configured rate
- **Accessory Data:** 256 bytes (counter, trigger, IMU)
- **Total:** Sum of above components per 2ms block

## Troubleshooting

### Connection Issues
- **Hardware:** Verify device is powered on, USB cable connected
- **Network:** For TCP, ensure IP is 169.254.x.x range (link-local)
- **Mock Device:** Always works - use for testing UI/functionality

### No Probes Detected
- Check physical probe connections to front panel
- Verify probe cables are fully seated
- Try disconnect/reconnect device

### Calibration Not Saving
- Ensure Subject ID is entered in Configuration tab
- Check folder permissions for `./calibration/`
- Verify disk space available

### Poor Protocol Performance
- Increase display refresh rate (Configuration dialog → Display Settings)
- Reduce number of active channels if CPU limited
- Check for background processes consuming resources

## API Example

```python
from clients import MockNovecentoClient
from core.novecento_config import NovecentoConfiguration, SamplingRate

# Create client
client = MockNovecentoClient()
client.connect("mock")

# Configure
config = NovecentoConfiguration.create_default()
config.inputs['IN1'].is_enabled = True
config.inputs['IN1'].sampling_rate = SamplingRate.HZ_2000
config.aux_channels = {'AUX1', 'AUX2'}
client.apply_configuration(config)

# Stream data
def callback(data):
    print(f"EMG shape: {data.emg_samples.shape}")
    print(f"AUX shape: {data.aux_samples.shape}")

client.start_streaming(callback)

# Stop
client.stop_streaming()
client.disconnect()
```

## Performance Notes

### Display Refresh Rate
- **50-75 ms:** Smooth real-time display (recommended)
- **100-200 ms:** Original OT code default (less CPU)
- Lower values = smoother but higher CPU usage

### Data Streaming
- Hardware client processes data in 50ms chunks (25 x 2ms blocks)
- Display updates independently via timer
- Recording is continuous regardless of display rate

### Resource Usage
- Typical CPU: 5-15% with default settings
- Memory: ~100-200 MB
- Disk: ~1 GB/hour for 64ch @ 2kHz (HDF5 format)

## Credits

- **Hardware:** OT Bioelettronica Novecento+ amplifier
- **Protocol:** Configuration Protocol v2.3 (October 2024)
- **Framework:** PySide6 (Qt for Python)

## License

This software is provided for research and educational purposes.

## Support

For issues or questions:
1. Check this README and troubleshooting section
2. Verify hardware connections and configuration
3. Test with Mock Device to isolate software vs hardware issues
4. Check console output for error messages"# learning-repository-experiments" 
