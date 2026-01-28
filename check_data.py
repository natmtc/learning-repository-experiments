import h5py
import numpy as np
import matplotlib.pyplot as plt
import json
from tkinter import Tk, filedialog


def load_and_normalize_aux(time_window=(0, 45), plot_aux=True, plot_emg=False):
    """
    Open dialogs to select .h5 and .json files (metadata),
    then load aux data, apply calibration offsets and MVCs,
    and optionally plot EMG channels.

    Parameters:
        time_window (tuple): (start_time, end_time) in seconds
        plot_aux (bool): whether to plot the AUX (force) data
        plot_emg (bool): whether to plot the EMG channels (first 64)

    Returns:
        t_window (np.ndarray): timestamps in the selected window
        aux_normalized (np.ndarray): processed aux data, shape (channels, samples)
        channel_names (list): list of AUX channel names
    """

    # Hide main Tkinter window
    root = Tk()
    root.withdraw()

    # --- Choose files ---
    h5_path = filedialog.askopenfilename(
        title="Select HDF5 file", filetypes=[("HDF5 files", "*.h5")]
    )
    if not h5_path:
        print("No HDF5 file selected. Exiting.")
        return None, None, None

    # Auto-find matching metadata file
    # HDF5: "Trapezoid_A1-A2_20260113_100553.h5"
    # JSON: "Trapezoid_A1-A2_20260113_100553_metadata.json"
    from pathlib import Path
    h5_file = Path(h5_path)
    json_path = h5_file.parent / f"{h5_file.stem}_metadata.json"
    
    if not json_path.exists():
        print(f"WARNING: Could not find matching metadata file: {json_path}")
        print("Please select metadata file manually...")
        json_path_str = filedialog.askopenfilename(
            title="Select Metadata JSON file (*_metadata.json)", 
            filetypes=[("JSON files", "*.json")]
        )
        if not json_path_str:
            print("No JSON file selected. Exiting.")
            return None, None, None
        json_path = Path(json_path_str)
    else:
        print(f"Auto-found metadata file: {json_path.name}")
    
    json_path = str(json_path)  # Convert back to string for file opening

    # --- Load metadata ---
    with open(json_path, "r") as f:
        metadata = json.load(f)

    print(f"Loaded metadata for subject: {metadata.get('subject_id', 'unknown')}")
    print(f"Task type: {metadata.get('task_type', 'unknown')}")
    
    # --- Load data from HDF5 ---
    with h5py.File(h5_path, "r") as f:
        # Load AUX data
        aux_dataset = f["aux/data"]
        n_aux = aux_dataset.shape[0]
        channel_names = [f"AUX{i+1}" for i in range(n_aux)]
        aux = aux_dataset[:]
        
        # Load EMG data if needed for plotting
        emg = None
        n_emg = 0
        if plot_emg and "emg/data" in f:
            emg_dataset = f["emg/data"]
            emg = emg_dataset[:]
            n_emg = emg.shape[0]
            print(f"Loaded {n_emg} EMG channels")
        
        # Load timestamps
        t = f["timestamps"][:]

    print(f"Loaded {n_aux} AUX channels, {len(t)} samples")
    print(f"Time range: {t[0]:.2f}s to {t[-1]:.2f}s")

    # --- Extract calibration from metadata ---
    extra_params = metadata.get("extra_params", {})
    
    # Get offsets and MVCs from metadata
    channel_offset_values = extra_params.get("channel_offset_values", {})
    channel_mvc_values = extra_params.get("channel_mvc_values", {})
    
    if not channel_offset_values or not channel_mvc_values:
        print("WARNING: No calibration data found in metadata!")
        print("Using default values (offset=0, MVC=1)")
        channel_offset_values = {ch: 0.0 for ch in channel_names}
        channel_mvc_values = {ch: 1.0 for ch in channel_names}
    
    # --- Mask time window ---
    start_time, end_time = time_window
    mask = (t >= start_time) & (t <= end_time)
    t_window = t[mask]
    aux_window = aux[:, mask]
    
    if aux_window.size == 0:
        print(f"WARNING: No data in time window {start_time}s-{end_time}s")
        return None, None, None

    print(f"Time window {start_time}s-{end_time}s: {aux_window.shape[1]} samples")

    # --- Apply offsets ---
    offsets = np.array([channel_offset_values.get(ch, 0.0) for ch in channel_names], dtype=float)
    print(f"Offsets: {offsets}")
    aux_corrected = aux_window - offsets[:, None]

    # --- Apply MVC normalization ---
    mvcs = np.array([channel_mvc_values.get(ch, 1.0) for ch in channel_names], dtype=float)
    print(f"MVCs: {mvcs}")
    aux_normalized = aux_corrected / mvcs[:, None]

    # --- Plot AUX data ---
    if plot_aux:
        # Shift each channel so min=0 for better overlay
        aux_shifted = aux_normalized - aux_normalized.min(axis=1, keepdims=True)

        plt.figure(figsize=(12, 5))
        for i, ch_name in enumerate(channel_names):
            plt.plot(t_window, aux_shifted[i], label=ch_name, linewidth=1.5)
        plt.xlabel("Time (s)", fontsize=12)
        plt.ylabel("Normalized Force (%MVC)", fontsize=12)
        plt.title(f"AUX Channels ({start_time}s-{end_time}s) - Offsets & MVC Applied", fontsize=14)
        plt.legend()
        plt.grid(alpha=0.3)
        plt.tight_layout()
        plt.show()

    # --- Plot EMG data (grid-based with channel configuration) ---
    if plot_emg and emg is not None:
        from tkinter import simpledialog
        
        # Ask user for channel configuration
        channel_config_str = simpledialog.askstring(
            "EMG Channel Configuration",
            "Enter number of channels per input (e.g., '64 96 96' for IN1=64ch, IN2=96ch, IN3=96ch):"
        )
        
        if not channel_config_str:
            print("No channel configuration provided. Skipping EMG plot.")
        else:
            # Parse channel configuration
            try:
                channels_per_input = [int(x) for x in channel_config_str.split()]
                total_channels_to_plot = sum(channels_per_input)
                
                if total_channels_to_plot > n_emg:
                    print(f"WARNING: Requested {total_channels_to_plot} channels but only {n_emg} available")
                    print(f"Will plot first {n_emg} channels")
                
                emg_window = emg[:, mask]
                
                # Print first EMG channel data
                print("\n" + "="*60)
                print("FIRST EMG CHANNEL DATA (Channel 0)")
                print("="*60)
                print(f"Shape: {emg_window[0].shape}")
                print(f"Min: {emg_window[0].min():.6f}")
                print(f"Max: {emg_window[0].max():.6f}")
                print(f"Mean: {emg_window[0].mean():.6f}")
                print(f"Std: {emg_window[0].std():.6f}")
                print(f"\nFirst 20 samples:")
                print(emg_window[0][:20])
                print(f"\nLast 20 samples:")
                print(emg_window[0][-20:])
                print("="*60 + "\n")
                
                # Create separate plot for each input
                n_inputs = len(channels_per_input)
                channel_start = 0
                
                for input_idx, n_channels in enumerate(channels_per_input):
                    channel_end = min(channel_start + n_channels, n_emg)
                    actual_channels = channel_end - channel_start
                    
                    if actual_channels <= 0:
                        break
                    
                    # Split into blocks of 32 channels
                    block_size = 32
                    n_blocks = (actual_channels + block_size - 1) // block_size  # Ceiling division
                    
                    for block_idx in range(n_blocks):
                        block_start = channel_start + block_idx * block_size
                        block_end = min(block_start + block_size, channel_end)
                        block_channels = block_end - block_start
                        
                        # Create figure for this block
                        fig, ax = plt.subplots(figsize=(14, 8))
                        
                        # Calculate individual amplitudes for each channel
                        channel_amplitudes = []
                        for ch_idx in range(block_start, block_end):
                            ch_data = emg_window[ch_idx]
                            ch_range = ch_data.max() - ch_data.min()
                            channel_amplitudes.append(ch_range)
                        
                        # Use median amplitude to determine spacing (more robust than max)
                        median_amplitude = np.median(channel_amplitudes) if channel_amplitudes else 1.0
                        if median_amplitude > 0:
                            spacing = median_amplitude * 0.5  # 50% of median amplitude for spacing
                        else:
                            spacing = 0.5
                        
                        # Plot each channel in this block - NORMALIZE EACH INDIVIDUALLY
                        for idx, ch_idx in enumerate(range(block_start, block_end)):
                            ch_data = emg_window[ch_idx]
                            ch_min, ch_max = ch_data.min(), ch_data.max()
                            ch_range = ch_max - ch_min if (ch_max - ch_min) > 0 else 1.0
                            
                            # Normalize to 0-1 range, then scale to spacing
                            normalized = (ch_data - ch_min) / ch_range * spacing * 1.0  # Use 100% of spacing
                            
                            # Offset by channel position in block
                            offset_data = normalized + idx * spacing
                            
                            ax.plot(t_window, offset_data, linewidth=0.3, color='#4a9eff', alpha=0.8)
                        
                        # Configure axes
                        ax.set_xlabel("Time (s)", fontsize=12)
                        ax.set_ylabel("Channel Number", fontsize=12)
                        
                        # Title with input and block info
                        global_ch_start = block_start - channel_start + 1  # 1-indexed global channel
                        global_ch_end = block_end - channel_start
                        ax.set_title(
                            f"IN{input_idx + 1} - Block {block_idx + 1}/{n_blocks} - Channels {global_ch_start}-{global_ch_end} ({start_time}s-{end_time}s)", 
                            fontsize=14
                        )
                        
                        # Set Y-axis with custom ticks at channel positions
                        channel_positions = [ch * spacing for ch in range(block_channels)]
                        ax.set_yticks(channel_positions)
                        ax.set_yticklabels(range(global_ch_start, global_ch_end + 1))
                        
                        # Set tight Y limits with small margins
                        y_min = -spacing * 0.1
                        y_max = (block_channels - 1) * spacing + spacing * 1.1
                        ax.set_ylim([y_min, y_max])
                        
                        ax.grid(alpha=0.3, axis='x')
                        ax.set_xlim([t_window[0], t_window[-1]])
                        
                        plt.tight_layout()
                        plt.show()
                    
                    channel_start = channel_end
                    
            except ValueError:
                print("Invalid channel configuration format. Use space-separated integers (e.g., '64 96 96')")

    return t_window, aux_normalized, channel_names


# Entry point
if __name__ == "__main__":
    # Plot both AUX and EMG for entire recording
    load_and_normalize_aux(time_window=(0, 45), plot_aux=True, plot_emg=True)


#### OLD CODE TO CHECK INDIVIDUAL FILES/PLOT RAW DATA


# Check files

# # .hp5 file (containing data)

# with h5py.File("data/a/Trapezoid_A1-A2_IN1_20260113_145108.h5", "r") as f:

#     def print_tree(name, obj):
#         print(name, obj)

#     f.visititems(print_tree)

# .json file (containing MVC/offset calibrations)

# import json
# import numpy as np

# with open("data/1/1_calibration.json", "r") as f:
#     calib = json.load(f)

# offsets_dict = calib["offsets"]

# channel_names = ["AUX1", "AUX2", "AUX3", "AUX4"]

# offsets = np.array(
#     [offsets_dict[ch] for ch in channel_names],
#     dtype=float
# )

# print(offsets.shape)


## Plot Raw AUX traces

# with h5py.File("data/1/dataname.h5", "r") as f:
#     aux = f["aux/data"][:]      # (2, N)
#     t = f["timestamps"][:]      # (N,)

# # Mask time window
# mask = (t >= 5.0) & (t <= 30.0)
# t_window = t[mask]
# aux_window = aux[:, mask]

# # Shift each channel so min == 0 (AFTER masking)
# aux_shifted = aux_window - aux_window.min(axis=1, keepdims=True)

# # Plot overlaid
# plt.figure(figsize=(10, 4))
# for ch in range(aux_shifted.shape[0]):
#     plt.plot(t_window, aux_shifted[ch], label=f"Aux channel {ch+1}")

# plt.xlabel("Time (s)")
# plt.ylabel("Shifted aux value")
# plt.title("Aux channels overlaid (min = 0 per channel)")
# plt.legend()
# plt.tight_layout()
# plt.show()