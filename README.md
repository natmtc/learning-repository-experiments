# EMG Bar Task Application

🚧 **UNDER CONSTRUCTION** 🚧

A desktop application for EMG recording and force-feedback tasks using the OT Bioelettronica Novecento+ amplifier.

## Features

- Real-time EMG and force sensor visualization
- Piano key display for multi-finger tasks
- Progress bar during hold phases
- Automatic data recording (HDF5 format)
- Export results to CSV
- Mock device mode for testing without hardware

## Quick Start

### Installation

```bash
pip install -r requirements.txt
```

### Run

```bash
# With mock device (no hardware needed)
python main.py --mock

# With real hardware
python main.py
```

## Bar Task

1. Load sample CSV or create custom finger combinations
2. Click "Start Task"
3. Follow visual feedback (green = in target, red = out)
4. Progress bar shows hold duration
5. Export results to CSV

## Files Recorded

- **EMG + Force data**: `data/[subject]/bartask_[timestamp].hdf5`
- **Results table**: Export via "📊 Export Results" button

---

🚧 **This project is under active development** 🚧

More documentation coming soon!