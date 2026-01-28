"""
Main Window - Primary application window with tabbed interface.
"""

from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTabWidget,
    QStatusBar,
    QMenuBar,
    QMenu,
    QToolBar,
    QLabel,
    QMessageBox,
    QFileDialog,
    QApplication,
)
from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QAction, QFont, QIcon

from typing import Optional
import sys

from gui.config_tab import ConfigurationTab
from gui.calibration_tab import CalibrationTab
from gui.trapezoid_tab import TrapezoidTab
from gui.bartask_tab import BarTaskTab
from gui.style import apply_style, COLORS
from data.managers import CalibrationManager, TrialLogger


class MainWindow(QMainWindow):
    """
    Main application window for Novecento EMG Recording & Force Feedback.
    """

    def __init__(self):
        super().__init__()

        self.setWindowTitle("Novecento EMG Recording & Force Feedback")
        self.setMinimumSize(1200, 800)

        # Initialize shared managers - will be configured when subject is set
        self._data_folder = "./data"
        self._calibration_manager: Optional[CalibrationManager] = CalibrationManager(
            self._data_folder
        )
        self._trial_logger = TrialLogger(self._data_folder)

        self._setup_ui()
        self._setup_menu()
        self._setup_statusbar()
        self._connect_signals()

        # Apply dark theme
        self._apply_theme()

        # Pass calibration manager to all tabs immediately
        self._calibration_tab._calibration_manager = self._calibration_manager
        self._trapezoid_tab.set_calibration_manager(self._calibration_manager)
        self._trapezoid_tab.set_trial_logger(self._trial_logger)
        self._trapezoid_tab.set_config_tab(
            self._config_tab
        )  # Pass config tab reference
        self._bartask_tab.set_calibration_manager(self._calibration_manager)
        self._bartask_tab.set_trial_logger(self._trial_logger)

    def _setup_ui(self):
        """Setup the main UI components"""
        # Central widget with tab interface
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(5, 5, 5, 5)

        # Tab widget
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)

        # Create tabs
        self._config_tab = ConfigurationTab()
        self._calibration_tab = CalibrationTab()
        self._trapezoid_tab = TrapezoidTab()
        self._bartask_tab = BarTaskTab()

        # Add tabs
        self._tabs.addTab(self._config_tab, "Configuration")
        self._tabs.addTab(self._calibration_tab, "Calibration")
        self._tabs.addTab(self._trapezoid_tab, "Trapezoid Protocol")
        self._tabs.addTab(self._bartask_tab, "Bar Task")

        main_layout.addWidget(self._tabs)

    def _setup_menu(self):
        """Setup menu bar"""
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("&File")

        new_session_action = QAction("New Session", self)
        new_session_action.setShortcut("Ctrl+N")
        new_session_action.triggered.connect(self._new_session)
        file_menu.addAction(new_session_action)

        file_menu.addSeparator()

        export_action = QAction("Export Data...", self)
        export_action.setShortcut("Ctrl+E")
        export_action.triggered.connect(self._export_data)
        file_menu.addAction(export_action)

        file_menu.addSeparator()

        exit_action = QAction("Exit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # Device menu
        device_menu = menubar.addMenu("&Device")

        connect_action = QAction("Connect", self)
        connect_action.triggered.connect(self._config_tab._connect)
        device_menu.addAction(connect_action)

        disconnect_action = QAction("Disconnect", self)
        disconnect_action.triggered.connect(self._config_tab._disconnect)
        device_menu.addAction(disconnect_action)

        device_menu.addSeparator()

        visualise_action = QAction("Toggle Visualisation", self)
        visualise_action.triggered.connect(self._config_tab._toggle_visualisation)
        device_menu.addAction(visualise_action)

        # Protocol menu
        protocol_menu = menubar.addMenu("&Protocol")

        start_trapezoid_action = QAction("Start Trapezoid", self)
        start_trapezoid_action.triggered.connect(self._start_trapezoid)
        protocol_menu.addAction(start_trapezoid_action)

        start_bartask_action = QAction("Start Bar Task", self)
        start_bartask_action.triggered.connect(self._start_bartask)
        protocol_menu.addAction(start_bartask_action)

        # Help menu
        help_menu = menubar.addMenu("&Help")

        about_action = QAction("About", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

        docs_action = QAction("Documentation", self)
        docs_action.triggered.connect(self._show_docs)
        help_menu.addAction(docs_action)

    def _setup_statusbar(self):
        """Setup status bar"""
        self._statusbar = QStatusBar()
        self.setStatusBar(self._statusbar)

        # Connection status
        self._conn_label = QLabel("Disconnected")
        self._conn_label.setStyleSheet("color: #ff6600;")
        self._statusbar.addWidget(self._conn_label)

        # Spacer
        self._statusbar.addWidget(QLabel(""), stretch=1)

        # Subject ID
        self._subject_label = QLabel(
            "Subject: ----------------------------------------"
        )
        self._statusbar.addPermanentWidget(self._subject_label)

    def _connect_signals(self):
        """Connect signals between components"""
        # Connection signals
        self._config_tab.connectionChanged.connect(self._on_connection_changed)
        self._config_tab.channelsChanged.connect(self._on_channels_changed)

        # Data folder and subject signals
        self._config_tab.dataFolderChanged.connect(self._on_data_folder_changed)
        self._config_tab.subjectChanged.connect(self._on_subject_changed)

        # Global display refresh rate
        self._config_tab.displayRefreshChanged.connect(self._on_display_refresh_changed)

        # Calibration signals
        self._calibration_tab.calibrationUpdated.connect(self._on_calibration_updated)

        # Tab change
        self._tabs.currentChanged.connect(self._on_tab_changed)

    def _apply_theme(self):
        """Apply dark theme to application"""
        apply_style(self)

    @Slot(bool)
    def _on_connection_changed(self, connected: bool):
        """Handle connection status change"""
        if connected:
            self._conn_label.setText("Connected")
            self._conn_label.setStyleSheet("color: #00ff00;")

            # Pass client to other tabs
            client = self._config_tab.get_client()
            if client:
                self._calibration_tab.set_client(client)
                self._calibration_tab.set_config_tab(
                    self._config_tab
                )  # NEW: Pass config_tab reference
                self._trapezoid_tab.set_client(client)
                self._trapezoid_tab.set_client(client)
                self._bartask_tab.set_client(client)
        else:
            self._conn_label.setText("Disconnected")
            self._conn_label.setStyleSheet("color: #ff6600;")

    @Slot(list, list)
    def _on_channels_changed(self, emg_channels, aux_channels):
        """Handle channel selection change"""
        self._calibration_tab.set_aux_channels(aux_channels)
        self._trapezoid_tab.set_aux_channels(aux_channels)
        self._trapezoid_tab.set_aux_channels(aux_channels)
        self._bartask_tab.set_aux_channels(aux_channels)

        # Setup calibration manager
        subject_id = self._config_tab.get_subject_id()
        if subject_id:
            self._setup_calibration(subject_id)

    @Slot()
    def _on_calibration_updated(self):
        """Handle calibration data update"""
        # Refresh calibration in protocol tabs
        if self._calibration_manager:
            self._trapezoid_tab.set_calibration_manager(self._calibration_manager)
            self._trapezoid_tab.set_calibration_manager(self._calibration_manager)
            self._bartask_tab.set_calibration_manager(self._calibration_manager)
            self._bartask_tab._check_calibration()

    @Slot(str)
    def _on_data_folder_changed(self, folder: str):
        """Handle data folder change"""
        self._data_folder = folder

        # Update all managers to use the new folder
        if self._calibration_manager:
            self._calibration_manager.set_storage_path(folder)

        if self._trial_logger:
            self._trial_logger.set_output_path(folder)

    @Slot(int)
    def _on_display_refresh_changed(self, rate_ms: int):
        """Handle global display refresh rate change - propagate to all tabs"""
        # Set refresh rate on all tabs that support it
        if hasattr(self._calibration_tab, "set_display_refresh_rate"):
            self._calibration_tab.set_display_refresh_rate(rate_ms)
        if hasattr(self._trapezoid_tab, "set_display_refresh_rate"):
            self._trapezoid_tab.set_display_refresh_rate(rate_ms)
        if hasattr(self._trapezoid_tab, "set_display_refresh_rate"):
            self._trapezoid_tab.set_display_refresh_rate(rate_ms)
        if hasattr(self._bartask_tab, "set_display_refresh_rate"):
            self._bartask_tab.set_display_refresh_rate(rate_ms)

    @Slot(str)
    def _on_subject_changed(self, subject_id: str):
        """Handle subject ID change"""
        self._subject_label.setText(f"Subject: {subject_id}")

        # Update calibration manager with new subject
        if self._calibration_manager:
            self._calibration_manager.set_subject(subject_id)

        # Update calibration tab
        self._calibration_tab.set_subject(subject_id)

        # Refresh protocol tabs
        self._on_calibration_updated()

    @Slot(int)
    def _on_tab_changed(self, index: int):
        """Handle tab change"""
        # Ensure subject is set
        subject_id = self._config_tab.get_subject_id()
        if subject_id and not self._calibration_manager:
            self._setup_calibration(subject_id)

    def _setup_calibration(self, subject_id: str):
        """Setup calibration manager for subject"""
        # Update the data folder from config
        self._data_folder = self._config_tab.get_data_folder()

        # Update the existing calibration manager (don't create new one)
        self._calibration_manager.set_storage_path(self._data_folder)
        self._calibration_manager.set_subject(subject_id)

        # Update calibration tab
        self._calibration_tab.set_subject(subject_id)
        self._calibration_tab._calibration_manager = self._calibration_manager

        # Update protocol tabs
        self._trapezoid_tab.set_calibration_manager(self._calibration_manager)
        self._trapezoid_tab.set_calibration_manager(self._calibration_manager)
        self._bartask_tab.set_calibration_manager(self._calibration_manager)

    def _new_session(self):
        """Start a new session"""
        reply = QMessageBox.question(
            self,
            "New Session",
            "Start a new session? This will reset the current configuration.",
            QMessageBox.Yes | QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            self._config_tab.set_subject_id("")
            self._subject_label.setText(
                "Subject: ----------------------------------------"
            )
            self._calibration_manager = None

    def _export_data(self):
        """Export data dialog"""
        QMessageBox.information(
            self,
            "Export",
            "Data is automatically saved to the configured data folder.\n\n"
            "Recording data: ./data/\n"
            "Calibration data: ./calibration/\n"
            "Trial results: ./trials/",
        )

    def _start_trapezoid(self):
        """Switch to trapezoid tab and start"""
        self._tabs.setCurrentWidget(self._trapezoid_tab)

    def _start_bartask(self):
        """Switch to bar task tab and start"""
        self._tabs.setCurrentWidget(self._bartask_tab)

    def _show_about(self):
        """Show about dialog"""
        QMessageBox.about(
            self,
            "About Novecento EMG",
            "<h2>Novecento EMG Recording & Force Feedback</h2>"
            "<p>Version 1.0</p>"
            "<p>A comprehensive application for EMG recording and "
            "force-feedback protocols using the OT Bioelettronica "
            "Novecento+ amplifier.</p>"
            "<p><b>Features:</b></p>"
            "<ul>"
            "<li>Multi-channel EMG and auxiliary recording</li>"
            "<li>MVC and offset calibration</li>"
            "<li>Trapezoid force-tracking protocol</li>"
            "<li>Multi-finger bar task protocol</li>"
            "</ul>",
        )

    def _show_docs(self):
        """Show documentation"""
        QMessageBox.information(
            self,
            "Documentation",
            "<h3>Quick Start Guide</h3>"
            "<ol>"
            "<li><b>Connect:</b> Select device and click Connect</li>"
            "<li><b>Configure:</b> Select channels and set recording options</li>"
            "<li><b>Calibrate:</b> Record offset (rest) and MVC for each channel</li>"
            "<li><b>Run Protocol:</b> Choose Trapezoid or Bar Task</li>"
            "</ol>"
            "<p>For detailed documentation, see the README file.</p>",
        )

    def closeEvent(self, event):
        """Handle window close"""
        # Disconnect from device
        client = self._config_tab.get_client()
        if client and client.is_connected:
            client.disconnect()

        event.accept()


def run_app():
    """Run the application"""
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Set application font
    font = QFont("Segoe UI", 9)
    app.setFont(font)

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(run_app())
