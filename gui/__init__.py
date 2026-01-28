"""
GUI Module for Novecento EMG Application
"""

# Avoid circular imports - only import when needed
__all__ = [
    'MainWindow',
    'ConfigurationTab', 
    'CalibrationTab',
    'TrapezoidTab',
    'BarTaskTab'
]

def get_main_window():
    from gui.main_window import MainWindow
    return MainWindow

def get_config_tab():
    from gui.config_tab import ConfigurationTab
    return ConfigurationTab

def get_calibration_tab():
    from gui.calibration_tab import CalibrationTab
    return CalibrationTab

def get_trapezoid_tab():
    from gui.trapezoid_tab import TrapezoidTab
    return TrapezoidTab

def get_bartask_tab():
    from gui.bartask_tab import BarTaskTab
    return BarTaskTab