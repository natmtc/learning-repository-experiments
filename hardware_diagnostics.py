"""Hardware diagnostics tool for Novecento performance analysis."""

import time
import numpy as np
from collections import deque
from datetime import datetime
import json

class HardwareDiagnostics:
    """Monitor Novecento hardware performance and identify bottlenecks."""
    
    def __init__(self, client):
        self.client = client
        self.packet_times = deque(maxlen=1000)
        self.packet_gaps = deque(maxlen=1000)
        self.samples_per_packet = deque(maxlen=1000)
        self.start_time = None
        self.last_packet_time = None
        self.expected_interval = None
        
    def start_monitoring(self, sample_rate=2000, num_probes=8):
        """Start diagnostic monitoring."""
        self.expected_interval = 1.0 / sample_rate  # Expected time between samples
        self.start_time = time.time()
        self.last_packet_time = self.start_time
        self.packet_times.clear()
        self.packet_gaps.clear()
        self.samples_per_packet.clear()
        
    def record_packet(self, num_samples):
        """Record packet arrival statistics."""
        current_time = time.time()
        
        if self.last_packet_time is not None:
            gap = current_time - self.last_packet_time
            self.packet_gaps.append(gap)
        
        self.packet_times.append(current_time - self.start_time)
        self.samples_per_packet.append(num_samples)
        self.last_packet_time = current_time
        
    def get_report(self):
        """Generate diagnostic report."""
        if len(self.packet_gaps) == 0:
            return {"error": "No data collected"}
        
        gaps = np.array(self.packet_gaps)
        samples = np.array(self.samples_per_packet)
        
        # Calculate statistics
        mean_gap = np.mean(gaps)
        std_gap = np.std(gaps)
        max_gap = np.max(gaps)
        min_gap = np.min(gaps)
        
        # Identify problematic gaps (>2x expected)
        expected_packet_interval = 0.005  # Assuming ~200Hz packet rate
        long_gaps = gaps[gaps > expected_packet_interval * 2]
        gap_outlier_pct = len(long_gaps) / len(gaps) * 100
        
        # Sample statistics
        mean_samples = np.mean(samples)
        std_samples = np.std(samples)
        
        # Calculate expected vs actual sample rate
        total_time = self.packet_times[-1] - self.packet_times[0] if len(self.packet_times) > 1 else 0
        total_samples = np.sum(samples)
        actual_rate = total_samples / total_time if total_time > 0 else 0
        
        report = {
            "packet_statistics": {
                "total_packets": len(self.packet_gaps),
                "mean_gap_ms": mean_gap * 1000,
                "std_gap_ms": std_gap * 1000,
                "max_gap_ms": max_gap * 1000,
                "min_gap_ms": min_gap * 1000,
                "gap_outliers_pct": gap_outlier_pct,
                "num_long_gaps": len(long_gaps)
            },
            "sample_statistics": {
                "total_samples": int(total_samples),
                "mean_samples_per_packet": mean_samples,
                "std_samples_per_packet": std_samples,
                "actual_sample_rate_hz": actual_rate,
                "expected_rate_hz": 2000
            },
            "loss_analysis": {
                "sample_rate_deficit_pct": (1 - actual_rate/2000) * 100 if actual_rate > 0 else 100,
                "is_consistent": std_gap < mean_gap * 0.5,  # Low variance = consistent
                "has_long_stalls": max_gap > expected_packet_interval * 5
            },
            "diagnosis": self._diagnose(gaps, actual_rate)
        }
        
        return report
    
    def _diagnose(self, gaps, actual_rate):
        """Provide diagnostic interpretation."""
        issues = []
        
        # Check for consistent undersampling
        if actual_rate < 1900:  # >5% loss
            issues.append("CRITICAL: Significant sample loss detected")
        
        # Check for intermittent stalls
        max_gap = np.max(gaps)
        mean_gap = np.mean(gaps)
        if max_gap > mean_gap * 10:
            issues.append("WARNING: Intermittent long stalls detected (USB/buffer issue?)")
        
        # Check for consistent timing
        std_gap = np.std(gaps)
        if std_gap > mean_gap * 0.5:
            issues.append("WARNING: Inconsistent packet timing (CPU/scheduling issue?)")
        
        # Check packet rate
        if mean_gap > 0.006:  # Should be ~5ms for 200Hz packet rate
            issues.append("WARNING: Slow packet rate (hardware can't keep up?)")
        
        if not issues:
            issues.append("OK: Hardware appears to be performing within spec")
        
        return issues


def run_diagnostic_test(client, duration=60, num_probes=8):
    """Run a diagnostic test session."""
    print(f"\n{'='*60}")
    print("NOVECENTO HARDWARE DIAGNOSTICS")
    print(f"{'='*60}")
    print(f"Test duration: {duration}s")
    print(f"Number of probes: {num_probes}")
    print(f"Expected samples per channel: {duration * 2000}")
    print(f"{'='*60}\n")
    
    diagnostics = HardwareDiagnostics(client)
    diagnostics.start_monitoring(sample_rate=2000, num_probes=num_probes)
    
    # Start streaming
    print("Starting data stream...")
    
    # Define callback to capture data
    def data_callback(stream_data):
        nonlocal sample_count
        # Count samples from either EMG or AUX (both have same sample count)
        if stream_data.aux_samples.size > 0:
            num_samples = stream_data.aux_samples.shape[1]
        elif stream_data.emg_samples.size > 0:
            num_samples = stream_data.emg_samples.shape[1]
        else:
            return
        
        sample_count += num_samples
        diagnostics.record_packet(num_samples)
    
    client.start_streaming(data_callback)
    
    start_time = time.time()
    sample_count = 0
    last_print = 0
    
    try:
        while time.time() - start_time < duration:
            elapsed = time.time() - start_time
            
            # Progress update every 5 seconds
            if int(elapsed) - last_print >= 5:
                expected = int(elapsed * 2000)
                loss_pct = (1 - sample_count/expected) * 100 if expected > 0 else 0
                print(f"[{elapsed:.1f}s] Samples: {sample_count}/{expected} ({loss_pct:.1f}% loss)")
                last_print = int(elapsed)
            
            time.sleep(0.1)
            
    finally:
        client.stop_streaming()
        print("\nData stream stopped.")
    
    # Generate report
    report = diagnostics.get_report()
    
    print(f"\n{'='*60}")
    print("DIAGNOSTIC REPORT")
    print(f"{'='*60}\n")
    
    print("PACKET STATISTICS:")
    for key, value in report['packet_statistics'].items():
        print(f"  {key}: {value:.2f}" if isinstance(value, float) else f"  {key}: {value}")
    
    print("\nSAMPLE STATISTICS:")
    for key, value in report['sample_statistics'].items():
        print(f"  {key}: {value:.2f}" if isinstance(value, float) else f"  {key}: {value}")
    
    print("\nLOSS ANALYSIS:")
    for key, value in report['loss_analysis'].items():
        print(f"  {key}: {value:.2f}" if isinstance(value, float) else f"  {key}: {value}")
    
    print("\nDIAGNOSIS:")
    for issue in report['diagnosis']:
        print(f"  • {issue}")
    
    print(f"\n{'='*60}\n")
    
    # Save report to file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"novecento_diagnostics_{timestamp}.json"
    
    # Convert numpy bools to Python bools for JSON serialization
    def convert_for_json(obj):
        if isinstance(obj, np.bool_):
            return bool(obj)
        elif isinstance(obj, dict):
            return {k: convert_for_json(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [convert_for_json(v) for v in obj]
        return obj
    
    report_json = convert_for_json(report)
    
    with open(filename, 'w') as f:
        json.dump(report_json, f, indent=2)
    print(f"Full report saved to: {filename}")
    
    return report


if __name__ == "__main__":
    from clients.hardware_client import HardwareNovecentoClient
    
    # Run diagnostic
    client = HardwareNovecentoClient()
    if client.connect():
        # Configure to actually use the EMG channels
        config = client.get_configuration()
        
        # Enable first 8 inputs with their detected probe types
        for i in range(1, 9):
            input_name = f"IN{i}"
            if input_name in config.inputs:
                config.inputs[input_name].is_enabled = True
        
        # Add some AUX channels
        config.aux_channels = {"LC1", "LC2", "AUX1", "AUX2"}
        
        client.apply_configuration(config)
        
        print(f"\nConfigured channels:")
        active = client.get_active_channels()
        print(f"  EMG: {len(active['emg'])} channels")
        print(f"  AUX: {len(active['aux'])} channels\n")
        
        run_diagnostic_test(client, duration=60, num_probes=8)
        client.disconnect()